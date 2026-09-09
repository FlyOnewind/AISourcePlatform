"""语义抽取模块 — 通过 LLM 将解析元素转换为结构化的知识块。

核心流程：
1. 全文优先：token 不超安全阈值时所有元素一次提交 LLM
2. 递进降级：超限时按标题层级递进切分（h1→h2→h3→…），只以 token 是否超限为降级判断
3. 语义切分兜底：标题耗尽后用 embedding 相似度断点切分
4. Token 硬切兜底：embedding 不可用时按 token 上限硬切 + 20% 重叠
5. LLM 失败或返回空结果 → _fallback_chunks 纯文本拼接，不再触发进一步切分
"""

import json
import logging
from typing import Any

from app.core.config import settings
from app.core.models import (
    Asset,
    AssetRef,
    KnowledgeChunk,
    KnowledgeType,
    ParsedElement,
    SourceRef,
    compute_hash,
)
from llm.prompts import build_extraction_messages
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)


def _safe_knowledge_type(raw_value: str | None) -> KnowledgeType:
    """将原始 knowledge_type 字符串安全转换为 KnowledgeType 枚举。
    未知或缺失值时回退为 declarative。"""
    if raw_value is None:
        return KnowledgeType.declarative
    try:
        return KnowledgeType(raw_value)
    except ValueError:
        logger.warning("Unknown knowledge_type '%s', falling back to declarative", raw_value)
        return KnowledgeType.declarative


EXTRACT_SCHEMA = {"required": ["chunks"]}


