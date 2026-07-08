"""统一错误码定义和异常转换。

覆盖文档不存在、知识块不存在、重复文档、版本冲突和校验错误，
并将 core.errors 中的异常映射为 APIErrorResponse。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.v1.schemas import APIErrorResponse, ErrorDetail
from app.core.errors import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    KnowledgeBaseError,
)


# ── 错误码常量 ──────────────────────────────────────────────────────

class ErrorCode:
    """机器可读错误码。"""
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    DOCUMENT_DUPLICATE = "DOCUMENT_DUPLICATE"
    DOCUMENT_VERSION_CONFLICT = "DOCUMENT_VERSION_CONFLICT"
    CHUNK_NOT_FOUND = "CHUNK_NOT_FOUND"
    CHUNK_DUPLICATE = "CHUNK_DUPLICATE"
    CHUNK_VERSION_CONFLICT = "CHUNK_VERSION_CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INGEST_JOB_NOT_FOUND = "INGEST_JOB_NOT_FOUND"
    INGEST_JOB_CONFLICT = "INGEST_JOB_CONFLICT"
    DOC_NOT_FOUND = "DOC_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# ── 自定义异常 ──────────────────────────────────────────────────────

class ChunkNotFoundError(KnowledgeBaseError):
    """指定的知识块不存在。"""
    pass


# ── 异常处理器注册 ──────────────────────────────────────────────────

def _build_response(status_code: int, code: str, message: str, details: object = None) -> JSONResponse:
    """构建统一的 JSON 错误响应。"""
    return JSONResponse(
        status_code=status_code,
        content=APIErrorResponse(
            error=ErrorDetail(code=code, message=message, details=details),
        ).model_dump(mode="json"),
    )


async def document_not_found_handler(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
    return _build_response(404, ErrorCode.DOCUMENT_NOT_FOUND, str(exc))


async def duplicate_document_handler(request: Request, exc: DuplicateDocumentError) -> JSONResponse:
    return _build_response(409, ErrorCode.DOCUMENT_DUPLICATE, str(exc))


async def chunk_not_found_handler(request: Request, exc: ChunkNotFoundError) -> JSONResponse:
    return _build_response(404, ErrorCode.CHUNK_NOT_FOUND, str(exc))


async def knowledge_base_error_handler(request: Request, exc: KnowledgeBaseError) -> JSONResponse:
    """兜底 - 其他 KnowledgeBase 子类异常。"""
    return _build_response(500, ErrorCode.INTERNAL_ERROR, str(exc))


# ── 异常处理器列表，供路由层注册 ────────────────────────────────────

EXCEPTION_HANDLERS = {
    DocumentNotFoundError: document_not_found_handler,
    DuplicateDocumentError: duplicate_document_handler,
    ChunkNotFoundError: chunk_not_found_handler,
    KnowledgeBaseError: knowledge_base_error_handler,
}
