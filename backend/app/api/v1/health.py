"""系统健康检查 API — GET /api/v1/health/*

提供两级健康检查：
- /live：进程存活探针（供 K8s liveness probe 等外部监控使用，前端不使用）
- /    ：整体状态 + 外部依赖详情（前端仪表盘 + banner 状态灯使用）
         PostgreSQL、Milvus、MinIO、LLM 四路并行探测，任一异常返回 degraded
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter

from app.api.v1.schemas import APIResponse
from app.utils.thread_pool import health_executor

router = APIRouter(prefix="/health", tags=["health"])

logger = logging.getLogger(__name__)

# 单个外部服务检查的超时时间（秒），防止某个服务卡死阻塞整个 /health 接口
_CHECK_TIMEOUT = 10.0


# ── 存活探针 /live ───────────────────────────────────────────────────
# 仅验证进程可响应，不触碰任何外部依赖。
# 前端不再调用此端点（改用 /health），保留供 K8s liveness probe 使用。


@router.get("/live")
async def health_live():
    """进程存活探针 — 仅返回 ok，不检查任何外部服务。"""
    return APIResponse(
        data={"status": "ok"},
        metadata={"service": "knowledge-base-system", "version": "0.5.0"},
    ).model_dump(mode="json")


# ── 整体健康检查 / ───────────────────────────────────────────────────
# 并行探测四个外部服务（kb-health 线程池 + asyncio.gather），每个有 _CHECK_TIMEOUT 秒超时保护。
# 前端仪表盘和顶部 banner 状态灯均使用此端点。


@router.get("")
async def health():
    """返回系统整体状态和外部依赖详情。

    并行探测 PostgreSQL、Milvus、MinIO、LLM（asyncio.gather + kb-health 线程池）。
    隐藏敏感信息：不暴露密钥、连接密码或完整堆栈。
    任一依赖 error 时 data.status 为 degraded，HTTP 仍返回 200。
    """
    loop = asyncio.get_running_loop()

    async def _run_check(name: str, check_fn) -> dict[str, Any]:
        """在线程池中运行同步检查，带超时保护。"""
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(health_executor, check_fn),
                timeout=_CHECK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("%s 健康检查超时（%s 秒）", name, _CHECK_TIMEOUT)
            return {"status": "error", "name": name, "summary": "健康检查超时"}

    # 四路并行探测，总耗时 = 最慢依赖的耗时（上限 _CHECK_TIMEOUT 秒）
    postgresql, milvus, minio, llm = await asyncio.gather(
        _run_check("PostgreSQL", _check_postgresql),
        _run_check("Milvus", _check_milvus),
        _run_check("MinIO", _check_minio),
        _run_check("LLM", _check_llm),
    )
    deps: dict[str, dict[str, Any]] = {
        "postgresql": postgresql,
        "milvus": milvus,
        "minio": minio,
        "llm": llm,
    }

    error_deps = [k for k, v in deps.items() if v.get("status") == "error"]
    overall = "degraded" if error_deps else "ok"

    return APIResponse(
        data={
            "status": overall,
            "dependencies": deps,
        },
        metadata={"service": "knowledge-base-system", "version": "0.3.0"},
    ).model_dump(mode="json")


# ── 辅助函数 ─────────────────────────────────────────────────────────


def _safe_summary(exc: Exception) -> str:
    """安全提取异常摘要，不暴露堆栈。"""
    return str(exc)[:200]


def _check_postgresql() -> dict[str, Any]:
    """检查 PostgreSQL 数据库连接 — 执行 SELECT 1 验证连接可用。"""
    try:
        from sqlalchemy import text
        from app.db.engine import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "name": "PostgreSQL"}
    except Exception as e:
        logger.warning("PostgreSQL 健康检查失败: %s", e)
        return {"status": "error", "name": "PostgreSQL", "summary": _safe_summary(e)}


def _check_milvus() -> dict[str, Any]:
    """检查 Milvus 向量数据库连接 — 连接并验证 collection 可查询。"""
    try:
        from app.core.deps import milvus_manager

        if milvus_manager is not None:
            milvus_manager.ensure_collection()
            # 验证 collection 确实可用（不只是连接成功）
            if milvus_manager.collection is not None:
                _ = milvus_manager.collection.num_entities
            return {"status": "ok", "name": "Milvus"}
        return {"status": "not_configured", "name": "Milvus"}
    except Exception as e:
        logger.warning("Milvus 健康检查失败: %s", e)
        return {"status": "error", "name": "Milvus", "summary": _safe_summary(e)}


def _check_minio() -> dict[str, Any]:
    """检查 MinIO 对象存储连接 — 调用 list_buckets 验证 API 可达。"""
    try:
        from app.core.deps import minio_asset_store

        if minio_asset_store is not None:
            minio_asset_store.client.list_buckets()
            return {"status": "ok", "name": "MinIO"}
        return {"status": "not_configured", "name": "MinIO"}
    except Exception as e:
        logger.warning("MinIO 健康检查失败: %s", e)
        return {"status": "error", "name": "MinIO", "summary": _safe_summary(e)}


def _check_llm() -> dict[str, Any]:
    """检查 LLM 服务 — 发送真实 API 请求验证连通性和 API Key 有效性。"""
    try:
        from app.core.config import get_settings
        from llm.volcengine_client import _get_cached_client

        settings = get_settings()
        if not settings.api_key:
            return {"status": "not_configured", "name": "LLM"}

        client = _get_cached_client()
        # 发送最轻量的请求，仅验证服务可达、API Key 有效
        client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        return {"status": "ok", "name": "LLM"}
    except Exception as e:
        logger.warning("LLM 健康检查失败: %s", e)
        return {"status": "error", "name": "LLM", "summary": _safe_summary(e)}
