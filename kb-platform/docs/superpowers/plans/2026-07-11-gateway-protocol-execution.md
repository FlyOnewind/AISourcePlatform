# Gateway and Protocol Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace stub capability execution with a Schema-enforcing, resilient Gateway and real HTTP, MCP, gRPC, and A2A adapters.

**Architecture:** FastAPI remains the control plane. `GatewayService` executes an immutable capability version through a fixed validation and policy pipeline. Redis holds distributed rate, idempotency, and breaker state; PostgreSQL holds endpoints and invocation records; protocol adapters contain transport-specific behavior behind one interface.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, Alembic, Redis, jsonschema Draft 2020-12, httpx, MCP Python SDK v1, grpc.aio, A2A Python SDK v1, pytest.

## Global Constraints

- Pin `mcp>=1.27,<2`; do not adopt the v2 prerelease.
- Use only MCP Streamable HTTP and legacy SSE; never spawn stdio processes.
- Use gRPC Reflection first and descriptor sets as fallback.
- All external targets pass SSRF validation and use governed Secret references.
- Only explicitly idempotent capabilities can be retried automatically.
- No production startup path may rely on `Base.metadata.create_all` for migration.
- Every production behavior starts with a failing test.

---

## File Map

- Create `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_gateway_foundations.py`: migrations.
- Create `app/gateway/contracts.py`: adapter and Gateway value types.
- Create `app/gateway/schema_validation.py`: Draft 2020-12 compilation and validation.
- Create `app/gateway/stability.py`: rate, idempotency, circuit, and bulkhead services.
- Create `app/gateway/routing.py`: endpoint eligibility, sticky weighted routing, fallback.
- Create `app/gateway/adapters/{base,http,mcp,grpc,a2a,hosted}.py`: real transports.
- Create `app/gateway/service.py`: deterministic invocation pipeline.
- Create `app/models/gateway.py`: endpoints, invocations, protocol configuration.
- Create `app/schemas/gateway.py`: API contracts.
- Create `app/api/v1/invocations.py`: submit/status/cancel API.
- Modify `app/api/v1/capabilities.py`: delegate calls to Gateway.
- Modify `app/main.py`, `app/models/__init__.py`, `app/core/config.py`, `pyproject.toml`.

### Task 1: Dependency and Alembic foundation

**Files:**
- Modify: `pyproject.toml`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_gateway_foundations.py`
- Modify: `app/core/db.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: `uv run alembic upgrade head` as the only production Schema upgrade command.

- [ ] **Step 1: Write the failing migration test**

```python
def test_alembic_has_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert len(script.get_heads()) == 1
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_migrations.py -q`  
Expected: FAIL because Alembic configuration does not exist.

- [ ] **Step 3: Add dependencies and migration bootstrap**

Add `alembic>=1.14,<2`, `jsonschema>=4.23,<5`, `mcp>=1.27,<2`, `grpcio>=1.74,<2`, `grpcio-reflection>=1.74,<2`, `protobuf>=5,<7`, `a2a-sdk[http-server,grpc]>=1,<2`, and `jmespath>=1,<2`. Configure async Alembic from `settings.database_url`, import `app.models`, and remove `create_all_tables()` from the FastAPI lifespan.

- [ ] **Step 4: Run GREEN**

Run: `uv lock && uv run pytest tests/test_migrations.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add pyproject.toml uv.lock alembic.ini alembic app/core/db.py tests/test_migrations.py && git commit -m "build: add gateway migration foundation"`

### Task 2: Draft 2020-12 Schema enforcement

**Files:**
- Create: `app/gateway/schema_validation.py`
- Create: `app/gateway/errors.py`
- Test: `tests/gateway/test_schema_validation.py`

**Interfaces:**
- Produces: `SchemaValidatorCache.validate_schema(schema) -> None`.
- Produces: `SchemaValidatorCache.validate(instance, schema, cache_key, direction) -> None`.
- Raises: `GatewayError(code, message, retryable, details)`.

- [ ] **Step 1: Write failing tests**

```python
def test_input_error_reports_path_without_value():
    cache = SchemaValidatorCache()
    with pytest.raises(GatewayError) as exc:
        cache.validate({}, {"type": "object", "required": ["product_id"]}, "cap:1", "input")
    assert exc.value.code == "SCHEMA_INPUT_INVALID"
    assert exc.value.details["path"] == []
    assert "instance" not in exc.value.details

def test_invalid_schema_is_rejected_at_publish():
    with pytest.raises(GatewayError, match="Schema"):
        SchemaValidatorCache().validate_schema({"type": "not-a-json-type"})
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/gateway/test_schema_validation.py -q`  
Expected: FAIL because the module is missing.

- [ ] **Step 3: Implement minimal validator cache**

