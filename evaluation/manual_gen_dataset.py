"""评测数据手动生成脚本。

基于知识库中已有文档的知识块，调用 LLM 生成评测数据（查询 + chunk 标注 + 关键词）。
与 gen_dataset.py 不同，本脚本由用户**手动触发**，支持按文档、按分类或全量生成。

使用方式：
    cd backend
    python tests/evaluation/manual_gen_dataset.py                        # 交互模式
    python tests/evaluation/manual_gen_dataset.py --doc <doc_id>         # 指定文档
    python tests/evaluation/manual_gen_dataset.py --category <分类名>     # 指定分类（跨文档）
    python tests/evaluation/manual_gen_dataset.py --all                  # 全部活跃文档
    python tests/evaluation/manual_gen_dataset.py --list                 # 列出文档和分类概览
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中，使 app.* 等模块可导入
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.core.config import settings
from evaluation.gen_dataset import generate_for_chunks
from evaluation.storage import save_per_doc_dataset, init_storage, UNMERGED_DIR


def _has_existing_dataset(doc_id: str) -> bool:
    """检查是否已有未合并的评测数据集，避免重复生成。"""
    return bool(list(UNMERGED_DIR.glob(f"{doc_id}*.json")))


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _chunk_to_dict(chunk) -> dict:
    """将 KnowledgeChunk 对象转为 LLM 生成所需的 dict 格式。

    字段需与 ingestion/pipeline.py 中 _trigger_eval_data_generation 保持一致。
    """
    return {
        "chunk_id": chunk.chunk_id,
        "title": chunk.title,
        "content": chunk.content,
        "category": chunk.category,
        "knowledge_type": chunk.knowledge_type.value if hasattr(chunk.knowledge_type, "value") else chunk.knowledge_type,
    }


def _get_active_chunks_for_doc(doc_id: str) -> list:
    """获取指定文档下所有活跃知识块。"""
    from app.core.deps import chunk_store

    chunks = chunk_store.list_by_doc_id(doc_id)
    return [c for c in chunks if c.status == "active"]


def _get_active_chunks_for_category(category: str) -> list:
    """获取指定分类下所有活跃文档的活跃知识块。

    按文档的 category 字段匹配，确保与文档列表展示的分类一致。
    """
    from app.core.deps import chunk_store, document_repo

    docs = document_repo.list(status="active", category=category)
    if not docs:
        return []

    all_chunks = []
    for doc in docs:
        chunks = chunk_store.list_by_doc_id(doc.doc_id)
        all_chunks.extend(c for c in chunks if c.status == "active")
    return all_chunks


def _load_doc_info(doc_id: str) -> tuple[str, int]:
    """获取文档标题和版本号。不存在时返回 (doc_id, 1)，与 pipeline 回退策略一致。"""
    from app.core.deps import document_repo

    doc = document_repo.get(doc_id)
    if doc is None:
        return doc_id, 1
    return doc.title or doc.doc_id, doc.version


def _run_generate(
    chunks: list,
    doc_id: str,
    doc_title: str,
    query_count: int | None = None,
    doc_version: int = 1,
) -> tuple[list[dict], list[str]]:
    """对一批 chunk 调用 LLM 生成评测数据，校验后保存到 datasets/unmerged/。

    直接复用 gen_dataset.generate_for_chunks() 的完整流程：
    分片 → LLM 生成 → 校验 → 注入元数据。

    Args:
        chunks: KnowledgeChunk 对象列表。
        doc_id: 归属文档 ID。
        doc_title: 文档标题。
        query_count: 期望生成的查询数量。
        doc_version: 文档版本号。

    Returns:
        (有效条目列表, 错误信息列表)
    """
    if query_count is None:
        query_count = settings.auto_eval_queries_per_doc

    if not chunks:
        print(f"    [WARN] 没有活跃知识块，跳过")
        return [], []

    chunk_dicts = [_chunk_to_dict(c) for c in chunks]

    items, errors = generate_for_chunks(
        chunks=chunk_dicts,
        doc_id=doc_id,
        doc_title=doc_title,
        query_count=query_count,
        doc_version=doc_version,
    )

    if errors:
        for err in errors:
            print(f"    [WARN] {err}")

    if items:
        saved_path = save_per_doc_dataset(
            doc_id=doc_id,
            doc_title=doc_title,
            items=items,
            chunk_count=len(chunk_dicts),
            doc_version=doc_version,
        )
        print(f"    [OK] 生成 {len(items)} 条 → {saved_path.name}")
    else:
        print(f"    [FAIL] 未能生成有效评测数据")

    return items, errors


# ── 生成模式 ──────────────────────────────────────────────────────────


def run_doc(doc_id: str) -> int:
    """为指定文档生成评测数据。

    Args:
        doc_id: 文档 ID。

    Returns:
        生成的条目数。
    """
    chunks = _get_active_chunks_for_doc(doc_id)
    doc_title, doc_version = _load_doc_info(doc_id)

    if _has_existing_dataset(doc_id):
        print(f"  [SKIP]「{doc_title}」已有未合并数据集，跳过")
        return 0

    print(f"  [GEN]「{doc_title}」({len(chunks)} 个知识块) ...")

    items, _ = _run_generate(chunks, doc_id, doc_title, doc_version=doc_version)
    return len(items)


def run_category(category: str) -> int:
    """为指定分类下所有文档生成评测数据（按 doc_id 分组逐文档生成）。

    Args:
        category: 分类名。

    Returns:
        生成的总条目数。
    """
    chunks = _get_active_chunks_for_category(category)

    if not chunks:
        print(f"[FAIL] 分类「{category}」下没有活跃知识块")
        return 0

    # 按 doc_id 分组 — 保持与现有按文档存储的兼容性
    groups: dict[str, list] = {}
    for c in chunks:
        groups.setdefault(c.doc_id, []).append(c)

    print(f"\n[CAT] 分类「{category}」: {len(chunks)} 个 chunk，分布在 {len(groups)} 个文档中\n")

    total = 0
    skipped = 0
    for i, (doc_id, doc_chunks) in enumerate(groups.items(), 1):
        doc_title, doc_version = _load_doc_info(doc_id)

        if _has_existing_dataset(doc_id):
            print(f"  [{i}/{len(groups)}] [SKIP]「{doc_title}」已有未合并数据集，跳过")
            skipped += 1
            continue

        print(f"  [{i}/{len(groups)}]「{doc_title}」({len(doc_chunks)} 个知识块) ...")
        try:
            items, _ = _run_generate(doc_chunks, doc_id, doc_title, doc_version=doc_version)
            total += len(items)
        except Exception as exc:
            print(f"    [FAIL] 失败: {exc}")

    print(f"\n[OK] 分类「{category}」共生成 {total} 条评测数据", end="")
    if skipped:
        print(f"，跳过 {skipped} 个已有文档")
    print("\n")
    return total


def run_all() -> int:
    """为所有活跃文档生成评测数据。

    Returns:
        生成的总条目数。
    """
    from app.core.deps import document_repo

    docs = document_repo.list(status="active")
    if not docs:
        print("(empty) 没有活跃文档")
        return 0

    print(f"\n[START] 开始为 {len(docs)} 个文档生成评测数据...\n")

    total = 0
    for i, doc in enumerate(docs, 1):
        print(f"[{i}/{len(docs)}] ", end="")
        try:
            n = run_doc(doc.doc_id)
            total += n
        except Exception as exc:
            print(f"    [FAIL] 失败: {exc}")

    print(f"\n[OK] 全量生成完成，共 {total} 条评测数据\n")
    return total


# ── 列表展示 ──────────────────────────────────────────────────────────


def _iter_active_docs():
    """迭代所有活跃文档，返回 (序号, Document, chunk_count) 元组列表。"""
    from app.core.deps import document_repo, chunk_store

    docs = document_repo.list(status="active")
    result = []
    for i, doc in enumerate(docs, 1):
        count = chunk_store.count_by_doc_id(doc.doc_id)
        result.append((i, doc, count))
    return result


def run_list():
    """列出文档概览和分类统计。"""
    init_storage()

    # ── 文档列表 ──
    docs_info = _iter_active_docs()

    if not docs_info:
        print("(empty) 没有活跃文档，请先入库文档。")
        return

    print(f"\n{'='*80}")
    print(f"{'序号':<5} {'文档标题':<35} {'doc_id':<14} {'chunk':<7} {'分类'}")
    print(f"{'='*80}")
    for idx, doc, count in docs_info:
        title = doc.title[:33] + ".." if len(doc.title) > 35 else doc.title
        doc_id_short = doc.doc_id[:12]
        cat = doc.category or "-"
        print(f"{idx:<5} {title:<35} {doc_id_short:<14} {count:<7} {cat}")
    print(f"{'='*80}")
    print(f"共 {len(docs_info)} 个文档\n")

    # ── 分类统计（按文档 category 聚合 chunk 数量，与文档列表对齐）──
    cat_counts: dict[str, int] = {}
    for _, doc, count in docs_info:
        cat = doc.category or "未分类"
        cat_counts[cat] = cat_counts.get(cat, 0) + count

    if cat_counts:
        print(f"{'='*40}")
        print(f"{'分类':<22} {'chunk数':<8}")
        print(f"{'='*40}")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            print(f"{cat:<22} {count:<8}")
        print(f"{'='*40}")
        print(f"共 {len(cat_counts)} 个分类\n")


# ── 交互模式 ──────────────────────────────────────────────────────────


def run_interactive():
    """交互模式：展示概览后让用户选择生成维度。"""
    run_list()

    docs_info = _iter_active_docs()
    if not docs_info:
        return

    # 从文档级 category 提取分类名（与 run_list 展示对齐）
    cat_names = sorted(set(doc.category or "未分类" for _, doc, _ in docs_info))

    print("请选择生成模式:")
    print("  1) 按文档序号 — 输入数字（如 3）")
    print("  2) 按分类名   — 输入分类名（如 通用）")
    print("  3) 全部文档   — 输入 all")
    print("  4) 退出       — 输入 q")
    print()

    choice = input("> ").strip()

    if not choice or choice.lower() == "q":
        print("[BYE] 已退出")
        return

    if choice.lower() == "all":
        run_all()
        return

    # 先尝试按分类名匹配（必须在 int 解析之前，否则纯数字分类名会被当作文档序号）
    if choice in cat_names:
        cat = None if choice == "未分类" else choice
        run_category(cat if cat else "")
        return

    # 尝试按文档序号匹配
    try:
        idx = int(choice)
        for i, doc, _ in docs_info:
            if i == idx:
                print(f"\n[DOC] 已选择文档: {doc.title}\n")
                run_doc(doc.doc_id)
                return
        print(f"[FAIL] 序号 {idx} 不在有效范围内")
        return
    except ValueError:
        pass

    print(f"[FAIL] 无效输入「{choice}」，请输入有效序号、分类名或 all")


# ── CLI 入口 ──────────────────────────────────────────────────────────


if __name__ == "__main__":
    args = sys.argv[1:]

    # 帮助信息
    if "--help" in args or "-h" in args:
        print(__doc__)
        raise SystemExit(0)

    # 无参数 → 交互模式
    if not args:
        init_storage()
        run_interactive()
        raise SystemExit(0)

    # --doc <doc_id>
    doc_arg_idx = next((i for i, a in enumerate(args) if a == "--doc"), None)
    if doc_arg_idx is not None and doc_arg_idx + 1 < len(args):
        init_storage()
        doc_id = args[doc_arg_idx + 1]
        n = run_doc(doc_id)
        raise SystemExit(0 if n > 0 else 1)

    # --category <name>
    cat_arg_idx = next((i for i, a in enumerate(args) if a == "--category"), None)
    if cat_arg_idx is not None and cat_arg_idx + 1 < len(args):
        init_storage()
        category = args[cat_arg_idx + 1]
        total = run_category(category)
        raise SystemExit(0 if total > 0 else 1)

    # --all（放在 --doc/--category 之后，避免误匹配参数值）
    if args == ["--all"]:
        init_storage()
        total = run_all()
        raise SystemExit(0 if total > 0 else 1)

    # --list
    if args == ["--list"]:
        run_list()
        raise SystemExit(0)

    print("[FAIL] 未知参数，使用 --help 查看帮助")
    raise SystemExit(2)
