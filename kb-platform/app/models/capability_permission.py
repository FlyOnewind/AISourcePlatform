"""能力权限模型，对应文档13 的 capability_permissions 表。"""
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Base, TimestampMixin


class CapabilityPermission(Base, TimestampMixin):
    __tablename__ = "capability_permissions"
    __table_args__ = (
        UniqueConstraint(
            "capability_id",
            "subject_type",
            "subject_code",
            "permission",
            name="uq_capability_permission_subject",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("capabilities.id"), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    subject_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    capability = relationship("Capability")