"""能力注册中心API：注册/检索/调用/发布，对应文档11 3.2 与文档06。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity, get_task_id, get_trace_id, require_admin_roles
from app.core.db import get_db
from app.models.capability import Capability, CapabilityVersion
from app.schemas.capability import (
    CapabilityCreate,
    CapabilityHit,
    CapabilityInvokeRequest,
    CapabilityInvokeResponse,
    CapabilityOut,
    CapabilitySearchRequest,
    CapabilitySearchResponse,
    PublishRequest,
    RecommendedStep,
    UsageInfo,
)
from app.schemas.common import ok
from app.services.audit_service import AuditService
from app.services.capability_service import CapabilityNotFoundError, CapabilityService
from app.services.llm.factory import get_llm_provider
from app.services.policy_service import PolicyService, Resource, Subject

router = APIRouter(prefix="/api/v1/capabilities", tags=["capabilities"])


def _to_out(cap: Capability) -> CapabilityOut:
    return CapabilityOut(
        id=str(cap.id),
        capability_key=cap.capability_key,
        type=cap.type,
        name=cap.name,
        description=cap.description,
        business_domain=cap.business_domain,
        tags=cap.tags or [],
        security_level=cap.security_level,
        owner_department=cap.owner_department,
        status=cap.status,
        current_version=cap.current_version,
        input_schema=cap.input_schema or {},
        output_schema=cap.output_schema or {},
    )


@router.post("")
async def create_capability(
    payload: CapabilityCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    existing = await db.execute(select(Capability).where(Capability.capability_key == payload.capability_key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "409001", "message": "capability_key 已存在"})
    if not payload.owner_department and not payload.owner_user:
        raise HTTPException(status_code=422, detail={"code": "422001", "message": "能力必须有 Owner（文档03第9节要求）"})

    data = payload.model_dump()
    data["metadata_"] = data.pop("metadata")
    cap = Capability(**data)
    db.add(cap)
    await db.flush()
    db.add(CapabilityVersion(capability_id=cap.id, version=cap.current_version, config=data, status="draft"))
    await db.commit()
    await db.refresh(cap)
    return ok(_to_out(cap).model_dump())


@router.get("")
async def list_capabilities(
    type: str | None = None,
    business_domain: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    stmt = select(Capability)
    if type:
        stmt = stmt.where(Capability.type == type)
    if business_domain:
        stmt = stmt.where(Capability.business_domain == business_domain)
    if status:
        stmt = stmt.where(Capability.status == status)
    result = await db.execute(stmt)
    caps = result.scalars().all()
    return ok([_to_out(c).model_dump() for c in caps])


@router.get("/{capability_id}")
async def get_capability(
    capability_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)
):
    result = await db.execute(select(Capability).where(Capability.id == capability_id))
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "能力不存在"})
    return ok(_to_out(cap).model_dump())


@router.patch("/{capability_id}")
async def update_capability(
    capability_id: str,
    payload: CapabilityCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    result = await db.execute(select(Capability).where(Capability.id == capability_id))
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "能力不存在"})
    data = payload.model_dump(exclude={"capability_key"})
    data["metadata_"] = data.pop("metadata")
    for k, v in data.items():
        setattr(cap, k, v)
    await db.commit()
    await db.refresh(cap)
    return ok(_to_out(cap).model_dump())


@router.post("/search")
async def search_capabilities(
    payload: CapabilitySearchRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    trace_id: str = Depends(get_trace_id),
):
    service = CapabilityService(db, get_llm_provider())
    subject = Subject(agent_role=identity.role, business_domain=identity.business_domain)
    scored, _ = await service.search(subject, payload.task, payload.keywords, payload.top_k, payload.filters)

    hits = [
        CapabilityHit(
            capability_id=str(cap.id),
            capability_key=cap.capability_key,
            type=cap.type,
            name=cap.name,
            description=cap.description,
            score=score,
            why_recommended=reason,
            input_schema=cap.input_schema or {},
            version=cap.current_version,
        )
        for cap, score, reason in scored
    ]
    plan = [
        RecommendedStep(step=i + 1, capability_id=str(cap.id), capability_key=cap.capability_key, reason=reason)
        for i, (cap, _, reason) in enumerate(scored)
    ]

    audit = AuditService(db)
    await audit.log(
        trace_id=trace_id,
        actor_type=identity.actor_type,
        actor_id=identity.key,
        action="search_capabilities",
        resource_type="capability",
        input_payload=payload.model_dump(),
        output_payload={"count": len(hits)},
    )
    await db.commit()

    response = CapabilitySearchResponse(trace_id=trace_id, capabilities=hits, recommended_plan=plan)
    return ok(response.model_dump())


@router.post("/{capability_id}/invoke")
async def invoke_capability(
    capability_id: str,
    payload: CapabilityInvokeRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    trace_id: str = Depends(get_trace_id),
    task_id: str | None = Depends(get_task_id),
):
    service = CapabilityService(db, get_llm_provider())
    audit = AuditService(db)
    subject = Subject(agent_role=identity.role, business_domain=identity.business_domain)

    try:
        cap = await service.get_capability(capability_id)
    except CapabilityNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "能力不存在"}) from None

    if cap.status not in ("published", "gray"):
        raise HTTPException(status_code=403, detail={"code": "403001", "message": f"能力当前状态为 {cap.status}，不可调用"})

    if cap.allowed_agent_roles and identity.role not in cap.allowed_agent_roles and identity.role != "master_agent":
        await audit.log(
            trace_id=trace_id, actor_type=identity.actor_type, actor_id=identity.key, action="invoke_capability",
            resource_type=cap.type, resource_id=cap.capability_key, decision="deny", error_code="403001",
        )
        await db.commit()
        raise HTTPException(status_code=403, detail={"code": "403001", "message": "Agent 无权限调用该能力"})

    policy_service = PolicyService(db)
    allowed, reason = await policy_service.evaluate(
        subject,
        Resource(capability_type=cap.type, business_domain=cap.business_domain, security_level=cap.security_level),
        "invoke",
        context=payload.context,
    )
    if not allowed:
        await audit.log(
            trace_id=trace_id, actor_type=identity.actor_type, actor_id=identity.key, action="invoke_capability",
            resource_type=cap.type, resource_id=cap.capability_key, decision="deny", error_code="403001",
            metadata={"reason": reason},
        )
        await db.commit()
        raise HTTPException(status_code=403, detail={"code": "403001", "message": f"策略拒绝: {reason}"})

    try:
        output, latency_ms = await service.invoke(subject, cap, payload.input, payload.context)
        success = "error" not in output
    except Exception as exc:  # noqa: BLE001
        output, latency_ms, success = {"error": str(exc)}, 0, False

    await audit.log(
        trace_id=trace_id,
        task_id=task_id,
        actor_type=identity.actor_type,
        actor_id=identity.key,
        action="invoke_capability",
        resource_type=cap.type,
        resource_id=cap.capability_key,
        resource_version=cap.current_version,
        decision="allow",
        input_payload=payload.input,
        output_payload=output,
        latency_ms=latency_ms,
        error_code=None if success else "500001",
    )
    await db.commit()

    response = CapabilityInvokeResponse(
        success=success,
        capability_id=str(cap.id),
        capability_key=cap.capability_key,
        version=cap.current_version,
        output=output if success else {},
        citations=output.get("citations", []) if isinstance(output, dict) else [],
        error=output.get("error") if not success else None,
        usage=UsageInfo(latency_ms=latency_ms),
        trace_id=trace_id,
    )
    return ok(response.model_dump())


@router.post("/{capability_id}/publish")
async def publish_capability(
    capability_id: str,
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
    trace_id: str = Depends(get_trace_id),
):
    result = await db.execute(select(Capability).where(Capability.id == capability_id))
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "能力不存在"})
    if not cap.input_schema or not cap.output_schema:
        raise HTTPException(status_code=422, detail={"code": "422001", "message": "能力必须有输入输出Schema才能发布"})

    new_version = payload.version or cap.current_version
    cap.status = "published"
    cap.current_version = new_version
    db.add(CapabilityVersion(capability_id=cap.id, version=new_version, config={}, status="published", release_notes=payload.release_notes))

    audit = AuditService(db)
    await audit.log(
        trace_id=trace_id, actor_type=identity.actor_type, actor_id=identity.key, action="publish_capability",
        resource_type=cap.type, resource_id=cap.capability_key, resource_version=new_version,
    )
    await db.commit()
    await db.refresh(cap)
    return ok(_to_out(cap).model_dump())


@router.post("/{capability_id}/rollback")
async def rollback_capability(
    capability_id: str,
    target_version: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    result = await db.execute(select(Capability).where(Capability.id == capability_id))
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "能力不存在"})
    version_result = await db.execute(
        select(CapabilityVersion).where(
            CapabilityVersion.capability_id == cap.id, CapabilityVersion.version == target_version
        )
    )
    if version_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "目标版本不存在"})
    cap.current_version = target_version
    await db.commit()
    await db.refresh(cap)
    return ok(_to_out(cap).model_dump())


@router.post("/{capability_id}/disable")
async def disable_capability(
    capability_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    result = await db.execute(select(Capability).where(Capability.id == capability_id))
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "能力不存在"})
    cap.status = "disabled"
    await db.commit()
    return ok({"capability_id": capability_id, "status": "disabled"})
