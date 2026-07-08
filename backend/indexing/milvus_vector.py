"""Milvus 稠密向量索引与 Collection 管理器。

MilvusCollectionManager 统一管理 Milvus 连接、Collection 加载和 upsert 合并。
MilvusVectorIndex 基于 HNSW + COSINE 实现稠密向量相似度检索。
Collection 和索引由 scripts/setup_services.py 一次性创建，本模块只加载已有 Collection。

辅助函数：
- _json_dumps: 将 Python 值序列化为 JSON 字符串（Milvus VARCHAR 字段存储用）
- _escape_expr_value: 转义 Milvus 布尔表达式中的特殊字符（反斜杠和双引号）
- _default_entity: 构造 Milvus upsert 时的默认实体字段（用于缺失缓存的回退）
"""

import json
import logging
from typing import Any

from app.core.config import settings
from indexing.base import VectorIndex

logger = logging.getLogger(__name__)

DENSE_DIM = 1024
JSON_TEXT_FIELDS = {"source_refs", "asset_refs"}


def _json_dumps(value: Any) -> str:
    """将 Python 值序列化为 JSON 字符串，用于 Milvus VARCHAR 字段存储。

    None 或缺失值默认序列化为空数组 "[]"。
    """
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _escape_expr_value(value: str) -> str:
    """转义 Milvus 布尔表达式中的特殊字符（反斜杠和双引号）。

    防止用户输入中的特殊字符破坏 Milvus expr 语法。
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _default_entity(chunk_id: str) -> dict[str, Any]:
    """构造 Milvus upsert 的默认实体字典，用于缺失缓存时的回退填充。"""
    return {
        "chunk_id": chunk_id,
        "doc_id": "",
        "doc_title": "",
        "title": "",
        "content": "",
        "dense_vector": [0.0] * DENSE_DIM,
        "category": "",
        "knowledge_type": "",
        "status": "active",
        "source_refs": "[]",
        "asset_refs": "[]",
        "metadata": "{}",
    }


class MilvusCollectionManager:
    """Milvus Collection 生命周期管理器。

    统一管理：连接建立 / Collection 创建与 Schema 迁移 / 标量字段 upsert 合并 /
    HNSW + BM25 双索引创建 / 实体缓存。

    MilvusVectorIndex 和 MilvusBM25Index 共享同一个 Collection：
    - dense_vector 字段：HNSW 索引（COSINE 度量），供向量检索
    - sparse_vector 字段：BM25 Function 自动生成 + SPARSE_INVERTED_INDEX（BM25 度量）
    - 其余 VARCHAR/INT64 字段：标量存储与过滤
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.host = host or settings.milvus_host
        self.port = port or settings.milvus_port
        self.collection_name = collection_name or settings.milvus_collection
        self.alias = f"kb_{self.collection_name}"
        self.collection: Any | None = None
        self._cache: dict[str, dict[str, Any]] = {}

    def connect(self) -> None:
        """建立 Milvus 连接（幂等）。"""
        try:
            from pymilvus import connections
        except ImportError as exc:
            raise RuntimeError("pymilvus is not installed") from exc

        connections.connect(alias=self.alias, host=self.host, port=str(self.port))

    def ensure_collection(self) -> None:
        """加载已有 Collection（由 setup_services.py 预先创建）。

        Collection 不存在时抛出 RuntimeError，提示先运行初始化脚本。
        """
        self.connect()
        from pymilvus import Collection, utility

        if not utility.has_collection(self.collection_name, using=self.alias):
            raise RuntimeError(
                f"Milvus Collection '{self.collection_name}' 不存在，"
                f"请先运行: python scripts/setup_services.py"
            )
        self.collection = Collection(self.collection_name, using=self.alias)
        self.ensure_sparse_index()
        self.collection.load()

    def ensure_sparse_index(self) -> None:
        """确保 sparse_vector 字段上存在 SPARSE_INVERTED_INDEX（BM25 度量）。"""
        if self.collection is None:
            return
        for index in getattr(self.collection, "indexes", []) or []:
            if getattr(index, "field_name", "") == "sparse_vector":
                return
        self.collection.create_index(
            "sparse_vector",
            {
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "BM25",
                "params": {},
            },
        )

    def disconnect(self) -> None:
        """断开 Milvus 连接（使用 remove_connection 替代已弃用的 disconnect）。"""
        try:
            from pymilvus import connections

            connections.remove_connection(self.alias)
        except Exception:
            logger.exception("断开 Milvus 连接失败")

    def upsert_fields(self, chunk_id: str, fields: dict[str, Any]) -> None:
        """更新单条知识块的标量字段（转为批量调用）。"""
        self.upsert_fields_batch([(chunk_id, fields)])

    def _load_existing_entities(self, chunk_ids: list[str]) -> None:
        """将 Milvus 已有实体加载到缓存，避免局部更新覆盖原向量和正文。"""
        missing_ids = [chunk_id for chunk_id in chunk_ids if chunk_id not in self._cache]
        if not missing_ids:
            return
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")

        quoted_ids = ", ".join(
            f'"{_escape_expr_value(chunk_id)}"'
            for chunk_id in missing_ids
        )
        rows = self.collection.query(
            expr=f"chunk_id in [{quoted_ids}]",
            output_fields=list(_default_entity("").keys()),
        )
        for row in rows or []:
            chunk_id = str(row.get("chunk_id", ""))
            if chunk_id:
                self._cache[chunk_id] = dict(row)

    def upsert_fields_batch(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        if not items:
            return
        self.ensure_collection()
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")

        # 进程重启后内存缓存为空。局部更新前必须先读取原实体，否则默认值会把
        # dense_vector、content 等未更新字段覆盖为空值。
        self._load_existing_entities([chunk_id for chunk_id, _ in items])

        # sparse_vector 是 BM25 Function 自动生成的输出字段，不能手动写入
        _FUNCTION_OUTPUT_FIELDS = {"sparse_vector"}

        entities = []
        for chunk_id, fields in items:
            cached = self._cache.get(chunk_id)
            if cached is None and "dense_vector" not in fields:
                raise KeyError(f"Milvus 中不存在待局部更新的知识块: {chunk_id}")
            entity = dict(cached or _default_entity(chunk_id))
            entity.update(fields)
            # 移除 Function 输出字段——它们由 Milvus 自动生成
            for f in _FUNCTION_OUTPUT_FIELDS:
                entity.pop(f, None)
            self._cache[chunk_id] = entity
            entities.append(entity)
        self.collection.upsert(entities)
        self.collection.flush()

    def upsert_entities(self, entities: list[dict[str, Any]]) -> None:
        """全量 upsert 实体列表，跳过 _load_existing_entities 查询。

        调用方保证每个 entity 包含全部必要字段（dense_vector 或 content 至少其一，
        加上 doc_id/doc_title/title/category/knowledge_type/status/source_refs/asset_refs）。

        适用场景：_index_chunks 初次入库；不适用于部分更新（sync_index_metadata）。
        """
        if not entities:
            return
        self.ensure_collection()
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")

        _FN_OUTPUT = {"sparse_vector"}
        for entity in entities:
            for f in _FN_OUTPUT:
                entity.pop(f, None)
            # 写入内存缓存，供后续部分更新（sync_index_metadata）使用
            self._cache[entity["chunk_id"]] = entity
        self.collection.upsert(entities)
        self.collection.flush()

    def delete(self, chunk_id: str) -> None:
        self.ensure_collection()
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")
        self._cache.pop(chunk_id, None)
        self.collection.delete(expr=f'chunk_id == "{_escape_expr_value(chunk_id)}"')
        self.collection.flush()

    def delete_batch(self, chunk_ids: list[str]) -> None:
        """批量删除知识块，一次 RPC + 一次 flush。

        适用于重入库清理、批量删除等场景，避免逐条 delete 的 RPC 开销。
        """
        if not chunk_ids:
            return
        self.ensure_collection()
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")
        for chunk_id in chunk_ids:
            self._cache.pop(chunk_id, None)
        quoted = ", ".join(
            f'"{_escape_expr_value(cid)}"' for cid in chunk_ids
        )
        self.collection.delete(expr=f"chunk_id in [{quoted}]")
        self.collection.flush()


class MilvusVectorIndex(VectorIndex):
    """基于 Milvus 的稠密向量索引实现（HNSW + COSINE 相似度）。

    与 MilvusBM25Index 共享同一 Collection，通过注入 MilvusCollectionManager
    实现连接和集合生命周期的统一管理。
    """

    def __init__(self, manager: MilvusCollectionManager | None = None) -> None:
        """初始化向量索引，可注入共享的 MilvusCollectionManager。"""
        self._manager = manager or MilvusCollectionManager()

    @property
    def manager(self) -> MilvusCollectionManager:
        """获取内部的 MilvusCollectionManager 实例。"""
        return self._manager

    def connect(self) -> None:
        """建立 Milvus 连接（委托给 manager）。"""
        self._manager.connect()

    def ensure_collection(self) -> None:
        """确保 Collection 存在且 Schema 兼容（委托给 manager）。"""
        self._manager.ensure_collection()

    def disconnect(self) -> None:
        """断开 Milvus 连接（委托给 manager）。"""
        self._manager.disconnect()

    def add(
        self,
        chunk_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        """添加单条稠密向量 + 标量字段（转为批量调用）。"""
        self.add_batch([(chunk_id, vector, metadata)])

    def add_batch(
        self,
        items: list[tuple[str, list[float], dict | None]],
    ) -> None:
        """批量添加稠密向量 + 标量字段。"""
        fields_items = [
            (chunk_id, self._build_fields(vector, metadata))
            for chunk_id, vector, metadata in items
        ]
        self._manager.upsert_fields_batch(fields_items)

    @staticmethod
    def _build_fields(
        vector: list[float],
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """从向量和元数据构造 Milvus upsert 所需的标量字段字典。"""
        metadata = metadata or {}
        if len(vector) != DENSE_DIM:
            raise ValueError(f"dense vector dimension must be {DENSE_DIM}")

        fields = {
            "dense_vector": [float(v) for v in vector],
            "doc_id": str(metadata.get("doc_id", "")),
            "doc_title": str(metadata.get("doc_title", ""))[:512],
            "title": str(metadata.get("title", ""))[:512],
            "content": str(metadata.get("content", ""))[:65535],
            "category": str(metadata.get("category", "")),
            "knowledge_type": str(metadata.get("knowledge_type", "")),
            "status": str(metadata.get("status", "active")),
        }
        for key in JSON_TEXT_FIELDS:
            fields[key] = _json_dumps(metadata.get(key, {} if key == "metadata" else []))
        return fields

    def delete(self, chunk_id: str) -> None:
        """删除指定知识块的向量和标量字段（委托给 manager）。"""
        self._manager.delete(chunk_id)

    def upsert_fields(self, chunk_id: str, fields: dict[str, Any]) -> None:
        """更新 Milvus 中知识块的标量字段。"""
        self._manager.upsert_fields(chunk_id, fields)

    def upsert_fields_batch(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        """批量更新 Milvus 中标量字段。"""
        self._manager.upsert_fields_batch(items)

    # Milvus 检索返回的标量字段（检索 pipeline 实际使用的字段）
    _SEARCH_OUTPUT_FIELDS = [
        "chunk_id", "doc_id", "doc_title", "title", "content", "category",
        "knowledge_type", "source_refs", "asset_refs",
    ]

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        categories: list[str] | None = None,
        knowledge_types: list[str] | None = None,
        doc_ids: list[str] | None = None,
        chunk_statuses: list[str] | None = None,
    ) -> list[tuple[str, float, dict]]:
        """稠密向量相似度检索（HNSW + COSINE）。

        返回 (chunk_id, score, fields_dict) 列表，按分数降序排列。
        全部过滤走 Milvus 标量字段，无需 PostgreSQL 后置过滤。

        参数:
            categories: 分类过滤列表，None 不过滤。
            knowledge_types: 知识类型过滤列表，None 不过滤。
            doc_ids: 文档 ID 过滤列表，None 不过滤。
            chunk_statuses: 知识块状态过滤列表，None 默认只查 active。
        """
        self._manager.ensure_collection()
        collection = self._manager.collection
        if collection is None:
            raise RuntimeError("Milvus collection is not initialized")

        # 状态过滤：未指定时默认只查 active
        if chunk_statuses:
            if len(chunk_statuses) == 1:
                expr_parts = [f'status == "{_escape_expr_value(chunk_statuses[0])}"']
            else:
                quoted = ", ".join(f'"{_escape_expr_value(s)}"' for s in chunk_statuses)
                expr_parts = [f"status in [{quoted}]"]
        else:
            expr_parts = ['status == "active"']
        if categories:
            if len(categories) == 1:
                expr_parts.append(f'category == "{_escape_expr_value(categories[0])}"')
            else:
                quoted = ", ".join(f'"{_escape_expr_value(c)}"' for c in categories)
                expr_parts.append(f"category in [{quoted}]")
        if knowledge_types:
            if len(knowledge_types) == 1:
                expr_parts.append(f'knowledge_type == "{_escape_expr_value(knowledge_types[0])}"')
            else:
                quoted = ", ".join(f'"{_escape_expr_value(k)}"' for k in knowledge_types)
                expr_parts.append(f"knowledge_type in [{quoted}]")
        if doc_ids:
            if len(doc_ids) == 1:
                expr_parts.append(f'doc_id == "{_escape_expr_value(doc_ids[0])}"')
            else:
                quoted = ", ".join(f'"{_escape_expr_value(d)}"' for d in doc_ids)
                expr_parts.append(f"doc_id in [{quoted}]")
        expr = " && ".join(expr_parts)

        results = collection.search(
            data=[[float(v) for v in query_vector]],
            anns_field="dense_vector",
            param={"metric_type": "COSINE", "params": {"ef": settings.milvus_hnsw_ef}},
            limit=top_k,
            expr=expr,
            output_fields=self._SEARCH_OUTPUT_FIELDS,
        )
        if not results:
            return []
        return [
            (hit.entity.get("chunk_id"), float(hit.score), dict(hit.entity.fields))
            for hit in results[0]
        ]