```python
class SchemaValidatorCache:
    def __init__(self) -> None:
        self._validators: dict[str, Draft202012Validator] = {}

    def validate_schema(self, schema: dict) -> None:
        Draft202012Validator.check_schema(schema)

    def validate(self, instance: object, schema: dict, cache_key: str, direction: str) -> None:
        validator = self._validators.setdefault(cache_key, Draft202012Validator(schema))
        error = next(iter(validator.iter_errors(instance)), None)
        if error:
            raise GatewayError(
                code=f"SCHEMA_{direction.upper()}_INVALID",
                message=f"{direction} does not satisfy capability contract",
                retryable=False,
                details={"path": list(error.path), "schema_path": list(error.schema_path), "keyword": error.validator},
            )
```

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/gateway/test_schema_validation.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/gateway tests/gateway && git commit -m "feat: enforce capability json schemas"`

### Task 3: Endpoint and invocation persistence

**Files:**
- Create: `app/models/gateway.py`
- Modify: `app/models/__init__.py`
- Create: `app/schemas/gateway.py`
- Modify: `alembic/versions/0001_gateway_foundations.py`
- Test: `tests/gateway/test_gateway_models.py`

**Interfaces:**
- Produces: `CapabilityEndpoint`, `CapabilityInvocation`, `MCPServer`, `GRPCDescriptor`, `A2AAgent`.
- Endpoint fields: `protocol`, `target`, `priority`, `weight`, `environment`, `release_channel`, `health_status`, `secret_ref`, `tls_config`, `gray_rule`, `fallback_endpoint_id`, `enabled`.

- [ ] **Step 1: Write a failing model-contract test**

```python
def test_endpoint_requires_supported_protocol():
    endpoint = CapabilityEndpoint(protocol="smtp", target="x")
    with pytest.raises(ValueError):
        EndpointConfig.model_validate(endpoint)
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/gateway/test_gateway_models.py -q`  
Expected: FAIL because the models do not exist.

- [ ] **Step 3: Implement models, strict Pydantic enums, and migration tables**

Use `Literal["http", "mcp", "grpc", "a2a", "hosted"]` for protocol configuration. Add unique constraints for endpoint names and invocation idempotency scope.

- [ ] **Step 4: Run migration and test**

Run: `uv run alembic upgrade head && uv run pytest tests/gateway/test_gateway_models.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/models app/schemas alembic tests/gateway && git commit -m "feat: persist gateway endpoints and invocations"`

### Task 4: Redis stability controls

**Files:**
- Create: `app/gateway/stability.py`
- Test: `tests/gateway/test_stability.py`

**Interfaces:**
- Produces: `RateLimiter.acquire(key, limit, period_seconds) -> RateDecision`.
- Produces: `IdempotencyStore.reserve(scope, payload_hash, ttl) -> IdempotencyDecision`.
- Produces: `CircuitBreaker.before_call(key)`, `record_success(key)`, `record_failure(key)`.
- Produces: `BulkheadRegistry.slot(key, limit)` async context manager.

- [ ] **Step 1: Write failing fakeredis-backed behavior tests**

```python
async def test_idempotency_rejects_same_key_with_different_payload(store):
    assert (await store.reserve("cap:v:user:k", "hash-a", 60)).status == "reserved"
    with pytest.raises(GatewayError, match="different payload"):
        await store.reserve("cap:v:user:k", "hash-b", 60)

async def test_breaker_moves_to_half_open_after_timeout(breaker, clock):
    await breaker.record_failure("ep", threshold=1, reset_seconds=10)
    with pytest.raises(GatewayError):
        await breaker.before_call("ep")
    clock.advance(11)
    assert (await breaker.before_call("ep")).state == "half_open"
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/gateway/test_stability.py -q`  
Expected: FAIL because services are missing.

- [ ] **Step 3: Implement Redis Lua token bucket, atomic idempotency reservation, breaker transitions, and local semaphore bulkheads**

Keep Redis keys namespaced by environment. Fail closed for write-risk classes when Redis is unavailable.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/gateway/test_stability.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/gateway/stability.py tests/gateway/test_stability.py && git commit -m "feat: add distributed gateway stability controls"`

### Task 5: Sticky endpoint routing and fallback

**Files:**
- Create: `app/gateway/routing.py`
- Test: `tests/gateway/test_routing.py`

**Interfaces:**
- Produces: `EndpointRouter.select(endpoints, routing_key, channel) -> CapabilityEndpoint`.
- Produces: `EndpointRouter.fallback(failed, endpoints, error_class) -> CapabilityEndpoint | None`.

- [ ] **Step 1: Write failing routing tests**

```python
def test_sticky_key_selects_same_weighted_endpoint(router, endpoints):
    first = router.select(endpoints, "tenant:user:task", "gray")
    assert all(router.select(endpoints, "tenant:user:task", "gray").id == first.id for _ in range(20))

def test_contract_error_never_fails_over(router, primary, backup):
    assert router.fallback(primary, [backup], "provider_contract_error") is None
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/gateway/test_routing.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement deterministic SHA-256 weighted selection and explicit transient-error fallback matrix**

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/gateway/test_routing.py -q && git add app/gateway/routing.py tests/gateway/test_routing.py && git commit -m "feat: add sticky gray endpoint routing"`

