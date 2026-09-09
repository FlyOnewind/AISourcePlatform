"""文档解析器抽象基类和通用数据结构。

定义所有解析器必须遵循的统一契约：ParseResult 数据类和 DocumentParser 抽象类，
以及解析过程中共享的内部状态基类 _BaseParseState。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.models import Asset, Document, ParsedElement


@dataclass
class ParseResult:
    """解析结果，包含文档、结构化元素和资源资产。

    由各格式解析器的 parse() 方法返回，代表单个文档的一次解析结果。
    子文档的递归发现和加载由 RecursiveLoader 负责，不在解析器职责范围内。
    """
    doc: Document
    elements: list[ParsedElement] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)


@dataclass
class _BaseParseState:
    """解析器内部状态基类。

    所有解析器的内部状态类（如 _PdfParseState、_DocxParseState 等）
    继承此基类，共享 doc_id、doc_version、elements、序号计数和标题路径。

    各子类通过 dataclass 继承扩展自己的特有字段（如表格状态、列表状态等）。
    """
    doc_id: str
    doc_version: int
    elements: list[ParsedElement] = field(default_factory=list)
    _seq: int = 0
    _section_path: list[str] = field(default_factory=list)

    def _next_seq(self) -> int:
        """生成递增的序号，用于 ParsedElement.sequence_order。"""
        self._seq += 1
        return self._seq


class DocumentParser(ABC):
    """文档解析器抽象基类。

    所有格式解析器需实现 supports() 和 parse() 两个方法。
    通过 ParserRegistry 按 source_type 注册和分发。

    parse() 签名接受 bytes | str，各解析器内部自行处理类型转换。
    """

    @abstractmethod
    def supports(self, source_type: str) -> bool:
        """判断当前解析器是否支持指定的 source_type。"""
        ...

    @abstractmethod
    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """将原始文档解析为 ParseResult。

        Args:
            doc: 待解析的文档对象。
            content: 文档原始内容（bytes 或 str），由 Pipeline 显式传入。

        Returns:
            包含文档、元素列表和资源资产列表的 ParseResult。
        """
        ...
