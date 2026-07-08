"""评测数据集自动生成模块。

从已入库的知识块出发，使用 LLM 自动生成查询 + chunk_id 标注 + 关键词标注。
仅提供入库流程调用的 API，不暴露 CLI 入口。用户可在入库后直接修改 LLM 生成的评测数据。

工作流程:
    1. 入库完成后，后台线程调用 generate_for_chunks()
    2. 将 chunk 列表分片（每批 ≤80 个），对每批调用 LLM 生成查询
    3. LLM 生成查询 → 标注期望 chunk_id → 提取关键词
    4. _validate_annotations() 校验 chunk_id 合法性和关键词存在性
    5. 返回有效条目列表，供 storage.save_per_doc_dataset() 写入文件
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent / "backend"  # backend/ 目录
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

logger = logging.getLogger(__name__)

LLM_INPUT_CHUNK_LIMIT = 80   # 单次 LLM 调用的 chunk 数量上限
BATCH_QUERY_COUNT = 2        # 每批生成的查询数（分批时降低单批数量以控制总量）

# ── LLM 提示词 ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是知识库检索评测数据构建助手。

你的任务是根据提供的知识块列表生成评测用的查询和标注。

要求：
- 精确生成 {target_count} 条查询，将知识块视为同一篇文档的不同章节
- 查询风格要多样化，模拟真实用户的检索行为，包含以下类型（均匀分布）：
  - 完整疑问句（"怎么配置超时时间？"）
  - 关键词组合（"超时 配置 参数"）
  - 短语/口语片段（"那个异步处理的东西"）
  - 祈使/陈述句（"查一下分片逻辑""给个配置示例"）
- 不要直接复制 chunk 原文中的完整句子，使用同义改写和口语化表述
- 每个 chunk ID 必须是知识块列表中真实存在的 ID
- 输出格式：一个 JSON 对象，包含 items 数组。每个 item 有 query（查询文本）、
  expected_chunk_ids（能回答该查询的 chunk ID 列表，1-3 个）、
  expected_content_contains（从对应 chunk 中摘取的关键词，3-5 个，必须原文中存在）"""

USER_PROMPT_TEMPLATE = """为以下 {chunk_count} 个知识块生成恰好 {target_count} 条评测查询。

知识块：
{chunks_json}

只输出 JSON 对象，不要 Markdown 代码块，不要额外文字。格式示例：
{{"items":[{{"query":"...","expected_chunk_ids":["chunk_xxx"],"expected_content_contains":["关键词1","关键词2"]}}]}}"""

OUTPUT_SCHEMA = {"required": ["items"]}


def _generate(chunks: list[dict], target_count: int) -> list[dict]:
    """调用 LLM 生成评测数据（内部函数）。

    Args:
        chunks: 知识块列表，每个 dict 包含 chunk_id, title, content。
        target_count: 期望生成的查询数量。

    Returns:
        LLM 返回的 items 列表。
    """
    from llm.volcengine_client import llm_client

    if not chunks:
        return []

    chunks_json = json.dumps(chunks, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(target_count=target_count)},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
            chunk_count=len(chunks),
            target_count=target_count,
            chunks_json=chunks_json,
        )},
    ]

    result = llm_client.chat_json(messages, schema=OUTPUT_SCHEMA)
    return result.get("items", [])


