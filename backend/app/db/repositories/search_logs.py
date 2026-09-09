"""搜索日志仓储 — 搜索请求记录的写入操作。"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.models import DbSearchLog
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class SearchLogRepository(BaseRepository):
    """搜索日志仓储，提供搜索请求记录的创建操作。

    搜索日志为只写不读，仅提供 create 方法。后续如需统计分析，
    可直接通过 SQL 或 BI 工具查询 search_logs 表。
    """

    def create(self, log: DbSearchLog) -> DbSearchLog:
        """创建搜索日志记录。"""
        with self._session() as session:
            session: Session
            session.add(log)
            session.commit()
            return log
