import hashlib
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── 辅助函数 ──────────────────────────────────────────────────────

def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def compute_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


# ── 枚举类型 ──────────────────────────────────────────────────────

# 文档生命周期：pending → processing → active | failed
class DocStatus(str, Enum):
    pending = "pending"          # 待处理：已创建但尚未开始入库流程
    active = "active"
    deleted = "deleted"          # 软删除状态，可通过 restore 恢复为 active
    failed = "failed"
    processing = "processing"


# 资源处理状态：downloading → ready | failed
class AssetStatus(str, Enum):
    downloading = "downloading"   # 下载中：外部链接资源正在下载
    ready = "ready"
    failed = "failed"


# 知识块状态：active / deleted
class ChunkStatus(str, Enum):
    active = "active"
    deleted = "deleted"


class KnowledgeType(str, Enum):
    """知识块的语义类型。当前阶段统一使用 declarative，后续扩展其余类型。"""
    declarative = "declarative"    # 陈述型：事实、定义、属性说明、概念解释
    relational = "relational"      # 关系型：实体关联、依赖、包含、对比
    procedural = "procedural"      # 流程型：步骤、操作顺序、条件分支、决策流程


class ElementType(str, Enum):
    """文档解析元素类型。"""
    title = "title"
    paragraph = "paragraph"
    list = "list"
    table = "table"
    code = "code"
    unknown = "unknown"


class AssetType(str, Enum):
    image = "image"                   # 嵌入图片（_data 存储字节数据，original_uri 为空）
    video = "video"                   # 嵌入视频（_data 存储字节数据，original_uri 为空）
    image_link = "image_link"         # 图片链接（链接文字后缀为图片扩展名）
    video_link = "video_link"         # 视频链接（链接文字后缀为视频扩展名）
    document_link = "document_link"   # 文档链接（链接文字后缀为文档扩展名，下载后触发子文档入库）
    web_link = "web_link"             # 普通网页链接（链接文字无识别后缀）


# ── 嵌套类型 ──────────────────────────────────────────────────────

class SourceLocation(BaseModel):
    page: int | None = None
    section_path: list[str] = Field(default_factory=list)
    table_path: list[dict] = Field(default_factory=list)


class AssetRef(BaseModel):
    """知识块关联的资源引用。前端通过资源类型+占位符展示，不包含渲染信息。"""
    asset_id: str
    caption: str | None = None


class SourceRef(BaseModel):
    doc_id: str
    doc_version: int = 1
    element_id: str
    source_location: SourceLocation = Field(default_factory=SourceLocation)


class ScoreComponents(BaseModel):
    vector: float = 0.0
    bm25: float = 0.0
    rrf: float = 0.0
    rerank: float | None = None  # None 表示 LLM Rerank 未执行或失败


# ── 顶层模型 ──────────────────────────────────────────────────────

class Document(BaseModel):
    doc_id: str = Field(default_factory=lambda: new_id("doc"))
    title: str
    source_type: str
    source_uri: str
    source_hash: str = ""
    category: str = "\u901a\u7528"
    version: int = 1
    status: DocStatus = DocStatus.pending
    parent_doc_id: str | None = None
    root_doc_id: str | None = None
    previous_doc_id: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetData(BaseModel):
    """元素内关联的资源信息。

    由解析器在解析时填入，记录正文中占位符与实际 Asset 的对应关系。
    表格单元格也通过 structured_data 内的同名字段关联。
    """
    placeholder: str = ""                         # 占位符，如 "{{image:1}}"，旧解析器可为空
    asset_id: str                                 # 关联的 Asset.asset_id


