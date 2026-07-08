"""统一 API 响应格式，对应文档11 第5节。"""
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Envelope(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    trace_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def ok(data: Any = None, trace_id: str | None = None) -> dict:
    return Envelope(success=True, data=data, trace_id=trace_id).model_dump(mode="json")


def fail(code: str, message: str, trace_id: str | None = None, details: dict | None = None) -> dict:
    return Envelope(
        success=False,
        error=ErrorDetail(code=code, message=message, details=details or {}),
        trace_id=trace_id,
    ).model_dump(mode="json")
