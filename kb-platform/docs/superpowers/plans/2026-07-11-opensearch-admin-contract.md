# OpenSearch Retrieval and Admin Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist embeddings, replace full-scan retrieval with OpenSearch hybrid search, migrate Qdrant safely, expose explicit failure semantics, and repair the admin permission-delete contract.

**Architecture:** OpenSearch holds capability and knowledge search documents behind versioned aliases. Temporal Activities build candidate indexes and switch aliases only after validation. PostgreSQL remains the metadata authority.

**Tech Stack:** OpenSearch 3.x, opensearch-py async client, Temporal Activities, Redis degraded cache, pytest, Docker Compose.

## Global Constraints

- Permission, tenant, environment, status, and risk filters run before scoring.
- Each query creates one query embedding; stored documents are never re-embedded during search.
- OpenSearch outage returns 503 unless an explicit low-risk cached-degradation policy applies.
- No PostgreSQL full scan or in-memory cosine fallback.
- Qdrant remains until migration verification succeeds, then leaves the serving path and Compose.
- Every behavior starts with a failing test.

---

## File Map

- Create `app/search/client.py`, `mappings.py`, `indexing.py`, `capability_search.py`, `knowledge_search.py`, `errors.py`, `migration.py`.
- Create `app/models/search.py`, `app/schemas/search.py`, Alembic revision `0003_search_indexes.py`.
- Modify `app/services/capability_service.py`, `app/services/retrieval_service.py`, `app/services/knowledge_service.py`, `app/api/v1/capabilities.py`, `app/api/v1/knowledge.py`.
- Modify `app/api/v1/capabilities.py` and `admin_console/app.js` for permission deletion.
- Modify `docker-compose.yml`, `.env.example`, `pyproject.toml`, `README.md`.

### Task 1: OpenSearch client, mappings, and index versions

**Files:** `pyproject.toml`, `app/core/config.py`, `app/search/client.py`, `app/search/mappings.py`, `app/models/search.py`, `alembic/versions/0003_search_indexes.py`, `tests/search/test_mappings.py`.

- [ ] Write failing tests asserting capability/knowledge mappings contain `knn_vector`, keyword filter fields, and strict dimensions.
- [ ] Run RED: `uv run pytest tests/search/test_mappings.py -q`.
- [ ] Add `opensearch-py>=3,<4`, async client configuration, `IndexVersion`, and exact mapping builders.
- [ ] Run GREEN and commit: `git commit -m "feat: add versioned opensearch mappings"`.

### Task 2: Capability persistent indexing

**Files:** `app/search/indexing.py`, `app/workflows/activities.py`, `tests/search/test_capability_indexing.py`.

**Interfaces:** `CapabilityIndexer.index_version(capability_id, version) -> IndexDocumentResult`.

- [ ] Write failing test proving unchanged checksums do not call the embedding provider twice.
- [ ] Write failing test asserting indexed fields include Schema property names, permissions, health, quality, cost, model, dimension, and checksum.
- [ ] Run RED.
- [ ] Implement stable canonical text and bulk upsert.
- [ ] Run GREEN and commit: `git commit -m "feat: persist capability search vectors"`.

### Task 3: Capability hybrid search

**Files:** `app/search/capability_search.py`, `app/services/capability_service.py`, `tests/search/test_capability_search.py`.

**Interfaces:** `CapabilitySearchService.search(subject, request) -> list[CapabilitySearchHit]`.

- [ ] Write failing test asserting one query embedding call and no `select(Capability)` full-table load.
- [ ] Write failing test asserting authorization filters are in the OpenSearch request body before the hybrid clauses.
- [ ] Implement BM25 + k-NN hybrid query and deterministic reranking.
- [ ] Run: `uv run pytest tests/search/test_capability_search.py tests/test_capabilities.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat: use opensearch for capability discovery"`.

### Task 4: Knowledge candidate indexes and hybrid retrieval

**Files:** `app/search/knowledge_search.py`, `app/search/indexing.py`, `app/services/retrieval_service.py`, `app/workflows/activities.py`, `tests/search/test_knowledge_search.py`.

- [ ] Write failing tests for permission pre-filtering, version aliases, BM25/vector fusion, citations, and atomic alias switch.
- [ ] Write failing test asserting index-build failure leaves the old alias unchanged.
- [ ] Remove Qdrant and in-memory fallback from `RetrievalService`; delegate to `KnowledgeSearchService`.
- [ ] Run GREEN and commit: `git commit -m "feat: add versioned knowledge hybrid search"`.

### Task 5: Explicit outage and controlled degradation

**Files:** `app/search/errors.py`, `app/search/capability_search.py`, `app/search/knowledge_search.py`, `app/api/v1/capabilities.py`, `app/api/v1/knowledge.py`, `tests/search/test_failure_semantics.py`.

- [ ] Write failing tests asserting OpenSearch errors return HTTP 503 and never call PostgreSQL chunk/capability full scans.
- [ ] Write failing low-risk-cache test asserting `degraded=true`, cache timestamp, and index version.
- [ ] Implement explicit `SearchBackendUnavailable` mapping and policy-gated Redis cache.
- [ ] Run GREEN and commit: `git commit -m "fix: make search degradation explicit"`.

### Task 6: Qdrant migration and removal gate

**Files:** `app/search/migration.py`, `scripts/migrate_qdrant_to_opensearch.py`, `tests/integration/test_qdrant_migration.py`, `docker-compose.yml`.

- [ ] Write failing integration test that seeds Qdrant, migrates, verifies document/vector counts and samples, and switches aliases only after success.
- [ ] Implement resumable migration checkpoints and a `--verify-only` mode.
- [ ] Run: `uv run pytest tests/integration/test_qdrant_migration.py -q`; expect PASS.
- [ ] Remove Qdrant service/config/dependency only after the test and a real local verification pass.
- [ ] Commit: `git commit -m "chore: migrate qdrant indexes to opensearch"`.

### Task 7: Permission delete API and frontend contract

**Files:** `app/api/v1/capabilities.py`, `admin_console/app.js`, `tests/test_capability_permissions.py`, `tests/test_admin_contracts.py`.

- [ ] Write failing API tests for authorized delete, wrong-capability permission ID, missing permission, and unauthorized actor.
- [ ] Write failing static contract test that extracts admin `apiFetch` method/path pairs and matches them against generated OpenAPI paths.
- [ ] Implement `DELETE /api/v1/capabilities/{capability_id}/permissions/{permission_id}` with ownership constraint and audit.
- [ ] Run: `uv run pytest tests/test_capability_permissions.py tests/test_admin_contracts.py -q`; expect PASS.
- [ ] Commit: `git commit -m "fix: align admin permission delete contract"`.

### Task 8: Compose and end-to-end delivery gate

**Files:** `docker-compose.yml`, `.env.example`, `README.md`, `tests/integration/test_search_end_to_end.py`.

- [ ] Add OpenSearch and Dashboards with pinned images, volumes, health checks, memory settings, and development-only security configuration.
- [ ] Write an end-to-end test that registers and indexes capabilities, uploads and publishes knowledge asynchronously, searches both indexes, and verifies explicit outage behavior.
- [ ] Run: `docker compose up -d && docker compose ps && uv run pytest tests/search tests/integration/test_search_end_to_end.py tests/test_admin_contracts.py -q`.
- [ ] Expected: all required services healthy and tests PASS without fallback warnings.
- [ ] Commit: `git commit -m "feat: complete opensearch production retrieval"`.

