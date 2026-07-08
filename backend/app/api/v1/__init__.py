"""API v1 路由分组。

将所有 v1 子路由收集到统一前缀 `/api/v1` 下，
并注册 v1 专属异常处理器。
"""

from fastapi import APIRouter, FastAPI

from app.api.v1.errors import EXCEPTION_HANDLERS

router = APIRouter(prefix="/api/v1")


def register_v1_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 实例上注册 v1 异常处理器。

    将 app.core.errors 中的异常映射为统一的 APIErrorResponse。
    """
    for exc_class, handler in EXCEPTION_HANDLERS.items():
        app.add_exception_handler(exc_class, handler)


def mount_v1_sub_routers() -> None:
    """挂载所有 v1 子路由到 v1 router。

    延迟导入各子路由模块，避免在部分环境（如测试）
    中因 import 链触发预先存在的依赖问题。
    在 main.py 的 app 创建完成后调用。
    """
    from app.api.v1 import chunks, documents, health, jobs, search  # noqa: F811
    router.include_router(health.router)
    router.include_router(documents.router)
    router.include_router(chunks.router)
    router.include_router(jobs.router)
    router.include_router(search.router)
