"""解析元素仓储 — ParsedElement 的 PostgreSQL 持久化与查询。"""

import logging

from app.core.models import (
    AssetData,
    ElementType,
    ParsedElement,
    SourceLocation,
)
from app.db.models import DbParsedElement
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ParsedElementRepository(BaseRepository):
    """解析元素仓储 — 在 PostgreSQL 中持久化并查询 ParsedElement 记录。"""

    def _to_db(self, el: ParsedElement) -> DbParsedElement:
        """将领域模型 ParsedElement 转换为 ORM 对象 DbParsedElement。"""
        return DbParsedElement(
            element_id=el.element_id,
            doc_id=el.doc_id,
            doc_version=el.doc_version,
            parent_element_id=el.parent_element_id,
            sequence_order=el.sequence_order,
            element_type=el.element_type.value,
            text=el.text,
            structured_data=el.structured_data,
            asset_data=[ad.model_dump(mode="json") for ad in el.asset_data],
            source_location=el.source_location.model_dump(mode="json"),
            created_at=el.created_at,
            meta=el.metadata,
        )

    def _from_db(self, db_el: DbParsedElement) -> ParsedElement:
        """将 ORM 对象 DbParsedElement 还原为领域模型 ParsedElement。"""
        raw_assets = db_el.asset_data or []
        return ParsedElement(
            element_id=db_el.element_id,
            doc_id=db_el.doc_id,
            doc_version=db_el.doc_version,
            parent_element_id=db_el.parent_element_id,
            sequence_order=db_el.sequence_order,
            element_type=ElementType(db_el.element_type),
            text=db_el.text,
            structured_data=db_el.structured_data,
            asset_data=[AssetData(**raw) for raw in raw_assets],
            source_location=SourceLocation.model_validate(db_el.source_location or {}),
            created_at=db_el.created_at,
            metadata=db_el.meta or {},
        )

    def create_batch(self, elements: list[ParsedElement]) -> list[ParsedElement]:
        """批量写入解析元素（入库场景全新建，使用 bulk_save_objects 单次 INSERT）。

        前提：pipeline 中 _cleanup_previous_artifacts 已调用 delete_by_doc_id 清空旧数据。
        """
        if not elements:
            return elements
        with self._session() as session:
            db_objs = [self._to_db(el) for el in elements]
            session.bulk_save_objects(db_objs)
            session.commit()
            return elements

    def get_by_doc_id(self, doc_id: str) -> list[ParsedElement]:
        """按文档 ID 查询所有解析元素，按 sequence_order 升序返回。"""
        with self._session() as session:
            db_els = (
                session.query(DbParsedElement)
                .filter_by(doc_id=doc_id)
                .order_by(DbParsedElement.sequence_order)
                .all()
            )
            return [self._from_db(db_el) for db_el in db_els]

    def delete_by_doc_id(self, doc_id: str) -> int:
        """物理删除指定文档的全部解析元素，并返回删除数量。"""
        with self._session() as session:
            deleted = (
                session.query(DbParsedElement)
                .filter_by(doc_id=doc_id)
                .delete(synchronize_session=False)
            )
            session.commit()
            return int(deleted)
