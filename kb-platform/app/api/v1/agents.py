"""Agent 注册与发现，对应文档11 3.1 与文档09 discover_agents。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity, require_admin_roles
from app.core.db import get_db
from app.core.security import generate_api_key
from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentOut, AgentUpdate
from app.schemas.common import ok

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _to_out(agent: Agent, reveal_key: bool = False) -> AgentOut:
    return AgentOut(
        id=str(agent.id),
        agent_key=agent.agent_key,
        name=agent.name,
        role=agent.role,
        business_domain=agent.business_domain,
        owner_department=agent.owner_department,
        status=agent.status,
        is_master=agent.is_master,
        api_key=agent.api_key if reveal_key else None,
        supported_tasks=agent.supported_tasks or [],
    )


@router.post("")
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    existing = await db.execute(select(Agent).where(Agent.agent_key == payload.agent_key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "409001", "message": "agent_key 已存在"})

    agent = Agent(**payload.model_dump(), api_key=generate_api_key("agent"))
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return ok(_to_out(agent, reveal_key=True).model_dump())


@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(Agent))
    agents = result.scalars().all()
    return ok([_to_out(a).model_dump() for a in agents])


@router.get("/discover")
async def discover_agents(
    domain: str | None = None,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    """主控Agent查询可协作子Agent，对应文档06 client.discover_agents 与文档09 4节。"""
    stmt = select(Agent).where(Agent.status == "active", Agent.is_master.is_(False))
    if domain:
        stmt = stmt.where(Agent.business_domain == domain)
    result = await db.execute(stmt)
    agents = result.scalars().all()
    return ok([_to_out(a).model_dump() for a in agents])


@router.get("/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Agent 不存在"})
    return ok(_to_out(agent).model_dump())


@router.patch("/{agent_id}")
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Agent 不存在"})
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(agent, k, v)
    await db.commit()
    await db.refresh(agent)
    return ok(_to_out(agent).model_dump())


@router.post("/{agent_id}/rotate-key")
async def rotate_key(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin")),
):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Agent 不存在"})
    agent.api_key = generate_api_key("agent")
    await db.commit()
    await db.refresh(agent)
    return ok(_to_out(agent, reveal_key=True).model_dump())


@router.post("/{agent_id}/disable")
async def disable_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin")),
):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "Agent 不存在"})
    agent.status = "disabled"
    await db.commit()
    return ok({"agent_id": agent_id, "status": "disabled"})
