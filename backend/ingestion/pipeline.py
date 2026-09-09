"""文档入库流水线 — 编排解析、语义抽取、索引写入的完整流程。

主要类：
- IngestionPipeline: 同步执行文档入库，包含清理旧块、解析、资源处理、抽取、索引五个阶段。
- _batched: 通用列表分片工具函数。
"""

import hashlib
import logging
import re
import sys
import threading
from concurrent.futures import Future, as_completed
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import settings
from app.core.errors import DuplicateDocumentError
from app.utils.thread_pool import asset_worker_pool, eval_gen_pool
from app.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    DocStatus,
    Document,
    JobStage,
    KnowledgeChunk,
    new_id,
)
from app.core.paths import resolve_file_uri
from assets.base import AssetStore
from assets.downloader import download_to_bytes
from assets.asset_processor import (
    process_image,
    process_image_link,
    process_video,
    process_video_link,
)
from assets.minio_store import MinioAssetStore, make_asset_key, make_minio_key, read_uri_bytes
from indexing.base import BM25Index, VectorIndex
from indexing.milvus_vector import _json_dumps
from llm.semantic_extractor import SemanticExtractor
from llm.volcengine_client import embedding_client
from parsers.registry import ParserRegistry

logger = logging.getLogger(__name__)

# 占位符正则：{{image:1}}、{{doc:2}}、{{video:3}}、{{web:4}} 等
_PLACEHOLDER_RE = re.compile(r"\{\{(?:image|doc|video|web|res):\d+\}\}")


def _strip_placeholders(text: str) -> str:
    """去除文本中的图片/链接占位符，用于生成向量 embedding。

    占位符（如 {{image:1}}、{{image_link:3}}）在 LLM 语义抽取时保留以关联资源，
    但在生成 embedding 向量时应剔除，避免占位符噪声影响向量语义质量。
    content 字段仍保留完整占位符以供前端渲染。

    参数:
        text: 可能包含占位符的原始文本

    返回:
        已去除各类型占位符的纯文本
    """
    return _PLACEHOLDER_RE.sub("", text).strip()

# URL 后缀 → source_type 映射（用于 document_link 推断子文档类型）
_SUFFIX_TO_SOURCE_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
}


def _batched(items: list[Any], size: int) -> list[list[Any]]:
    """按固定大小切分列表，避免单次 embedding 或 upsert 过大。"""
    batch_size = max(1, size)
    return [items[start : start + batch_size] for start in range(0, len(items), batch_size)]


def _source_type_from_url(url: str) -> str | None:
    """从 URL 后缀推断 source_type，用于 document_link 子文档。"""
    suffix = PurePosixPath(url.split("?", 1)[0]).suffix.lower()
    return _SUFFIX_TO_SOURCE_TYPE.get(suffix)


def _dispatch_asset(
    asset: Asset,
    asset_store: Any,
    minio_store: MinioAssetStore | None,
) -> None:
    """单个 Asset 的处理分发函数，供线程池调用（纯函数，无副作用）。"""
    at = asset.asset_type
    if at == AssetType.image:
        process_image(asset, asset_store, minio_store)
    elif at == AssetType.video:
        process_video(asset, asset_store, minio_store)
    elif at == AssetType.image_link:
        process_image_link(asset, asset_store, minio_store)
    elif at == AssetType.video_link:
        process_video_link(asset, asset_store, minio_store)


