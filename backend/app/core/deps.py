"""应用级依赖注入与共享状态。"""

import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.models import DocStatus, JobStage, JobStatus

# ── 线程池初始化（必须在导入 pipeline 等消费模块之前完成，避免 from-import 绑定 None） ──
from app.utils.thread_pool import (
    startup_health_pool,
    startup_search_pool,
    startup_upload_pool,
    startup_asset_worker_pool,
    startup_eval_gen_pool,
)

startup_health_pool()       # 4 线程，健康检查
startup_search_pool()       # 8 线程，并发搜索隔离
startup_upload_pool()       # 8 线程，文件上传 + MinIO 写入
startup_asset_worker_pool() # 6 线程，资源处理六路并发
startup_eval_gen_pool()     # 8 线程，评测数据异步生成

from assets.minio_store import MinioAssetStore
from ingestion.pipeline import IngestionPipeline, _strip_placeholders
from llm.semantic_extractor import SemanticExtractor
from llm.volcengine_client import embedding_client
from parsers.docx_parser import DocxParser
from parsers.html_parser import HtmlParser
from parsers.markdown_parser import MarkdownParser
from parsers.pdf_parser import PdfParser
from parsers.pptx_parser import PptxParser
from parsers.registry import ParserRegistry
from parsers.xlsx_parser import XlsxParser
from app.utils.thread_pool import search_executor
from retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger(__name__)

# ── Parser registry ──────────────────────────────────────────────────

parser_registry = ParserRegistry()
parser_registry.register(MarkdownParser(), DocxParser(), XlsxParser(), PptxParser(), PdfParser(), HtmlParser())

# ── 外部服务后端 ─────────────────────────────────────────────────────

def _init_postgres_backend() -> None:
    """初始化 PostgreSQL 后端；不可用时直接终止启动。"""
    from sqlalchemy import text

    try:
        from app.db.engine import get_engine
        from app.db.engine import create_session_factory as pg_create_session_factory
        from app.db.repositories.assets import PgAssetStore
        from app.db.repositories.chunks import PgChunkStore
        from app.db.repositories.documents import DocumentRepository
        from app.db.repositories.elements import ParsedElementRepository
        from app.db.repositories.jobs import IngestJobRepository
        from app.db.repositories.search_logs import SearchLogRepository

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        sf = pg_create_session_factory()
        globals()["session_factory"] = sf
        globals()["asset_store"] = PgAssetStore(sf)
        globals()["chunk_store"] = PgChunkStore(sf)
        globals()["document_repo"] = DocumentRepository(sf)
        globals()["element_repo"] = ParsedElementRepository(sf)
        globals()["job_repo"] = IngestJobRepository(sf)
        globals()["search_log_repo"] = SearchLogRepository(sf)
    except Exception as exc:
        logger.exception("PostgreSQL 初始化失败")
        raise RuntimeError("PostgreSQL 不可用，服务启动失败") from exc


session_factory = None
asset_store = None
chunk_store = None
document_repo = None
element_repo = None
job_repo = None
search_log_repo = None

if settings.backend != "postgres":
    raise RuntimeError(f"仅支持 BACKEND=postgres，当前配置为 {settings.backend!r}")

_init_postgres_backend()

# ── MinIO backend ─────────────────────────────────────────────────────

minio_asset_store = None
if not settings.minio_enabled:
    raise RuntimeError("必须设置 MINIO_ENABLED=true，资源文件仅允许写入 MinIO")

try:
    minio_asset_store = MinioAssetStore(asset_store)
    asset_store = minio_asset_store
except Exception as exc:
    logger.exception("MinIO 初始化失败")
    raise RuntimeError("MinIO 不可用，服务启动失败") from exc

# ── Milvus backend ────────────────────────────────────────────────────

milvus_manager = None
if not settings.milvus_enabled:
    raise RuntimeError("必须设置 MILVUS_ENABLED=true，检索索引仅允许写入 Milvus")

