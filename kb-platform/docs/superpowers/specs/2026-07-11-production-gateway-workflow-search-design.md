# Production Gateway, Workflow, and Search Design

**Date:** 2026-07-11  
**Status:** Approved design  
**Scope:** Production-grade Schema enforcement, Gateway execution, Temporal workflows, protocol adapters, OpenSearch hybrid retrieval, asynchronous document ingestion, and admin API contract repair.

## 1. Goals

This design replaces the current demonstration-only execution paths with production-capable services while retaining one maintainable Python repository.

The delivery must:

- enforce JSON Schema Draft 2020-12 on capability inputs and outputs;
- route all capability calls through one deterministic Gateway pipeline;
- provide real HTTP, MCP, gRPC, A2A, and trusted hosted adapters;
- support rate limiting, idempotency, circuit breaking, bulkheads, weighted gray routing, and fallback endpoints;
- execute persistent DAG workflows with conditions, approvals, compensation, cancellation, and recovery on Temporal;
- move document parsing, embedding, and indexing out of FastAPI request workers and into Temporal workers;
- persist capability and knowledge embeddings in OpenSearch and use BM25 plus vector hybrid retrieval;
- prohibit silent fallback to PostgreSQL full scans or in-memory vector search;
- add the missing capability-permission delete endpoint used by the admin console;
- run locally through Docker Compose while keeping process and configuration boundaries suitable for a later Kubernetes migration.

## 2. Non-goals

- This delivery does not provide Helm charts or a Kubernetes production deployment.
- It does not execute arbitrary uploaded Python code as a hosted capability.
- It does not support MCP stdio transport.
- It does not retain Qdrant as a second online retrieval backend after migration.
- It does not split the repository into independently versioned microservice repositories.

## 3. Runtime Topology

The repository produces three independently deployable application processes:

1. **FastAPI Control Plane**
   - registration, versioning, permissions, endpoint configuration;
   - workflow definition and execution APIs;
   - document upload and processing-status APIs;
   - MCP, gRPC, and A2A registration APIs;
   - invocation submission, status, and cancellation APIs.

2. **Gateway Worker**
   - deterministic invocation pipeline;
   - endpoint selection and stability controls;
   - protocol adapter execution;
   - output validation, audit, and metrics.

3. **Knowledge and Workflow Worker**
   - generic capability DAG execution;
   - approval and compensation handling;
   - document parsing, chunking, embedding, indexing, validation, and publication.

Supporting services are PostgreSQL, Redis, MinIO, OpenSearch, OpenSearch Dashboards, Temporal Server, and Temporal UI. Task queues isolate `gateway-execution`, `knowledge-ingestion`, and `workflow-orchestration`. Workers must be horizontally scalable and must not rely on process-local durable state.

## 4. Code Boundaries

- `app/gateway/`: invocation pipeline, routing, stability controls, protocol adapters.
- `app/workflows/`: Temporal workflows, activities, worker entry points, workflow data contracts.
- `app/search/`: OpenSearch clients, mappings, index writers, alias management, hybrid retrieval.
- `app/api/v1/`: thin authenticated APIs that validate requests and submit work.
- `app/models/`: business metadata and query-oriented execution summaries.
- `app/schemas/`: API, workflow, endpoint, and protocol configuration contracts.

Temporal remains the source of truth for execution history. PostgreSQL stores query-oriented summaries and platform business metadata, not a duplicate Temporal event history.

## 5. Gateway Invocation Pipeline

Every capability invocation follows this order:

1. authenticate the caller and resolve the task context;
2. resolve an immutable capability version;
3. evaluate permissions and risk policy;
4. validate input against JSON Schema;
5. check or reserve the idempotency key;
6. apply distributed rate limiting;
7. select an eligible endpoint through gray routing;
8. check the endpoint bulkhead and circuit breaker;
9. invoke the selected protocol adapter;
10. validate the adapter result against the output Schema;
11. record audit, invocation status, latency, and metrics;
12. store the idempotent result and return it.

