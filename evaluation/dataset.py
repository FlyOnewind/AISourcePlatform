"""评测数据模型 — 定义 EvalItem 数据类和数据集加载/保存逻辑。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalItem:
    """单条评测查询记录。

    每条记录包含用户查询文本和两个维度的期望标注：
    - expected_chunk_ids: 期望命中的知识块 ID 列表（用于计算 Recall@K 和 MRR）
    - expected_content_contains: 答案应包含的关键词（仅供人工参考，不参与指标计算）
    """

    query: str
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_content_contains: list[str] = field(default_factory=list)

    # ── 元数据字段（用于溯源和保护人工标注） ──
    doc_id: str | None = None       # 来源文档 ID
    doc_version: int = 1            # 来源文档版本号（重入库后递增，旧版本标注自动失效）
    source: str = "auto"            # auto（自动生成）或 manual（人工标注）

    @classmethod
    def from_dict(cls, data: dict) -> "EvalItem":
        """从字典创建 EvalItem，缺失字段使用默认值。

        Args:
            data: 字典格式的评测数据，来自 JSON 反序列化。

        Returns:
            EvalItem 实例。
        """
        return cls(
            query=data["query"],
            expected_chunk_ids=data.get("expected_chunk_ids", []),
            expected_content_contains=data.get("expected_content_contains", []),
            doc_id=data.get("doc_id") or data.get("source_doc_id"),
            doc_version=data.get("doc_version", 1),
            source=data.get("source", "auto"),
        )


def load_dataset(path: Path | str | None = None) -> list[EvalItem]:
    """从 JSON 文件加载评测数据集。

    Args:
        path: 评测数据集文件路径。默认取 tests/evaluation/eval_dataset.json。

    Returns:
        EvalItem 列表，每条完整有效。

    Raises:
        FileNotFoundError: 数据集文件不存在时。
        ValueError: 记录缺少必填字段 query 时跳过并报告。
    """
    if path is None:
        path = Path(__file__).parent / "eval_dataset.json"

    if not Path(path).exists():
        raise FileNotFoundError(f"评测数据集文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    items: list[EvalItem] = []
    for i, record in enumerate(raw):
        query = record.get("query")
        if not query:
            # 跳过缺少必填字段的记录
            import logging
            logging.getLogger(__name__).warning("记录 %d 缺少必填字段 query，已跳过", i)
            continue

        expected_chunk_ids = record.get("expected_chunk_ids", [])
        expected_content_contains = record.get("expected_content_contains", [])

        if not expected_chunk_ids and not expected_content_contains:
            import logging
            logging.getLogger(__name__).warning(
                "记录 %d ('%s') 缺少有效标注，已跳过", i, query[:50]
            )
            continue

        items.append(EvalItem.from_dict(record))

    return items


def save_dataset(items: list[EvalItem], path: Path | str | None = None) -> Path:
    """将评测数据集保存为 JSON 文件（覆盖写入）。

    Args:
        items: EvalItem 列表。
        path: 输出文件路径。默认写入 eval_dataset.json。

    Returns:
        写入的文件路径。
    """
    if path is None:
        path = Path(__file__).parent / "eval_dataset.json"

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = [
        {
            "query": item.query,
            "expected_chunk_ids": item.expected_chunk_ids,
            "expected_content_contains": item.expected_content_contains,
            "doc_id": item.doc_id,
            "doc_version": item.doc_version,
            "source": item.source,
        }
        for item in items
    ]

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path
