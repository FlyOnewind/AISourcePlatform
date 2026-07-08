"""一个真实可用的示例 Tool：违禁词/合规话术检测。

对应文档09"违禁词审核Agent/合规校验工具"，用规则词表实现（非 Mock 占位），
可直接在 demo_multi_agent.py 的终检环节调用并得到有意义的结果。
"""
import re

FORBIDDEN_WORDS = [
    "根治", "包治百病", "无效退款", "最高级", "国家级", "全网最低", "绝对安全",
    "永久有效", "第一", "唯一", "祖传秘方", "特效", "神效",
]


def check_forbidden_words(text: str) -> dict:
    hits = []
    for word in FORBIDDEN_WORDS:
        for m in re.finditer(re.escape(word), text):
            hits.append({"word": word, "position": m.start()})
    passed = len(hits) == 0
    return {
        "passed": passed,
        "risk_level": "high" if len(hits) >= 3 else ("medium" if hits else "low"),
        "hits": hits,
        "suggestion": "未发现违禁表达" if passed else f"发现 {len(hits)} 处疑似违禁/夸大表达，请修改后再发布",
    }
