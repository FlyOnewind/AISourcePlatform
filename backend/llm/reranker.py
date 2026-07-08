"""LLM 重排序模块 — 对候选知识块批量打分后按相关性降序排列。

采用一次性批量打分策略：将所有候选打包进一个 prompt，LLM 在一次调用中
返回所有候选的评分，代码层负责排序。单次 LLM 调用替代 N 次独立调用，
将重排耗时从 O(N×单次LLM) 降至 O(1次LLM)，消除并发 API 调用带来的限流和开销。
"""

import logging
from typing import Any

from app.core.config import settings
from app.core.models import KnowledgeChunk
from llm.prompts import (
    RERANK_BATCH_SCHEMA,
    RERANK_SCHEMA,
    build_rerank_batch_message,
    build_rerank_message,
)
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)

def _score_batch(
    query: str, chunks: list[KnowledgeChunk]
) -> list[dict[str, Any]]:
    """一次 LLM 调用为所有候选批量打分。

    将所有候选内容打包为一个 prompt，LLM 一次性返回所有评分。
    任一条目评分失败（LLM 未返回该 chunk_id）时，该条目不设 relevance_score，
    由 pipeline 层从 RRF 融合分数回退。
    """
    candidates = [
        {"chunk_id": c.chunk_id, "content": c.content} for c in chunks
    ]
    try:
        messages = build_rerank_batch_message(query, candidates)
        result = llm_client.chat_json(
            messages, schema=RERANK_BATCH_SCHEMA, model=settings.llm_fast_model,
            max_tokens=4096,
        )
        scores = result.get("scores", [])
    except Exception:
        logger.exception("批量重排打分失败，所有候选回退使用 RRF 分数")
        return [
            {"chunk_id": c.chunk_id, "reason": "批量 LLM 调用失败，使用 RRF 融合分数"}
            for c in chunks
        ]

    # 构建 chunk_id → score 映射
    score_map: dict[str, dict[str, Any]] = {}
    for entry in scores:
        cid = entry.get("chunk_id", "")
        if not cid:
            continue
        try:
            score = float(entry.get("relevance_score", 0.0))
            score_map[cid] = {
                "chunk_id": cid,
                "relevance_score": max(0.0, min(1.0, score)),
                "reason": entry.get("reason", ""),
            }
        except (ValueError, TypeError):
            score_map[cid] = {
                "chunk_id": cid,
                "reason": f"LLM 返回无效分值: {entry.get('relevance_score')}",
            }

    # 确保每个候选都有结果（LLM 遗漏的回退）
    ranked = []
    for c in chunks:
        if c.chunk_id in score_map:
            ranked.append(score_map[c.chunk_id])
        else:
            ranked.append({
                "chunk_id": c.chunk_id,
                "reason": "LLM 未返回该条目评分，使用 RRF 融合分数",
            })
    return ranked


def _score_one(query: str, chunk: KnowledgeChunk) -> dict[str, Any]:
    """对单条知识块调用 LLM 进行相关性打分（仅候选数=1 时使用）。"""
    try:
        messages = build_rerank_message(query, chunk.content)
        result = llm_client.chat_json(
            messages, schema=RERANK_SCHEMA, model=settings.llm_fast_model,
            max_tokens=1024,
        )
        score = float(result.get("relevance_score", 0.0))
        return {
            "chunk_id": chunk.chunk_id,
            "relevance_score": max(0.0, min(1.0, score)),
            "reason": result.get("reason", ""),
        }
    except Exception:
        logger.warning("单条重排打分失败 chunk=%s", chunk.chunk_id, exc_info=True)
        return {
            "chunk_id": chunk.chunk_id,
            "reason": "LLM 调用失败，使用 RRF 融合分数",
        }


class Reranker:
    """LLM 重排序器 — 批量打包候选一次打分，代码层负责降序排列。

    策略：
    - 候选数 = 0：直接返回空列表
    - 候选数 = 1：单条 prompt 调用（沿用旧 prompt，输出更简洁）
    - 候选数 ≥ 2：批量 prompt 调用，一次 LLM 请求返回所有评分
    """

    def rerank(
        self, query: str, candidates: list[KnowledgeChunk]
    ) -> list[dict[str, Any]]:
        """对候选批量调用 LLM 打分，降序排列。

        返回按相关性降序排列的打分条目。
        """
        if not candidates:
            return []

        if len(candidates) == 1:
            ranked = [_score_one(query, candidates[0])]
        else:
            ranked = _score_batch(query, candidates)

        # 代码负责排序 — LLM 只管打分
        ranked.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return ranked
