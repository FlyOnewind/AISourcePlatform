"""知识库文档生命周期管理：上传/解析/切片/索引/发布，对应文档04第3节状态机。"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.object_storage import get_object_storage
from app.core.vector_store import get_vector_store
from app.models.knowledge import Document, KnowledgeBase, KnowledgeChunk
from app.services.chunkers.simple_chunker import chunk_text
from app.services.llm.base import LLMProvider
from app.services.parsers.document_parser import parse_document


class KnowledgeService:
    def __init__(self, db: AsyncSession, llm: LLMProvider) -> None:
        self._db = db
        self._llm = llm

    async def upload_document(
        self, kb: KnowledgeBase, filename: str, content: bytes, security_level: str = "internal"
    ) -> Document:
        storage = get_object_storage()
        object_name = f"{kb.kb_key}/{uuid.uuid4()}_{filename}"
        object_uri = storage.put_object(object_name, content)

        doc = Document(
            kb_id=kb.id,
            title=filename,
            source_type="upload",
            object_uri=object_uri,
            parse_status="uploaded",
            security_level=security_level,
        )
        self._db.add(doc)
        await self._db.flush()

        # 本地演示场景文件小，直接同步跑完整个 pipeline；生产版本应放入 worker 异步执行（后续待办）。
        await self.process_document(doc, content, filename)
        return doc

    async def process_document(self, doc: Document, content: bytes, filename: str) -> None:
        doc.parse_status = "parsing"
        await self._db.flush()

        try:
            parsed = parse_document(filename, content)
        except Exception as exc:  # noqa: BLE001
            doc.parse_status = "parse_failed"
            doc.parse_error = str(exc)
            await self._db.flush()
            return

        doc.parse_status = "parsed"
        drafts = chunk_text(parsed.raw_text)
        if not drafts:
            doc.parse_status = "parse_failed"
            doc.parse_error = "解析结果为空，未生成任何切片"
            await self._db.flush()
            return

        doc.parse_status = "chunking"
        await self._db.flush()

        vectors = await self._llm.embed([d.content for d in drafts])
        store = get_vector_store()
        kb_id_str = str(doc.kb_id)

        chunks: list[KnowledgeChunk] = []
        for i, (draft, vector) in enumerate(zip(drafts, vectors, strict=False)):
            chunk = KnowledgeChunk(
                doc_id=doc.id,
                kb_id=doc.kb_id,
                chunk_index=i,
                title_path=draft.title_path,
                content=draft.content,
                keywords=draft.keywords,
                security_level=doc.security_level,
                version=doc.version,
            )
            self._db.add(chunk)
            chunks.append(chunk)
        await self._db.flush()

        for chunk, vector in zip(chunks, vectors, strict=False):
            chunk.embedding_id = str(chunk.id)
            try:
                store.upsert_chunk(
                    kb_key=kb_id_str,
                    chunk_id=str(chunk.id),
                    vector=vector,
                    payload={"doc_id": str(doc.id), "chunk_index": chunk.chunk_index},
                )
            except Exception:  # noqa: BLE001
                pass  # Qdrant 不可用时静默降级，retrieval_service 会走内存兜底

        doc.parse_status = "indexed"
        await self._db.flush()

    async def publish_document(self, doc: Document) -> None:
        if doc.parse_status != "indexed":
            raise ValueError(f"文档当前状态为 {doc.parse_status}，需先完成索引才能发布")
        doc.parse_status = "published"
        await self._db.flush()

    async def get_chunk_count(self, doc_id: uuid.UUID) -> int:
        result = await self._db.execute(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id))
        return len(result.scalars().all())
