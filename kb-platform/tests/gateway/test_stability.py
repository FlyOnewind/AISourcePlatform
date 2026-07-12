import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as redis

from app.core.config import Settings
from app.gateway.errors import GatewayError
from app.gateway.stability import (
    BulkheadRegistry,
    CircuitBreaker,
    CircuitDecision,
    IdempotencyStore,
    RateLimiter,
)


class ManualClock:
    def __init__(self, initial: float = 1_000.0) -> None:
        self.current = initial

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@pytest_asyncio.fixture
async def redis_client():
    client = redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    await client.ping()
    yield client
    await client.aclose()


@pytest.fixture
def namespace() -> str:
    return f"test-{uuid4().hex}"


async def test_gateway_redis_prefix_is_configurable(redis_client, namespace):
    settings = Settings(gateway_redis_prefix="edge-gateway")
    limiter = RateLimiter(
        redis_client,
        namespace,
        key_prefix=settings.gateway_redis_prefix,
        clock=ManualClock(),
    )

    await limiter.acquire("caller", 1, 60)

    assert await redis_client.keys(f"edge-gateway:{namespace}:rate:*")


@pytest.mark.parametrize(("limit", "period"), [(0, 1), (-1, 1), (1, 0), (1, -1)])
async def test_rate_limiter_rejects_invalid_configuration(redis_client, namespace, limit, period):
    limiter = RateLimiter(redis_client, namespace)

    with pytest.raises(ValueError):
        await limiter.acquire("caller", limit, period)


async def test_rate_limiter_allows_capacity_then_returns_retry_delay(redis_client, namespace):
    limiter = RateLimiter(redis_client, namespace, clock=ManualClock())

    decisions = [await limiter.acquire("caller", 3, 60) for _ in range(4)]

    assert [decision.allowed for decision in decisions] == [True, True, True, False]
    assert [decision.remaining for decision in decisions[:3]] == [2, 1, 0]
    assert decisions[-1].remaining == 0
    assert decisions[-1].retry_after_ms > 0


async def test_rate_limiter_refills_proportionally(redis_client, namespace):
    clock = ManualClock()
    limiter = RateLimiter(redis_client, namespace, clock=clock)
    for _ in range(4):
        assert (await limiter.acquire("caller", 4, 8)).allowed

    clock.advance(2)

    assert (await limiter.acquire("caller", 4, 8)).allowed
    assert not (await limiter.acquire("caller", 4, 8)).allowed


async def test_rate_limiter_is_atomic_under_concurrent_callers(redis_client, namespace):
    limiter = RateLimiter(redis_client, namespace, clock=ManualClock())

    decisions = await asyncio.gather(*(limiter.acquire("shared", 10, 60) for _ in range(30)))

    assert sum(decision.allowed for decision in decisions) == 10


async def test_rate_limiter_keys_include_environment_and_component(redis_client, namespace):
    limiter = RateLimiter(redis_client, namespace, clock=ManualClock())

    await limiter.acquire("caller", 1, 60)

    assert await redis_client.keys(f"gateway:{namespace}:rate:*")
    assert await redis_client.pttl(f"gateway:{namespace}:rate:caller") > 0


@pytest.fixture
def store(redis_client, namespace):
    return IdempotencyStore(redis_client, namespace)


async def test_idempotency_reserves_then_reports_in_progress(store):
    first = await store.reserve("cap:v:user:k", "hash-a", 60)
    duplicate = await store.reserve("cap:v:user:k", "hash-a", 60)

    assert first.status == "reserved"
    assert duplicate.status == "in_progress"
    assert duplicate.result is None


async def test_idempotency_rejects_same_key_with_different_payload(store):
    assert (await store.reserve("cap:v:user:k", "hash-a", 60)).status == "reserved"

    with pytest.raises(GatewayError) as exc:
        await store.reserve("cap:v:user:k", "hash-b", 60)

    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert exc.value.retryable is False


async def test_idempotency_completion_is_returned_to_duplicates(store):
    result = {"items": [1, "two", None], "ok": True}
    await store.reserve("scope", "hash", 60)

    await store.complete("scope", "hash", result, 60)

    decision = await store.reserve("scope", "hash", 60)
    assert decision.status == "completed"
    assert decision.result == result
    assert decision.result is not result


async def test_competing_duplicate_completions_preserve_the_established_result(store):
    first_result = {"winner": "first"}
    second_result = {"winner": "second"}
    await store.reserve("scope", "hash", 60)

    await asyncio.gather(
        store.complete("scope", "hash", first_result, 60),
        store.complete("scope", "hash", second_result, 60),
    )
    established = (await store.reserve("scope", "hash", 60)).result
    competing = second_result if established == first_result else first_result

    await store.complete("scope", "hash", competing, 60)

    assert (await store.reserve("scope", "hash", 60)).result == established


