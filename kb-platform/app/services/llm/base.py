"""LLM/Embedding Provider 抽象接口。

所有上层代码（RAG生成、能力检索语义打分、Skill执行）只依赖这个接口，
不关心底层是 Mock 还是真实模型，切换 Provider 无需改动业务代码。
"""
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """把文本编码为向量，用于向量检索和语义相似度打分。"""

    @abstractmethod
    async def generate(self, prompt: str, system: str | None = None, temperature: float = 0.4) -> str:
        """根据 prompt 生成文本，用于 RAG 答案生成、Skill 内容生成等。"""

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        """标识是否为 Mock 实现，供响应中透传告知调用方（避免误以为是真实模型结果）。"""
