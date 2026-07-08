"""统一响应模型、错误结构和公共请求参数。

覆盖 data、meta、error 和分页元信息，确保所有 /api/v1 接口
返回一致的 JSON 结构。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ── 通用类型变量 ────────────────────────────────────────────────────
T = TypeVar("T")


# ── 错误模型 ────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    """单条错误详情。"""
    code: str = Field(..., description="机器可读错误码，如 DOCUMENT_NOT_FOUND")
    message: str = Field(..., description="面向用户的消息摘要")
    details: Any | None = Field(default=None, description="可选的结构化错误明细")


# ── 分页元信息 ─────────────────────────────────────────────────────

class PaginationMeta(BaseModel):
    """分页元信息。"""
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total: int = Field(..., ge=0)
    total_pages: int | None = Field(default=None, ge=0, description="总页数，如果无法计算则为 None")


# ── 统一响应容器 ────────────────────────────────────────────────────

class APIResponse(BaseModel, Generic[T]):
    """所有 /api/v1 接口的统一成功响应。

    列表接口使用 PaginatedResponse（继承本类并覆盖 meta）。
    """
    data: T = Field(..., description="响应主数据")
    metadata: dict[str, Any] = Field(default_factory=dict, description="补充元数据")
    error: None = Field(default=None, description="成功时为 null")


class APIErrorResponse(BaseModel):
    """所有 /api/v1 接口的统一错误响应。"""
    data: None = Field(default=None, description="错误时为 null")
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: ErrorDetail = Field(..., description="错误详情")


class PaginatedResponse(APIResponse[list[T]], Generic[T]):
    """带标准分页信息的列表响应。

    使用方式:
        PaginatedResponse[DocumentItem](
            data=[...],
            metadata=PaginationMeta(page=1, page_size=20, total=100).model_dump(),
        )
    """


def response_json(response: BaseModel, status_code: int = 200) -> JSONResponse:
    """将 v1 响应模型转换为带 HTTP 状态码的 FastAPI JSONResponse。"""
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json"),
    )


def error_json(
    code: str,
    message: str,
    status_code: int,
    details: Any | None = None,
    meta: dict[str, Any] | None = None,
) -> JSONResponse:
    """构建统一错误响应，避免在成功响应模型中塞入 error。"""
    return JSONResponse(
        status_code=status_code,
        content=APIErrorResponse(
            metadata=meta or {},
            error=ErrorDetail(code=code, message=message, details=details),
        ).model_dump(mode="json"),
    )


# ── 公共请求参数模型 ────────────────────────────────────────────────

class PaginationParams(BaseModel):
    """分页与排序请求参数。"""
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=200, description="每页条目数，最大 200")
    sort_by: str | None = Field(default=None, description="排序字段，如 updated_at")
    sort_order: str = Field(default="desc", description="排序方向: asc 或 desc")


class SearchParams(BaseModel):
    """关键词和时间范围过滤参数。"""
    keyword: str | None = Field(default=None, description="关键词搜索，在标题/内容中匹配")
    created_after: datetime | None = Field(default=None, description="创建时间起")
    created_before: datetime | None = Field(default=None, description="创建时间止")
    updated_after: datetime | None = Field(default=None, description="更新时间起")
    updated_before: datetime | None = Field(default=None, description="更新时间止")