class IngestionPipeline:
    """文档入库流水线编排器。

    协调解析器注册表、语义抽取器、向量/BM25 双路索引和资源存储，
    执行完整的文档入库流程：解析 → 资源处理 → LLM 语义抽取 → 索引写入。
    """

    def __init__(
        self,
        parser_registry: ParserRegistry,
        extractor: SemanticExtractor,
        vector_index: VectorIndex,
        bm25_index: BM25Index,
        asset_store: AssetStore,
        chunk_store: Any = None,
        document_repo: Any = None,
        element_repo: Any = None,
    ) -> None:
        self._parser_registry = parser_registry
        self._extractor = extractor
        self._vector_index = vector_index
        self._bm25_index = bm25_index
        self._asset_store = asset_store
        self._chunk_store = chunk_store
        self._document_repo = document_repo
        self._element_repo = element_repo
        self._minio_store = asset_store if isinstance(asset_store, MinioAssetStore) else None

    def _cleanup_old_chunks(self, doc_id: str) -> None:
        """重入库前批量清理旧知识块，从 Milvus 和 PostgreSQL 中删除。

        vector 和 BM25 共享同一 Milvus collection，一次批量 delete 即可；
        PG 侧用 bulk_hard_delete 一条 DELETE 完成。
        """
        if not self._chunk_store or not hasattr(self._chunk_store, "list_by_doc_id"):
            return
        old_chunks = self._chunk_store.list_by_doc_id(doc_id)
        if not old_chunks:
            return

        chunk_ids = [c.chunk_id for c in old_chunks]

        # Milvus 批量删除（一条 expr + 一次 flush，替代逐条双删）
        manager = getattr(self._vector_index, "manager", None)
        if manager is not None and hasattr(manager, "delete_batch"):
            try:
                manager.delete_batch(chunk_ids)
            except Exception as exc:
                raise RuntimeError(
                    f"批量清理 Milvus 失败: {len(chunk_ids)} 个知识块"
                ) from exc
        else:
            # 回退：逐条删除（不含测试/回退路径）
            for chunk_id in chunk_ids:
                try:
                    self._vector_index.delete(chunk_id)
                except Exception as exc:
                    raise RuntimeError(f"清理旧知识块失败: {chunk_id}") from exc

        # PG 批量硬删除
        if hasattr(self._chunk_store, "bulk_hard_delete"):
            self._chunk_store.bulk_hard_delete(chunk_ids)
        else:
            for chunk_id in chunk_ids:
                self._chunk_store.hard_delete(chunk_id)

    def _cleanup_old_elements(self, doc_id: str) -> None:
        """删除重入库文档的旧解析元素，防止解析结果缩短后残留旧元素。"""
        if self._element_repo and hasattr(self._element_repo, "delete_by_doc_id"):
            self._element_repo.delete_by_doc_id(doc_id)

    def _cleanup_old_assets(self, doc_id: str) -> None:
        """删除重入库文档的旧资源对象与元数据，防止产生失效资源引用。

        优先走 MinioAssetStore.delete_by_doc_id 批量删除（一条 DELETE）；
        未实现时回退到 get_by_doc_id + 逐条 delete。
        """
        if hasattr(self._asset_store, "delete_by_doc_id"):
            self._asset_store.delete_by_doc_id(doc_id)
        elif hasattr(self._asset_store, "get_by_doc_id"):
            for asset in self._asset_store.get_by_doc_id(doc_id):
                self._asset_store.delete(asset.asset_id)

    def _cleanup_previous_artifacts(self, doc_id: str) -> None:
        """按知识块、解析元素、资源的依赖顺序清理旧入库产物。"""
        self._cleanup_old_chunks(doc_id)
        self._cleanup_old_elements(doc_id)
        self._cleanup_old_assets(doc_id)

    def ingest(
        self,
        doc: Document,
        raw_content: bytes | str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Document:
        """同步执行文档入库，返回更新后的 Document（status=active 或 failed）。

        重入库场景先清理旧知识块、解析元素和资源，再走完整流水线。
        """
        try:
            doc.status = DocStatus.processing
            doc.error_message = None
            doc.updated_at = datetime.now(timezone.utc)

            # ── 清除删除前状态标记（恢复流程写入，重入库后失效） ──
            if doc.metadata and "previous_status" in doc.metadata:
                del doc.metadata["previous_status"]

            # 先持久化 processing，确保进程异常退出时数据库不会停留在旧状态。
            if self._document_repo:
                existing = self._document_repo.get(doc.doc_id)
                if existing is None:
                    doc = self._document_repo.create(doc)
                else:
                    doc = self._document_repo.update(doc)

            # ── 重入库前清理旧知识块、解析元素和资源 ──
            self._cleanup_previous_artifacts(doc.doc_id)

            self._run_create(doc, raw_content, options)

            doc.status = DocStatus.active
            doc.error_message = None
            doc.updated_at = datetime.now(timezone.utc)
            if self._document_repo:
                self._document_repo.update(doc)
        except Exception as exc:
            logger.exception("文档 %s 入库失败", doc.doc_id)
            doc.status = DocStatus.failed
            doc.error_message = str(exc)[:2000]
            doc.updated_at = datetime.now(timezone.utc)
            if self._document_repo:
                try:
                    self._document_repo.update(doc)
                except Exception:
                    logger.exception("持久化文档失败状态时出错")
            raise  # 重新抛出，让上层（actor / Dramatiq）根据策略决定重试或标记 job 失败
        return doc

    def _run_create(
        self,
        doc: Document,
        raw_content: bytes | str | None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """文档入库流程（解析 → 资源处理 → 抽取 → 索引）。"""
        # ── 提取进度回调（actor 通过 options 传入） ──
        _progress = (options or {}).get("progress_callback")

        def _notify(stage: str, pct: int):
            if _progress:
                try:
                    _progress(stage, pct)
                except Exception:
                    pass

        # 1. 解析文档
        _notify(JobStage.PARSING, 15)
        parser = self._parser_registry.get(doc.source_type)

        # 降级路径：调用方未传内容时从 MinIO / file:// / http(s):// 读取
        if raw_content is None:
            if doc.source_uri.startswith("minio://"):
                raw_content = read_uri_bytes(doc.source_uri, self._minio_store)
            elif doc.source_uri.startswith("file://"):
                raw_content = resolve_file_uri(doc.source_uri).read_bytes()
            elif doc.source_uri.startswith("http://") or doc.source_uri.startswith("https://"):
                raw_content = read_uri_bytes(doc.source_uri)
            else:
                raise ValueError(
                    f"无法读取文档内容：不支持的 source_uri 协议: {doc.source_uri[:80]}"
                )

        result = parser.parse(doc, raw_content)
        elements = result.elements
        assets = result.assets

        # Element 先于 Asset 持久化（核心数据优先保证）
        if self._element_repo and elements:
            self._element_repo.create_batch(elements)

        self._prepare_assets(assets)

        # 2. 语义抽取（全文优先 + 递进降级）
        _notify(JobStage.EXTRACTING, 40)
        chunks = self._extractor.extract(elements, assets, doc.category)

        # 将文档标题写入 chunk metadata，供 Milvus 索引直接返回，免查 PG
        doc_title = doc.title or ""
        for c in chunks:
            c.metadata["doc_title"] = doc_title

        # 3. 索引
        _notify(JobStage.INDEXING, 70)
        if chunks:
            self._index_chunks(chunks)

        # 4. 自动生成评测数据（后台异步）
        if settings.auto_eval_enabled and chunks:
            logger.warning("触发评测数据生成: doc_id=%s, chunks=%d", doc.doc_id, len(chunks))
            self._trigger_eval_data_generation(doc, chunks)
        else:
            logger.warning("跳过评测数据生成: enabled=%s, chunks=%d", settings.auto_eval_enabled, len(chunks))

    def _prepare_assets(self, assets: list[Asset]) -> None:
        """按资源类型分发处理：六路统一提交到 asset_worker_pool 并发。

        - image / video / image_link / video_link → _dispatch_asset（魔数+视觉+MinIO）
        - document_link → _process_document_link（下载→预占位→MinIO→异步入库）
        - web_link / 其他 → asset_store.put() 直接持久化（无 I/O，无需线程池）
        """
        processable: list[Asset] = []

        for asset in assets:
            at = asset.asset_type
            if at in (AssetType.image, AssetType.video,
                       AssetType.image_link, AssetType.video_link,
                       AssetType.document_link):
                processable.append(asset)
            else:
                self._asset_store.put(asset)      # web_link 等直接持久化

        if not processable:
            return

        if asset_worker_pool is not None:
            # 六路统一并发：每次 put 独立 session，天然线程安全
            # 使用独立 asset_worker_pool，避免与调用方竞争 worker 导致死锁
            futures: dict[Future, Asset] = {}
            for asset in processable:
                if asset.asset_type == AssetType.document_link:
                    future = asset_worker_pool.submit(
                        self._process_document_link, asset,
                    )
                else:
                    future = asset_worker_pool.submit(
                        _dispatch_asset, asset, self._asset_store, self._minio_store,
                    )
                futures[future] = asset

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    logger.exception(
                        "Asset 处理异常: %s", futures[future].asset_id,
                    )
        else:
            # 线程池未初始化时（如测试环境）回退串行
            for asset in processable:
                try:
                    if asset.asset_type == AssetType.document_link:
                        self._process_document_link(asset)
                    else:
                        _dispatch_asset(asset, self._asset_store, self._minio_store)
                except Exception:
                    logger.exception(
                        "Asset 处理异常（串行回退）: %s", asset.asset_id,
                    )

    def _process_document_link(self, asset: Asset) -> None:
        """处理文档链接 Asset：对标 _do_upload 的完整流程，创建子文档并异步入库。

        与直接上传一致的流程：Document 预占位 → MinIO 上传 → 更新 source_uri → ingest。
        子文档异步入库，失败影响仅限子文档，不传播到主文档。

        Args:
            asset: document_link 类型的 Asset。
        """
        # ── [1] HTTP 下载 ──
        try:
            data = download_to_bytes(asset.original_uri)
        except Exception as exc:
            logger.warning("文档链接下载失败: %s (%s)", asset.original_uri, exc)
            asset.status = AssetStatus.failed
            asset.error_message = f"download_failed: {exc}"
            self._asset_store.put(asset)
            return

        # ── [2] 推断子文档类型 ──
        source_type = _source_type_from_url(asset.original_uri)
        if source_type is None:
            logger.warning("无法推断文档链接类型: %s", asset.original_uri)
            asset.status = AssetStatus.failed
            asset.error_message = "unsupported_document_type"
            self._asset_store.put(asset)
            return

        # ── [3] 内容去重 ──
        source_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
        if self._document_repo and hasattr(self._document_repo, "find_by_hash"):
            existing = self._document_repo.find_by_hash(source_hash)
            if existing is not None:
                logger.info("文档链接 %s 与已有文档 %s 内容相同，跳过", asset.original_uri, existing.doc_id)
                asset.storage_uri = existing.source_uri
                asset.status = AssetStatus.ready
                self._asset_store.put(asset)
                return

        # ── [4] Document 预占位（对标 _do_upload: 先 PG 后 MinIO，防孤儿文件） ──
        child_doc_id = new_id("doc")
        file_name = Path(asset.original_uri.rsplit("?", 1)[0]).name or "document"

        parent_root_id = asset.doc_id
        if self._document_repo:
            parent_doc = self._document_repo.get(asset.doc_id)
            if parent_doc:
                parent_root_id = parent_doc.root_doc_id or parent_doc.doc_id

        child_doc = Document(
            doc_id=child_doc_id,
            title=Path(file_name).stem or "子文档",
            source_type=source_type,
            source_uri="",                       # MinIO 写入后更新
            source_hash=source_hash,
            category="通用",
            parent_doc_id=asset.doc_id,
            root_doc_id=parent_root_id,
            metadata={"source": "document_link", "original_url": asset.original_uri},
        )

        if self._document_repo:
            try:
                self._document_repo.create(child_doc)
            except DuplicateDocumentError:
                # 并发竞态：查重之后另一个请求抢先插入了相同 hash
                logger.warning("子文档 %s 并发重复，跳过", child_doc_id)
                existing = self._document_repo.find_by_hash(source_hash)
                asset.storage_uri = existing.source_uri if existing else ""
                asset.status = AssetStatus.ready
                self._asset_store.put(asset)
                return

        # ── [5] MinIO 上传（PG 预占位成功后再写文件，失败回滚 PG） ──
        if self._minio_store is not None:
            key = make_minio_key(child_doc_id, file_name)
            try:
                source_uri = self._minio_store.upload_bytes(
                    self._minio_store.input_bucket,
                    key,
                    data,
                    "application/octet-stream",
                )
            except Exception as exc:
                logger.warning("子文档 MinIO 上传失败: %s (%s)", child_doc_id, exc)
                if self._document_repo:
                    try:
                        self._document_repo.hard_delete(child_doc_id)
                    except Exception:
                        logger.exception("回滚子文档预占位失败: %s", child_doc_id)
                asset.status = AssetStatus.failed
                asset.error_message = f"minio_upload_failed: {exc}"
                self._asset_store.put(asset)
                return
        else:
            source_uri = asset.original_uri

        # ── [6] 更新 source_uri ──
        child_doc.source_uri = source_uri
        if self._document_repo:
            try:
                self._document_repo.update(child_doc)
            except Exception:
                logger.exception("更新子文档 source_uri 失败: %s", child_doc_id)

        asset.storage_uri = source_uri
        asset.status = AssetStatus.ready
        self._asset_store.put(asset)

        # ── [7] 异步入库（对标 _do_upload：创建 Job + Dramatiq 入队） ──
        from app.core.deps import job_repo  # pylint: disable=import-outside-toplevel
        from app.core.models import IngestJob  # pylint: disable=import-outside-toplevel
        from app.tasks.ingest import ingest_document  # pylint: disable=import-outside-toplevel

        job_id = new_id("job")
        job = IngestJob(job_id=job_id, doc_id=child_doc_id)

        if job_repo is not None:
            try:
                job = job_repo.create(job)
            except Exception:
                logger.exception("创建子文档 IngestJob 失败: %s", child_doc_id)
                job = None

        # 入队 Dramatiq
        try:
            message = ingest_document.send(job_id, child_doc_id)
            if job is not None and job_repo is not None:
                job.dramatiq_message_id = message.message_id
                job_repo.update(job)
        except Exception:
            logger.exception("子文档 Dramatiq 入队失败: job_id=%s, doc_id=%s", job_id, child_doc_id)
            if job is not None and job_repo is not None:
                try:
                    job_repo.hard_delete(job_id)
                except Exception:
                    logger.exception("回滚子文档 job 失败: %s", job_id)


    def index_existing_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        """重新索引已持久化的知识块（不重复写 PG），用于启动恢复或人工补偿。"""
        self._index_chunks(chunks, persist_chunks=False)

    def _index_chunks(
        self,
        chunks: list[KnowledgeChunk],
        *,
        persist_chunks: bool = True,
    ) -> None:
        """生成 embedding，写入 Milvus（dense_vector + content→BM25 自动 sparse + 标量）。

        步骤：1) 可选 PG 持久化  2) 按批生成 Embedding  3) 按批一次 upsert 写入 Milvus。

        vector 和 BM25 合并为一次 upsert：同一 collection 上一次写入含 dense_vector
        和 content，消除先后顺序依赖，同时跳过 _load_existing_entities 冗余查询。
        """
        if self._chunk_store and persist_chunks:
            if hasattr(self._chunk_store, "bulk_put"):
                self._chunk_store.bulk_put(chunks)
            else:
                for chunk in chunks:
                    self._chunk_store.put(chunk)

        for batch in _batched(chunks, settings.embedding_batch_size):
            texts = [_strip_placeholders(chunk.content) for chunk in batch]
            vectors = embedding_client.embed_text(texts)
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"embedding count mismatch: chunks={len(batch)}, vectors={len(vectors)}"
                )

            entities: list[dict[str, Any]] = []
            for chunk, vector in zip(batch, vectors):
                meta = self._chunk_index_metadata(chunk)
                entities.append({
                    "chunk_id": chunk.chunk_id,
                    "dense_vector": [float(v) for v in vector],
                    "doc_id": str(meta.get("doc_id", "")),
                    "doc_title": str(meta.get("doc_title", ""))[:512],
                    "title": str(meta.get("title", ""))[:512],
                    "content": str(meta.get("content", ""))[:65535],
                    "category": str(meta.get("category", "")),
                    "knowledge_type": str(meta.get("knowledge_type", "")),
                    "status": str(meta.get("status", "active")),
                    "source_refs": _json_dumps(meta.get("source_refs", [])),
                    "asset_refs": _json_dumps(meta.get("asset_refs", [])),
                    "metadata": "{}",
                })

            for write_batch in _batched(entities, settings.index_upsert_batch_size):
                self._vector_index.manager.upsert_entities(write_batch)

    @staticmethod
    def _chunk_index_metadata(chunk: KnowledgeChunk) -> dict[str, Any]:
        """构造写入 Milvus 检索索引的知识块元数据字典。

        包含 doc_id（从 KnowledgeChunk.doc_id 冗余字段直接读取）、title、content、
        category 等标量字段，以及序列化为 JSON 字符串的 source_refs 和 metadata。
        """
        doc_id = chunk.doc_id or (chunk.source_refs[0].doc_id if chunk.source_refs else "")
        return {
            "doc_id": doc_id,
            "doc_title": chunk.metadata.get("doc_title", ""),
            "title": chunk.title,
            "content": chunk.content,
            "category": chunk.category,
            "knowledge_type": chunk.knowledge_type.value,
            "status": chunk.status.value,
            "source_refs": [
                ref.model_dump(mode="json")
                for ref in chunk.source_refs
            ],
            "asset_refs": [
                ref.model_dump(mode="json")
                for ref in chunk.asset_refs
            ],
        }

    def _trigger_eval_data_generation(self, doc: Document, chunks: list[KnowledgeChunk]) -> None:
        """在后台异步触发评测数据生成。

        失败不影响主流程，仅记录日志。
        """
        def _generate() -> None:
            logger.warning("评测数据生成线程启动: doc_id=%s, chunks=%d", doc.doc_id, len(chunks))
            try:
                # 将项目根目录加入 sys.path，以便导入根级 evaluation 包
                # 兼容两种场景：
                #   Host:   backend/ingestion/pipeline.py → parents[2] = 仓库根目录
                #   Worker: /app/ingestion/pipeline.py    → parents[1] = /app（evaluation 挂载在此）
                _self = Path(__file__).resolve()
                for _parent in (_self.parents[2], _self.parents[1]):
                    if str(_parent) not in sys.path:
                        sys.path.insert(0, str(_parent))
                from evaluation.gen_dataset import generate_for_chunks
                from evaluation.storage import save_per_doc_dataset

                # 转换 chunk 格式为 dict 列表，供 LLM 使用
                chunk_dicts = [
                    {
                        "chunk_id": c.chunk_id,
                        "title": c.title,
                        "content": c.content,
                        "category": c.category,
                        "knowledge_type": c.knowledge_type.value,
                    }
                    for c in chunks
                ]

                # 生成评测数据（异步，不阻塞主流程）
                items, errors = generate_for_chunks(
                    chunks=chunk_dicts,
                    doc_id=doc.doc_id,
                    doc_title=doc.title or doc.doc_id,
                    query_count=settings.auto_eval_queries_per_doc,
                    doc_version=doc.version,
                )

                if errors:
                    logger.warning(
                        "评测数据生成有 %d 个警告：%s",
                        len(errors), errors[:3],
                    )

                if not items:
                    logger.warning("没有生成有效的评测数据")
                    return

                # 保存分文档数据集（不自动合并到全局，保持人工标注与自动生成隔离）
                path = save_per_doc_dataset(
                    doc_id=doc.doc_id,
                    doc_title=doc.title or doc.doc_id,
                    items=items,
                    chunk_count=len(chunks),
                    doc_version=doc.version,
                )
                logger.warning(
                    "文档 %s 评测数据生成完成，%d 条 → %s",
                    doc.doc_id, len(items), path,
                )

            except ImportError:
                logger.exception("评测数据生成失败（导入错误），已跳过")
            except Exception:
                logger.exception("评测数据生成异常，已跳过")

        # 提交到评测专用线程池执行（8 线程，控制 LLM 并发）
        if eval_gen_pool is not None:
            logger.warning("提交评测数据生成到线程池: doc_id=%s", doc.doc_id)
            eval_gen_pool.submit(_generate)
        else:
            # 线程池未初始化时（如测试环境）回退裸线程
            logger.warning("评测线程池未初始化，回退裸线程: doc_id=%s", doc.doc_id)
            thread = threading.Thread(target=_generate, daemon=True)
            thread.start()
