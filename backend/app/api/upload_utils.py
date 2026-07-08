"""上传工具函数模块。

提供 MinIO 上传的公共函数，供 v1 上传接口复用。
文件内容由调用方读入内存后传入，不在模块内部执行文件 IO。
"""

import io
import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.deps import minio_asset_store
from app.core.models import new_id
from assets.minio_store import make_minio_key

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────

DEFAULT_CATEGORY = "通用"
MINIO_PART_SIZE = 10 * 1024 * 1024  # MinIO 分片上传的块大小（10 MiB）


def save_upload_file(
    content: bytes,
    original_name: str,
    size: int,
    *,
    title: str | None = None,
    category: str = DEFAULT_CATEGORY,
    content_type: str = "application/octet-stream",
    doc_id: str | None = None,
) -> dict:
    """将文件内容上传到 MinIO，返回文件元信息。

    MinIO 上传在内存中完成，不执行文件 IO。
    文件大小由调用方预先计算后传入，避免重复 IO。

    Args:
        content:        文件原始字节。
        original_name:  原始文件名（用于生成 MinIO key 和缺省标题）。
        size:           文件字节数。
        title:          文档标题，为空时从 original_name 推断。
        category:       文档分类，默认"通用"。
        content_type:   文件 MIME 类型。
        doc_id:         预分配的文档 ID，为空时自动生成。

    Returns:
        dict 包含以下字段：
        - source_uri:   MinIO 对象 URI（格式：minio://bucket/key）
        - doc_id:       文档 ID
        - file_name:    原始文件名
        - size:         文件字节数
        - title:        文档标题
        - category:     文档分类
    """
    cfg = get_settings()
    resolved_doc_id = doc_id or new_id("doc")

    # ── 上传到 MinIO ──
    if not cfg.minio_enabled or minio_asset_store is None:
        raise RuntimeError("MinIO 未启用，文件上传失败")

    key = make_minio_key(resolved_doc_id, original_name)
    try:
        minio_asset_store.client.put_object(
            cfg.minio_bucket_input,
            key,
            io.BytesIO(content),
            length=size,
            content_type=content_type,
            part_size=MINIO_PART_SIZE,
        )
    except Exception:
        # 上传失败时尝试清理 MinIO 中可能残留的碎片对象
        logger.exception("MinIO 上传失败: %s", key)
        try:
            minio_asset_store.client.remove_object(cfg.minio_bucket_input, key)
        except Exception:
            logger.debug("清理 MinIO 残留对象失败（可能未写入）: %s", key)
        raise

    source_uri = f"minio://{cfg.minio_bucket_input}/{key}"

    return {
        "source_uri": source_uri,
        "doc_id": resolved_doc_id,
        "file_name": original_name,
        "size": size,
        "title": title or Path(original_name).stem,
        "category": category or DEFAULT_CATEGORY,
    }
