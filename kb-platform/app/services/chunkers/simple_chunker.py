"""知识切片：按 Markdown 标题层级切片，纯文本按段落/长度切片。

对应文档04 第5节的简化版实现——覆盖"按标题层级""按段落"两种通用策略，
FAQ一问一答、表格按行组等更细的策略留作后续待办。
"""
import re
from dataclasses import dataclass, field

MAX_CHUNK_CHARS = 800


@dataclass
class ChunkDraft:
    content: str
    title_path: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def chunk_text(raw_text: str) -> list[ChunkDraft]:
    if _looks_like_markdown(raw_text):
        return _chunk_by_headings(raw_text)
    return _chunk_by_paragraph(raw_text)


def _looks_like_markdown(text: str) -> bool:
    return bool(re.search(r"^#{1,6}\s", text, flags=re.MULTILINE))


def _chunk_by_headings(text: str) -> list[ChunkDraft]:
    lines = text.splitlines()
    chunks: list[ChunkDraft] = []
    heading_stack: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        content = "\n".join(buffer).strip()
        if content:
            chunks.append(ChunkDraft(content=content, title_path=list(heading_stack), keywords=_extract_keywords(content)))
        buffer.clear()

    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_stack[level - 1 :] = [title]
            heading_stack[:] = heading_stack[:level]
        else:
            buffer.append(line)
    flush()

    # 超长片段再按段落切
    result: list[ChunkDraft] = []
    for c in chunks:
        if len(c.content) <= MAX_CHUNK_CHARS:
            result.append(c)
        else:
            for sub in _split_long_text(c.content):
                result.append(ChunkDraft(content=sub, title_path=c.title_path, keywords=_extract_keywords(sub)))
    return result or [ChunkDraft(content=text.strip(), keywords=_extract_keywords(text))]


def _chunk_by_paragraph(text: str) -> list[ChunkDraft]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return [ChunkDraft(content=text.strip())] if text.strip() else []
    chunks: list[ChunkDraft] = []
    buffer = ""
    for p in paragraphs:
        candidate = f"{buffer}\n\n{p}" if buffer else p
        if len(candidate) > MAX_CHUNK_CHARS and buffer:
            chunks.append(ChunkDraft(content=buffer, keywords=_extract_keywords(buffer)))
            buffer = p
        else:
            buffer = candidate
    if buffer:
        chunks.append(ChunkDraft(content=buffer, keywords=_extract_keywords(buffer)))
    return chunks


def _split_long_text(text: str) -> list[str]:
    return [text[i : i + MAX_CHUNK_CHARS] for i in range(0, len(text), MAX_CHUNK_CHARS)]


def _extract_keywords(text: str, top_n: int = 8) -> list[str]:
    tokens = re.findall(r"[\w一-鿿]{2,}", text.lower())
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:top_n]]
