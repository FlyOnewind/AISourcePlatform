"""
示例工具集合
展示如何创建和注册新工具
"""
from typing import Any, Dict, List
from app.services.tools import ToolDefinition, ToolImplementation


class TextAnalysisTool(ToolImplementation):
    """文本分析工具 - 分析文本的基本属性"""

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            capability_key="tool_text_analysis",
            name="文本分析工具",
            description="分析文本的长度、字符数、词数等基本属性",
            business_domain="content",
            tags=["文本分析", "统计", "内容"],
            scenarios=[
                "内容质量检查",
                "文本长度验证",
                "内容统计分析"
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待分析的文本"},
                    "language": {"type": "string", "description": "文本语言", "default": "zh"}
                },
                "required": ["text"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "char_count": {"type": "integer", "description": "字符数"},
                    "word_count": {"type": "integer", "description": "词数"},
                    "line_count": {"type": "integer", "description": "行数"},
                    "has_content": {"type": "boolean", "description": "是否有内容"},
                    "language_detected": {"type": "string", "description": "检测到的语言"}
                }
            },
            security_level="internal",
            owner_department="技术部",
            side_effect="read_only",
            metadata={
                "version": "1.0.0",
                "category": "content_analysis",
                "supports_batch": False
            },
            examples=[
                {
                    "input": {"text": "这是一段示例文本"},
                    "output": {
                        "char_count": 8,
                        "word_count": 2,
                        "line_count": 1,
                        "has_content": True
                    }
                }
            ],
            timeout_ms=2000
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        text = input_data.get("text", "")

        # 计算基本统计
        char_count = len(text)
        lines = text.split("\n")
        line_count = len(lines)

        # 简单词数统计（按空格或标点分割）
        import re
        words = re.findall(r"[\w']+|[一-鿿]", text)
        word_count = len(words)

        # 语言检测（简化版）
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        language_detected = "zh" if chinese_chars > char_count / 2 else "en"

        return {
            "char_count": char_count,
            "word_count": word_count,
            "line_count": line_count,
            "has_content": char_count > 0,
            "language_detected": language_detected,
            "tool_version": self.config.get("version", "1.0.0")
        }


class DataFormatTool(ToolImplementation):
    """数据格式化工具 - 格式化各种数据类型"""

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            capability_key="tool_data_format",
            name="数据格式化工具",
            description="格式化JSON、日期、数字等数据类型",
            business_domain="utility",
            tags=["格式化", "工具", "数据"],
            scenarios=[
                "数据清洗",
                "格式转换",
                "数据标准化"
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "data": {"type": ["string", "number", "object", "array"], "description": "待格式化的数据"},
                    "format_type": {"type": "string", "description": "格式化类型", "enum": ["json", "number", "date"]},
                    "options": {"type": "object", "description": "格式化选项"}
                },
                "required": ["data", "format_type"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "formatted": {"type": ["string", "number", "object"], "description": "格式化后的数据"},
                    "original_type": {"type": "string", "description": "原始数据类型"},
                    "format_type": {"type": "string", "description": "使用的格式类型"}
                }
            },
            security_level="internal",
            owner_department="技术部",
            side_effect="read_only",
            metadata={
                "version": "1.0.0",
                "category": "utility"
            },
            examples=[],
            timeout_ms=3000
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        import json
        from datetime import datetime

        data = input_data.get("data")
        format_type = input_data.get("format_type")
        options = input_data.get("options", {})

        formatted = data
        original_type = type(data).__name__

        try:
            if format_type == "json":
                indent = options.get("indent", 2)
                formatted = json.dumps(data, ensure_ascii=False, indent=indent)
            elif format_type == "number":
                decimal_places = options.get("decimal_places", 2)
                if isinstance(data, (int, float)):
                    formatted = round(float(data), decimal_places)
            elif format_type == "date":
                if isinstance(data, str):
                    # 尝试解析日期字符串
                    date_formats = [
                        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y",
                        "%Y-%m-%d %H:%M:%S", "%Y%m%d"
                    ]
                    date_obj = None
                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(data, fmt)
                            break
                        except ValueError:
                            continue
                    if date_obj:
                        target_format = options.get("target_format", "%Y-%m-%d")
                        formatted = date_obj.strftime(target_format)
        except Exception as e:
            formatted = data

        return {
            "formatted": formatted,
            "original_type": original_type,
            "format_type": format_type,
            "tool_version": self.config.get("version", "1.0.0")
        }


class SentimentAnalysisTool(ToolImplementation):
    """情感分析工具 - 简单的文本情感分析（基于关键词）"""

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            capability_key="tool_sentiment_analysis",
            name="情感分析工具",
            description="分析文本的情感倾向（正面/负面/中性）",
            business_domain="content",
            tags=["情感分析", "NLP", "内容分析"],
            scenarios=[
                "用户反馈分析",
                "评论情感判断",
                "内容倾向分析"
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待分析的文本"}
                },
                "required": ["text"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "sentiment": {"type": "string", "description": "情感倾向", "enum": ["positive", "negative", "neutral"]},
                    "confidence": {"type": "number", "description": "置信度"},
                    "positive_words": {"type": "array", "description": "正面关键词"},
                    "negative_words": {"type": "array", "description": "负面关键词"}
                }
            },
            security_level="internal",
            owner_department="运营部",
            side_effect="read_only",
            metadata={
                "version": "1.0.0",
                "positive_words": [
                    "好", "棒", "优秀", "完美", "喜欢", "满意", "不错",
                    "great", "good", "excellent", "perfect", "love", "like"
                ],
                "negative_words": [
                    "差", "糟糕", "失望", "不好", "讨厌", "不满",
                    "bad", "terrible", "awful", "disappointed", "hate"
                ]
            },
            examples=[],
            timeout_ms=3000
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        text = input_data.get("text", "").lower()

        # 从配置获取关键词，如果没有则使用默认
        positive_words = self.config.get("positive_words", [
            "好", "棒", "优秀", "完美", "喜欢", "满意", "不错"
        ])
        negative_words = self.config.get("negative_words", [
            "差", "糟糕", "失望", "不好", "讨厌", "不满"
        ])

        found_positive = []
        found_negative = []

        for word in positive_words:
            if word.lower() in text:
                found_positive.append(word)

        for word in negative_words:
            if word.lower() in text:
                found_negative.append(word)

        pos_count = len(found_positive)
        neg_count = len(found_negative)

        # 简单计算情感
        if pos_count > neg_count:
            sentiment = "positive"
            confidence = min(1.0, (pos_count - neg_count) / max(pos_count, 1))
        elif neg_count > pos_count:
            sentiment = "negative"
            confidence = min(1.0, (neg_count - pos_count) / max(neg_count, 1))
        else:
            sentiment = "neutral"
            confidence = 0.5

        return {
            "sentiment": sentiment,
            "confidence": confidence,
            "positive_words": found_positive,
            "negative_words": found_negative,
            "tool_version": self.config.get("version", "1.0.0")
        }


# 导出所有示例工具
ALL_TOOLS = [
    TextAnalysisTool,
    DataFormatTool,
    SentimentAnalysisTool
]
