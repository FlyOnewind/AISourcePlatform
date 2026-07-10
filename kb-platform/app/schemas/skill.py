"""Skill/Prompt schema，对应文档05与文档11 3.4/3.5。"""
from typing import Any

from pydantic import BaseModel, Field


class SkillCreate(BaseModel):
    skill_key: str
    name: str
    description: str | None = None
    type: str  # prompt_skill | rag_skill | tool_skill | workflow_skill | agent_skill
    business_domain: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    allowed_agent_roles: list[str] = Field(default_factory=list)
    prompt_key: str | None = None


class SkillOut(BaseModel):
    id: str
    skill_key: str
    name: str
    type: str
    version: str
    status: str
    dependencies: list[str]

    model_config = {"from_attributes": True}


class SkillDetailOut(SkillOut):
    description: str | None = None
    business_domain: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_agent_roles: list[str] = Field(default_factory=list)
    prompt_key: str | None = None


class SkillInvokeRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class SkillEvaluateRequest(BaseModel):
    test_cases: list[dict[str, Any]] = Field(default_factory=list)


class PromptCreate(BaseModel):
    prompt_key: str
    name: str
    template: str
    variables: list[dict[str, Any]] = Field(default_factory=list)
    model_config_data: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    owner: str | None = None

    model_config = {"populate_by_name": True}


class PromptOut(BaseModel):
    id: str
    prompt_key: str
    name: str
    version: str
    status: str
    owner: str | None

    model_config = {"from_attributes": True}


class PromptDetailOut(PromptOut):
    template: str
    variables: list[dict[str, Any]] = Field(default_factory=list)
    model_config_data: dict[str, Any] = Field(default_factory=dict, alias="model_config")


class PromptRenderRequest(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None


class PromptRenderResponse(BaseModel):
    prompt_id: str
    version: str
    rendered: str
