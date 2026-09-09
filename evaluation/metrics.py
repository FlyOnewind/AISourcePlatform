"""检索质量评测指标计算。

提供四个标准指标：Hit@K、Recall@K、Precision@K、MRR，以及安全的均值汇总函数。
"""


def precision_at_k(
    results: list[str],
    expected: list[str],
    k: int = 5,
) -> float | None:
    """计算标准 Precision@K：top-K 中命中的期望 chunk 数占 K 的比例。

    例如：top-5 命中 2 个 → Precision@5 = 2/5 = 0.4。

    Args:
        results: 检索返回的 chunk_id 列表，按分数降序排列。
        expected: 期望命中的 chunk_id 列表。
        k: 截断位置，默认 5。

    Returns:
        Precision@K 分数 (float)；
        如果 expected 为空则返回 None（无标注，不计入汇总）。
    """
    if not expected:
        return None
    top_k = set(results[:k])
    hits = len(top_k & set(expected))
    return hits / k


def recall_at_k(
    results: list[str],
    expected: list[str],
    k: int = 5,
) -> float | None:
    """计算标准 Recall@K：top-K 中命中的期望 chunk 数占期望总数的比例。

    例如：期望 3 个 chunk，top-5 命中 2 个 → Recall@5 = 2/3 ≈ 0.667。

    Args:
        results: 检索返回的 chunk_id 列表，按分数降序排列。
        expected: 期望命中的 chunk_id 列表。
        k: 截断位置，默认 5。

    Returns:
        Recall@K 分数 (float)，命中数/期望总数；
        如果 expected 为空则返回 None（无标注，不计入汇总）。
    """
    if not expected:
        return None
    top_k = set(results[:k])
    hits = len(top_k & set(expected))
    return hits / len(expected)


def mrr(
    results: list[str],
    expected: list[str],
) -> float | None:
    """计算 Mean Reciprocal Rank（单条查询版本）。

    取第一个命中 chunk 的排名倒数。排第 1 → 1.0，排第 3 → 0.333，未命中 → 0.0。

    Args:
        results: 检索返回的 chunk_id 列表，按分数降序排列。
        expected: 期望命中的 chunk_id 列表。

    Returns:
        倒数排名 (float)；
        如果 expected 为空则返回 None（无标注，不计入汇总）。
    """
    if not expected:
        return None
    expected_set = set(expected)
    for rank, chunk_id in enumerate(results, 1):
        if chunk_id in expected_set:
            return 1.0 / rank
    return 0.0


def hit_at_k(
    results: list[str],
    expected: list[str],
    k: int = 5,
) -> float | None:
    """计算 Hit@K：top-K 中是否至少命中一个期望 chunk。

    命中返回 1.0，未命中返回 0.0。批量使用时取均值即命中率。

    Args:
        results: 检索返回的 chunk_id 列表，按分数降序排列。
        expected: 期望命中的 chunk_id 列表。
        k: 截断位置，默认 5。

    Returns:
        1.0 或 0.0；
        如果 expected 为空则返回 None（无标注，不计入汇总）。
    """
    if not expected:
        return None
    top_k = set(results[:k])
    return 1.0 if (top_k & set(expected)) else 0.0


def safe_mean(values: list[float | None]) -> float | None:
    """计算非 None 值的算术平均。全为 None 时返回 None。

    Args:
        values: 可能包含 None 的浮点数列表。

    Returns:
        平均值；全为 None 时返回 None。
    """
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)
