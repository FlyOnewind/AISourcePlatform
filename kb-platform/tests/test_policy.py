"""RBAC/ABAC策略评估单元测试，对应文档07第2节和"越权防护"。"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy
from app.services.policy_service import PolicyService, Resource, Subject


@pytest.mark.asyncio
async def test_default_deny_without_matching_policy(db_session: AsyncSession):
    service = PolicyService(db_session)
    subject = Subject(agent_role="operation_agent")
    resource = Resource(capability_type="tool", business_domain="finance", security_level="confidential")
    allowed, reason = await service.evaluate(subject, resource, "invoke")
    assert allowed is False
    assert "默认拒绝" in reason


@pytest.mark.asyncio
async def test_master_agent_always_allowed(db_session: AsyncSession):
    service = PolicyService(db_session)
    subject = Subject(agent_role="master_agent")
    resource = Resource(capability_type="tool", business_domain="finance", security_level="restricted")
    allowed, _ = await service.evaluate(subject, resource, "invoke")
    assert allowed is True


@pytest.mark.asyncio
async def test_allow_policy_grants_access(db_session: AsyncSession):
    policy = Policy(
        policy_key="policy_finance_read", name="finance read", effect="allow",
        subject={"agent_role": ["finance_agent"]}, resource={"business_domain": "finance"},
        actions=["search", "invoke"], conditions={}, status="active",
    )
    db_session.add(policy)
    await db_session.commit()

    service = PolicyService(db_session)
    allowed, _ = await service.evaluate(
        Subject(agent_role="finance_agent"), Resource(capability_type="tool", business_domain="finance"), "invoke"
    )
    assert allowed is True

    denied, _ = await service.evaluate(
        Subject(agent_role="operation_agent"), Resource(capability_type="tool", business_domain="finance"), "invoke"
    )
    assert denied is False


@pytest.mark.asyncio
async def test_deny_policy_overrides_allow(db_session: AsyncSession):
    db_session.add_all([
        Policy(policy_key="allow_all_ops", name="allow", effect="allow", subject={"agent_role": ["operation_agent"]},
               resource={"business_domain": "operation"}, actions=["invoke"], conditions={}, status="active"),
        Policy(policy_key="deny_restricted", name="deny", effect="deny", subject={"agent_role": ["operation_agent"]},
               resource={"business_domain": "operation", "security_level": ["restricted"]}, actions=["invoke"], conditions={}, status="active"),
    ])
    await db_session.commit()

    service = PolicyService(db_session)
    allowed, _ = await service.evaluate(
        Subject(agent_role="operation_agent"),
        Resource(capability_type="tool", business_domain="operation", security_level="restricted"),
        "invoke",
    )
    assert allowed is False
