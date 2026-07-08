"""审计日志查询 schema，对应文档11 3.6。"""
from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: str
    trace_id: str
    task_id: str | None
    actor_type: str
    actor_id: str
    action: str
    resource_type: str | None
    resource_id: str | None
    resource_version: str | None
    decision: str
    latency_ms: int | None
    error_code: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TraceDetail(BaseModel):
    trace_id: str
    spans: list[AuditLogOut]
