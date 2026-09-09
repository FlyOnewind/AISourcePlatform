"""应用全局配置管理 — 火山引擎 LLM/Embedding、PostgreSQL、Milvus、MinIO 等外部服务参数。"""

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOLCENGINE_",
        env_file=PACKAGE_ROOT / ".env",
    )

    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    llm_model: str = "doubao-seed-2-0-pro-260215"  # 语义抽取等高质量任务
    llm_fast_model: str = Field(default="doubao-seed-2-0-mini-260428", validation_alias="LLM_FAST_MODEL")  # 改写/重排等高频低延迟任务
    embedding_model: str = "doubao-embedding-vision-251215"
    request_timeout_seconds: float = Field(default=3600.0, validation_alias="VOLCENGINE_TIMEOUT_SECONDS")

    # 检索默认参数。通过原始环境变量读取，便于评测脚本动态覆盖。
    vector_top_k: int = Field(default=30, validation_alias="VECTOR_TOP_K")
    bm25_top_k: int = Field(default=30, validation_alias="BM25_TOP_K")
    fusion_top_k: int = Field(default=15, validation_alias="FUSION_TOP_K")
    final_top_k: int = Field(default=5, validation_alias="FINAL_TOP_K")
    rrf_k: int = Field(default=60, validation_alias="RRF_K")

    # 入库处理限制
    max_upload_size_mb: int = Field(default=100, validation_alias="MAX_UPLOAD_SIZE_MB")  # 上传文件大小上限（MB），超限拒绝，防止 OOM
    # LLM 上下文窗口大小（参与 max_window_tokens 默认值计算）
    context_window_tokens: int = Field(default=256000, validation_alias="CONTEXT_WINDOW_TOKENS")
    # 单次 LLM 语义抽取的输入 Token 上限，默认取 context_window_tokens 的 40%。
    # context 预算分配（256K）：
    #   输出(65536, 26%) + prompt(5000, 2%) + 输入实际(~164K, 64%) + 余量(~22K, 8%) = 256K
    # 输入 102400 估算 × 1.5(JSON补偿) + asset描述(10000) ≈ 164K 实际。
    # mini 模型 (32K) 需手动调小，如 context=32000 → max_window≈13000。
    max_window_tokens: int = Field(
        default=102400, validation_alias="MAX_WINDOW_TOKENS",
    )
    embedding_batch_size: int = Field(default=100, validation_alias="EMBEDDING_BATCH_SIZE")
    index_upsert_batch_size: int = Field(default=100, validation_alias="INDEX_UPSERT_BATCH_SIZE")

    # LLM 重试策略
    max_json_retries: int = 3

    # 后端模式：仅支持 postgres。
    backend: str = Field(default="postgres", validation_alias="BACKEND")
    database_url: str = Field(
        default="postgresql://kbuser:kbpass@localhost:5432/knowledge_base",
        validation_alias="DATABASE_URL",
    )

    # Milvus：必须启用并可连接。
    milvus_enabled: bool = Field(default=True, validation_alias="MILVUS_ENABLED")
    milvus_host: str = Field(default="localhost", validation_alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, validation_alias="MILVUS_PORT")
    milvus_collection: str = Field(
        default="knowledge_chunks", validation_alias="MILVUS_COLLECTION"
    )
    # HNSW 索引参数
    milvus_hnsw_M: int = Field(default=16, validation_alias="MILVUS_HNSW_M")
    milvus_hnsw_ef_construction: int = Field(default=200, validation_alias="MILVUS_HNSW_EF_CONSTRUCTION")
    milvus_hnsw_ef: int = Field(default=120, validation_alias="MILVUS_HNSW_EF")  # HNSW 搜索候选集大小，ef ≥ top_k×4 保证召回率（top_k=30 → 建议 ≥120）
    # BM25 检索参数
    milvus_sparse_ef: int = Field(default=60, validation_alias="MILVUS_SPARSE_EF")  # 稀疏向量搜索候选集大小，ef ≥ top_k×2 保证召回率（top_k=30 → 建议 ≥60）

    # MinIO：必须启用并可连接。
    minio_enabled: bool = Field(default=True, validation_alias="MINIO_ENABLED")
    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(
        default="minioadmin", validation_alias="MINIO_ACCESS_KEY"
    )
    minio_secret_key: str = Field(
        default="minioadmin", validation_alias="MINIO_SECRET_KEY"
    )
    minio_bucket_input: str = Field(
        default="kb-input", validation_alias="MINIO_BUCKET_INPUT"
    )
    minio_bucket_assets: str = Field(
        default="kb-assets", validation_alias="MINIO_BUCKET_ASSETS"
    )
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")
    minio_presigned_expiry: int = Field(
        default=3600, validation_alias="MINIO_PRESIGNED_EXPIRY"
    )
    minio_public_endpoint: str = Field(
        default="",
        validation_alias="MINIO_PUBLIC_ENDPOINT",
    )  # 预签名 URL 对外暴露的地址，如 https://kb.example.com；留空则使用内部地址

    # 多模态视觉理解
    image_vision_enabled: bool = Field(default=True, validation_alias="IMAGE_VISION_ENABLED")
    video_vision_enabled: bool = Field(default=True, validation_alias="VIDEO_VISION_ENABLED")

    # MinerU PDF 精准解析
    mineru_api_token: str = Field(default="", validation_alias="MINERU_API_TOKEN")
    mineru_api_base: str = Field(default="https://mineru.net", validation_alias="MINERU_API_BASE")
    mineru_use_vlm: bool = Field(default=False, validation_alias="MINERU_USE_VLM")

    # 评测数据自动生成
    auto_eval_enabled: bool = Field(default=True, validation_alias="AUTO_EVAL_ENABLED")
    auto_eval_queries_per_doc: int = Field(default=3, validation_alias="AUTO_EVAL_QUERIES_PER_DOC")

    # 微信微盘下载：浏览器 Cookie（短期，需手动刷新）
    wechat_drive_cookies: str = Field(default="", validation_alias="WECHAT_DRIVE_COOKIES")
    # 微信微盘下载：企业 API 凭证（持久化，自动刷新 access_token）
    wechat_corpid: str = Field(default="", validation_alias="WECHAT_CORPID")
    wechat_corpsecret: str = Field(default="", validation_alias="WECHAT_CORPSECRET")

    # 异步任务队列（Dramatiq + Redis）
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    dramatiq_task_max_retries: int = Field(default=3, validation_alias="DRAMATIQ_TASK_MAX_RETRIES")
    dramatiq_task_time_limit_ms: int = Field(default=1_800_000, validation_alias="DRAMATIQ_TASK_TIME_LIMIT_MS")  # 30 分钟硬超时

    def reload_runtime_env(self) -> "Settings":
        """按需刷新运行期可调配置，支持评测和线上调参无需重启。"""
        fresh = type(self)()
        for field_name, field in type(self).model_fields.items():
            candidates = {field_name}
            if field.validation_alias:
                candidates.add(str(field.validation_alias))
            else:
                candidates.add(f"VOLCENGINE_{field_name.upper()}")
            if any(name in os.environ for name in candidates):
                setattr(self, field_name, getattr(fresh, field_name))
        return self


settings = Settings()


def get_settings(*, reload_env: bool = False) -> Settings:
    """返回全局配置；需要时刷新环境变量覆盖项。"""
    if reload_env:
        settings.reload_runtime_env()
    return settings
