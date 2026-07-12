import os
import subprocess
import sys
from dataclasses import replace
from uuid import UUID

import pytest

from app.gateway.errors import GatewayError
from app.gateway.routing import EndpointRouter, RoutableEndpoint


@pytest.fixture
def router() -> EndpointRouter:
    return EndpointRouter()


@pytest.fixture
def endpoints() -> list[RoutableEndpoint]:
    capability_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    return [
        RoutableEndpoint(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            capability_id=capability_id,
            protocol="a2a",
            environment="prod",
            release_channel="gray",
            priority=10,
            weight=1,
            health_status="healthy",
            enabled=True,
            fallback_endpoint_id=None,
        ),
        RoutableEndpoint(
            id=UUID("00000000-0000-0000-0000-000000000002"),
            capability_id=capability_id,
            protocol="a2a",
            environment="prod",
            release_channel="gray",
            priority=10,
            weight=3,
            health_status="unknown",
            enabled=True,
            fallback_endpoint_id=None,
        ),
    ]


@pytest.fixture
def primary_and_backup(endpoints):
    backup = replace(endpoints[1], health_status="healthy")
    primary = replace(endpoints[0], fallback_endpoint_id=backup.id)
    return primary, backup


def test_sticky_key_selects_same_weighted_endpoint(router, endpoints):
    first = router.select(endpoints, "tenant:user:task", "prod", "gray")

    assert all(
        router.select(list(reversed(endpoints)), "tenant:user:task", "prod", "gray").id
        == first.id
        for _ in range(20)
    )


def test_different_keys_map_deterministically_through_weights(router, endpoints):
    assert router.select(endpoints, "key-0", "prod", "gray").id == endpoints[0].id
    assert router.select(endpoints, "key-2", "prod", "gray").id == endpoints[1].id


def test_only_lowest_priority_eligible_group_participates(router, endpoints):
    higher_priority = replace(
        endpoints[0],
        id=UUID("00000000-0000-0000-0000-000000000003"),
        priority=20,
        weight=100,
    )

    selected = router.select([*endpoints, higher_priority], "priority-key", "prod", "gray")

    assert selected.id in {endpoint.id for endpoint in endpoints}


@pytest.mark.parametrize(
    "ineligible_fields",
    [
        {"environment": "staging"},
        {"release_channel": "stable"},
        {"enabled": False},
        {"health_status": "unhealthy"},
        {"health_status": "disabled"},
    ],
)
def test_selection_filters_ineligible_endpoints(router, endpoints, ineligible_fields):
    eligible = replace(endpoints[0], priority=20)
    ineligible = replace(
        endpoints[1],
        priority=1,
        **ineligible_fields,
    )

    assert router.select([ineligible, eligible], "filter-key", "prod", "gray") == eligible


@pytest.mark.parametrize("candidates", [[], None])
def test_no_eligible_endpoint_raises_non_retryable_gateway_error(router, endpoints, candidates):
    candidates = (
        candidates
        if candidates is not None
        else [replace(endpoints[0], enabled=False)]
    )

    with pytest.raises(GatewayError) as caught:
        router.select(candidates, "routing-key", "prod", "gray")

    assert caught.value.code == "NO_ELIGIBLE_ENDPOINT"
    assert caught.value.retryable is False


def assert_invalid_configuration(router, endpoints, routing_key="routing-key"):
    with pytest.raises(GatewayError) as caught:
        router.select(endpoints, routing_key, "prod", "gray")

    assert caught.value.code == "INVALID_ROUTING_CONFIGURATION"
    assert caught.value.retryable is False


def test_duplicate_endpoint_ids_are_invalid(router, endpoints):
    duplicate = replace(endpoints[1], id=endpoints[0].id)

    assert_invalid_configuration(router, [endpoints[0], duplicate])


@pytest.mark.parametrize(
    "invalid_endpoint",
    [
        lambda endpoint: replace(endpoint, weight=0),
        lambda endpoint: replace(endpoint, weight=-1),
        lambda endpoint: replace(endpoint, priority=-1),
    ],
)
def test_invalid_weight_or_priority_is_invalid_configuration(router, endpoints, invalid_endpoint):
    assert_invalid_configuration(router, [invalid_endpoint(endpoints[0])])


