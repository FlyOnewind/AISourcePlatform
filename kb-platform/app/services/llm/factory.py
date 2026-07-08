"""Provider 工厂：按配置自动选择 Mock 或真实 Provider。

未显式设置 LLM_PROVIDER=openai_compatible 且未填 LLM_API_KEY 时，
自动回退 Mock，保证开箱即用不依赖外网。
"""
from functools import lru_cache

from app.core.config import get_settings
from app.services.llm.base import LLMProvider
from app.services.llm.mock_provider import MockProvider
from app.services.llm.openai_compatible_provider import OpenAICompatibleProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    use_real = settings.llm_provider == "openai_compatible" and bool(settings.llm_api_key)
    if use_real:
        return OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            embedding_model=settings.embedding_model,
        )
    return MockProvider(dim=settings.embedding_dim)
