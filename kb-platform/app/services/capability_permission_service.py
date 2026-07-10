"""能力权限评估服务：优先检查 capability_permissions，再回退到旧 RBAC/ABAC 策略。"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.capability import Capability
from app.models.capability_permission import CapabilityPermission


@dataclass
class PermissionSubject:
    subject_type: str
    subject_code: str
    business_domain: str | None = None
    department: str | None = None


def _match_list_field(policy_value: Any, actual: str | None) -> bool:
    if policy_value is None:
        return True
    if actual is None:
        return False
    if isinstance(policy_value, list):
        return actual in policy_value
    return policy_value == actual


def _match_conditions(policy_conditions: dict, context: dict[str, Any]) -> bool:
    if not policy_conditions:
        return True
    for key, expected in policy_conditions.items():
        actual = context.get(key)
        if not _match_list_field(expected, actual):
            return False
    return True


class CapabilityPermissionService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def from_role(role: str, business_domain: str | None = None, department: str | None = None) -> PermissionSubject:
        return PermissionSubject(subject_type="role", subject_code=role, business_domain=business_domain, department=department)

    @staticmethod
    def from_identity(identity) -> PermissionSubject:
        subject_type = "agent" if identity.actor_type == "agent" else "user"
        return PermissionSubject(
            subject_type=subject_type,
            subject_code=identity.key,
            business_domain=identity.business_domain,
        )

    async def evaluate(
        self,
        subject: PermissionSubject,
        capability: Capability,
        permission: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool | None, str]:
        """返回 (允许/拒绝/无显式配置, 原因)。

        - True: 命中 capability_permissions 且允许
        - False: 存在显式权限配置，但当前 subject 不匹配
        - None: 当前 capability/permission 还没有配置显式权限，回退到旧策略
        """
        context = context or {}
        result = await self._db.execute(
            select(CapabilityPermission).where(
                CapabilityPermission.capability_id == capability.id,
                CapabilityPermission.permission == permission,
                CapabilityPermission.status == "active",
            )
        )
        permissions = list(result.scalars().all())
        if not permissions:
            return None, "未配置显式能力权限"

        for perm in permissions:
            if perm.subject_type != subject.subject_type:
                continue
            if perm.subject_code != subject.subject_code:
                continue
            if not _match_conditions(perm.conditions or {}, context):
                continue
            return True, f"命中能力权限 {perm.id}"

        return False, f"存在显式权限配置，但 {subject.subject_type}:{subject.subject_code} 不匹配"