@pytest.mark.parametrize("routing_key", ["", "   ", "\t"])
def test_blank_routing_key_is_invalid_configuration(router, endpoints, routing_key):
    assert_invalid_configuration(router, endpoints, routing_key)


def test_sha256_selection_is_stable_across_python_hash_seeds():
    script = """
from uuid import UUID
from app.gateway.routing import EndpointRouter, RoutableEndpoint

capability_id = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
common = dict(
    capability_id=capability_id,
    protocol='a2a',
    environment='prod',
    release_channel='gray',
    priority=10,
    health_status='healthy',
    enabled=True,
    fallback_endpoint_id=None,
)
endpoints = [
    RoutableEndpoint(id=UUID('00000000-0000-0000-0000-000000000001'), weight=1, **common),
    RoutableEndpoint(id=UUID('00000000-0000-0000-0000-000000000002'), weight=3, **common),
]
print(EndpointRouter().select(endpoints, 'key-2', 'prod', 'gray').id)
"""

    selections = []
    for seed in ("1", "8675309"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        selections.append(result.stdout.strip())

    assert selections == [
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000002",
    ]


@pytest.mark.parametrize(
    "error_class",
    [
        "connection_error",
        "connect_timeout",
        "read_timeout",
        "service_unavailable",
        "circuit_open",
    ],
)
def test_explicit_healthy_same_capability_fallback_is_selected_for_transient_error(
    router, primary_and_backup, error_class
):
    primary, backup = primary_and_backup

    assert router.fallback(primary, [primary, backup], error_class) == backup


@pytest.mark.parametrize(
    "error_class",
    [
        "schema_input_error",
        "schema_output_error",
        "provider_contract_error",
        "authentication_error",
        "authorization_error",
        "risk_rejected",
        "cancelled",
        "unknown_error",
    ],
)
def test_non_transient_error_never_fails_over(router, primary_and_backup, error_class):
    primary, backup = primary_and_backup

    assert router.fallback(primary, [primary, backup], error_class) is None


def test_missing_fallback_relationship_or_target_returns_none(router, primary_and_backup):
    primary, backup = primary_and_backup

    no_relationship = replace(primary, fallback_endpoint_id=None)
    assert router.fallback(
        no_relationship, [primary, backup], "read_timeout"
    ) is None
    assert router.fallback(primary, [primary], "read_timeout") is None


@pytest.mark.parametrize(
    "backup_fields",
    [
        {"enabled": False},
        {"health_status": "unhealthy"},
        {"health_status": "disabled"},
        {"health_status": "degraded"},
        {"capability_id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")},
        {"environment": "staging"},
        {"protocol": "mcp"},
    ],
)
def test_ineligible_or_incompatible_fallback_returns_none(
    router, primary_and_backup, backup_fields
):
    primary, backup = primary_and_backup
    backup = replace(backup, **backup_fields)

    assert router.fallback(primary, [primary, backup], "read_timeout") is None


def test_visited_fallback_returns_none(router, primary_and_backup):
    primary, backup = primary_and_backup

    assert router.fallback(
        primary,
        [primary, backup],
        "read_timeout",
        visited_endpoint_ids={backup.id},
    ) is None


def test_self_fallback_is_invalid_configuration(router, endpoints):
    primary = replace(endpoints[0], fallback_endpoint_id=endpoints[0].id)

    with pytest.raises(GatewayError) as caught:
        router.fallback(primary, [primary], "read_timeout")

    assert caught.value.code == "INVALID_ROUTING_CONFIGURATION"
    assert caught.value.retryable is False


def test_multi_node_fallback_cycle_is_invalid_configuration(router, primary_and_backup):
    primary, backup = primary_and_backup
    third = replace(
        backup,
        id=UUID("00000000-0000-0000-0000-000000000003"),
        fallback_endpoint_id=primary.id,
    )
    backup = replace(backup, fallback_endpoint_id=third.id)

    with pytest.raises(GatewayError) as caught:
        router.fallback(
            primary,
            [primary, backup, third],
            "read_timeout",
            visited_endpoint_ids={primary.id},
        )

    assert caught.value.code == "INVALID_ROUTING_CONFIGURATION"
    assert caught.value.retryable is False
