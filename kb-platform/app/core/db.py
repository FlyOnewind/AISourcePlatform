"""数据库引擎与会话管理（SQLAlchemy 2.0 async）。

本轮不引入 Alembic：启动时通过 Base.metadata.create_all 建表，
后续 schema 稳定后再补迁移工具（见 README「后续待办」）。
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def create_all_tables() -> None:
    """Create tables for test and local helper workflows only."""
    # 必须在此处导入所有 models 模块，确保它们注册到 Base.metadata 上
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
