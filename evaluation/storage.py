"""评测数据与结果存储封装。

提供：
- 分文档评测数据集保存到 datasets/unmerged/ 目录（未合并）
- 合并后将源文件移动到 datasets/merged/ 目录（已合并）
- 评测结果以 JSONL 格式追加写入 results/history.jsonl
- 存储目录初始化
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
UNMERGED_DIR = EVAL_DIR / "datasets" / "unmerged"
MERGED_DIR = EVAL_DIR / "datasets" / "merged"
RESULTS_DIR = EVAL_DIR / "results"


def init_storage() -> None:
    """初始化存储目录结构 — 确保 datasets/unmerged/、datasets/merged/ 和 results/ 存在。"""
    UNMERGED_DIR.mkdir(parents=True, exist_ok=True)
    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)


def save_per_doc_dataset(
    doc_id: str,
    doc_title: str,
    items: list[dict[str, Any]],
    chunk_count: int,
    doc_version: int = 1,
) -> Path:
    """保存单个文档的评测数据到 datasets/unmerged/ 目录。

    同 doc_id 的旧文件在写入前自动清理（文档重入库后旧标注失效）。

    文件命名：doc_{doc_id前12位}_{日期}.json
    写入内容：{ metadata: {...}, items: [...] }

    Args:
        doc_id: 文档 ID。
        doc_title: 文档标题。
        items: 评测条目列表，每个 dict 包含 query、expected_chunk_ids、
               expected_content_contains、doc_id、doc_version、source 字段。
        chunk_count: 该文档包含的知识块数量。
        doc_version: 文档版本号。默认 1。

    Returns:
        保存的文件路径。
    """
    init_storage()

    # 清理同 doc_id 的旧数据集文件（重入库后旧标注失效）
    for old_file in UNMERGED_DIR.glob(f"{doc_id}*.json"):
        old_file.unlink()

    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"{doc_id}_{timestamp}.json"
    path = UNMERGED_DIR / filename

    data = {
        "metadata": {
            "doc_id": doc_id,
            "doc_title": doc_title,
            "doc_version": doc_version,
            "generated_at": datetime.now().isoformat(),
            "generated_by": "auto-ingest",
            "chunk_count": chunk_count,
            "query_count": len(items),
        },
        "items": items,
    }

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def append_eval_result(
    search_params: dict[str, Any],
    metrics: dict[str, float | None],
    query_count: int,
    success_count: int = 0,
    failure_count: int = 0,
) -> Path:
    """将本次评测结果以一行 JSON 追加写入 results/history.jsonl。

    每条记录包含时间戳、检索参数、评测指标、查询总数及成功/失败计数。

    Args:
        search_params: 检索参数字典，包含 rewrite、vector_top_k、bm25_top_k、
                       rrf_k、rerank、top_k 等字段。
        metrics: 评测指标字典，包含 recall_at_5 和 mrr。
        query_count: 参与评测的查询总数。
        success_count: 成功查询数。
        failure_count: 失败查询数。

    Returns:
        history.jsonl 的文件路径。
    """
    init_storage()

    record = {
        "timestamp": datetime.now().isoformat(),
        "search_params": search_params,
        "metrics": metrics,
        "query_count": query_count,
        "success_count": success_count,
        "failure_count": failure_count,
    }

    history_path = RESULTS_DIR / "history.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return history_path
