# Knowledge Maintenance Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a complete knowledge-base, document, and chunk maintenance lifecycle in the existing `/admin` console, including soft deletion, restoration, processing controls, and chunk inspection/editing.

**Architecture:** Extend the existing SQLAlchemy resources and FastAPI router with focused lifecycle services and schemas, while keeping PostgreSQL authoritative and Qdrant synchronized. Move knowledge-page behavior into a build-free `admin_console/knowledge.js` module that consumes the REST contract through existing shared UI helpers.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, PostgreSQL, MinIO, Qdrant, Pydantic v2, pytest/httpx, vanilla HTML/CSS/JavaScript.

## Global Constraints

- Deletion is soft deletion; MinIO source objects are retained.
- Restored resources remain unpublished until explicitly published.
- Temporal asynchronous processing is out of scope; upload and reprocess remain synchronous.
- Qdrant failures must produce an `index_failed` state and visible error.
- The admin console remains build-free and is served from `/admin`.
- Run only the focused tests named in this plan; do not run the full pytest suite.

## File Structure

- `alembic/versions/0003_knowledge_maintenance.py`: lifecycle columns and indexes.
- `app/models/knowledge.py`: ORM lifecycle fields.
- `app/schemas/knowledge.py`: update, chunk, filter, and page contracts.
- `app/core/vector_store.py`: point-level vector deletion.
- `app/services/knowledge_service.py`: reprocess, chunk update, vector synchronization, lifecycle operations.
- `app/services/retrieval_service.py`: excludes deleted and unpublished documents/chunks.
- `app/api/v1/knowledge.py`: REST endpoints, filters, authorization, and audit calls.
- `admin_console/knowledge.js`: knowledge-page state, rendering, and actions.
- `admin_console/index.html`: knowledge maintenance controls and script loading.
- `admin_console/style.css`: drawer, chunk editor, recycle-bin, and processing states.
- `tests/test_knowledge_maintenance.py`: focused lifecycle API/service tests.
- `tests/test_knowledge.py`: existing upload/search regression tests.
- `tests/test_migrations.py`: migration column assertions.
- `tests/test_admin_knowledge_contract.py`: static frontend/API contract test.

---

### Task 1: Persist lifecycle state and validation contracts

**Files:**
- Create: `alembic/versions/0003_knowledge_maintenance.py`
- Modify: `app/models/knowledge.py`
- Modify: `app/schemas/knowledge.py`
- Modify: `tests/test_migrations.py`
- Create: `tests/test_knowledge_maintenance.py`

**Interfaces:**
- Produces: `deleted_at` on all three knowledge resources.
- Produces: `KnowledgeBaseUpdate`, `DocumentUpdate`, `ChunkUpdate`, `ChunkOut`, and `ChunkPage` schemas.
- Consumes: existing `TimestampMixin`, PostgreSQL JSONB/ARRAY, and Pydantic v2.

- [ ] **Step 1: Write failing migration and schema tests**

Add a migration assertion that queries `information_schema.columns` for `deleted_at` on `knowledge_bases`, `documents`, and `knowledge_chunks`. Add schema tests that reject blank names/content, invalid security levels, and `max_chunk_chars` outside 200–4000.

```python
def test_knowledge_update_validation():
    with pytest.raises(ValidationError):
        KnowledgeBaseUpdate(name=" ")
    with pytest.raises(ValidationError):
        KnowledgeBaseUpdate(retrieval_config={"max_chunk_chars": 100})
    with pytest.raises(ValidationError):
        ChunkUpdate(content="")
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_knowledge_maintenance.py::test_knowledge_update_validation tests/test_migrations.py::test_alembic_upgrade_head_creates_existing_tables -q`

Expected: FAIL because update schemas and `deleted_at` columns do not exist.

- [ ] **Step 3: Add migration and ORM fields**

Create revision `0003` with `down_revision = "0002"` and add timezone-aware nullable timestamps plus indexes:

```python
def upgrade() -> None:
    for table in ("knowledge_bases", "documents", "knowledge_chunks"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])
```

Mirror each field as `Mapped[datetime | None]` in the ORM.

- [ ] **Step 4: Add validated schemas**

