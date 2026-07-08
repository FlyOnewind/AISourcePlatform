"""知识块仓储 — KnowledgeChunk 的 PostgreSQL 持久化与查询。

提供知识块的 CRUD、分页过滤、批量状态更新、软删除/恢复等功能。
doc_id 不再作为独立列，改为通过 source_refs JSONB 中的 doc_id 查询。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, text

from app.core.models import (
    AssetRef,
    KnowledgeChunk,
    KnowledgeType,
    SourceRef,
    SourceLocation,
)
from app.db.models import DbKnowledgeChunk
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


def _source_refs_contains_doc(doc_id: str):
    """按 doc_id 列过滤，等价于 source_refs JSONB @> 查询但可用 B-tree 索引。"""
    return DbKnowledgeChunk.doc_id == doc_id


class PgChunkStore(BaseRepository):
    """知识块仓储 — 实现 PostgreSQL 下的 KnowledgeChunk 持久化存储。"""

    def _to_db(self, chunk: KnowledgeChunk) -> DbKnowledgeChunk:
        """将领域模型 KnowledgeChunk 转换为 ORM 对象 DbKnowledgeChunk。"""
        return DbKnowledgeChunk(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id or (chunk.source_refs[0].doc_id if chunk.source_refs else ""),
            title=chunk.title,
            content=chunk.content,
            content_hash=chunk.content_hash,
            knowledge_type=chunk.knowledge_type.value,
            category=chunk.category,
            status=chunk.status.value,
            asset_refs=[ref.model_dump(mode="json") for ref in chunk.asset_refs],
            source_refs=[ref.model_dump(mode="json") for ref in chunk.source_refs],
            created_at=chunk.created_at,
            updated_at=chunk.updated_at,
            meta=chunk.metadata,
        )

    def _from_db(self, db_chunk: DbKnowledgeChunk) -> KnowledgeChunk:
        """将 ORM 对象 DbKnowledgeChunk 还原为领域模型 KnowledgeChunk。"""
        asset_refs = []
        for raw in db_chunk.asset_refs or []:
            asset_refs.append(
                AssetRef(
                    asset_id=raw["asset_id"],
                    caption=raw.get("caption"),
                )
            )

        source_refs = []
        for raw in db_chunk.source_refs or []:
            source_refs.append(
                SourceRef(
                    doc_id=raw["doc_id"],
                    doc_version=raw.get("doc_version", 1),
                    element_id=raw["element_id"],
                    source_location=SourceLocation.model_validate(
                        raw.get("source_location") or {}
                    ),
                )
            )

        return KnowledgeChunk(
            chunk_id=db_chunk.chunk_id,
            doc_id=db_chunk.doc_id or "",
            title=db_chunk.title,
            content=db_chunk.content,
            content_hash=db_chunk.content_hash,
            knowledge_type=KnowledgeType(db_chunk.knowledge_type),
            category=db_chunk.category,
            status=db_chunk.status,
            asset_refs=asset_refs,
            source_refs=source_refs,
            created_at=db_chunk.created_at or datetime.now(timezone.utc),
            updated_at=db_chunk.updated_at or datetime.now(timezone.utc),
            metadata=db_chunk.meta or {},
        )

    def put(self, chunk: KnowledgeChunk) -> None:
        """保存知识块。已存在则更新（刷新 updated_at），不存在则新建。"""
        self.bulk_put([chunk])

    def bulk_put(self, chunks: list[KnowledgeChunk]) -> None:
        """批量保存知识块。一次查询 + 一次 commit，替代逐条 put 的 N 次往返。

        先批量查询已存在的 chunk_id，存在则原地更新字段，不存在则新建。
        """
        if not chunks:
            return
        with self._session() as session:
            chunk_ids = [c.chunk_id for c in chunks]
            existing_rows = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.chunk_id.in_(chunk_ids))
                .all()
            )
            existing_map = {row.chunk_id: row for row in existing_rows}

            now = datetime.now(timezone.utc)
            for chunk in chunks:
                row = existing_map.get(chunk.chunk_id)
                if row is not None:
                    # 更新已有记录
                    row.doc_id = chunk.doc_id or (chunk.source_refs[0].doc_id if chunk.source_refs else "")
                    row.title = chunk.title
                    row.content = chunk.content
                    row.content_hash = chunk.content_hash
                    row.knowledge_type = chunk.knowledge_type.value
                    row.category = chunk.category
                    row.status = chunk.status.value
                    row.asset_refs = [ref.model_dump(mode="json") for ref in chunk.asset_refs]
                    row.source_refs = [ref.model_dump(mode="json") for ref in chunk.source_refs]
                    row.updated_at = now
                    row.meta = chunk.metadata
                else:
                    session.add(self._to_db(chunk))
            session.commit()

    def get(self, chunk_id: str) -> KnowledgeChunk | None:
        with self._session() as session:
            db_chunk = session.get(DbKnowledgeChunk, chunk_id)
            if db_chunk is None:
                return None
            return self._from_db(db_chunk)

    def get_batch(self, chunk_ids: list[str]) -> list[KnowledgeChunk]:
        with self._session() as session:
            db_chunks = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.chunk_id.in_(chunk_ids))
                .all()
            )
            return [self._from_db(c) for c in db_chunks]

    def list_all(self, category: str | None = None) -> list[KnowledgeChunk]:
        with self._session() as session:
            query = session.query(DbKnowledgeChunk)
            if category is not None:
                query = query.filter_by(category=category)
            db_chunks = query.order_by(DbKnowledgeChunk.chunk_id).all()
            return [self._from_db(c) for c in db_chunks]

    def list_by_doc_id(self, doc_id: str) -> list[KnowledgeChunk]:
        """按文档 ID 查找所有知识块（通过 source_refs JSONB 查询）。"""
        with self._session() as session:
            db_chunks = (
                session.query(DbKnowledgeChunk)
                .filter(_source_refs_contains_doc(doc_id))
                .order_by(DbKnowledgeChunk.chunk_id)
                .all()
            )
            return [self._from_db(c) for c in db_chunks]

    def list_by_doc_ids(self, doc_ids: list[str]) -> list[KnowledgeChunk]:
        """按多个文档 ID 批量查找知识块，一次查询。"""
        if not doc_ids:
            return []
        with self._session() as session:
            db_chunks = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.doc_id.in_(doc_ids))
                .order_by(DbKnowledgeChunk.chunk_id)
                .all()
            )
            return [self._from_db(c) for c in db_chunks]

    def bulk_update_status_by_doc_id(self, doc_id: str, status: str) -> None:
        """将指定文档下所有 chunk 批量更新为目标状态。"""
        with self._session() as session:
            rows = (
                session.query(DbKnowledgeChunk)
                .filter(_source_refs_contains_doc(doc_id))
                .all()
            )
            for row in rows:
                row.status = status
            session.commit()

    def bulk_update_status_by_doc_ids(self, doc_ids: list[str], status: str) -> None:
        """批量更新多个文档下所有 chunk 的状态，一条 UPDATE。"""
        if not doc_ids:
            return
        with self._session() as session:
            session.query(DbKnowledgeChunk).filter(
                DbKnowledgeChunk.doc_id.in_(doc_ids)
            ).update({DbKnowledgeChunk.status: status}, synchronize_session=False)
            session.commit()

    def bulk_update_fields_by_doc_id(self, doc_id: str, fields: dict) -> list[KnowledgeChunk]:
        """批量更新指定文档下所有 chunk 的元数据字段，返回更新后的 chunk 列表。"""
        with self._session() as session:
            rows = (
                session.query(DbKnowledgeChunk)
                .filter(_source_refs_contains_doc(doc_id))
                .all()
            )
            for row in rows:
                for key, value in fields.items():
                    if hasattr(row, key):
                        setattr(row, key, value)
            session.commit()
        # 返回更新后的 domain 对象，供后续 Milvus 同步
        return self.list_by_doc_id(doc_id)

    def count(self) -> int:
        with self._session() as session:
            return session.query(DbKnowledgeChunk).count()

    # ── 扩展查询（2.3） ──────────────────────────────────────────

    def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        search_mode: str = "chunk_title",  # "chunk_title" | "doc_title"
        doc_id: str | None = None,
        source_type: str | None = None,
        category: str | None = None,
        knowledge_type: str | None = None,
        status: str | None = None,
        has_assets: bool | None = None,
        has_sources: bool | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[KnowledgeChunk], int]:
        """分页、关键词、多条件过滤查询知识块列表。

        search_mode:
            - "chunk_title": 关键词匹配知识块标题和内容（默认）
            - "doc_title": 关键词匹配来源文档标题（需 JOIN documents 表）

        doc_id 和 source_type 筛选通过 source_refs JSONB 或 JOIN documents 实现。

        Returns:
            (知识块列表, 总条数)
        """
        with self._session() as session:
            from app.db.models import DbDocument

            query = session.query(DbKnowledgeChunk)

            # ── 按文档标题搜索 / 按文档来源类型筛选需要 JOIN documents 表 ──
            # 通过 source_refs JSONB 中的 doc_id 提取并 JOIN
            need_join = (keyword and search_mode == "doc_title") or (source_type is not None) or (doc_id is not None and source_type is not None)
            if need_join:
                # 语义抽取保证同一知识块的首个 source_ref 指向所属文档。
                query = query.join(
                    DbDocument,
                    text("documents.doc_id = (knowledge_chunks.source_refs->0->>'doc_id')"),
                )

            # ── 关键词搜索 ──
            if keyword:
                kw_pattern = f"%{keyword}%"
                from sqlalchemy import or_
                if search_mode == "doc_title":
                    if not need_join:
                        # 延迟 JOIN
                        query = query.join(
                            DbDocument,
                            text("documents.doc_id = (knowledge_chunks.source_refs->0->>'doc_id')"),
                        )
                    query = query.filter(DbDocument.title.ilike(kw_pattern))
                else:
                    query = query.filter(
                        or_(
                            DbKnowledgeChunk.title.ilike(kw_pattern),
                            DbKnowledgeChunk.content.ilike(kw_pattern),
                        )
                    )

            # ── 条件过滤 ──
            if source_type is not None:
                query = query.filter(DbDocument.source_type == source_type)
            if doc_id is not None:
                query = query.filter(_source_refs_contains_doc(doc_id))
            if category is not None:
                query = query.filter(DbKnowledgeChunk.category == category)
            if knowledge_type is not None:
                query = query.filter(DbKnowledgeChunk.knowledge_type == knowledge_type)
            if status is not None:
                query = query.filter(DbKnowledgeChunk.status == status)

            # ── 有关联资源/来源过滤（JSON 数组非空） ──
            if has_assets is True:
                query = query.filter(
                    func.jsonb_array_length(DbKnowledgeChunk.asset_refs) > 0
                )
            elif has_assets is False:
                query = query.filter(
                    func.jsonb_array_length(DbKnowledgeChunk.asset_refs) == 0
                )

            if has_sources is True:
                query = query.filter(
                    func.jsonb_array_length(DbKnowledgeChunk.source_refs) > 0
                )
            elif has_sources is False:
                query = query.filter(
                    func.jsonb_array_length(DbKnowledgeChunk.source_refs) == 0
                )

            # ── 总数 ──
            total = query.count()

            # ── 排序 ──
            sort_column = getattr(DbKnowledgeChunk, sort_by, DbKnowledgeChunk.created_at)
            if sort_order == "asc":
                query = query.order_by(sort_column.asc())
            else:
                query = query.order_by(sort_column.desc())

            # ── 分页 ──
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)

            chunks = [self._from_db(c) for c in query.all()]
            return chunks, total

    # ── 批量状态更新（2.4） ───────────────────────────────────────

    def bulk_update_status_by_chunk_ids(
        self,
        chunk_ids: list[str],
        status: str,
    ) -> int:
        """按 chunk_id 列表批量更新业务状态。

        Returns:
            更新的行数
        """
        if not chunk_ids:
            return 0
        with self._session() as session:
            rows = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.chunk_id.in_(chunk_ids))
                .all()
            )
            for row in rows:
                row.status = status
            session.commit()
            return len(rows)

    # ── 软删除与恢复 ─────────────────────────────────────────────

    def soft_delete(self, chunk_id: str) -> KnowledgeChunk:
        """将知识块软删除。"""
        with self._session() as session:
            db_chunk = session.get(DbKnowledgeChunk, chunk_id)
            if db_chunk is None:
                return None
            db_chunk.status = "deleted"
            session.commit()
            return self._from_db(db_chunk)

    def hard_delete(self, chunk_id: str) -> None:
        """硬删除知识块（物理删除，用于重入库前清理旧块）。"""
        with self._session() as session:
            db_chunk = session.get(DbKnowledgeChunk, chunk_id)
            if db_chunk is not None:
                session.delete(db_chunk)
                session.commit()

    def bulk_hard_delete(self, chunk_ids: list[str]) -> None:
        """批量硬删除知识块，一条 DELETE 完成。

        用于重入库前清理旧块，避免逐条 session + commit 的开销。
        """
        if not chunk_ids:
            return
        with self._session() as session:
            session.query(DbKnowledgeChunk).filter(
                DbKnowledgeChunk.chunk_id.in_(chunk_ids)
            ).delete(synchronize_session=False)
            session.commit()

    def restore(self, chunk_id: str) -> KnowledgeChunk:
        """恢复软删除的知识块。"""
        with self._session() as session:
            db_chunk = session.get(DbKnowledgeChunk, chunk_id)
            if db_chunk is None:
                return None
            db_chunk.status = "active"
            session.commit()
            return self._from_db(db_chunk)

    def count_by_doc_id(self, doc_id: str) -> int:
        """统计某文档下的知识块数量（通过 source_refs JSONB 查询）。"""
        with self._session() as session:
            return (
                session.query(DbKnowledgeChunk)
                .filter(_source_refs_contains_doc(doc_id))
                .count()
            )

    def find_by_content_hash(self, content_hash: str, exclude_chunk_id: str = "") -> KnowledgeChunk | None:
        """按内容哈希查找知识块，用于重复内容检测。可排除指定 chunk_id。"""
        if not content_hash:
            return None
        with self._session() as session:
            query = session.query(DbKnowledgeChunk).filter_by(content_hash=content_hash)
            if exclude_chunk_id:
                query = query.filter(DbKnowledgeChunk.chunk_id != exclude_chunk_id)
            db_chunk = query.first()
            if db_chunk is None:
                return None
            return self._from_db(db_chunk)