Failures must identify whether they are retryable. Automatic retries are permitted only when the capability explicitly declares `idempotent=true` and the error is classified as transient.

## 6. JSON Schema Enforcement

The implementation uses `jsonschema.Draft202012Validator`.

- Capability publication validates that input and output Schemas are themselves valid Draft 2020-12 Schemas.
- Compiled validators are cached by capability ID and immutable version.
- Input is validated before reserving scarce downstream resources.
- Output is validated before a call is recorded as successful.
- Validation errors include the instance path, Schema path, and failing keyword.
- Error responses never echo sensitive input values.
- Invalid downstream output is classified as a provider contract failure and can affect endpoint health.

## 7. Stability Controls

### 7.1 Rate limiting

Redis Lua scripts implement a distributed token bucket. Keys include tenant or caller, capability, version, and configured limit scope. A Redis failure is fail-closed for high-risk writes and configurable for low-risk reads.

### 7.2 Idempotency

The unique identity is `capability + version + caller + idempotency_key`.

- An in-progress duplicate returns a conflict or waits according to the invocation mode.
- A completed duplicate returns the stored result.
- Request payload hashes must match; reusing a key with a different payload is rejected.
- Stored results follow the configured retention policy.

### 7.3 Circuit breakers and bulkheads

Circuit state is shared through Redis and transitions through closed, open, and half-open. Breaker keys are endpoint-specific. Bulkheads combine protocol/endpoint semaphores with Temporal task-queue concurrency limits.

### 7.4 Gray routing and fallback

Endpoints carry priority, weight, environment, release channel, health state, and optional fallback relationships. Stable hashing on tenant, caller, or task session provides sticky gray routing. Fallback occurs only for classified transient failures and only to a healthy compatible endpoint.

## 8. Protocol Adapters

All adapters implement:

```python
class ProtocolAdapter(Protocol):
    async def health_check(self, endpoint, context) -> HealthResult: ...
    async def invoke(self, endpoint, request, context) -> AdapterResult: ...
    async def cancel(self, invocation, context) -> None: ...
```

### 8.1 HTTP

Use `httpx.AsyncClient` with connection pooling, explicit timeouts, TLS verification, redirect controls, SSRF-safe destination validation, and credential injection through Secret references. The adapter must not accept arbitrary credentials in invocation payloads.

### 8.2 MCP

Pin the stable MCP Python SDK below v2 until v2 is stable and migration is explicitly approved. Try Streamable HTTP first and support legacy SSE as a compatibility transport. Perform initialization and capability negotiation before tool calls. Registered MCP Servers store a protected endpoint, authentication reference, allowed primitives, allowed tools, timeout, and health state.

### 8.3 gRPC

Use `grpc.aio`. Prefer server Reflection and use an uploaded descriptor set when Reflection is unavailable. Descriptor sets are stored in MinIO and versioned in PostgreSQL. Dynamic protobuf messages are converted to and from the Gateway JSON contract. TLS and metadata credentials use governed Secret references.

### 8.4 A2A

Discover and validate the Agent Card before invoking optional features. Support message submission, task retrieval, cancellation, SSE streaming/subscription, and push-notification configuration and callbacks. Webhook endpoints require SSRF protection, HTTPS outside local development, authentication, idempotent delivery handling, and rate limiting.

### 8.5 Hosted

Only implementations registered in the trusted platform codebase can execute. Uploaded artifacts cannot be imported or evaluated as Python code by the Gateway.

## 9. Temporal Workflow Design

Workflow definitions are versioned JSON documents in PostgreSQL. Published versions are immutable. Starting an execution passes the complete definition snapshot to Temporal so an in-flight execution cannot observe later edits.

Supported node types:

- `capability`: invoke a fixed capability code and version;
- `condition`: choose branches with a restricted expression language;
- `parallel`: run branches concurrently using `all` or `any` completion policy;
- `approval`: wait for an authorized Temporal Signal;
- `transform`: deterministic JSONPath/JMESPath data mapping;
- `subworkflow`: execute an immutable workflow version as a child workflow;
- `end`: construct the final result.