Use `field_validator` for trimmed non-empty values and a typed retrieval configuration:

```python
class RetrievalConfig(BaseModel):
    max_chunk_chars: int = Field(default=800, ge=200, le=4000)

class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    business_domain: str | None = None
    owner_department: str | None = None
    security_level: Literal["public", "internal", "confidential", "restricted"] | None = None
    retrieval_config: RetrievalConfig | None = None

class ChunkPage(BaseModel):
    items: list[ChunkOut]
    total: int
    page: int
    page_size: int
```

Expose `deleted_at` in administrative outputs.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run pytest tests/test_knowledge_maintenance.py::test_knowledge_update_validation tests/test_migrations.py::test_alembic_upgrade_head_creates_existing_tables -q`

Expected: PASS.

Commit: `git commit -am "feat: add knowledge lifecycle persistence"` after staging the new files explicitly.

---

### Task 2: Make vector and document processing lifecycle-safe

**Files:**
- Modify: `app/core/vector_store.py`
- Modify: `app/services/chunkers/simple_chunker.py`
- Modify: `app/services/knowledge_service.py`
- Modify: `tests/test_knowledge_maintenance.py`

**Interfaces:**
- Produces: `VectorStore.delete_chunks(kb_key: str, chunk_ids: list[str]) -> None`.
- Produces: `KnowledgeService.reprocess_document(doc)`, `update_chunk(chunk, payload)`, `soft_delete_*`, and `restore_*`.
- Consumes: `ObjectStorage.get_object`, `LLMProvider.embed`, and ORM lifecycle fields from Task 1.

- [ ] **Step 1: Write failing service tests with real database rows and faked external adapters**

Test these behaviors independently:

```python
async def test_chunk_edit_reembeds_and_upserts(...):
    updated = await service.update_chunk(chunk, ChunkUpdate(content="updated text"))
    assert updated.content == "updated text"
    assert fake_store.upserts[-1].chunk_id == str(chunk.id)

async def test_index_failure_sets_visible_failure(...):
    fake_store.raise_on_upsert = RuntimeError("qdrant unavailable")
    await service.process_document(doc, b"hello", "a.txt")
    assert doc.parse_status == "index_failed"
    assert "qdrant unavailable" in doc.parse_error
```

Also test cascading soft deletion and restoration leaving resources unpublished.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_knowledge_maintenance.py -q -k "chunk_edit or index_failure or soft_delete or restore"`

Expected: FAIL because lifecycle service methods and point deletion do not exist.

- [ ] **Step 3: Add point deletion and configurable chunk sizing**

Implement Qdrant point deletion:

```python
def delete_chunks(self, kb_key: str, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    name = self._collection_name(kb_key)
    if self._client.collection_exists(name):
        self._client.delete(name, points_selector=qmodels.PointIdsList(points=chunk_ids))
```

Change `chunk_text(raw_text, max_chunk_chars=800)` and pass the knowledge base's validated setting.

- [ ] **Step 4: Implement lifecycle service methods**

Use injected optional storage/vector adapters in `KnowledgeService.__init__` for testability. Reprocessing resolves the retained object name by removing the bucket prefix from `object_uri`, deletes old vectors and chunks, and invokes the same processing pipeline. Do not swallow vector exceptions:

```python
try:
    store.upsert_chunk(...)
except Exception as exc:
    doc.parse_status = "index_failed"
    doc.parse_error = f"向量索引失败: {exc}"
    await self._db.flush()
    return
```

Chunk edits upsert the new embedding before returning success. Soft deletion sets UTC timestamps, removes online vectors, and is idempotent. Restoration clears timestamps but uses `indexed` rather than `published` state.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run pytest tests/test_knowledge_maintenance.py -q -k "chunk_edit or index_failure or soft_delete or restore or reprocess"`

Expected: PASS.

Commit: `git commit -am "feat: add knowledge lifecycle services"`.

---

### Task 3: Expose authenticated maintenance APIs and safe retrieval

**Files:**
- Modify: `app/api/v1/knowledge.py`
- Modify: `app/services/retrieval_service.py`
- Modify: `tests/test_knowledge_maintenance.py`
- Modify: `tests/test_knowledge.py`

**Interfaces:**
- Produces: the REST contract from the approved design.
- Consumes: Task 1 schemas, Task 2 service methods, `AuditService`, `get_trace_id`, and `require_admin_roles`.

- [ ] **Step 1: Write failing API lifecycle tests**

Cover update, filters, publish/unpublish, reprocess, soft delete/restore, pagination, chunk edit, audit creation, and non-admin rejection. Use existing `_create_admin` patterns and assert envelope data:

```python
response = await client.get(
    f"/api/v1/documents/{doc_id}/chunks?page=1&page_size=20",
    headers={"X-API-Key": admin_key},
)
assert response.status_code == 200
assert response.json()["data"]["total"] > 0

