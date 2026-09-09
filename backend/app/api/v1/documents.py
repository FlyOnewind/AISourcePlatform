"""文档管理 API v1 — 列表、创建、详情、更新、软删除、恢复和入库动作。

所有端点均返回统一的 APIResponse / PaginatedResponse 结构。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi import status as http_status

from app.api import upload_utils as upload_api
from app.api.v1.errors import ErrorCode
from app.api.v1.schemas import (
    APIResponse,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    SearchParams,
    error_json,
)
from app.api.v1.services import sync_index_metadata_batch
from app.core.deps import (
    asset_store,
    bm25_index,
    chunk_store,
    document_repo,
    element_repo,
    ingestion_pipeline,
    vector_index,
)
from app.core.errors import (
    DocumentNotFoundError,
    DuplicateDocumentError,
)
from app.core.config import settings
from app.core.models import ChunkStatus, DocStatus, Document, compute_hash, new_id
from app.utils.thread_pool import upload_executor

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _build_index_summary(doc_id: str) -> dict[str, int]:
    """构建文档的知识块统计摘要。"""
    if hasattr(chunk_store, "count_by_doc_id"):
        try:
            total = chunk_store.count_by_doc_id(doc_id)
            return {"total": total}
        except Exception:
            pass
    return {"total": 0}


def _build_doc_stats(doc_id: str) -> dict[str, int | dict]:
    """构建文档统计信息。"""
    stats: dict[str, Any] = {"chunk_count": 0, "element_count": 0, "asset_count": 0}

    # 统计 chunk 数量
    if hasattr(chunk_store, "count_by_doc_id"):
        stats["chunk_count"] = chunk_store.count_by_doc_id(doc_id)
    elif hasattr(chunk_store, "list_by_doc_id"):
        stats["chunk_count"] = len(chunk_store.list_by_doc_id(doc_id))

    # 统计 element 数量
    if element_repo is not None:
        elements = element_repo.get_by_doc_id(doc_id)
        stats["element_count"] = len(elements)

    # 统计 asset 数量
    if asset_store is not None and hasattr(asset_store, "count_by_doc_id"):
        stats["asset_count"] = asset_store.count_by_doc_id(doc_id)
    elif asset_store is not None and hasattr(asset_store, "get_by_doc_id"):
        stats["asset_count"] = len(asset_store.get_by_doc_id(doc_id))

    stats["index_summary"] = _build_index_summary(doc_id)
    return stats


def _doc_to_item(doc: Document) -> dict[str, Any]:
    """将 Document 转为前端展示条目（含统计）。"""
    item = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "source_type": doc.source_type,
        "source_uri": doc.source_uri,
        "source_hash": doc.source_hash,
        "category": doc.category,
        "version": doc.version,
        "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
        "parent_doc_id": doc.parent_doc_id,
        "root_doc_id": doc.root_doc_id,
        "previous_doc_id": doc.previous_doc_id,
        "error_message": doc.error_message,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "metadata": doc.metadata if hasattr(doc, "metadata") else {},
    }
    # 附加统计
    try:
        item.update(_build_doc_stats(doc.doc_id))
    except Exception:
        item.update({"chunk_count": 0, "element_count": 0, "asset_count": 0, "index_summary": {}})
    return item


def _element_to_item(element: Any) -> dict[str, Any]:
    """将解析元素转为前端可展示条目。"""
    return {
        "element_id": element.element_id,
        "doc_id": element.doc_id,
        "doc_version": element.doc_version,
        "parent_element_id": element.parent_element_id,
        "sequence_order": element.sequence_order,
        "element_type": element.element_type.value if hasattr(element.element_type, "value") else element.element_type,
        "text": element.text,
        "structured_data": element.structured_data,
        "asset_data": [ad.model_dump(mode="json") for ad in element.asset_data],
        "source_location": (
            element.source_location.model_dump(mode="json")
            if hasattr(element.source_location, "model_dump")
            else element.source_location
        ),
        "metadata": element.metadata if hasattr(element, "metadata") else {},
    }


def _source_type_from_filename(filename: str) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    return {
        "md": "markdown",
        "markdown": "markdown",
        "txt": "txt",
        "docx": "docx",
        "xlsx": "xlsx",
        "html": "html",
        "htm": "html",
        "pdf": "pdf",
        "pptx": "pptx",
    }.get(ext, "unknown")


def _cleanup_old_doc(old_doc_id: str) -> None:
    """软删除旧文档并同步关联知识块索引状态。

    用于文档更新/替换场景：新文件已成功写入 MinIO 后，
    清理旧文档及其 chunk 的索引条目。
    """
    if document_repo is None:
        return
    try:
        document_repo.soft_delete(old_doc_id)
        if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
            chunk_store.bulk_update_status_by_doc_id(old_doc_id, "deleted")
        if hasattr(chunk_store, "list_by_doc_id"):
            old_chunks = chunk_store.list_by_doc_id(old_doc_id)
            if old_chunks:
                sync_index_metadata_batch(old_chunks, vector_index, bm25_index)
    except Exception:
        logger.exception(
            "软删除旧文档失败: %s（新文档已就位，可手动清理）", old_doc_id,
        )


# ── 4.1 文档列表 ──────────────────────────────────────────────────

@router.get("/ids")
async def list_document_ids(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
):
    """只返回符合条件的 doc_id 列表，供全选等批量操作使用。"""
    if document_repo is None or not hasattr(document_repo, "list_paginated"):
        return error_json(ErrorCode.SERVICE_UNAVAILABLE, "不可用", http_status.HTTP_503_SERVICE_UNAVAILABLE)

    all_ids = []
    page = 1
    while True:
        docs, total = document_repo.list_paginated(
            page=page, page_size=1000,
            keyword=keyword, status=status, category=category,
            sort_by="created_at", sort_order="desc",
        )
        for d in docs:
            all_ids.append(d.doc_id)
        if page * 1000 >= total:
            break
        page += 1

    return APIResponse(data=all_ids).model_dump(mode="json")


@router.get("")
async def list_documents(
    pagination: PaginationParams = Depends(),
    search: SearchParams = Depends(),
    source_type: str | None = Query(default=None, description="按来源类型过滤"),
    status: str | None = Query(default=None, description="按状态过滤"),
    category: str | None = Query(default=None, description="按分类过滤"),
    parent_doc_id: str | None = Query(default=None, description="按父文档过滤"),
    root_doc_id: str | None = Query(default=None, description="按根文档过滤"),
):
    """获取文档分页列表，支持多条件筛选和排序。

    返回统一的 PaginatedResponse 结构，每个文档条目包含统计信息。
    """
    # ── PostgreSQL 后端 ──
    if document_repo is not None and hasattr(document_repo, "list_paginated"):
        docs, total = document_repo.list_paginated(
            page=pagination.page,
            page_size=pagination.page_size,
            keyword=search.keyword,
            source_type=source_type,
            status=status,
            category=category,
            parent_doc_id=parent_doc_id,
            root_doc_id=root_doc_id,
            sort_by=pagination.sort_by or "updated_at",
            sort_order=pagination.sort_order,
        )
        items = [_doc_to_item(d) for d in docs]
        total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
        meta = PaginationMeta(
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
            total_pages=total_pages,
        )
        return PaginatedResponse(data=items, metadata=meta.model_dump()).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── 4.2 创建文档 ──────────────────────────────────────────────────

@router.post("", status_code=http_status.HTTP_201_CREATED)
async def create_document(
    title: str = Body(...),
    source_type: str = Body(...),
    source_uri: str = Body(...),
    source_hash: str = Body(default=""),
    category: str = Body(default="通用"),
    metadata: str | None = Body(default=None, description="JSON 格式的元数据"),
):
    """创建新文档并立即提交异步入库任务。

    与 upload 端点一致，必定触发异步入库（不可跳过）。
    HTTP 请求在 Document 创建后立即返回 job_id，
    Worker 异步执行 ingest。
    """
    import json

    meta_dict: dict[str, Any] = {}
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            pass

    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        # 去重检查
        if source_hash:
            existing = document_repo.find_by_hash(source_hash)
            if existing is not None:
                return error_json(
                    ErrorCode.DOCUMENT_DUPLICATE,
                    f"相同 source_hash 的文档已存在: {existing.doc_id}",
        http_status.HTTP_409_CONFLICT,
                    details={"existing_doc_id": existing.doc_id},
                )

        doc = Document(
            title=title,
            source_type=source_type,
            source_uri=source_uri,
            source_hash=source_hash,
            category=category,
            metadata=meta_dict,
        )
        try:
            created = document_repo.create(doc)
        except DuplicateDocumentError as e:
            return error_json(
                ErrorCode.DOCUMENT_DUPLICATE,
                str(e),
    http_status.HTTP_409_CONFLICT,
            )

        response_data = _doc_to_item(created)

        # 创建 Job + 入队 Dramatiq（异步入库，不阻塞 HTTP 响应）
        try:
            from app.core.deps import job_repo
            from app.core.models import IngestJob
            from app.tasks.ingest import ingest_document

            job = IngestJob(job_id=new_id("job"), doc_id=created.doc_id)
            job_repo.create(job)
            ingest_document.send(job.job_id, created.doc_id)
            response_data["job_id"] = job.job_id
        except Exception as e:
            logger.exception("入队失败: %s", created.doc_id)
            response_data["ingest_error"] = str(e)

        return APIResponse(data=response_data).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.post("/upload", status_code=http_status.HTTP_201_CREATED)
async def upload_documents(
    files: list[UploadFile] = File(...),
    category: str = Form(default=upload_api.DEFAULT_CATEGORY),
    replace_doc_id: str | None = Form(default=None),
    confirm_replace: bool = Form(default=False),
):
    """上传文件（支持单文件或多文件），创建文档并提交异步入库任务。

    单文件模式（len(files)==1）：支持 replace_doc_id / confirm_replace 替换流程。
    多文件模式：跳过替换逻辑，逐个验证后批量写入 MinIO 并入队。

    一次 HTTP 请求完成全部文件处理，避免浏览器并发多个请求阻塞主线程。
    """
    loop = asyncio.get_running_loop()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    resolved_category = category or upload_api.DEFAULT_CATEGORY

    # ── 逐个验证 ──
    valid_items: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    is_single = len(files) == 1

    for f in files:
        original_name = f.filename or "upload"
        f.file.seek(0, 2)
        size = f.file.tell()
        f.file.seek(0)
        if size > max_bytes:
            results.append({"file_name": original_name, "size": size, "duplicate": False, "error": f"文件大小 {size / 1024 / 1024:.1f} MB 超过上限"})
            continue

        file_content = f.file.read()
        source_hash = compute_hash(file_content)
        content_type = f.content_type or "application/octet-stream"
        resolved_title = Path(original_name).stem

        # 重复内容检测
        if document_repo is not None:
            existing = document_repo.find_by_hash(source_hash)
            if existing is not None:
                results.append({"file_name": original_name, "size": size, "duplicate": True, "doc_id": existing.doc_id, "title": existing.title, "category": existing.category})
                continue

        # 单文件替换流程
        old_doc = None
        replace_id = None
        if is_single and replace_doc_id and confirm_replace and document_repo is not None:
            old_doc = document_repo.get(replace_doc_id)
            if old_doc is None:
                return error_json(ErrorCode.DOCUMENT_NOT_FOUND, f"要替换的文档 {replace_doc_id} 不存在", http_status.HTTP_404_NOT_FOUND)
            if old_doc.status != DocStatus.active:
                return error_json(ErrorCode.DOCUMENT_NOT_FOUND, f"文档 {replace_doc_id} 状态不是 active，无法替换", http_status.HTTP_409_CONFLICT)
            resolved_title = old_doc.title
            resolved_category = old_doc.category
            replace_id = replace_doc_id

        valid_items.append({"file_content": file_content, "original_name": original_name, "size": size, "source_hash": source_hash, "resolved_title": resolved_title, "content_type": content_type, "old_doc": old_doc, "replace_doc_id": replace_id})

    if not valid_items:
        dup = sum(1 for r in results if r.get("duplicate"))
        err = sum(1 for r in results if r.get("error"))
        return APIResponse(data={"files": results, "total": len(files), "success": 0, "duplicate": dup, "failed": err}).model_dump(mode="json")

    # ── 批量写入 MinIO + 入队（线程池顺序执行） ──
    batch_results = await loop.run_in_executor(upload_executor, _batch_upload_sync, valid_items, resolved_category)
    results.extend(batch_results)
    success = sum(1 for r in results if r.get("job_id") and not r.get("duplicate") and not r.get("error"))
    dup = sum(1 for r in results if r.get("duplicate"))
    failed = len(results) - success - dup

    return APIResponse(data={"files": results, "total": len(files), "success": success, "duplicate": dup, "failed": failed}).model_dump(mode="json")


def _batch_upload_sync(items: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    """在线程池中逐文件写入 MinIO + 创建 Job + 入队 Dramatiq。"""
    results: list[dict[str, Any]] = []
    for item in items:
        try:
            result = _do_upload_sync(
                file_content=item["file_content"], original_name=item["original_name"],
                size=item["size"], source_hash=item["source_hash"],
                resolved_title=item["resolved_title"], resolved_category=category,
                content_type=item["content_type"], old_doc=item.get("old_doc"),
                replace_doc_id=item.get("replace_doc_id"),
            )
            results.append(result)
        except Exception:
            logger.exception("批量上传写入失败: %s", item["original_name"])
            results.append({"file_name": item["original_name"], "size": item["size"], "duplicate": False, "error": "文件保存失败"})
    return results


# ═══════════════════════════════════════════════════════════════════════
# 上传同步阶段（在线程池中同步执行 MinIO 写入 + 入队，不阻塞事件循环）
# ═══════════════════════════════════════════════════════════════════════


def _do_upload_sync(
    file_content: bytes,
    original_name: str,
    size: int,
    source_hash: str,
    resolved_title: str,
    resolved_category: str,
    content_type: str,
    old_doc: Document | None,
    replace_doc_id: str | None,
) -> dict[str, Any]:
    """上传同步阶段：预占位 → MinIO → 旧文档清理 → 创建 Job + 入队。

    入库（ingest）不在本函数中执行，而是由 Dramatiq Worker 异步消费。
    仅做必须在 HTTP 请求中完成的操作（文件写入 MinIO），返回 job_id 给前端。
    """
    # ── [5] 创建 Document 预占位 ──
    pre_doc_id = new_id("doc")
    doc = Document(
        doc_id=pre_doc_id,
        title=resolved_title,
        source_type=_source_type_from_filename(original_name),
        source_uri="",  # 文件写入后更新
        source_hash=source_hash,
        category=resolved_category,
        previous_doc_id=replace_doc_id if old_doc else None,
    )

    if document_repo is not None:
        try:
            doc = document_repo.create(doc)
        except DuplicateDocumentError as e:
            return error_json(
                ErrorCode.DOCUMENT_DUPLICATE,
                str(e),
                http_status.HTTP_409_CONFLICT,
            )

    # ── [6] 写文件到 MinIO ──
    upload_data: dict[str, Any] = {}
    try:
        upload_data = upload_api.save_upload_file(
            file_content,
            original_name,
            size,
            title=resolved_title,
            category=resolved_category,
            content_type=content_type,
            doc_id=pre_doc_id,
        )
    except Exception:
        logger.exception("文件写入 MinIO 失败: %s", pre_doc_id)
        if document_repo is not None:
            try:
                document_repo.hard_delete(pre_doc_id)
            except Exception:
                logger.exception("回滚预占位失败: %s", pre_doc_id)
        return error_json(
            ErrorCode.INTERNAL_ERROR,
            "文件保存失败",
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # ── [7] 更新 source_uri ──
    doc.source_uri = upload_data["source_uri"]
    if document_repo is not None:
        try:
            doc = document_repo.update(doc)
        except Exception:
            logger.exception("更新 source_uri 失败: %s", pre_doc_id)

    # ── [8] 软删除旧文档 + 同步旧 chunk 索引（更新场景） ──
    replaced = old_doc is not None
    if old_doc is not None:
        _cleanup_old_doc(old_doc.doc_id)

    # ── [9] 创建 IngestJob + 入队 Dramatiq（不再同步 ingest） ──
    from app.core.deps import job_repo
    from app.core.models import IngestJob
    from app.tasks.ingest import ingest_document

    job_id = new_id("job")
    job = IngestJob(
        job_id=job_id,
        doc_id=pre_doc_id,
        stage="",
        progress=0,
    )

    if job_repo is not None:
        try:
            job = job_repo.create(job)
        except Exception:
            logger.exception("创建 IngestJob 失败: %s", pre_doc_id)
            return error_json(
                ErrorCode.INTERNAL_ERROR,
                "创建入库任务失败，请重试",
                http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # 入队 Dramatiq 任务
    try:
        message = ingest_document.send(job_id, pre_doc_id)
        job.dramatiq_message_id = message.message_id
        if job_repo is not None:
            job_repo.update(job)
    except Exception:
        logger.exception("Dramatiq 入队失败: job_id=%s, doc_id=%s", job_id, pre_doc_id)
        # 入队失败 → 全量回滚（删除 job + doc），用户可原样重传，不会被 hash 去重拦
        if job_repo is not None:
            try:
                job_repo.hard_delete(job_id)
            except Exception:
                logger.exception("回滚 job 失败: %s", job_id)
        if document_repo is not None:
            try:
                document_repo.hard_delete(pre_doc_id)
            except Exception:
                logger.exception("回滚 doc 失败: %s", pre_doc_id)
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "任务队列不可用，请稍后重试",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # ── 构造响应 ──
    response_data = _doc_to_item(doc)
    response_data.update({
        "job_id": job_id,
        "duplicate": False,
        "suggested_replace": False,
        "replaced": replaced,
        "replaced_doc_id": replace_doc_id if replaced else None,
        "file_name": original_name,
        "size": upload_data["size"],
    })
    return APIResponse(data=response_data).model_dump(mode="json")


# ── 4.3 文档详情 ──────────────────────────────────────────────────

@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """获取文档详情、统计信息和元数据。"""
    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        doc = document_repo.get(doc_id)
        if doc is None:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {doc_id} 不存在",
    http_status.HTTP_404_NOT_FOUND,
            )

        item = _doc_to_item(doc)
        # 补充聚合统计
        if hasattr(document_repo, "get_stats"):
            item.update(document_repo.get_stats(doc_id))
        return APIResponse(data=item).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── 4.3.1 更新文档元数据 ───────────────────────────────────────────

@router.patch("/{doc_id}")
async def update_document(
    doc_id: str,
    title: str | None = Query(default=None),
    category: str | None = Query(default=None),
):
    """更新文档的标题和分类等元数据，并同步到关联知识块的 PG 和 Milvus。"""
    if document_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 文档仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    doc = document_repo.get(doc_id)
    if doc is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )

    # ── 构建变更字段 ──
    chunk_updates: dict = {}
    if title is not None:
        doc.title = title
        chunk_updates["title"] = title
    if category is not None:
        doc.category = category
        chunk_updates["category"] = category

    try:
        updated = document_repo.update(doc)
    except DocumentNotFoundError as e:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            str(e),
            http_status.HTTP_404_NOT_FOUND,
        )

    # ── 同步关联知识块：PG 批量更新 + Milvus 逐条同步 ──
    if chunk_updates and hasattr(chunk_store, "bulk_update_fields_by_doc_id"):
        try:
            synced_chunks = chunk_store.bulk_update_fields_by_doc_id(doc_id, chunk_updates)
            sync_index_metadata_batch(synced_chunks, vector_index, bm25_index)
        except Exception:
            logger.exception("批量更新 chunk 元数据失败")

    return APIResponse(data=_doc_to_item(updated)).model_dump(mode="json")


@router.get("/{doc_id}/elements")
async def list_document_elements(
    doc_id: str,
    pagination: PaginationParams = Depends(),
):
    """获取文档解析元素分页列表。"""
    if document_repo is not None and document_repo.get(doc_id) is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )

    if element_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 解析元素仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    elements = sorted(
        element_repo.get_by_doc_id(doc_id),
        key=lambda element: element.sequence_order,
    )
    total = len(elements)
    start = (pagination.page - 1) * pagination.page_size
    end = start + pagination.page_size
    total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
    meta = PaginationMeta(
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        total_pages=total_pages,
    )
    return PaginatedResponse(
        data=[_element_to_item(element) for element in elements[start:end]],
        metadata=meta.model_dump(),
    ).model_dump(mode="json")


# ── 4.4 软删除文档 ────────────────────────────────────────────────

@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """软删除文档，将关联活跃知识块状态设置为 deleted 并同步索引。"""
    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        chunks_to_sync = []
        if hasattr(chunk_store, "list_by_doc_id"):
            chunks_to_sync = [
                c for c in chunk_store.list_by_doc_id(doc_id)
                if (c.status.value if hasattr(c.status, "value") else c.status) != "deleted"
            ]
        try:
            doc = document_repo.soft_delete(doc_id)
        except DocumentNotFoundError as e:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                str(e),
    http_status.HTTP_404_NOT_FOUND,
            )

        # 同步删除关联知识块
        if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
            chunk_store.bulk_update_status_by_doc_id(doc_id, "deleted")

        # 在索引中批量标记知识块为已删除
        if chunks_to_sync:
            for c in chunks_to_sync:
                c.status = ChunkStatus.deleted
            sync_index_metadata_batch(chunks_to_sync, vector_index, bm25_index)

        return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ── 4.4b 批量软删除文档 ──────────────────────────────────────────

@router.post("/batch-delete")
async def batch_delete_documents(body: dict[str, Any] = Body(...)):
    """批量软删除文档，同步关联知识块状态到 Milvus。"""
    doc_ids: list[str] = body.get("doc_ids", [])

    if not doc_ids:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            "doc_ids 不能为空",
            http_status.HTTP_400_BAD_REQUEST,
        )

    if document_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 文档仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # 一次性收集所有待同步的知识块 ID
    all_chunk_ids: list[str] = []
    if hasattr(chunk_store, "list_by_doc_ids"):
        for c in chunk_store.list_by_doc_ids(doc_ids):
            status = c.status.value if hasattr(c.status, "value") else c.status
            if status != "deleted":
                all_chunk_ids.append(c.chunk_id)

    # 批量软删除文档
    updated = document_repo.bulk_soft_delete(doc_ids)

    # 批量更新关联知识块 PG 状态（一条 UPDATE）
    if hasattr(chunk_store, "bulk_update_status_by_doc_ids"):
        try:
            chunk_store.bulk_update_status_by_doc_ids(doc_ids, "deleted")
        except Exception:
            logger.exception("批量更新知识块状态失败")

    # 批量同步 Milvus（一次 RPC）
    if all_chunk_ids:
        manager = getattr(vector_index, "manager", None)
        if manager is not None and hasattr(manager, "delete_batch"):
            try:
                manager.delete_batch(all_chunk_ids)
            except Exception:
                logger.exception("批量同步 Milvus 删除状态失败")
        else:
            for cid in all_chunk_ids:
                try:
                    vector_index.delete(cid)
                except Exception:
                    pass

    return APIResponse(
        data={"action": "delete", "updated": updated},
        metadata={"total_submitted": len(doc_ids)},
    ).model_dump(mode="json")


# ── 4.4c 批量重试文档 ──────────────────────────────────────────

@router.post("/batch-retry")
async def batch_retry_documents(body: dict[str, Any] = Body(...)):
    """批量重试失败文档，提交到线程池异步入库。"""
    doc_ids: list[str] = body.get("doc_ids", [])

    if not doc_ids:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            "doc_ids 不能为空",
            http_status.HTTP_400_BAD_REQUEST,
        )

    if document_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 文档仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    submitted = 0
    skipped: list[str] = []

    for doc_id in doc_ids:
        doc = document_repo.get(doc_id)
        if doc is None or doc.status != DocStatus.failed:
            skipped.append(doc_id)
            continue
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            upload_executor,
            ingestion_pipeline.ingest,
            doc,
        )
        submitted += 1

    return APIResponse(
        data={"action": "retry", "submitted": submitted, "skipped": len(skipped)},
        metadata={"total_submitted": len(doc_ids)},
    ).model_dump(mode="json")


# ── 4.4d 批量恢复文档 ──────────────────────────────────────────

@router.post("/batch-restore")
async def batch_restore_documents(body: dict[str, Any] = Body(...)):
    """批量恢复已删除的文档到删前状态。

    - 简单恢复（previous_status=active）：批量改状态 + 同步索引
    - 复杂恢复（previous_status=failed/processing）：提交到线程池重入库
    """
    doc_ids: list[str] = body.get("doc_ids", [])

    if not doc_ids:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            "doc_ids 不能为空",
            http_status.HTTP_400_BAD_REQUEST,
        )

    if document_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 文档仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    simple_docs: list[Document] = []
    complex_docs: list[Document] = []

    for doc_id in doc_ids:
        doc = document_repo.get(doc_id)
        if doc is None or doc.status != DocStatus.deleted:
            continue
        previous_status = (doc.metadata or {}).get("previous_status", "active")
        if previous_status in ("failed", "processing"):
            complex_docs.append(doc)
        else:
            simple_docs.append(doc)

    restored = 0
    re_ingested = 0

    # ── 简单恢复：批量改文档状态 ──
    for doc in simple_docs:
        doc.status = DocStatus.active
        doc.updated_at = datetime.now(timezone.utc)
        if doc.metadata and "previous_status" in doc.metadata:
            del doc.metadata["previous_status"]
        try:
            document_repo.update(doc)
            restored += 1
        except Exception:
            logger.exception("批量恢复文档失败: %s", doc.doc_id)

    # ── 批量更新知识块状态（一条 UPDATE） ──
    simple_doc_ids = [d.doc_id for d in simple_docs]
    if simple_doc_ids and hasattr(chunk_store, "bulk_update_status_by_doc_ids"):
        try:
            chunk_store.bulk_update_status_by_doc_ids(simple_doc_ids, "active")
        except Exception:
            logger.exception("批量恢复知识块状态失败")

    # ── 批量同步 Milvus（一次查询 + 一次 RPC） ──
    if simple_doc_ids and hasattr(chunk_store, "list_by_doc_ids"):
        simple_chunks = chunk_store.list_by_doc_ids(simple_doc_ids)
        if simple_chunks:
            try:
                sync_index_metadata_batch(simple_chunks, vector_index, bm25_index)
            except Exception:
                logger.exception("批量恢复 Milvus 状态失败")

    # ── 复杂恢复：提交到线程池重入库 ──
    loop = asyncio.get_running_loop()
    for doc in complex_docs:
        loop.run_in_executor(
            upload_executor,
            ingestion_pipeline.ingest,
            doc,
        )
        re_ingested += 1

    return APIResponse(
        data={
            "action": "restore",
            "restored": restored,
            "re_ingested": re_ingested,
        },
        metadata={"total_submitted": len(doc_ids)},
    ).model_dump(mode="json")


# ── 4.5 恢复文档 ──────────────────────────────────────────────────

@router.post("/{doc_id}/restore")
async def restore_document(doc_id: str):
    """恢复软删除的文档到删前状态。

    - active → 改状态 + 知识块回索引（轻量）
    - failed / processing → 重走入库流程（全量重建）
    """
    if document_repo is None:
        return error_json(ErrorCode.SERVICE_UNAVAILABLE, "PostgreSQL 文档仓储不可用", 503)

    doc = document_repo.get(doc_id)
    if doc is None:
        return error_json(ErrorCode.DOCUMENT_NOT_FOUND, f"文档 {doc_id} 不存在", 404)

    # 只有 deleted 状态的文档才能恢复
    if doc.status != DocStatus.deleted:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            f"文档 {doc_id} 当前状态为 {doc.status.value}，只能恢复已删除的文档",
            400,
        )

    # 读取删前状态（由 soft_delete 写入 metadata）
    previous_status = (doc.metadata or {}).get("previous_status", "active")

    # 检查 source_hash 唯一约束：若已有活跃/处理中/等待中 文档持有相同 hash，阻止恢复
    if doc.source_hash:
        existing = document_repo.find_by_hash(
            doc.source_hash, statuses=["active", "processing", "pending"],
        )
        if existing and existing.doc_id != doc_id:
            return error_json(
                ErrorCode.DOCUMENT_DUPLICATE,
                f"无法恢复文档：已存在相同内容的活跃文档（doc_id: {existing.doc_id}），"
                f"请先删除该文档后再恢复",
                409,
            )

    if previous_status == "active":
        # 活跃删除恢复：只改状态 + 知识块回索引（轻量，不重入库）
        doc = document_repo.restore(doc_id)
        if hasattr(chunk_store, "bulk_update_status_by_doc_id"):
            chunk_store.bulk_update_status_by_doc_id(doc_id, "active")
        if hasattr(chunk_store, "list_by_doc_id"):
            restored_chunks = chunk_store.list_by_doc_id(doc_id)
            if restored_chunks:
                sync_index_metadata_batch(restored_chunks, vector_index, bm25_index)

    elif previous_status == "failed":
        # 失败删除恢复：重走入库（在线程池中执行，避免阻塞事件循环）
        loop = asyncio.get_running_loop()
        doc = await loop.run_in_executor(
            upload_executor,
            ingestion_pipeline.ingest,
            doc,
        )

    elif previous_status == "processing":
        # 处理中删除恢复：同上，重走入库
        loop = asyncio.get_running_loop()
        doc = await loop.run_in_executor(
            upload_executor,
            ingestion_pipeline.ingest,
            doc,
        )

    return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")


# ── 4.5.1 重试失败文档 ─────────────────────────────────────────────

@router.post("/{doc_id}/retry")
async def retry_document(doc_id: str):
    """重新触发失败文档的入库流水线。"""
    if document_repo is None:
        return error_json(
            ErrorCode.SERVICE_UNAVAILABLE,
            "PostgreSQL 文档仓储不可用",
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    doc = document_repo.get(doc_id)
    if doc is None:
        return error_json(
            ErrorCode.DOCUMENT_NOT_FOUND,
            f"文档 {doc_id} 不存在",
            http_status.HTTP_404_NOT_FOUND,
        )
    if doc.status != DocStatus.failed:
        return error_json(
            ErrorCode.VALIDATION_ERROR,
            "只能重试失败状态的文档",
            http_status.HTTP_400_BAD_REQUEST,
        )

    # 检查是否已有同名活跃文档
    if doc.source_hash:
        active_dup = document_repo.find_by_hash(doc.source_hash)
        if active_dup is not None and active_dup.doc_id != doc_id:
            return error_json(
                ErrorCode.DOCUMENT_DUPLICATE,
                f"已存在内容相同的活跃文档「{active_dup.title}」，无法重试",
                http_status.HTTP_409_CONFLICT,
                details={"existing_doc_id": active_dup.doc_id},
            )

    # 重新入库（在线程池中执行，避免阻塞事件循环）
    loop = asyncio.get_running_loop()
    try:
        doc = await loop.run_in_executor(
            upload_executor,
            ingestion_pipeline.ingest,
            doc,
        )
    except Exception:
        logger.exception("重试入库失败")
        return error_json(
            ErrorCode.INTERNAL_ERROR,
            "重试入库失败",
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return APIResponse(data=_doc_to_item(doc)).model_dump(mode="json")


# ── 4.6 版本历史 ──────────────────────────────────────────────────

@router.get("/{doc_id}/history")
async def get_document_history(doc_id: str):
    """获取文档的版本历史。"""
    # ── PostgreSQL 后端 ──
    if document_repo is not None:
        try:
            history = document_repo.get_version_history(doc_id)
        except DocumentNotFoundError:
            return error_json(
                ErrorCode.DOCUMENT_NOT_FOUND,
                f"文档 {doc_id} 不存在",
                http_status.HTTP_404_NOT_FOUND,
            )

        # 返回简化的版本信息
        history_items = []
        for doc in history:
            history_items.append({
                "doc_id": doc.doc_id,
                "title": doc.title,
                "version": doc.version,
                "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "previous_doc_id": doc.previous_doc_id,
            })

        return APIResponse(data=history_items).model_dump(mode="json")

    return error_json(
        ErrorCode.SERVICE_UNAVAILABLE,
        "PostgreSQL 文档仓储不可用",
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )
