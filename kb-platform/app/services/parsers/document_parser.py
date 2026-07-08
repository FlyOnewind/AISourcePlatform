"""文档解析：按文件扩展名分发到对应解析器，产出纯文本 + 结构化标题路径提示。

支持 txt / md / pdf / docx，对应文档04 第4节解析能力要求的最小子集
（表格/图片OCR/HTML 留作后续待办，README 中会注明）。
"""
from dataclasses import dataclass, field
from io import BytesIO

from docx import Document as DocxDocument
from pypdf import PdfReader


@dataclass
class ParsedDocument:
    raw_text: str
    parse_quality_score: float = 1.0
    warnings: list[str] = field(default_factory=list)


class UnsupportedFileTypeError(ValueError):
    pass


def parse_document(filename: str, content: bytes) -> ParsedDocument:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("txt", "md", "markdown"):
        return _parse_text(content)
    if ext == "pdf":
        return _parse_pdf(content)
    if ext == "docx":
        return _parse_docx(content)
    raise UnsupportedFileTypeError(f"不支持的文件类型: .{ext}（当前支持 txt/md/pdf/docx）")


def _parse_text(content: bytes) -> ParsedDocument:
    text = content.decode("utf-8", errors="replace")
    return ParsedDocument(raw_text=text)


def _parse_pdf(content: bytes) -> ParsedDocument:
    warnings: list[str] = []
    try:
        reader = PdfReader(BytesIO(content))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                warnings.append(f"第{i + 1}页未提取到文本，可能为扫描图片（OCR 未实现，留作后续待办）")
            pages.append(text)
        raw_text = "\n\n".join(pages)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"PDF 解析失败: {exc}") from exc
    quality = 1.0 if not warnings else max(0.3, 1.0 - 0.1 * len(warnings))
    return ParsedDocument(raw_text=raw_text, parse_quality_score=quality, warnings=warnings)


def _parse_docx(content: bytes) -> ParsedDocument:
    try:
        doc = DocxDocument(BytesIO(content))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        raw_text = "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"DOCX 解析失败: {exc}") from exc
    return ParsedDocument(raw_text=raw_text)
