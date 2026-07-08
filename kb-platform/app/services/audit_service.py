"""审计日志写入服务，对应文档07 第7节。"""
import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import new_id
from app.models.audit import AuditLog


def _digest(payload: Any) -> str:
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(
        self,
        *,
        trace_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        resource_version: str | None = None,
        decision: str = "allow",
        task_id: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        latency_ms: int | None = None,
        error_code: str | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            trace_id=trace_id,
            task_id=task_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource_version,
            decision=decision,
            input_digest=_digest(input_payload) if input_payload is not None else None,
            output_digest=_digest(output_payload) if output_payload is not None else None,
            latency_ms=latency_ms,
            error_code=error_code,
            metadata_=metadata or {},
        )
        self._db.add(entry)
        await self._db.flush()
        return entry


def gen_trace_id() -> str:
    return new_id("trace")
