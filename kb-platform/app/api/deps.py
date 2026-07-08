"""通用依赖：身份鉴权(API Key)、trace_id 获取、数据库会话。"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.agent import AdminUser, Agent


@dataclass
class Identity:
    id: str
    key: str
    name: str
    role: str
    actor_type: str  # "agent" | "admin_user"
    business_domain: str | None = None


async def get_current_identity(request: Request, db: AsyncSession = Depends(get_db)) -> Identity:
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not api_key:
        raise HTTPException(status_code=401, detail={"code": "401001", "message": "缺少 API Key，Agent 未认证"})

    result = await db.execute(select(Agent).where(Agent.api_key == api_key))
    agent = result.scalar_one_or_none()
    if agent is not None:
        if agent.status != "active":
            raise HTTPException(status_code=401, detail={"code": "401001", "message": f"Agent 状态为 {agent.status}，已停用"})
        return Identity(
            id=str(agent.id),
            key=agent.agent_key,
            name=agent.name,
            role=agent.role,
            actor_type="agent",
            business_domain=agent.business_domain,
        )

    result = await db.execute(select(AdminUser).where(AdminUser.api_key == api_key))
    admin = result.scalar_one_or_none()
    if admin is not None:
        if admin.status != "active":
            raise HTTPException(status_code=401, detail={"code": "401001", "message": "管理员账号已停用"})
        return Identity(id=str(admin.id), key=admin.username, name=admin.display_name, role=admin.role, actor_type="admin_user")

    raise HTTPException(status_code=401, detail={"code": "401001", "message": "无效的 API Key"})


def require_admin_roles(*roles: str):
    async def _check(identity: Identity = Depends(get_current_identity)) -> Identity:
        if identity.actor_type != "admin_user" or identity.role not in roles:
            raise HTTPException(status_code=403, detail={"code": "403001", "message": "无权限执行此操作"})
        return identity

    return _check


def get_trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "")


def get_task_id(request: Request) -> str | None:
    return getattr(request.state, "task_id", None)
