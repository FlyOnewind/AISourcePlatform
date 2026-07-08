"""检索引擎抽象基类 — 定义 VectorIndex 和 BM25Index 的统一接口。

具体实现：
- MilvusVectorIndex: 基于 Milvus 的稠密向量索引（HNSW + COSINE）
- MilvusBM25Index: 基于 Milvus 原生 BM25 Function 的稀疏向量索引
"""

from abc import ABC, abstractmethod


class VectorIndex(ABC):
    """稠密向量索引抽象基类 — 基于语义向量进行相似度检索。"""

    @abstractmethod
    def add(
        self,
        chunk_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        """添加单条向量记录。"""

    def add_batch(
        self,
        items: list[tuple[str, list[float], dict | None]],
    ) -> None:
        """批量添加向量；默认逐条写入，具体实现可覆盖为真正批量写入。"""
        for chunk_id, vector, metadata in items:
            self.add(chunk_id, vector, metadata)

    @abstractmethod
    def delete(self, chunk_id: str) -> None:
        """删除指定知识块的向量索引。"""

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int,
        categories: list[str] | None = None,
        knowledge_types: list[str] | None = None,
        doc_ids: list[str] | None = None,
        chunk_statuses: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """向量相似度检索，返回 (chunk_id, score) 列表，按分数降序排列。

        参数:
            categories: 分类过滤列表，None 不过滤。
            knowledge_types: 知识类型过滤列表，None 不过滤。
            doc_ids: 文档 ID 过滤列表，None 不过滤。
            chunk_statuses: 知识块状态过滤列表，None 默认只查 active。
        """


class BM25Index(ABC):
    """BM25 关键词索引抽象基类 — 基于分词进行全文检索。"""

    @abstractmethod
    def add(
        self,
        chunk_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None:
        """添加单条文本索引。"""

    def add_batch(
        self,
        items: list[tuple[str, str, dict | None]],
    ) -> None:
        """批量添加文本索引；默认逐条写入，具体实现可覆盖为真正批量写入。"""
        for chunk_id, text, metadata in items:
            self.add(chunk_id, text, metadata)

    @abstractmethod
    def delete(self, chunk_id: str) -> None:
        """删除指定知识块的文本索引。"""

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int,
        categories: list[str] | None = None,
        knowledge_types: list[str] | None = None,
        doc_ids: list[str] | None = None,
        chunk_statuses: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """BM25 关键词检索，返回 (chunk_id, score) 列表，按分数降序排列。

        参数:
            categories: 分类过滤列表，None 不过滤。
            knowledge_types: 知识类型过滤列表，None 不过滤。
            doc_ids: 文档 ID 过滤列表，None 不过滤。
            chunk_statuses: 知识块状态过滤列表，None 默认只查 active。
        """
