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
from app.services.tools.forbidden_word_check import check_forbidden_words


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
        tool_deps = [d for d in (skill.dependencies or []) if d.startswith("tool_")]
        if "tool_forbidden_word_check" in tool_deps:
            text = input_data.get("text") or input_data.get("script") or ""
            return {"tool_result": check_forbidden_words(text), "tool": "tool_forbidden_word_check"}
        return {
            "output_text": f"[MOCK TOOL] 未实现工具依赖 {tool_deps}，返回占位结果",
            "tool_dependencies": tool_deps,
        }

    async def _run_workflow_skill(self, skill: Skill, input_data: dict, context: dict) -> dict:
        steps_result = []
        accumulated_context = dict(input_data)
        for dep_key in skill.dependencies or []:
            if dep_key.startswith("kb_"):
                from app.services.retrieval_service import RetrievalService

                retrieval = RetrievalService(self._db, self._llm)
                query = accumulated_context.get("query") or accumulated_context.get("task") or ""
                chunks = await retrieval.search(query=query, kb_ids=None, top_k=3)
                steps_result.append({"step": dep_key, "type": "knowledge", "hits": len(chunks)})
            elif dep_key.startswith("tool_"):
                text = accumulated_context.get("text") or accumulated_context.get("script") or ""
                if dep_key == "tool_forbidden_word_check":
                    result = check_forbidden_words(text)
                    steps_result.append({"step": dep_key, "type": "tool", "result": result})
            else:
                steps_result.append({"step": dep_key, "type": "unresolved"})

        summary_prompt = (
            f"工作流 {skill.name} 执行步骤：{steps_result}\n输入：{input_data}\n请生成综合结果。"
        )
        output_text = await self._llm.generate(summary_prompt)
        return {"output_text": output_text, "steps": steps_result}

    async def _run_agent_skill(self, skill: Skill, input_data: dict) -> dict:
        agent_deps = [d for d in (skill.dependencies or []) if d.startswith("agent_")]
        return {
            "output_text": f"[STUB] agent_skill 调用了存量Agent {agent_deps}（本地演示环境无真实外部Agent端点）",
            "agent_dependencies": agent_deps,
            "input_echo": input_data,
        }
