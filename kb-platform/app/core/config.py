"""应用配置。所有配置项均可通过 .env 覆盖，详见 .env.example 的注释。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_name: str = "kb-platform"
    debug: bool = True
    secret_key: str = "dev-secret-key-change-me"

    database_url: str = "postgresql+asyncpg://kbplatform:kbplatform@localhost:5432/kbplatform"

    redis_url: str = "redis://localhost:6379/0"
    gateway_redis_prefix: str = "gateway"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_prefix: str = "kb_"

    object_storage_endpoint: str = "localhost:9000"
    object_storage_access_key: str = "kbplatform"
    object_storage_secret_key: str = "kbplatform123"
    object_storage_bucket: str = "kb-platform-docs"
    object_storage_secure: bool = False

    # LLM_PROVIDER: "mock" | "openai_compatible"。留空/未知值时按是否配置了 LLM_API_KEY 自动判断。
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
