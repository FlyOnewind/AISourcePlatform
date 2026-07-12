import asyncio
import json
import math
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.gateway.errors import GatewayError


_RATE_LIMIT_SCRIPT = """
local capacity = tonumber(ARGV[1])
local period_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])
local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated_ms')
local tokens = tonumber(values[1]) or capacity
local updated_ms = tonumber(values[2]) or now_ms
local elapsed_ms = math.max(0, now_ms - updated_ms)
tokens = math.min(capacity, tokens + elapsed_ms * capacity / period_ms)

local allowed = 0
local retry_after_ms = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry_after_ms = math.ceil((1 - tokens) * period_ms / capacity)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_ms', now_ms)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return {allowed, math.floor(tokens), retry_after_ms}
"""

_IDEMPOTENCY_RESERVE_SCRIPT = """
local values = redis.call('HMGET', KEYS[1], 'payload_hash', 'status', 'result')
if not values[1] then
    redis.call('HSET', KEYS[1], 'payload_hash', ARGV[1], 'status', 'in_progress')
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
    return {'reserved'}
end
if values[1] ~= ARGV[1] then
    return {'reused'}
end
if values[2] == 'completed' then
    return {'completed', values[3]}
end
return {'in_progress'}
"""

_IDEMPOTENCY_COMPLETE_SCRIPT = """
local values = redis.call('HMGET', KEYS[1], 'payload_hash', 'status')
if not values[1] then
    return 'missing'
end
if values[1] ~= ARGV[1] then
    return 'reused'
end
redis.call('HSET', KEYS[1], 'status', 'completed', 'result', ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 'completed'
"""

_IDEMPOTENCY_RELEASE_SCRIPT = """
local values = redis.call('HMGET', KEYS[1], 'payload_hash', 'status')
if values[1] == ARGV[1] and values[2] == 'in_progress' then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_CIRCUIT_BEFORE_SCRIPT = """
local values = redis.call('HMGET', KEYS[1], 'state', 'opened_at_ms', 'probe_at_ms')
local state = values[1]
local now_ms = tonumber(ARGV[1])
local reset_ms = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])
if not state or state == 'closed' then
    return {'closed', 0}
end
if state == 'open' then
    local elapsed_ms = math.max(0, now_ms - tonumber(values[2]))
    if elapsed_ms < reset_ms then
        return {'open', math.max(1, reset_ms - elapsed_ms)}
    end
    redis.call('HSET', KEYS[1], 'state', 'half_open', 'probe_at_ms', now_ms)
    redis.call('PEXPIRE', KEYS[1], ttl_ms)
    return {'half_open', 0}
end

local probe_elapsed_ms = math.max(0, now_ms - tonumber(values[3]))
if probe_elapsed_ms >= reset_ms then
    redis.call('HSET', KEYS[1], 'probe_at_ms', now_ms)
    redis.call('PEXPIRE', KEYS[1], ttl_ms)
    return {'half_open', 0}
end
return {'open', math.max(1, reset_ms - probe_elapsed_ms)}
"""

_CIRCUIT_FAILURE_SCRIPT = """
local state = redis.call('HGET', KEYS[1], 'state')
local threshold = tonumber(ARGV[1])
local failures
if state == 'half_open' or state == 'open' then
    failures = threshold
else
    failures = redis.call('HINCRBY', KEYS[1], 'failures', 1)
end
if failures >= threshold then
    redis.call('HSET', KEYS[1], 'state', 'open', 'failures', threshold, 'opened_at_ms', ARGV[2])
    redis.call('HDEL', KEYS[1], 'probe_at_ms')
else
    redis.call('HSET', KEYS[1], 'state', 'closed')
