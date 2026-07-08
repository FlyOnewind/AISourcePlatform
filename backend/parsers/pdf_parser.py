"""PDF 解析器。

双链路，对调用方透明：

- MinerU API（优先）：配置 MINERU_API_TOKEN 后启用。云端布局分析 + 阅读顺序恢复 +
  表格/公式识别，输出类 Markdown 后经 MarkdownParser 统一解析。
- PyMuPDF 本地（兜底）：未配置 token 或 API 调用失败时自动切换。字体启发式标题 +
  页眉页脚跨页重复过滤 + find_tables 表格识别。

不论哪条链路，PyMuPDF 都参与：MinerU 链路中负责超链接 bbox 匹配注入和嵌入图片二进制提取。
"""

import hashlib
import json
import logging
import re
import statistics
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import fitz
import requests

from app.core.config import get_settings
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
from parsers.markdown_parser import MarkdownParser
from parsers.utils import classify_link_url_first

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
# PyMuPDF 本地链路常量（MinerU 不可用时兜底）
# ══════════════════════════════════════════════════════════════════════════

TITLE_FONT_SIZE_THRESHOLD = 14.0
BOLD_TITLE_MIN_SIZE = 12.0
BOLD_TITLE_MAX_SIZE = 13.0
MAX_TITLE_CHARS = 80
HEADER_FOOTER_FONT_MAX = 10.0
HEADER_FOOTER_Y_MARGIN = 0.15
HEADER_FOOTER_MIN_REPEAT_PAGES = 3
HEADER_FOOTER_MAX_CHARS = 100
PARAGRAPH_GAP_RATIO = 1.5

PAGE_NUMBER_PATTERNS = [
    re.compile(r"^\d+$"),
    re.compile(r"^[ivxlcdm]+$", re.IGNORECASE),
    re.compile(r"^\d+\s*/\s*\d+$"),
    re.compile(r"^-\s*\d+\s*-$"),
    re.compile(r"^第\s*\d+\s*页?$"),
]

VIDEO_URL_RE = re.compile(
    r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
    re.IGNORECASE,
)

ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".csv", ".txt", ".md",
}

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
}


# ══════════════════════════════════════════════════════════════════════════
# 本地链路内部数据结构
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class _TextBlock:
    """页面文本块——字体、位置、span 边界。"""
    page: int
    y0: float; y1: float; x0: float; x1: float
    text: str
    font_size: float
    is_bold: bool
    bbox: tuple[float, float, float, float]
    span_bboxes: list[tuple[str, tuple[float, float, float, float]]] = field(default_factory=list)


@dataclass
class _AssetRecord:
    """Asset 去重记录。"""
    asset: Asset
    key: tuple[str, str]


@dataclass
class _LocalPdfState(_BaseParseState):
    """PyMuPDF 本地解析状态。

    继承 _BaseParseState 的 doc_id、doc_version、elements、_seq、_section_path。
    """
    assets: list[Asset] = field(default_factory=list)
    assets_by_key: dict[tuple[str, str], _AssetRecord] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    _PH_MAP = {"image": "image", "video": "video", "image_link": "image",
               "video_link": "video", "document_link": "doc", "web_link": "web"}

    def next_ph(self, asset_type: str) -> str:
        prefix = self._PH_MAP.get(asset_type, "res")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{{{{{prefix}:{self._counters[prefix]}}}}}"


