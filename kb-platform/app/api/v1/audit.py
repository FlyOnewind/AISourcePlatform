"""审计日志与Trace查询、总览指标，对应文档11 3.6 与文档08首页看板。"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity, require_admin_roles
from app.core.db import get_db
from app.models.agent import Agent
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.knowledge import Document, KnowledgeBase
from app.schemas.audit import AuditLogOut, TraceDetail
from app.schemas.common import ok

router = APIRouter(tags=["audit"])


def _to_out(a: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=str(a.id), trace_id=a.trace_id, task_id=a.task_id, actor_type=a.actor_type, actor_id=a.actor_id,
        action=a.action, resource_type=a.resource_type, resource_id=a.resource_id, resource_version=a.resource_version,
        decision=a.decision, latency_ms=a.latency_ms, error_code=a.error_code, created_at=a.created_at,
    )


@router.get("/api/v1/audit-logs")
async def list_audit_logs(
    actor_id: str | None = None,
    action: str | None = None,
    limit: int = Query(default=50, le=500),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "security_admin", "auditor")),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    result = await db.execute(stmt)
    return ok([_to_out(a).model_dump() for a in result.scalars().all()])


@router.get("/api/v1/traces/{trace_id}")
async def get_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    result = await db.execute(select(AuditLog).where(AuditLog.trace_id == trace_id).order_by(AuditLog.created_at))
    spans = [_to_out(a) for a in result.scalars().all()]
    return ok(TraceDetail(trace_id=trace_id, spans=spans).model_dump())


@router.get("/api/v1/metrics/overview")
async def metrics_overview(
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    total_caps = (await db.execute(select(func.count()).select_from(Capability))).scalar_one()
    published_caps = (
        await db.execute(select(func.count()).select_from(Capability).where(Capability.status == "published"))
    ).scalar_one()
    total_kbs = (await db.execute(select(func.count()).select_from(KnowledgeBase))).scalar_one()
    total_docs = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    total_agents = (await db.execute(select(func.count()).select_from(Agent))).scalar_one()

    since = datetime.now(UTC) - timedelta(days=1)
    today_calls = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "invoke_capability", AuditLog.created_at >= since)
        )
    ).scalar_one()
    today_errors = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "invoke_capability", AuditLog.created_at >= since, AuditLog.error_code.is_not(None)
            )
        )
    ).scalar_one()
    success_rate = 1.0 if today_calls == 0 else round(1 - today_errors / today_calls, 4)

    avg_latency = (
        await db.execute(
            select(func.avg(AuditLog.latency_ms)).where(AuditLog.action == "invoke_capability", AuditLog.created_at >= since)
        )
    ).scalar_one()

    return ok(
        {
            "total_capabilities": total_caps,
            "published_capabilities": published_caps,
            "total_knowledge_bases": total_kbs,
            "total_documents": total_docs,
            "total_agents": total_agents,
            "today_invocations": today_calls,
            "today_success_rate": success_rate,
            "avg_latency_ms": round(avg_latency, 1) if avg_latency else 0,
        }
    )
