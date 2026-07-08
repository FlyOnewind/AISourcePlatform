"""RRF（倒数排序融合）— 将稠密向量检索与 BM25 关键词检索的排序结果融合为统一分数。

融合公式：score(chunk) = sum(1 / (k + rank))，k 为平滑常数（默认 60）。
分数越高表示越相关。
"""

from app.core.config import get_settings


def rrf_fusion(
    vector_results: list[tuple[str, float]],
    bm25_results: list[tuple[str, float]],
    k: int | None = None,
) -> dict[str, float]:
    """倒数排序融合（Reciprocal Rank Fusion）。

    将向量检索和 BM25 检索两条排序列表按照 RRF 公式合并，
    返回 {chunk_id: fused_score}，分数越高表示越相关。

    参数:
        vector_results: 向量检索的 (chunk_id, score) 列表，已按分数降序
        bm25_results: BM25 检索的 (chunk_id, score) 列表，已按分数降序
        k: RRF 平滑常数，默认从配置读取（settings.rrf_k），一般为 60
    """
    k = k or get_settings(reload_env=True).rrf_k
    scores: dict[str, float] = {}

    for rank, (chunk_id, _) in enumerate(vector_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    for rank, (chunk_id, _) in enumerate(bm25_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    return scores