class SemanticExtractor:
    """语义抽取器 — 通过 LLM 将 ParsedElement 列表转换为 KnowledgeChunk 列表。

    全文优先策略：95%+ 的文档一次 LLM 调用即可完成抽取。
    极端大文档触发递进降级：元素数量超限分批 → h1 → h2 → h3 → … → embedding 切分 → token 硬切。
    LLM 不可用或返回空结果时自动回退为 fallback chunk。
    """

    def __init__(self) -> None:
        self._max_tokens = settings.max_window_tokens
        # 单次 LLM 调用的输入 Token 上限（估算值，默认 102400 = context 的 40%）
        # 实际发送时约 ×1.5（JSON 结构 + asset 描述）≈ 164K，占 context 64%
        # + 输出 65536 (26%) + prompt 5000 (2%) → 总计 234K / 256K（92%），8% 余量
        self._single_call_token_limit = settings.max_window_tokens

    # ── 公共入口 ─────────────────────────────────────────────────────

    def extract(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str = "通用",
    ) -> list[KnowledgeChunk]:
        """主入口：Token 判定 → 单次或递归切分。

        1. Token ≤ 上限 → 单次 LLM 调用（>99.9% 文档走此路径）
        2. Token > 上限 → _split_recursive 按标题层级递进切分，最终兜底 Token 滑窗硬切
        """
        if not elements:
            return []

        estimated = self._estimate_tokens(elements)

        if estimated <= self._single_call_token_limit:
            return self._try_extract_or_fallback(elements, assets, category)

        logger.info(
            "Token %d 超过单次上限 %d → 递归切分",
            estimated, self._single_call_token_limit,
        )
        return self._split_recursive(elements, assets, category, level=1)

    # ── LLM 抽取 + fallback 统一入口 ─────────────────────────────────

    def _try_extract_or_fallback(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """尝试 LLM 抽取；失败或返回空结果时直接走 _fallback_chunks。

        此方法是所有 LLM 调用的唯一出口，确保 LLM 失败不会触发进一步切分。
        """
        try:
            chunks = self._extract_section(elements, assets, category)
            if self._chunks_have_content(chunks):
                return chunks
            logger.warning("LLM 返回空结果，使用 fallback chunks")
        except Exception:
            logger.exception("LLM 调用失败，使用 fallback chunks")
        return self._fallback_chunks(elements, assets, category)

    @staticmethod
    def _chunks_have_content(chunks: list[KnowledgeChunk]) -> bool:
        """检查 chunk 列表是否有实际文本内容。"""
        if not chunks:
            return False
        return any(c.content.strip() for c in chunks)

    # ── 递进降级切分 ──────────────────────────────────────────────

    def _split_at_heading_level(
        self, elements: list[ParsedElement], level: int
    ) -> list[list[ParsedElement]]:
        """在指定 heading_level 处切分 elements。

        返回 sections 列表，每个 section 以该层级的标题元素开头。
        如果整个 elements 中没有目标层级的标题，返回单元素包装列表。
        """
        sections: list[list[ParsedElement]] = []
        current: list[ParsedElement] = []

        for el in elements:
            if (
                el.element_type.value == "title"
                and el.metadata.get("heading_level") == level
            ):
                if current:
                    sections.append(current)
                current = [el]
            else:
                current.append(el)

        if current:
            sections.append(current)

        return sections

    def _split_recursive(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
        level: int,
    ) -> list[KnowledgeChunk]:
        """递进切分核心：在 level 层级切分，仅对 token 超限的 section 继续下钻。

        - token 未超限 → _try_extract_or_fallback（LLM 失败直接 fallback，不下钻）
        - token 超限 → 按 level 标题切分
          - 切出多个 section → 逐个判断：未超限走 LLM，超限递归 level+1
          - 切不出（无该层级标题）→ _split_deeper_or_semantic
        """
        if not elements:
            return []

        estimated = self._estimate_tokens(elements)
        if estimated < self._single_call_token_limit:
            return self._try_extract_or_fallback(elements, assets, category)

        # 在当前层级切分
        sections = self._split_at_heading_level(elements, level)
        if len(sections) <= 1:
            # 该层级没有可用的标题切割点，尝试更深层或语义切分
            return self._split_deeper_or_semantic(elements, assets, category, level)

        all_chunks: list[KnowledgeChunk] = []
        for section in sections:
            section_est = self._estimate_tokens(section)
            if section_est < self._single_call_token_limit:
                all_chunks.extend(
                    self._try_extract_or_fallback(section, assets, category)
                )
            else:
                # 超限，下钻到更深层级
                all_chunks.extend(
                    self._split_recursive(section, assets, category, level + 1)
                )

        return all_chunks

    def _split_deeper_or_semantic(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
        level: int,
    ) -> list[KnowledgeChunk]:
        """当前层级无更多标题时的降级链：更深层标题 → embedding 语义切分 → token 硬切。

        三条策略是递进降级关系（非并行），前一条成功即返回。
        """
        # 策略 1：尝试更深层标题（level+1 ~ level+3，最深到 6）
        for deeper_level in range(level + 1, min(level + 4, 7)):
            deeper_sections = self._split_at_heading_level(elements, deeper_level)
            if len(deeper_sections) > 1:
                all_chunks: list[KnowledgeChunk] = []
                for section in deeper_sections:
                    all_chunks.extend(
                        self._split_recursive(section, assets, category, deeper_level)
                    )
                return all_chunks

        # 策略 2：尝试 embedding 语义切分
        try:
            subsections = self._split_by_semantic(elements)
            if len(subsections) > 1:
                all_chunks: list[KnowledgeChunk] = []
                for sub in subsections:
                    sub_est = self._estimate_tokens(sub)
                    if sub_est < self._single_call_token_limit:
                        all_chunks.extend(
                            self._try_extract_or_fallback(sub, assets, category)
                        )
                    else:
                        # 语义切出的子段仍超限，token 硬切
                        all_chunks.extend(
                            self._split_section(sub, assets, category)
                        )
                return all_chunks
        except Exception:
            logger.exception("embedding 语义切分失败，降级为 token 硬切")

        # 策略 3：最终兜底 — token 硬切
        return self._split_section(elements, assets, category)

    def _split_by_semantic(
        self, elements: list[ParsedElement]
    ) -> list[list[ParsedElement]]:
        """相邻元素 embedding 相似度断点切分。

        计算相邻元素的 embedding 余弦相似度，在相似度最低的 30% 位置切分。
        空 text 元素（如图片占位符）不参与 embedding 计算，切分后归入前一段。
        embedding 不可用时返回原列表的单元素包装。
        """
        if len(elements) < 2:
            return [list(elements)]

        # 过滤出有文本内容的元素用于 embedding 计算
        text_indices: list[int] = []
        texts: list[str] = []
        for i, el in enumerate(elements):
            if el.text and el.text.strip():
                text_indices.append(i)
                texts.append(el.text)

        if len(texts) < 2:
            return [list(elements)]

        try:
            from llm.volcengine_client import embedding_client as emb_client

            vectors = emb_client.embed_text(texts)
            if len(vectors) != len(texts):
                return [list(elements)]

            # 计算相邻（有文本的）元素的相似度
            def _cosine(a: list[float], b: list[float]) -> float:
                dot = sum(x * y for x, y in zip(a, b))
                norm_a = sum(x * x for x in a) ** 0.5
                norm_b = sum(x * x for x in b) ** 0.5
                if norm_a == 0 or norm_b == 0:
                    return 0.0
                return dot / (norm_a * norm_b)

            similarities: list[tuple[int, float]] = []  # (原始元素索引, 相似度)
            for j in range(len(vectors) - 1):
                orig_idx = text_indices[j]  # 相邻对中前一个元素在 elements 中的位置
                sim = _cosine(vectors[j], vectors[j + 1])
                similarities.append((orig_idx, sim))

            if not similarities:
                return [list(elements)]

            # 在相似度最低的 30% 位置切分
            sorted_sims = sorted(s[1] for s in similarities)
            threshold_idx = max(0, int(len(sorted_sims) * 0.3))
            threshold = sorted_sims[threshold_idx]
            split_indices = [
                idx + 1  # +1 使切分点在元素之后
                for idx, sim in similarities
                if sim <= threshold
            ]

            if not split_indices:
                return [list(elements)]

            # 按切分点构造子 sections
            sections: list[list[ParsedElement]] = []
            start = 0
            for idx in split_indices:
                if idx > start and idx < len(elements):
                    sections.append(elements[start:idx])
                    start = idx
            if start < len(elements):
                sections.append(elements[start:])
            return sections if len(sections) > 1 else [list(elements)]
        except Exception:
            logger.exception("embedding 相似度计算失败")
            return [list(elements)]

    def _split_section(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """Token 硬切兜底：段落边界切分 + 20% 重叠 + 逐段 LLM 抽取。

        每段先尝试 LLM，失败后走 _fallback_chunks 纯文本兜底。
        """
        if not elements:
            return []

        result_chunks: list[KnowledgeChunk] = []
        current: list[ParsedElement] = []
        current_tokens = 0
        overlap_count = max(1, int(len(elements) * 0.2))

        for i, el in enumerate(elements):
            el_tokens = self._estimate_tokens([el])
            if current_tokens + el_tokens > self._max_tokens and current:
                # 当前窗口已满，抽取
                result_chunks.extend(
                    self._try_extract_or_fallback(current, assets, category)
                )

                # 重叠：保留尾部 20% 元素作为上下文衔接
                overlap_start = max(0, len(current) - overlap_count)
                current = current[overlap_start:] + [el]
                current_tokens = (
                    self._estimate_tokens(current[:overlap_count]) + el_tokens
                )
            else:
                current.append(el)
                current_tokens += el_tokens

        if current:
            result_chunks.extend(
                self._try_extract_or_fallback(current, assets, category)
            )

        return result_chunks

    # ── Token 估算 ──────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(elements: list[ParsedElement]) -> int:
        """粗略 token 估算：中文约 1.8 字符/token，除数 1.2 含 JSON 结构和 prompt 模板的补偿。"""
        parts: list[str] = []
        for el in elements:
            if el.text:
                parts.append(el.text)
            if el.structured_data:
                parts.append(json.dumps(el.structured_data, ensure_ascii=False))
        text = " ".join(parts)
        return max(1, int(len(text) / 1.2))

    # ── LLM 抽取 ─────────────────────────────────────────────────────

    def _extract_section(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """对单个 section 调用 LLM 抽取知识块。

        异常直接抛出，由上层 _try_extract_or_fallback 处理降级路径。
        """
        title_path = self._get_title_path(elements)
        elements_json = self._elements_to_json(elements, assets)
        messages = build_extraction_messages(title_path, elements_json)

        data = llm_client.chat_json(messages, schema=EXTRACT_SCHEMA)
        return self._build_chunks(data, elements, assets, category)

    @staticmethod
    def _get_title_path(elements: list[ParsedElement]) -> list[str]:
        """从元素的 section_path 中提取标题路径。"""
        for el in elements:
            if el.source_location and el.source_location.section_path:
                return el.source_location.section_path
        return []

    @staticmethod
    def _elements_to_json(
        elements: list[ParsedElement],
        assets: list[Asset] | None = None,
    ) -> str:
        """将元素列表序列化为 LLM 输入 JSON，注入资源和视觉描述。

        每个元素携带自己的 asset_data（通过 asset_id 关联 Asset 获取类型和 URL）。
        标题元素注入 heading_level；代码元素注入 language 字段。
        """
        # 构造 Asset 查找表
        assets_by_id: dict[str, Asset] = {}
        if assets:
            assets_by_id = {a.asset_id: a for a in assets}

        items = []
        for el in elements:
            item: dict[str, Any] = {
                "element_id": el.element_id,
                "type": el.element_type.value,
                "text": el.text,
                "section_path": el.source_location.section_path,
            }
            if el.element_type.value == "title":
                heading_level = el.metadata.get("heading_level")
                if heading_level is not None:
                    item["heading_level"] = heading_level
            if el.element_type.value == "code" and el.structured_data:
                language = el.structured_data.get("language")
                if language:
                    item["language"] = language
            if el.structured_data:
                item["structured_data"] = el.structured_data

            # 注入元素级的资源映射（通过 asset_id 从 Asset 查找表获取类型）
            if el.asset_data:
                item["asset_data"] = []
                for ad in el.asset_data:
                    asset = assets_by_id.get(ad.asset_id)
                    item["asset_data"].append({
                        "placeholder": ad.placeholder,
                        "asset_id": ad.asset_id,
                        "type": asset.asset_type.value if asset else "unknown",
                    })

            # 注入 Asset 视觉描述（来自图片/视频 AI 分析）
            if assets:
                # 收集该元素关联的所有 Asset 的视觉描述
                element_asset_ids = {ad.asset_id for ad in el.asset_data}
                descriptions = []
                seen_ids: set[str] = set()
                for asset in assets:
                    if not asset.extracted_text:
                        continue
                    if asset.asset_id in seen_ids:
                        continue
                    # 通过 element_id 或 asset_id 关联
                    if asset.element_id == el.element_id or asset.asset_id in element_asset_ids:
                        seen_ids.add(asset.asset_id)
                        descriptions.append({
                            "asset_id": asset.asset_id,
                            "asset_type": asset.asset_type.value,
                            "description": asset.extracted_text,
                        })
                if descriptions:
                    item["asset_descriptions"] = descriptions

            items.append(item)

        return json.dumps(items, ensure_ascii=False, indent=2)

    def _build_chunks(
        self,
        data: dict,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """将 LLM 输出转换为 KnowledgeChunk 对象列表。

        不保留 relation 字段（该枚举已删除）；source_refs 为空时不强行全量兜底。
        """
        chunks: list[KnowledgeChunk] = []
        elements_by_id = {el.element_id: el for el in elements}
        assets_by_id = {a.asset_id: a for a in assets}

        for raw in data.get("chunks", []):
            content = raw.get("content", "")
            if not content:
                continue

            # ── 构造溯源引用 ──
            source_refs: list[SourceRef] = []
            seen_element_ids: set[str] = set()
            raw_source_refs = raw.get("source_refs")
            if not isinstance(raw_source_refs, list):
                raw_source_refs = []
            for raw_ref in raw_source_refs:
                if isinstance(raw_ref, dict):
                    eid = raw_ref.get("element_id")
                else:
                    continue
                el = elements_by_id.get(eid)
                if el and el.element_id not in seen_element_ids:
                    source_refs.append(
                        SourceRef(
                            doc_id=el.doc_id,
                            doc_version=el.doc_version,
                            element_id=el.element_id,
                            source_location=el.source_location,
                        )
                    )
                    seen_element_ids.add(el.element_id)

            # KnowledgeChunk 已不再保存独立 doc_id，source_refs 是文档归属的唯一依据。
            # LLM 未返回有效元素时回退到当前分段的全部元素，避免生成无法管理的孤儿知识块。
            if not source_refs:
                source_refs = [
                    SourceRef(
                        doc_id=el.doc_id,
                        doc_version=el.doc_version,
                        element_id=el.element_id,
                        source_location=el.source_location,
                    )
                    for el in elements
                ]

            # ── 构造资源引用 ──
            asset_refs: list[AssetRef] = []
            seen_asset_ids: set[str] = set()
            raw_asset_refs = raw.get("asset_refs")
            if not isinstance(raw_asset_refs, list):
                raw_asset_refs = []
            for raw_ref in raw_asset_refs:
                if isinstance(raw_ref, dict):
                    aid = raw_ref.get("asset_id")
                    caption = raw_ref.get("caption")
                else:
                    continue
                asset = assets_by_id.get(aid)
                if asset and asset.asset_id not in seen_asset_ids:
                    if not caption:
                        caption = (
                            asset.display_text
                            or f"{asset.asset_type.value}: {asset.original_uri}"
                        )
                    asset_refs.append(
                        AssetRef(
                            asset_id=asset.asset_id,
                            caption=caption,
                        )
                    )
                    seen_asset_ids.add(asset.asset_id)

            chunk = KnowledgeChunk(
                title=raw.get("title") or self._derive_title(content),
                content=content,
                content_hash=compute_hash(content),
                knowledge_type=_safe_knowledge_type(raw.get("knowledge_type")),
                category=category,
                asset_refs=asset_refs,
                source_refs=source_refs,
                metadata={},
            )
            chunks.append(chunk)

        return chunks

    @staticmethod
    def _derive_title(content: str) -> str:
        """从内容首句派生简短标题。"""
        first = content.split("。")[0].split("？")[0].strip()
        if len(first) > 40:
            first = first[:40] + "..."
        return first

    def _fallback_chunks(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """LLM 不可用或返回空结果时，保留可检索的解析文本。"""
        text_parts = [el.text.strip() for el in elements if el.text and el.text.strip()]
        content = "\n".join(text_parts).strip()
        if not content:
            return []

        source_refs = [
            SourceRef(
                doc_id=el.doc_id,
                doc_version=el.doc_version,
                element_id=el.element_id,
                source_location=el.source_location,
            )
            for el in elements
        ]

        # 通过 asset_id 关联 Asset，构造资源引用
        assets_by_id = {a.asset_id: a for a in assets}
        asset_refs: list[AssetRef] = []
        seen_ids: set[str] = set()
        for el in elements:
            for ad in el.asset_data:
                if ad.asset_id in seen_ids:
                    continue
                asset = assets_by_id.get(ad.asset_id)
                if asset is None:
                    continue
                asset_refs.append(
                    AssetRef(
                        asset_id=asset.asset_id,
                        caption=asset.display_text or asset.original_uri,
                    )
                )
                seen_ids.add(ad.asset_id)

        return [
            KnowledgeChunk(
                title=self._derive_title(content),
                content=content,
                content_hash=compute_hash(content),
                knowledge_type=KnowledgeType.declarative,
                category=category,
                asset_refs=asset_refs,
                source_refs=source_refs,
                metadata={},
            )
        ]
