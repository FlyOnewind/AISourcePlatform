"""v1 API 支撑服务 — 索引元数据同步和知识块重建索引。

这些服务作为 API 层与底层索引/仓储之间的中继，确保:
- 知识块状态变更后同步到向量索引和 BM25 索引元数据
- 内容变更后触发或排队重建索引（复用现有 embedding + 索引写入流程）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.models import KnowledgeChunk

if TYPE_CHECKING:
    from app.db.repositories.chunks import PgChunkStore
    from indexing.base import BM25Index, VectorIndex

logger = logging.getLogger(__name__)


# ── 2.5 索引元数据同步服务 ───────────────────────────────────────

def sync_index_metadata(
    chunk: KnowledgeChunk,
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
) -> None:
    """同步知识块元数据到 Milvus 索引（status、category、knowledge_type）。

    vector_index 和 bm25_index 共用同一 Milvus collection，一次 upsert_fields 即可。
    """
    metadata = {
        "status": chunk.status.value if hasattr(chunk.status, "value") else str(chunk.status),
        "category": chunk.category,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else str(chunk.knowledge_type),
    }
    _sync_vector_metadata(chunk.chunk_id, metadata, vector_index)


def sync_index_metadata_batch(
    chunks: list[KnowledgeChunk],
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
) -> int:
    """批量同步知识块状态到 Milvus 索引。"""
    if not chunks:
        return 0

    chunk_ids = [c.chunk_id for c in chunks]
    status_value = chunks[0].status.value if hasattr(chunks[0].status, "value") else str(chunks[0].status)

    if status_value == "deleted":
        manager = getattr(vector_index, "manager", None)
        if manager is not None and hasattr(manager, "delete_batch"):
            try:
                manager.delete_batch(chunk_ids)
            except Exception:
                logger.exception("批量删除 Milvus 索引失败")
        else:
            for cid in chunk_ids:
                try:
                    vector_index.delete(cid)
                except Exception:
                    pass
    else:
        try:
            batch_items = []
            for c in chunks:
                batch_items.append((c.chunk_id, {
                    "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                    "category": c.category,
                    "knowledge_type": c.knowledge_type.value if hasattr(c.knowledge_type, "value") else str(c.knowledge_type),
                }))
            vector_index.upsert_fields_batch(batch_items)
        except Exception:
            logger.exception("批量同步索引元数据失败")

    return len(chunks)


def _sync_vector_metadata(chunk_id: str, metadata: dict, vector_index: "VectorIndex") -> None:
    """同步 chunk 元数据到 Milvus 索引（通过 upsert_fields 更新标量字段）。"""
    if hasattr(vector_index, "upsert_fields"):
        vector_index.upsert_fields(chunk_id, metadata)


# ── 2.6 知识块重建索引服务 ─────────────────────────────────────

def reindex_chunk(
    chunk: KnowledgeChunk,
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
    embedding_client=None,
) -> None:
    """对单个知识块重建索引。

    向量索引和 BM25 共用同一 Milvus collection，一次 upsert 写入：
    dense_vector（embedding）+ content（触发 BM25 Function 自动生成 sparse_vector）+ 全部标量字段。

    参数:
        chunk: 需要重建索引的知识块
        vector_index: 向量索引实例（Milvus）
        bm25_index: 未使用（保留参数兼容），BM25 由 Milvus 内置 Function 自动处理
        embedding_client: embedding 客户端，需要 embed_text 方法
    """
    doc_id = chunk.doc_id or (chunk.source_refs[0].doc_id if chunk.source_refs else "")
    metadata = {
        "doc_id": doc_id,
        "doc_title": chunk.metadata.get("doc_title", ""),
        "title": chunk.title,
        "content": chunk.content,
        "category": chunk.category,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else str(chunk.knowledge_type),
        "status": chunk.status.value if hasattr(chunk.status, "value") else str(chunk.status),
        "source_refs": [ref.model_dump(mode="json") for ref in chunk.source_refs],
        "asset_refs": [ref.model_dump(mode="json") for ref in chunk.asset_refs],
        "metadata": chunk.metadata,
    }

    # 生成 embedding 并一次写入 Milvus（dense_vector + content→sparse_vector + 标量）
    vector = [0.0] * 1024  # 默认零向量：LLM 不可用时仍可通过 BM25 检索
    if embedding_client is not None and hasattr(embedding_client, "embed_text"):
        try:
            vectors = embedding_client.embed_text([chunk.content])
            if vectors:
                vector = vectors[0]
        except Exception:
            logger.exception("知识块 %s embedding 失败，仅写入 BM25 索引", chunk.chunk_id)
    vector_index.add(chunk.chunk_id, vector, metadata=metadata)


def reindex_chunks_batch(
    chunks: list[KnowledgeChunk],
    vector_index: "VectorIndex",
    bm25_index: "BM25Index",
    embedding_client=None,
    chunk_store: "PgChunkStore | None" = None,
) -> dict[str, list[str]]:
    """批量重建知识块索引。

    参数:
        chunks: 需要重建索引的知识块列表
        vector_index: 向量索引实例
        bm25_index: BM25 索引实例
        embedding_client: embedding 客户端
        chunk_store: 知识块仓储，用于更新索引状态

    返回:
        {"succeeded": [...], "failed": [...]}
    """
    succeeded: list[str] = []
    failed: list[str] = []

    for chunk in chunks:
        try:
            reindex_chunk(chunk, vector_index, bm25_index, embedding_client)

            succeeded.append(chunk.chunk_id)
        except Exception as exc:
            logger.exception("知识块 %s 重建索引失败", chunk.chunk_id)
            failed.append(chunk.chunk_id)

    return {"succeeded": succeeded, "failed": failed}