Publishing validates a single entry point, acyclic graph, complete branches, valid references, reachable terminal nodes, and compatible node contracts. All I/O, database, LLM, and protocol work runs in Activities. Workflow code performs deterministic orchestration only.

### 9.1 Approval

Approval nodes enter `waiting_approval`. The approval API authenticates and authorizes the reviewer, creates an approval record, and then sends an approve or reject Signal. A Signal cannot bypass platform authorization. Rejection follows the configured failure or compensation edge.

### 9.2 Compensation

Write nodes may declare a compensation capability. Successful compensatable nodes register their compensations. On failure or cancellation, compensation runs in reverse completion order. A failed compensation produces `compensation_failed` and requires operator intervention; it never converts the original execution to success.

### 9.3 Cancellation and status

Workflow Queries expose node status and execution state. Cancellation propagates to cancellable HTTP, gRPC, MCP, and A2A operations. PostgreSQL stores the Temporal Workflow ID, current state, current nodes, timestamps, and safe result summaries for product queries.

## 10. Asynchronous Document Ingestion

Document upload stores the original object and starts `DocumentIngestionWorkflow`. The API returns `202 Accepted` with the document ID and Temporal Workflow ID.

The workflow runs:

1. parse;
2. clean and normalize;
3. chunk;
4. embed;
5. write a candidate OpenSearch index;
6. validate document and chunk counts plus sample retrieval;
7. atomically switch the knowledge-base alias;
8. publish the document and index version.

Activities use deterministic object names, checksums, and version identifiers so retries are safe. A failed candidate index never changes the production alias or published status.

## 11. OpenSearch Retrieval

Logical index families are:

- `capabilities-v{n}` with alias `capabilities-current`;
- `knowledge-chunks-{kb_id}-v{n}` with alias `knowledge-{kb_id}-current`.

Capability documents contain searchable metadata, input/output field names, ranking attributes, permission filters, a persisted vector, the embedding model, dimension, and content checksum. Unchanged checksums skip re-embedding.

Knowledge documents contain text, title path, keywords, document/chunk/index versions, source, security level, permission labels, and a persisted vector.

Search performs:

1. server-generated tenant, identity, permission, environment, state, and risk pre-filters;
2. BM25 lexical recall;
3. k-NN vector recall;
4. OpenSearch hybrid score normalization or rank fusion;
5. deterministic reranking by quality, health, latency, cost, installed status, and recommended version.

Each query generates one query embedding. The service does not load all capabilities or chunks from PostgreSQL and does not re-embed all candidates.

## 12. Retrieval Failure Semantics and Qdrant Migration

OpenSearch failure returns `503 SEARCH_BACKEND_UNAVAILABLE` by default. The service must not silently fall back to PostgreSQL full scans or in-memory vector calculation.

An optional low-risk degraded mode may return a recent Redis result only when policy permits it. The response includes `degraded=true`, cache time, and index version. All failures affect health, metrics, and audit output.

A one-time migration reads Qdrant vectors and PostgreSQL metadata, writes OpenSearch documents, verifies counts and samples, then switches aliases. Qdrant is removed from the serving path and Compose only after verification succeeds.

## 13. Data Model

Add:

- `capability_endpoints`;
- `workflow_definitions` and `workflow_versions`;
- `workflow_execution_summaries`;
- `capability_invocations`;
- `index_versions`;
- `grpc_descriptors`;
- `mcp_servers`;
- `a2a_agents`;
- `approval_records`.

Endpoint records include protocol, target, environment, release channel, priority, weight, health, Secret reference, TLS configuration, gray rule, and fallback relation. Alembic manages all Schema and data migrations. Production startup must not use `create_all` as a migration mechanism.

## 14. API Contract

The existing capability invocation route remains for synchronous short calls and uses the new Gateway. Add invocation submission, status, and cancellation routes for long calls.

