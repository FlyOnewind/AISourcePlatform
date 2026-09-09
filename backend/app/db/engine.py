"""数据库引擎模块 — SQLAlchemy 引擎与会话工厂的惰性初始化。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings


_engine = None
_SessionFactory = None


def get_engine():
    """惰性获取 SQLAlchemy 引擎实例（首次调用时创建）。"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_size=5,
            echo=False,
        )
    return _engine


def create_session_factory() -> sessionmaker[Session]:
    """惰性创建绑定到引擎的 sessionmaker（autocommit=False, autoflush=False）。"""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionFactory
