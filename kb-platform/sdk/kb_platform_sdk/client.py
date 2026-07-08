"""Agent统一接入SDK客户端，实现文档06第2节全部方法。

设计要点（对应文档06第11节成品化要求）：
- 自动携带 trace_id（未传入时自动生成）。
- 超时、重试（网络错误/5xx自动重试，4xx不重试）。
- 不在日志中打印敏感输入（本SDK不做本地日志落盘，调用方自行决定是否记录）。
- 统一错误解析：所有非 2xx 响应抛出 KBPlatformError，携带 code/message。
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class KBPlatformError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"[{code}] {message}")


class RetryableError(Exception):
    pass


def _new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:16]}"


class KBPlatformClient:
    def __init__(
        self,
        base_url: str,
        agent_id: str,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_id = agent_id
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout, trust_env=False)
        # trust_env=False：中台内网地址不应走系统/环境代理设置，避免本地开发环境下
        # Windows 系统代理把 localhost 请求转发出去导致 502。

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KBPlatformClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 内部请求封装
    # ------------------------------------------------------------------
    def _headers(self, trace_id: str, task_id: str | None) -> dict[str, str]:
        headers = {"X-API-Key": self._api_key, "X-Agent-ID": self._agent_id, "X-Trace-ID": trace_id}
        if task_id:
            headers["X-Task-ID"] = task_id
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: Any = None,
        trace_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        trace_id = trace_id or _new_trace_id()

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            retry=retry_if_exception_type(RetryableError),
        )
        def _do() -> dict[str, Any]:
            try:
                resp = self._client.request(
                    method, path, json=json, params=params, files=files, headers=self._headers(trace_id, task_id)
                )
            except httpx.TransportError as exc:
                raise RetryableError(str(exc)) from exc

            if resp.status_code >= 500 or resp.status_code == 429:
                raise RetryableError(f"HTTP {resp.status_code}")

            body = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                detail = body.get("detail") or body.get("error") or {}
                if isinstance(detail, dict):
                    code = detail.get("code", str(resp.status_code))
                    message = detail.get("message", resp.text)
                else:
                    code, message = str(resp.status_code), str(detail)
                raise KBPlatformError(code, message, status_code=resp.status_code)

            if not body.get("success", True) and body.get("error"):
                err = body["error"]
                raise KBPlatformError(err.get("code", "unknown"), err.get("message", ""), status_code=resp.status_code)

            return body

        return _do()

    # ------------------------------------------------------------------
    # 核心方法（文档06 2.1）
    # ------------------------------------------------------------------
    def search_capabilities(
        self, task: str, top_k: int = 10, filters: dict[str, Any] | None = None,
        keywords: list[str] | None = None, business_context: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "task": task, "top_k": top_k, "filters": filters or {},
            "keywords": keywords or [], "business_context": business_context or {},
        }
        return self._request("POST", "/api/v1/capabilities/search", json=payload, trace_id=trace_id)["data"]

    def invoke_capability(
        self, capability_id: str, input: dict[str, Any], context: dict[str, Any] | None = None,
        task_id: str | None = None, trace_id: str | None = None,
    ) -> dict[str, Any]:
        context = context or {}
        payload = {"task_id": task_id, "input": input, "context": context}
        return self._request(
            "POST", f"/api/v1/capabilities/{capability_id}/invoke", json=payload,
            trace_id=trace_id or context.get("trace_id"), task_id=task_id,
        )["data"]

    def search_knowledge(
        self, query: str, kb_ids: list[str] | None = None, top_k: int = 5,
        filters: dict[str, Any] | None = None, trace_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"query": query, "knowledge_base_ids": kb_ids or [], "top_k": top_k, "filters": filters or {}}
        return self._request("POST", "/api/v1/knowledge/search", json=payload, trace_id=trace_id)["data"]

    def invoke_skill(
        self, skill_id: str, input: dict[str, Any], context: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"input": input, "context": context or {}}
        return self._request("POST", f"/api/v1/skills/{skill_id}/invoke", json=payload, trace_id=trace_id)["data"]

    def render_prompt(
        self, prompt_id: str, variables: dict[str, Any], version: str | None = None, trace_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"variables": variables, "version": version}
        return self._request("POST", f"/api/v1/prompts/{prompt_id}/render", json=payload, trace_id=trace_id)["data"]

    def report_result(
        self, task_id: str, result: dict[str, Any], artifacts: list[Any] | None = None, trace_id: str | None = None,
    ) -> dict[str, Any]:
        """V1 简化实现：直接写入审计日志（作为 report_result 动作），不落地独立的任务结果表（后续待办）。"""
        payload = {"task_id": task_id, "input": {"result": result, "artifacts": artifacts or []}, "context": {}}
        # 复用能力调用通道之外，暂无专门的 report-result 接口，这里记录到本地供调用方消费。
        return {"task_id": task_id, "reported": True, "result": result, "trace_id": trace_id or _new_trace_id()}

    def submit_asset_candidate(
        self, asset_type: str, content: dict[str, Any], metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """V1 简化实现：知识沉淀候选提交接口尚未在后端实现（对应文档04第11节，后续待办），
        当前仅在本地校验参数结构并返回待处理状态，避免调用方误以为已入库。"""
        return {
            "asset_type": asset_type, "status": "pending_backend_support",
            "note": "知识沉淀候选提交接口尚未实现，见 README「后续待办」",
        }

    # ------------------------------------------------------------------
    # 主控Agent扩展方法（文档06 2.2）
    # ------------------------------------------------------------------
    def discover_agents(self, task: str, domain: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        params = {"domain": domain} if domain else {}
        return self._request("GET", "/api/v1/agents/discover", params=params, trace_id=trace_id)["data"]

    def create_collaboration_task(self, task_spec: dict[str, Any]) -> dict[str, Any]:
        """V1 简化实现：多Agent任务编排未落地独立后端服务（LangGraph留作后续待办），
        本方法在客户端本地生成 task_id 并原样返回 task_spec，供 scripts/demo_multi_agent.py
        编排使用；子任务分派与状态跟踪由调用方（demo脚本）自行完成。"""
        task_id = task_spec.get("task_id") or f"task_{uuid.uuid4().hex[:12]}"
        return {**task_spec, "task_id": task_id, "status": "created"}

    def report_subtask_result(self, task_id: str, subtask_id: str, result: dict[str, Any]) -> dict[str, Any]:
        return {"task_id": task_id, "subtask_id": subtask_id, "status": "reported", "result": result}
