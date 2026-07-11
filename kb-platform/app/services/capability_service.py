"""能力注册中心核心服务：检索、调用分发，对应文档03。"""
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.capability import Capability
from app.models.knowledge import KnowledgeBase
from app.models.skill import PromptTemplate, Skill
from app.services.capability_permission_service import CapabilityPermissionService
from app.services.llm.base import LLMProvider
from app.services.policy_service import PolicyService, Resource, Subject
from app.services.prompt_service import PromptRenderError, render_prompt
from app.services.skill_runtime import SkillExecutionError, SkillRuntime
from app.services.tools import ToolRegistry, create_tool_executor

CAPABILITY_TYPE_ORDER = {"knowledge_base": 0, "tool": 1, "skill": 2, "prompt": 3, "agent": 4, "workflow": 5}


class CapabilityNotFoundError(ValueError):
    pass


class CapabilityForbiddenError(PermissionError):
    pass


class CapabilityService:
    def __init__(self, db: AsyncSession, llm: LLMProvider) -> None:
        self._db = db
        self._llm = llm
        self._policy = PolicyService(db)
        self._capability_permissions = CapabilityPermissionService(db)

    async def _visible_capabilities(self, requester: Subject) -> list[Capability]:
        result = await self._db.execute(select(Capability).where(Capability.status.in_(["published", "gray"])))
        capabilities = list(result.scalars().all())
        visible = []
        for cap in capabilities:
            if cap.allowed_agent_roles and requester.agent_role not in cap.allowed_agent_roles and requester.agent_role != "master_agent":
                continue
            perm_subject = CapabilityPermissionService.from_role(requester.agent_role, requester.business_domain, requester.department)
            perm_allowed, perm_reason = await self._capability_permissions.evaluate(perm_subject, cap, "discover")
            if perm_allowed is False:
                continue
            if perm_allowed is True:
                visible.append(cap)
                continue
            allowed, _ = await self._policy.evaluate(
                requester,
                Resource(capability_type=cap.type, business_domain=cap.business_domain, security_level=cap.security_level),
                "search",
            )
            if allowed:
                visible.append(cap)
        return visible

    async def search(
        self,
        requester: Subject,
        task: str,
        keywords: list[str],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[tuple[Capability, float, str]], list[Capability]]:
        """返回 (打分排序后的[能力,分数,推荐理由], 全部可见能力) 供路由层拼装响应。"""
        filters = filters or {}
        visible = await self._visible_capabilities(requester)

        domain_filter = filters.get("business_domain")
        if domain_filter:
            allowed_domains = domain_filter if isinstance(domain_filter, list) else [domain_filter]
            visible = [c for c in visible if c.business_domain in allowed_domains]

        query_text = f"{task} {' '.join(keywords)}"
        query_vec = (await self._llm.embed([query_text]))[0]
        cap_texts = [f"{c.name} {c.description or ''} {' '.join(c.tags)}" for c in visible]
        cap_vecs = await self._llm.embed(cap_texts) if cap_texts else []

        scored = []
        for cap, vec in zip(visible, cap_vecs, strict=False):
            tag_hits = sum(1 for kw in keywords if kw in (cap.tags or []) or kw in (cap.name + (cap.description or "")))
            vec_score = sum(a * b for a, b in zip(query_vec, vec, strict=False))
            score = max(0.0, min(1.0, 0.6 * vec_score + 0.4 * min(1.0, tag_hits * 0.3)))
            reason = f"任务描述与该能力标签/语义匹配度较高" if tag_hits == 0 else f"命中关键标签 {tag_hits} 个"
            scored.append((cap, round(score, 4), reason))

        scored.sort(key=lambda x: (-x[1], CAPABILITY_TYPE_ORDER.get(x[0].type, 9)))
        return scored[:top_k], visible

    async def get_capability(self, capability_id: str) -> Capability:
        result = await self._db.execute(select(Capability).where(Capability.id == capability_id))
        cap = result.scalar_one_or_none()
        if cap is None:
            raise CapabilityNotFoundError(f"能力不存在: {capability_id}")
        return cap

    async def invoke(
        self,
        requester: Subject,
        capability: Capability,
        input_data: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        """执行能力调用，返回 (output, latency_ms)。权限校验由调用方（路由层）提前完成并记录审计。"""
        started = time.perf_counter()

        if capability.type == "knowledge_base":
            output = await self._invoke_knowledge_base(capability, input_data)
        elif capability.type == "tool":
            output = await self._invoke_tool(capability, input_data)
        elif capability.type == "skill":
            output = await self._invoke_skill(capability, input_data, context)
        elif capability.type == "prompt":
            output = await self._invoke_prompt(capability, input_data)
        elif capability.type == "agent":
            output = await self._invoke_agent(capability, input_data)
        else:
            output = {"note": f"暂不支持的能力类型: {capability.type}"}

        latency_ms = int((time.perf_counter() - started) * 1000)
        return output, latency_ms

    async def _invoke_knowledge_base(self, capability: Capability, input_data: dict) -> dict:
        from app.services.retrieval_service import RetrievalService

        result = await self._db.execute(select(KnowledgeBase).where(KnowledgeBase.kb_key == capability.ref_id))
        kb = result.scalar_one_or_none()
        if kb is None:
            return {"error": f"关联知识库不存在: {capability.ref_id}"}
        retrieval = RetrievalService(self._db, self._llm)
        chunks = await retrieval.search(
            query=input_data.get("query", ""),
            kb_ids=[str(kb.id)],
            top_k=input_data.get("top_k", 5),
        )
        return {
            "chunks": [
                {"chunk_id": c.chunk_id, "content": c.content, "score": c.score, "doc_name": c.doc_name}
                for c in chunks
            ],
            "citations": [{"doc_name": c.doc_name, "chunk_id": c.chunk_id} for c in chunks],
            "confidence": chunks[0].score if chunks else 0.0,
        }

    async def _invoke_tool(self, capability: Capability, input_data: dict) -> dict:
        """通过工具注册框架统一调用工具实现。"""
        # 尝试使用已注册的工具实现
        tool_executor = create_tool_executor(capability)
        if tool_executor:
            try:
                return await tool_executor.execute(input_data)
            except Exception as e:
                return {"error": f"工具执行失败: {str(e)}", "capability_key": capability.capability_key}

        # 检查是否有 endpoint 配置进行远程调用
        if capability.endpoint:
            return await self._invoke_remote_tool(capability, input_data)

        # 对于示例工具，返回友好的 STUB 提示
        if capability.capability_key in ("tool_customer_segment", "tool_price_optimization"):
            return {
                "note": f"[示例工具] {capability.name} 需要外部端点配置",
                "capability_key": capability.capability_key,
                "status": "pending_external_endpoint",
                "echo": input_data,
            }

        return {"note": f"[STUB] 工具 {capability.capability_key} 暂无本地实现，返回占位结果", "echo": input_data}

    async def _invoke_remote_tool(self, capability: Capability, input_data: dict) -> dict:
        """调用远程工具端点（预留扩展）。"""
        # 这里可以实现 HTTP 调用远程工具的逻辑
        return {
            "note": f"[Remote Tool Stub] 工具 {capability.capability_key} 远程调用待实现",
            "endpoint": capability.endpoint,
            "echo": input_data,
        }

    async def _invoke_skill(self, capability: Capability, input_data: dict, context: dict) -> dict:
        result = await self._db.execute(select(Skill).where(Skill.skill_key == capability.ref_id))
        skill = result.scalar_one_or_none()
        if skill is None:
            return {"error": f"关联Skill不存在: {capability.ref_id}"}
        runtime = SkillRuntime(self._db, self._llm)
        try:
            return await runtime.execute(skill, input_data, context)
        except SkillExecutionError as exc:
            return {"error": str(exc)}

    async def _invoke_prompt(self, capability: Capability, input_data: dict) -> dict:
        result = await self._db.execute(select(PromptTemplate).where(PromptTemplate.prompt_key == capability.ref_id))
        prompt = result.scalar_one_or_none()
        if prompt is None:
            return {"error": f"关联Prompt不存在: {capability.ref_id}"}
        try:
            rendered = render_prompt(prompt, input_data.get("variables", input_data))
        except PromptRenderError as exc:
            return {"error": str(exc)}
        output_text = await self._llm.generate(rendered)
        return {"rendered": rendered, "output_text": output_text}

    async def _invoke_agent(self, capability: Capability, input_data: dict) -> dict:
        result = await self._db.execute(select(Agent).where(Agent.agent_key == capability.ref_id))
        agent = result.scalar_one_or_none()
        if agent is None:
            return {"error": f"关联Agent不存在: {capability.ref_id}"}
        if agent.status != "active":
            return {"error": f"Agent {agent.agent_key} 当前状态为 {agent.status}，不可调用"}
        # 本地演示环境中被调用的是同平台注册的存量Agent，没有真实外部端点时返回结构化 stub。
        return {
            "note": f"[STUB] 已路由至存量Agent {agent.name}（{agent.role}），本地演示未连接真实Agent端点",
            "agent_role": agent.role,
            "input_echo": input_data,
        }
