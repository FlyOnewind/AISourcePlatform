# Knowledge Maintenance Admin Design

Date: 2026-07-13
Status: Approved

## Objective

Complete the knowledge-base administration lifecycle in the existing static admin console. Administrators must be able to maintain knowledge bases, documents, and chunks without using Swagger or direct database access.

The implementation retains FastAPI, PostgreSQL, MinIO, Qdrant, and the build-free HTML/CSS/JavaScript admin console. Temporal-based asynchronous processing remains a separate architecture task; this increment keeps the existing synchronous document pipeline while making its state and failures accurate and actionable.

## Scope

### Knowledge bases

- List, search, inspect, edit, soft-delete, view deleted items, and restore.
- Edit name, business domain, owner department, security level, and retrieval/chunking configuration.
- Soft-deleting a knowledge base cascades to its documents and chunks and removes their vectors from online retrieval.
- Restoring a knowledge base leaves it unpublished until an administrator reviews and publishes content.

### Documents

- List and filter documents by text and processing state.
- Upload one or more supported files.
- Inspect metadata, processing state, errors, and chunk count.
- Edit document metadata, publish, unpublish, reprocess, soft-delete, and restore.
- Reprocessing removes old online vectors and generated chunks, then parses, chunks, embeds, and indexes the retained MinIO source again.

### Chunks

- Paginated list and text search within a document.
- View full content, title path, keywords, version, security level, and index state.
- Edit content and metadata, soft-delete, and restore.
- Saving content regenerates that chunk's embedding and updates Qdrant before reporting success.

### Out of scope

- Temporal workers, asynchronous progress events, cancellation, and distributed retry.
- Physical purge of soft-deleted MinIO objects.
- OCR and new file formats.
- Replacement of the static admin console with a framework application.

## Data Model

Add nullable `deleted_at` timestamps to `knowledge_bases`, `documents`, and `knowledge_chunks`. Default resource queries exclude rows whose `deleted_at` is set. Administrative recycle-bin queries explicitly request deleted rows.

Document processing state remains visible and gains accurate failure handling. Qdrant failures set `parse_status` to `index_failed` and persist `parse_error`; they must not result in `indexed` status.

Knowledge-base `retrieval_config` stores maintainable chunk settings. The first supported option is maximum chunk characters, validated within a safe bounded range. Existing records use the current 800-character default.

## API Contract

### Knowledge bases

- `PATCH /api/v1/knowledge-bases/{id}` updates editable fields.
- `DELETE /api/v1/knowledge-bases/{id}` soft-deletes the knowledge base and descendants.
- `POST /api/v1/knowledge-bases/{id}/restore` restores the knowledge base in an unpublished state.
- List endpoints accept search and deleted-state filters.

### Documents

- `PATCH /api/v1/documents/{id}` updates editable metadata.
- `DELETE /api/v1/documents/{id}` soft-deletes the document and chunks.
- `POST /api/v1/documents/{id}/restore` restores the document without publishing it.
- `POST /api/v1/documents/{id}/publish` publishes an indexed document.
- `POST /api/v1/documents/{id}/unpublish` returns it to indexed state.
- `POST /api/v1/documents/{id}/reprocess` rebuilds generated chunks and vectors from the retained source object.
- Document list endpoints accept text, status, and deleted-state filters.

### Chunks

- `GET /api/v1/documents/{id}/chunks` provides pagination, search, and deleted-state filtering.
- `GET /api/v1/chunks/{id}` returns chunk detail.
- `PATCH /api/v1/chunks/{id}` updates content or metadata and reindexes changed content.
- `DELETE /api/v1/chunks/{id}` soft-deletes and removes the vector from online retrieval.
- `POST /api/v1/chunks/{id}/restore` restores and reindexes the chunk.

All mutation endpoints require `platform_admin` or `knowledge_admin`. Mutations produce audit events containing actor, action, resource identity, trace ID, and non-secret change metadata.

## Processing and Consistency

The API remains synchronous for this increment. Upload and reprocess requests return only after parsing and indexing complete or fail. The UI disables duplicate actions while a request is active.

Database state is authoritative for lifecycle status. Vector changes are attempted before an operation reports success. If vector insertion fails, the document or chunk records the failure and the API returns an actionable error. Deletion and restore operations are idempotent.

Retrieval excludes soft-deleted knowledge bases, documents, and chunks. It also excludes unpublished documents so that restoring data never makes it searchable accidentally.

## Admin Console

Knowledge maintenance code moves from the oversized `admin_console/app.js` into `admin_console/knowledge.js`, loaded after the shared application utilities. The console remains build-free.

The page contains three coordinated levels:

1. Knowledge-base cards with search, edit, delete, recycle-bin, restore, and document navigation.
2. A document table with search, state filter, upload, detail, publish/unpublish, reprocess, delete, and restore actions.
3. A document-detail drawer containing paginated chunks with search, full-content view, edit, delete, and restore actions.

Destructive operations require confirmation. API failures remain visible in the active view and provide a retry action where applicable. Successful operations refresh only the affected list and counters.

## Validation and Error Handling

- Editable schemas reject empty names, invalid security levels, and unsafe chunk-size values.
- Unsupported file types and empty parse results return explicit validation failures.
- A missing MinIO source prevents reprocessing and produces a retained error state.
- A Qdrant failure cannot be silently converted into an indexed state.
- Concurrent duplicate actions are prevented in the UI; server operations remain idempotent where practical.

## Minimal Verification

Only focused tests are required for this increment:

- `tests/test_knowledge_maintenance.py`
- `tests/test_knowledge.py`
- `tests/test_migrations.py`
- A static admin-console API contract check.
- One live smoke flow: create knowledge base, upload document, view and edit a chunk, publish, soft-delete, and restore.

The full pytest suite is intentionally excluded at the user's request.

## Acceptance Criteria

- An administrator can complete the supported knowledge-base, document, and chunk lifecycle entirely from `/admin`.
- A newly uploaded document's full content and generated chunks are inspectable from the console.
- Editing a chunk updates both PostgreSQL and its vector index.
- Soft-deleted resources disappear from default lists and retrieval and are visible in the recycle bin.
- Restored resources remain unpublished until explicitly published.
- Index failures are visible and never reported as successful indexing.
- Focused tests and the live smoke flow pass.
