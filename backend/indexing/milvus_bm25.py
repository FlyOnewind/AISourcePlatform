"""Milvus 2.5 原生 BM25 索引实现。

基于 Milvus Function(FunctionType.BM25) + chinese 分析器，
稀疏向量由 Milvus 内置 Tantivy 引擎自动生成，无需应用层分词或 IDF 统计。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from indexing.base import BM25Index
from indexing.milvus_vector import (
    MilvusCollectionManager,
    _escape_expr_value,
    _json_dumps,
)

logger = logging.getLogger(__name__)

JSON_TEXT_FIELDS = {"source_refs", "asset_refs"}


class MilvusBM25Index(BM25Index):
    """基于 Milvus 原生 BM25 Function 的 BM25Index 实现。

    稀疏向量由 BM25 Function 从 content 字段自动生成，
    检索时直接传入原始查询文本，无需手动编码。
    """

    def __init__(self, manager: MilvusCollectionManager | None = None) -> None:
        """初始化 BM25 索引，可注入共享的 MilvusCollectionManager。"""
        self._manager = manager or MilvusCollectionManager()

    @property
    def manager(self) -> MilvusCollectionManager:
        """获取内部的 MilvusCollectionManager 实例。"""
        return self._manager

    def add(
        self,
        chunk_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None:
        """添加单条 BM25 索引（转为批量调用）。"""
        self.add_batch([(chunk_id, text, metadata)])

    def add_batch(
        self,
        items: list[tuple[str, str, dict | None]],
    ) -> None:
        """批量写入 content + 标量字段，BM25 Function 自动生成 sparse_vector。"""
        if not items:
            return

        self._manager.ensure_collection()
        fields_items = []
        for chunk_id, text, metadata in items:
            meta = metadata or {}
            fields = {
                "doc_id": str(meta.get("doc_id", "")),
                "doc_title": str(meta.get("doc_title", ""))[:512],
                "title": str(meta.get("title", ""))[:512],
                "content": text[:65535],
                "category": str(meta.get("category", "")),
                "knowledge_type": str(meta.get("knowledge_type", "")),
                "status": str(meta.get("status", "active")),
            }
            for key in JSON_TEXT_FIELDS:
                fields[key] = _json_dumps(meta.get(key, {} if key == "metadata" else []))
            fields_items.append((chunk_id, fields))
        self._manager.upsert_fields_batch(fields_items)

    def delete(self, chunk_id: str) -> None:
        """删除指定知识块的 BM25 索引。"""
        self._manager.delete(chunk_id)

    def upsert_fields(self, chunk_id: str, fields: dict[str, Any]) -> None:
        """更新标量字段（如 status），不重建稀疏向量。"""
        self._manager.upsert_fields(chunk_id, fields)

    def upsert_fields_batch(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        """批量更新标量字段。"""
        self._manager.upsert_fields_batch(items)

    # 与 vector_index 共享同一 collection，检索 pipeline 实际使用的标量字段
    _SEARCH_OUTPUT_FIELDS = [
        "chunk_id", "doc_id", "doc_title", "title", "content", "category",
        "knowledge_type", "source_refs", "asset_refs",
    ]

    def search(
        self,
        query: str,
        top_k: int,
        categories: list[str] | None = None,
        knowledge_types: list[str] | None = None,
        doc_ids: list[str] | None = None,
        chunk_statuses: list[str] | None = None,
    ) -> list[tuple[str, float, dict]]:
        """BM25 关键词检索，直接传入原始查询文本。
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
            data=[query],
            anns_field="sparse_vector",
            param={"metric_type": "BM25", "params": {"ef": settings.milvus_sparse_ef}},
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
