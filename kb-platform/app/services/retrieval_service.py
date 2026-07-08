"""知识检索服务：向量召回 + 关键词打分融合，权限过滤，对应文档04第6/7/10节。"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import KnowledgeBase, KnowledgeChunk
from app.services.llm.base import LLMProvider


@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float
    doc_id: str
    doc_name: str
    version: str


def _keyword_score(query: str, keywords: list[str], content: str) -> float:
    query_tokens = set(query.lower().split())
    if not query_tokens:
        return 0.0
    hits = sum(1 for kw in keywords if kw in query.lower())
    content_hits = sum(1 for tok in query_tokens if tok and tok in content.lower())
    return min(1.0, 0.15 * hits + 0.05 * content_hits)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return max(0.0, min(1.0, dot))  # 向量已归一化，dot 即余弦相似度


class RetrievalService:
    """当前实现直接在应用层对 chunk 做暴力向量比对（未使用 Qdrant 索引写入路径时的兜底），
    knowledge_service 会把 embedding 写入 Qdrant；此处优先尝试 Qdrant，失败则退化为
    从 Postgres 加载全部 chunk 内存计算，保证即使 Qdrant 未就绪也能跑通演示。"""

    def __init__(self, db: AsyncSession, llm) -> None:  # noqa: ANN001
        self._db = db
        self._llm: LLMProvider = llm

    async def search(
        self,
        query: str,
        kb_ids: list[str] | None,
        top_k: int,
        max_security_level: str | None = None,
    ) -> list[RetrievedChunk]:
        from app.core.vector_store import get_vector_store

        stmt = select(KnowledgeChunk).join(KnowledgeBase, KnowledgeChunk.kb_id == KnowledgeBase.id)
        stmt = stmt.where(KnowledgeBase.status == "published").options(selectinload(KnowledgeChunk.document))
        if kb_ids:
            stmt = stmt.where(KnowledgeChunk.kb_id.in_(kb_ids))
        result = await self._db.execute(stmt)
        chunks = list(result.scalars().all())

        security_order = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
        if max_security_level is not None:
            allowed_level = security_order.get(max_security_level, 1)
            chunks = [c for c in chunks if security_order.get(c.security_level, 1) <= allowed_level]

        if not chunks:
            return []

        query_vec = (await self._llm.embed([query]))[0]

        # 尝试用 Qdrant 做真正的向量检索（按 kb 分 collection），失败则回退内存计算
        vector_scores: dict[str, float] = {}
        try:
            store = get_vector_store()
            kb_key_map = {str(c.kb_id): c for c in chunks}
            for kb_id in {str(c.kb_id) for c in chunks}:
                hits = store.search(kb_key=kb_id, vector=query_vec, top_k=top_k * 3)
                for h in hits:
                    vector_scores[str(h["id"])] = h["score"]
        except Exception:  # noqa: BLE001
            vector_scores = {}

        scored: list[tuple[float, RetrievedChunk]] = []
        chunk_contents = [c.content for c in chunks]
        need_local_embed = not vector_scores
        local_vectors = await self._llm.embed(chunk_contents) if need_local_embed else []

        for i, chunk in enumerate(chunks):
            if str(chunk.id) in vector_scores:
                vec_score = vector_scores[str(chunk.id)]
            elif need_local_embed:
                vec_score = _cosine(query_vec, local_vectors[i])
            else:
                vec_score = 0.0
            kw_score = _keyword_score(query, chunk.keywords or [], chunk.content)
            final_score = 0.75 * vec_score + 0.25 * kw_score
            scored.append(
                (
                    final_score,
                    RetrievedChunk(
                        chunk_id=str(chunk.id),
                        content=chunk.content,
                        score=round(final_score, 4),
                        doc_id=str(chunk.doc_id),
                        doc_name=chunk.document.title if chunk.document else "",
                        version=chunk.version,
                    ),
                )
            )

        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top_k]]
