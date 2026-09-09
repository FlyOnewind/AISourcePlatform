"""数据库 ORM 模型定义 — SQLAlchemy declarative_base 映射。

定义六张表的列结构：
- documents: 文档主表
- parsed_elements: 解析元素表
- assets: 资源文件表
- knowledge_chunks: 知识块表
- ingest_jobs: 入库任务表
- search_logs: 搜索请求记录表

表结构由 scripts/setup_services.py 一次性创建，项目代码不再自动建表。
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()
JSONBType = JSONB


def _now() -> datetime:
    """返回当前 UTC 时间，作为 created_at / updated_at 的默认值工厂函数。"""
    return datetime.now(timezone.utc)


# ── 数据库模型 ──────────────────────────────────────────────────────


class DbDocument(Base):
    """文档 ORM 模型 — 对应 documents 表。"""

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_source_hash_active", "source_hash", unique=True,
              postgresql_where=text("status IN ('active', 'processing')")),
    )

    doc_id = Column(String(64), primary_key=True)
    title = Column(String(512), nullable=False)
    source_type = Column(String(32), nullable=False, default="markdown")
    source_uri = Column(Text, nullable=False)
    source_hash = Column(String(128), default="")
    version = Column(Integer, default=1)
    status = Column(String(32), default="pending")
    category = Column(String(128), default="通用")
    parent_doc_id = Column(String(64), nullable=True)
    root_doc_id = Column(String(64), nullable=True)
    previous_doc_id = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    meta = Column("metadata", JSONBType, default=dict)


class DbParsedElement(Base):
    """解析元素 ORM 模型 — 对应 parsed_elements 表。

    记录文档解析后的结构化元素（标题、段落、表格、图片引用等），
    按 sequence_order 保持原文顺序。
    """

    __tablename__ = "parsed_elements"
    __table_args__ = (
        Index("idx_pe_doc_id", "doc_id"),
    )

    element_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), ForeignKey("documents.doc_id"), nullable=False)
    doc_version = Column(Integer, default=1)
    parent_element_id = Column(String(64), nullable=True)
    sequence_order = Column(Integer, default=0)
    element_type = Column(String(32), nullable=False)
    text = Column(Text, default="")
    structured_data = Column(JSONBType, nullable=True)
    asset_data = Column(JSONBType, default=list)
    source_location = Column(JSONBType, default=dict)
    created_at = Column(DateTime(timezone=True), default=_now)
    meta = Column("metadata", JSONBType, default=dict)


class DbAsset(Base):
    """资源文件 ORM 模型 — 对应 assets 表。

    存储图片、视频等二进制资源的元数据与存储路径，
    支持多模态视觉理解后的描述文本（extracted_text）。
    """

    __tablename__ = "assets"
    __table_args__ = (
        Index("idx_assets_doc_id", "doc_id"),
    )

    asset_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), ForeignKey("documents.doc_id"), nullable=False)
    element_id = Column(String(64), default="")
    doc_version = Column(Integer, default=1)
    asset_type = Column(String(32), nullable=False)
    original_uri = Column(Text, nullable=False)
    storage_uri = Column(Text, nullable=True)
    content_hash = Column(String(128), default="")
    created_at = Column(DateTime(timezone=True), default=_now)
    status = Column(String(32), default="ready")
    extracted_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    meta = Column("metadata", JSONBType, default=dict)


class DbKnowledgeChunk(Base):
    """知识块 ORM 模型 — 对应 knowledge_chunks 表。

    知识块是语义抽取后的最小检索单元，按 knowledge_type 区分为陈述型、
    关系型、流程型三种。通过 source_refs 和 asset_refs 关联到源元素和资源。
    doc_id 作为冗余字段存储归属文档 ID，加速按文档查询和 JOIN 操作。
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("idx_kc_doc_id", "doc_id"),
        Index("idx_kc_content_hash", "content_hash"),
        Index("idx_kc_created_at", "created_at"),
        Index("idx_kc_updated_at", "updated_at"),
    )

    chunk_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), default="")
    title = Column(String(512), default="")
    content = Column(Text, nullable=False)
    content_hash = Column(String(128), default="")
    knowledge_type = Column(String(32), default="declarative")
    category = Column(String(128), default="通用")
    status = Column(String(32), default="active")
    asset_refs = Column(JSONBType, default=list)
    source_refs = Column(JSONBType, default=list)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    meta = Column("metadata", JSONBType, default=dict)


class DbIngestJob(Base):
    """入库任务 ORM 模型 — 对应 ingest_jobs 表。

    记录每个异步入库任务的生命周期，供 SSE 端点查询和前端进度展示。
    """

    __tablename__ = "ingest_jobs"
    __table_args__ = (
        Index("idx_ij_doc_id", "doc_id"),
        Index("idx_ij_status", "status"),
    )

    job_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), nullable=False)
    dramatiq_message_id = Column(String(128), default="")
    status = Column(String(32), default="queued")
    stage = Column(String(32), default="")
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class DbSearchLog(Base):
    """搜索请求记录 ORM 模型 — 对应 search_logs 表。

    记录每次搜索请求的完整信息：查询内容、检索策略、各阶段召回量、
    耗时、结果和状态，用于搜索质量分析和问题排查。

    status 取值：
      - success: 全链路正常，所有环节执行成功
      - partial: 有结果返回，但某一环节异常降级（如 Embedding/BM25/Rerank 失败）
      - error: 顶层异常，搜索整体失败
    """

    __tablename__ = "search_logs"
    __table_args__ = (
        Index("idx_sl_created_at", "created_at"),
        Index("idx_sl_status", "status"),
    )

    search_id = Column(String(64), primary_key=True)
    query = Column(Text, nullable=False)
    rewritten_query = Column(Text, default="")
    top_k = Column(Integer, default=10)
    filters = Column(JSONBType, default=dict)
    options = Column(JSONBType, default=dict)
    total_count = Column(Integer, default=0)
    result_count = Column(Integer, default=0)
    result_chunk_ids = Column(JSONBType, default=list)
    vector_count = Column(Integer, default=0)
    bm25_count = Column(Integer, default=0)
    timing_ms = Column(JSONBType, default=dict)  # {"rewrite_ms", "embedding_ms", "search_ms", "rerank_ms", "total_ms"}
    status = Column(String(32), default="success")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)

