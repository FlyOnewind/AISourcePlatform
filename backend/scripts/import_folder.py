"""从多层嵌套文件夹中批量导入文件到知识库。

递归遍历指定目录及其所有子目录，将支持的文件类型（md/txt/docx/xlsx/pptx/pdf/html）
上传到 MinIO，创建文档记录并提交异步入库任务。

用法：
  cd backend
  python scripts/import_folder.py /path/to/folder                          # 导入文件夹
  python scripts/import_folder.py /path/to/folder --category 技术文档       # 指定分类
"""

from __future__ import annotations

import argparse
import logging
import mimetypes
import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中，使 app.* 等模块可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── 初始化应用依赖（DB / MinIO / Milvus / Dramatiq broker） ──
# app.core.deps 在导入时自动完成 PostgreSQL、MinIO、Milvus、解析器等初始化
import app.core.deps  # noqa: E402, F401
# app.tasks 在导入时配置 Dramatiq Redis broker 并注册 actor
import app.tasks  # noqa: E402, F401

from app.core.config import settings  # noqa: E402
from app.core.deps import document_repo, job_repo  # noqa: E402
from app.core.models import Document, IngestJob, compute_hash, new_id  # noqa: E402
from app.core.errors import DuplicateDocumentError  # noqa: E402
from app.api.upload_utils import DEFAULT_CATEGORY, save_upload_file  # noqa: E402
from app.tasks.ingest import ingest_document  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("import_folder")

# ── 支持的文件扩展名 → source_type 映射 ──
EXT_TO_SOURCE_TYPE: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".pptx": "pptx",
}


def _guess_content_type(file_path: Path) -> str:
    """根据文件扩展名推断 MIME 类型。"""
    mime, _ = mimetypes.guess_type(str(file_path))
    return mime or "application/octet-stream"


def _collect_files(root: Path) -> list[Path]:
    """递归收集目录中所有支持的文件，跳过隐藏文件/文件夹（以 . 开头）。

    Args:
        root: 根目录路径。

    Returns:
        按路径排序的支持文件列表。
    """
    files: list[Path] = []

    def _walk(current: Path) -> None:
        try:
            for entry in sorted(current.iterdir()):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    _walk(entry)
                elif entry.is_file():
                    if entry.suffix.lower() in EXT_TO_SOURCE_TYPE:
                        files.append(entry)
        except PermissionError:
            logger.warning("无权限访问目录，跳过: %s", current)

    _walk(root)
    return files


