"""违禁词合规检测工具：可注册、可配置、可版本化的工具实现。

工具配置通过 Capability.metadata 进行管理，支持动态更新词表。
"""
import re
from typing import Any, Dict, List

from app.services.tools import ToolDefinition, ToolImplementation


# 默认违禁词表 - 作为后备配置，实际配置存储在 Capability.metadata 中
DEFAULT_FORBIDDEN_WORDS = [
    "根治", "包治百病", "无效退款", "最高级", "国家级", "全网最低", "绝对安全",
    "永久有效", "第一", "唯一", "祖传秘方", "特效", "神效",
]


class ForbiddenWordCheckTool(ToolImplementation):
    """违禁词检测工具的可注册实现。"""

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        """获取工具的完整定义。"""
        return ToolDefinition(
            capability_key="tool_forbidden_word_check",
            name="违禁词/合规话术检测工具",
            description="检测文本中是否包含违禁词或夸大表达，返回风险等级和修改建议",
            business_domain="compliance",
            tags=["合规", "违禁词", "审核", "广告法", "文本检测"],
            scenarios=[
                "直播脚本审核",
                "文案合规审核",
                "商品描述审核",
                "营销话术检测",
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待检测的文本内容"},
                    "check_level": {
                        "type": "string",
                        "description": "检测级别: strict(严格)/normal(正常)/loose(宽松)",
                        "enum": ["strict", "normal", "loose"],
                        "default": "normal",
                    },
                    "custom_words": {"type": "array", "description": "自定义违禁词列表（可选）", "items": {"type": "string"}},
                },
                "required": ["text"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "passed": {"type": "boolean", "description": "是否通过检测"},
                    "risk_level": {"type": "string", "description": "风险等级: high/medium/low"},
                    "hits": {"type": "array", "description": "命中的违禁词详情", "items": {"type": "object"}},
                    "suggestion": {"type": "string", "description": "修改建议"},
                    "word_count": {"type": "integer", "description": "命中的词数"},
                },
            },
            security_level="internal",
            owner_department="合规部",
            side_effect="read_only",
            metadata={
                "forbidden_words": DEFAULT_FORBIDDEN_WORDS,
                "version": "1.0.0",
                "last_updated": "2026-07-10",
                "check_rules": {
                    "strict": {"risk_threshold": 1, "word_matching": "exact"},
                    "normal": {"risk_threshold": 2, "word_matching": "fuzzy"},
                    "loose": {"risk_threshold": 5, "word_matching": "loose"},
                },
            },
            examples=[
                {
                    "input": {"text": "这款产品是全网最低价，绝对安全！"},
                    "output": {
                        "passed": False,
                        "risk_level": "high",
                        "hits": [
                            {"word": "全网最低", "position": 7},
                            {"word": "绝对安全", "position": 13},
                        ],
                        "suggestion": "发现 2 处疑似违禁/夸大表达，请修改后再发布",
                    },
                },
                {
                    "input": {"text": "这款产品用户体验良好，值得推荐。", "check_level": "normal"},
                    "output": {
                        "passed": True,
                        "risk_level": "low",
                        "hits": [],
                        "suggestion": "未发现违禁表达",
                    },
                },
            ],
            timeout_ms=5000,
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行违禁词检测。"""
        text = input_data.get("text") or input_data.get("script") or ""
        check_level = input_data.get("check_level", "normal")
        custom_words = input_data.get("custom_words", [])

        # 从 capability metadata 获取配置，如果没有则使用默认值
        forbidden_words = self.config.get("forbidden_words", DEFAULT_FORBIDDEN_WORDS).copy()
        forbidden_words.extend(custom_words)

        # 执行检测
        hits = self._check_text(text, forbidden_words, check_level)
        word_count = len(hits)

        # 评估风险等级
        risk_level = self._evaluate_risk(word_count, check_level)
        passed = word_count == 0

        # 生成建议
        suggestion = self._generate_suggestion(passed, word_count, hits, check_level)

        return {
            "passed": passed,
            "risk_level": risk_level,
            "hits": hits,
            "suggestion": suggestion,
            "word_count": word_count,
            "tool_version": self.config.get("version", "1.0.0"),
        }

    def _check_text(self, text: str, forbidden_words: List[str], check_level: str) -> List[Dict[str, Any]]:
        """检查文本中的违禁词。"""
        hits = []

        for word in forbidden_words:
            if not word:
                continue

            # 根据检查级别调整匹配策略
            if check_level == "loose":
                # 宽松模式：只匹配完整词
                pattern = r'\b' + re.escape(word) + r'\b'
            else:
                # 严格/正常模式：子串匹配
                pattern = re.escape(word)

            for match in re.finditer(pattern, text):
                hits.append({
                    "word": word,
                    "position": match.start(),
                    "context": self._get_context(text, match.start(), 20),
                })

        return hits

    def _get_context(self, text: str, position: int, context_length: int) -> str:
        """获取命中位置的上下文。"""
        start = max(0, position - context_length)
        end = min(len(text), position + context_length + 1)
        context = text[start:end]

        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."

        return context

    def _evaluate_risk(self, word_count: int, check_level: str) -> str:
        """根据命中数和检查级别评估风险。"""
        rules = self.config.get("check_rules", {})
        level_config = rules.get(check_level, {})
        threshold = level_config.get("risk_threshold", 2)

        if word_count >= threshold + 1:
            return "high"
        elif word_count >= 1:
            return "medium"
        return "low"

    def _generate_suggestion(self, passed: bool, word_count: int, hits: List[Dict], check_level: str) -> str:
        """生成检测建议。"""
        if passed:
            return "未发现违禁表达"

        words = [h["word"] for h in hits[:3]]
        word_list = "、".join(words)
        if len(hits) > 3:
            word_list += f" 等{len(hits)}个词"

        level_desc = {
            "strict": "严格模式",
            "normal": "正常模式",
            "loose": "宽松模式",
        }.get(check_level, "标准模式")

        return f"[{level_desc}] 发现 {word_count} 处疑似违禁/夸大表达（{word_list}），请修改后再发布"


# 保留向后兼容的函数接口
def check_forbidden_words(text: str) -> Dict[str, Any]:
    """
    向后兼容的接口：简单的违禁词检测。
    新代码应该使用 ToolRegistry 和 Capability 系统。
    """
    from app.models.capability import Capability

    # 创建一个临时的 capability 对象用于向后兼容
    temp_capability = Capability(
        capability_key="tool_forbidden_word_check",
        metadata_=ForbiddenWordCheckTool.get_definition().metadata,
    )
    tool = ForbiddenWordCheckTool(temp_capability)

    # 同步执行（为了向后兼容，这个函数不是 async）
    # 注意：在实际 async 环境中应该使用 async execute
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(tool.execute({"text": text}))
        # 精简返回结果以保持向后兼容
        return {
            "passed": result["passed"],
            "risk_level": result["risk_level"],
            "hits": [{"word": h["word"], "position": h["position"]} for h in result["hits"]],
            "suggestion": result["suggestion"],
        }
    except Exception:
        # 降级到原始简单实现
        hits = []
        for word in DEFAULT_FORBIDDEN_WORDS:
            for m in re.finditer(re.escape(word), text):
                hits.append({"word": word, "position": m.start()})
        passed = len(hits) == 0
        return {
            "passed": passed,
            "risk_level": "high" if len(hits) >= 3 else ("medium" if hits else "low"),
            "hits": hits,
            "suggestion": "未发现违禁表达" if passed else f"发现 {len(hits)} 处疑似违禁/夸大表达，请修改后再发布",
        }
