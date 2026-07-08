"""文档仓储 — Document 的 PostgreSQL 持久化与查询。

提供文档的 CRUD、分页过滤、去重、软删除/恢复、版本历史和聚合统计等功能。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.errors import DocumentNotFoundError, DuplicateDocumentError
from app.core.models import Document
from app.db.models import DbDocument
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class DocumentRepository(BaseRepository):
    """文档仓储 — 实现 PostgreSQL 下的 Document 持久化存储与查询。"""

    def _to_db(self, doc: Document) -> DbDocument:
        """将领域模型 Document 转换为 ORM 对象 DbDocument。"""
        return DbDocument(
            doc_id=doc.doc_id,
            title=doc.title,
            source_type=doc.source_type,
            source_uri=doc.source_uri,
            source_hash=doc.source_hash,
            version=doc.version,
            status=doc.status.value,
            category=doc.category,
            parent_doc_id=doc.parent_doc_id,
            root_doc_id=doc.root_doc_id,
            previous_doc_id=doc.previous_doc_id,
            error_message=doc.error_message,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            meta=doc.metadata,
        )

    def _from_db(self, db_doc: DbDocument) -> Document:
        """将 ORM 对象 DbDocument 还原为领域模型 Document。"""
        return Document(
            doc_id=db_doc.doc_id,
            title=db_doc.title,
            source_type=db_doc.source_type,
            source_uri=db_doc.source_uri,
            source_hash=db_doc.source_hash,
            version=db_doc.version,
            status=db_doc.status,
            category=db_doc.category,
            parent_doc_id=db_doc.parent_doc_id,
            root_doc_id=db_doc.root_doc_id,
            previous_doc_id=db_doc.previous_doc_id,
            error_message=db_doc.error_message,
            created_at=db_doc.created_at,
            updated_at=db_doc.updated_at,
            metadata=db_doc.meta or {},
        )

    def find_by_hash(
        self, source_hash: str, statuses: list[str] | None = None,
    ) -> Document | None:
        """按 source_hash 查找文档，用于去重检查。

        statuses 默认为 ["active", "processing"]，调用方可传入其他状态组合
        （如恢复时需同时检查 pending 文档）。
        """
        if not source_hash:
            return None
        if statuses is None:
            statuses = ["active", "processing"]
        with self._session() as session:
            db_doc = (
                session.query(DbDocument)
                .filter(DbDocument.source_hash == source_hash)
                .filter(DbDocument.status.in_(statuses))
                .first()
            )
            if db_doc is None:
                return None
            return self._from_db(db_doc)

    def create(self, doc: Document) -> Document:
        """创建新文档。先检查 doc_id 是否已存在，存在则抛出 DuplicateDocumentError。"""
        with self._session() as session:
            existing = session.get(DbDocument, doc.doc_id)
            if existing is not None:
                raise DuplicateDocumentError(
                    f"Document {doc.doc_id} already exists"
                )
            db_doc = self._to_db(doc)
            session.add(db_doc)
            session.commit()
            return self._from_db(db_doc)

    def get(self, doc_id: str) -> Document | None:
        with self._session() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                return None
            return self._from_db(db_doc)

    def get_batch(self, doc_ids: list[str]) -> dict[str, Document]:
        """批量加载文档，一次查询消除 N+1。

        Args:
            doc_ids: 文档 ID 列表。

        Returns:
            {doc_id: Document} 字典，不存在的 doc_id 不在 keys 中。
        """
        if not doc_ids:
            return {}
        with self._session() as session:
            rows = (
                session.query(DbDocument)
                .filter(DbDocument.doc_id.in_(doc_ids))
                .all()
            )
            return {row.doc_id: self._from_db(row) for row in rows}

    def update(self, doc: Document) -> Document:
        """更新文档字段。"""
        doc.updated_at = datetime.now(timezone.utc)
        with self._session() as session:
            db_doc = session.get(DbDocument, doc.doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"Document {doc.doc_id} not found")
            db_doc.title = doc.title
            db_doc.source_type = doc.source_type
            db_doc.source_uri = doc.source_uri
            db_doc.source_hash = doc.source_hash
            db_doc.version = doc.version
            db_doc.status = doc.status.value
            db_doc.category = doc.category
            db_doc.parent_doc_id = doc.parent_doc_id
            db_doc.root_doc_id = doc.root_doc_id
            db_doc.previous_doc_id = doc.previous_doc_id
            db_doc.error_message = doc.error_message
            db_doc.updated_at = doc.updated_at
            db_doc.meta = doc.metadata
            session.commit()
            result = self._from_db(db_doc)
            result.version = db_doc.version
            return result

    def touch_updated_at(self, doc_id: str) -> Document:
        """仅刷新文档更新时间，用于知识块写入等关联内容变化。"""
        with self._session() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"Document {doc_id} not found")
            db_doc.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._from_db(db_doc)

    def list(
        self,
        *,
        category: str | None = None,
        status: str | None = None,
        root_doc_id: str | None = None,
    ) -> list[Document]:
        with self._session() as session:
            query = session.query(DbDocument)
            if category is not None:
                query = query.filter_by(category=category)
            if status is not None:
                query = query.filter_by(status=status)
            if root_doc_id is not None:
                query = query.filter_by(root_doc_id=root_doc_id)
            return [self._from_db(db_doc) for db_doc in query.all()]

    # ── 扩展查询（2.1） ──────────────────────────────────────────

    def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        category: str | None = None,
        parent_doc_id: str | None = None,
        root_doc_id: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> tuple[list[Document], int]:
        """分页、关键词、多条件过滤查询文档列表。

        Returns:
            (文档列表, 总条数)
        """
        with self._session() as session:
            query = session.query(DbDocument)

            # ── 关键词搜索 ──
            if keyword:
                kw_pattern = f"%{keyword}%"
                from sqlalchemy import or_
                query = query.filter(
                    or_(
                        DbDocument.title.ilike(kw_pattern),
                        DbDocument.source_uri.ilike(kw_pattern),
                    )
                )

            # ── 条件过滤 ──
            if source_type is not None:
                query = query.filter_by(source_type=source_type)
            if status is not None:
                query = query.filter_by(status=status)
            if category is not None:
                query = query.filter_by(category=category)
            if parent_doc_id is not None:
                query = query.filter_by(parent_doc_id=parent_doc_id)
            if root_doc_id is not None:
                query = query.filter_by(root_doc_id=root_doc_id)

            # ── 总数 ──
            total = query.count()

            # ── 排序 ──
            sort_column = getattr(DbDocument, sort_by, DbDocument.updated_at)
            if sort_order == "asc":
                query = query.order_by(sort_column.asc())
            else:
                query = query.order_by(sort_column.desc())

            # ── 分页 ──
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)

            docs = [self._from_db(db_doc) for db_doc in query.all()]
            return docs, total

    # ── 软删除与恢复（2.2） ───────────────────────────────────────

    def soft_delete(self, doc_id: str) -> Document:
        """软删除文档，保存原状态到 meta.previous_status 供恢复时还原。

        Raises:
            DocumentNotFoundError: 文档不存在
        """
        with self._session() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"文档 {doc_id} 不存在")
            # 复制 JSONB 字典后再赋值，确保 SQLAlchemy 能检测到字段变更。
            meta = dict(db_doc.meta or {})
            meta["previous_status"] = db_doc.status
            db_doc.meta = meta
            db_doc.status = "deleted"
            db_doc.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._from_db(db_doc)

    def bulk_soft_delete(self, doc_ids: list[str]) -> int:
        """批量软删除文档，一条 UPDATE 完成。

        将指定文档的状态批量改为 deleted，保存原状态到 meta.previous_status。
        不存在的 doc_id 静默跳过。

        Returns:
            实际更新的文档数量。
        """
        if not doc_ids:
            return 0
        now = datetime.now(timezone.utc)
        with self._session() as session:
            # 逐条更新 — SQLAlchemy 批量 update 无法在 JSONB 字段中按行设不同值
            updated = 0
            for doc_id in doc_ids:
                db_doc = session.get(DbDocument, doc_id)
                if db_doc is None:
                    continue
                meta = dict(db_doc.meta or {})
                meta["previous_status"] = db_doc.status
                db_doc.meta = meta
                db_doc.status = "deleted"
                db_doc.updated_at = now
                updated += 1
            session.commit()
            return updated

    def hard_delete(self, doc_id: str) -> None:
        """物理删除文档记录，仅用于预占位回滚等内部场景。

        调用方必须确保该文档没有关联数据（知识块、解析元素、MinIO 文件等），
        否则会因外键约束删除失败或产生孤儿数据。

        Raises:
            DocumentNotFoundError: 文档不存在
        """
        with self._session() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"文档 {doc_id} 不存在")
            session.delete(db_doc)
            session.commit()

    def restore(self, doc_id: str) -> Document:
        """恢复软删除的文档到 active 状态（仅活跃文档删除后恢复使用）。

        failed / processing 文档的恢复由 API 层走 ingestion_pipeline.ingest()，
        不经过此方法。
        """
        with self._session() as session:
            db_doc = session.get(DbDocument, doc_id)
            if db_doc is None:
                raise DocumentNotFoundError(f"文档 {doc_id} 不存在")
            # 复制 JSONB 字典后再赋值，确保 previous_status 的删除会持久化。
            meta = dict(db_doc.meta or {})
            meta.pop("previous_status", None)  # 清除临时标记
            db_doc.status = "active"
            db_doc.meta = meta
            db_doc.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._from_db(db_doc)

    # ── 聚合统计 ────────────────────────────────────────────────

    def count_by_status(self, doc_id: str | None = None) -> dict[str, int]:
        """按状态统计文档数量。可选按 doc_id 精确计数。"""
        with self._session() as session:
            from sqlalchemy import func
            query = session.query(DbDocument.status, func.count(DbDocument.doc_id))
            if doc_id is not None:
                query = query.filter_by(doc_id=doc_id)
            query = query.group_by(DbDocument.status)
            return {status: count for status, count in query.all()}

    def get_stats(self, doc_id: str) -> dict:
        """获取单个文档的聚合统计信息。

        Returns:
            包含 chunk_count, element_count, asset_count 的字典。
            计数依赖关联仓储，若无关联仓储则返回 0。
        """
        stats = {"chunk_count": 0, "element_count": 0, "asset_count": 0}

        # 文档自身存在性校验
        doc = self.get(doc_id)
        if doc is None:
            return stats

        with self._session() as session:
            from app.db.models import DbAsset, DbKnowledgeChunk, DbParsedElement

            stats["chunk_count"] = (
                session.query(DbKnowledgeChunk)
                .filter(DbKnowledgeChunk.source_refs.contains([{"doc_id": doc_id}]))
                .count()
            )
            stats["element_count"] = (
                session.query(DbParsedElement)
                .filter_by(doc_id=doc_id)
                .count()
            )
            stats["asset_count"] = (
                session.query(DbAsset)
                .filter_by(doc_id=doc_id)
                .count()
            )

        return stats

    def find_similar_by_filename(self, filename: str) -> list[Document]:
        """查找同名的活跃文档。

        从 source_uri 中提取文件名进行匹配，返回状态为 active 的文档。
        """
        if not filename:
            return []

        from pathlib import Path
        target_name = Path(filename).name.lower()

        with self._session() as session:
            # 查询所有活跃文档，在内存中匹配文件名
            db_docs = (
                session.query(DbDocument)
                .filter(DbDocument.status == "active")
                .all()
            )

            matched = []
            for db_doc in db_docs:
                # 从 source_uri 中提取文件名
                doc_name = Path(db_doc.source_uri).name.lower()
                if doc_name == target_name:
                    matched.append(self._from_db(db_doc))

            return matched

    def get_version_history(self, doc_id: str) -> list[Document]:
        """获取文档的版本历史。

        通过 previous_doc_id 向前追溯，返回按时间倒序排列的版本列表。
        """
        # 首先获取当前文档
        current = self.get(doc_id)
        if not current:
            raise DocumentNotFoundError(f"文档 {doc_id} 不存在")

        history = [current]
        visited = {doc_id}

        # 向前追溯历史版本
        next_doc_id = current.previous_doc_id
        while next_doc_id and next_doc_id not in visited:
            prev_doc = self.get(next_doc_id)
            if not prev_doc:
                break
            history.append(prev_doc)
            visited.add(next_doc_id)
            next_doc_id = prev_doc.previous_doc_id

        # 按时间倒序排列（最新的在前）
        history.sort(key=lambda d: d.created_at, reverse=True)
        return history
