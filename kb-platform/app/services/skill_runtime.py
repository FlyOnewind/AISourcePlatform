"""Skill 执行引擎，对应文档05第5节执行流程与文档03 3.3 Skill类型。

支持类型：
- prompt_skill: 渲染 Prompt 后调用 LLM 生成。
- rag_skill: 先检索依赖知识库，再把片段拼进 Prompt 生成。
- tool_skill: 调用 dependencies 中声明的工具（当前内置 tool_forbidden_word_check）。
- workflow_skill: 依次执行 dependencies 列出的能力，将上一步输出作为下一步输入的补充上下文。
- agent_skill: 调用被依赖的存量 Agent（本地演示环境无真实外部端点，返回结构化 stub 并明确标注）。
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import PromptTemplate, Skill
from app.services.llm.base import LLMProvider
from app.services.prompt_service import render_prompt
from app.services.tools import ToolRegistry, create_tool_executor


class SkillExecutionError(ValueError):
    pass


class SkillRuntime:
    def __init__(self, db: AsyncSession, llm: LLMProvider) -> None:
        self._db = db
        self._llm = llm

    async def execute(self, skill: Skill, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if skill.type == "prompt_skill":
            return await self._run_prompt_skill(skill, input_data)
        if skill.type == "rag_skill":
            return await self._run_rag_skill(skill, input_data, context)
        if skill.type == "tool_skill":
            return await self._run_tool_skill(skill, input_data)
        if skill.type == "workflow_skill":
            return await self._run_workflow_skill(skill, input_data, context)
        if skill.type == "agent_skill":
            return await self._run_agent_skill(skill, input_data)
        raise SkillExecutionError(f"未知 Skill 类型: {skill.type}")

    async def _get_prompt(self, prompt_key: str) -> PromptTemplate:
        from sqlalchemy import select

        result = await self._db.execute(select(PromptTemplate).where(PromptTemplate.prompt_key == prompt_key))
        prompt = result.scalar_one_or_none()
        if prompt is None:
            raise SkillExecutionError(f"Skill 依赖的 Prompt 不存在: {prompt_key}")
        return prompt

    async def _run_prompt_skill(self, skill: Skill, input_data: dict) -> dict:
        if not skill.prompt_key:
            raise SkillExecutionError("prompt_skill 缺少 prompt_key 配置")
        prompt = await self._get_prompt(skill.prompt_key)
        rendered = render_prompt(prompt, input_data)
        output_text = await self._llm.generate(rendered)
        return {"output_text": output_text, "used_prompt": skill.prompt_key, "prompt_version": prompt.version}

    async def _run_rag_skill(self, skill: Skill, input_data: dict, context: dict) -> dict:
        from app.services.retrieval_service import RetrievalService

        query = input_data.get("query") or input_data.get("task") or ""
        kb_deps = [d for d in (skill.dependencies or []) if d.startswith("kb_")]
        retrieval = RetrievalService(self._db, self._llm)
        chunks = await retrieval.search(query=query, kb_ids=None, top_k=5) if query else []
        # 用依赖标签在描述中体现，便于演示可解释性
        context_text = "\n".join(f"[{c.doc_name}] {c.content[:200]}" for c in chunks)
        prompt = f"参考资料：\n{context_text}\n\n任务：{query}\n请基于参考资料生成结果。"
        output_text = await self._llm.generate(prompt)
        return {
            "output_text": output_text,
            "citations": [{"doc_name": c.doc_name, "chunk_id": c.chunk_id, "score": c.score} for c in chunks],
            "kb_dependencies": kb_deps,
        }

    async def _run_tool_skill(self, skill: Skill, input_data: dict) -> dict:
        """通过工具注册框架执行工具技能。"""
        tool_deps = [d for d in (skill.dependencies or []) if d.startswith("tool_")]
        if not tool_deps:
            return {
                "output_text": "[Tool Skill] 未指定工具依赖",
                "tool_dependencies": [],
            }

        # 获取数据库会话来加载 capability
        from sqlalchemy import select
        from app.models.capability import Capability

        results = []
        for tool_key in tool_deps:
            # 加载 capability
            result = await self._db.execute(
                select(Capability).where(Capability.capability_key == tool_key)
            )
            capability = result.scalar_one_or_none()

            if capability:
                # 尝试使用已注册的工具实现
                tool_executor = create_tool_executor(capability)
                if tool_executor:
                    tool_result = await tool_executor.execute(input_data)
                    results.append({
                        "tool": tool_key,
                        "result": tool_result,
                        "status": "executed",
                    })
                    continue

            # 向后兼容：如果没有找到注册的实现，使用旧方式
            if tool_key == "tool_forbidden_word_check":
                from app.services.tools.forbidden_word_check import check_forbidden_words
                text = input_data.get("text") or input_data.get("script") or ""
                results.append({
                    "tool": tool_key,
                    "result": check_forbidden_words(text),
                    "status": "legacy_fallback",
                })
                continue

            # 其他工具返回 STUB
            results.append({
                "tool": tool_key,
                "result": {"note": f"工具 {tool_key} 暂未实现"},
                "status": "stub",
            })

        if len(results) == 1:
            return {
                "tool_result": results[0]["result"],
                "tool": results[0]["tool"],
                "status": results[0]["status"],
            }

        return {
            "output_text": f"已执行 {len(results)} 个工具",
            "tool_dependencies": tool_deps,
            "results": results,
        }

    async def _run_workflow_skill(self, skill: Skill, input_data: dict, context: dict) -> dict:
        """执行工作流技能，支持多种依赖类型。"""
        from sqlalchemy import select
        from app.models.capability import Capability
        from app.services.retrieval_service import RetrievalService

        steps_result = []
        accumulated_context = dict(input_data)

        for dep_key in skill.dependencies or []:
            if dep_key.startswith("kb_"):
                retrieval = RetrievalService(self._db, self._llm)
                query = accumulated_context.get("query") or accumulated_context.get("task") or ""
                chunks = await retrieval.search(query=query, kb_ids=None, top_k=3)
                steps_result.append({"step": dep_key, "type": "knowledge", "hits": len(chunks)})

            elif dep_key.startswith("tool_"):
                # 通过工具注册框架执行
                result = await self._execute_workflow_tool(dep_key, accumulated_context)
                steps_result.append({"step": dep_key, "type": "tool", "result": result})

            else:
                steps_result.append({"step": dep_key, "type": "unresolved"})

        summary_prompt = (
            f"工作流 {skill.name} 执行步骤：{steps_result}\n输入：{input_data}\n请生成综合结果。"
        )
        output_text = await self._llm.generate(summary_prompt)
        return {"output_text": output_text, "steps": steps_result}

    async def _execute_workflow_tool(self, tool_key: str, input_data: dict) -> dict:
        """在工作流中执行单个工具。"""
        from sqlalchemy import select
        from app.models.capability import Capability

        result = await self._db.execute(
            select(Capability).where(Capability.capability_key == tool_key)
        )
        capability = result.scalar_one_or_none()

        if capability:
            tool_executor = create_tool_executor(capability)
            if tool_executor:
                return await tool_executor.execute(input_data)

        # 向后兼容
        if tool_key == "tool_forbidden_word_check":
            from app.services.tools.forbidden_word_check import check_forbidden_words
            text = input_data.get("text") or input_data.get("script") or ""
            return check_forbidden_words(text)

        return {"note": f"工具 {tool_key} 暂未实现"}

    async def _run_agent_skill(self, skill: Skill, input_data: dict) -> dict:
        agent_deps = [d for d in (skill.dependencies or []) if d.startswith("agent_")]
        return {
            "output_text": f"[STUB] agent_skill 调用了存量Agent {agent_deps}（本地演示环境无真实外部Agent端点）",
            "agent_dependencies": agent_deps,
            "input_echo": input_data,
        }
