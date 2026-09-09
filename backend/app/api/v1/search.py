"""检索 API v1 — 标准检索和筛选项。

POST /api/v1/search         — 标准检索，支持完整过滤和选项
GET  /api/v1/search/filters — 可用筛选项
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.v1.schemas import APIResponse, error_json
from app.core.deps import (
    asset_store,
    chunk_store,
    retrieval_pipeline,
    search_log_repo,
)
from app.core.models import new_id
from app.db.models import DbSearchLog
from app.utils.thread_pool import search_executor

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)


# ── 6.1 扩展检索请求模型 ──────────────────────────────────────────

class SearchFilters(BaseModel):
    """检索过滤条件 — 全部走 Milvus 标量字段，无需查询 PG。"""
    doc_ids: list[str] | None = Field(default=None, description="限定文档范围")
    categories: list[str] | None = Field(default=None, description="分类过滤")
    knowledge_types: list[str] | None = Field(default=None, description="知识类型过滤")
    chunk_status: list[str] | None = Field(default=None, description="知识块状态过滤")


class SearchOptions(BaseModel):
    """检索策略选项。"""
    rewrite: bool = Field(default=True, description="是否执行查询改写")
    hybrid: bool = Field(default=True, description="是否使用混合检索")
    rerank: bool = Field(default=True, description="是否执行 LLM 重排")


class SearchRequest(BaseModel):
    """v1 检索请求模型。"""
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    options: SearchOptions = Field(default_factory=SearchOptions)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _enrich_result(result_dict: dict) -> dict:
    """为 asset_refs 补充 storage_uri 和 asset_type，始终全量返回。"""
    for item in result_dict.get("results", []):
        enriched = []
        for ref in item.get("asset_refs", []):
            entry = dict(ref)
            asset_id = entry.get("asset_id", "")
            if asset_store is not None and asset_id:
                asset = asset_store.get(asset_id)
                if asset:
                    entry["asset_type"] = (
                        asset.asset_type.value
                        if hasattr(asset.asset_type, "value")
                        else str(asset.asset_type)
                    )
                    entry["storage_uri"] = asset.storage_uri or ""
                else:
                    entry["asset_type"] = "unknown"
                    entry["storage_uri"] = ""
            else:
                entry["asset_type"] = "unknown"
                entry["storage_uri"] = ""
            enriched.append(entry)
        item["asset_refs"] = enriched
    return result_dict


# ── 6.4 搜索日志异步写入 ──────────────────────────────────────────

def _write_search_log(log_entry: DbSearchLog) -> None:
    """同步写入搜索日志到 PostgreSQL（由线程池调度）。"""
    if search_log_repo is None:
        return
    try:
        search_log_repo.create(log_entry)
    except Exception:
        logger.exception("搜索日志写入失败")


# ── 6.5 标准检索 ──────────────────────────────────────────────────

@router.post("")
async def search(request: SearchRequest):
    """标准检索，支持完整过滤和策略选项。

    检索链路完全在 Milvus 内闭环：标量过滤 + 向量/BF25 双路召回，
    返回字段全量来自 Milvus 标量列，无需查询 PostgreSQL。

    每次搜索自动记录到 search_logs 表，包含查询内容、策略开关、
    各阶段召回量、耗时和状态，用于搜索质量分析和问题排查。
    """
    start_time = time.perf_counter()
    search_id = ""
    try:
        filters = request.filters
        categories: list[str] | None = list(filters.categories) if filters.categories else None
        ktypes: list[str] | None = list(filters.knowledge_types) if filters.knowledge_types else None
        doc_ids: list[str] | None = list(filters.doc_ids) if filters.doc_ids else None
        chunk_statuses: list[str] | None = list(filters.chunk_status) if filters.chunk_status else None

        # 始终以 debug=True 调用，采集各阶段统计用于日志记录
        loop = asyncio.get_running_loop()
        result, debug_info = await loop.run_in_executor(
            search_executor,
            retrieval_pipeline.search,
            request.query,
            request.top_k,
            categories,
            ktypes,
            doc_ids,
            chunk_statuses,
            True,                       # debug — 日志采集用，不影响 API 响应
            request.options.rewrite,
            request.options.hybrid,
            request.options.rerank,
        )
        search_id = result.search_id

        # 判定搜索状态：errors 非空即为 partial（有结果但某环节降级）
        status = "partial" if debug_info.errors else "success"

        result_dict = result.model_dump(mode="json")
        results = result_dict.get("results", [])

        result_dict = _enrich_result(result_dict)

        # 异步写搜索日志（不阻塞响应）
        log_entry = DbSearchLog(
            search_id=search_id,
            query=request.query,
            rewritten_query=debug_info.rewritten_query,
            top_k=request.top_k,
            filters=request.filters.model_dump(exclude_none=True),
            options=request.options.model_dump(exclude_none=True),
            total_count=result.total_count,
            result_count=len(results),
            result_chunk_ids=[item["chunk_id"] for item in results],
            vector_count=debug_info.vector_count,
            bm25_count=debug_info.bm25_count,
            timing_ms=debug_info.timing,
            status=status,
        )
        loop.run_in_executor(None, _write_search_log, log_entry)

        return APIResponse(
            data={"results": results},
            metadata={
                "search_id": search_id,
                "query": request.query,
                "rewritten_query": result_dict.get("rewritten_query", ""),
                "total_count": len(results),
                "filters": request.filters.model_dump(exclude_none=True),
                "options": request.options.model_dump(exclude_none=True),
            },
        ).model_dump(mode="json")
    except Exception as e:
        total_ms = int((time.perf_counter() - start_time) * 1000)
        logger.exception("检索失败")

        # 异步写错误日志
        try:
            loop = asyncio.get_running_loop()
            error_entry = DbSearchLog(
                search_id=search_id or new_id("search"),
                query=request.query,
                rewritten_query="",
                top_k=request.top_k,
                filters=request.filters.model_dump(exclude_none=True),
                options=request.options.model_dump(exclude_none=True),
                total_count=0,
                result_count=0,
                vector_count=0,
                bm25_count=0,
                timing_ms={"total_ms": total_ms},
                status="error",
                error_message=str(e),
            )
            loop.run_in_executor(None, _write_search_log, error_entry)
        except Exception:
            pass  # 日志写入失败不影响错误响应

        return error_json("INTERNAL_ERROR", f"检索失败: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── 6.6 检索筛选项 ────────────────────────────────────────────────

@router.get("/filters")
async def search_filters():
    """返回可用筛选项：分类、知识类型、知识块状态。"""
    filter_options: dict[str, list[dict[str, Any]]] = {
        "categories": [],
        "knowledge_types": [],
        "chunk_statuses": [],
    }

    cats: dict[str, int] = {}
    if hasattr(chunk_store, "list_all"):
        try:
            chunks = chunk_store.list_all()
            kts: dict[str, int] = {}
            ch_stats: dict[str, int] = {}
            for c in chunks:
                cat = c.category or "通用"
                cats[cat] = cats.get(cat, 0) + 1
                kt = c.knowledge_type.value if hasattr(c.knowledge_type, "value") else str(c.knowledge_type)
                kts[kt] = kts.get(kt, 0) + 1
                st = c.status.value if hasattr(c.status, "value") else str(c.status)
                ch_stats[st] = ch_stats.get(st, 0) + 1

            filter_options["knowledge_types"] = [{"value": k, "count": v} for k, v in kts.items()]
            filter_options["chunk_statuses"] = [{"value": k, "count": v} for k, v in ch_stats.items()]
        except Exception:
            pass

    # 分类统计优先从 PG 文档表获取（覆盖所有文档，含尚无 chunk 的新文档），不可用时回退 chunk_store
    from app.core.deps import document_repo  # noqa: E402
    if document_repo is not None and hasattr(document_repo, "list_paginated"):
        try:
            doc_categories: dict[str, int] = {}
            page = 1
            page_size = 200
            while True:
                docs, total = document_repo.list_paginated(page=page, page_size=page_size)
                for doc in docs:
                    cat_name = getattr(doc, "category", None) or "通用"
                    doc_categories[cat_name] = doc_categories.get(cat_name, 0) + 1
                if page * page_size >= total or not docs:
                    break
                page += 1
            filter_options["categories"] = [
                {"value": value, "count": count}
                for value, count in sorted(doc_categories.items())
            ]
        except Exception:
            pass

    if not filter_options["categories"]:
        filter_options["categories"] = [{"value": k, "count": v} for k, v in cats.items()]

    return APIResponse(data=filter_options).model_dump(mode="json")