def _import_one(file_path: Path, category: str) -> dict:
    """导入单个文件：读取 → 去重 → 预占位 → MinIO → 入队。

    Args:
        file_path: 文件路径。
        category:  文档分类。

    Returns:
        包含 file_path、size、status、doc_id、error 等字段的结果字典。
    """
    original_name = file_path.name
    ext = file_path.suffix.lower()
    source_type = EXT_TO_SOURCE_TYPE.get(ext, "unknown")

    # ── [1] 读取文件内容 ──
    try:
        file_content = file_path.read_bytes()
    except Exception as exc:
        logger.error("读取文件失败: %s (%s)", file_path, exc)
        return {"file_path": str(file_path), "file_name": original_name, "size": 0, "status": "failed", "error": f"读取失败: {exc}"}

    size = len(file_content)

    # ── [2] 去重检查 ──
    source_hash = compute_hash(file_content)
    if document_repo is not None:
        existing = document_repo.find_by_hash(source_hash)
        if existing is not None:
            logger.info("跳过重复: %s（已有文档 %s）", file_path, existing.doc_id)
            return {"file_path": str(file_path), "file_name": original_name, "size": size, "status": "duplicate", "doc_id": existing.doc_id}

    # ── [3] 创建 Document 预占位 ──
    doc_id = new_id("doc")
    doc = Document(
        doc_id=doc_id,
        title=file_path.stem,
        source_type=source_type,
        source_uri="",
        source_hash=source_hash,
        category=category,
        metadata={"import_source": str(file_path)},
    )

    if document_repo is not None:
        try:
            doc = document_repo.create(doc)
        except DuplicateDocumentError as e:
            logger.warning("并发重复: %s (%s)", file_path, e)
            return {"file_path": str(file_path), "file_name": original_name, "size": size, "status": "duplicate", "error": str(e)}

    # ── [4] 上传到 MinIO ──
    try:
        upload_data = save_upload_file(
            file_content, original_name, size,
            title=file_path.stem, category=category,
            content_type=_guess_content_type(file_path), doc_id=doc_id,
        )
    except Exception as exc:
        logger.error("MinIO 上传失败: %s (%s)", file_path, exc)
        if document_repo is not None:
            try:
                document_repo.hard_delete(doc_id)
            except Exception:
                pass
        return {"file_path": str(file_path), "file_name": original_name, "size": size, "status": "failed", "error": f"MinIO 上传失败: {exc}"}

    # ── [5] 更新 source_uri ──
    doc.source_uri = upload_data["source_uri"]
    if document_repo is not None:
        try:
            doc = document_repo.update(doc)
        except Exception:
            logger.exception("更新 source_uri 失败: %s", doc_id)

    # ── [6] 创建 IngestJob + 入队 Dramatiq ──
    job_id = new_id("job")
    try:
        job = IngestJob(job_id=job_id, doc_id=doc_id, stage="", progress=0)
        if job_repo is not None:
            job = job_repo.create(job)

        message = ingest_document.send(job_id, doc_id)
        job.dramatiq_message_id = message.message_id
        if job_repo is not None:
            job_repo.update(job)

    except Exception as exc:
        logger.exception("入队失败: %s (%s)", job_id, file_path)
        if job_repo is not None:
            try:
                job_repo.hard_delete(job_id)
            except Exception:
                pass
        if document_repo is not None:
            try:
                document_repo.hard_delete(doc_id)
            except Exception:
                pass
        return {"file_path": str(file_path), "file_name": original_name, "size": size, "status": "failed", "error": f"入队失败: {exc}"}

    logger.info("已提交: %s → doc_id=%s job_id=%s", file_path, doc_id, job_id)
    return {"file_path": str(file_path), "file_name": original_name, "size": size, "doc_id": doc_id, "job_id": job_id, "status": "success"}


def main() -> None:
    parser = argparse.ArgumentParser(description="从多层嵌套文件夹批量导入文件到知识库")
    parser.add_argument("folder", type=str, help="要导入的根目录路径")
    parser.add_argument("--category", "-c", type=str, default=DEFAULT_CATEGORY, help=f"文档分类（默认: {DEFAULT_CATEGORY}）")
    args = parser.parse_args()

    root = Path(args.folder).resolve()
    if not root.is_dir():
        logger.error("路径不存在或不是目录: %s", root)
        sys.exit(1)

    # ── 收集文件 ──
    files = _collect_files(root)
    if not files:
        logger.warning("没有找到支持的文件（%s）", ", ".join(EXT_TO_SOURCE_TYPE.keys()))
        return

    logger.info("目录: %s", root)
    logger.info("文件: %d 个 | 分类: %s", len(files), args.category)
    logger.info("数据库: %s | MinIO: %s | Redis: %s", settings.database_url, settings.minio_endpoint, settings.redis_url)

    # ── 逐个导入 ──
    results: list[dict] = []
    for i, file_path in enumerate(files, 1):
        rel = file_path.relative_to(root) if file_path.is_relative_to(root) else file_path
        logger.info("[%d/%d] %s", i, len(files), rel)
        results.append(_import_one(file_path, args.category))

    # ── 汇总 ──
    success = sum(1 for r in results if r["status"] == "success")
    dup = sum(1 for r in results if r["status"] == "duplicate")
    fail = sum(1 for r in results if r["status"] == "failed")
    logger.info("=" * 50)
    logger.info("导入完成: 成功 %d | 跳过(重复) %d | 失败 %d", success, dup, fail)

    if fail:
        logger.warning("失败文件:")
        for r in results:
            if r["status"] == "failed":
                logger.warning("  - %s: %s", r["file_path"], r.get("error", "未知错误"))


if __name__ == "__main__":
    main()
