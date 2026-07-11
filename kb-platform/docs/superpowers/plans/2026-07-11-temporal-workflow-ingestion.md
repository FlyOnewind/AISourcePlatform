# Temporal Workflow and Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable Temporal DAG execution, approval, compensation, cancellation, and asynchronous document ingestion.

**Architecture:** PostgreSQL stores immutable workflow definitions and execution summaries. Temporal stores execution history. Deterministic Workflows coordinate Gateway and knowledge Activities on isolated task queues.

**Tech Stack:** Temporal Server 1.29.x, Temporal Python SDK 1.x, PostgreSQL, MinIO, FastAPI, pytest, Temporal test environment.

## Global Constraints

- Workflow code performs no network, database, random, wall-clock, or LLM I/O.
- Published workflow versions are immutable and passed as complete snapshots.
- Approval Signals are sent only after API authorization and durable approval recording.
- Compensation runs in reverse completion order and never changes a failed execution to success.
- Document upload returns `202` before parsing starts.
- Every behavior starts with a failing test.

---

## File Map

- Create `app/models/workflow.py`, `app/schemas/workflow.py`.
- Create `app/workflows/contracts.py`, `validation.py`, `capability_dag.py`, `document_ingestion.py`, `activities.py`, `worker.py`, `client.py`.
- Create `app/api/v1/workflows.py`, `app/api/v1/document_jobs.py`.
- Modify `app/api/v1/knowledge.py`, `app/services/knowledge_service.py`, `app/main.py`, `docker-compose.yml`, `.env.example`, `pyproject.toml`.
- Create Alembic revision `0002_temporal_workflows.py`.

### Task 1: Temporal configuration and Compose services

**Files:** `pyproject.toml`, `app/core/config.py`, `.env.example`, `docker-compose.yml`, `app/workflows/client.py`, `tests/workflows/test_temporal_connection.py`.

- [ ] Write a failing configuration test asserting `temporal_address`, namespace, and three task queues.
- [ ] Run: `uv run pytest tests/workflows/test_temporal_connection.py -q`; expect FAIL.
- [ ] Add `temporalio>=1.16,<2`, Temporal Server/UI services, health checks, and `get_temporal_client()`.
- [ ] Run: `docker compose config && uv run pytest tests/workflows/test_temporal_connection.py -q`; expect PASS.
- [ ] Commit: `git commit -am "build: add temporal runtime"` plus new files.

### Task 2: Workflow persistence and DAG publication validation

**Files:** `app/models/workflow.py`, `app/schemas/workflow.py`, `app/workflows/validation.py`, `alembic/versions/0002_temporal_workflows.py`, `tests/workflows/test_dag_validation.py`.

**Interfaces:** `validate_workflow_definition(definition: WorkflowDefinitionData) -> None`.

- [ ] Write failing tests for cycles, missing branch edges, unreachable end nodes, invalid capability versions, and a valid parallel/approval graph.
- [ ] Run: `uv run pytest tests/workflows/test_dag_validation.py -q`; expect FAIL.
- [ ] Implement node discriminated unions and Kahn topological validation:

```python
class CapabilityNode(BaseModel):
    type: Literal["capability"]
    capability_code: str
    version: str
    compensation_capability_code: str | None = None

class ApprovalNode(BaseModel):
    type: Literal["approval"]
    approver_roles: list[str]
    on_reject: str
```

- [ ] Run migration and tests; expect PASS.
- [ ] Commit: `git commit -m "feat: validate immutable workflow dags"`.

### Task 3: Generic Temporal DAG Workflow

**Files:** `app/workflows/contracts.py`, `app/workflows/capability_dag.py`, `app/workflows/activities.py`, `tests/workflows/test_capability_dag.py`.

**Interfaces:** `CapabilityDAGWorkflow.run(WorkflowExecutionInput) -> WorkflowExecutionResult`; Signals `approve`, `reject`, `cancel`; Query `state`.

- [ ] Write failing Temporal test-environment tests for condition routing, parallel-all, parallel-any, and state Query.
- [ ] Run: `uv run pytest tests/workflows/test_capability_dag.py -q`; expect FAIL.
- [ ] Implement deterministic graph scheduling and Gateway Activity calls with fixed capability versions.
- [ ] Run the tests; expect PASS.
- [ ] Commit: `git commit -m "feat: execute capability dags on temporal"`.

### Task 4: Approval and Saga compensation

**Files:** `app/workflows/capability_dag.py`, `app/models/workflow.py`, `app/api/v1/workflows.py`, `tests/workflows/test_approval_compensation.py`.

- [ ] Write failing tests proving unauthorized approval cannot send a Signal, authorized approval resumes, rejection follows `on_reject`, and compensations execute B then A after C fails.
- [ ] Run RED: `uv run pytest tests/workflows/test_approval_compensation.py -q`.
- [ ] Implement authorization-before-Signal, durable `ApprovalRecord`, `workflow.wait_condition`, and reverse compensation stack.
- [ ] Run GREEN and commit: `git commit -m "feat: add workflow approvals and compensation"`.

### Task 5: Workflow execution APIs and summaries

**Files:** `app/api/v1/workflows.py`, `app/workflows/client.py`, `app/models/workflow.py`, `app/main.py`, `tests/test_workflow_api.py`.

- [ ] Write failing API tests for create, publish, execute, query, cancel, approve, and reject.
- [ ] Run RED: `uv run pytest tests/test_workflow_api.py -q`.
- [ ] Implement routes that use Temporal Workflow IDs `wf:{workflow_code}:{execution_id}` and synchronize safe execution summaries.
- [ ] Run GREEN and commit: `git commit -m "feat: expose temporal workflow lifecycle api"`.

### Task 6: Asynchronous document-ingestion workflow

**Files:** `app/workflows/document_ingestion.py`, `app/workflows/activities.py`, `app/services/knowledge_service.py`, `app/api/v1/knowledge.py`, `app/api/v1/document_jobs.py`, `tests/workflows/test_document_ingestion.py`, `tests/test_knowledge.py`.

**Interfaces:** `DocumentIngestionWorkflow.run(DocumentIngestionInput) -> DocumentIngestionResult`.

- [ ] Write failing test asserting upload returns HTTP 202 with `workflow_id` while document status is `queued`.
- [ ] Write failing workflow test asserting parse, chunk, embed, candidate-index, validate, alias-switch, publish order and no alias switch on failure.
- [ ] Run RED: `uv run pytest tests/workflows/test_document_ingestion.py tests/test_knowledge.py -q`.
- [ ] Move synchronous processing into idempotent Activities; use checksums and versioned object/index names.
- [ ] Run GREEN and commit: `git commit -m "feat: ingest documents asynchronously with temporal"`.

### Task 7: Worker entry points and delivery gate

**Files:** `app/workflows/worker.py`, `docker-compose.yml`, `README.md`, `tests/integration/test_temporal_end_to_end.py`.

- [ ] Write failing Compose integration test that starts a workflow, waits for approval, completes, and observes summary state.
- [ ] Add separate Gateway and Knowledge/Workflow worker commands with graceful shutdown.
- [ ] Run: `docker compose up -d temporal temporal-ui gateway-worker workflow-worker && uv run pytest tests/workflows tests/integration/test_temporal_end_to_end.py -q`.
- [ ] Expected: PASS; document upload endpoint remains responsive during processing.
- [ ] Commit: `git commit -m "feat: run production temporal workers"`.

