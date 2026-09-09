"""Repository 基类 — 提供 session 工厂注入与 session 上下文管理。"""

from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.db.engine import create_session_factory


class BaseRepository:
    """所有 PostgreSQL Repository 的基类。

    子类通过 ``self._session()`` 获取 SQLAlchemy session 上下文管理器，
    无需在每个方法中重复 ``with self._session_factory() as session:``。
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or create_session_factory()

    @contextmanager
    def _session(self) -> Session:  # type: ignore[valid-type]
        """获取一个事务边界的 SQLAlchemy session 上下文管理器。"""
        with self._session_factory() as session:
            yield session