try:
    from indexing.milvus_bm25 import MilvusBM25Index
    from indexing.milvus_vector import MilvusCollectionManager, MilvusVectorIndex

    milvus_manager = MilvusCollectionManager()
    milvus_manager.ensure_collection()
    vector_index = MilvusVectorIndex(milvus_manager)
    bm25_index = MilvusBM25Index(milvus_manager)
except Exception as exc:
    logger.exception("Milvus 初始化失败")
    raise RuntimeError("Milvus 不可用，服务启动失败") from exc

extractor = SemanticExtractor()

ingestion_pipeline = IngestionPipeline(
    parser_registry=parser_registry,
    extractor=extractor,
    vector_index=vector_index,
    bm25_index=bm25_index,
    asset_store=asset_store,
    chunk_store=chunk_store,
    document_repo=document_repo,
    element_repo=element_repo,
)

retrieval_pipeline = RetrievalPipeline(
    vector_index=vector_index,
    bm25_index=bm25_index,
    chunk_store=chunk_store,
    asset_store=asset_store,
    # executor 不注入：pipeline 内部自建临时 2 线程池跑 Vector+BM25；
    # 外层由 search_executor 管理并发搜索隔离。
)

# ── 评测数据生成线程池已在模块顶部初始化，此处保留注释说明 ──
# startup_eval_gen_pool() 在 pipeline 等消费模块导入之前就已调用，
# 确保 from-import 不会绑定到 None。


def rebuild_retrieval_indexes_from_chunks(category: str | None = None) -> int:
    """从 PostgreSQL 知识块持久化数据全量重建 Milvus 向量 + BM25 索引。

    遍历 chunk_store 中的全部 active 知识块，逐一生成 embedding 后写入 Milvus，
    BM25 索引由 Milvus 内置 BM25 Function 自动处理。

    参数:
        category: 可选，按分类过滤需要索引的知识块；为 None 时索引全部分类

    返回:
        成功索引的知识块数量
    """
    if not hasattr(chunk_store, "list_all"):
        raise RuntimeError("当前知识块存储不支持重建检索索引")

    chunks = chunk_store.list_all(category=category)

    # 仅索引活跃知识块。
    chunks = [c for c in chunks if c.status.value == "active"]
    if not chunks:
        return 0

    # 批量写入 BM25 索引
    bm25_items = []
    for c in chunks:
        doc_id = c.doc_id or (c.source_refs[0].doc_id if c.source_refs else "")
        metadata = {
            "doc_id": doc_id,
            "doc_title": c.metadata.get("doc_title", ""),
            "title": c.title,
            "category": c.category,
            "knowledge_type": c.knowledge_type.value,
            "status": "active",
            "source_refs": [ref.model_dump(mode="json") for ref in c.source_refs],
            "asset_refs": [ref.model_dump(mode="json") for ref in c.asset_refs],
        }
        bm25_items.append((c.chunk_id, _strip_placeholders(c.content), metadata))
    bm25_index.add_batch(bm25_items)

    # 批量写入向量索引
    vectors = embedding_client.embed_text([_strip_placeholders(c.content) for c in chunks])
    vector_items = []
    for chunk, vector in zip(chunks, vectors):
        doc_id = chunk.doc_id or (chunk.source_refs[0].doc_id if chunk.source_refs else "")
        metadata = {
            "doc_id": doc_id,
            "doc_title": chunk.metadata.get("doc_title", ""),
            "title": chunk.title,
            "content": chunk.content,
            "category": chunk.category,
            "knowledge_type": chunk.knowledge_type.value,
            "status": chunk.status.value,
            "source_refs": [ref.model_dump(mode="json") for ref in chunk.source_refs],
            "asset_refs": [ref.model_dump(mode="json") for ref in chunk.asset_refs],
        }
        vector_items.append((chunk.chunk_id, vector, metadata))
    vector_index.add_batch(vector_items)

    return len(chunks)


