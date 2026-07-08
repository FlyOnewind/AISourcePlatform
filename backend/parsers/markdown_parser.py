"""Markdown 和纯文本文档解析器。

使用 markdown-it 解析 Markdown 文档，提取标题、段落、表格、代码块、列表五种结构化元素。
列表保留嵌套层级（通过 parent_element_id 维护父子关系）。
引用块整体归入段落。图片、视频、文档、网页链接统一用占位符替换，
资源信息写入元素的 asset_data 字段。
"""

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.core.models import (
    Asset,
    AssetData,
    AssetStatus,
    AssetType,
    Document,
    ElementType,
    ParsedElement,
    SourceLocation,
    compute_hash,
)
from parsers.base import DocumentParser, ParseResult, _BaseParseState
from parsers.utils import (
    classify_link_url_first,
    is_video_url,
)


# ── 解析器内部状态 ──────────────────────────────────────────────


@dataclass
class _MdParseState(_BaseParseState):
    """Markdown 解析器的可变状态，每次 parse() 调用独立创建，天然线程安全。

    继承 _BaseParseState 的 doc_id、doc_version、elements、_seq、_section_path。
    所有可变字段都有默认值，由 dataclass 自动初始化，无需手动重置。
    """

    # ── 输出累积 ──
    assets: list[Asset] = field(default_factory=list)
    _counters: dict[str, int] = field(default_factory=dict)

    # ── 标题 / 段落缓冲区 ──
    heading_level: int = 0
    para_parts: list[str] = field(default_factory=list)
    pending_asset_data: list[AssetData] = field(default_factory=list)

    # ── 表格解析 ──
    in_table: bool = False
    in_thead: bool = False
    in_tbody: bool = False
    table_headers: list[tuple[str, list[AssetData]]] = field(default_factory=list)
    table_rows: list[list[tuple[str, list[AssetData]]]] = field(default_factory=list)
    current_row: list[tuple[str, list[AssetData]]] = field(default_factory=list)

    # ── 列表解析（栈结构支持嵌套）──
    in_list: bool = False
    _list_stack: list[dict] = field(default_factory=list)  # [{"container": ParsedElement, "current_text": str, "item_assets": list, "last_item_id": str}]

    # ── 引用块 ──
    in_blockquote: bool = False

    # ── 链接内联解析 ──
    in_link: bool = False
    link_href: str = ""
    link_text_parts: list[str] = field(default_factory=list)

    # ── <video> 预处理暂存 ──
    preplaced_assets: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    # ── 工具方法 ──

    # _next_seq() 继承自 _BaseParseState

    def next_ph(self, rtype: str) -> str:
        """生成递增占位符，如 {{image:1}}、{{doc:2}}、{{web:3}}。"""
        self._counters[rtype] = self._counters.get(rtype, 0) + 1
        label_map = {
            "image_link": "image", "video_link": "video",
            "document_link": "doc", "web_link": "web",
            "url": "web", "image": "image", "video": "video",
        }
        return f"{{{{{label_map.get(rtype, 'res')}:{self._counters[rtype]}}}}}"


