"""Persist Gateway endpoints, invocations, and protocol descriptors.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "capability_endpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("environment", sa.String(length=64), server_default="local", nullable=False),
        sa.Column("release_channel", sa.String(length=64), server_default="stable", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("weight", sa.Integer(), server_default="100", nullable=False),
        sa.Column("health_status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("secret_ref", sa.String(length=512), nullable=True),
        sa.Column("tls_config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("gray_rule", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("fallback_endpoint_id", sa.UUID(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "protocol IN ('http', 'mcp', 'grpc', 'a2a', 'hosted')",
            name="ck_capability_endpoint_protocol",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_capability_endpoint_priority"),
        sa.CheckConstraint("weight > 0", name="ck_capability_endpoint_weight"),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"]),
        sa.ForeignKeyConstraint(
            ["fallback_endpoint_id", "capability_id"],
            ["capability_endpoints.id", "capability_endpoints.capability_id"],
            name="fk_capability_endpoint_fallback_same_capability",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "capability_id", "environment", "name", name="uq_capability_endpoint_environment_name"
        ),
        sa.UniqueConstraint("id", "capability_id", name="uq_capability_endpoint_id_capability"),
    )
    op.create_index(
        op.f("ix_capability_endpoints_capability_id"),
        "capability_endpoints",
        ["capability_id"],
        unique=False,
    )

    op.create_table(
        "capability_invocations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invocation_key", sa.String(length=128), nullable=False),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.Column("capability_version", sa.String(length=64), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=True),
        sa.Column("caller_type", sa.String(length=64), nullable=False),
        sa.Column("caller_id", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_hash", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("input_digest", sa.String(length=128), nullable=False),
        sa.Column("output_digest", sa.String(length=128), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("request_metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("result_metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "protocol IN ('http', 'mcp', 'grpc', 'a2a', 'hosted')",
            name="ck_capability_invocation_protocol",
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"]),
        sa.ForeignKeyConstraint(["endpoint_id"], ["capability_endpoints.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_capability_invocations_capability_id"),
        "capability_invocations",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_capability_invocations_invocation_key"),
        "capability_invocations",
        ["invocation_key"],
        unique=True,
    )
    op.create_index(
        "uq_capability_invocation_idempotency",
        "capability_invocations",
        ["capability_id", "capability_version", "caller_type", "caller_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION prevent_capability_invocation_version_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.capability_version IS DISTINCT FROM OLD.capability_version THEN
                RAISE EXCEPTION 'capability_version is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_capability_invocation_version_immutable
        BEFORE UPDATE OF capability_version ON capability_invocations
        FOR EACH ROW
        EXECUTE FUNCTION prevent_capability_invocation_version_update()
        """
    )

    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("allowed_primitives", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("allowed_tools", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "transport IN ('streamable_http', 'sse')", name="ck_mcp_server_transport"
        ),
        sa.ForeignKeyConstraint(["endpoint_id"], ["capability_endpoints.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_id"),
    )
    op.create_index(op.f("ix_mcp_servers_server_key"), "mcp_servers", ["server_key"], unique=True)

    op.create_table(
        "grpc_descriptors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("artifact_uri", sa.String(length=1024), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("services", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "source IN ('reflection', 'descriptor_set')", name="ck_grpc_descriptor_source"
        ),
        sa.CheckConstraint(
            "source <> 'descriptor_set' OR (artifact_uri IS NOT NULL AND checksum IS NOT NULL)",
            name="ck_grpc_descriptor_set_artifact",
        ),
        sa.ForeignKeyConstraint(["endpoint_id"], ["capability_endpoints.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_id", "version", name="uq_grpc_descriptor_endpoint_version"),
    )

    op.create_table(
        "a2a_agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_key", sa.String(length=128), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=False),
        sa.Column("agent_card_url", sa.String(length=1024), nullable=False),
        sa.Column("agent_card", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("supports_streaming", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_push_notifications", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("card_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["endpoint_id"], ["capability_endpoints.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_id"),
    )
    op.create_index(op.f("ix_a2a_agents_agent_key"), "a2a_agents", ["agent_key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_a2a_agents_agent_key"), table_name="a2a_agents")
    op.drop_table("a2a_agents")
    op.drop_table("grpc_descriptors")
    op.drop_index(op.f("ix_mcp_servers_server_key"), table_name="mcp_servers")
    op.drop_table("mcp_servers")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_capability_invocation_version_immutable "
        "ON capability_invocations"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_capability_invocation_version_update()")
    op.drop_index("uq_capability_invocation_idempotency", table_name="capability_invocations")
    op.drop_index(op.f("ix_capability_invocations_invocation_key"), table_name="capability_invocations")
    op.drop_index(op.f("ix_capability_invocations_capability_id"), table_name="capability_invocations")
    op.drop_table("capability_invocations")
    op.drop_index(op.f("ix_capability_endpoints_capability_id"), table_name="capability_endpoints")
    op.drop_table("capability_endpoints")
