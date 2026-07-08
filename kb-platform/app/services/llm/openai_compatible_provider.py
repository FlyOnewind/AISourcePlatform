"""OpenAI 兼容 Provider：适配 DeepSeek 等提供 OpenAI 兼容接口的服务。"""
from openai import AsyncOpenAI

from app.services.llm.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str, embedding_model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._embedding_model = embedding_model

    @property
    def is_mock(self) -> bool:
        return False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(model=self._embedding_model, input=texts)
        return [item.embedding for item in resp.data]

    async def generate(self, prompt: str, system: str | None = None, temperature: float = 0.4) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=temperature
        )
        return resp.choices[0].message.content or ""
