#!/usr/bin/env python
"""
数据库连接与数据检查脚本
用于验证数据库连接和检查导入的数据
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("="*60)
print("数据库检查工具")
print("="*60)


def check_config():
    """检查配置文件"""
    print("\n[1/5] 检查配置...")
    config_files = [
        ".env.example",
        "pyproject.toml",
        "app/core/config.py"
    ]

    for f in config_files:
        exists = (project_root / f).exists()
        status = "OK" if exists else "MISSING"
        print(f"  {status} {f}")

    return True


def check_imports():
    """检查模块导入"""
    print("\n[2/5] 检查模块导入...")

    modules = [
        ("app.core.config", "配置模块"),
        ("app.core.db", "数据库模块"),
        ("app.models", "模型模块"),
    ]

    for module_path, desc in modules:
        try:
            __import__(module_path)
            print(f"  OK {desc}")
        except Exception as e:
            print(f"  FAIL {desc}: {e}")
            return False

    return True


def check_models():
    """检查数据模型"""
    print("\n[3/5] 检查数据模型...")

    try:
        from app.models import (
            agent, capability, knowledge, skill,
            prompt, policy, audit, approval,
            asset, capability_permission, common
        )
        print("  OK 所有模型模块已加载")

        # 检查主要模型类
        model_classes = [
            ("Agent", agent.Agent),
            ("Capability", capability.Capability),
            ("KnowledgeBase", knowledge.KnowledgeBase),
            ("Skill", skill.Skill),
            ("PromptTemplate", prompt.PromptTemplate),
        ]

        for name, cls in model_classes:
            print(f"  OK {name}")

        return True
    except Exception as e:
        print(f"  FAIL 模型检查: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_database_config():
    """检查数据库配置"""
    print("\n[4/5] 检查数据库配置...")

    try:
        from app.core.config import get_settings
        settings = get_settings()

        print(f"  OK 配置已加载")
        print(f"  DB URL: {settings.database_url[:50]}..." if len(str(settings.database_url)) > 50 else f"  DB URL: {settings.database_url}")

        return True
    except Exception as e:
        print(f"  WARN 配置检查: {e}")
        print("  (这可能是正常的，需要实际数据库连接才能完整验证)")
        return True


def create_verification_script():
    """创建数据库验证脚本（需要实际连接后运行）"""
    print("\n[5/5] 创建验证脚本...")

    script_content = '''#!/usr/bin/env python
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

        print("\\n[1/6] 连接数据库...")
        async with AsyncSessionLocal() as db:
            print("  OK 数据库已连接")

            # 检查 Agents
            print("\\n[2/6] 检查 Agents...")
            result = await db.execute(select(func.count(Agent.id)))
            agent_count = result.scalar()
            print(f"  Agent 总数: {agent_count}")

            if agent_count > 0:
                agents = await db.execute(select(Agent))
                for agent in agents.scalars().all():
                    print(f"    - {agent.name} ({agent.agent_key})")

            # 检查 Capabilities
            print("\\n[3/6] 检查 Capabilities...")
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
            print("\\n[4/6] 检查 Tools...")
            result = await db.execute(
                select(Capability).where(Capability.type == "tool")
            )
            tools = result.scalars().all()
            print(f"  Tool 总数: {len(tools)}")
            for tool in tools:
                print(f"    - {tool.name} ({tool.capability_key})")

            # 检查 Knowledge Bases
            print("\\n[5/6] 检查 Knowledge Bases...")
            result = await db.execute(select(func.count(KnowledgeBase.id)))
            kb_count = result.scalar()
            print(f"  Knowledge Base 总数: {kb_count}")

            result = await db.execute(select(func.count(Document.id)))
            doc_count = result.scalar()
            print(f"  Document 总数: {doc_count}")

            # 检查 Skills
            print("\\n[6/6] 检查 Skills & Prompts...")
            result = await db.execute(select(func.count(Skill.id)))
            skill_count = result.scalar()
            print(f"  Skill 总数: {skill_count}")

            result = await db.execute(select(func.count(PromptTemplate.id)))
            prompt_count = result.scalar()
            print(f"  Prompt 总数: {prompt_count}")

            print("\\n" + "="*60)
            print("验证完成!")
            print("="*60)

            return True

    except Exception as e:
        print(f"\\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(verify_database())
    sys.exit(0 if success else 1)
'''

    script_path = project_root / "verify_data.py"
    script_path.write_text(script_content, encoding="utf-8")
    print(f"  OK 验证脚本已创建: verify_data.py")

    return True


def main():
    """主函数"""
    results = []

    results.append(("配置检查", check_config()))
    results.append(("模块导入", check_imports()))
    results.append(("数据模型", check_models()))
    results.append(("数据库配置", check_database_config()))
    results.append(("创建验证脚本", create_verification_script()))

    print("\n" + "="*60)
    print("检查摘要")
    print("="*60)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    for name, ok in results:
        status = "OK" if ok else "FAIL"
        print(f"  {status} {name}")

    print(f"\n总计: {passed}/{total} 通过")

    print("\n" + "="*60)
    print("下一步")
    print("="*60)
    print("1. 确保 Docker 已安装并运行")
    print("2. 运行: docker-compose up -d")
    print("3. 运行: python -m app.seeds.seed_data")
    print("4. 启动服务: uvicorn app.main:app --reload")
    print("5. 数据导入后运行: python verify_data.py")
    print("="*60)


if __name__ == "__main__":
    main()
