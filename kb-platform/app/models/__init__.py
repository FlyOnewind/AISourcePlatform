"""集中导入所有模型，确保它们注册到 Base.metadata（供 create_all_tables 使用）。"""
from app.models.agent import AdminUser, Agent
from app.models.approval import ApprovalTicket
from app.models.audit import AuditLog
from app.models.asset import AssetCandidate, CollaborationTask
from app.models.capability import Capability, CapabilityVersion
from app.models.capability_permission import CapabilityPermission
from app.models.knowledge import Document, KnowledgeBase, KnowledgeChunk
from app.models.policy import Policy
from app.models.skill import PromptTemplate, Skill

__all__ = [
    "Agent",
    "AdminUser",
    "ApprovalTicket",
    "AuditLog",
    "AssetCandidate",
    "Capability",
    "CapabilityVersion",
    "CapabilityPermission",
    "CollaborationTask",
    "Document",
    "KnowledgeBase",
    "KnowledgeChunk",
    "Policy",
    "PromptTemplate",
    "Skill",
]
