"""Skill管理与调试API，对应文档11 3.4。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity, get_trace_id, require_admin_roles
from app.core.db import get_db
from app.models.skill import Skill
from app.schemas.common import ok
from app.schemas.skill import (
    SkillCreate,
    SkillDetailOut,
    SkillEvaluateRequest,
    SkillInvokeRequest,
    SkillOut,
)
from app.services.audit_service import AuditService
from app.services.llm.factory import get_llm_provider
from app.services.skill_runtime import SkillExecutionError, SkillRuntime

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _to_out(skill: Skill) -> SkillOut:
    return SkillOut(
        id=str(skill.id), skill_key=skill.skill_key, name=skill.name, type=skill.type,
        version=skill.version, status=skill.status, dependencies=skill.dependencies or [],
    )


@router.post("")
async def create_skill(
    payload: SkillCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    existing = await db.execute(select(Skill).where(Skill.skill_key == payload.skill_key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "409001", "message": "skill_key 已存在"})
    skill = Skill(**payload.model_dump())
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return ok(_to_out(skill).model_dump())


@router.get("")
async def list_skills(db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(Skill))
    return ok([_to_out(s).model_dump() for s in result.scalars().all()])


@router.get("/{skill_id}")
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Skill 不存在"})
    return ok(
        SkillDetailOut(
            **_to_out(skill).model_dump(),
            description=skill.description,
            business_domain=skill.business_domain,
            input_schema=skill.input_schema or {},
            output_schema=skill.output_schema or {},
            allowed_agent_roles=skill.allowed_agent_roles or [],
            prompt_key=skill.prompt_key,
        ).model_dump()
    )


@router.post("/{skill_id}/invoke")
async def invoke_skill(
    skill_id: str,
    payload: SkillInvokeRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    trace_id: str = Depends(get_trace_id),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Skill 不存在"})
    if skill.allowed_agent_roles and identity.role not in skill.allowed_agent_roles and identity.role != "master_agent":
        raise HTTPException(status_code=403, detail={"code": "403001", "message": "无权限调用该 Skill"})

    runtime = SkillRuntime(db, get_llm_provider())
    try:
        output = await runtime.execute(skill, payload.input, payload.context)
        success = True
    except SkillExecutionError as exc:
        output, success = {"error": str(exc)}, False

    audit = AuditService(db)
    await audit.log(
        trace_id=trace_id, actor_type=identity.actor_type, actor_id=identity.key, action="invoke_skill",
        resource_type="skill", resource_id=skill.skill_key, resource_version=skill.version,
        input_payload=payload.input, output_payload=output, error_code=None if success else "500001",
    )
    await db.commit()
    return ok({"success": success, "skill_id": skill_id, "version": skill.version, "output": output, "trace_id": trace_id})


@router.post("/{skill_id}/evaluate")
async def evaluate_skill(
    skill_id: str,
    payload: SkillEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    """V1 简化版评估：逐条跑 test_cases 并返回原始输出，暂无自动打分模型（后续待办，见README）。"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Skill 不存在"})
    runtime = SkillRuntime(db, get_llm_provider())
    results = []
    for case in payload.test_cases:
        try:
            output = await runtime.execute(skill, case.get("input", {}), case.get("context", {}))
            results.append({"input": case.get("input", {}), "output": output, "success": True})
        except SkillExecutionError as exc:
            results.append({"input": case.get("input", {}), "error": str(exc), "success": False})
    return ok({"skill_id": skill_id, "results": results})


@router.post("/{skill_id}/publish")
async def publish_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Skill 不存在"})
    if not skill.input_schema or not skill.output_schema:
        raise HTTPException(status_code=422, detail={"code": "422001", "message": "Skill 必须有输入输出Schema才能发布"})
    skill.status = "published"
    await db.commit()
    return ok({"skill_id": skill_id, "status": "published"})
