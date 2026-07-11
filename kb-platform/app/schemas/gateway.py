"""Strict Gateway endpoint protocol configuration contracts."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


ProtocolType = Literal["http", "mcp", "grpc", "a2a", "hosted"]


class EndpointConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: ProtocolType
    target: str
    priority: int = Field(default=0, ge=0)
    weight: int = Field(default=100, gt=0)
    environment: str = "local"
    release_channel: str = "stable"
    health_status: Literal["unknown", "healthy", "unhealthy", "disabled"] = "unknown"
    secret_ref: str | None = None
    tls_config: dict[str, Any] = Field(default_factory=dict)
    gray_rule: dict[str, Any] = Field(default_factory=dict)
    fallback_endpoint_id: UUID | None = None
    enabled: bool = True


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["streamable_http", "sse"]
    allowed_primitives: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)


class GRPCDescriptorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["reflection", "descriptor_set"]
    artifact_uri: str | None = None
    checksum: str | None = None

    @model_validator(mode="after")
    def validate_descriptor_set_artifact(self) -> "GRPCDescriptorConfig":
        if self.source == "descriptor_set" and (not self.artifact_uri or not self.checksum):
            raise ValueError("descriptor_set requires artifact_uri and checksum")
        return self


class A2AAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supports_streaming: StrictBool = False
    supports_push_notifications: StrictBool = False


__all__ = [
    "A2AAgentConfig",
    "EndpointConfig",
    "GRPCDescriptorConfig",
    "MCPServerConfig",
    "ProtocolType",
]