deleted = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
assert deleted.status_code == 200
assert (await client.get(f"/api/v1/knowledge-bases/{kb_id}/documents", headers=headers)).json()["data"] == []
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_knowledge_maintenance.py -q -k "api or filter or audit or retrieval"`

Expected: FAIL with 404/405 for missing endpoints or deleted rows still visible.

- [ ] **Step 3: Implement query filters and endpoints**

Add helpers `_resolve_document`, `_resolve_chunk`, `_audit_mutation`, and deleted-state conditions. Use `page >= 1`, `1 <= page_size <= 100`, and case-insensitive search. Return 404 for resources excluded by the requested deleted-state view.

Each mutation follows:

```python
await service.soft_delete_document(doc)
await AuditService(db).log(
    trace_id=trace_id,
    actor_type=identity.actor_type,
    actor_id=identity.key,
    action="delete_document",
    resource_type="document",
    resource_id=str(doc.id),
)
await db.commit()
return ok({"id": str(doc.id), "deleted": True}, trace_id)
```

- [ ] **Step 4: Exclude inactive lifecycle rows from retrieval**

Join `Document` and require:

```python
stmt = stmt.join(Document, KnowledgeChunk.doc_id == Document.id).where(
    KnowledgeBase.deleted_at.is_(None),
    Document.deleted_at.is_(None),
    KnowledgeChunk.deleted_at.is_(None),
    KnowledgeBase.status == "published",
    Document.parse_status == "published",
)
```

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run pytest tests/test_knowledge_maintenance.py tests/test_knowledge.py -q`

Expected: PASS.

Commit: `git commit -am "feat: expose knowledge maintenance APIs"`.

---

### Task 4: Establish the build-free frontend maintenance contract

**Files:**
- Create: `admin_console/knowledge.js`
- Modify: `admin_console/app.js`
- Modify: `admin_console/index.html`
- Create: `tests/test_admin_knowledge_contract.py`

**Interfaces:**
- Consumes: global `apiFetch`, `showToast`, `showModal`, `escapeHtml`, `badge`, and `appState` from `app.js`.
- Produces: `window.KnowledgeAdmin` with `loadKnowledgeBases()`, `selectKnowledgeBase(id)`, and action handlers.

- [ ] **Step 1: Write the failing static contract test**

```python
def test_admin_loads_knowledge_module_and_uses_maintenance_endpoints():
    html = Path("admin_console/index.html").read_text(encoding="utf-8")
    js = Path("admin_console/knowledge.js").read_text(encoding="utf-8")
    assert '<script src="knowledge.js"></script>' in html
    for fragment in (
        "/documents/${documentId}/chunks",
        "/documents/${documentId}/publish",
        "/documents/${documentId}/reprocess",
        "/chunks/${chunkId}",
    ):
        assert fragment in js
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_admin_knowledge_contract.py -q`

Expected: FAIL because `knowledge.js` does not exist.

- [ ] **Step 3: Create module state and API actions**

Define an IIFE with private state and exposed handlers:

```javascript
window.KnowledgeAdmin = (() => {
  const state = { kbId: null, documentId: null, chunkPage: 1, includeDeleted: false };
  async function request(path, options) { return apiFetch(path, options); }
  async function publishDocument(documentId) {
    await request(`/api/v1/documents/${documentId}/publish`, { method: 'POST' });
    showToast('文档已发布', 'success');
    return loadDocuments();
  }
  return { loadKnowledgeBases, selectKnowledgeBase, publishDocument };
})();
```