Add APIs for:

- workflow definition, publication, execution, query, cancellation, and approval;
- asynchronous document-processing status;
- MCP Server registration, discovery, refresh, and tool import;
- gRPC Reflection and descriptor import;
- A2A Agent Card registration, refresh, tasks, streaming, and callbacks;
- endpoint, gray release, health, and index-version administration;
- `DELETE /api/v1/capabilities/{capability_id}/permissions/{permission_id}`.

Errors use a stable envelope with `code`, `message`, `trace_id`, `retryable`, and safe structured `details`.

## 15. Docker Compose and Kubernetes Portability

Compose must run PostgreSQL, Redis, MinIO, OpenSearch, OpenSearch Dashboards, Temporal Server, Temporal UI, FastAPI, Gateway Worker, and Knowledge/Workflow Worker with explicit health checks.

Configuration is environment-driven. Containers are stateless except declared volumes. Workers use separate entry points and task queues, support graceful shutdown, and can be replicated. Service discovery uses configurable hostnames rather than hard-coded Compose names. These boundaries permit later translation to Kubernetes Deployments, Services, Secrets, ConfigMaps, and autoscaling without changing application interfaces.

## 16. Testing and Acceptance

All behavior changes use test-driven development.

Unit tests cover Schema validation, DAG publication, routing, rate limiting, idempotency, breaker transitions, compensation order, and error classification. Temporal tests cover retries, Signals, cancellation, child workflows, and recovery. Compose integration tests use real OpenSearch, Redis, Temporal, MCP, gRPC, and A2A servers. Protocol acceptance must not be replaced by no-op or echo adapters.

Required end-to-end scenarios:

- invalid input is rejected before adapter execution;
- invalid provider output is recorded as a contract failure;
- duplicate idempotent requests execute once and return the same result;
- a reused idempotency key with a different payload is rejected;
- stable gray-routing keys hit the same endpoint;
- an unhealthy primary can fail over only under configured conditions;
- an open breaker blocks calls and later permits a half-open probe;
- approval pauses execution and only an authorized decision resumes it;
- compensation executes in reverse order after a later node fails;
- OpenSearch failure is visible and never triggers a silent full scan;
- document upload returns immediately and publication happens only after index validation;
- MCP Streamable HTTP and SSE, gRPC Reflection and descriptor fallback, and complete A2A task flows work against real test servers;
- the admin permission-delete action calls an existing authorized API.

## 17. Delivery Decomposition

Implementation is split into three ordered, independently testable plans:

1. **Gateway and protocol execution**: Alembic foundations, JSON Schema enforcement, endpoint routing, Redis stability controls, HTTP/MCP/gRPC/A2A adapters, and invocation APIs.
2. **Temporal workflow and ingestion**: Temporal infrastructure, persistent DAG execution, approvals, compensation, cancellation, execution summaries, and asynchronous document processing.
3. **OpenSearch retrieval and admin contract**: capability and knowledge mappings, persistent embeddings, hybrid retrieval, Qdrant migration, failure semantics, index aliases, and the permission-delete API/UI contract.

Plan 2 consumes the Gateway invocation interface from Plan 1. Plan 3 reuses Temporal ingestion activities from Plan 2 and the Schema/version contracts from Plan 1. Each plan must leave the project runnable and must pass its own unit and Compose integration gates before the next plan starts.

## 18. Authoritative References

- Temporal Python SDK: <https://docs.temporal.io/develop/python>
- Temporal message passing: <https://docs.temporal.io/develop/python/workflows/message-passing>
- OpenSearch hybrid search: <https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/>
- MCP transports: <https://modelcontextprotocol.io/specification/2025-06-18/basic/transports>
- MCP Python SDK: <https://github.com/modelcontextprotocol/python-sdk>
- gRPC Python: <https://grpc.io/docs/languages/python/>
- A2A specification: <https://github.com/a2aproject/A2A/blob/main/docs/specification.md>
