"""资产（图片/视频）资源处理器。

负责 Asset 的后续处理流程：文件读取、格式校验、哈希去重、视觉理解和 MinIO 上传。

处理模式：
- image / video：内嵌资源，从 _data 或 original_uri 读取字节后走共享管线
- image_link / video_link：外部链接资源，先 HTTP 下载再走与内嵌资源相同的共享管线
- document_link：文档链接，下载后触发子文档入库（由 pipeline._process_document_link 处理）
"""

import hashlib
import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.models import Asset, AssetStatus
from assets.base import AssetStore
from assets.downloader import download_to_bytes
from assets.minio_store import MinioAssetStore, make_asset_key, read_uri_bytes

logger = logging.getLogger(__name__)

# ── 魔数 → MIME 类型映射 ──────────────────────────────────────────────

# 图片文件头魔数
_MAGIC_IMAGE = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",
    b"BM": "image/bmp",
}

# 视频容器格式魔数（用于基本格式校验）
_MAGIC_VIDEO = {
    b"\x00\x00\x00": "video/mp4",       # MP4: offset 4 处有 ftyp，这里宽松匹配前 3 字节
    b"\x1a\x45\xdf\xa3": "video/webm",  # WebM / MKV: EBML header
    b"RIFF": "video/avi",               # AVI: RIFF 容器
}


# ── 内部工具函数 ──────────────────────────────────────────────────────

def sniff_image_mime(data: bytes) -> str | None:
    """通过文件头魔数推断图片的 MIME 类型。

    Args:
        data: 图片文件的原始字节。

    Returns:
        MIME 类型字符串（如 "image/png"），无法识别时返回 None。
    """
    for magic, mime in _MAGIC_IMAGE.items():
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


def sniff_video_mime(data: bytes) -> str | None:
    """通过文件头魔数推断视频容器的 MIME 类型。

    支持的格式：MP4、WebM、MKV、AVI。

    Args:
        data: 视频文件的原始字节。

    Returns:
        MIME 类型字符串（如 "video/mp4"），无法识别时返回 None。
    """
    # MP4: 第 4-7 字节为 ftyp，前 3 字节通常为零
    if len(data) >= 12 and data[4:8] == b"ftyp":
        # 进一步区分 MP4 / MOV / 3GP
        brand = data[8:12]
        if brand == b"qt  ":
            return "video/quicktime"
        return "video/mp4"
    # WebM / MKV: EBML header
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        # doc_type 在 EBML header 中，位置不固定，统一返回 video/webm
        return "video/webm"
    # AVI: RIFF....AVI
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"AVI ":
        return "video/avi"
    return None


def _local_or_external_uri(uri: str) -> str:
    """为本地路径补充 file:// 前缀，已是远程协议的 URI 原样返回。"""
    if uri.startswith(("http://", "https://", "file://", "minio://")):
        return uri
    return f"file:///{Path(uri).resolve().as_posix()}"


def find_ready_duplicate(
    asset_store: AssetStore,
    content_hash: str,
    current_asset_id: str,
) -> Asset | None:
    """在已存储的 Asset 中查找具有相同 content_hash 的 ready 状态副本。

    通过 PgAssetStore 的 session_factory 查询数据库中的重复 Asset。

    Args:
        asset_store: Asset 存储后端。
        content_hash: 待匹配的内容哈希值。
        current_asset_id: 当前 Asset 的 ID（排除自身匹配）。

    Returns:
        匹配的已存在 Asset，未找到时返回 None。
    """
    metadata_store = getattr(asset_store, "_metadata_store", asset_store)
    if hasattr(metadata_store, "_store"):
        for asset in metadata_store._store.values():
            if (
                asset.asset_id != current_asset_id
                and asset.content_hash == content_hash
                and asset.status == AssetStatus.ready
            ):
                return asset

    session_factory = getattr(metadata_store, "_session_factory", None)
    if session_factory is not None:
        try:
            from app.db.models import DbAsset
            from app.db.repositories.assets import PgAssetStore

            with session_factory() as session:
                row = (
                    session.query(DbAsset)
                    .filter_by(content_hash=content_hash, status=AssetStatus.ready.value)
                    .first()
                )
                if row and row.asset_id != current_asset_id:
                    return PgAssetStore(session_factory)._from_db(row)
        except Exception:
            logger.exception("查询重复 Asset 失败")
    return None


# ── 共享处理管线 ──────────────────────────────────────────────────────

