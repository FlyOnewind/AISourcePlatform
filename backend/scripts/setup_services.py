"""初始化所有外部服务：PostgreSQL 建表、Milvus 建 Collection、MinIO 建 Bucket。

一次性运行脚本，在全新环境或 docker-compose up 后执行。
项目代码不再自动创建这些资源，依赖由此脚本预先建好。

用法:  cd backend && python scripts/setup_services.py
"""

import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def setup_postgresql() -> None:
    """创建 PostgreSQL 所有表（幂等，已有表则跳过）。"""
    from app.core.config import settings
    from app.db.engine import get_engine
    from app.db.models import Base
    from sqlalchemy import text, inspect

    logger.info("=== PostgreSQL: 建表 ===")
    engine = get_engine()

    # 验证连接
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("  连接成功: %s", settings.database_url)

    # 创建所有表（幂等，含 __table_args__ 中定义的索引）
    Base.metadata.create_all(engine)
    logger.info("  表创建完成")

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logger.info("  现有表: %s", tables)


def setup_milvus() -> None:
    """创建 Milvus Collection 及 HNSW + BM25 双索引（幂等，已有则跳过）。"""
    from app.core.config import settings
    from pymilvus import (
        Collection, CollectionSchema, DataType, FieldSchema,
        Function, FunctionType, connections, utility,
    )

    logger.info("=== Milvus: 建 Collection ===")
    alias = "kb_setup"
    connections.connect(alias=alias, host=settings.milvus_host, port=str(settings.milvus_port))
    logger.info("  连接成功: %s:%s", settings.milvus_host, settings.milvus_port)

    coll_name = settings.milvus_collection
    if utility.has_collection(coll_name, using=alias):
        logger.info("  Collection '%s' 已存在，跳过创建", coll_name)
        connections.disconnect(alias)
        return

    DENSE_DIM = 1024
    fields = [
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="doc_title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(
            name="content", dtype=DataType.VARCHAR, max_length=65535,
            enable_analyzer=True, analyzer_params={"type": "chinese"},
        ),
        FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=DENSE_DIM),
        FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="knowledge_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="source_refs", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="asset_refs", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=65535),
    ]

    bm25_func = Function(
        name="bm25",
        function_type=FunctionType.BM25,
        input_field_names=["content"],
        output_field_names="sparse_vector",
    )

    schema = CollectionSchema(
        fields,
        description="知识库知识块混合检索索引（HNSW + BM25）",
        functions=[bm25_func],
    )

    collection = Collection(coll_name, schema=schema, using=alias)

    # HNSW 索引（稠密向量）
    collection.create_index(
        "dense_vector",
        {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {
                "M": settings.milvus_hnsw_M,
                "efConstruction": settings.milvus_hnsw_ef_construction,
            },
        },
    )

    # BM25 稀疏向量索引
    collection.create_index(
        "sparse_vector",
        {
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "BM25",
            "params": {},
        },
    )

    collection.load()
    logger.info("  Collection '%s' 创建完成（HNSW + BM25 索引已加载）", coll_name)
    connections.disconnect(alias)


def setup_minio() -> None:
    """创建 MinIO Bucket（幂等，已有则跳过）。"""
    from app.core.config import settings
    from minio import Minio

    logger.info("=== MinIO: 建 Bucket ===")
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    logger.info("  连接成功: %s", settings.minio_endpoint)

    for bucket in [settings.minio_bucket_input, settings.minio_bucket_assets]:
        if client.bucket_exists(bucket):
            logger.info("  Bucket '%s' 已存在，跳过", bucket)
        else:
            client.make_bucket(bucket)
            logger.info("  Bucket '%s' 已创建", bucket)


def main() -> None:
    logger.info("开始初始化外部服务...")
    try:
        setup_postgresql()
    except Exception:
        logger.exception("PostgreSQL 初始化失败")
        sys.exit(1)

    try:
        setup_milvus()
    except Exception:
        logger.exception("Milvus 初始化失败")
        sys.exit(1)

    try:
        setup_minio()
    except Exception:
        logger.exception("MinIO 初始化失败")
        sys.exit(1)

    logger.info("=== 全部外部服务初始化完成 ===")


if __name__ == "__main__":
    main()
