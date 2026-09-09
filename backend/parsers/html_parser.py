"""HTML 文档解析器
使用 BeautifulSoup 将静HTML 文档解析为统一ParsedElement Asset支持标题、段落、列表、代码块、表格以及图片、视频、附件等内嵌资源的提取"""

import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

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
from app.core.paths import resolve_file_uri
from parsers.base import DocumentParser, ParseResult, _BaseParseState
from parsers.utils import classify_link_url_first


@dataclass
class _AssetRecord:
    """内部资源记录，保存 Asset 对象及原始 URL。"""
    asset: Asset
    original_url: str


@dataclass
class _HtmlParseState(_BaseParseState):
    """HTML 解析过程中的可变状态。

    继承 _BaseParseState 的 doc_id、doc_version、elements、_seq、_section_path。
    """
    assets: list[Asset] = field(default_factory=list)
    assets_by_key: dict[tuple[str, AssetType], _AssetRecord] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    _PH_MAP = {"image": "image", "video": "video", "image_link": "image",
               "video_link": "video", "document_link": "doc", "web_link": "web"}

    def next_ph(self, asset_type: str) -> str:
        """生成递增占位符 {{type:n}}。"""
        prefix = self._PH_MAP.get(asset_type, "res")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{{{{{prefix}:{self._counters[prefix]}}}}}"


