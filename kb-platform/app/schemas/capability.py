"""能力注册/检索/调用 schema，对应文档03 与文档06。"""
from typing import Any

from pydantic import BaseModel, Field


class CapabilityCreate(BaseModel):
    capability_key: str
    type: str  # knowledge_base | tool | skill | prompt | agent | workflow
    name: str
    description: str | None = None
    business_domain: str | None = None
    tags: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    examples: list[Any] = Field(default_factory=list)
    security_level: str = "internal"
    owner_department: str | None = None
    owner_user: str | None = None
    allowed_agent_roles: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    timeout_ms: int = 30000
    side_effect: str = "read_only"
    ref_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityOut(BaseModel):
    id: str
    capability_key: str
    type: str
    name: str
    description: str | None
    business_domain: str | None
    tags: list[str]
    security_level: str
    owner_department: str | None
    status: str
    current_version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    model_config = {"from_attributes": True}


class CapabilityDetailOut(CapabilityOut):
    scenarios: list[str]
    examples: list[Any]
    owner_user: str | None = None
    allowed_agent_roles: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    timeout_ms: int = 30000
    side_effect: str = "read_only"
    ref_id: str | None = None
    current_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilitySearchRequest(BaseModel):
    task: str
    keywords: list[str] = Field(default_factory=list)
    business_context: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    top_k: int = 10


class RecommendedStep(BaseModel):
    step: int
    capability_id: str
    capability_key: str
    reason: str


class CapabilityHit(BaseModel):
    capability_id: str
    capability_key: str
    type: str
    name: str
    description: str | None
    score: float
    why_recommended: str
    input_schema: dict[str, Any]
    version: str


class CapabilitySearchResponse(BaseModel):
    trace_id: str
    capabilities: list[CapabilityHit]
    recommended_plan: list[RecommendedStep]


class CapabilityInvokeRequest(BaseModel):
    task_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class UsageInfo(BaseModel):
    latency_ms: int
    tokens: int = 0
    cost: float = 0.0


class CapabilityInvokeResponse(BaseModel):
    success: bool
    capability_id: str
    capability_key: str
    version: str
    output: dict[str, Any] = Field(default_factory=dict)
    citations: list[Any] = Field(default_factory=list)
    error: str | None = None
    usage: UsageInfo
    trace_id: str


class PublishRequest(BaseModel):
    version: str | None = None
    release_notes: str | None = None


class CapabilityPermissionCreate(BaseModel):
    subject_type: str
    subject_code: str
    permission: str
    conditions: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class CapabilityPermissionOut(BaseModel):
    id: str
    capability_id: str
    subject_type: str
    subject_code: str
    permission: str
    conditions: dict[str, Any]
    status: str

    model_config = {"from_attributes": True}
