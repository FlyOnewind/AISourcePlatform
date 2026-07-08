"""Skill 资产模型，对应文档05。"""
import uuid

from sqlalchemy import ARRAY, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import Base, TimestampMixin


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # prompt_skill | rag_skill | tool_skill | workflow_skill | agent_skill
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    business_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    dependencies: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    """依赖的其他 capability_key，如 kb_product / tool_forbidden_word_check。"""
    allowed_agent_roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    prompt_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """prompt_skill/rag_skill 依赖的 PromptTemplate.prompt_key。"""
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class PromptTemplate(Base, TimestampMixin):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, default=list)
    model_config_: Mapped[dict] = mapped_column("model_config", JSONB, default=dict)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