class ParsedElement(BaseModel):
    element_id: str = Field(default_factory=lambda: new_id("el"))
    doc_id: str
    doc_version: int = 1
    parent_element_id: str | None = None
    sequence_order: int = 0
    element_type: ElementType
    text: str = ""
    structured_data: dict[str, Any] | None = None
    asset_data: list[AssetData] = Field(default_factory=list)
    source_location: SourceLocation = Field(default_factory=SourceLocation)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class Asset(BaseModel):
    """文档关联的资源资产。

    字段语义按 asset_type 不同：
    - image/video:     original_uri=""，storage_uri=MinIO key，display_text=""
    - image_link/video_link/document_link: original_uri=URL，storage_uri=下载后 MinIO key，display_text=链接文字
    - web_link:        original_uri=URL，storage_uri=None，display_text=链接文字
    _data 为运行时私有属性（不入库），image/video 类型的原始字节数据。
    """
    asset_id: str = Field(default_factory=lambda: new_id("asset"))
    doc_id: str
    element_id: str = ""
    doc_version: int = 1
    asset_type: AssetType
    original_uri: str = ""              # 链接类型存 URL，嵌入类型为空
    storage_uri: str | None = None      # MinIO key，web_link 为空
    display_text: str = ""              # 链接锚文本，嵌入类型为空
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: AssetStatus = AssetStatus.ready
    extracted_text: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: new_id("chunk"))
    doc_id: str = ""                           # \u5f52\u5c5e\u6587\u6863 ID\uff0c\u4ece source_refs[0].doc_id \u5197\u4f59\uff0c\u52a0\u901f\u67e5\u8be2
    title: str = ""
    content: str
    content_hash: str = ""
    knowledge_type: KnowledgeType = KnowledgeType.declarative
    category: str = "\u901a\u7528"
    status: ChunkStatus = ChunkStatus.active
    asset_refs: list[AssetRef] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _set_content_hash(self) -> "KnowledgeChunk":
        if not self.content_hash and self.content:
            self.content_hash = compute_hash(self.content)
        return self

    @model_validator(mode="after")
    def _set_doc_id(self) -> "KnowledgeChunk":
        """从 source_refs[0].doc_id 自动填充 doc_id 冗余字段。"""
        if not self.doc_id and self.source_refs:
            self.doc_id = self.source_refs[0].doc_id
        return self


class SearchResultItem(BaseModel):
    chunk_id: str
    doc_id: str = ""                   # 从 Milvus 直接带回，免查 PG
    doc_title: str = ""                # 从 Milvus 直接带回，免查 PG
    status: str = "active"             # 从 Milvus 带回，供过滤器使用
    title: str = ""
    content: str
    score: float
    category: str
    knowledge_type: KnowledgeType
    score_components: ScoreComponents = Field(default_factory=ScoreComponents)
    asset_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)


class SearchResult(BaseModel):
    search_id: str = Field(default_factory=lambda: new_id("search"))
    query: str
    rewritten_query: str = ""
    total_count: int = 0
    results: list[SearchResultItem] = Field(default_factory=list)


# ── 入库任务模型（Dramatiq 异步任务状态追踪） ────────────────────


class JobStatus(str, Enum):
    """入库任务生命周期状态。"""

    queued = "queued"           # 已入队，等待 Worker 取走
    processing = "processing"   # Worker 正在执行
    completed = "completed"     # 入库成功
    failed = "failed"           # 入库失败（可重试）


class JobStage:
    """入库阶段常量。

    processing 阶段：PARSING / EXTRACTING / INDEXING
    终态：COMPLETED / FAILED
    """

    PARSING = "parsing"           # 解析文档结构
    EXTRACTING = "extracting"     # 语义抽取
    INDEXING = "indexing"         # 向量化 + 索引写入
    COMPLETED = "completed"       # 入库成功
    FAILED = "failed"             # 入库失败


class IngestJob(BaseModel):
    """入库任务领域模型。

    持久化到 ingest_jobs 表，SSE 端点每秒轮询此表推送状态变更。
    """

    job_id: str
    doc_id: str
    dramatiq_message_id: str = ""
    status: JobStatus = JobStatus.queued
    stage: str = ""                             # 当前阶段，仅 processing 时有值
    progress: int = 0                          # 0-100
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
