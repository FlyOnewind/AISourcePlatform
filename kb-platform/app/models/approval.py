"""审批工单，对应文档07 第6节。V1 仅提供数据结构与基础流转 API，
不做审批节点自动路由（提交人->Owner->安全合规->平台管理员）的自动化，
当前实现为单节点人工审批，多级审批留作后续待办。
"""
import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import Base, TimestampMixin


class ApprovalTicket(Base, TimestampMixin):
    __tablename__ = "approval_tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # capability_publish | knowledge_publish | skill_gray_release | permission_grant | tool_write_online
    ticket_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    applicant: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending|approved|rejected
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
