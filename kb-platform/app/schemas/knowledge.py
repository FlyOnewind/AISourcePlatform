"""知识库/文档/检索 schema，对应文档04与文档11 3.3。"""
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    kb_key: str
    name: str
    business_domain: str | None = None
    owner_department: str | None = None
    security_level: str = "internal"
    retrieval_config: dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseOut(BaseModel):
    id: str
    kb_key: str
    name: str
    business_domain: str | None
    security_level: str
    status: str

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    kb_id: str
    title: str
    source_type: str
    parse_status: str
    version: str
    security_level: str
    chunk_count: int = 0

    model_config = {"from_attributes": True}


class KnowledgeSearchRequest(BaseModel):
    query: str
    knowledge_base_ids: list[str] = Field(default_factory=list)
    top_k: int = 5
    filters: dict[str, Any] = Field(default_factory=dict)


class ChunkSource(BaseModel):
    doc_name: str
    doc_id: str
    version: str


class ChunkHit(BaseModel):
    chunk_id: str
    content: str
    score: float
    source: ChunkSource


class KnowledgeSearchResponse(BaseModel):
    trace_id: str
    chunks: list[ChunkHit]


class KnowledgeAnswerRequest(KnowledgeSearchRequest):
    pass


class KnowledgeAnswerResponse(BaseModel):
    trace_id: str
    answer: str
    citations: list[ChunkHit]
