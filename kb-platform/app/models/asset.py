"""中台协作与资产候选模型。"""
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Base, TimestampMixin


class AssetCandidate(Base, TimestampMixin):
    __tablename__ = "asset_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    submitted_by: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollaborationTask(Base, TimestampMixin):
    __tablename__ = "collaboration_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    caller_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    caller_agent_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    task_spec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    subtask_results: Mapped[list] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    caller_agent = relationship("Agent")