def _process_image_data(
    data: bytes,
    asset: Asset,
    asset_store: AssetStore,
    minio_store: MinioAssetStore | None = None,
) -> Asset:
    """处理图片字节数据：魔数校验、哈希去重、视觉理解、MinIO 上传。

    供 process_image（内嵌图片）和 process_image_link（下载后图片）共享。

    Args:
        data: 图片原始字节。
        asset: 待处理的图片 Asset。
        asset_store: Asset 元数据存储。
        minio_store: MinIO 对象存储后端（None 时跳过上传）。

    Returns:
        处理后的 Asset（状态为 ready 或 failed）。
    """
    try:
        mime_type = sniff_image_mime(data)
        if mime_type is None:
            # 检查是否下载到了 HTML 页面（如链接失效返回登录页）
            preview = data[:200].lstrip()
            if preview.startswith((b"<", b"<!DOCTYPE", b"<!doctype")):
                asset.error_message = (
                    "图片链接返回了网页而非图片文件（可能需要登录或已失效），"
                    f"响应前 100 字节: {data[:100]!r}"
                )
            else:
                asset.error_message = "invalid_image_type"
            asset.status = AssetStatus.failed
            asset_store.put(asset)
            return asset

        asset.metadata["mime_type"] = mime_type
        asset.content_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
        duplicate = find_ready_duplicate(asset_store, asset.content_hash, asset.asset_id)
        if duplicate is not None:
            asset.storage_uri = duplicate.storage_uri
            asset.extracted_text = duplicate.extracted_text
            asset.status = AssetStatus.ready
            asset_store.put(asset)
            return asset

        # 视觉理解：调用多模态模型生成图片内容描述
        cfg = get_settings(reload_env=True)
        if cfg.image_vision_enabled:
            try:
                from llm.volcengine_client import llm_client

                description = llm_client.describe_image(data, mime_type)
                if description:
                    asset.extracted_text = description
                else:
                    logger.warning("图片 %s 视觉理解返回空结果（可能 API Key 未配置或模型调用失败）", asset.asset_id)
                    asset.metadata["vision_status"] = "no_result"
            except Exception:
                logger.exception("图片 %s 视觉理解失败，继续上传 MinIO", asset.asset_id)
                asset.metadata["vision_status"] = "error"

        if minio_store is not None:
            key = make_asset_key(asset.content_hash, mime_type)
            asset.storage_uri = minio_store.upload_bytes(
                minio_store.assets_bucket,
                key,
                data,
                mime_type,
            )
        elif not asset.storage_uri and asset.asset_type not in (AssetType.image, AssetType.video):
            asset.storage_uri = _local_or_external_uri(asset.original_uri)

        asset.status = AssetStatus.ready
        object.__setattr__(asset, "_data", data)
        asset_store.put(asset)
        return asset
    except Exception as exc:
        logger.warning("图片资源处理失败: %s", exc)
        asset.status = AssetStatus.failed
        asset.error_message = str(exc)
        asset_store.put(asset)
        return asset


def _process_video_data(
    data: bytes,
    asset: Asset,
    asset_store: AssetStore,
    minio_store: MinioAssetStore | None = None,
) -> Asset:
    """处理视频字节数据：哈希去重、视觉理解、MinIO 上传。

    供 process_video（内嵌视频）和 process_video_link（下载后视频）共享。

    Args:
        data: 视频原始字节。
        asset: 待处理的视频 Asset。
        asset_store: Asset 元数据存储。
        minio_store: MinIO 对象存储后端（None 时跳过上传）。

    Returns:
        处理后的 Asset（状态为 ready 或 failed）。
    """
    try:
        # 格式校验：通过魔数推断视频容器格式
        mime_type = sniff_video_mime(data)
        if mime_type is None:
            # 无法识别视频容器格式时，检查是否为 HTML/文本响应（如下载链接返回登录页）
            preview = data[:200].lstrip()
            if preview.startswith((b"<", b"<!DOCTYPE", b"<!doctype")):
                asset.status = AssetStatus.failed
                asset.error_message = (
                    "视频链接返回了网页而非视频文件（可能需要登录或已失效），"
                    f"响应前 100 字节: {data[:100]!r}"
                )
                asset_store.put(asset)
                return asset
            # 其他无法识别格式的情况，使用通用 MIME 继续（容忍非标准容器）
            logger.warning("视频 %s 无法识别容器格式，使用通用 MIME", asset.asset_id)
            mime_type = "video/mp4"

        asset.metadata["mime_type"] = mime_type
        asset.content_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
        duplicate = find_ready_duplicate(asset_store, asset.content_hash, asset.asset_id)
        if duplicate is not None:
            asset.storage_uri = duplicate.storage_uri
            asset.extracted_text = duplicate.extracted_text
            asset.status = AssetStatus.ready
            asset_store.put(asset)
            return asset

        # 视觉理解：调用多模态模型生成视频内容总结
        cfg = get_settings(reload_env=True)
        if cfg.video_vision_enabled:
            try:
                from llm.volcengine_client import llm_client

                description = llm_client.describe_video(data, mime_type)
                if description:
                    asset.extracted_text = description
                else:
                    logger.warning("视频 %s 视觉理解返回空结果（可能 API Key 未配置或模型调用失败）", asset.asset_id)
                    asset.metadata["vision_status"] = "no_result"
            except Exception:
                logger.exception("视频 %s 视觉理解失败，继续上传 MinIO", asset.asset_id)
                asset.metadata["vision_status"] = "error"

        # 上传 MinIO
        if minio_store is not None:
            key = make_asset_key(asset.content_hash, mime_type)
            asset.storage_uri = minio_store.upload_bytes(
                minio_store.assets_bucket,
                key,
                data,
                mime_type,
            )
        elif not asset.storage_uri and asset.asset_type not in (AssetType.image, AssetType.video):
            asset.storage_uri = _local_or_external_uri(asset.original_uri)

        asset.status = AssetStatus.ready
        object.__setattr__(asset, "_data", data)
        asset_store.put(asset)
        return asset
    except Exception as exc:
        logger.warning("视频资源处理失败: %s", exc)
        asset.status = AssetStatus.failed
        asset.error_message = str(exc)
        asset_store.put(asset)
        return asset