end
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]))
return failures
"""


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after_ms: int


@dataclass(frozen=True)
class IdempotencyDecision:
    status: Literal["reserved", "in_progress", "completed"]
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class CircuitDecision:
    state: Literal["closed", "open", "half_open"]
    probe_allowed: bool


def _redis_unavailable(operation: str, error: RedisError) -> GatewayError:
    return GatewayError(
        "REDIS_UNAVAILABLE",
        f"Redis is unavailable during {operation}",
        retryable=True,
    )


def _text(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


class RateLimiter:
    def __init__(
        self,
        redis: Redis,
        namespace: str,
        *,
        key_prefix: str = "gateway",
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not namespace:
            raise ValueError("namespace must not be empty")
        if not key_prefix:
            raise ValueError("key_prefix must not be empty")
        self._redis = redis
        self._prefix = f"{key_prefix}:{namespace}:rate"
        self._clock = clock

    async def acquire(self, key: str, limit: int, period_seconds: int) -> RateDecision:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")

        period_ms = period_seconds * 1_000
        try:
            values = await self._redis.eval(
                _RATE_LIMIT_SCRIPT,
                1,
                f"{self._prefix}:{key}",
                limit,
                period_ms,
                math.floor(self._clock() * 1_000),
                period_ms * 2,
            )
        except RedisError as error:
            raise _redis_unavailable("rate limiting", error) from error
        return RateDecision(
            allowed=bool(values[0]),
            remaining=int(values[1]),
            retry_after_ms=int(values[2]),
        )


def _validate_json_native(value: object) -> None:
    if value is None or type(value) in {str, int, bool}:
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise ValueError("result must contain only JSON-native values")
    if type(value) is list:
        for child in value:
            _validate_json_native(child)
        return
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("result must contain only JSON-native values")
            _validate_json_native(child)
        return
    raise ValueError("result must contain only JSON-native values")


def _idempotency_reused() -> GatewayError:
    return GatewayError(
        "IDEMPOTENCY_KEY_REUSED",
        "Idempotency key was reused with a different payload",
    )


class IdempotencyStore:
    def __init__(
        self,
        redis: Redis,
        namespace: str,
        *,
        key_prefix: str = "gateway",
    ) -> None:
        if not namespace:
            raise ValueError("namespace must not be empty")
        if not key_prefix:
            raise ValueError("key_prefix must not be empty")
        self._redis = redis
        self._prefix = f"{key_prefix}:{namespace}:idempotency"

    def _key(self, scope: str) -> str:
        return f"{self._prefix}:{scope}"

    async def reserve(
        self,
        scope: str,
        payload_hash: str,
        ttl_seconds: int,
    ) -> IdempotencyDecision:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        try:
            values = await self._redis.eval(
                _IDEMPOTENCY_RESERVE_SCRIPT,
                1,
                self._key(scope),
                payload_hash,
                ttl_seconds,
            )
        except RedisError as error:
            raise _redis_unavailable("idempotency reservation", error) from error

        status = _text(values[0])
        if status == "reused":
            raise _idempotency_reused()
        if status == "completed":
            return IdempotencyDecision("completed", json.loads(values[1]))
        return IdempotencyDecision(status)

    async def complete(
        self,
        scope: str,
        payload_hash: str,
        result: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        _validate_json_native(result)
        if type(result) is not dict:
            raise ValueError("result must contain only JSON-native values")
        serialized = json.dumps(
            result,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            raw_status = await self._redis.eval(
                _IDEMPOTENCY_COMPLETE_SCRIPT,
                1,
                self._key(scope),
                payload_hash,
                serialized,
                ttl_seconds,
            )
        except RedisError as error:
            raise _redis_unavailable("idempotency completion", error) from error
        status = _text(raw_status)
        if status == "reused":
            raise _idempotency_reused()
        if status == "missing":
            raise GatewayError(
                "IDEMPOTENCY_NOT_RESERVED",
                "Idempotency key has not been reserved",
            )

    async def release(self, scope: str, payload_hash: str) -> None:
        try:
            await self._redis.eval(
                _IDEMPOTENCY_RELEASE_SCRIPT,
                1,
                self._key(scope),
                payload_hash,
            )
        except RedisError as error:
            raise _redis_unavailable("idempotency release", error) from error


class CircuitBreaker:
    def __init__(
        self,
        redis: Redis,
        namespace: str,
        *,
        key_prefix: str = "gateway",
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not namespace:
            raise ValueError("namespace must not be empty")
        if not key_prefix:
            raise ValueError("key_prefix must not be empty")
        self._redis = redis
        self._prefix = f"{key_prefix}:{namespace}:circuit"
        self._clock = clock

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    @staticmethod
    def _validate(failure_threshold: int, reset_seconds: int) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if reset_seconds <= 0:
            raise ValueError("reset_seconds must be positive")

    async def before_call(
        self,
        key: str,
        failure_threshold: int,
        reset_seconds: int,
    ) -> CircuitDecision:
        self._validate(failure_threshold, reset_seconds)
        reset_ms = reset_seconds * 1_000
        try:
            values = await self._redis.eval(
                _CIRCUIT_BEFORE_SCRIPT,
                1,
                self._key(key),
                math.floor(self._clock() * 1_000),
                reset_ms,
                reset_ms * 10,
            )
        except RedisError as error:
            raise _redis_unavailable("circuit check", error) from error
        state = _text(values[0])
        if state == "open":
            raise GatewayError(
                "CIRCUIT_OPEN",
                "Circuit is open",
                retryable=True,
                details={"retry_after_ms": max(1, int(values[1]))},
            )
        return CircuitDecision(
            state=state,
            probe_allowed=state == "half_open",
        )

    async def record_success(self, key: str) -> None:
        try:
            await self._redis.delete(self._key(key))
        except RedisError as error:
            raise _redis_unavailable("circuit success recording", error) from error

    async def record_failure(
        self,
        key: str,
        failure_threshold: int,
        reset_seconds: int,
    ) -> None:
        self._validate(failure_threshold, reset_seconds)
        reset_ms = reset_seconds * 1_000
        try:
            await self._redis.eval(
                _CIRCUIT_FAILURE_SCRIPT,
                1,
                self._key(key),
                failure_threshold,
                math.floor(self._clock() * 1_000),
                reset_ms * 10,
            )
        except RedisError as error:
            raise _redis_unavailable("circuit failure recording", error) from error


class BulkheadRegistry:
    def __init__(self) -> None:
        self._slots: dict[str, tuple[int, asyncio.BoundedSemaphore]] = {}

    @asynccontextmanager
    async def slot(
        self,
        key: str,
        limit: int,
        acquire_timeout_seconds: float,
    ) -> AsyncIterator[None]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if acquire_timeout_seconds <= 0:
            raise ValueError("acquire_timeout_seconds must be positive")

        configured = self._slots.get(key)
        if configured is None:
            semaphore = asyncio.BoundedSemaphore(limit)
            self._slots[key] = (limit, semaphore)
        else:
            configured_limit, semaphore = configured
            if configured_limit != limit:
                raise ValueError(
                    f"bulkhead key {key!r} has conflicting limit "
                    f"{limit}; configured limit is {configured_limit}"
                )

        acquired = False
        try:
            try:
                await asyncio.wait_for(
                    semaphore.acquire(),
                    timeout=acquire_timeout_seconds,
                )
                acquired = True
            except TimeoutError as error:
                raise GatewayError(
                    "BULKHEAD_FULL",
                    "Bulkhead capacity is exhausted",
                    retryable=True,
                ) from error
            yield
        finally:
            if acquired:
                semaphore.release()
