"""评测触发脚本。

加载全局评测数据集，逐条查询并计算 Recall@K 和 MRR，
最后将结果追加写入 results/history.jsonl。

使用方式：
    cd backend
    python tests/evaluation/run_eval.py
    python tests/evaluation/run_eval.py --no-rewrite --no-rerank --top-k 10
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from evaluation.dataset import load_dataset
from evaluation.metrics import hit_at_k, mrr, precision_at_k, recall_at_k, safe_mean
from evaluation.storage import append_eval_result
from evaluation.dataset import EvalItem


def _run(rewrite: bool = True, rerank: bool = True, top_k: int = 5) -> int:
    """执行评测主流程。

    Args:
        rewrite: 是否启用查询改写。
        rerank: 是否启用 LLM 重排序。
        top_k: 检索返回数量，也是 Recall@K 的 K 值。
    """
    # ── 1. 加载全局评测数据集 ──
    try:
        dataset = load_dataset()
    except FileNotFoundError:
        print("❌ 全局评测数据集 eval_dataset.json 不存在。")
        print("   请先入库文档（自动生成评测数据），然后用 merge_to_global.py 合并到全局。")
        return 1

    if not dataset:
        print("⚠️  评测数据集为空，请先添加评测数据。")
        return 1

    # ── 2. 过滤过期标注（剔除已不存在的 chunk_id，不拖累 Recall 分母）──
    from app.core.deps import chunk_store

    all_expected_ids = set()
    for item in dataset:
        all_expected_ids.update(item.expected_chunk_ids)

    existing_ids: set[str] = set()
    if all_expected_ids and hasattr(chunk_store, "get_batch"):
        existing_chunks = chunk_store.get_batch(list(all_expected_ids))
        existing_ids = {c.chunk_id for c in existing_chunks}

    stale_count = 0
    filtered_count = 0
    active_dataset: list[EvalItem] = []
    for item in dataset:
        expected_ids = item.expected_chunk_ids
        if expected_ids and not any(cid in existing_ids for cid in expected_ids):
            stale_count += 1
            continue
        # 剔除已不存在的 chunk_id，让 Recall 分母反映真实可达上限
        if expected_ids:
            original_count = len(expected_ids)
            item.expected_chunk_ids = [cid for cid in expected_ids if cid in existing_ids]
            if len(item.expected_chunk_ids) < original_count:
                filtered_count += 1
        active_dataset.append(item)

    if stale_count:
        print(f"🗑️  丢弃 {stale_count} 条过期标注（chunk 全部已被删除）")
    if filtered_count:
        print(f"🧹  清理 {filtered_count} 条标注中的已删除 chunk（共 {len(active_dataset)} 条有效）")

    if not active_dataset:
        print("⚠️  过滤后无有效评测条目，请先入库文档生成新的评测数据。")
        return 1

    # ── 3. 确认检索索引可用（直接复用现有索引，不重建）──
    from app.core.deps import retrieval_pipeline

    active_chunk_count = len(existing_ids)
    if active_chunk_count == 0:
        print("⚠️  检索索引中无知识块，请先完成文档入库。")
        return 1

    # ── 4. 并发查询 ──
    total = len(active_dataset)

    print(f"\n🔍 复用现有检索索引: {active_chunk_count} 个活跃 chunk")
    print(f"📊 评测中，共 {total} 条查询（已过滤 {stale_count} 条过期）...\n")

    start_time = time.time()

    # 并发提交所有检索，按序收集结果
    chunk_ids_map: dict[int, list[str]] = {}
    error_map: dict[int, str] = {}

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                retrieval_pipeline.search,
                item.query,
                top_k,
                rewrite=rewrite,
                rerank=rerank,
            ): i
            for i, item in enumerate(active_dataset)
        }
        completed = 0
        for future in as_completed(futures):
            i = futures[future]
            completed += 1
            try:
                result = future.result(timeout=30)
                chunk_ids_map[i] = [r.chunk_id for r in result.results]
            except Exception as exc:
                error_map[i] = str(exc)
            # 每 10 条输出一次进度
            if completed % 10 == 0 or completed == total:
                print(f"  [{completed}/{total}] 检索完成...")

    # ── 5. 按原始顺序计算指标 ──
    recall_scores: list[float | None] = []
    precision_scores: list[float | None] = []
    hit_scores: list[float | None] = []
    mrr_scores: list[float | None] = []
    failure_count = 0

    for i, item in enumerate(active_dataset):
        if i in error_map:
            print(f"  [{i+1}/{total}] 检索异常: {item.query[:40]}... ({error_map[i]})")
            failure_count += 1
            recall_scores.append(None)
            precision_scores.append(None)
            hit_scores.append(None)
            mrr_scores.append(None)
            continue

        chunk_ids = chunk_ids_map[i]
        r5 = recall_at_k(chunk_ids, item.expected_chunk_ids, k=top_k)
        p5 = precision_at_k(chunk_ids, item.expected_chunk_ids, k=top_k)
        h5 = hit_at_k(chunk_ids, item.expected_chunk_ids, k=top_k)
        m = mrr(chunk_ids, item.expected_chunk_ids)
        recall_scores.append(r5)
        precision_scores.append(p5)
        hit_scores.append(h5)
        mrr_scores.append(m)

        # 每 10 条输出一次进度
        if (i + 1) % 10 == 0 or (i + 1) == total:
            print(f"  [{i+1}/{total}] 已完成...")

    elapsed = time.time() - start_time

    # ── 6. 汇总指标 ──
    avg_recall = safe_mean(recall_scores)
    avg_precision = safe_mean(precision_scores)
    avg_hit = safe_mean(hit_scores)
    avg_mrr = safe_mean(mrr_scores)
    success_count = len(active_dataset) - failure_count

    # ── 7. 控制台输出 ──
    print()
    print("=" * 50)
    print("📊 评测完成")
    print("=" * 50)
    print(f"  查询总数:       {len(active_dataset)}（成功 {success_count} / 失败 {failure_count}）")
    print(f"  已过滤过期:      {stale_count} 条")
    print(f"  耗时:           {elapsed:.1f}s")
    print(f"  Hit@{top_k}:          {avg_hit:.4f}" if avg_hit is not None else f"  Hit@{top_k}:          N/A")
    print(f"  Recall@{top_k}:       {avg_recall:.4f}" if avg_recall is not None else f"  Recall@{top_k}:       N/A")
    print(f"  Precision@{top_k}:    {avg_precision:.4f}" if avg_precision is not None else f"  Precision@{top_k}:    N/A")
    print(f"  MRR:            {avg_mrr:.4f}" if avg_mrr is not None else "  MRR:            N/A")
    print()

    # ── 8. 追加评测历史 ──
    from app.core.config import get_settings
    cfg = get_settings(reload_env=True)

    search_params = {
        "rewrite": rewrite,
        "rerank": rerank,
        "top_k": top_k,
        "vector_top_k": cfg.vector_top_k,
        "bm25_top_k": cfg.bm25_top_k,
        "rrf_top_k": cfg.fusion_top_k,
    }

    metrics = {
        f"hit_at_{top_k}": avg_hit,
        f"recall_at_{top_k}": avg_recall,
        # f"precision_at_{top_k}": avg_precision,
        "mrr": avg_mrr,
    }

    history_path = append_eval_result(
        search_params=search_params,
        metrics=metrics,
        query_count=len(active_dataset),
        success_count=success_count,
        failure_count=failure_count,
    )
    print(f"📄 结果已追加: {history_path}")

    return 0


if __name__ == "__main__":
    args = sys.argv[1:]

    # 帮助信息
    if "--help" in args or "-h" in args:
        print(__doc__)
        print("选项:")
        print("  --no-rewrite    关闭查询改写（默认开启）")
        print("  --no-rerank     关闭 LLM 重排序（默认开启）")
        print("  --top-k N       检索返回数量及 Recall@K 的 K 值（默认 5）")
        print("  --help, -h      显示此帮助信息")
        raise SystemExit(0)

    rewrite = "--no-rewrite" not in args
    rerank = "--no-rerank" not in args
    top_k = 5
    for i, arg in enumerate(args):
        if arg == "--top-k" and i + 1 < len(args):
            try:
                top_k = int(args[i + 1])
            except ValueError:
                print(f"❌ --top-k 参数值无效: {args[i + 1]}，必须为整数")
                raise SystemExit(2)
    raise SystemExit(_run(rewrite=rewrite, rerank=rerank, top_k=top_k))