class PdfParser(DocumentParser):
    """PDF 解析器——MinerU API 优先，PyMuPDF 本地兜底。

    - 配置了 MINERU_API_TOKEN：MinerU 云端布局分析 → MarkdownParser 统一输出
    - 未配置或 API 失败：_LocalPdfParser 纯本地解析（字体启发式标题 + 页眉页脚过滤）
    - 两条链路均通过 PyMuPDF 补充超链接和图片二进制数据
    """

    SUPPORTED_TYPES = {"pdf"}

    # MinerU API 端点
    _BATCH_URL = "/api/v4/file-urls/batch"        # 申请上传 + 自动创建解析任务
    _BATCH_RESULT_URL = "/api/v4/extract-results/batch"  # 查询批量任务结果
    _TASK_POLL_INTERVAL = 3       # 轮询间隔（秒）
    _TASK_MAX_WAIT = 300          # 最长等待（秒）
    _BBOX_NORM = 1000.0           # MinerU bbox 归一化范围

    def __init__(self) -> None:
        cfg = get_settings()
        self._token: str = getattr(cfg, "mineru_api_token", "") or ""
        self._api_base: str = getattr(cfg, "mineru_api_base", "") or "https://mineru.net"
        self._use_vlm: bool = getattr(cfg, "mineru_use_vlm", False)
        self._fallback: DocumentParser | None = None  # 延迟加载

    def _get_fallback(self) -> DocumentParser:
        """延迟初始化本地 PyMuPDF 解析器（_LocalPdfParser）作为降级方案。"""
        if self._fallback is None:
            self._fallback = _LocalPdfParser()
        return self._fallback

    def supports(self, source_type: str) -> bool:
        return source_type.lower() == "pdf"

    # ── 主解析入口 ──────────────────────────────────────────────────

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """MinerU API 解析（默认），不可用时自动降级本地链路。"""
        if isinstance(content, str):
            content = content.encode("utf-8")

        if not self._token:
            logger.warning("未配置 MINERU_API_TOKEN，降级到本地链路")
            return self._get_fallback().parse(doc, content)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "input.pdf"
            pdf_path.write_bytes(content)

            try:
                # 1. MinerU API
                mineru_md, mineru_blocks = self._run_mineru(pdf_path)
            except Exception as exc:
                logger.warning("MinerU API 失败 (%s)，降级到本地链路", exc)
                return self._get_fallback().parse(doc, content)

            # 2. PyMuPDF 提取链接 + bbox 匹配 + 注入 Markdown
            pdf = fitz.open(pdf_path)
            try:
                md_with_links = self._inject_links(pdf, mineru_md, mineru_blocks)
            finally:
                pdf.close()

            # 3. MarkdownParser 解析
            md_parser = MarkdownParser()
            result = md_parser.parse(doc, md_with_links)

            # 4. PyMuPDF 提取嵌入图片 + bbox 匹配 + 替换 Asset
            pdf2 = fitz.open(pdf_path)
            try:
                self._fix_image_assets(result, pdf2, mineru_blocks)
            finally:
                pdf2.close()

            # 5. 回填 element_id + 设置 source_hash
            self._backfill_element_ids(result)
            doc.source_hash = compute_hash(content)

            return result

    # ── MinerU API ───────────────────────────────────────────────────

    def _run_mineru(self, pdf_path: Path) -> tuple[str, list[dict[str, Any]]]:
        """提交 PDF 到 MinerU（上传后自动解析），轮询完成，返回 (md_text, blocks)。"""
        batch_id, upload_url = self._apply_upload(pdf_path)
        self._put_file(upload_url, pdf_path)
        zip_path = self._wait_batch_and_download(batch_id, pdf_path.parent)
        return self._parse_mineru_output(zip_path)

    def _apply_upload(self, pdf_path: Path) -> tuple[str, str]:
        """申请上传 URL + 创建批量解析任务，返回 (batch_id, upload_url)。"""
        url = f"{self._api_base}{self._BATCH_URL}"
        body: dict[str, Any] = {
            "files": [{"name": pdf_path.name}],
            "language": "ch",
            "enable_formula": True,
            "enable_table": True,
        }
        if self._use_vlm:
            body["model_version"] = "vlm"

        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU 上传申请失败: {data.get('msg', resp.text)}")
        batch_id = data["data"]["batch_id"]
        file_urls = data["data"].get("file_urls", [])
        if not file_urls:
            raise RuntimeError("MinerU 上传申请返回空 URL")
        logger.info("MinerU batch_id=%s", batch_id)
        return batch_id, file_urls[0]

    @staticmethod
    def _put_file(upload_url: str, pdf_path: Path) -> None:
        """PUT 文件到 OSS 预签名 URL，上传后系统自动提交解析任务。"""
        with open(pdf_path, "rb") as f:
            resp = requests.put(upload_url, data=f, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"MinerU 文件上传失败: HTTP {resp.status_code}")
        logger.info("MinerU 文件上传成功，系统自动开始解析")

    def _wait_batch_and_download(self, batch_id: str, out_dir: Path) -> Path:
        """轮询批量任务结果，完成后下载第一个文件的 ZIP。"""
        url = f"{self._api_base}{self._BATCH_RESULT_URL}/{batch_id}"
        start = time.monotonic()

        while True:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"MinerU 查询失败: {data.get('msg', resp.text)}")

            results = data.get("data", {}).get("extract_result", [])
            if not results:
                raise RuntimeError("MinerU 批量结果为空")

            file_result = results[0]
            state = file_result.get("state", "")

            if state == "done":
                zip_url = file_result.get("full_zip_url", "")
                if not zip_url:
                    raise RuntimeError("MinerU 完成但缺少 full_zip_url")
                return self._download_zip(zip_url, out_dir)

            if state == "failed":
                err = file_result.get("err_msg", "unknown")
                raise RuntimeError(f"MinerU 解析失败: {err}")

            if time.monotonic() - start > self._TASK_MAX_WAIT:
                raise TimeoutError(f"MinerU 任务超时 ({self._TASK_MAX_WAIT}s)")

            logger.debug("MinerU 处理中: state=%s", state)
            time.sleep(self._TASK_POLL_INTERVAL)

    @staticmethod
    def _download_zip(zip_url: str, out_dir: Path) -> Path:
        """下载结果 ZIP 并解压，返回解压目录。"""
        resp = requests.get(zip_url, timeout=120)
        resp.raise_for_status()

        zip_path = out_dir / "mineru_output.zip"
        zip_path.write_bytes(resp.content)

        extract_dir = out_dir / "mineru_output"
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        logger.info("MinerU 结果已解压到 %s", extract_dir)
        return extract_dir

    @staticmethod
    def _parse_mineru_output(extract_dir: Path) -> tuple[str, list[dict[str, Any]]]:
        """从 MinerU 输出目录读取 full.md 和 content_list.json。"""
        # 查找 full.md
        md_files = list(extract_dir.glob("**/full.md"))
        if not md_files:
            raise RuntimeError("MinerU 输出中找不到 full.md")
        md_text = md_files[0].read_text(encoding="utf-8")

        # 查找 content_list.json
        cl_files = list(extract_dir.glob("**/*_content_list.json"))
        if not cl_files:
            cl_files = list(extract_dir.glob("**/content_list.json"))
        blocks: list[dict[str, Any]] = []
        if cl_files:
            blocks = json.loads(cl_files[0].read_text(encoding="utf-8"))
            if not isinstance(blocks, list):
                blocks = []

        return md_text, blocks

    # ── 链接：PyMuPDF 提取 + bbox 匹配 + 注入 Markdown ─────────────

    def _inject_links(
        self,
        pdf: fitz.Document,
        md_text: str,
        mineru_blocks: list[dict[str, Any]],
    ) -> str:
        """提取 PDF 超链接，通过 bbox 匹配关联到 MinerU 文本块，注入 [锚文字](URI)。"""
        # 所有可读内容块（含 header/footer/aside_text/page_footnote）都参与链接匹配
        readable_blocks: list[dict[str, Any]] = [
            b for b in mineru_blocks
            if b.get("type") in ("text", "page_number", "header", "footer",
                                 "aside_text", "page_footnote")
            and (b.get("text", "").strip() or b.get("img_path", ""))
        ]

        # 按页分组
        blocks_by_page: dict[int, list[dict[str, Any]]] = {}
        for b in readable_blocks:
            page_idx = b.get("page_idx", 0)
            blocks_by_page.setdefault(page_idx, []).append(b)

        links_injected = 0
        for page_num in range(pdf.page_count):
            page = pdf[page_num]
            pw, ph = page.rect.width, page.rect.height
            page_blocks = blocks_by_page.get(page_num, [])

            for link in page.get_links():
                uri = link.get("uri", "")
                if not uri or not uri.startswith(("http://", "https://")):
                    continue

                link_rect = link.get("from")
                if link_rect is None:
                    continue

                # link rect → 0-1000
                lr = fitz.Rect(link_rect)
                link_bbox = self._pdf_to_mineru(lr, pw, ph)

                # 找 bbox 交集最大的 text 块作为锚文字来源
                best = self._best_match(link_bbox, page_blocks)
                if best is None:
                    continue

                # 用 link rect 精确取锚文字，回退到 text 块全文
                anchor = page.get_textbox(lr).strip()
                if not anchor:
                    anchor = best.get("text", "").strip()
                if not anchor:
                    continue

                # 避免在已是 Markdown 链接语法的文字上重复注入
                if f"[{anchor}]" in md_text:
                    continue

                # 用匹配块的文本定位，只在块内替换，避免同锚文字多处出现时换错位置
                injected = False
                block_text = best.get("text", "").strip()
                if block_text and block_text in md_text:
                    block_idx = md_text.find(block_text)
                    anchor_pos = md_text.find(anchor, block_idx,
                                              block_idx + len(block_text))
                    if anchor_pos >= 0:
                        md_text = (
                            md_text[:anchor_pos]
                            + f"[{anchor}]({uri})"
                            + md_text[anchor_pos + len(anchor):]
                        )
                        injected = True

                if not injected:
                    # 锚文字不在匹配块范围内（被 MinerU 过滤），追到文末
                    md_text += f"\n[{anchor}]({uri})"
                links_injected += 1

        logger.info("MinerU 链接注入: %d 个", links_injected)
        return md_text

    @staticmethod
    def _pdf_to_mineru(rect: fitz.Rect, page_width: float, page_height: float) -> list[float]:
        """PDF 坐标 → MinerU 0-1000 归一化坐标。"""
        s = PdfParser._BBOX_NORM
        return [
            rect.x0 / page_width * s,
            rect.y0 / page_height * s,
            rect.x1 / page_width * s,
            rect.y1 / page_height * s,
        ]

    @staticmethod
    def _best_match(
        target_bbox: list[float],
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """在 blocks 中按 bbox 交集面积找最佳匹配。"""
        best, best_area = None, 0.0
        tr = fitz.Rect(target_bbox)
        for b in blocks:
            br = fitz.Rect(b.get("bbox", [0, 0, 0, 0]))
            if tr.intersects(br):
                area = (tr & br).get_area()
                if area > best_area:
                    best_area = area
                    best = b
        return best

    # ── 图片：PyMuPDF 提取 + bbox 匹配 + 替换 MarkdownParser 产出的 Asset ──

    def _fix_image_assets(
        self,
        result: ParseResult,
        pdf: fitz.Document,
        mineru_blocks: list[dict[str, Any]],
    ) -> None:
        """用 PyMuPDF 嵌入图片替换 MinerU image 块对应的 MarkdownParser Asset。

        MinerU OCR 模式下嵌入图片已被转为文本，不重复提取。
        仅当 MinerU 明确标记 image 块时才用 PyMuPDF 替换为嵌入二进制。
        """
        image_blocks = [b for b in mineru_blocks if b.get("type") == "image"]
        if not image_blocks:
            return

        # 收集 PyMuPDF 图片信息
        pymupdf_images: list[dict[str, Any]] = []
        for page_num in range(pdf.page_count):
            page = pdf[page_num]
            try:
                for info in page.get_image_info():
                    pymupdf_images.append({
                        "xref": info.get("number"),
                        "bbox": info.get("bbox"),
                        "page": page_num,
                    })
            except Exception:
                continue

        fixed = 0
        for img_block in image_blocks:
            page_idx = img_block.get("page_idx", 0)
            mineru_bbox = img_block.get("bbox", [0, 0, 0, 0])
            page = pdf[page_idx]
            pw, ph = page.rect.width, page.rect.height
            pdf_bbox = self._mineru_to_pdf(mineru_bbox, pw, ph)

            for pm_img in pymupdf_images:
                if pm_img["page"] != page_idx or pm_img["bbox"] is None:
                    continue
                if not fitz.Rect(pdf_bbox).intersects(fitz.Rect(pm_img["bbox"])):
                    continue

                try:
                    base_image = pdf.extract_image(pm_img["xref"])
                    image_bytes = base_image.get("image")
                except Exception:
                    continue
                if not image_bytes:
                    continue

                img_path = img_block.get("img_path", "")
                target_asset = self._find_asset_by_path(result, img_path)
                if target_asset is not None:
                    content_hash = f"sha256:{hashlib.sha256(image_bytes).hexdigest()}"
                    object.__setattr__(target_asset, "_data", image_bytes)
                    target_asset.content_hash = content_hash
                    target_asset.asset_type = AssetType.image
                    target_asset.original_uri = ""
                    target_asset.metadata["source"] = "pdf_image"
                    target_asset.metadata["width"] = base_image.get("width")
                    target_asset.metadata["height"] = base_image.get("height")
                    fixed += 1
                break

        logger.info("MinerU 图片修复: %d/%d 个", fixed, len(image_blocks))

    @staticmethod
    def _mineru_to_pdf(
        mineru_bbox: list[float],
        page_width: float,
        page_height: float,
    ) -> list[float]:
        """MinerU 0-1000 坐标 → PDF 坐标。"""
        s = PdfParser._BBOX_NORM
        return [
            mineru_bbox[0] / s * page_width,
            mineru_bbox[1] / s * page_height,
            mineru_bbox[2] / s * page_width,
            mineru_bbox[3] / s * page_height,
        ]

    @staticmethod
    def _find_asset_by_path(result: ParseResult, img_path: str) -> Asset | None:
        """在 ParseResult 中查找 original_uri 尾缀匹配 img_path 的 Asset。"""
        if not img_path:
            return None
        for asset in result.assets:
            if asset.original_uri and asset.original_uri.endswith(img_path):
                return asset
            # 也可能只存了文件名
            if asset.original_uri and Path(img_path).name in asset.original_uri:
                return asset
        return None

    # ── element_id 回填 ─────────────────────────────────────────────

    @staticmethod
    def _backfill_element_ids(result: ParseResult) -> None:
        """通过 element.asset_data 回填 Asset.element_id。"""
        for el in result.elements:
            for ad in el.asset_data:
                for asset in result.assets:
                    if asset.asset_id == ad.asset_id and not asset.element_id:
                        asset.element_id = el.element_id


# ══════════════════════════════════════════════════════════════════════════
# _LocalPdfParser — 纯本地 PyMuPDF 解析，MinerU 不可用时的兜底方案
# ══════════════════════════════════════════════════════════════════════════

class _LocalPdfParser(DocumentParser):
    """纯本地 PyMuPDF PDF 解析器。

    字体启发式标题检测 + 跨页重复检测过滤页眉页脚 +
    PyMuPDF find_tables 表格识别 + span bbox 精确链接匹配。
    不依赖任何外部 API。
    """

    SUPPORTED_TYPES = {"pdf"}

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not content:
            raise ValueError("PDF 解析失败：文档内容为空")
        try:
            pdf = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"PDF 解析失败：{exc}") from exc
        if pdf.is_encrypted:
            pdf.close()
            raise ValueError("PDF 解析失败：文档已加密")
        if pdf.page_count == 0:
            pdf.close()
            raise ValueError("PDF 解析失败：文档无页面")

        state = _LocalPdfState(doc.doc_id, doc.version)
        try:
            toc_entries = self._build_toc_map(pdf)
            blocks_by_page: dict[int, list[_TextBlock]] = {}
            all_blocks: list[_TextBlock] = []
            for page_num in range(pdf.page_count):
                page = pdf[page_num]
                page_blocks = self._extract_blocks(page, page_num + 1)
                all_blocks.extend(page_blocks)
                if page_blocks:
                    blocks_by_page[page_num + 1] = page_blocks
            header_footer_keys = self._detect_header_footer_blocks(all_blocks, pdf.page_count)
            for page_num in range(pdf.page_count):
                page = pdf[page_num]
                page_number = page_num + 1
                page_height = page.rect.height
                page_titles = toc_entries.get(page_number, [])
                page_blocks = [
                    b for b in blocks_by_page.get(page_number, [])
                    if not self._is_header_footer(b, header_footer_keys, page_height)
                ]
                merged_blocks = self._merge_adjacent_blocks(page_blocks)
                self._process_page(page, page_number, merged_blocks, page_titles, state, doc, pdf)
            text_elements = [el for el in state.elements if el.element_type != ElementType.unknown]
            if not text_elements:
                raise ValueError("PDF 解析失败：无可提取的文本内容")
            doc.source_hash = compute_hash(content)
            return ParseResult(doc=doc, elements=state.elements, assets=state.assets)
        except ValueError:
            raise
        finally:
            try:
                pdf.close()
            except Exception:
                pass

    # ── TOC ──

    @staticmethod
    def _build_toc_map(pdf: fitz.Document) -> dict[int, list[tuple[int, str]]]:
        toc_map: dict[int, list[tuple[int, str]]] = {}
        try:
            toc = pdf.get_toc(simple=True)
        except Exception:
            return toc_map
        for entry in toc:
            if len(entry) != 3:
                continue
            level, title, page_num = entry
            title = title.strip()
            if not title:
                continue
            toc_map.setdefault(int(page_num), []).append((int(level), title))
        for page_num in toc_map:
            toc_map[page_num].sort(key=lambda item: item[0])
        return toc_map

    # ── 文本块提取 ──

    @staticmethod
    def _extract_blocks(page: fitz.Page, page_number: int) -> list[_TextBlock]:
        blocks: list[_TextBlock] = []
        try:
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        except Exception:
            return blocks
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            bbox = block["bbox"]
            y0, y1 = bbox[1], bbox[3]
            x0, x1 = bbox[0], bbox[2]
            all_text_parts: list[str] = []
            font_sizes: list[float] = []
            font_flags: list[int] = []
            font_names: list[str] = []
            span_bboxes: list[tuple[str, tuple[float, float, float, float]]] = []
            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                    font_sizes.append(span.get("size", 0))
                    font_flags.append(span.get("flags", 0))
                    font_names.append(span.get("font", ""))
                    span_bboxes.append((span.get("text", ""), tuple(span.get("bbox", (0, 0, 0, 0)))))
                all_text_parts.append(line_text)
            combined_text = " ".join(part for part in all_text_parts if part).strip()
            if not combined_text:
                continue
            avg_font_size = statistics.mean(font_sizes) if font_sizes else 0.0
            has_bold_flag = any(f & 16 for f in font_flags)
            has_bold_name = any("bold" in fn.lower() for fn in font_names)
            is_bold = has_bold_flag or has_bold_name
            blocks.append(_TextBlock(
                page=page_number, y0=y0, y1=y1, x0=x0, x1=x1,
                text=combined_text, font_size=avg_font_size, is_bold=is_bold,
                bbox=tuple(bbox), span_bboxes=span_bboxes,
            ))
        blocks.sort(key=lambda b: (b.y0, b.x0))
        return blocks

    # ── 页眉页脚 ──

    def _detect_header_footer_blocks(self, all_blocks: list[_TextBlock], page_count: int) -> set[tuple[int, str]]:
        if page_count < HEADER_FOOTER_MIN_REPEAT_PAGES:
            return set()
        repeat_map: dict[tuple[int, str], set[int]] = {}
        for block in all_blocks:
            text = block.text.strip()
            if not text:
                continue
            y_bucket = int(block.y0 / 10) * 10
            key = (y_bucket, text)
            repeat_map.setdefault(key, set()).add(block.page)
        return {key for key, pages in repeat_map.items() if len(pages) >= HEADER_FOOTER_MIN_REPEAT_PAGES}

    @staticmethod
    def _is_header_footer(block: _TextBlock, header_footer_keys: set[tuple[int, str]], page_height: float) -> bool:
        text = block.text.strip()
        if not text:
            return True
        y_bucket = int(block.y0 / 10) * 10
        if (y_bucket, text) in header_footer_keys:
            return True
        if block.y0 < page_height * HEADER_FOOTER_Y_MARGIN:
            if block.font_size <= HEADER_FOOTER_FONT_MAX and len(text) <= HEADER_FOOTER_MAX_CHARS:
                return True
        if block.y1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
            if block.font_size <= HEADER_FOOTER_FONT_MAX and len(text) <= HEADER_FOOTER_MAX_CHARS:
                return any(pat.search(text) for pat in PAGE_NUMBER_PATTERNS) or True
        return False

    # ── 块合并 ──

    @staticmethod
    def _merge_adjacent_blocks(blocks: list[_TextBlock]) -> list[_TextBlock]:
        if not blocks:
            return []
        merged: list[_TextBlock] = []
        current = blocks[0]
        for next_block in blocks[1:]:
            same_font = abs(current.font_size - next_block.font_size) < 0.5 and current.is_bold == next_block.is_bold
            gap = next_block.y0 - current.y1
            threshold = current.font_size * PARAGRAPH_GAP_RATIO if current.font_size > 0 else 12.0
            if same_font and gap <= max(threshold, 2.0):
                combined = f"{current.text} {next_block.text}".strip()
                merged_span_bboxes = current.span_bboxes + next_block.span_bboxes
                current = _TextBlock(
                    page=current.page, y0=current.y0, y1=next_block.y1,
                    x0=min(current.x0, next_block.x0), x1=max(current.x1, next_block.x1),
                    text=combined, font_size=current.font_size, is_bold=current.is_bold,
                    bbox=(min(current.bbox[0], next_block.bbox[0]),
                          min(current.bbox[1], next_block.bbox[1]),
                          max(current.bbox[2], next_block.bbox[2]),
                          max(current.bbox[3], next_block.bbox[3])),
                    span_bboxes=merged_span_bboxes,
                )
            else:
                merged.append(current)
                current = next_block
        merged.append(current)
        return merged

    # ── 页面处理 ──

    def _process_page(self, page: fitz.Page, page_number: int, blocks: list[_TextBlock],
                      toc_titles: list[tuple[int, str]], state: _LocalPdfState,
                      doc: Document, pdf: fitz.Document) -> None:
        for level, title in toc_titles:
            self._add_title(state, title, level, page_number)
        table_regions = self._detect_tables(page)
        table_y_ranges: list[tuple[float, float]] = []
        for table_data in table_regions:
            table_block = self._add_table(table_data, page_number, state, page, doc)
            if table_block is not None:
                table_y_ranges.append((table_block.y0, table_block.y1))
        block_to_element: dict[int, int] = {}
        for bi, block in enumerate(blocks):
            if self._in_table_region(block, table_y_ranges):
                continue
            self._add_text_block(block, state, page_number, doc)
            block_to_element[bi] = len(state.elements) - 1
        self._match_links_to_blocks(page, blocks, block_to_element, state, doc, page_number)
        self._extract_page_images(page, page_number, state, doc, pdf)
        self._asset_ids_for_page_links(page, state, doc, page_number)

    # ── 链接匹配 ──

    def _match_links_to_blocks(self, page: fitz.Page, blocks: list[_TextBlock],
                               block_to_element: dict[int, int], state: _LocalPdfState,
                               doc: Document, page_number: int) -> None:
        try:
            links = page.get_links()
        except Exception:
            return
        page_height = page.rect.height
        for link in links:
            uri = link.get("uri", "")
            if not uri or not uri.startswith(("http://", "https://")):
                continue
            link_rect = link.get("from")
            if link_rect is None:
                continue
            lr = fitz.Rect(link_rect)
            if lr.y0 < page_height * HEADER_FOOTER_Y_MARGIN:
                continue
            if lr.y1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
                continue
            best_match: tuple[int, str, float] | None = None
            for bi, block in enumerate(blocks):
                if bi not in block_to_element:
                    continue
                for span_text, span_bbox in block.span_bboxes:
                    sr = fitz.Rect(span_bbox)
                    if sr.intersects(lr):
                        ratio = (sr & lr).get_area() / max(sr.get_area(), 1.0)
                        if ratio >= 0.1:
                            if best_match is None or ratio > best_match[2]:
                                best_match = (bi, span_text, ratio)
            if best_match is not None:
                bi, anchor_text, _ = best_match
                ei = block_to_element[bi]
                element = state.elements[ei]
                asset_type = self._asset_type_for_url(uri, anchor_text)
                if asset_type is not None:
                    display_text = anchor_text if anchor_text and anchor_text != uri else ""
                    asset = self._asset_for_url(uri, asset_type, state, doc, {}, display_text=display_text)
                    if not any(ad.asset_id == asset.asset_id for ad in element.asset_data):
                        ph = state.next_ph(asset_type.value)
                        element.asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                    if not asset.element_id:
                        asset.element_id = element.element_id

    # ── 标题 ──

    def _add_title(self, state: _LocalPdfState, text: str, level: int, page_number: int) -> None:
        while len(state._section_path) >= level:
            state._section_path.pop()
        state._section_path.append(text)
        self._append_element(state, ParsedElement(
            doc_id=state.doc_id, doc_version=state.doc_version,
            sequence_order=state._next_seq(), element_type=ElementType.title, text=text,
            source_location=SourceLocation(page=page_number, section_path=list(state._section_path)),
            metadata={"heading_level": level},
        ))

    def _add_text_block(self, block: _TextBlock, state: _LocalPdfState,
                        page_number: int, doc: Document) -> None:
        text = block.text.strip()
        if not text:
            return
        is_heading = False
        heading_level = 1
        if block.font_size >= TITLE_FONT_SIZE_THRESHOLD and len(text) <= MAX_TITLE_CHARS:
            is_heading = True
            if block.font_size >= 18:
                heading_level = 1
            elif block.font_size >= 16:
                heading_level = 2
            else:
                heading_level = 3
        elif (BOLD_TITLE_MIN_SIZE <= block.font_size <= BOLD_TITLE_MAX_SIZE
              and block.is_bold and len(text) <= MAX_TITLE_CHARS):
            is_heading = True
            heading_level = 3
        if is_heading:
            while len(state._section_path) >= heading_level:
                state._section_path.pop()
            state._section_path.append(text)
            element_type = ElementType.title
            metadata: dict[str, Any] = {"heading_level": heading_level}
        else:
            element_type = ElementType.paragraph
            metadata: dict[str, Any] = {}
        self._append_element(state, ParsedElement(
            doc_id=state.doc_id, doc_version=state.doc_version,
            sequence_order=state._next_seq(), element_type=element_type, text=text,
            source_location=SourceLocation(page=page_number, section_path=list(state._section_path)),
            metadata=metadata,
        ))

    # ── 表格 ──

    @staticmethod
    def _detect_tables(page: fitz.Page) -> list[dict[str, Any]]:
        if not hasattr(page, "find_tables"):
            return []
        try:
            tables = page.find_tables()
        except Exception:
            return []
        if tables is None:
            return []
        result: list[dict[str, Any]] = []
        for table in tables:
            try:
                extracted = table.extract()
                if not extracted or len(extracted) < 2:
                    continue
                ncols = len(extracted[0]) if extracted else 0
                result.append({
                    "headers": [{"text": str(cell or "")} for cell in extracted[0]],
                    "rows": extracted[1:],
                    "bbox": getattr(table, "bbox", None),
                    "cells_bbox": getattr(table, "cells", None),
                    "ncols": ncols,
                })
            except Exception:
                continue
        return result

    def _add_table(self, table_data: dict[str, Any], page_number: int,
                   state: _LocalPdfState, page: fitz.Page | None = None,
                   doc: Document | None = None) -> _TextBlock | None:
        headers = table_data["headers"]
        raw_rows = table_data["rows"]
        if not raw_rows:
            return None
        table_asset_ids: list[Asset] = []
        cell_bboxes = table_data.get("cells_bbox")
        ncols = table_data.get("ncols", 0)
        links = page.get_links() if page is not None else []
        if cell_bboxes and ncols and links:
            for cell_idx, cell_bbox in enumerate(cell_bboxes):
                for link in links:
                    lr = fitz.Rect(link.get("from", (0, 0, 0, 0)))
                    if fitz.Rect(cell_bbox).intersects(lr):
                        uri = link.get("uri", "")
                        if not uri:
                            continue
                        asset_type = self._asset_type_for_url(uri)
                        if doc is not None:
                            asset = self._asset_for_url(uri, asset_type, state, doc, {})
                            table_asset_ids.append(asset)
                        break
        rows: list[dict[str, Any]] = []
        for row in raw_rows:
            rows.append({"cells": [{"text": str(cell or "")} for cell in row]})
        structured: dict[str, Any] = {"table": {"caption": "", "headers": headers, "rows": rows}}
        text_parts: list[str] = []
        if headers:
            text_parts.append(" | ".join(h["text"] for h in headers))
        for row in rows:
            text_parts.append(" | ".join(cell["text"] for cell in row["cells"]))
        table_asset_data: list[AssetData] = []
        for a in {a.asset_id: a for a in table_asset_ids}.values():
            ph = state.next_ph(a.asset_type.value)
            table_asset_data.append(AssetData(placeholder=ph, asset_id=a.asset_id))
        self._append_element(state, ParsedElement(
            doc_id=state.doc_id, doc_version=state.doc_version,
            sequence_order=state._next_seq(), element_type=ElementType.table,
            text="\n".join(part for part in text_parts if part.strip()),
            structured_data=structured, asset_data=table_asset_data,
            source_location=SourceLocation(page=page_number, section_path=list(state._section_path)),
            metadata={},
        ))
        bbox = table_data.get("bbox")
        if bbox:
            return _TextBlock(page=page_number, y0=bbox[1], y1=bbox[3],
                             x0=bbox[0], x1=bbox[2], text="", font_size=0,
                             is_bold=False, bbox=tuple(bbox))
        return None

    @staticmethod
    def _in_table_region(block: _TextBlock, table_y_ranges: list[tuple[float, float]]) -> bool:
        for y0, y1 in table_y_ranges:
            if not (block.y1 < y0 or block.y0 > y1):
                return True
        return False

    # ── 图片 ──

    def _extract_page_images(self, page: fitz.Page, page_number: int,
                             state: _LocalPdfState, doc: Document, pdf: fitz.Document) -> None:
        image_list = page.get_images(full=True)
        if not image_list:
            return
        page_height = page.rect.height
        image_bboxes: dict[int, tuple[float, float, float, float]] = {}
        try:
            for info in page.get_image_info():
                idx = info.get("number")
                bbox = info.get("bbox")
                if idx is not None and bbox is not None:
                    image_bboxes[idx] = tuple(bbox)
        except Exception:
            pass
        for idx, img in enumerate(image_list):
            xref = img[0]
            if idx in image_bboxes:
                _by0, _by1 = image_bboxes[idx][1], image_bboxes[idx][3]
                if _by0 < page_height * HEADER_FOOTER_Y_MARGIN:
                    continue
                if _by1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
                    continue
            try:
                base_image = pdf.extract_image(xref)
            except Exception:
                continue
            image_bytes = base_image.get("image")
            if not image_bytes:
                continue
            content_hash_val = f"sha256:{hashlib.sha256(image_bytes).hexdigest()}"
            key = ("image", content_hash_val)
            existing = state.assets_by_key.get(key)
            if existing is not None:
                asset = existing.asset
            else:
                ext = base_image.get("ext", "png")
                filename = f"pdf-image-p{page_number}-{xref}.{ext}"
                asset = Asset(
                    doc_id=doc.doc_id, asset_type=AssetType.image, original_uri="",
                    storage_uri=None, content_hash=content_hash_val,
                    status=AssetStatus.ready, extracted_text=None,
                    metadata={"page": page_number, "xref": xref, "file_name": filename,
                              "source": "pdf_image", "width": base_image.get("width"),
                              "height": base_image.get("height")},
                )
                object.__setattr__(asset, "_data", image_bytes)
                state.assets.append(asset)
                state.assets_by_key[key] = _AssetRecord(asset=asset, key=key)
            ph = state.next_ph("image")
            self._append_element(state, ParsedElement(
                doc_id=state.doc_id, doc_version=state.doc_version,
                sequence_order=state._next_seq(), element_type=ElementType.paragraph, text=ph,
                asset_data=[AssetData(placeholder=ph, asset_id=asset.asset_id)],
                source_location=SourceLocation(page=page_number, section_path=list(state._section_path)),
                metadata={"page": page_number, "xref": xref, "file_name": filename},
            ))

    # ── 孤立链接兜底 ──

    def _asset_ids_for_page_links(self, page: fitz.Page, state: _LocalPdfState,
                                  doc: Document, page_number: int) -> None:
        try:
            links = page.get_links()
        except Exception:
            return
        page_height = page.rect.height
        for link in links:
            uri = link.get("uri", "")
            if not uri or not uri.startswith(("http://", "https://")):
                continue
            link_rect = link.get("from")
            if link_rect is not None:
                lr = fitz.Rect(link_rect)
                if lr.y0 < page_height * HEADER_FOOTER_Y_MARGIN:
                    continue
                if lr.y1 > page_height * (1 - HEADER_FOOTER_Y_MARGIN):
                    continue
            asset_type = self._asset_type_for_url(uri)
            if (asset_type.value, uri) in state.assets_by_key:
                continue
            asset = self._asset_for_url(uri, asset_type, state, doc, {})
            for el in reversed(state.elements):
                if not any(ad.asset_id == asset.asset_id for ad in el.asset_data):
                    ph = state.next_ph(asset_type.value)
                    el.asset_data.append(AssetData(placeholder=ph, asset_id=asset.asset_id))
                if not asset.element_id:
                    asset.element_id = el.element_id
                break

    # ── 资源管理 ──

    def _asset_for_url(self, url: str, asset_type: AssetType, state: _LocalPdfState,
                       doc: Document, metadata: dict[str, Any], display_text: str = "") -> Asset:
        key = (asset_type.value, url)
        existing = state.assets_by_key.get(key)
        if existing is not None:
            return existing.asset
        asset = Asset(
            doc_id=doc.doc_id, asset_type=asset_type, original_uri=url,
            display_text=display_text, storage_uri=None, status=AssetStatus.ready,
            extracted_text=None, metadata={**metadata},
        )
        state.assets.append(asset)
        state.assets_by_key[key] = _AssetRecord(asset=asset, key=key)
        return asset

    def _asset_type_for_url(self, url: str, link_text: str = "") -> AssetType:
        """URL 后缀优先 → 锚文字兜底 → web_link。"""
        return classify_link_url_first(url, link_text)

    def _is_video_url(self, url: str) -> bool:
        return bool(VIDEO_URL_RE.search(url or ""))

    @staticmethod
    def _is_attachment_url(url: str) -> bool:
        path = url.split("?", 1)[0]
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in ATTACHMENT_EXTENSIONS if suffix else False

    @staticmethod
    def _is_image_url(url: str) -> bool:
        path = url.split("?", 1)[0]
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in IMAGE_EXTENSIONS if suffix else False

    @staticmethod
    def _append_element(state: _LocalPdfState, element: ParsedElement) -> None:
        asset_ids = {ad.asset_id for ad in element.asset_data}
        for record in state.assets_by_key.values():
            if record.asset.asset_id in asset_ids and not record.asset.element_id:
                record.asset.element_id = element.element_id
        state.elements.append(element)