# ── 公开入口函数 ──────────────────────────────────────────────────────

def process_image(
    asset: Asset,
    asset_store: AssetStore,
    minio_store: MinioAssetStore | None = None,
) -> Asset:
    """处理内嵌图片 Asset：从 _data 或 original_uri 读取字节后走共享管线。

    Args:
        asset: 待处理的图片 Asset（asset_type=image，_data 不为空）。
        asset_store: Asset 元数据存储。
        minio_store: MinIO 对象存储后端（None 时跳过上传）。

    Returns:
        处理后的 Asset。
    """
    data = getattr(asset, "_data", None)
    # 不再从 original_uri 降级（嵌入类型 original_uri 已为空）
    return _process_image_data(data, asset, asset_store, minio_store)


def process_video(
    asset: Asset,
    asset_store: AssetStore,
    minio_store: MinioAssetStore | None = None,
) -> Asset:
    """处理内嵌视频 Asset：从 _data 或 original_uri 读取字节后走共享管线。

    Args:
        asset: 待处理的视频 Asset（asset_type=video，_data 不为空）。
        asset_store: Asset 元数据存储。
        minio_store: MinIO 对象存储后端（None 时跳过上传）。

    Returns:
        处理后的 Asset。
    """
    data = getattr(asset, "_data", None)
    # 不再从 original_uri 降级（嵌入类型 original_uri 已为空）
    return _process_video_data(data, asset, asset_store, minio_store)


def process_image_link(
    asset: Asset,
    asset_store: AssetStore,
    minio_store: MinioAssetStore | None = None,
) -> Asset:
    """处理外部图片链接 Asset：HTTP 下载后走与内嵌图片相同的处理管线。

    Args:
        asset: 待处理的图片链接 Asset（asset_type=image_link，original_uri 为 URL）。
        asset_store: Asset 元数据存储。
        minio_store: MinIO 对象存储后端。

    Returns:
        处理后的 Asset。
    """
    try:
        data = download_to_bytes(asset.original_uri)
    except Exception as exc:
        logger.warning("图片链接下载失败: %s (%s)", asset.original_uri, exc)
        asset.status = AssetStatus.failed
        asset.error_message = f"download_failed: {exc}"
        asset_store.put(asset)
        return asset
    return _process_image_data(data, asset, asset_store, minio_store)


def process_video_link(
    asset: Asset,
    asset_store: AssetStore,
    minio_store: MinioAssetStore | None = None,
) -> Asset:
    """处理外部视频链接 Asset：HTTP 下载后走与内嵌视频相同的处理管线。

    Args:
        asset: 待处理的视频链接 Asset（asset_type=video_link，original_uri 为 URL）。
        asset_store: Asset 元数据存储。
        minio_store: MinIO 对象存储后端。

    Returns:
        处理后的 Asset。
    """
    try:
        data = download_to_bytes(asset.original_uri)
    except Exception as exc:
        logger.warning("视频链接下载失败: %s (%s)", asset.original_uri, exc)
        asset.status = AssetStatus.failed
        asset.error_message = f"download_failed: {exc}"
        asset_store.put(asset)
        return asset
    return _process_video_data(data, asset, asset_store, minio_store)
