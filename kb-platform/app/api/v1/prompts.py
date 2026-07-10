"""Prompt管理API，对应文档11 3.5。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity, require_admin_roles
from app.core.db import get_db
from app.models.skill import PromptTemplate
from app.schemas.common import ok
from app.schemas.skill import PromptCreate, PromptDetailOut, PromptOut, PromptRenderRequest, PromptRenderResponse
from app.services.prompt_service import PromptRenderError, render_prompt

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


def _to_out(p: PromptTemplate) -> PromptOut:
    return PromptOut(id=str(p.id), prompt_key=p.prompt_key, name=p.name, version=p.version, status=p.status, owner=p.owner)


@router.get("/{prompt_id}")
async def get_prompt(prompt_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Prompt 不存在"})
    return ok(
        PromptDetailOut(
            **_to_out(prompt).model_dump(),
            template=prompt.template,
            variables=prompt.variables or [],
            model_config_data=prompt.model_config_ or {},
        ).model_dump()
    )


@router.post("")
async def create_prompt(
    payload: PromptCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    existing = await db.execute(select(PromptTemplate).where(PromptTemplate.prompt_key == payload.prompt_key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "409001", "message": "prompt_key 已存在"})
    data = payload.model_dump(by_alias=False)
    model_cfg = data.pop("model_config_data")
    prompt = PromptTemplate(**data, model_config_=model_cfg)
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return ok(_to_out(prompt).model_dump())


@router.get("")
async def list_prompts(db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(PromptTemplate))
    return ok([_to_out(p).model_dump() for p in result.scalars().all()])


@router.get("/{prompt_id}")
async def get_prompt(prompt_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Prompt 不存在"})
    return ok(_to_out(prompt).model_dump())


@router.post("/{prompt_id}/render")
async def render_prompt_endpoint(
    prompt_id: str,
    payload: PromptRenderRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Prompt 不存在"})
    try:
        rendered = render_prompt(prompt, payload.variables)
    except PromptRenderError as exc:
        raise HTTPException(status_code=422, detail={"code": "422001", "message": str(exc)}) from None
    return ok(PromptRenderResponse(prompt_id=prompt_id, version=prompt.version, rendered=rendered).model_dump())


@router.post("/{prompt_id}/publish")
async def publish_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Prompt 不存在"})
    prompt.status = "published"
    await db.commit()
    return ok({"prompt_id": prompt_id, "status": "published"})