async def test_idempotency_complete_rejects_a_different_payload_hash(store):
    await store.reserve("scope", "hash-a", 60)

    with pytest.raises(GatewayError) as exc:
        await store.complete("scope", "hash-b", {"ok": True}, 60)

    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"


async def test_idempotency_release_only_removes_matching_in_progress(store):
    await store.reserve("scope", "hash-a", 60)

    await store.release("scope", "hash-b")
    assert (await store.reserve("scope", "hash-a", 60)).status == "in_progress"
    await store.release("scope", "hash-a")
    assert (await store.reserve("scope", "hash-c", 60)).status == "reserved"


async def test_idempotency_release_cannot_remove_completed_result(store):
    await store.reserve("scope", "hash", 60)
    await store.complete("scope", "hash", {"value": 1}, 60)

    await store.release("scope", "hash")

    decision = await store.reserve("scope", "hash", 60)
    assert decision.status == "completed"
    assert decision.result == {"value": 1}


@pytest.mark.parametrize("ttl", [0, -1])
async def test_idempotency_rejects_non_positive_ttl(store, ttl):
    with pytest.raises(ValueError):
        await store.reserve("scope", "hash", ttl)

    with pytest.raises(ValueError):
        await store.complete("scope", "hash", {}, ttl)


@pytest.mark.parametrize(
    "result",
    [
        {"value": float("nan")},
        {"value": (1, 2)},
        {1: "non-string-key"},
        {"value": object()},
    ],
)
async def test_idempotency_rejects_non_json_native_results(store, result):
    await store.reserve("scope", "hash", 60)

    with pytest.raises(ValueError, match="JSON-native"):
        await store.complete("scope", "hash", result, 60)


async def test_idempotency_completion_refreshes_ttl(store, redis_client, namespace):
    await store.reserve("scope", "hash", 1)
    key = f"gateway:{namespace}:idempotency:scope"
    await redis_client.pexpire(key, 100)

    await store.complete("scope", "hash", {"ok": True}, 2)

    assert await redis_client.pttl(key) > 1_000


async def test_duplicate_completion_preserves_result_and_refreshes_ttl(
    store,
    redis_client,
    namespace,
):
    canonical = {"winner": "canonical"}
    await store.reserve("scope", "hash", 60)
    await store.complete("scope", "hash", canonical, 60)
    key = f"gateway:{namespace}:idempotency:scope"
    await redis_client.pexpire(key, 100)

    await store.complete("scope", "hash", {"winner": "late"}, 2)

    decision = await store.reserve("scope", "hash", 60)
    assert decision.result == canonical
    assert await redis_client.pttl(key) > 1_000


async def test_only_one_concurrent_idempotency_reservation_is_new(store):
    decisions = await asyncio.gather(*(store.reserve("scope", "hash", 60) for _ in range(20)))

    assert sum(decision.status == "reserved" for decision in decisions) == 1
    assert sum(decision.status == "in_progress" for decision in decisions) == 19


async def test_redis_clients_with_byte_responses_are_supported(namespace):
    client = redis.Redis.from_url("redis://127.0.0.1:6379/0")
    try:
        store = IdempotencyStore(client, namespace)
        assert (await store.reserve("scope", "hash", 60)).status == "reserved"
        await store.complete("scope", "hash", {"ok": True}, 60)
        assert (await store.reserve("scope", "hash", 60)).result == {"ok": True}

        breaker = CircuitBreaker(client, namespace, clock=ManualClock())
        await breaker.record_failure("endpoint", 1, 10)
        with pytest.raises(GatewayError) as exc:
            await breaker.before_call("endpoint", 1, 10, 30)
        assert exc.value.code == "CIRCUIT_OPEN"
    finally:
        await client.aclose()


async def test_idempotency_fails_closed_when_redis_is_unavailable(namespace):
    unavailable = redis.Redis.from_url("redis://127.0.0.1:6399/0", decode_responses=True)
    store = IdempotencyStore(unavailable, namespace)
    try:
        with pytest.raises(GatewayError) as exc:
            await store.reserve("scope", "hash", 60)
    finally:
        await unavailable.aclose()

    assert exc.value.code == "REDIS_UNAVAILABLE"
    assert exc.value.retryable is True


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def breaker(redis_client, namespace, clock):
    return CircuitBreaker(redis_client, namespace, clock=clock)


async def test_circuit_starts_closed(breaker):
    assert await breaker.before_call("endpoint", 2, 10, 30) == CircuitDecision(
        state="closed",
        probe_allowed=False,
        probe_token=None,
    )