def recover_pending_chunk_indexes(limit: int | None = None) -> int:
    """启动时恢复活跃知识块的索引（服务重启后自动补齐 Milvus 数据）。

    适用场景：Milvus Collection 被清空或重建后，从 PG 中取全部 active 知识块重新写入索引。
    注意：此函数会调用 embedding_client 生成向量，大批量时耗时较长。

    参数:
        limit: 可选，限制恢复数量上限（用于验证性重启）

    返回:
        成功恢复的知识块数量
    """
    if not hasattr(chunk_store, "list_all"):
        return 0

    all_chunks = chunk_store.list_all()
    chunks = [c for c in all_chunks if c.status.value == "active"]
    if limit is not None:
        chunks = chunks[:limit]
    if not chunks:
        return 0

    ingestion_pipeline.index_existing_chunks(chunks)
    return len(chunks)


def recover_stale_processing_docs(
    timeout_minutes: int = 30,
) -> int:
    """启动时恢复超时的 processing 文档，标记为 failed。

    进程在 _run_create 中异常退出（OOM / kill -9）会导致
    Document 永久停留在 processing。扫描所有 processing 文档，
    将 updated_at 超过阈值的标记为 failed 并设置错误信息。

    Args:
        timeout_minutes: processing 超时阈值（分钟），默认 30。

    Returns:
        恢复的文档数量。
    """
    if document_repo is None:
        return 0

    processing_docs = document_repo.list(status="processing")
    if not processing_docs:
        return 0

    now = datetime.now(timezone.utc)
    timeout = timedelta(minutes=timeout_minutes)
    recovered = 0

    for doc in processing_docs:
        stale_at = doc.updated_at  # 保存原始 processing 开始时间，供日志使用
        if now - stale_at <= timeout:
            continue
        doc.status = DocStatus.failed
        doc.error_message = "入库超时：服务可能在入库过程中异常退出，请重试"
        doc.updated_at = now
        try:
            document_repo.update(doc)
            recovered += 1
            logger.warning(
                "恢复超时 processing 文档: %s（processing 开始于 %s）",
                doc.doc_id, stale_at.isoformat(),
            )
        except Exception:
            logger.exception("恢复 processing 文档失败: %s", doc.doc_id)

    if recovered:
        logger.info("已恢复 %d 个超时 processing 文档", recovered)
    return recovered


def recover_stale_processing_jobs(
    timeout_minutes: int = 60,
) -> int:
    """启动时恢复超时的 processing 任务，标记为 failed。

    Worker 进程异常退出（OOM / kill -9）会导致 IngestJob 永久停留在
    processing 状态。扫描所有 processing 任务，将 updated_at 超过阈值的
    标记为 failed 并设置错误信息。

    Args:
        timeout_minutes: processing 超时阈值（分钟），默认 60。

    Returns:
        恢复的任务数量。
    """
    if job_repo is None:
        return 0

    processing_jobs = job_repo.list_by_status("processing")
    if not processing_jobs:
        return 0

    now = datetime.now(timezone.utc)
    timeout = timedelta(minutes=timeout_minutes)
    recovered = 0

    for job in processing_jobs:
        stale_at = job.updated_at
        if now - stale_at <= timeout:
            continue
        job.status = JobStatus.failed
        job.error_message = "入库超时：Worker 可能在入库过程中异常退出，请重试"
        job.updated_at = now
        try:
            job_repo.update(job)
            recovered += 1
            logger.warning(
                "恢复超时 processing 任务: %s (processing 开始于 %s, doc_id=%s)",
                job.job_id, stale_at.isoformat(), job.doc_id,
            )
        except Exception:
            logger.exception("恢复 processing 任务失败: %s", job.job_id)

    if recovered:
        logger.info("已恢复 %d 个超时 processing 任务", recovered)
    return recovered


def shutdown_resources() -> None:
    """FastAPI 关闭时释放外部连接。"""
    if milvus_manager is not None:
        milvus_manager.disconnect()
