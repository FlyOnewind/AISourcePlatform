"""中台集成与任务编排 schema。"""
from typing import Any

from pydantic import BaseModel, Field


class AssetCandidateCreate(BaseModel):
    asset_type: str
    content: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetCandidateOut(BaseModel):
    id: str
    candidate_key: str
    asset_type: str
    content: dict[str, Any]
    metadata: dict[str, Any]
    submitted_by: str
    status: str
    note: str | None = None

    model_config = {"from_attributes": True}


class CollaborationTaskCreate(BaseModel):
    task_spec: dict[str, Any] = Field(default_factory=dict)
    caller_agent_key: str | None = None


class CollaborationTaskOut(BaseModel):
    id: str
    task_key: str
    caller_agent_key: str
    task_spec: dict[str, Any]
    status: str
    result: dict[str, Any] | None = None
    subtask_results: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CollaborationTaskResultCreate(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class SubtaskResultCreate(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)