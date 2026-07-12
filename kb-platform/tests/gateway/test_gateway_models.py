"""Gateway endpoint and invocation persistence contracts."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.core.db import Base
from app.models.capability import Capability
from app.models.gateway import CapabilityEndpoint, CapabilityInvocation
from app.schemas.gateway import (
    A2AAgentConfig,
    EndpointConfig,
    GRPCDescriptorConfig,
    MCPServerConfig,
)


GATEWAY_TABLES = {
    "capability_endpoints",
    "capability_invocations",
    "mcp_servers",
    "grpc_descriptors",
    "a2a_agents",
}


def test_unsupported_protocol_is_rejected():
    with pytest.raises(ValidationError):
        EndpointConfig(protocol="websocket", target="https://example.test")


@pytest.mark.parametrize(
    ("field", "value"),
    [("weight", 0), ("weight", -1), ("priority", -1)],
)
def test_endpoint_rejects_invalid_weight_and_priority(field, value):
    with pytest.raises(ValidationError):
        EndpointConfig(protocol="http", target="https://example.test", **{field: value})


@pytest.mark.parametrize("raw_secret", ["api_key", "token", "password"])
def test_endpoint_rejects_raw_secret_extras(raw_secret):
    with pytest.raises(ValidationError):
        EndpointConfig(
            protocol="http",
            target="https://example.test",
            **{raw_secret: "do-not-store"},
        )


def test_endpoint_accepts_secret_reference():
    config = EndpointConfig(
        protocol="http",
        target="https://example.test",
        secret_ref="vault://gateway/service",
    )
    assert config.secret_ref == "vault://gateway/service"


@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
def test_mcp_transport_accepts_supported_values(transport):
    assert MCPServerConfig(transport=transport).transport == transport


def test_mcp_transport_rejects_unsupported_value():
    with pytest.raises(ValidationError):
        MCPServerConfig(transport="stdio")


@pytest.mark.parametrize("source", ["reflection", "descriptor_set"])
def test_grpc_descriptor_accepts_supported_sources(source):
    kwargs = (
        {"artifact_uri": "s3://descriptors/service.pb", "checksum": "sha256:abc"}
        if source == "descriptor_set"
        else {}
    )
    assert GRPCDescriptorConfig(source=source, **kwargs).source == source


def test_grpc_descriptor_rejects_unsupported_source():
    with pytest.raises(ValidationError):
        GRPCDescriptorConfig(source="proto_file")


@pytest.mark.parametrize(
    "missing",
    ["artifact_uri", "checksum"],
)
def test_descriptor_set_requires_artifact_uri_and_checksum(missing):
    kwargs = {
        "source": "descriptor_set",
        "artifact_uri": "s3://descriptors/service.pb",
        "checksum": "sha256:abc",
    }
    kwargs.pop(missing)
    with pytest.raises(ValidationError):
        GRPCDescriptorConfig(**kwargs)


def test_protocol_configs_forbid_extras_and_a2a_flags_are_strict_booleans():
    with pytest.raises(ValidationError):
        MCPServerConfig(transport="sse", token="raw")
    with pytest.raises(ValidationError):
        GRPCDescriptorConfig(source="reflection", password="raw")
    with pytest.raises(ValidationError):
        A2AAgentConfig(supports_streaming="yes")


def test_sqlalchemy_metadata_contains_gateway_tables_and_constraints():
    assert GATEWAY_TABLES <= set(Base.metadata.tables)

    endpoint = Base.metadata.tables["capability_endpoints"]
    endpoint_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in endpoint.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("capability_id", "environment", "name") in endpoint_unique_columns
    assert {"fallback_endpoint_id", "capability_id"} in [
        set(constraint.columns.keys())
        for constraint in endpoint.foreign_key_constraints
    ]

    invocation = Base.metadata.tables["capability_invocations"]
    idempotency_index = next(
        index for index in invocation.indexes if index.name == "uq_capability_invocation_idempotency"
    )
    assert idempotency_index.unique is True
    assert tuple(column.name for column in idempotency_index.columns) == (
        "capability_id",
        "capability_version",
        "caller_type",
        "caller_id",
        "idempotency_key",
    )
    assert "idempotency_key IS NOT NULL" in str(
        idempotency_index.dialect_options["postgresql"]["where"]
    )


def _check_constraint_names(table_name):
    return {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    }


def _unique_column_sets(table_name):
    table = Base.metadata.tables[table_name]
    constraints = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    indexes = {
        tuple(index.columns.keys())
        for index in table.indexes
        if isinstance(index, Index) and index.unique
    }
    return constraints | indexes


def test_sqlalchemy_metadata_contains_all_gateway_checks_and_unique_indexes():
    assert {
        "ck_capability_endpoint_protocol",
        "ck_capability_endpoint_priority",
        "ck_capability_endpoint_weight",
    } <= _check_constraint_names("capability_endpoints")
    assert {("capability_id", "environment", "name")} <= _unique_column_sets(
        "capability_endpoints"
    )
    capability_index = next(
        index
        for index in Base.metadata.tables["capability_endpoints"].indexes
        if index.name == "ix_capability_endpoints_capability_id"
    )
    assert tuple(capability_index.columns.keys()) == ("capability_id",)
    assert capability_index.unique is False

    assert "ck_capability_invocation_protocol" in _check_constraint_names(
        "capability_invocations"
    )
    assert {("invocation_key",)} <= _unique_column_sets("capability_invocations")

    assert "ck_mcp_server_transport" in _check_constraint_names("mcp_servers")
    assert {("server_key",), ("endpoint_id",)} <= _unique_column_sets("mcp_servers")

    assert {
        "ck_grpc_descriptor_source",
        "ck_grpc_descriptor_set_artifact",
    } <= _check_constraint_names("grpc_descriptors")
    assert {("endpoint_id", "version")} <= _unique_column_sets("grpc_descriptors")

    assert {("agent_key",), ("endpoint_id",)} <= _unique_column_sets("a2a_agents")


async def _migration_database():
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"kbplatform_gateway_{uuid.uuid4().hex}"
    admin_url = source_url.set(database="postgres").render_as_string(hide_password=False)
    target_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    admin_dsn = admin_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    target_dsn = target_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    admin_connection = await asyncpg.connect(admin_dsn)
    await admin_connection.execute(f'CREATE DATABASE "{database_name}"')
    return database_name, target_url, target_dsn, admin_connection


async def _drop_migration_database(database_name, admin_connection):
    await admin_connection.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
        database_name,
    )
    await admin_connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    await admin_connection.close()


def _run_alembic(target_url, *args):
    env = os.environ.copy()
    env["DATABASE_URL"] = target_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=Path(__file__).parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_alembic_has_one_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert len(script.get_heads()) == 1
    assert script.get_current_head() == "0002"


@pytest.mark.asyncio
async def test_fresh_alembic_upgrade_creates_all_gateway_tables():
    database_name, target_url, target_dsn, admin_connection = await _migration_database()
    try:
        result = _run_alembic(target_url, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr
        connection = await asyncpg.connect(target_dsn)
        try:
            rows = await connection.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            constraint_rows = await connection.fetch(
                """
                SELECT conrelid::regclass::text AS table_name, conname, contype,
                       pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE conrelid = ANY($1::regclass[])
                """,
                sorted(GATEWAY_TABLES),
            )
            index_rows = await connection.fetch(
                """
                SELECT tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = ANY($1::text[])
                """,
                sorted(GATEWAY_TABLES),
            )
        finally:
            await connection.close()
        assert GATEWAY_TABLES <= {row["table_name"] for row in rows}
        constraints = {
            (row["table_name"], row["conname"]): row["definition"]
            for row in constraint_rows
        }
        assert {
            ("capability_endpoints", "ck_capability_endpoint_protocol"),
            ("capability_endpoints", "ck_capability_endpoint_priority"),
            ("capability_endpoints", "ck_capability_endpoint_weight"),
            ("capability_endpoints", "uq_capability_endpoint_environment_name"),
            ("capability_invocations", "ck_capability_invocation_protocol"),
            ("mcp_servers", "ck_mcp_server_transport"),
            ("mcp_servers", "mcp_servers_endpoint_id_key"),
            ("grpc_descriptors", "ck_grpc_descriptor_source"),
            ("grpc_descriptors", "ck_grpc_descriptor_set_artifact"),
            ("grpc_descriptors", "uq_grpc_descriptor_endpoint_version"),
            ("a2a_agents", "a2a_agents_endpoint_id_key"),
        } <= set(constraints)
        indexes = {row["indexname"]: row["indexdef"] for row in index_rows}
        endpoint_capability_index = indexes["ix_capability_endpoints_capability_id"]
        assert "CREATE INDEX" in endpoint_capability_index
        assert "UNIQUE" not in endpoint_capability_index
        assert "(capability_id)" in endpoint_capability_index
        assert "UNIQUE" in indexes["ix_capability_invocations_invocation_key"]
        assert "UNIQUE" in indexes["ix_mcp_servers_server_key"]
        assert "UNIQUE" in indexes["ix_a2a_agents_agent_key"]
        assert "WHERE (idempotency_key IS NOT NULL)" in indexes[
            "uq_capability_invocation_idempotency"
        ]
    finally:
        await _drop_migration_database(database_name, admin_connection)


@pytest.mark.asyncio
async def test_downgrade_0002_removes_only_gateway_tables():
    database_name, target_url, target_dsn, admin_connection = await _migration_database()
    try:
        upgrade = _run_alembic(target_url, "upgrade", "head")
        assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
        downgrade = _run_alembic(target_url, "downgrade", "0001")
        assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
        connection = await asyncpg.connect(target_dsn)
        try:
            rows = await connection.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        finally:
            await connection.close()
        existing = {row["table_name"] for row in rows}
        assert not (GATEWAY_TABLES & existing)
        assert {"capabilities", "agents", "knowledge_bases", "audit_logs"} <= existing
        connection = await asyncpg.connect(target_dsn)
        try:
            immutable_function = await connection.fetchval(
                "SELECT to_regprocedure('prevent_capability_invocation_version_update()')"
            )
        finally:
            await connection.close()
        assert immutable_function is None
    finally:
        await _drop_migration_database(database_name, admin_connection)


@pytest.mark.asyncio
async def test_endpoint_name_uniqueness_is_scoped_to_capability_and_environment(db_session):
    capability = Capability(capability_key="endpoint-scope", type="tool", name="Endpoint scope")
    db_session.add(capability)
    await db_session.flush()
    db_session.add_all(
        [
            CapabilityEndpoint(
                capability_id=capability.id,
                name="primary",
                protocol="http",
                target="https://local.example.test",
                environment="local",
            ),
            CapabilityEndpoint(
                capability_id=capability.id,
                name="primary",
                protocol="http",
                target="https://prod.example.test",
                environment="production",
            ),
        ]
    )
    await db_session.commit()

    db_session.add(
        CapabilityEndpoint(
            capability_id=capability.id,
            name="primary",
            protocol="http",
            target="https://duplicate.example.test",
            environment="local",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_same_endpoint_environment_and_name_are_allowed_for_different_capabilities(db_session):
    first = Capability(capability_key="endpoint-first", type="tool", name="First")
    second = Capability(capability_key="endpoint-second", type="tool", name="Second")
    db_session.add_all([first, second])
    await db_session.flush()
    db_session.add_all(
        [
            CapabilityEndpoint(
                capability_id=first.id,
                name="primary",
                protocol="http",
                target="https://first.example.test",
                environment="production",
            ),
            CapabilityEndpoint(
                capability_id=second.id,
                name="primary",
                protocol="http",
                target="https://second.example.test",
                environment="production",
            ),
        ]
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_invocation_partial_idempotency_uniqueness(db_session):
    capability = Capability(capability_key="idempotency-scope", type="tool", name="Idempotency scope")
    db_session.add(capability)
    await db_session.flush()

    def invocation(invocation_key, idempotency_key):
        return CapabilityInvocation(
            invocation_key=invocation_key,
            capability_id=capability.id,
            capability_version="1.0.0",
            caller_type="agent",
            caller_id="planner",
            idempotency_key=idempotency_key,
            status="pending",
            protocol="http",
            input_digest="sha256:input",
            output_digest="sha256:output",
        )

    db_session.add_all([invocation("null-1", None), invocation("null-2", None)])
    await db_session.commit()
    db_session.add(invocation("non-null-1", "request-1"))
    await db_session.commit()
    db_session.add(invocation("non-null-2", "request-1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_invocation_rejects_unsupported_protocol_at_persistence(db_session):
    capability = Capability(capability_key="protocol-check", type="tool", name="Protocol check")
    db_session.add(capability)
    await db_session.flush()
    db_session.add(
        CapabilityInvocation(
            invocation_key="invalid-protocol",
            capability_id=capability.id,
            capability_version="1.0.0",
            caller_type="agent",
            caller_id="planner",
            status="pending",
            protocol="websocket",
            input_digest="sha256:input",
            output_digest="sha256:output",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_migrated_database_prevents_capability_version_update_but_allows_status_update():
    database_name, target_url, target_dsn, admin_connection = await _migration_database()
    try:
        upgrade = _run_alembic(target_url, "upgrade", "head")
        assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
        connection = await asyncpg.connect(target_dsn)
        try:
            capability_id = uuid.uuid4()
            invocation_id = uuid.uuid4()
            await connection.execute(
                """
                INSERT INTO capabilities (
                    id, capability_key, type, name, tags, scenarios, input_schema,
                    output_schema, examples, security_level, allowed_agent_roles,
                    status, current_version, timeout_ms, side_effect, metadata
                ) VALUES (
                    $1, 'immutable-version', 'tool', 'Immutable version', '{}', '{}',
                    '{}', '{}', '[]', 'internal', '{}', 'published', '1.0.0',
                    30000, 'read_only', '{}'
                )
                """,
                capability_id,
            )
            await connection.execute(
                """
                INSERT INTO capability_invocations (
                    id, invocation_key, capability_id, capability_version, caller_type,
                    caller_id, status, protocol, input_digest, output_digest
                ) VALUES ($1, 'immutable-invocation', $2, '1.0.0', 'agent', 'planner',
                    'pending', 'http', 'sha256:input', 'sha256:output')
                """,
                invocation_id,
                capability_id,
            )

            with pytest.raises(asyncpg.CheckViolationError, match="capability_version is immutable"):
                await connection.execute(
                    "UPDATE capability_invocations SET capability_version = '2.0.0' WHERE id = $1",
                    invocation_id,
                )

            result = await connection.execute(
                "UPDATE capability_invocations SET status = 'completed' WHERE id = $1",
                invocation_id,
            )
            assert result == "UPDATE 1"
        finally:
            await connection.close()
    finally:
        await _drop_migration_database(database_name, admin_connection)
