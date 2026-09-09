"""解析器注册表。

按 source_type 管理和分发 DocumentParser 实现，支持大小写不敏感的注册、查找、
注销、优先级覆盖和全量查询。
"""

import logging

from parsers.base import DocumentParser

logger = logging.getLogger(__name__)


class UnsupportedFormatError(ValueError):
    """当没有解析器能处理给定的 source_type 时抛出。"""

    def __init__(self, source_type: str, supported_types: list[str]) -> None:
        self.source_type = source_type
        self.supported_types = supported_types
        super().__init__(
            f"Unsupported source_type: {source_type}. "
            f"Supported types: {', '.join(sorted(supported_types))}"
        )


class ParserRegistry:
    """按 source_type 注册和查找 DocumentParser 实现的注册表。

    使用方式：
        registry = ParserRegistry()
        registry.register(MarkdownParser(), PdfParser())
        parser = registry.get("pdf")
        result = parser.parse(doc)
    """

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {}
        self._priorities: dict[str, int] = {}

    @property
    def supported_types(self) -> list[str]:
        """返回所有已注册的 source_type（按字母排序）。"""
        return sorted(self._parsers.keys())

    def register(self, *parsers: DocumentParser, priority: int = 0) -> None:
        """注册一个或多个解析器。

        每个解析器的 SUPPORTED_TYPES 类属性作为注册键（大小写不敏感）。
        高优先级解析器覆盖低优先级；同优先级时后注册的覆盖先注册的。
        重复注册或覆盖均输出日志。

        Args:
            *parsers: 一个或多个 DocumentParser 实例。
            priority: 优先级（整数，默认 0），值越大优先级越高。
        """
        for parser in parsers:
            supported = getattr(parser, "SUPPORTED_TYPES", set())
            for source_type in supported:
                key = source_type.lower()
                existing = self._parsers.get(key)
                existing_priority = self._priorities.get(key, 0)

                if existing is not None and existing is not parser:
                    if priority < existing_priority:
                        logger.warning(
                            "跳过注册 '%s'（%s，优先级 %d）：已存在 %s（优先级 %d）",
                            key,
                            type(parser).__name__,
                            priority,
                            type(existing).__name__,
                            existing_priority,
                        )
                        continue
                    logger.warning(
                        "覆盖 '%s' 解析器：%s（优先级 %d）→ %s（优先级 %d）",
                        key,
                        type(existing).__name__,
                        existing_priority,
                        type(parser).__name__,
                        priority,
                    )

                self._parsers[key] = parser
                self._priorities[key] = priority

    def get(self, source_type: str) -> DocumentParser:
        """获取指定 source_type 对应的解析器。

        Args:
            source_type: 文档类型标识（如 "pdf"、"markdown"、"docx" 等）。

        Returns:
            匹配的 DocumentParser 实例。

        Raises:
            UnsupportedFormatError: 当没有注册该类型的解析器时。
        """
        key = source_type.lower()
        if key not in self._parsers:
            raise UnsupportedFormatError(source_type, self.supported_types)
        return self._parsers[key]

    def unregister(self, source_type: str) -> None:
        """注销指定 source_type 的解析器注册项。

        对未注册的类型静默成功（幂等操作）。

        Args:
            source_type: 要注销的文档类型标识。
        """
        key = source_type.lower()
        self._parsers.pop(key, None)
        self._priorities.pop(key, None)

    def get_all(self) -> dict[str, DocumentParser]:
        """返回所有已注册的解析器映射。

        Returns:
            {source_type: DocumentParser} 字典的浅拷贝。
        """
        return dict(self._parsers)