class MarkdownParser(DocumentParser):
    """将 Markdown 和纯文本文档解析为 ParsedElement 和 Asset。

    支持的 source_type：markdown、md、txt、text。

    输出：
    - elements：含 title / paragraph / table / code / list 五种元素类型。
    - 代码块通过 ElementType.code 保留原文内容和编程语言信息。
    - 引用块内部文本以段落形式保留。
    - 元素通过 asset_data 字段记录占位符（如 [image1]）与 URL 的映射。
    - assets：image_link / video_link / document_link 的 Asset 对象（供入库流水线下载上传）。
    """

    SUPPORTED_TYPES = {"markdown", "md", "txt", "text"}

    _VIDEO_FULL_TAG_RE = re.compile(
        r'<video[^>]+src=["\'](?P<src>[^"\']+)["\'][^>]*>.*?</video>',
        re.IGNORECASE | re.DOTALL,
    )

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    # ── 主解析入口 ──────────────────────────────────────────────────

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """主解析入口：将 Markdown 文本解析为元素和资源列表。"""
        if isinstance(content, bytes):
            content = content.decode("utf-8")

        state = _MdParseState(
            doc_id=doc.doc_id,
            doc_version=doc.version,
        )

        content = self._pre_replace_video_tags(content, state)

        md = MarkdownIt("commonmark", {"breaks": True, "html": False})
        md.enable("table")
        tokens = md.parse(content)
        for token in tokens:
            self._process_token(token, state)

        self._flush_paragraph(state)

        # 后处理：将 preplaced 资源回填到包含其占位符的元素，并创建 Asset
        for el in state.elements:
            for ph, (placeholder, rtype, url) in list(state.preplaced_assets.items()):
                if ph in el.text:
                    asset = Asset(
                        doc_id=state.doc_id,
                        asset_type=AssetType(rtype),
                        original_uri=url,
                        status=AssetStatus.ready,
                        metadata={},
                    )
                    state.assets.append(asset)
                    el.asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    # 检查结构化数据中的单元格文本
                    if el.structured_data:
                        for row in el.structured_data.get("table", {}).get("rows", []):
                            for cell in row.get("cells", []):
                                if ph in cell.get("text", ""):
                                    cell.setdefault("asset_data", []).append(
                                        {"placeholder": ph, "asset_id": asset.asset_id}
                                    )
                    del state.preplaced_assets[ph]

        # 回填 Asset.element_id 关联
        self._link_assets_to_elements(state)

        doc.source_hash = compute_hash(content)

        return ParseResult(
            doc=doc,
            elements=state.elements,
            assets=state.assets,
        )

    # ── 资源构造 ──────────────────────────────────────────────────

    def _add_asset_data(
        self,
        state: _MdParseState,
        placeholder: str,
        rtype: str,
        url: str,
        display_text: str = "",
    ) -> None:
        """记录一条资源到当前段落的 pending_asset_data，同时创建 Asset。"""
        asset = Asset(
            doc_id=state.doc_id,
            asset_type=AssetType(rtype),
            original_uri=url,
            display_text=display_text,
            status=AssetStatus.ready,
            metadata={},
        )
        state.assets.append(asset)
        state.pending_asset_data.append(AssetData(
            placeholder=placeholder, asset_id=asset.asset_id,
        ))

    # ── 预处理：<video> 标签 → 占位符 ───────────────────────────

    def _pre_replace_video_tags(self, content: str, state: _MdParseState) -> str:
        def _replace(m: re.Match, st: _MdParseState = state) -> str:
            src = m.group("src")
            ph = st.next_ph("video_link")
            st.preplaced_assets[ph] = (ph, "video_link", src)
            return ph

        new_content = self._VIDEO_FULL_TAG_RE.sub(_replace, content)
        return re.sub(r'\n{3,}', '\n\n', new_content)

    # ── token 分发 ─────────────────────────────────────────────────

    def _process_token(self, token: Token, state: _MdParseState) -> None:
        t = token.type

        if t == "heading_open":
            self._flush_paragraph(state)
            state.heading_level = int(token.tag[1])

        elif t == "heading_close":
            text = "".join(state.para_parts).strip()
            if text:
                while len(state._section_path) >= state.heading_level:
                    state._section_path.pop()
                state._section_path.append(text)
                state.elements.append(self._make_element(
                    state, ElementType.title, text,
                    metadata={"heading_level": state.heading_level},
                ))
            state.heading_level = 0
            state.para_parts = []

        elif t == "table_open":
            self._flush_paragraph(state)
            state.in_table = True
            state.table_headers = []
            state.table_rows = []
            state.current_row = []

        elif t == "table_close":
            state.in_table = False
            self._emit_table(state)

        elif t == "thead_open":
            state.in_thead = True
        elif t == "thead_close":
            if state.current_row:
                state.table_headers = state.current_row
                state.current_row = []
            state.in_thead = False
        elif t == "tbody_open":
            state.in_tbody = True
        elif t == "tbody_close":
            state.in_tbody = False

        elif t == "tr_open":
            state.current_row = []

        elif t == "tr_close":
            if state.current_row:
                if state.in_thead:
                    state.table_headers = state.current_row
                else:
                    state.table_rows.append(state.current_row)
                state.current_row = []

        elif t in ("th_open", "td_open", "th_close", "td_close"):
            pass

        elif t == "paragraph_open":
            pass

        elif t == "paragraph_close":
            if not state.heading_level and not state.in_table and not state.in_list:
                state.para_parts.append("\n")

        elif t == "inline":
            rendered = self._render_inline(token, state)
            if state.in_table and state.current_row is not None:
                # 拍平当前单元格的 asset_data 到 cell 里
                cell_asset_data = list(state.pending_asset_data)
                state.pending_asset_data = []
                state.current_row.append((rendered, cell_asset_data))
            elif state._list_stack:
                # 列表条目内：文本累积到当前列表帧
                frame = state._list_stack[-1]
                frame["current_text"] += rendered
                frame["item_assets"].extend(state.pending_asset_data)
                state.pending_asset_data = []
            else:
                state.para_parts.append(rendered)

        elif t == "bullet_list_open":
            self._open_list(state, ordered=False)

        elif t == "ordered_list_open":
            self._open_list(state, ordered=True)

        elif t == "list_item_open":
            # 开始新条目前，先 flush 上一个条目（如果有的话）
            if state._list_stack:
                self._flush_list_item(state, state._list_stack[-1])

        elif t in ("bullet_list_close", "ordered_list_close"):
            if state._list_stack:
                # flush 最后一个条目
                frame = state._list_stack.pop()
                self._flush_list_item(state, frame)
            if not state._list_stack:
                state.in_list = False

        elif t in ("list_item_close",):
            pass

        elif t == "fence":
            self._flush_paragraph(state)
            code_text = token.content
            language = token.info.strip() if token.info else ""
            state.elements.append(ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state._next_seq(),
                element_type=ElementType.code,
                text=code_text,
                structured_data={"language": language} if language else None,
                source_location=SourceLocation(section_path=list(state._section_path)),
            ))

        elif t == "blockquote_open":
            self._flush_paragraph(state)
            state.in_blockquote = True

        elif t == "blockquote_close":
            self._flush_paragraph(state)
            state.in_blockquote = False

    # ── 内联渲染 ─────────────────────────────────────────────────

    def _render_inline(self, token: Token, state: _MdParseState) -> str:
        if not token.children:
            return token.content

        parts: list[str] = []
        for child in token.children:
            ctype = child.type

            if ctype == "text":
                if state.in_link:
                    state.link_text_parts.append(child.content)
                else:
                    parts.append(child.content)

            elif ctype == "softbreak":
                (state.link_text_parts if state.in_link else parts).append(" ")

            elif ctype == "hardbreak":
                (state.link_text_parts if state.in_link else parts).append("\n")

            elif ctype == "code_inline":
                (state.link_text_parts if state.in_link else parts).append(child.content)

            elif ctype == "image":
                src = child.attrs.get("src", "") if isinstance(child.attrs, dict) else ""
                alt = child.content or ""
                # 嵌入图片：alt 为空则按文件名后缀判断
                rtype = "video_link" if self._is_video_link(src, alt) else "image_link"
                ph = state.next_ph(rtype)
                self._add_asset_data(state, ph, rtype, src)
                parts.append(ph)

            elif ctype == "link_open":
                state.in_link = True
                state.link_href = (
                    child.attrs.get("href", "")
                    if isinstance(child.attrs, dict) else ""
                )
                state.link_text_parts = []

            elif ctype == "link_close":
                state.in_link = False
                link_text = "".join(state.link_text_parts)
                rtype = classify_link_url_first(state.link_href, link_text).value
                ph = state.next_ph(rtype)
                self._add_asset_data(state, ph, rtype, state.link_href, display_text=link_text)
                parts.append(link_text + ph)
                state.link_text_parts = []

            else:
                if state.in_link:
                    state.link_text_parts.append(child.content or "")
                elif child.content:
                    parts.append(child.content)

        return "".join(parts)

    # ── 链接分类 ────────────────────────────────────────────────

    @staticmethod
    def _is_video_link(src: str, alt: str = "") -> bool:
        return (
            "video" in alt.lower()
            or is_video_url(src)
            or src.lower().split("?", 1)[0].endswith((".mp4", ".webm", ".mov", ".m4v"))
        )

    # ── 列表构造 ──────────────────────────────────────────────────

    def _open_list(self, state: _MdParseState, ordered: bool) -> None:
        """进入一个列表（有序或无序），创建容器元素并压栈。

        如果已在列表中（嵌套），先 flush 父级条目的文本，
        使嵌套列表的 parent_element_id 指向父级条目。
        """
        self._flush_paragraph(state)

        parent_id: str | None = None
        if state._list_stack:
            self._flush_list_item(state, state._list_stack[-1])
            parent_id = state._list_stack[-1].get("last_item_id")

        container = ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            parent_element_id=parent_id,
            sequence_order=state._next_seq(),
            element_type=ElementType.list,
            text="",
            structured_data={"ordered": ordered},
            source_location=SourceLocation(section_path=list(state._section_path)),
        )
        state.elements.append(container)
        state._list_stack.append({
            "container": container,
            "current_text": "",
            "item_assets": [],
            "last_item_id": None,
        })
        state.in_list = True

    def _flush_list_item(self, state: _MdParseState, frame: dict) -> None:
        """将当前列表帧累积的文本刷新为一个条目 paragraph。"""
        text = frame["current_text"].strip()
        if text or frame["item_assets"]:
            item = ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                parent_element_id=frame["container"].element_id,
                sequence_order=state._next_seq(),
                element_type=ElementType.paragraph,
                text=text,
                asset_data=list(frame["item_assets"]),
                source_location=SourceLocation(section_path=list(state._section_path)),
            )
            state.elements.append(item)
            frame["last_item_id"] = item.element_id
        frame["current_text"] = ""
        frame["item_assets"] = []

    # ── 元素构造 ──────────────────────────────────────────────────

    def _make_element(
        self,
        state: _MdParseState,
        element_type: ElementType,
        text: str,
        metadata: dict | None = None,
    ) -> ParsedElement:
        """创建一个 ParsedElement，绑定当前累积的 asset_data。"""
        el = ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            sequence_order=state._next_seq(),
            element_type=element_type,
            text=text,
            asset_data=list(state.pending_asset_data),
            source_location=SourceLocation(section_path=list(state._section_path)),
            metadata=metadata or {},
        )
        state.pending_asset_data = []
        return el

    def _flush_paragraph(self, state: _MdParseState) -> None:
        text = "".join(state.para_parts).strip()
        state.para_parts = []
        if text:
            meta = {"blockquote": True} if state.in_blockquote else None
            state.elements.append(
                self._make_element(state, ElementType.paragraph, text, metadata=meta)
            )

    def _emit_table(self, state: _MdParseState) -> None:
        if not state.table_rows:
            return

        flat_parts: list[str] = []
        if state.table_headers:
            flat_parts.append(" | ".join(h[0] for h in state.table_headers))
        for row in state.table_rows:
            flat_parts.append(" | ".join(cell[0] for cell in row))

        cells_data = [
            {"cells": [{"text": cell_text} for cell_text, _ in row]}
            for row in state.table_rows
        ]

        # 汇总所有单元格的 asset_data 到表格级
        all_asset_data: list[AssetData] = []
        for row in state.table_rows:
            for _, cell_ads in row:
                all_asset_data.extend(cell_ads)

        state.elements.append(ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            sequence_order=state._next_seq(),
            element_type=ElementType.table,
            text="\n".join(flat_parts),
            structured_data={
                "table": {
                    "caption": "",
                    "headers": [{"text": h[0]} for h in state.table_headers] if state.table_headers else [],
                    "rows": cells_data,
                }
            },
            asset_data=all_asset_data,
            source_location=SourceLocation(section_path=list(state._section_path)),
        ))

    # ── 后处理 ──────────────────────────────────────────────────

    def _link_assets_to_elements(self, state: _MdParseState) -> None:
        """通过 element.asset_data 回填 Asset.element_id。"""
        for el in state.elements:
            for ad in el.asset_data:
                for asset in state.assets:
                    if asset.asset_id == ad.asset_id and not asset.element_id:
                        asset.element_id = el.element_id
