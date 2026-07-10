"""中台集成 API：资产候选、协作任务、任务结果回写。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity
from app.core.db import get_db
from app.core.security import new_id
from app.models.agent import Agent
from app.models.asset import AssetCandidate, CollaborationTask
from app.schemas.common import ok
from app.schemas.integration import (
    AssetCandidateCreate,
    AssetCandidateOut,
    CollaborationTaskCreate,
    CollaborationTaskOut,
    CollaborationTaskResultCreate,
    SubtaskResultCreate,
)

router = APIRouter(prefix="/api/v1", tags=["integration"])


def _asset_out(asset: AssetCandidate) -> AssetCandidateOut:
    return AssetCandidateOut(
        id=str(asset.id),
        candidate_key=asset.candidate_key,
        asset_type=asset.asset_type,
        content=asset.content or {},
        metadata=asset.metadata_ or {},
        submitted_by=asset.submitted_by,
        status=asset.status,
        note=asset.note,
    )


def _task_out(task: CollaborationTask) -> CollaborationTaskOut:
    return CollaborationTaskOut(
        id=str(task.id),
        task_key=task.task_key,
        caller_agent_key=task.caller_agent_key,
        task_spec=task.task_spec or {},
        status=task.status,
        result=task.result,
        subtask_results=task.subtask_results or [],
    )


@router.post("/asset-candidates")
async def submit_asset_candidate(
    payload: AssetCandidateCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    candidate_key = new_id("asset_candidate")
    asset = AssetCandidate(
        candidate_key=candidate_key,
        asset_type=payload.asset_type,
        content=payload.content,
        metadata_=payload.metadata,
        submitted_by=identity.key,
        status="pending",
        note="awaiting_review",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return ok(_asset_out(asset).model_dump())


@router.get("/asset-candidates")
async def list_asset_candidates(db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(AssetCandidate).order_by(AssetCandidate.created_at.desc()))
    return ok([_asset_out(item).model_dump() for item in result.scalars().all()])


@router.get("/asset-candidates/{candidate_id}")
async def get_asset_candidate(candidate_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(AssetCandidate).where(AssetCandidate.id == candidate_id))
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "资产候选不存在"})
    return ok(_asset_out(asset).model_dump())


@router.post("/collaboration-tasks")
async def create_collaboration_task(
    payload: CollaborationTaskCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    caller_agent_key = payload.caller_agent_key or identity.key
    result = await db.execute(select(Agent).where(Agent.agent_key == caller_agent_key))
    agent = result.scalar_one_or_none()
    task = CollaborationTask(
        task_key=new_id("task"),
        caller_agent_id=agent.id if agent else None,
        caller_agent_key=caller_agent_key,
        task_spec=payload.task_spec,
        status="created",
        result=None,
        subtask_results=[],
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return ok(_task_out(task).model_dump())


@router.get("/collaboration-tasks/{task_id}")
async def get_collaboration_task(task_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(CollaborationTask).where(CollaborationTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "协作任务不存在"})
    return ok(_task_out(task).model_dump())


@router.post("/collaboration-tasks/{task_id}/result")
async def report_task_result(
    task_id: str,
    payload: CollaborationTaskResultCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    result = await db.execute(select(CollaborationTask).where(CollaborationTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "协作任务不存在"})
    task.result = payload.result
    task.status = "reported"
    await db.commit()
    await db.refresh(task)
    return ok(_task_out(task).model_dump())


@router.post("/collaboration-tasks/{task_id}/subtasks/{subtask_id}/result")
async def report_subtask_result(
    task_id: str,
    subtask_id: str,
    payload: SubtaskResultCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    result = await db.execute(select(CollaborationTask).where(CollaborationTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "协作任务不存在"})
    subtask_results = list(task.subtask_results or [])
    subtask_results.append({"subtask_id": subtask_id, "result": payload.result})
    task.subtask_results = subtask_results
    await db.commit()
    await db.refresh(task)
    return ok(_task_out(task).model_dump())