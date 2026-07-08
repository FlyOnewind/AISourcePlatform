"""RBAC/ABAC 策略评估，对应文档07 第2节。

策略结构：{subject, resource, actions, conditions, effect}。
评估规则：
- 若不存在任何匹配 resource+action 的策略 -> 默认拒绝（安全优先，符合文档07"越权防护"）。
- 若存在匹配的 deny 策略 -> 拒绝（deny 优先于 allow）。
- 若存在匹配的 allow 策略且无 deny 命中 -> 允许。
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy


@dataclass
class Subject:
    agent_role: str
    business_domain: str | None = None
    department: str | None = None


@dataclass
class Resource:
    capability_type: str
    business_domain: str | None = None
    security_level: str = "internal"


def _match_list_field(policy_value: Any, actual: str | None) -> bool:
    """policy_value 可以是 None(不限制)、字符串、或字符串列表。"""
    if policy_value is None:
        return True
    if actual is None:
        return False
    if isinstance(policy_value, list):
        return actual in policy_value
    return policy_value == actual


def _match_subject(policy_subject: dict, subject: Subject) -> bool:
    if "agent_role" in policy_subject and not _match_list_field(policy_subject["agent_role"], subject.agent_role):
        return False
    if "department" in policy_subject and not _match_list_field(policy_subject["department"], subject.department):
        return False
    return True


def _match_resource(policy_resource: dict, resource: Resource) -> bool:
    if "capability_type" in policy_resource and not _match_list_field(
        policy_resource["capability_type"], resource.capability_type
    ):
        return False
    if "business_domain" in policy_resource and not _match_list_field(
        policy_resource["business_domain"], resource.business_domain
    ):
        return False
    if "security_level" in policy_resource and not _match_list_field(
        policy_resource["security_level"], resource.security_level
    ):
        return False
    return True


def _match_conditions(policy_conditions: dict, context: dict) -> bool:
    if not policy_conditions:
        return True
    for key, expected in policy_conditions.items():
        actual = context.get(key)
        if not _match_list_field(expected, actual):
            return False
    return True


class PolicyService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _load_active_policies(self) -> list[Policy]:
        result = await self._db.execute(select(Policy).where(Policy.status == "active"))
        return list(result.scalars().all())

    async def evaluate(
        self,
        subject: Subject,
        resource: Resource,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """返回 (是否允许, 原因)。master_agent 角色默认放行（主控Agent可跨域发现能力），
        其余按策略表评估，无命中策略默认拒绝。"""
        if subject.agent_role == "master_agent":
            return True, "master_agent 默认放行"

        context = context or {}
        policies = await self._load_active_policies()
        matched_allow = False
        for policy in policies:
            if action not in (policy.actions or []):
                continue
            if not _match_subject(policy.subject, subject):
                continue
            if not _match_resource(policy.resource, resource):
                continue
            if not _match_conditions(policy.conditions, context):
                continue
            if policy.effect == "deny":
                return False, f"命中拒绝策略 {policy.policy_key}"
            if policy.effect == "allow":
                matched_allow = True

        if matched_allow:
            return True, "命中允许策略"
        return False, "无匹配策略，默认拒绝"
