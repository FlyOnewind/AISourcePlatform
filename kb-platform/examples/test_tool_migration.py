#!/usr/bin/env python
"""测试工具迁移是否成功。"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_tool_imports():
    """测试工具模块导入是否正常。"""
    print("=" * 60)
    print("测试 1: 工具模块导入")
    print("=" * 60)

    try:
        from app.services.tools import ToolRegistry, create_tool_executor
        from app.services.tools.forbidden_word_check import ForbiddenWordCheckTool, check_forbidden_words

        print("✅ 工具模块导入成功")
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tool_definition():
    """测试工具定义获取是否正常。"""
    print("\n" + "=" * 60)
    print("测试 2: 工具定义获取")
    print("=" * 60)

    try:
        from app.services.tools.forbidden_word_check import ForbiddenWordCheckTool

        definition = ForbiddenWordCheckTool.get_definition()
        print(f"✅ 获取工具定义成功:")
        print(f"   - capability_key: {definition.capability_key}")
        print(f"   - name: {definition.name}")
        print(f"   - description: {definition.description[:50]}...")
        print(f"   - tags: {definition.tags}")
        print(f"   - 有 metadata: {bool(definition.metadata)}")
        print(f"   - 有 examples: {bool(definition.examples)}")
        return True
    except Exception as e:
        print(f"❌ 获取定义失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_backward_compatibility():
    """测试向后兼容性是否正常。"""
    print("\n" + "=" * 60)
    print("测试 3: 向后兼容性（旧函数调用）")
    print("=" * 60)

    try:
        from app.services.tools.forbidden_word_check import check_forbidden_words

        test_text = "这是一条测试文本，包含最高级这个违禁词。"
        result = check_forbidden_words(test_text)

        print(f"✅ 向后兼容函数调用成功:")
        print(f"   - passed: {result.get('passed')}")
        print(f"   - risk_level: {result.get('risk_level')}")
        print(f"   - hits: {len(result.get('hits', []))} 个词")
        print(f"   - suggestion: {result.get('suggestion')}")
        return True
    except Exception as e:
        print(f"❌ 向后兼容测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tool_registry():
    """测试工具注册表是否正常。"""
    print("\n" + "=" * 60)
    print("测试 4: 工具注册表")
    print("=" * 60)

    try:
        from app.services.tools import ToolRegistry

        definitions = ToolRegistry.get_all_definitions()
        print(f"✅ 工具注册表加载成功:")
        print(f"   - 找到 {len(definitions)} 个工具定义")

        for defi in definitions:
            print(f"   - {defi.capability_key}: {defi.name}")

        return True
    except Exception as e:
        print(f"❌ 工具注册表测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_tool_execution():
    """测试工具执行是否正常（需要 async 环境）。"""
    print("\n" + "=" * 60)
    print("测试 5: 工具执行器（Async）")
    print("=" * 60)

    try:
        from app.services.tools.forbidden_word_check import ForbiddenWordCheckTool
        from app.models.capability import Capability

        # 创建临时 capability
        capability = Capability(
            capability_key="tool_forbidden_word_check",
            metadata_=ForbiddenWordCheckTool.get_definition().metadata,
        )

        tool = ForbiddenWordCheckTool(capability)
        result = await tool.execute({
            "text": "这是绝对安全的产品，效果最好！",
            "check_level": "strict",
        })

        print(f"✅ 工具异步执行成功:")
        print(f"   - passed: {result.get('passed')}")
        print(f"   - risk_level: {result.get('risk_level')}")
        print(f"   - word_count: {result.get('word_count')}")
        print(f"   - tool_version: {result.get('tool_version')}")
        return True
    except Exception as e:
        print(f"❌ 工具执行测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试。"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + "           工具迁移验证测试套件".center(58) + "║")
    print("╚" + "=" * 58 + "╝")

    results = []

    # 同步测试
    results.append(("工具导入", test_tool_imports()))
    results.append(("工具定义", test_tool_definition()))
    results.append(("向后兼容", test_backward_compatibility()))
    results.append(("工具注册", test_tool_registry()))

    # 异步测试
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    results.append(("工具执行", loop.run_until_complete(test_tool_execution())))

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    for name, ok in results:
        status = "✅ 通过" if ok else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 所有测试通过！工具迁移成功。")
        return 0
    else:
        print(f"\n⚠️ 有 {total - passed} 个测试失败，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
