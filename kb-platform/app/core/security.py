"""安全相关工具：API Key 生成与 trace/task 上下文变量。

鉴权本身（校验 API Key 对应哪个身份、角色是否满足要求）在 app/api/deps.py 中实现，
因为它需要查询数据库；这里只放与请求生命周期无关的纯工具函数。
"""
import contextvars
import secrets

# 当前请求的 trace_id / task_id，由 TraceMiddleware 注入，供 service 层日志复用，
# 避免把 trace_id 一层层显式传参。
trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)


def generate_api_key(prefix: str = "kbp") -> str:
    """生成形如 kbp_live_xxxxxxxx 的 API Key，用于 Agent/管理员身份鉴权。"""
    return f"{prefix}_{secrets.token_urlsafe(24)}"


def generate_trace_id() -> str:
    return f"trace_{secrets.token_hex(12)}"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"