class HtmlParser(DocumentParser):
    """将 HTML 文档解析为统一的 ParsedElement 和 Asset。

    支持 html 与 htm 来源类型。
    """

    SUPPORTED_TYPES = {"html", "htm"}
    SKIP_TAGS = {"script", "style", "noscript", "template", "meta", "link"}
    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "body",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
    RESOURCE_TAGS = {"img", "video", "source", "iframe", "embed", "object", "a"}
    VIDEO_URL_RE = re.compile(
        r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
        re.IGNORECASE,
    )
    HTTP_URL_RE = re.compile(r"https?://[^\s\])<\"']+", re.IGNORECASE)
    ATTACHMENT_EXTENSIONS = {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".zip",
        ".rar",
        ".7z",
        ".csv",
        ".txt",
        ".md",
    }

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """将 HTML 文档解析为结构化元素和资源列表。"""
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        if not content.strip():
            raise ValueError("HTML 解析失败：文档内容为空")

        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all(self.SKIP_TAGS):
            tag.decompose()

        root = self._content_root(soup)
        state = _HtmlParseState(doc.doc_id, doc.version)
        base_url = self._base_url(soup, doc)

        self._walk_children(root, state, doc, base_url)
        doc.source_hash = compute_hash(content)

        if not state.elements:
            raise ValueError("HTML 解析失败：未提取到有效内容")
        return ParseResult(doc=doc, elements=state.elements, assets=state.assets)

    @staticmethod
    def _content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
        """定位 HTML 文档的主要内容根节点
        优先使用 <main>，其<body>，再<article>        """
        for selector in ("main", "body"):
            found = soup.find(selector)
            if isinstance(found, Tag):
                return found
        articles = soup.find_all("article", recursive=False)
        if len(articles) == 1 and isinstance(articles[0], Tag):
            return articles[0]
        return soup

    @staticmethod
    def _base_url(soup: BeautifulSoup, doc: Document) -> str:
        """提取基准 URL，优先使用 base 标签，其次使用文档 source_uri。"""
        base = soup.find("base", href=True)
        if isinstance(base, Tag):
            return str(base.get("href") or "")
        return doc.source_uri

    def _walk_children(
        self,
        parent: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """递归遍历父节点的子元素，并跳过纯文本节点。"""
        for child in parent.children:
            if isinstance(child, NavigableString):
                continue
            if not isinstance(child, Tag):
                continue
            self._process_tag(child, state, doc, base_url)

    def _process_tag(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """根据标签类型分发到对应处理方法。"""
        name = (tag.name or "").lower()
        if name in self.SKIP_TAGS:
            return
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._add_title(tag, state)
            self._walk_children(tag, state, doc, base_url)
            return
        if name in {"p", "blockquote"}:
            self._add_paragraph(tag, state, doc, base_url)
            return
        if name in {"ul", "ol"}:
            self._add_list(tag, state, doc, base_url)
            return
        if name in {"pre", "code"}:
            self._add_code(tag, state)
            return
        if name == "table":
            self._add_table(tag, state, doc, base_url)
            return
        if name in self.RESOURCE_TAGS:
            self._add_resource_element(tag, state, doc, base_url)
            return

        self._walk_children(tag, state, doc, base_url)

    def _add_title(self, tag: Tag, state: _HtmlParseState) -> None:
        """添加标题元素，并按 h1-h6 层级更新 section_path。"""
        text = self._text_without_nested_blocks(tag)
        if not text:
            return
        level = int(tag.name[1])
        while len(state._section_path) >= level:
            state._section_path.pop()
        state._section_path.append(text)
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state._next_seq(),
                element_type=ElementType.title,
                text=text,
                source_location=SourceLocation(section_path=list(state._section_path)),
                metadata={"heading_level": level, "tag": tag.name},
            ),
        )

    def _add_paragraph(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """添加段落元素，并收集其中的资源引用。"""
        text, asset_ids = self._render_inline_html(tag, state, doc, base_url)
        if not text and not asset_ids:
            return
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state._next_seq(),
                element_type=ElementType.paragraph,
                text=text,
                asset_data=asset_ids,
                source_location=SourceLocation(section_path=list(state._section_path)),
                metadata={
                    "tag": tag.name,
                    **({"blockquote": True} if (tag.name or "").lower() == "blockquote" else {}),
                },
            ),
        )

    def _add_list(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
        parent_element_id: str | None = None,
    ) -> None:
        """添加列表元素，并递归处理嵌套列表。

        parent_element_id: 嵌套列表的父条目 paragraph ID（顶层列表为 None）。
        """
        items = [child for child in tag.find_all("li", recursive=False)]
        if not items:
            return

        container = ParsedElement(
            doc_id=state.doc_id,
            doc_version=state.doc_version,
            parent_element_id=parent_element_id,
            sequence_order=state._next_seq(),
            element_type=ElementType.list,
            text="",
            source_location=SourceLocation(section_path=list(state._section_path)),
            metadata={"ordered": tag.name == "ol", "tag": tag.name},
        )
        self._append_element(state, container)

        for item in items:
            nested_lists = item.find_all(["ul", "ol"], recursive=False)
            for nested in nested_lists:
                nested.extract()
            text, asset_ids = self._render_inline_html(item, state, doc, base_url)
            item_element_id: str | None = None
            if text or asset_ids:
                item_el = ParsedElement(
                    doc_id=state.doc_id,
                    doc_version=state.doc_version,
                    parent_element_id=container.element_id,
                    sequence_order=state._next_seq(),
                    element_type=ElementType.paragraph,
                    text=text,
                    asset_data=asset_ids,
                    source_location=SourceLocation(section_path=list(state._section_path)),
                    metadata={"tag": "li"},
                )
                self._append_element(state, item_el)
                item_element_id = item_el.element_id
            for nested in nested_lists:
                self._add_list(nested, state, doc, base_url, parent_element_id=item_element_id)

    def _add_code(self, tag: Tag, state: _HtmlParseState) -> None:
        """添加代码块元素，并从 class 属性推断编程语言。"""
        text = tag.get_text("\n", strip=False).strip("\n")
        if not text:
            return
        language = self._language_from_class(tag) or self._language_from_class(tag.find("code"))
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state._next_seq(),
                element_type=ElementType.code,
                text=unescape(text),
                structured_data={"language": language} if language else None,
                source_location=SourceLocation(section_path=list(state._section_path)),
                metadata={"tag": tag.name},
            ),
        )

    def _add_table(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """添加表格元素，支持嵌套表格、标题行和单元格资源。"""
        nested_tables = tag.find_all("table")
        for nested in nested_tables:
            nested.extract()

        caption_tag = tag.find("caption", recursive=False)
        caption = self._text(caption_tag) if caption_tag else ""
        table_rows: list[list[dict[str, Any]]] = []
        asset_ids: list[AssetData] = []

        for tr in tag.find_all("tr"):
            cells = []
            for cell_tag in tr.find_all(["th", "td"], recursive=False):
                cell_text, cell_assets = self._render_inline_html(cell_tag, state, doc, base_url)
                asset_ids.extend(cell_assets)
                cells.append(
                    {
                        "text": cell_text,
                        "asset_data": [ad.model_dump() for ad in cell_assets],
                        "metadata": {
                            "tag": cell_tag.name,
                            "rowspan": self._int_attr(cell_tag, "rowspan", 1),
                            "colspan": self._int_attr(cell_tag, "colspan", 1),
                        },
                    }
                )
            if cells:
                table_rows.append(cells)

        if not table_rows:
            for nested in nested_tables:
                self._add_table(nested, state, doc, base_url)
            return

        header_index = self._header_row_index(tag, table_rows)
        headers = [cell["text"] for cell in table_rows[header_index]]
        rows = [
            {"cells": row}
            for index, row in enumerate(table_rows)
            if index != header_index
        ]
        structured = {
            "table": {
                "caption": caption,
                "headers": headers,
                "rows": rows,
                "metadata": {
                    "tag": "table",
                    "row_count": len(table_rows),
                    "header_row_index": header_index,
                },
            }
        }
        text_parts = []
        if caption:
            text_parts.append(caption)
        if headers:
            text_parts.append(" | ".join(headers))
        for row in rows:
            text_parts.append(" | ".join(cell["text"] for cell in row["cells"]))

        # 表格级资源引用按 asset_id 去重。
        seen_asset_ids: set[str] = set()
        deduped_asset_data: list[AssetData] = []
        for ad in asset_ids:
            if ad.asset_id not in seen_asset_ids:
                seen_asset_ids.add(ad.asset_id)
                deduped_asset_data.append(ad)

        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state._next_seq(),
                element_type=ElementType.table,
                text="\n".join(part for part in text_parts if part.strip()),
                structured_data=structured,
                asset_data=deduped_asset_data,
                source_location=SourceLocation(section_path=list(state._section_path)),
                metadata={"tag": "table", "caption": caption},
            ),
        )

        for nested in nested_tables:
            self._add_table(nested, state, doc, base_url)

    def _add_resource_element(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> None:
        """<img>video>iframe> 等资源标签创建对应的元素
        图片和视频属于附属资源，对应元素类型统一paragraph        """
        asset_ids = self._assets_from_resource_tag(tag, state, doc, base_url)
        if not asset_ids:
            return
        text = self._text(tag) or self._resource_label(tag, state)
        self._append_element(
            state,
            ParsedElement(
                doc_id=state.doc_id,
                doc_version=state.doc_version,
                sequence_order=state._next_seq(),
                element_type=ElementType.paragraph,
                text=text,
                asset_data=asset_ids,
                source_location=SourceLocation(section_path=list(state._section_path)),
                metadata={"tag": tag.name},
            ),
        )

    def _assets_in_tag(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> list[AssetData]:
        """收集指定标签及其子标签中的资源引用。"""
        asset_ids: list[AssetData] = []
        for resource in tag.find_all(self.RESOURCE_TAGS):
            asset_ids.extend(self._assets_from_resource_tag(resource, state, doc, base_url))
        for url in self.HTTP_URL_RE.findall(self._text(tag)):
            if self._is_video_url(url):
                asset = self._asset_for_url(url, AssetType.video_link, state, doc, {})
                asset_ids.append(
                    AssetData(placeholder="", asset_id=asset.asset_id)
                )
        # 按 asset_id 去重
        seen: set[str] = set()
        deduped: list[AssetData] = []
        for ad in asset_ids:
            if ad.asset_id not in seen:
                seen.add(ad.asset_id)
                deduped.append(ad)
        return deduped

    def _assets_from_resource_tag(
        self,
        tag: Tag,
        state: _HtmlParseState,
        doc: Document,
        base_url: str,
    ) -> list[AssetData]:
        """从单个资源标签创Asset 并返回对应的 AssetData 列表
        支持 img、video、source、a（附件链接）、iframe、embed、object 等标签        """
        name = (tag.name or "").lower()
        attr = "href" if name == "a" else "data" if name == "object" else "src"
        raw_url = str(tag.get(attr) or "")
        if not raw_url:
            return []

        original_url = raw_url.strip()
        resolved_url = self._resolve_url(original_url, base_url)
        if name == "img":
            alt = str(tag.get("alt") or "")
            asset_type = classify_link_url_first(resolved_url or original_url, alt)
            asset = self._asset_for_url(
                resolved_url or original_url,
                asset_type,
                state,
                doc,
                {},
            )
            asset.display_text = alt
            ph = state.next_ph(asset_type.value)
            return [AssetData(placeholder=ph, asset_id=asset.asset_id)]

        if name == "a":
            # <a> 链接: URL 优先 → 锚文字兜底 → web_link，对齐其他解析器
            anchor = tag.get_text(strip=True)
            asset_type = classify_link_url_first(resolved_url or original_url, anchor)
            asset = self._asset_for_url(
                resolved_url or original_url,
                asset_type,
                state,
                doc,
                {},
            )
            asset.display_text = anchor
            ph = state.next_ph(asset_type.value)
            return [AssetData(placeholder=ph, asset_id=asset.asset_id)]

        if name in {"iframe", "embed", "object"}:
            asset = self._asset_for_url(
                resolved_url or original_url,
                AssetType.document_link,
                state,
                doc,
                {},
            )
            ph = state.next_ph("document_link")
            return [AssetData(placeholder=ph, asset_id=asset.asset_id)]
        return []

    def _asset_for_url(
        self,
        url: str,
        asset_type: AssetType,
        state: _HtmlParseState,
        doc: Document,
        metadata: dict[str, Any],
    ) -> Asset:
        """创建或复用 Asset，按 URL 和资源类型去重。"""
        key = (url, asset_type)
        existing = state.assets_by_key.get(key)
        if existing is not None:
            return existing.asset
        asset = Asset(
            doc_id=doc.doc_id,
            asset_type=asset_type,
            original_uri=url,
            storage_uri=None,
            status=AssetStatus.ready,
            extracted_text=None,
            metadata={
                **metadata,
            },
        )
        state.assets.append(asset)
        state.assets_by_key[key] = _AssetRecord(asset=asset, original_url=url)
        return asset

    @staticmethod
    def _append_element(state: _HtmlParseState, element: ParsedElement) -> None:
        """添加元素，并通过 asset_id 回填 Asset.element_id。"""
        assets_by_id = {
            record.asset.asset_id: record.asset
            for record in state.assets_by_key.values()
        }
        for ad in element.asset_data:
            asset = assets_by_id.get(ad.asset_id)
            if asset is not None and not asset.element_id:
                asset.element_id = element.element_id
        state.elements.append(element)

    def _header_row_index(self, table: Tag, rows: list[list[dict[str, Any]]]) -> int:
        """检测表格的标题行索引
        优先检<thead> 元素，其次检查第一行是否全<th> 单元格        """
        thead = table.find("thead")
        if thead is not None:
            first_header = thead.find("tr")
            if first_header is not None:
                table_rows = table.find_all("tr")
                try:
                    return table_rows.index(first_header)
                except ValueError:
                    return 0
        if rows and all(cell["metadata"]["tag"] == "th" for cell in rows[0]):
            return 0
        return 0

    def _render_inline_html(
        self, tag: Tag, state: "_HtmlParseState", doc: Document, base_url: str,
    ) -> tuple[str, list[AssetData]]:
        """递归渲染内联 HTML，在 <a>/<img> 原位插入占位符，对齐 MD 行为。

        遍历 tag 的直接子节点：
        - 文本节点 → 直接拼接
        - <a> → 递归取内部文字 + classify_link_url_first → "文字{{type:N}}"
        - <img> → classify → "{{image:N}}"
        - <video>/<iframe>/<embed> → "{{type:N}}"
        - 行内标签（<b>/<i>/<span> 等）→ 递归
        - 块级标签 → 跳过
        """
        text_parts: list[str] = []
        asset_data: list[AssetData] = []

        for child in tag.children:
            if isinstance(child, NavigableString):
                text_parts.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue

            name = (child.name or "").lower()

            if name == "a":
                href = str(child.get("href") or "")
                resolved = self._resolve_url(href.strip(), base_url)
                inner, child_ads = self._render_inline_html(child, state, doc, base_url)
                if resolved:
                    asset_type = classify_link_url_first(resolved, inner.strip())
                    asset = self._asset_for_url(resolved, asset_type, state, doc, {})
                    asset.display_text = inner.strip()
                    ph = state.next_ph(asset_type.value)
                    asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    asset_data.extend(child_ads)
                    text_parts.append(inner + ph)
                else:
                    text_parts.append(inner)
                    asset_data.extend(child_ads)

            elif name == "img":
                src = str(child.get("src") or "")
                alt = str(child.get("alt") or "")
                resolved = self._resolve_url(src.strip(), base_url)
                if resolved:
                    asset_type = classify_link_url_first(resolved, alt)
                    asset = self._asset_for_url(resolved, asset_type, state, doc, {})
                    asset.display_text = alt
                    ph = state.next_ph(asset_type.value)
                    asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    text_parts.append(ph)

            elif name in ("video", "source", "iframe", "embed", "object"):
                attr = "data" if name == "object" else "src"
                raw = str(child.get(attr) or "")
                resolved = self._resolve_url(raw.strip(), base_url)
                if resolved:
                    is_vid = name in ("video", "source") or self._is_video_url(resolved)
                    asset_type = AssetType.video_link if is_vid else AssetType.document_link
                    asset = self._asset_for_url(resolved, asset_type, state, doc, {})
                    ph = state.next_ph(asset_type.value)
                    asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    text_parts.append(ph)

            elif name in self.BLOCK_TAGS:
                continue

            else:
                inner, child_ads = self._render_inline_html(child, state, doc, base_url)
                text_parts.append(inner)
                asset_data.extend(child_ads)

        text = self._normalize_text("".join(text_parts))
        return text, asset_data

    def _text_without_nested_blocks(self, tag: Tag) -> str:
        """提取标签文本，并排除嵌套的块级子标签。"""
        clone = BeautifulSoup(str(tag), "html.parser")
        clone_tag = clone.find(tag.name)
        if clone_tag is None:
            return ""
        for nested in clone_tag.find_all(self.BLOCK_TAGS - {tag.name}):
            nested.decompose()
        return self._normalize_text(clone_tag.get_text(" ", strip=True))

    @staticmethod
    def _text(tag: Tag | None) -> str:
        """提取标签纯文本并归一化空白。"""
        if tag is None:
            return ""
        return HtmlParser._normalize_text(tag.get_text(" ", strip=True))

    @staticmethod
    def _normalize_text(text: str) -> str:
        """将连续空白归一化为单个空格并去除首尾空白。"""
        return re.sub(r"\s+", " ", unescape(text)).strip()

    @staticmethod
    def _language_from_class(tag: Tag | None) -> str:
        """从标签 class 属性中的 language-xx 或 lang-xx 推断语言。"""
        if not isinstance(tag, Tag):
            return ""
        classes = tag.get("class") or []
        for klass in classes:
            text = str(klass)
            if text.startswith("language-"):
                return text.removeprefix("language-")
            if text.startswith("lang-"):
                return text.removeprefix("lang-")
        return ""

    @staticmethod
    def _int_attr(tag: Tag, name: str, default: int) -> int:
        """安全获取标签的整数属性值，最小值为 1。"""
        try:
            return max(1, int(str(tag.get(name) or default)))
        except ValueError:
            return default

    @staticmethod
    def _resolve_url(url: str, base_url: str) -> str:
        """在基准地址为 HTTP(S) 时，将相对 URL 解析为绝对 URL。"""
        if not url:
            return ""
        if urlparse(url).scheme:
            return url
        if base_url and urlparse(base_url).scheme in {"http", "https"}:
            return urljoin(base_url, url)
        return url

    def _tag_is_video(self, tag: Tag) -> bool:
        """判断标签是否表示视频资源。"""
        name = (tag.name or "").lower()
        if name in {"video", "source"}:
            return True
        if name == "iframe":
            raw = str(tag.get("src") or "")
            return self._is_video_url(raw)
        return False

    def _is_video_url(self, url: str) -> bool:
        """判断 URL 是否为视频链接。"""
        return bool(self.VIDEO_URL_RE.search(url))

    def _is_attachment_url(self, url: str) -> bool:
        """判断 URL 是否指向附件文件。"""
        path = urlparse(url).path or url
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in self.ATTACHMENT_EXTENSIONS

    def _resource_label(self, tag: Tag, state: _HtmlParseState) -> str:
        """为资源标签生成 {{type:n}} 占位符文本。"""
        name = (tag.name or "").lower()
        if name == "img":
            return state.next_ph("image")
        if name in {"video", "source", "iframe"}:
            return state.next_ph("video")
        return state.next_ph("document_link")
