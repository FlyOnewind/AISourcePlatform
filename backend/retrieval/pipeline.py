"""检索流水线 — 编排查询改写、双路检索、RRF 融合、LLM 重排序的完整流程。

检索流程（5 个阶段）：
1. 查询改写：LLM 将用户查询改写为陈述句 + 关键词列表
2. Embedding：对改写后的查询生成稠密向量
3. 双路并行检索：向量检索（HNSW + COSINE）+ BM25 关键词检索
4. RRF 融合：倒数排序融合两路结果
5. LLM Rerank：对融合后的候选逐条打分，按相关性降序输出

Milvus 返回全量标量字段，无需查询 PG 即可构建 SearchResult。
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.models import (
    KnowledgeChunk,
    KnowledgeType,
    ScoreComponents,
    SearchResult,
    SearchResultItem,
    SourceLocation,
    SourceRef,
)


@dataclass
class RetrievalDebugInfo:
    """检索全链路调试信息数据类。

    记录查询改写、各阶段候选列表、统计数据和错误信息，
    仅在 search(debug=True) 时填充并返回。
    """
    # 查询改写
    original_query: str
    rewritten_query: str
    keywords: list[str] = field(default_factory=list)
    # 各阶段候选 (chunk_id, score)
    vector_candidates: list[tuple[str, float]] = field(default_factory=list)
    bm25_candidates: list[tuple[str, float]] = field(default_factory=list)
    fused_candidates: list[tuple[str, float]] = field(default_factory=list)
    rerank_results: list[dict] = field(default_factory=list)
    # 统计
    vector_count: int = 0
    bm25_count: int = 0
    fused_count: int = 0
    rerank_count: int = 0
    errors: list[str] = field(default_factory=list)
    # 各阶段耗时（毫秒，int）
    timing: dict[str, int] = field(default_factory=dict)
from assets.base import AssetStore
from indexing.base import BM25Index, VectorIndex
from indexing.fusion import rrf_fusion
from llm.query_rewriter import QueryRewriter
from llm.reranker import Reranker
from llm.volcengine_client import embedding_client

logger = logging.getLogger(__name__)


def _parse_json_field(raw: Any, default: Any = None) -> Any:
    """解析 Milvus VARCHAR 存储的 JSON 字符串字段。"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return default
    return raw if raw is not None else default


def _renderable_storage_uri(storage_uri: str | None) -> str | None:
    if not storage_uri:
        return storage_uri
    if storage_uri.startswith(("http://", "https://", "file://", "minio://")):
        return storage_uri
    return f"file:///{Path(storage_uri).resolve().as_posix()}"