async def test_circuit_opens_only_at_failure_threshold(breaker):
    await breaker.record_failure("endpoint", failure_threshold=2, reset_seconds=10)
    assert (await breaker.before_call("endpoint", 2, 10, 30)).state == "closed"

    await breaker.record_failure("endpoint", failure_threshold=2, reset_seconds=10)

    with pytest.raises(GatewayError) as exc:
        await breaker.before_call("endpoint", 2, 10, 30)
    assert exc.value.code == "CIRCUIT_OPEN"
    assert exc.value.retryable is True
    assert exc.value.details["retry_after_ms"] > 0


async def test_circuit_state_is_endpoint_specific(breaker):
    await breaker.record_failure("endpoint-a", failure_threshold=1, reset_seconds=10)

    assert (await breaker.before_call("endpoint-b", 1, 10, 30)).state == "closed"


async def test_only_one_half_open_probe_is_allowed(breaker, clock):
    await breaker.record_failure("endpoint", failure_threshold=1, reset_seconds=10)
    clock.advance(11)

    first, second = await asyncio.gather(
        breaker.before_call("endpoint", 1, 10, 30),
        breaker.before_call("endpoint", 1, 10, 30),
        return_exceptions=True,
    )

    assert sum(
        isinstance(value, CircuitDecision) and value.probe_allowed
        for value in (first, second)
    ) == 1
    admitted = next(value for value in (first, second) if isinstance(value, CircuitDecision))
    assert admitted.probe_token
    rejected = next(value for value in (first, second) if isinstance(value, GatewayError))
    assert rejected.code == "CIRCUIT_OPEN"
    assert rejected.details["retry_after_ms"] > 0


async def test_slow_half_open_probe_remains_exclusive_for_probe_lease(
    redis_client,
    namespace,
    clock,
):
    first_breaker = CircuitBreaker(redis_client, namespace, clock=clock)
    second_breaker = CircuitBreaker(redis_client, namespace, clock=clock)
    await first_breaker.record_failure("endpoint", failure_threshold=1, reset_seconds=1)
    clock.advance(2)
    first = await first_breaker.before_call("endpoint", 1, 1, 5)

    clock.advance(2)
    with pytest.raises(GatewayError) as exc:
        await second_breaker.before_call("endpoint", 1, 1, 5)

    assert first.probe_allowed is True
    assert first.probe_token
    assert exc.value.code == "CIRCUIT_OPEN"
    assert exc.value.details["retry_after_ms"] == 3_000


async def test_expired_probe_lease_allows_a_new_owner(breaker, clock):
    await breaker.record_failure("endpoint", failure_threshold=1, reset_seconds=1)
    clock.advance(2)
    first = await breaker.before_call("endpoint", 1, 1, 5)

    clock.advance(6)
    second = await breaker.before_call("endpoint", 1, 1, 5)

    assert first.probe_token
    assert second.probe_token
    assert second.probe_token != first.probe_token


async def test_half_open_probe_success_closes_circuit(breaker, clock):
    await breaker.record_failure("endpoint", failure_threshold=1, reset_seconds=10)
    clock.advance(11)
    probe = await breaker.before_call("endpoint", 1, 10, 30)
    assert probe.state == "half_open"

    await breaker.record_success("endpoint", probe_token=probe.probe_token)

    assert (await breaker.before_call("endpoint", 1, 10, 30)).state == "closed"


async def test_half_open_probe_failure_reopens_and_resets_timer(breaker, clock):
    await breaker.record_failure("endpoint", failure_threshold=1, reset_seconds=10)
    clock.advance(11)
    probe = await breaker.before_call("endpoint", 1, 10, 30)

    await breaker.record_failure(
        "endpoint",
        failure_threshold=1,
        reset_seconds=10,
        probe_token=probe.probe_token,
    )

    with pytest.raises(GatewayError) as exc:
        await breaker.before_call("endpoint", 1, 10, 30)
    assert exc.value.details["retry_after_ms"] == 10_000


async def test_stale_pre_open_success_cannot_clear_open_circuit(breaker):
    await breaker.record_failure("endpoint", failure_threshold=2, reset_seconds=10)
    await breaker.record_failure("endpoint", failure_threshold=2, reset_seconds=10)

    await breaker.record_success("endpoint")

    with pytest.raises(GatewayError) as exc:
        await breaker.before_call("endpoint", 2, 10, 30)
    assert exc.value.code == "CIRCUIT_OPEN"


