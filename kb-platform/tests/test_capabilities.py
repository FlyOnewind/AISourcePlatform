"""能力检索/调用/权限过滤测试，对应 PRD 4.1 验收标准。"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_api_key
from app.models.agent import Agent
from app.models.capability import Capability
from app.models.policy import Policy


async def _create_agent(db_session: AsyncSession, agent_key: str, role: str, domain: str | None = None) -> str:
    api_key = generate_api_key("agent")
    agent = Agent(agent_key=agent_key, name=agent_key, role=role, business_domain=domain, status="active", api_key=api_key, is_master=(role == "master_agent"))
    db_session.add(agent)
    await db_session.commit()
    return api_key


async def _create_capability(db_session: AsyncSession, key: str, cap_type: str, domain: str, allowed_roles: list[str] | None = None) -> Capability:
    cap = Capability(
        capability_key=key, type=cap_type, name=key, description=f"desc for {key}", business_domain=domain,
        tags=[domain], input_schema={"query": "string"}, output_schema={"result": "string"},
        security_level="internal", owner_department="test_dept", allowed_agent_roles=allowed_roles or [],
        status="published", current_version="1.0.0", ref_id="tool_forbidden_word_check" if cap_type == "tool" else key,
    )
    db_session.add(cap)
    await db_session.commit()
    await db_session.refresh(cap)
    return cap


async def _grant_policy(db_session: AsyncSession, policy_key: str, roles: list[str], domains: list[str]) -> None:
    """默认拒绝策略下（文档07"越权防护"），测试需显式授予策略才能检索/调用能力，
    与 seed_data.py 中真实的 domain_policies 写法保持一致。"""
    db_session.add(
        Policy(
            policy_key=policy_key, name=policy_key, effect="allow",
            subject={"agent_role": roles}, resource={"business_domain": domains},
            actions=["search", "invoke"], conditions={}, status="active",
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_search_capabilities_returns_results(client: AsyncClient, db_session: AsyncSession):
    agent_key = await _create_agent(db_session, "op_1", "operation_agent", "operation")
    await _create_capability(db_session, "cap_live_script", "skill", "operation")
    await _grant_policy(db_session, "policy_op_1", ["operation_agent"], ["operation"])

    resp = await client.post(
        "/api/v1/capabilities/search",
        json={"task": "生成门店直播脚本", "keywords": ["直播"], "top_k": 5},
        headers={"X-API-Key": agent_key},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["trace_id"]
    assert len(data["capabilities"]) >= 1


@pytest.mark.asyncio
async def test_different_roles_get_different_results(client: AsyncClient, db_session: AsyncSession):
    """对应 PRD 验收标准：不同Agent角色获得的能力结果不同。"""
    op_key = await _create_agent(db_session, "op_2", "operation_agent", "operation")
    fin_key = await _create_agent(db_session, "fin_2", "finance_agent", "finance")

    await _create_capability(db_session, "cap_op_only", "skill", "operation", allowed_roles=["operation_agent"])
    await _create_capability(db_session, "cap_fin_only", "skill", "finance", allowed_roles=["finance_agent"])
    await _grant_policy(db_session, "policy_op_2", ["operation_agent"], ["operation"])
    await _grant_policy(db_session, "policy_fin_2", ["finance_agent"], ["finance"])

    # finance域没有对operation_agent开放的policy，operation_agent搜不到finance能力
    op_resp = await client.post(
        "/api/v1/capabilities/search", json={"task": "任意任务", "top_k": 10}, headers={"X-API-Key": op_key}
    )
    fin_resp = await client.post(
        "/api/v1/capabilities/search", json={"task": "任意任务", "top_k": 10}, headers={"X-API-Key": fin_key}
    )
    op_keys = {c["capability_key"] for c in op_resp.json()["data"]["capabilities"]}
    fin_keys = {c["capability_key"] for c in fin_resp.json()["data"]["capabilities"]}
    assert op_keys != fin_keys


@pytest.mark.asyncio
async def test_invoke_tool_capability(client: AsyncClient, db_session: AsyncSession):
    admin_key = await _create_agent(db_session, "master_1", "master_agent")
    cap = await _create_capability(db_session, "tool_forbidden_word_check", "tool", "compliance")

    resp = await client.post(
        f"/api/v1/capabilities/{cap.id}/invoke",
        json={"input": {"text": "本产品绝对安全，根治百病"}},
        headers={"X-API-Key": admin_key},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["success"] is True
    assert body["output"]["passed"] is False
    assert body["output"]["risk_level"] in ("medium", "high")


@pytest.mark.asyncio
async def test_invoke_capability_forbidden_role(client: AsyncClient, db_session: AsyncSession):
    op_key = await _create_agent(db_session, "op_3", "operation_agent", "operation")
    cap = await _create_capability(db_session, "cap_finance_only", "skill", "finance", allowed_roles=["finance_agent"])

    resp = await client.post(
        f"/api/v1/capabilities/{cap.id}/invoke", json={"input": {}}, headers={"X-API-Key": op_key}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_invoke_nonexistent_capability(client: AsyncClient, db_session: AsyncSession):
    master_key = await _create_agent(db_session, "master_2", "master_agent")
    resp = await client.post(
        "/api/v1/capabilities/00000000-0000-0000-0000-000000000000/invoke",
        json={"input": {}},
        headers={"X-API-Key": master_key},
    )
    assert resp.status_code == 404
