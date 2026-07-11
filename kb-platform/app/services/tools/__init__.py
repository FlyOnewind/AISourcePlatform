"""工具注册表：统一管理所有可注册的工具实现，支持动态发现与版本化。"""
import importlib
import inspect
from typing import Any, Callable, Dict, List, Optional, Type

from app.models.capability import Capability


class ToolDefinition:
    """工具定义：完整描述一个可注册的工具。"""
    def __init__(
        self,
        capability_key: str,
        name: str,
        description: str,
        business_domain: str,
        tags: List[str],
        scenarios: List[str],
        input_schema: Dict[str, Any],
        output_schema: Dict[str, Any],
        security_level: str = "internal",
        owner_department: str = "compliance",
        side_effect: str = "read_only",
        metadata: Dict[str, Any] = None,
        examples: List[Dict[str, Any]] = None,
        timeout_ms: int = 30000,
    ):
        self.capability_key = capability_key
        self.name = name
        self.description = description
        self.business_domain = business_domain
        self.tags = tags
        self.scenarios = scenarios
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.security_level = security_level
        self.owner_department = owner_department
        self.side_effect = side_effect
        self.metadata = metadata or {}
        self.examples = examples or []
        self.timeout_ms = timeout_ms


class ToolImplementation:
    """工具实现基类：所有可注册工具都应该实现这个接口。"""

    def __init__(self, capability: Capability):
        self.capability = capability
        self.config = capability.metadata_ or {}

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具，返回结果。"""
        raise NotImplementedError("子类必须实现 execute 方法")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        """获取工具的定义，用于注册到 capability 注册表。"""
        raise NotImplementedError("子类必须实现 get_definition 方法")


class ToolRegistry:
    """工具注册表：管理所有已注册的工具实现。"""

    _registry: Dict[str, Type[ToolImplementation]] = {}
    _loaded: bool = False

    @classmethod
    def register(cls, capability_key: str, tool_class: Type[ToolImplementation]):
        """注册一个工具实现。"""
        cls._registry[capability_key] = tool_class

    @classmethod
    def get_implementation(cls, capability_key: str) -> Optional[Type[ToolImplementation]]:
        """获取工具实现类。"""
        if not cls._loaded:
            cls._load_tools()
        return cls._registry.get(capability_key)

    @classmethod
    def get_all_definitions(cls) -> List[ToolDefinition]:
        """获取所有已注册工具的定义。"""
        if not cls._loaded:
            cls._load_tools()
        return [tool_class.get_definition() for tool_class in cls._registry.values()]

    @classmethod
    def _load_tools(cls):
        """自动发现并加载工具模块。"""
        if cls._loaded:
            return

        # 这里可以扩展为扫描目录并自动加载
        # 目前先显式注册内置工具
        try:
            from app.services.tools.forbidden_word_check import ForbiddenWordCheckTool
            cls.register("tool_forbidden_word_check", ForbiddenWordCheckTool)
        except Exception:
            pass

        # 加载示例工具
        try:
            from app.services.tools.example_tools import (
                TextAnalysisTool,
                DataFormatTool,
                SentimentAnalysisTool
            )
            cls.register("tool_text_analysis", TextAnalysisTool)
            cls.register("tool_data_format", DataFormatTool)
            cls.register("tool_sentiment_analysis", SentimentAnalysisTool)
        except Exception:
            pass

        cls._loaded = True


def create_tool_executor(capability: Capability) -> Optional[ToolImplementation]:
    """为给定的 capability 创建工具执行器。"""
    tool_class = ToolRegistry.get_implementation(capability.capability_key)
    if tool_class:
        return tool_class(capability)
    return None


__all__ = [
    "ToolDefinition",
    "ToolImplementation",
    "ToolRegistry",
    "create_tool_executor"
]
