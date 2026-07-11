"""Gateway endpoint and invocation persistence contracts."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from pydantic import ValidationError
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
        finally:
            await connection.close()
        assert GATEWAY_TABLES <= {row["table_name"] for row in rows}
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
