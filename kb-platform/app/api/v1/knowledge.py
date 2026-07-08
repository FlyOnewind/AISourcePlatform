"""知识资产API：知识库管理、文档上传、检索/问答，对应文档11 3.3。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity, get_trace_id, require_admin_roles
from app.core.db import get_db
from app.models.knowledge import Document, KnowledgeBase
from app.schemas.common import ok
from app.schemas.knowledge import (
    ChunkHit,
    ChunkSource,
    DocumentOut,
    KnowledgeAnswerRequest,
    KnowledgeAnswerResponse,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.services.audit_service import AuditService
from app.services.knowledge_service import KnowledgeService
from app.services.llm.factory import get_llm_provider
from app.services.policy_service import PolicyService, Resource, Subject
from app.services.retrieval_service import RetrievalService

router = APIRouter(tags=["knowledge"])

SECURITY_ORDER = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def _kb_out(kb: KnowledgeBase) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=str(kb.id), kb_key=kb.kb_key, name=kb.name, business_domain=kb.business_domain,
        security_level=kb.security_level, status=kb.status,
    )


@router.post("/api/v1/knowledge-bases")
async def create_kb(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "knowledge_admin")),
):
    existing = await db.execute(select(KnowledgeBase).where(KnowledgeBase.kb_key == payload.kb_key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "409001", "message": "kb_key 已存在"})
    kb = KnowledgeBase(**payload.model_dump())
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return ok(_kb_out(kb).model_dump())


@router.get("/api/v1/knowledge-bases")
async def list_kbs(db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    subject = Subject(agent_role=identity.role, business_domain=identity.business_domain)
    policy = PolicyService(db)
    result = await db.execute(select(KnowledgeBase))
    kbs = result.scalars().all()
    visible = []
    for kb in kbs:
        allowed, _ = await policy.evaluate(
            subject, Resource(capability_type="knowledge_base", business_domain=kb.business_domain, security_level=kb.security_level), "search"
        )
        if allowed:
            visible.append(kb)
    return ok([_kb_out(kb).model_dump() for kb in visible])


@router.get("/api/v1/knowledge-bases/{kb_id}")
async def get_kb(kb_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "知识库不存在"})
    return ok(_kb_out(kb).model_dump())


@router.post("/api/v1/knowledge-bases/{kb_id}/documents")
async def upload_document(
    kb_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "knowledge_admin")),
):
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "知识库不存在"})

    content = await file.read()
    service = KnowledgeService(db, get_llm_provider())
    doc = await service.upload_document(kb, file.filename or "unnamed", content, security_level=kb.security_level)
    await db.commit()
    await db.refresh(doc)
    chunk_count = await service.get_chunk_count(doc.id)
    return ok(
        DocumentOut(
            id=str(doc.id), kb_id=str(doc.kb_id), title=doc.title, source_type=doc.source_type,
            parse_status=doc.parse_status, version=doc.version, security_level=doc.security_level,
            chunk_count=chunk_count,
        ).model_dump()
    )


@router.get("/api/v1/knowledge-bases/{kb_id}/documents")
async def list_documents(kb_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(Document).where(Document.kb_id == kb_id))
    docs = result.scalars().all()
    service = KnowledgeService(db, get_llm_provider())
    out = []
    for doc in docs:
        count = await service.get_chunk_count(doc.id)
        out.append(
            DocumentOut(
                id=str(doc.id), kb_id=str(doc.kb_id), title=doc.title, source_type=doc.source_type,
                parse_status=doc.parse_status, version=doc.version, security_level=doc.security_level,
                chunk_count=count,
            ).model_dump()
        )
    return ok(out)


@router.get("/api/v1/documents/{doc_id}")
async def get_document(doc_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(get_current_identity)):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "文档不存在"})
    service = KnowledgeService(db, get_llm_provider())
    count = await service.get_chunk_count(doc.id)
    return ok(
        DocumentOut(
            id=str(doc.id), kb_id=str(doc.kb_id), title=doc.title, source_type=doc.source_type,
            parse_status=doc.parse_status, version=doc.version, security_level=doc.security_level, chunk_count=count,
        ).model_dump()
    )


@router.post("/api/v1/documents/{doc_id}/publish")
async def publish_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "knowledge_admin")),
):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail={"code": "404001", "message": "文档不存在"})
    service = KnowledgeService(db, get_llm_provider())
    try:
        await service.publish_document(doc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "422001", "message": str(exc)}) from None

    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id))
    kb = kb_result.scalar_one_or_none()
    if kb is not None and kb.status != "published":
        kb.status = "published"

    await db.commit()
    return ok({"document_id": doc_id, "parse_status": "published"})


@router.post("/api/v1/knowledge/search")
async def search_knowledge(
    payload: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    trace_id: str = Depends(get_trace_id),
):
    retrieval = RetrievalService(db, get_llm_provider())
    max_level = payload.filters.get("max_security_level") or _resolve_max_level(identity)
    chunks = await retrieval.search(payload.query, payload.knowledge_base_ids or None, payload.top_k, max_level)

    audit = AuditService(db)
    await audit.log(
        trace_id=trace_id, actor_type=identity.actor_type, actor_id=identity.key, action="search_knowledge",
        resource_type="knowledge_base", input_payload=payload.model_dump(), output_payload={"count": len(chunks)},
    )
    await db.commit()

    response = KnowledgeSearchResponse(
        trace_id=trace_id,
        chunks=[
            ChunkHit(chunk_id=c.chunk_id, content=c.content, score=c.score, source=ChunkSource(doc_name=c.doc_name, doc_id=c.doc_id, version=c.version))
            for c in chunks
        ],
    )
    return ok(response.model_dump())


@router.post("/api/v1/knowledge/answer")
async def answer_knowledge(
    payload: KnowledgeAnswerRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    trace_id: str = Depends(get_trace_id),
):
    llm = get_llm_provider()
    retrieval = RetrievalService(db, llm)
    max_level = payload.filters.get("max_security_level") or _resolve_max_level(identity)
    chunks = await retrieval.search(payload.query, payload.knowledge_base_ids or None, payload.top_k, max_level)

    context_text = "\n\n".join(f"[来源:{c.doc_name}] {c.content}" for c in chunks)
    prompt = f"参考资料：\n{context_text}\n\n问题：{payload.query}\n请基于参考资料回答，并说明依据。"
    answer = await llm.generate(prompt)

    audit = AuditService(db)
    await audit.log(
        trace_id=trace_id, actor_type=identity.actor_type, actor_id=identity.key, action="answer_knowledge",
        resource_type="knowledge_base", input_payload=payload.model_dump(),
    )
    await db.commit()

    response = KnowledgeAnswerResponse(
        trace_id=trace_id,
        answer=answer,
        citations=[
            ChunkHit(chunk_id=c.chunk_id, content=c.content, score=c.score, source=ChunkSource(doc_name=c.doc_name, doc_id=c.doc_id, version=c.version))
            for c in chunks
        ],
    )
    return ok(response.model_dump())


def _resolve_max_level(identity: Identity) -> str:
    # master_agent 与平台管理员可见更高密级；其余 Agent 默认只能看 internal 及以下。
    if identity.role == "master_agent" or identity.actor_type == "admin_user":
        return "confidential"
    return "internal"