class RetrievalPipeline:
    """检索流水线编排器 — 协调查询改写、双路检索、融合和重排序的完整流程。

    依赖注入：vector_index、bm25_index、chunk_store、asset_store。
    Milvus 返回完整标量字段，检索过程中无需查询 PG。
    """

    def __init__(
        self,
        vector_index: VectorIndex,
        bm25_index: BM25Index,
        chunk_store: Any,
        asset_store: AssetStore | None = None,
    ) -> None:
        self._vector_index = vector_index
        self._bm25_index = bm25_index
        self._chunk_store = chunk_store
        self._asset_store = asset_store
        self._rewriter = QueryRewriter()
        self._reranker = Reranker()

    def search(
        self,
        query: str,
        top_k: int | None = None,
        categories: list[str] | None = None,
        knowledge_types: list[str] | None = None,
        doc_ids: list[str] | None = None,
        chunk_statuses: list[str] | None = None,
        debug: bool = False,
        rewrite: bool = True,
        hybrid: bool = True,
        rerank: bool = True,
    ) -> SearchResult | tuple[SearchResult, RetrievalDebugInfo]:
        """执行完整检索流水线。

        参数:
            query: 用户原始查询
            top_k: 最终返回结果数量（默认从配置读取）
            categories: 知识块分类过滤列表，None 不过滤
            knowledge_types: 知识类型过滤列表，None 不过滤
            doc_ids: 文档 ID 过滤列表，None 不过滤
            chunk_statuses: 知识块状态过滤列表，None 默认只查 active
            debug: 为 True 时返回 (SearchResult, RetrievalDebugInfo) 元组
            rewrite: 是否执行查询改写
            hybrid: 是否启用 BM25；为 False 时仅执行向量检索
            rerank: 是否执行 LLM 重排

        返回:
            debug=False 时返回 SearchResult
            debug=True 时返回 (SearchResult, RetrievalDebugInfo)
        """
        cfg = get_settings(reload_env=True)
        final_k = top_k or cfg.final_top_k

        # 初始化调试信息
        debug_info: RetrievalDebugInfo | None = None
        if debug:
            debug_info = RetrievalDebugInfo(original_query=query, rewritten_query=query)
        t_total = time.perf_counter()

        # 1. 查询改写；关闭时保持原查询，确保 API 策略开关真实生效。
        t0 = time.perf_counter()
        if rewrite:
            rewrite_result = self._rewriter.rewrite(query)
        else:
            rewrite_result = {"rewritten_query": query, "keywords": [query]}
        rewritten = rewrite_result.get("rewritten_query") or query
        keywords = rewrite_result.get("keywords") or [query]
        keywords_str = " ".join(keywords)

        if debug and debug_info:
            debug_info.rewritten_query = rewritten
            debug_info.keywords = keywords
            debug_info.timing["rewrite_ms"] = int((time.perf_counter() - t0) * 1000)

        # 2. Embedding
        t0 = time.perf_counter()
        query_vec: list[float] | None = None
        try:
            query_vecs = embedding_client.embed_text([rewritten])
            query_vec = query_vecs[0]
        except Exception as e:
            err_msg = f"Vector embedding failed: {e}"
            logger.exception(err_msg)
            if debug and debug_info:
                debug_info.errors.append(err_msg)
            query_vec = None
        finally:
            if debug and debug_info:
                debug_info.timing["embedding_ms"] = int((time.perf_counter() - t0) * 1000)

        # 3. 并行双路检索（返回 (chunk_id, score, fields) — Milvus 全量标量字段）
        vec_results: list[tuple[str, float, dict]] = []
        bm25_results: list[tuple[str, float, dict]] = []

        def _search_vector():
            if query_vec is None:
                return []
            return self._vector_index.search(
                query_vec,
                top_k=cfg.vector_top_k,
                categories=categories,
                knowledge_types=knowledge_types,
                doc_ids=doc_ids,
                chunk_statuses=chunk_statuses,
            )

        def _search_bm25():
            return self._bm25_index.search(
                keywords_str,
                top_k=cfg.bm25_top_k,
                categories=categories,
                knowledge_types=knowledge_types,
                doc_ids=doc_ids,
                chunk_statuses=chunk_statuses,
            )

        # 临时 2 线程池跑双路检索并行（外层已有 search_executor 隔离并发搜索）
        t0 = time.perf_counter()
        inner_pool = ThreadPoolExecutor(max_workers=2)

        future_vec = inner_pool.submit(_search_vector) if query_vec is not None else None
        future_bm25 = inner_pool.submit(_search_bm25) if hybrid else None

        if future_bm25 is not None:
            try:
                bm25_results = future_bm25.result()
            except Exception as e:
                err_msg = f"BM25 retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)

        if future_vec is not None:
            try:
                vec_results = future_vec.result()
            except Exception as e:
                err_msg = f"Vector retrieval failed: {e}"
                logger.exception(err_msg)
                if debug and debug_info:
                    debug_info.errors.append(err_msg)

        inner_pool.shutdown(wait=True)

        if debug and debug_info:
            debug_info.timing["search_ms"] = int((time.perf_counter() - t0) * 1000)

        # 从 Milvus 返回字段构建 chunk 数据（无需查 PG）
        fields_map: dict[str, dict] = {}
        for cid, score, fields in vec_results + bm25_results:
            fields_map[cid] = fields

        # 记录召回结果（debug 用）
        if debug and debug_info:
            debug_info.vector_candidates = [(c, s) for c, s, _ in vec_results]
            debug_info.bm25_candidates = [(c, s) for c, s, _ in bm25_results]
            debug_info.vector_count = len(vec_results)
            debug_info.bm25_count = len(bm25_results)

        # 4. RRF 融合
        if not vec_results and not bm25_results:
            result = SearchResult(query=query, rewritten_query=rewritten)
            if debug and debug_info:
                debug_info.timing["total_ms"] = int((time.perf_counter() - t_total) * 1000)
                return result, debug_info
            return result

        fused = rrf_fusion(
            [(c, s) for c, s, _ in vec_results],
            [(c, s) for c, s, _ in bm25_results],
            k=cfg.rrf_k,
        )
        sorted_fused = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        top_fused = sorted_fused[: cfg.fusion_top_k]

        if debug and debug_info:
            debug_info.fused_candidates = top_fused
            debug_info.fused_count = len(top_fused)

        if not top_fused:
            result = SearchResult(query=query, rewritten_query=rewritten)
            if debug and debug_info:
                debug_info.timing["total_ms"] = int((time.perf_counter() - t_total) * 1000)
                return result, debug_info
            return result

        # 5. 从 Milvus 字段构建候选（Milvus 已存完整字段，无需查 PG）
        top_chunk_ids = [cid for cid, _ in top_fused]
        candidates: list[KnowledgeChunk] = []
        for cid in top_chunk_ids:
            fields = fields_map.get(cid)
            if not fields:
                continue
            try:
                candidate_type = KnowledgeType(fields.get("knowledge_type", "declarative"))
            except ValueError:
                candidate_type = KnowledgeType.declarative
            candidates.append(
                KnowledgeChunk(
                    chunk_id=cid,
                    title=fields.get("title", ""),
                    content=fields.get("content", ""),
                    knowledge_type=candidate_type,
                    category=fields.get("category", "通用"),
                )
            )

        t0 = time.perf_counter()
        if rerank:
            try:
                reranked = self._reranker.rerank(query, candidates)
            except Exception:
                logger.exception("LLM 重排失败，回退使用 RRF 顺序")
                reranked = [{"chunk_id": chunk.chunk_id} for chunk in candidates]
        else:
            reranked = [{"chunk_id": chunk.chunk_id} for chunk in candidates]

        if debug and debug_info:
            debug_info.timing["rerank_ms"] = int((time.perf_counter() - t0) * 1000)
            debug_info.rerank_results = reranked
            debug_info.rerank_count = len(reranked)

        # Rerank 全部成功才用 LLM 分排序，否则统一回退 RRF 分（避免不同量纲混排）
        all_reranked = (
            rerank
            and len(reranked) == len(candidates)
            and all("relevance_score" in entry for entry in reranked)
        )

        # 6. 构建结果（Milvus 已含完整字段，PG 补全由 API 层 _filter_and_enrich_result 负责）
        items: list[SearchResultItem] = []
        score_map: dict[str, float] = dict(top_fused)
        vec_map = {c: s for c, s, _ in vec_results}
        bm25_map = {c: s for c, s, _ in bm25_results}

        sorted_items = sorted(
            reranked,
            key=lambda r: r.get("relevance_score", score_map.get(r["chunk_id"], 0.0)) if all_reranked
                     else score_map.get(r["chunk_id"], 0.0),
            reverse=True,
        )

        for rank_entry in sorted_items[:final_k]:
            cid = rank_entry["chunk_id"]
            fields = fields_map.get(cid)
            if not fields:
                continue

            try:
                kt = KnowledgeType(fields.get("knowledge_type", "declarative"))
            except ValueError:
                kt = KnowledgeType.declarative

            items.append(
                SearchResultItem(
                    chunk_id=cid,
                    doc_id=fields.get("doc_id", ""),
                    doc_title=fields.get("doc_title", ""),
                    status=fields.get("status", "active"),
                    title=fields.get("title", ""),
                    content=fields.get("content", ""),
                    score=rank_entry.get("relevance_score") if all_reranked else score_map.get(cid, 0.0),
                    category=fields.get("category", "通用"),
                    knowledge_type=kt,
                    score_components=ScoreComponents(
                        vector=vec_map.get(cid, 0.0),
                        bm25=bm25_map.get(cid, 0.0),
                        rrf=score_map.get(cid, 0.0),
                        rerank=rank_entry.get("relevance_score"),
                    ),
                    asset_refs=_parse_json_field(fields.get("asset_refs"), []),
                    source_refs=[
                        SourceRef(
                            doc_id=r.get("doc_id", ""),
                            doc_version=r.get("doc_version", 1),
                            element_id=r.get("element_id", ""),
                            source_location=SourceLocation.model_validate(r.get("source_location") or {}),
                        )
                        if isinstance(r, dict) else r
                        for r in _parse_json_field(fields.get("source_refs"), [])
                    ],
                )
            )

        result = SearchResult(
            query=query,
            rewritten_query=rewritten,
            total_count=len(top_fused),
            results=items,
        )

        if debug and debug_info:
            debug_info.timing["total_ms"] = int((time.perf_counter() - t_total) * 1000)
            return result, debug_info
        return result
