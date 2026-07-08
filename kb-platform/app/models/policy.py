"""RBAC/ABAC 策略模型，对应文档07 第2节。"""
import uuid

from sqlalchemy import ARRAY, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import Base, TimestampMixin


class Policy(Base, TimestampMixin):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    effect: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")  # allow | deny
    subject: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    """如 {"agent_role": ["finance_agent", "master_agent"]}"""
    resource: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    """如 {"capability_type": "tool", "business_domain": "finance", "security_level": ["internal"]}"""
    actions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)  # search/invoke/read/...
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