async def test_stale_probe_success_cannot_close_another_probe_lease(breaker, clock):
    await breaker.record_failure("endpoint", failure_threshold=1, reset_seconds=1)
    clock.advance(2)
    probe = await breaker.before_call("endpoint", 1, 1, 10)

    await breaker.record_success("endpoint", probe_token="stale-token")

    with pytest.raises(GatewayError):
        await breaker.before_call("endpoint", 1, 1, 10)
    await breaker.record_success("endpoint", probe_token=probe.probe_token)
    assert (await breaker.before_call("endpoint", 1, 1, 10)).state == "closed"


async def test_stale_probe_failure_cannot_reopen_another_probe_lease(breaker, clock):
    await breaker.record_failure("endpoint", failure_threshold=1, reset_seconds=1)
    clock.advance(2)
    probe = await breaker.before_call("endpoint", 1, 1, 10)

    await breaker.record_failure(
        "endpoint",
        failure_threshold=1,
        reset_seconds=1,
        probe_token="stale-token",
    )

    await breaker.record_success("endpoint", probe_token=probe.probe_token)
    assert (await breaker.before_call("endpoint", 1, 1, 10)).state == "closed"


async def test_circuit_state_has_conservative_expiry(breaker, redis_client, namespace):
    await breaker.record_failure("endpoint", failure_threshold=2, reset_seconds=10)

    ttl = await redis_client.pttl(f"gateway:{namespace}:circuit:endpoint")

    assert ttl >= 99_000


@pytest.mark.parametrize(
    ("threshold", "reset_seconds"),
    [(0, 10), (-1, 10), (1, 0), (1, -1)],
)
async def test_circuit_rejects_invalid_configuration(breaker, threshold, reset_seconds):
    with pytest.raises(ValueError):
        await breaker.before_call("endpoint", threshold, reset_seconds, 30)

    with pytest.raises(ValueError):
        await breaker.record_failure("endpoint", threshold, reset_seconds)


@pytest.mark.parametrize("probe_lease_seconds", [0, -1])
async def test_circuit_rejects_non_positive_probe_lease(breaker, probe_lease_seconds):
    with pytest.raises(ValueError, match="probe_lease_seconds"):
        await breaker.before_call("endpoint", 1, 10, probe_lease_seconds)


async def test_circuit_fails_closed_when_redis_is_unavailable(namespace):
    unavailable = redis.Redis.from_url("redis://127.0.0.1:6399/0", decode_responses=True)
    breaker = CircuitBreaker(unavailable, namespace)
    try:
        with pytest.raises(GatewayError) as exc:
            await breaker.before_call("endpoint", 1, 10, 30)
    finally:
        await unavailable.aclose()

    assert exc.value.code == "REDIS_UNAVAILABLE"
    assert exc.value.retryable is True


async def test_bulkhead_never_exceeds_configured_active_slots():
    registry = BulkheadRegistry()
    active = 0
    maximum = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal active, maximum
        async with registry.slot("endpoint", 3, 1):
            async with lock:
                active += 1
                maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1

    await asyncio.gather(*(worker() for _ in range(20)))

    assert maximum == 3


async def test_bulkhead_keys_have_independent_capacity():
    registry = BulkheadRegistry()

    async with registry.slot("endpoint-a", 1, 1):
        async with registry.slot("endpoint-b", 1, 1):
            pass


async def test_bulkhead_timeout_raises_retryable_gateway_error():
    registry = BulkheadRegistry()

    async with registry.slot("endpoint", 1, 1):
        with pytest.raises(GatewayError) as exc:
            async with registry.slot("endpoint", 1, 0.01):
                pytest.fail("timed-out slot must not be entered")

    assert exc.value.code == "BULKHEAD_FULL"
    assert exc.value.retryable is True


async def test_bulkhead_rejects_conflicting_limit_for_existing_key():
    registry = BulkheadRegistry()

    async with registry.slot("endpoint", 1, 1):
        with pytest.raises(ValueError, match="conflicting limit"):
            async with registry.slot("endpoint", 2, 1):
                pass


async def test_bulkhead_releases_slot_after_context_exception():
    registry = BulkheadRegistry()

    with pytest.raises(RuntimeError):
        async with registry.slot("endpoint", 1, 1):
            raise RuntimeError("boom")

    async with registry.slot("endpoint", 1, 0.01):
        pass


async def test_bulkhead_releases_slot_after_cancellation():
    registry = BulkheadRegistry()
    entered = asyncio.Event()

    async def hold_slot():
        async with registry.slot("endpoint", 1, 1):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold_slot())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with registry.slot("endpoint", 1, 0.01):
        pass


@pytest.mark.parametrize(("limit", "timeout"), [(0, 1), (-1, 1), (1, 0), (1, -1)])
async def test_bulkhead_rejects_invalid_configuration(limit, timeout):
    registry = BulkheadRegistry()

    with pytest.raises(ValueError):
        async with registry.slot("endpoint", limit, timeout):
            pass
