""" pytest 配置：使用同一个 Postgres 容器上的独立测试库 kbplatform_test。

需要先 `docker compose up -d postgres` 且 .env 中的 DATABASE_URL 可达。
每个测试函数结束后清空所有表数据，保证测试之间互不干扰。
"""
from collections.abc import AsyncGenerator

import asyncpg
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import db as db_module
from app.core.config import get_settings

settings = get_settings()


def _test_db_url(url: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/kbplatform_test"


def _admin_dsn(url: str) -> str:
    plain = url.replace("postgresql+asyncpg://", "postgresql://")
    base, _, _ = plain.rpartition("/")
    return f"{base}/postgres"


TEST_DATABASE_URL = _test_db_url(settings.database_url)

# 用测试引擎/会话工厂替换 app.core.db 的模块级对象，
# 所有依赖 get_db()/create_all_tables() 的代码在调用时会查到这里的替换值。
# 关键：必须用 NullPool —— pytest-asyncio 默认每个测试函数用独立事件循环，
# 而 asyncpg 连接绑定在创建它的事件循环上；用普通连接池会导致连接跨循环复用，
# 报 "cannot perform operation: another operation is in progress"。NullPool 每次都开新连接。
_test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
db_module.engine = _test_engine
db_module.AsyncSessionLocal = async_sessionmaker(_test_engine, expire_on_commit=False, class_=AsyncSession)


async def _ensure_test_database() -> None:
    conn = await asyncpg.connect(_admin_dsn(settings.database_url))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'kbplatform_test'")
        if not exists:
            await conn.execute("CREATE DATABASE kbplatform_test")
    finally:
        await conn.close()


@pytest_asyncio.fixture(autouse=True)
async def _setup_and_clean_db():
    await _ensure_test_database()
    from app import models  # noqa: F401

    async with db_module.engine.begin() as conn:
        await conn.run_sync(db_module.Base.metadata.create_all)

    yield

    async with db_module.engine.begin() as conn:
        for table in reversed(db_module.Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with db_module.AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
