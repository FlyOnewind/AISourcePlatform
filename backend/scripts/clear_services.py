"""清空所有外部服务数据与结构：PostgreSQL 删表、Milvus 删 Collection、MinIO 清空对象并删 Bucket。

用法:  cd backend && python scripts/clear_services.py
"""

import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def clear_postgresql() -> None:
    """删除 PostgreSQL 中所有表（不可逆）。"""
    from sqlalchemy import text, inspect
    from app.db.engine import get_engine
    from app.db.models import Base

    logger.info("=== PostgreSQL: 删表 ===")
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("  连接成功")

    inspector = inspect(engine)
    tables_before = inspector.get_table_names()
    logger.info("  删除前表: %s", tables_before)

    Base.metadata.drop_all(engine)
    logger.info("  所有表已删除")

    tables_after = inspector.get_table_names()
    if tables_after:
        logger.warning("  残留表: %s", tables_after)
    else:
        logger.info("  确认：无残留表")


def clear_milvus() -> None:
    """删除 Milvus Collection（不可逆）。"""
    from app.core.config import settings
    from pymilvus import connections, utility

    logger.info("=== Milvus: 删 Collection ===")
    alias = "kb_clear"
    connections.connect(alias=alias, host=settings.milvus_host, port=str(settings.milvus_port))
    logger.info("  连接成功: %s:%s", settings.milvus_host, settings.milvus_port)

    coll_name = settings.milvus_collection
    if utility.has_collection(coll_name, using=alias):
        utility.drop_collection(coll_name, using=alias)
        logger.info("  Collection '%s' 已删除", coll_name)
    else:
        logger.info("  Collection '%s' 不存在，跳过", coll_name)

    connections.disconnect(alias)


def clear_minio() -> None:
    """清空 MinIO Bucket 中所有对象后删除 Bucket（不可逆）。"""
    from app.core.config import settings
    from minio import Minio

    logger.info("=== MinIO: 清空对象 + 删 Bucket ===")
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    logger.info("  连接成功: %s", settings.minio_endpoint)

    for bucket in [settings.minio_bucket_input, settings.minio_bucket_assets]:
        if not client.bucket_exists(bucket):
            logger.info("  Bucket '%s' 不存在，跳过", bucket)
            continue

        # 递归删除所有对象
        objects = list(client.list_objects(bucket, recursive=True))
        if objects:
            for obj in objects:
                client.remove_object(bucket, obj.object_name)
            logger.info("  Bucket '%s': 已删除 %d 个对象", bucket, len(objects))
        else:
            logger.info("  Bucket '%s': 无对象", bucket)

        client.remove_bucket(bucket)
        logger.info("  Bucket '%s': 已删除", bucket)


def main() -> None:
    logger.info("⚠️  即将清空 PostgreSQL 表、Milvus Collection、MinIO Bucket，不可恢复！")

    try:
        clear_postgresql()
    except Exception:
        logger.exception("PostgreSQL 清理失败")

    try:
        clear_milvus()
    except Exception:
        logger.exception("Milvus 清理失败")

    try:
        clear_minio()
    except Exception:
        logger.exception("MinIO 清理失败")

    logger.info("=== 全部清理完成 ===")


if __name__ == "__main__":
    main()
