"""文档解析器包。

提供多格式文档解析的统一入口，将各类文档（PDF、Markdown、DOCX、HTML、PPTX、XLSX）
解析为统一的 ParsedElement 和 Asset 结构，供下游索引管线消费。
"""

from parsers.docx_parser import DocxParser
from parsers.html_parser import HtmlParser
from parsers.markdown_parser import MarkdownParser
from parsers.pdf_parser import PdfParser
from parsers.pptx_parser import PptxParser
from parsers.xlsx_parser import XlsxParser

__all__ = [
    "HtmlParser",
    "PdfParser",
    "MarkdownParser",
    "DocxParser",
    "PptxParser",
    "XlsxParser",
]
