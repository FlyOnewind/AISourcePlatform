"""向量库封装（Qdrant）。集合按知识库维度划分：{prefix}{kb_key}。"""
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import get_settings


class VectorStore:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = QdrantClient(url=settings.qdrant_url)
        self._prefix = settings.qdrant_collection_prefix
        self._dim = settings.embedding_dim

    def _collection_name(self, kb_key: str) -> str:
        return f"{self._prefix}{kb_key}"

    def ensure_collection(self, kb_key: str) -> None:
        name = self._collection_name(kb_key)
        if not self._client.collection_exists(name):
            self._client.create_collection(
                collection_name=name,
                vectors_config=qmodels.VectorParams(size=self._dim, distance=qmodels.Distance.COSINE),
            )

    def upsert_chunk(self, kb_key: str, chunk_id: str, vector: list[float], payload: dict) -> None:
        self.ensure_collection(kb_key)
        self._client.upsert(
            collection_name=self._collection_name(kb_key),
            points=[qmodels.PointStruct(id=chunk_id, vector=vector, payload=payload)],
        )

    def search(self, kb_key: str, vector: list[float], top_k: int = 5) -> list[dict]:
        name = self._collection_name(kb_key)
        if not self._client.collection_exists(name):
            return []
        hits = self._client.query_points(collection_name=name, query=vector, limit=top_k).points
        return [{"id": h.id, "score": h.score, "payload": h.payload} for h in hits]

    def delete_collection(self, kb_key: str) -> None:
        name = self._collection_name(kb_key)
        if self._client.collection_exists(name):
            self._client.delete_collection(name)


@lru_cache
def get_vector_store() -> VectorStore:
    return VectorStore()
