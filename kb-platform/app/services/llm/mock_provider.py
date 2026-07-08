"""Mock Provider：不依赖任何外部服务，保证全流程本地可运行。

- embed: 用确定性哈希把文本映射到固定维度向量（同一文本永远得到同一向量，
  不同文本之间的余弦相似度由词汇重叠程度决定），用于在没有真实 Embedding
  模型时也能验证检索链路是否打通。
- generate: 抽取式模板生成——不调用任何模型，直接从 prompt 里能找到的
  上下文片段拼出一个结构化占位结果，明确标注 [MOCK GENERATED]，避免
  被误认为真实模型输出。
"""
import hashlib
import re

from app.services.llm.base import LLMProvider


class MockProvider(LLMProvider):
    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim

    @property
    def is_mock(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        tokens = re.findall(r"\w+", text.lower()) or [text.lower() or "empty"]
        vector = [0.0] * self._dim
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for i in range(0, len(digest), 2):
                idx = int.from_bytes(digest[i : i + 2], "big") % self._dim
                # 用 digest 后续字节决定正负号，让向量有正有负而不是全正
                sign = 1.0 if digest[i] % 2 == 0 else -1.0
                vector[idx] += sign
        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    async def generate(self, prompt: str, system: str | None = None, temperature: float = 0.4) -> str:
        snippet = prompt.strip().replace("\n", " ")
        snippet = snippet[:200] + ("..." if len(snippet) > 200 else "")
        return (
            "[MOCK GENERATED] 未配置真实 LLM_API_KEY，以下为规则占位输出，"
            f"仅用于验证链路：基于输入「{snippet}」生成的结构化结果。"
            "配置 .env 中的 LLM_API_KEY 后将改为调用真实模型。"
        )
