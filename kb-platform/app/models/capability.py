"""能力注册中心核心模型，对应文档03 与文档11 2.2/2.3。"""
import uuid

from sqlalchemy import ARRAY, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Base, TimestampMixin


class Capability(Base, TimestampMixin):
    """统一能力元数据。type: knowledge_base | tool | skill | prompt | agent | workflow。"""

    __tablename__ = "capabilities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_domain: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    scenarios: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    examples: Mapped[list] = mapped_column(JSONB, default=list)
    security_level: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
    owner_department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allowed_agent_roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    current_version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)
    # side_effect: read_only | write | approval_required（文档03 3.2 Tool定义）
    side_effect: Mapped[str] = mapped_column(String(32), nullable=False, default="read_only")
    ref_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """指向具体实现表的外键（如 skill_id / prompt_id / knowledge_base_id / agent_id），
    knowledge_base/skill/prompt/agent 四类能力据此找到真正的执行实体；tool 类型自身即为执行单元。"""
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    versions: Mapped[list["CapabilityVersion"]] = relationship(back_populates="capability", cascade="all, delete-orphan")


class CapabilityVersion(Base, TimestampMixin):
    __tablename__ = "capability_versions"
    __table_args__ = (UniqueConstraint("capability_id", "version", name="uq_capability_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("capabilities.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    capability: Mapped[Capability] = relationship(back_populates="versions")
