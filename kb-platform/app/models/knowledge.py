"""知识资产模型：知识库/文档/切片，对应文档04与文档11 2.4/2.5/2.6。"""
import uuid

from sqlalchemy import ARRAY, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Base, TimestampMixin


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    security_level: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
    # draft | parsing | indexed | published | offline（文档04 3.2 简化版）
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    retrieval_config: Mapped[dict] = mapped_column(JSONB, default=dict)

    documents: Mapped[list["Document"]] = relationship(back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="upload")
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    # uploaded -> parsing -> parsed -> chunking -> indexed -> pending_review -> published -> offline
    parse_status: Mapped[str] = mapped_column(String(64), nullable=False, default="uploaded")
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    security_level: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title_path: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    embedding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    security_level: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")
