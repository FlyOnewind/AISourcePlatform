"""Prompt模板渲染服务，对应文档05 6.1与文档11 3.5 render。"""
import re

from app.models.skill import PromptTemplate


class PromptRenderError(ValueError):
    pass


def render_prompt(prompt: PromptTemplate, variables: dict) -> str:
    required = [v["name"] for v in (prompt.variables or []) if v.get("required")]
    missing = [name for name in required if name not in variables]
    if missing:
        raise PromptRenderError(f"缺少必填变量: {', '.join(missing)}")

    def _replace(match: re.Match) -> str:
        key = match.group(1).strip()
        if key not in variables:
            return match.group(0)
        value = variables[key]
        return str(value) if not isinstance(value, dict | list) else _stringify(value)

    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", _replace, prompt.template)


def _stringify(value: dict | list) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
