"""查询改写模块 — 将用户口语化查询改写为适合检索的陈述句和关键词列表。

通过 LLM 将问句转为陈述句描述、提取核心关键词、判断查询意图，
输出 rewritten_query（用于向量检索）和 keywords（用于 BM25 检索）。
"""

import logging

from app.core.config import settings
from app.core.errors import LLMError
from llm.prompts import QUERY_REWRITE_SCHEMA, build_rewrite_messages
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)


class QueryRewriter:
    """查询改写器 — 通过 LLM 将用户查询改写为更适合检索的形式。"""

    def rewrite(self, query: str) -> dict:
        """改写用户查询。

        返回字典包含:
        - rewritten_query: 改写后的陈述句（用于向量检索）
        - keywords: 核心关键词列表（用于 BM25 检索）
        - intent: 查询意图分类（fact_lookup / how_to / definition / comparison / policy）

        LLM 调用失败时回退为原始查询。
        """
        try:
            messages = build_rewrite_messages(query)
            result = llm_client.chat_json(
                messages, schema=QUERY_REWRITE_SCHEMA, model=settings.llm_fast_model,
                max_tokens=1024,
            )
            return {
                "rewritten_query": result.get("rewritten_query", query),
                "keywords": result.get("keywords", []),
                "intent": result.get("intent", ""),
            }
        except LLMError:
            logger.exception("Query rewrite failed, falling back to original")
            return {
                "rewritten_query": query,
                "keywords": [query],
                "intent": "",
            }