def _validate_annotations(
    items: list[dict],
    chunks: list[dict],
) -> tuple[list[dict], list[str]]:
    """校验 LLM 生成的评测数据，过滤无效条目。

    校验规则：
    1. expected_chunk_ids 必须存在于输入的 chunks 中（防止 LLM 编造 ID）
    2. expected_content_contains 中的关键词必须在对应 chunk 正文中存在

    Args:
        items: 待校验的评测条目列表。
        chunks: 知识块列表（用于校验 chunk_id 和关键词）。

    Returns:
        (有效条目列表, 错误信息列表)
    """
    chunk_id_set = {c["chunk_id"] for c in chunks}
    chunk_content_map = {c["chunk_id"]: c.get("content", "") for c in chunks}

    valid_items = []
    errors = []

    for i, item in enumerate(items):
        query = item.get("query", "")
        if not query:
            errors.append(f"条目 {i}: 缺少 query")
            continue

        expected_chunk_ids = item.get("expected_chunk_ids", [])
        expected_keywords = item.get("expected_content_contains", [])

        # 1. 校验 chunk_id 合法性 — 过滤 LLM 编造的无效 ID
        invalid_ids = [cid for cid in expected_chunk_ids if cid not in chunk_id_set]
        if invalid_ids:
            errors.append(f"条目 '{query[:30]}': 无效的 chunk_id {invalid_ids}")
            expected_chunk_ids = [cid for cid in expected_chunk_ids if cid in chunk_id_set]
            item["expected_chunk_ids"] = expected_chunk_ids

        # 2. 校验关键词在 chunk 正文中存在
        if expected_chunk_ids:
            related_content = " ".join(
                chunk_content_map.get(cid, "") for cid in expected_chunk_ids
            )
        else:
            related_content = " ".join(chunk_content_map.values())

        if related_content:
            valid_keywords = [
                kw for kw in expected_keywords
                if kw.lower() in related_content.lower()
            ]
            if len(valid_keywords) != len(expected_keywords):
                invalid_kws = set(expected_keywords) - set(valid_keywords)
                errors.append(f"条目 '{query[:30]}': 关键词不在 chunk 中 - {invalid_kws}")
                item["expected_content_contains"] = valid_keywords

        # 至少有一个维度有标注才认为有效
        if expected_chunk_ids or item.get("expected_content_contains"):
            valid_items.append(item)
        else:
            errors.append(f"条目 '{query[:30]}': 缺少有效标注，已过滤")

    return valid_items, errors


def generate_for_chunks(
    chunks: list[dict],
    doc_id: str,
    doc_title: str,
    query_count: int = 3,
    doc_version: int = 1,
) -> tuple[list[dict], list[str]]:
    """为指定文档的知识块生成评测数据。

    入库流程调用的唯一入口。调用 LLM 生成查询和标注，校验后补充元数据字段。
    超过 LLM_INPUT_CHUNK_LIMIT 的知识块列表自动分片生成（每批最多 80 个 chunk）。

    生成数量自适应：实际生成条数不超过 chunk 总数，避免小文档因知识点不足
    而产生同质化查询（例如 1 个 chunk 只生成 1 条，2 个 chunk 生成 2 条）。

    Args:
        chunks: 知识块列表，每个 dict 包含 chunk_id, title, content。
        doc_id: 文档 ID。
        doc_title: 文档标题。
        query_count: 期望生成的查询数量，默认 3。实际不超过 chunk 数量。
        doc_version: 文档版本号，用于过滤过期标注。默认 1。

    Returns:
        (有效条目列表, 错误信息列表)。每个有效条目包含 query、
        expected_chunk_ids、expected_content_contains、doc_id、doc_version、source 六个字段。
    """
    all_items: list[dict] = []
    all_errors: list[str] = []

    # 实际生成数不超过 chunk 总数，避免小文档查询同质化
    effective_count = max(1, min(query_count, len(chunks))) if chunks else 0

    # 分片：每批 ≤ LLM_INPUT_CHUNK_LIMIT 个 chunk，每批独立生成 query_count 条
    max_total = query_count * 2  # 分片场景总量上限，避免大文档生成过多条目
    if len(chunks) > LLM_INPUT_CHUNK_LIMIT:
        batch_count = (len(chunks) + LLM_INPUT_CHUNK_LIMIT - 1) // LLM_INPUT_CHUNK_LIMIT
        logger.info(
            "知识块总数 %d 超过限制 %d，分 %d 批生成（每批 %d 条，上限 %d 条）",
            len(chunks), LLM_INPUT_CHUNK_LIMIT, batch_count, query_count, max_total,
        )
        for i in range(0, len(chunks), LLM_INPUT_CHUNK_LIMIT):
            if len(all_items) >= max_total:
                break
            batch = chunks[i : i + LLM_INPUT_CHUNK_LIMIT]
            # 每批的生成数也不超过该批 chunk 数
            batch_target = max(1, min(query_count, len(batch)))
            items = _generate(batch, target_count=batch_target)
            if items:
                valid_items, errors = _validate_annotations(items, chunks)
                all_items.extend(valid_items)
                all_errors.extend(errors)
    else:
        items = _generate(chunks, target_count=effective_count)
        if items:
            all_items, all_errors = _validate_annotations(items, chunks)

    # 截断到上限
    if len(all_items) > max_total:
        all_items = all_items[:max_total]

    if not all_items and not all_errors:
        all_errors.append("LLM 未生成任何条目")

    # 补充元数据（doc_id + doc_version + source）
    for item in all_items:
        item["doc_id"] = doc_id
        item["doc_version"] = doc_version
        item["source"] = "auto"

    return all_items, all_errors
