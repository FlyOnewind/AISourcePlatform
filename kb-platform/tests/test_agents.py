"""Agent注册与鉴权测试。"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_api_key
from app.models.agent import AdminUser


async def _create_admin(db_session: AsyncSession) -> str:
    api_key = generate_api_key("admin")
    admin = AdminUser(username="test_admin", display_name="Test Admin", role="platform_admin", api_key=api_key, status="active")
    db_session.add(admin)
    await db_session.commit()
    return api_key


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_agent_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/agents", json={"agent_key": "a1", "name": "A1", "role": "operation_agent"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "401001"


@pytest.mark.asyncio
async def test_create_and_list_agent(client: AsyncClient, db_session: AsyncSession):
    admin_key = await _create_admin(db_session)
    resp = await client.post(
        "/api/v1/agents",
        json={"agent_key": "operation_agent_test", "name": "运营智能体", "role": "operation_agent", "business_domain": "operation"},
        headers={"X-API-Key": admin_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["agent_key"] == "operation_agent_test"
    assert body["data"]["api_key"]  # 创建时返回一次性 api_key

    list_resp = await client.get("/api/v1/agents", headers={"X-API-Key": admin_key})
    assert list_resp.status_code == 200
    agents = list_resp.json()["data"]
    assert any(a["agent_key"] == "operation_agent_test" for a in agents)
    # 列表接口不应回传 api_key
    assert all(a["api_key"] is None for a in agents)


@pytest.mark.asyncio
async def test_duplicate_agent_key_conflict(client: AsyncClient, db_session: AsyncSession):
    admin_key = await _create_admin(db_session)
    payload = {"agent_key": "dup_agent", "name": "A", "role": "operation_agent"}
    r1 = await client.post("/api/v1/agents", json=payload, headers={"X-API-Key": admin_key})
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/agents", json=payload, headers={"X-API-Key": admin_key})
    assert r2.status_code == 409
