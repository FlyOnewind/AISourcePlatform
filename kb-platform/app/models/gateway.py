"""Persistent Gateway control-plane endpoint and invocation models."""

import uuid

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import Base, TimestampMixin


class CapabilityEndpoint(Base, TimestampMixin):
    __tablename__ = "capability_endpoints"
    __table_args__ = (
        CheckConstraint(
            "protocol IN ('http', 'mcp', 'grpc', 'a2a', 'hosted')",
            name="ck_capability_endpoint_protocol",
        ),
        CheckConstraint("priority >= 0", name="ck_capability_endpoint_priority"),
        CheckConstraint("weight > 0", name="ck_capability_endpoint_weight"),
        UniqueConstraint(
            "capability_id", "environment", "name", name="uq_capability_endpoint_environment_name"
        ),
        UniqueConstraint("id", "capability_id", name="uq_capability_endpoint_id_capability"),
        ForeignKeyConstraint(
            ["fallback_endpoint_id", "capability_id"],
            ["capability_endpoints.id", "capability_endpoints.capability_id"],
            name="fk_capability_endpoint_fallback_same_capability",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capabilities.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False, default="local")
    release_channel: Mapped[str] = mapped_column(String(64), nullable=False, default="stable")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    secret_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tls_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    gray_rule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    fallback_endpoint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CapabilityInvocation(Base, TimestampMixin):
    __tablename__ = "capability_invocations"
    __table_args__ = (
        Index(
            "uq_capability_invocation_idempotency",
            "capability_id",
            "capability_version",
            "caller_type",
            "caller_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invocation_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    capability_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capabilities.id"), nullable=False, index=True
    )
    capability_version: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("capability_endpoints.id"), nullable=True
    )
    caller_type: Mapped[str] = mapped_column(String(64), nullable=False)
    caller_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    output_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class MCPServer(Base, TimestampMixin):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        CheckConstraint(
            "transport IN ('streamable_http', 'sse')", name="ck_mcp_server_transport"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capability_endpoints.id"), nullable=False, unique=True
    )
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed_primitives: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    allowed_tools: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class GRPCDescriptor(Base, TimestampMixin):
    __tablename__ = "grpc_descriptors"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "version", name="uq_grpc_descriptor_endpoint_version"),
        CheckConstraint(
            "source IN ('reflection', 'descriptor_set')", name="ck_grpc_descriptor_source"
        ),
        CheckConstraint(
            "source <> 'descriptor_set' OR (artifact_uri IS NOT NULL AND checksum IS NOT NULL)",
            name="ck_grpc_descriptor_set_artifact",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capability_endpoints.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    services: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class A2AAgent(Base, TimestampMixin):
    __tablename__ = "a2a_agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capability_endpoints.id"), nullable=False, unique=True
    )
    agent_card_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    agent_card: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_push_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    card_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


__all__ = [
    "A2AAgent",
    "CapabilityEndpoint",
    "CapabilityInvocation",
    "GRPCDescriptor",
    "MCPServer",
]
