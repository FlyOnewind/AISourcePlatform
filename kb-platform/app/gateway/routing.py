from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Collection, Sequence
from uuid import UUID

from app.gateway.errors import GatewayError


_TRANSIENT_FALLBACK_ERRORS = frozenset(
    {
        "connection_error",
        "connect_timeout",
        "read_timeout",
        "service_unavailable",
        "circuit_open",
    }
)


def _invalid_configuration(message: str) -> GatewayError:
    return GatewayError(
        "INVALID_ROUTING_CONFIGURATION",
        message,
        retryable=False,
    )


@dataclass(frozen=True)
class RoutableEndpoint:
    id: UUID
    capability_id: UUID
    protocol: str
    environment: str
    release_channel: str
    priority: int
    weight: int
    health_status: str
    enabled: bool
    fallback_endpoint_id: UUID | None


class EndpointRouter:
    def select(
        self,
        endpoints: Sequence[RoutableEndpoint],
        routing_key: str,
        environment: str,
        release_channel: str,
    ) -> RoutableEndpoint:
        endpoint_ids = [endpoint.id for endpoint in endpoints]
        invalid_endpoint = any(
            endpoint.weight <= 0 or endpoint.priority < 0 for endpoint in endpoints
        )
        if (
            not routing_key.strip()
            or len(endpoint_ids) != len(set(endpoint_ids))
            or invalid_endpoint
        ):
            raise _invalid_configuration("Routing configuration is invalid.")
        eligible = [
            endpoint
            for endpoint in endpoints
            if endpoint.enabled
            and endpoint.environment == environment
            and endpoint.release_channel == release_channel
            and endpoint.health_status not in {"unhealthy", "disabled"}
        ]
        if not eligible:
            raise GatewayError(
                "NO_ELIGIBLE_ENDPOINT",
                "No eligible endpoint matches the routing request.",
                retryable=False,
            )
        priority = min(endpoint.priority for endpoint in eligible)
        candidates = sorted(
            (endpoint for endpoint in eligible if endpoint.priority == priority),
            key=lambda endpoint: endpoint.id.int,
        )
        total_weight = sum(endpoint.weight for endpoint in candidates)
        bucket = (
            int.from_bytes(sha256(routing_key.encode("utf-8")).digest(), "big")
            % total_weight
        )
        for endpoint in candidates:
            if bucket < endpoint.weight:
                return endpoint
            bucket -= endpoint.weight
        raise AssertionError("weighted selection exhausted unexpectedly")

    def fallback(
        self,
        failed: RoutableEndpoint,
        endpoints: Sequence[RoutableEndpoint],
        error_class: str,
        visited_endpoint_ids: Collection[UUID] = (),
    ) -> RoutableEndpoint | None:
        if (
            error_class not in _TRANSIENT_FALLBACK_ERRORS
            or failed.fallback_endpoint_id is None
        ):
            return None
        endpoint_ids = [endpoint.id for endpoint in endpoints]
        if len(endpoint_ids) != len(set(endpoint_ids)):
            raise _invalid_configuration(
                "Fallback graph contains duplicate endpoint IDs."
            )
        endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}
        graph_visited: set[UUID] = set()
        current: RoutableEndpoint | None = failed
        while current is not None and current.fallback_endpoint_id is not None:
            if current.id in graph_visited:
                raise _invalid_configuration("Fallback graph contains a cycle.")
            graph_visited.add(current.id)
            current = endpoint_by_id.get(current.fallback_endpoint_id)

        target = endpoint_by_id.get(failed.fallback_endpoint_id)
        if target is None:
            return None
        if (
            target.id in visited_endpoint_ids
            or not target.enabled
            or target.health_status not in {"healthy", "unknown"}
            or target.capability_id != failed.capability_id
            or target.environment != failed.environment
            or target.protocol != failed.protocol
        ):
            return None
        return target
