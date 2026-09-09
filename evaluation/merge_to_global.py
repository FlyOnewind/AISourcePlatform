"""手动合并脚本 — 将文档级评测数据合并到全局数据集中。

使用方式：
    cd backend

    # 合并单个文档
    python tests/evaluation/merge_to_global.py <doc_id>

    # 合并全部未合并的文档
    python tests/evaluation/merge_to_global.py --all

行为：
    - 在 datasets/unmerged/ 目录下查找文件名前缀匹配的 JSON 文件
    - 读取其中的 items 数组，按 (doc_id, query) 去重
    - 追加到 eval_dataset.json，已存在（source 为 "manual"）的条目不被覆盖
    - 合并完成后将源文件移动到 datasets/merged/ 目录
    - 输出合并结果摘要
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from evaluation.dataset import load_dataset, save_dataset
from evaluation.storage import UNMERGED_DIR, MERGED_DIR, init_storage


def merge_doc_to_global(doc_id: str) -> tuple[int, int, int]:
    """将指定文档的评测数据合并到全局数据集。

    Args:
        doc_id: 文档 ID（完整或前缀均可，用于匹配文件名）。

    Returns:
        (新增数, 更新数, 跳过数) 三元组。
    """
    init_storage()

    # ── 1. 查找匹配的未合并数据集 ──
    matching_files = sorted(UNMERGED_DIR.glob(f"{doc_id}*.json"))
    if not matching_files:
        print(f"❌ 未在 {UNMERGED_DIR} 中找到文档 {doc_id} 的评测数据文件")
        print(f"   搜索模式: {doc_id}*.json")
        return (0, 0, 0)

    print(f"📂 在 unmerged/ 中找到 {len(matching_files)} 个匹配文件:")
    for f in matching_files:
        print(f"   - {f.name}")

    # ── 2. 收集所有待合并的条目 ──
    new_items: list[dict] = []
    for file_path in matching_files:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        new_items.extend(items)
        print(f"   读取 {file_path.name}: {len(items)} 条")

    if not new_items:
        print("⚠️  没有可合并的条目。")
        return (0, 0, 0)

    # ── 3. 加载全局数据集，构建已存在 query 的集合 ──
    global_path = Path(__file__).parent / "eval_dataset.json"
    existing_items: list[dict] = []
    if global_path.exists():
        with open(global_path, encoding="utf-8") as f:
            existing_items = json.load(f)

    # 构建已有 (doc_id, query) → index 的映射（跨文档不同 query 不冲突）
    existing_keys: dict[tuple[str, str], int] = {}
    for idx, item in enumerate(existing_items):
        q = item.get("query", "")
        d = item.get("doc_id", "")
        if q:
            existing_keys[(d, q)] = idx

    # ── 4. 按 (doc_id, query) 去重合并 ──
    added = 0
    skipped = 0
    updated = 0
    for item in new_items:
        q = item.get("query", "")
        d = item.get("doc_id", "")
        if not q:
            continue

        key = (d, q)
        if key in existing_keys:
            existing_idx = existing_keys[key]
            existing = existing_items[existing_idx]

            # 人工标注永远不覆盖
            if existing.get("source") == "manual":
                skipped += 1
                continue

            # 自动标注直接用新标注替换，过期 chunk 由 run_eval 过滤
            existing_items[existing_idx] = {
                "query": q,
                "expected_chunk_ids": item.get("expected_chunk_ids", []),
                "expected_content_contains": item.get("expected_content_contains", []),
                "doc_id": item.get("doc_id"),
                "doc_version": item.get("doc_version", 1),
                "source": item.get("source", "auto"),
            }
            updated += 1
            continue

        # 新条目 → 添加到全局数据集
        existing_items.append({
            "query": q,
            "expected_chunk_ids": item.get("expected_chunk_ids", []),
            "expected_content_contains": item.get("expected_content_contains", []),
            "doc_id": item.get("doc_id"),
            "doc_version": item.get("doc_version", 1),
            "source": item.get("source", "auto"),
        })
        existing_keys[key] = len(existing_items) - 1
        added += 1

    # ── 5. 写回全局数据集 ──
    global_path.write_text(
        json.dumps(existing_items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\n📊 合并完成:")
    print(f"   新增: {added} 条")
    print(f"   更新: {updated} 条")
    print(f"   跳过: {skipped} 条（人工标注保护）")
    print(f"   全局数据集总计: {len(existing_items)} 条")
    print(f"   📄 {global_path}")

    # ── 6. 将已合并的源文件移动到 merged/ 目录 ──
    for file_path in matching_files:
        target = MERGED_DIR / file_path.name
        file_path.rename(target)
        print(f"   📦 {file_path.name} → merged/")

    return (added, updated, skipped)


def merge_all() -> dict[str, int]:
    """合并所有未合并的文档评测数据到全局数据集。

    遍历 datasets/unmerged/ 下全部 doc_*.json 文件，
    一次性收集所有条目后执行去重合并，完成后将源文件移动到 datasets/merged/。

    Returns:
        汇总统计字典，包含 total_added、total_updated、total_skipped、total_files。
    """
    init_storage()

    all_files = sorted(UNMERGED_DIR.glob("doc_*.json"))
    if not all_files:
        print("📂 datasets/unmerged/ 中没有待合并的文件。")
        return {"total_added": 0, "total_updated": 0, "total_skipped": 0, "total_files": 0}

    print(f"📂 发现 {len(all_files)} 个未合并文件\n")

    # ── 1. 收集所有待合并的条目 ──
    new_items: list[dict] = []
    for file_path in all_files:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        new_items.extend(items)
        print(f"   读取 {file_path.name}: {len(items)} 条")

    if not new_items:
        print("⚠️  没有可合并的条目。")
        return {"total_added": 0, "total_updated": 0, "total_skipped": 0, "total_files": len(all_files)}

    # ── 2. 加载全局数据集，构建已存在 (doc_id, query) 的映射 ──
    global_path = Path(__file__).parent / "eval_dataset.json"
    existing_items: list[dict] = []
    if global_path.exists():
        with open(global_path, encoding="utf-8") as f:
            existing_items = json.load(f)

    existing_keys: dict[tuple[str, str], int] = {}
    for idx, item in enumerate(existing_items):
        q = item.get("query", "")
        d = item.get("doc_id", "")
        if q:
            existing_keys[(d, q)] = idx

    # ── 3. 按 (doc_id, query) 去重合并 ──
    total_added = 0
    total_skipped = 0
    total_updated = 0
    for item in new_items:
        q = item.get("query", "")
        d = item.get("doc_id", "")
        if not q:
            continue

        key = (d, q)
        if key in existing_keys:
            existing_idx = existing_keys[key]
            existing = existing_items[existing_idx]

            if existing.get("source") == "manual":
                total_skipped += 1
                continue

            existing_items[existing_idx] = {
                "query": q,
                "expected_chunk_ids": item.get("expected_chunk_ids", []),
                "expected_content_contains": item.get("expected_content_contains", []),
                "doc_id": item.get("doc_id"),
                "doc_version": item.get("doc_version", 1),
                "source": item.get("source", "auto"),
            }
            total_updated += 1
            continue

        existing_items.append({
            "query": q,
            "expected_chunk_ids": item.get("expected_chunk_ids", []),
            "expected_content_contains": item.get("expected_content_contains", []),
            "doc_id": item.get("doc_id"),
            "doc_version": item.get("doc_version", 1),
            "source": item.get("source", "auto"),
        })
        existing_keys[key] = len(existing_items) - 1
        total_added += 1

    # ── 4. 写回全局数据集 ──
    global_path.write_text(
        json.dumps(existing_items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # ── 5. 将已合并的源文件移动到 merged/ 目录 ──
    for file_path in all_files:
        target = MERGED_DIR / file_path.name
        file_path.rename(target)

    print(f"\n📊 合并完成:")
    print(f"   处理文件: {len(all_files)} 个")
    print(f"   新增: {total_added} 条")
    print(f"   更新: {total_updated} 条")
    print(f"   跳过: {total_skipped} 条（人工标注保护）")
    print(f"   全局数据集总计: {len(existing_items)} 条")
    print(f"   📄 {global_path}")

    return {
        "total_added": total_added,
        "total_updated": total_updated,
        "total_skipped": total_skipped,
        "total_files": len(all_files),
    }


def main() -> int:
    """CLI 入口。"""
    if len(sys.argv) < 2:
        print("用法: python merge_to_global.py [--all | <doc_id>]")
        print()
        print("示例:")
        print("  python merge_to_global.py doc_abc123456789")
        print("  python merge_to_global.py --all")
        return 1

    if sys.argv[1] == "--all":
        result = merge_all()
        return 0 if result["total_added"] >= 0 else 1

    doc_id = sys.argv[1]
    added, _updated, _skipped = merge_doc_to_global(doc_id)
    return 0 if added >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
