"""Agent 注册表，对应文档11 2.1 agents 及文档07 RBAC Agent角色。

同时承载"存量Agent"能力类型（文档03 3.5）——一个 Agent 记录既可以是
调用中台的运行时身份，也可以作为 capability(type=agent) 被其他 Agent 发现和调用。
"""
import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import Base, TimestampMixin


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    business_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    api_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    is_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    supported_tasks: Mapped[list] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class AdminUser(Base, TimestampMixin):
    """管理后台人类用户，角色对应文档07 2.1 RBAC 基础角色（platform_admin 等）。"""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
