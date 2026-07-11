#!/usr/bin/env python
"""
数据库数据验证脚本
注意: 需要数据库实际连接才能运行此脚本
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def verify_database():
    """验证数据库中的数据"""
    print("="*60)
    print("数据库数据验证")
    print("="*60)

    try:
        from sqlalchemy import select, func
        from app.core.db import AsyncSessionLocal
        from app.models.agent import Agent
        from app.models.capability import Capability
        from app.models.knowledge import KnowledgeBase, Document
        from app.models.skill import Skill, PromptTemplate

        print("\n[1/6] 连接数据库...")
        async with AsyncSessionLocal() as db:
            print("  OK 数据库已连接")

            # 检查 Agents
            print("\n[2/6] 检查 Agents...")
            result = await db.execute(select(func.count(Agent.id)))
            agent_count = result.scalar()
            print(f"  Agent 总数: {agent_count}")

            if agent_count > 0:
                agents = await db.execute(select(Agent))
                for agent in agents.scalars().all():
                    print(f"    - {agent.name} ({agent.agent_key})")

            # 检查 Capabilities
            print("\n[3/6] 检查 Capabilities...")
            result = await db.execute(select(func.count(Capability.id)))
            cap_count = result.scalar()
            print(f"  Capability 总数: {cap_count}")

            # 按类型分组
            types = ["knowledge_base", "tool", "skill", "prompt", "agent", "workflow"]
            for type_name in types:
                result = await db.execute(
                    select(func.count(Capability.id)).where(Capability.type == type_name)
                )
                count = result.scalar()
                if count > 0:
                    print(f"    - {type_name}: {count}")

            # 检查 Tools
            print("\n[4/6] 检查 Tools...")
            result = await db.execute(
                select(Capability).where(Capability.type == "tool")
            )
            tools = result.scalars().all()
            print(f"  Tool 总数: {len(tools)}")
            for tool in tools:
                print(f"    - {tool.name} ({tool.capability_key})")

            # 检查 Knowledge Bases
            print("\n[5/6] 检查 Knowledge Bases...")
            result = await db.execute(select(func.count(KnowledgeBase.id)))
            kb_count = result.scalar()
            print(f"  Knowledge Base 总数: {kb_count}")

            result = await db.execute(select(func.count(Document.id)))
            doc_count = result.scalar()
            print(f"  Document 总数: {doc_count}")

            # 检查 Skills
            print("\n[6/6] 检查 Skills & Prompts...")
            result = await db.execute(select(func.count(Skill.id)))
            skill_count = result.scalar()
            print(f"  Skill 总数: {skill_count}")

            result = await db.execute(select(func.count(PromptTemplate.id)))
            prompt_count = result.scalar()
            print(f"  Prompt 总数: {prompt_count}")

            print("\n" + "="*60)
            print("验证完成!")
            print("="*60)

            return True

    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(verify_database())
    sys.exit(0 if success else 1)