Move the existing knowledge-page functions from `app.js` without duplicating global names, and delegate page navigation to the module.

- [ ] **Step 4: Load the module after shared utilities**

Place `<script src="knowledge.js"></script>` after `app.js`. Keep startup listeners in `app.js` but call `KnowledgeAdmin.loadKnowledgeBases()`.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run pytest tests/test_admin_knowledge_contract.py -q`

Expected: PASS.

Commit: `git commit -am "refactor: isolate knowledge admin module"` after staging new files.

---

### Task 5: Build the knowledge, document, and chunk maintenance UI

**Files:**
- Modify: `admin_console/knowledge.js`
- Modify: `admin_console/index.html`
- Modify: `admin_console/style.css`
- Modify: `tests/test_admin_knowledge_contract.py`

**Interfaces:**
- Consumes: Task 3 REST endpoints and Task 4 module boundary.
- Produces: searchable knowledge cards, document table, recycle views, and chunk detail drawer.

- [ ] **Step 1: Extend failing static contract assertions**

Assert accessible controls and handlers exist:

```python
for control_id in (
    "knowledge-recycle-toggle", "document-search", "document-status-filter",
    "document-detail-drawer", "chunk-search", "chunk-list", "chunk-editor",
):
    assert f'id="{control_id}"' in html
assert "editChunk" in js
assert "restoreDocument" in js
assert "softDeleteKnowledgeBase" in js
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_admin_knowledge_contract.py -q`

Expected: FAIL with the first missing control or handler.

- [ ] **Step 3: Add page controls and drawer markup**

Add labeled search/filter controls, edit forms, processing/error text, recycle toggle, and an `aria-labelledby` drawer. Buttons must be actual `<button>` elements and destructive buttons must open the existing confirmation modal.

- [ ] **Step 4: Implement rendering and operations**

Implement focused functions for list fetching and DOM rendering, not one monolithic render function. Escape all server-provided text. Disable action buttons while requests are pending and use `try/finally` to restore them. Chunk edits send only changed fields through `PATCH /api/v1/chunks/{id}` and refresh the chunk row after success.

Document rows expose actions according to lifecycle state:

- `indexed`: publish, reprocess, delete.
- `published`: unpublish, reprocess, delete.
- `parse_failed` or `index_failed`: inspect error, reprocess, delete.
- deleted view: restore only.

- [ ] **Step 5: Add responsive styles**

Use existing CSS variables. The drawer is fixed on desktop and full-width on narrow screens; chunk content uses wrapped preformatted text; focus and destructive states remain visible.

- [ ] **Step 6: Verify GREEN and commit**

Run: `uv run pytest tests/test_admin_knowledge_contract.py -q`

Expected: PASS.

Commit: `git commit -am "feat: add knowledge maintenance admin UI"`.

---

### Task 6: Focused migration and live lifecycle verification

**Files:**
- Modify only if a focused verification exposes a defect in the preceding task's files.

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: verified running migration, API, and admin lifecycle.

- [ ] **Step 1: Apply migration**

Run: `uv run alembic upgrade head`

Expected: current revision becomes `0003 (head)`.

- [ ] **Step 2: Run only the approved focused tests**

Run:

```text
uv run pytest tests/test_knowledge_maintenance.py tests/test_knowledge.py tests/test_migrations.py tests/test_admin_knowledge_contract.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 3: Restart API and execute the live smoke lifecycle**

Use the seeded admin key without printing it. Against `http://127.0.0.1:8010`, create a uniquely keyed temporary knowledge base, upload a small Markdown file, fetch chunks, edit the first chunk, publish the document, soft-delete it, request the recycle view, and restore it. Assert every response is 200 and the edited content is returned.

- [ ] **Step 4: Verify retrieval and UI availability**

Assert `/health`, `/admin/`, and `/openapi.json` return 200. Verify default document/chunk lists omit the soft-deleted resource during the deletion stage and the recycle query includes it.

- [ ] **Step 5: Inspect scoped diff and commit any verification fix**

Run: `git diff --check` and `git status --short`. Do not stage the pre-existing `docker-compose.yml` change with feature commits. If no fix was required, do not create an empty commit.