### Task 6: HTTP and hosted adapters

**Files:**
- Create: `app/gateway/contracts.py`
- Create: `app/gateway/adapters/base.py`
- Create: `app/gateway/adapters/http.py`
- Create: `app/gateway/adapters/hosted.py`
- Create: `app/gateway/network_policy.py`
- Test: `tests/gateway/adapters/test_http.py`

**Interfaces:**
- Consumes: `EndpointConfig`, `InvocationContext`.
- Produces: `AdapterResult(output, status_code, metadata)`.

- [ ] **Step 1: Write failing SSRF, timeout, and real ASGI-server tests**

```python
async def test_http_adapter_rejects_loopback_outside_local(adapter):
    with pytest.raises(GatewayError, match="destination"):
        await adapter.invoke(endpoint(target="http://127.0.0.1/admin"), request({}), prod_context())
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/gateway/adapters/test_http.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement async pooled HTTP, DNS/IP validation, redirect revalidation, TLS, Secret injection, health check, and cancel hooks**

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/gateway/adapters/test_http.py -q && git add app/gateway tests/gateway/adapters && git commit -m "feat: implement secure http gateway adapter"`

### Task 7: MCP, gRPC, and A2A adapters

**Files:**
- Create: `app/gateway/adapters/mcp.py`
- Create: `app/gateway/adapters/grpc.py`
- Create: `app/gateway/adapters/a2a.py`
- Test: `tests/integration/protocols/test_mcp_adapter.py`
- Test: `tests/integration/protocols/test_grpc_adapter.py`
- Test: `tests/integration/protocols/test_a2a_adapter.py`
- Create: `tests/fixtures/protocol_servers/`

**Interfaces:**
- MCP request: `{"tool": str, "arguments": dict}`.
- gRPC request: `{"service": str, "method": str, "message": dict}`.
- A2A request: canonical SDK `Message` plus task and streaming options.

- [ ] **Step 1: Add real local protocol servers and failing client tests**

Tests must start official SDK servers on ephemeral ports and assert tool results, Reflection discovery, descriptor fallback, Agent Card discovery, task polling, cancellation, streaming event order, and webhook idempotency.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/integration/protocols -q`  
Expected: FAIL because adapters are missing.

- [ ] **Step 3: Implement official-SDK adapters**

MCP tries Streamable HTTP then legacy SSE only on transport negotiation failure. gRPC caches descriptors by endpoint version. A2A validates declared streaming/push capabilities before calling optional operations.

- [ ] **Step 4: Run GREEN and commit**

Run: `uv run pytest tests/integration/protocols -q && git add app/gateway/adapters tests/integration/protocols tests/fixtures && git commit -m "feat: implement mcp grpc and a2a adapters"`

### Task 8: Gateway pipeline and APIs

**Files:**
- Create: `app/gateway/service.py`
- Create: `app/gateway/registry.py`
- Create: `app/api/v1/invocations.py`
- Modify: `app/api/v1/capabilities.py`
- Modify: `app/main.py`
- Test: `tests/gateway/test_gateway_service.py`
- Test: `tests/test_invocations.py`

**Interfaces:**
- Produces: `GatewayService.invoke(command: InvocationCommand) -> InvocationResult`.
- Produces: `POST /api/v1/invocations`, `GET /api/v1/invocations/{id}`, `POST /api/v1/invocations/{id}/cancel`.

- [ ] **Step 1: Write failing pipeline-order and API tests**

```python
async def test_invalid_input_never_calls_adapter(gateway, adapter):
    with pytest.raises(GatewayError) as exc:
        await gateway.invoke(command(input={}))
    assert exc.value.code == "SCHEMA_INPUT_INVALID"
    assert adapter.calls == 0

async def test_invalid_output_marks_contract_failure(gateway, adapter):
    adapter.output = {"wrong": True}
    with pytest.raises(GatewayError) as exc:
        await gateway.invoke(valid_command())
    assert exc.value.code == "SCHEMA_OUTPUT_INVALID"
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/gateway/test_gateway_service.py tests/test_invocations.py -q`  
Expected: FAIL.

- [ ] **Step 3: Implement exact pipeline order and replace `CapabilityService` stub dispatch**

The compatibility route maps its request to `InvocationCommand`. Remove remote-tool and agent stub success responses; missing endpoints return a non-retryable configuration error.

- [ ] **Step 4: Run complete delivery gate**

Run: `uv run pytest tests/gateway tests/integration/protocols tests/test_capabilities.py tests/test_invocations.py -q`  
Expected: PASS with no warnings.

- [ ] **Step 5: Commit**

Run: `git add app tests && git commit -m "feat: route capability execution through gateway"`

