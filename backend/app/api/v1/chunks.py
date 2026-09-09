"""知识块管理 API v1 — 列表、创建、详情、更新、软删除、恢复、重建索引和批量操作。

所有端点均返回统一的 APIResponse / PaginatedResponse 结构。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.v1.errors import ErrorCode
from app.api.v1.schemas import (
    APIResponse,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    SearchParams,
    error_json,
)
from app.api.v1.services import (
    reindex_chunk,
    sync_index_metadata,
    sync_index_metadata_batch,
)
from app.core.deps import (
    asset_store,
    bm25_index,
    chunk_store,
    document_repo,
    vector_index,
)
from app.core.models import (
    AssetRef,
    ChunkStatus,
    KnowledgeChunk,
    KnowledgeType,
    SourceRef,
    compute_hash,
)
from llm.volcengine_client import embedding_client

router = APIRouter(prefix="/chunks", tags=["chunks"])
logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _get_primary_doc_id(chunk: KnowledgeChunk) -> str:
    """获取主要关联文档 ID，优先使用 doc_id 冗余字段。"""
    if chunk.doc_id:
        return chunk.doc_id
    if chunk.source_refs:
        return chunk.source_refs[0].doc_id
    return ""


def _batch_load_doc_info(doc_ids: set[str]) -> dict[str, dict[str, str]]:
    """批量加载文档标题和来源类型，消除列表页 N+1 查询。

    Args:
        doc_ids: 去重后的文档 ID 集合。

    Returns:
        {doc_id: {"title": ..., "source_type": ...}} 字典，缺失的 doc_id 不在 keys 中。
    """
    cache: dict[str, dict[str, str]] = {}
    if document_repo is None:
        return cache
    for doc_id in doc_ids:
        if not doc_id:
            continue
        doc = document_repo.get(doc_id)
        if doc:
            cache[doc_id] = {"title": doc.title, "source_type": doc.source_type}
    return cache


def _resolve_doc_title(doc_id: str) -> str | None:
    """单条文档标题查询，供详情页等低频场景使用。"""
    if not doc_id or document_repo is None:
        return None
    doc = document_repo.get(doc_id)
    return doc.title if doc else None


def _resolve_doc_source_type(doc_id: str) -> str:
    """单条文档来源类型查询，供详情页等低频场景使用。"""
    if not doc_id or document_repo is None:
        return ""
    doc = document_repo.get(doc_id)
    return doc.source_type if doc else ""


def _chunk_to_list_item(
    chunk: KnowledgeChunk,
    doc_info_cache: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """将知识块转为列表条目（含内容摘要、时间等展示字段）。

    Args:
        chunk: 知识块对象。
        doc_info_cache: 批量预加载的文档信息缓存，避免逐条 N+1 查询。
    """
    preview = chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
    doc_id = _get_primary_doc_id(chunk)

    if doc_info_cache and doc_id in doc_info_cache:
        doc_info = doc_info_cache[doc_id]
        doc_title = doc_info["title"]
        doc_source_type = doc_info["source_type"]
    else:
        doc_title = _resolve_doc_title(doc_id)
        doc_source_type = _resolve_doc_source_type(doc_id)

    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": doc_id,
        "doc_title": doc_title,
        "doc_source_type": doc_source_type,
        "title": chunk.title,
        "content_preview": preview,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else chunk.knowledge_type,
        "category": chunk.category,
        "status": chunk.status.value if hasattr(chunk.status, "value") else chunk.status,
        "asset_count": len(chunk.asset_refs) if chunk.asset_refs else 0,
        "source_count": len(chunk.source_refs) if chunk.source_refs else 0,
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
        "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else None,
        "metadata": chunk.metadata if hasattr(chunk, "metadata") else {},
    }


def _enrich_asset_ref(asset_ref: AssetRef) -> dict[str, Any]:
    """将 AssetRef 扩充为含资源详情的字典，供前端直接使用。

    返回的字典包含：
    - asset_id, caption（原始字段）
    - asset_type（image/video/document_link/web_link/...）
    - storage_uri（预签名下载 URL，可直接加载）
    """
    item: dict[str, Any] = (
        asset_ref.model_dump(mode="json")
        if hasattr(asset_ref, "model_dump")
        else dict(asset_ref)
    )
    if asset_store is not None and hasattr(asset_store, "get"):
        asset = asset_store.get(asset_ref.asset_id)
        if asset:
            item["asset_type"] = (
                asset.asset_type.value
                if hasattr(asset.asset_type, "value")
                else str(asset.asset_type)
            )
            item["storage_uri"] = asset.storage_uri or ""
        else:
            item["asset_type"] = "unknown"
            item["storage_uri"] = ""
    else:
        item["asset_type"] = "unknown"
        item["storage_uri"] = ""
    return item


def _chunk_to_detail(chunk: KnowledgeChunk) -> dict[str, Any]:
    """将知识块转为详情条目（含完整内容、来源、资源、时间）。

    asset_refs 会附带资源的 asset_type、storage_uri、file_name，
    便于前端按类型分组展示并直接加载。
    """
    doc_id = _get_primary_doc_id(chunk)
    enriched_assets = [_enrich_asset_ref(r) for r in (chunk.asset_refs or [])]

    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": doc_id,
        "doc_title": _resolve_doc_title(doc_id),
        "title": chunk.title,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else chunk.knowledge_type,
        "category": chunk.category,
        "status": chunk.status.value if hasattr(chunk.status, "value") else chunk.status,
        "asset_refs": enriched_assets,
        "source_refs": [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in (chunk.source_refs or [])],
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
        "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else None,
        "metadata": chunk.metadata if hasattr(chunk, "metadata") else {},
    }


def _resolve_chunk(chunk_id: str) -> KnowledgeChunk | None:
    """从 PostgreSQL 知识块存储解析知识块。"""
    if hasattr(chunk_store, "get"):
        return chunk_store.get(chunk_id)
    return None


# ── 5.1 知识块列表 ──────────────────────────────────────────────────

@router.get("")
async def list_chunks(
    pagination: PaginationParams = Depends(),
    search: SearchParams = Depends(),
    doc_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None, description="按来源文档类型筛选（markdown/pdf/docx/html/pptx/xlsx）"),
    search_mode: str = Query(default="chunk_title", description="搜索模式: chunk_title 按知识块标题搜索, doc_title 按文档标题搜索"),
    category: str | None = Query(default=None),
    knowledge_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    has_assets: bool | None = Query(default=None),
    has_sources: bool | None = Query(default=None),
):
    """获取知识块分页列表，支持多条件筛选。"""
    if hasattr(chunk_store, "list_paginated"):
        chunks, total = chunk_store.list_paginated(
            page=pagination.page,
            page_size=pagination.page_size,
            keyword=search.keyword,
            search_mode=search_mode,
            doc_id=doc_id,
            source_type=source_type,
            category=category,
            knowledge_type=knowledge_type,
            status=status,
            has_assets=has_assets,
            has_sources=has_sources,
            sort_by=pagination.sort_by or "created_at",
            sort_order=pagination.sort_order,
        )
        # 批量预加载文档信息，消除列表页 N+1 查询
        unique_doc_ids = {_get_primary_doc_id(c) for c in chunks}
        unique_doc_ids.discard("")
        doc_info_cache = _batch_load_doc_info(unique_doc_ids) if unique_doc_ids else {}

        items = [_chunk_to_list_item(c, doc_info_cache=doc_info_cache) for c in chunks]
        total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
        meta = PaginationMeta(
            page=pagination.page, page_size=pagination.page_size,
            total=total, total_pages=total_pages,
        )
        return PaginatedResponse(data=items, metadata=meta.model_dump()).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 知识块存储不可用",
        503,
    )


# ── 5.2 创建知识块 ──────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_chunk(
    doc_id: str = Query(...),
    title: str = Query(default=""),
    content: str = Query(...),
    knowledge_type: str = Query(default="declarative"),
    category: str = Query(default="通用"),
    metadata: str | None = Query(default=None),
):
    """创建人工知识块，计算 content_hash。
    doc_id 通过 source_refs 关联，不再作为独立字段。
    """
    # 校验文档存在性
    if document_repo is not None:
        doc = document_repo.get(doc_id)
        if doc is None:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {doc_id} 不存在",
                status.HTTP_404_NOT_FOUND,
            )

    meta_dict: dict[str, Any] = {"manual": True}
    if metadata:
        try:
            meta_dict.update(json.loads(metadata))
        except json.JSONDecodeError:
            pass

    chunk = KnowledgeChunk(
        title=title,
        content=content,
        knowledge_type=KnowledgeType(knowledge_type),
        category=category,
        source_refs=[SourceRef(doc_id=doc_id, element_id="")],
        metadata=meta_dict,
    )

    # 重复内容检测
    if chunk.content_hash and hasattr(chunk_store, "find_by_content_hash"):
        dup = chunk_store.find_by_content_hash(chunk.content_hash)
        if dup is not None:
            return error_json(
                ErrorCode.CHUNK_DUPLICATE,
                f"内容与已有知识块「{dup.title or dup.chunk_id}」重复，请修改后重试。",
                status.HTTP_409_CONFLICT,
            )

    # 持久化 PG
    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    # 写入 Milvus（embedding → dense_vector + BM25 自动生成 sparse_vector）
    try:
        reindex_chunk(chunk, vector_index, bm25_index, embedding_client)
    except Exception:
        logger.exception("新建知识块索引写入失败: %s", chunk.chunk_id)

    if document_repo is not None and hasattr(document_repo, "touch_updated_at"):
        try:
            document_repo.touch_updated_at(doc_id)
        except Exception:
            logger.exception("刷新知识块归属文档更新时间失败")

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.2b 知识块 ID 列表（全选用） ─────────────────────────────────

@router.get("/ids")
async def list_chunk_ids(
    search: SearchParams = Depends(),
    search_mode: str = Query(default="chunk_title"),
    doc_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    knowledge_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    """返回当前筛选条件下的全部知识块 ID，用于批量全选操作。"""
    if hasattr(chunk_store, "list_paginated"):
        chunk_ids: list[str] = []
        page = 1
        page_size = 2000
        while True:
            chunks, total = chunk_store.list_paginated(
                page=page, page_size=page_size,
                keyword=search.keyword,
                search_mode=search_mode,
                doc_id=doc_id,
                source_type=source_type,
                category=category,
                knowledge_type=knowledge_type,
                status=status,
                sort_by="chunk_id",
                sort_order="asc",
            )
            for c in chunks:
                chunk_ids.append(c.chunk_id)
            if page * page_size >= total or not chunks:
                break
            page += 1
        return APIResponse(data=chunk_ids, metadata={"total": len(chunk_ids)}).model_dump(mode="json")

    return error_json(ErrorCode.SERVICE_UNAVAILABLE, "PostgreSQL 知识块存储不可用", 503)


# ── 5.3 知识块详情 ──────────────────────────────────────────────────

@router.get("/{chunk_id}")
async def get_chunk(chunk_id: str):
    """获取知识块详情，含完整内容、来源引用、资源引用。"""
    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.4 & 5.5 更新知识块 ───────────────────────────────────────────

@router.patch("/{chunk_id}")
async def update_chunk(
    chunk_id: str,
    title: str | None = Query(default=None),
    content: str | None = Query(default=None),
    category: str | None = Query(default=None),
    knowledge_type: str | None = Query(default=None),
    reindex: bool = Query(default=True, description="内容变化时是否重建索引"),
):
    """更新知识块字段。内容变化时重新计算 content_hash 并触发重建索引。
    若新内容哈希与已有知识块重复，返回 409 冲突提示。
    """
    from fastapi import status as http_status

    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )

    content_changed = False

    if title is not None:
        chunk.title = title
    if content is not None and content != chunk.content:
        chunk.content = content
        chunk.content_hash = compute_hash(content)
        content_changed = True
    if category is not None:
        chunk.category = category
    if knowledge_type is not None:
        try:
            chunk.knowledge_type = KnowledgeType(knowledge_type)
        except ValueError:
            return error_json(
                ErrorCode.VALIDATION_ERROR,
                f"无效的知识类型: {knowledge_type}，有效值为 {[k.value for k in KnowledgeType]}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    # ── 重复内容检测：新哈希与已有知识块冲突 ──
    if content_changed and chunk.content_hash:
        dup = chunk_store.find_by_content_hash(chunk.content_hash, exclude_chunk_id=chunk_id)
        if dup is not None:
            return error_json(
                ErrorCode.CHUNK_DUPLICATE,
                f"内容与已有知识块「{dup.title or dup.chunk_id}」重复，请修改后重试。",
                http_status.HTTP_409_CONFLICT,
            )

    # 持久化
    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    # 内容变化 → 重建索引
    if content_changed and reindex:
        reindex_chunk(chunk, vector_index, bm25_index, embedding_client)
    elif not content_changed:
        # 仅元数据变化 → 同步 Milvus
        try:
            sync_index_metadata(chunk, vector_index, bm25_index)
        except Exception:
            logger.exception("同步元数据到索引失败: %s", chunk_id)

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.6 删除和恢复知识块 ───────────────────────────────────────────

@router.delete("/{chunk_id}")
async def delete_chunk(chunk_id: str):
    """软删除知识块，仅修改状态字段。"""
    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    chunk.status = ChunkStatus.deleted
    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    # 同步 Milvus 索引
    try:
        sync_index_metadata(chunk, vector_index, bm25_index)
    except Exception:
        logger.exception("同步删除状态到索引失败: %s", chunk_id)

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


@router.post("/{chunk_id}/restore")
async def restore_chunk(chunk_id: str):
    """恢复软删除的知识块，仅修改状态字段。"""
    chunk = _resolve_chunk(chunk_id)
    if chunk is None:
        return error_json(
            ErrorCode.CHUNK_NOT_FOUND,
            f"知识块 {chunk_id} 不存在",
            status.HTTP_404_NOT_FOUND,
        )

    chunk.status = ChunkStatus.active
    if hasattr(chunk_store, "put"):
        chunk_store.put(chunk)

    # 同步 Milvus 索引
    try:
        sync_index_metadata(chunk, vector_index, bm25_index)
    except Exception:
        logger.exception("同步恢复状态到索引失败: %s", chunk_id)

    return APIResponse(data=_chunk_to_detail(chunk)).model_dump(mode="json")


# ── 5.8 批量状态操作 ───────────────────────────────────────────────

@router.post("/batch")
async def batch_chunk_operation(body: dict[str, Any] = Body(...)):
    """对多个知识块执行批量状态操作（delete / restore）。"""
    action = body.get("action", "")
    chunk_ids = body.get("chunk_ids", [])

    if not chunk_ids:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            "chunk_ids 不能为空",
            status.HTTP_400_BAD_REQUEST,
        )

    target_status: str | None = None
    if action == "delete":
        target_status = "deleted"
    elif action == "restore":
        target_status = "active"
    else:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            f"不支持的操作: {action}",
            status.HTTP_400_BAD_REQUEST,
        )

    resolved_chunks = []
    if hasattr(chunk_store, "bulk_update_status_by_chunk_ids"):
        updated = chunk_store.bulk_update_status_by_chunk_ids(chunk_ids, target_status)
        for cid in chunk_ids:
            c = _resolve_chunk(cid)
            if c:
                resolved_chunks.append(c)
    else:
        updated = 0
        for cid in chunk_ids:
            chunk = _resolve_chunk(cid)
            if chunk:
                chunk.status = ChunkStatus(target_status)
                if hasattr(chunk_store, "put"):
                    chunk_store.put(chunk)
                updated += 1
                resolved_chunks.append(chunk)

    # 同步 Milvus 索引
    if resolved_chunks:
        try:
            sync_index_metadata_batch(resolved_chunks, vector_index, bm25_index)
        except Exception:
            logger.exception("批量同步索引状态失败")

    return APIResponse(
        data={"action": action, "updated": updated},
        metadata={"total_submitted": len(chunk_ids)},
    ).model_dump(mode="json")
