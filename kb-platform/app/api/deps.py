"""通用依赖：身份鉴权(API Key)、trace_id 获取、数据库会话。"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.agent import AdminUser, Agent

# 用标准 APIKeyHeader 声明鉴权方案，这样 Swagger UI 右上角会出现「Authorize」按钮，
# 填一次 X-API-Key 后，/docs 里所有「Try it out」请求会自动带上该 header。
# auto_error=False：允许该依赖本身不报错，由 get_current_identity 统一处理缺失/无效的情况，
# 以便返回和文档06一致的 {code, message} 错误结构，而不是 FastAPI 默认的 403。
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass
class Identity:
    id: str
    key: str
    name: str
    role: str
    actor_type: str  # "agent" | "admin_user"
    business_domain: str | None = None


async def get_current_identity(
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: str | None = Security(_api_key_header),
) -> Identity:
    api_key = api_key or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
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
