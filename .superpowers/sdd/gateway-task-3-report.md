# Gateway Task 3 Report

## Status

Implemented endpoint and invocation persistence only. No runtime routing, Redis controls,
protocol adapters, or API endpoints were added.

## RED evidence

1. Initial focused run:

   `DATABASE_URL=postgresql+asyncpg://kbplatform:kbplatform@127.0.0.1:5432/kbplatform python -m pytest tests/gateway/test_gateway_models.py -q`

   Result: collection failed with `ModuleNotFoundError: No module named 'app.models.gateway'`,
   confirming the requested model surface did not exist.

2. After adding the minimal schema/model surface, the focused run executed 23 tests:

   Result: `21 passed, 2 failed`. The failures were the expected migration gaps:
   Alembic head was `0001` instead of `0002`, and a fresh upgrade did not create the five
   Gateway tables.

## GREEN evidence

- Focused suite: `23 passed in 13.11s`.
- Required regression suite (`test_gateway_models.py`, `test_migrations.py`,
  `test_capabilities.py`): `31 passed in 29.24s`.
- Final full suite: `64 passed, 1 warning in 55.36s`.
- Final `uv run alembic check`: `No new upgrade operations detected.`
- Final `git diff --check`: exit code 0.

All pytest and Alembic commands used the required IPv4 `DATABASE_URL`.

## Files

- Created `kb-platform/app/models/gateway.py`.
- Modified `kb-platform/app/models/__init__.py`.
- Created `kb-platform/app/schemas/gateway.py`.
- Created `kb-platform/alembic/versions/0002_gateway_models.py`.
- Created `kb-platform/tests/gateway/test_gateway_models.py`.

## Implemented contracts

- Five SQLAlchemy models/tables with UUID keys and timestamps.
- Endpoint environment-scoped uniqueness, positive weight/non-negative priority checks,
  supported-protocol check, and same-capability fallback composite foreign key.
- Invocation key uniqueness and PostgreSQL partial uniqueness for non-null idempotency keys.
- MCP transport, gRPC source/descriptor artifact, and A2A capability persistence.
- Strict Pydantic protocol configurations that reject extras/raw secrets and accept only
  the specified protocol values.
- Forward and reverse migration coverage on fresh PostgreSQL databases.

## Commit

Subject: `feat: persist gateway endpoints and invocations` (the implementation commit
containing this report).

## Self-review

- Confirmed every requested field, nullability rule, uniqueness rule, and index is present
  in both SQLAlchemy metadata and revision `0002`.
- Confirmed downgrade order removes only the five Gateway tables and preserves revision
  `0001` tables.
- Confirmed protocol secrets are represented only by `secret_ref`; strict schemas reject
  `api_key`, `token`, and `password` extras.
- Confirmed no runtime routing, adapter, Redis, or API code is present in the diff.
- Removed one unused test import and reformatted the aggregate model import during refactor.

## Concerns

- The final full suite emits one pre-existing Qdrant client warning because a Qdrant server
  version could not be queried; all tests still pass and the warning is unrelated to this task.
- The specified development database contained the initial 15 tables but no Alembic stamp.
  After verifying it had no Gateway tables, it was safely stamped at `0001` and upgraded to
  `0002` so the required drift check could run. Fresh-database upgrade/downgrade behavior is
  independently covered by the tests.

## Review fixes (2026-07-12)

### Commits

- Initial Task 3 implementation: `6af87eb` (`6af87ebff5206f4c381904f429bf89a0c3ad527a`).
- Persistence review fixes: `3c2a6d9` (`3c2a6d933a73720bb1f7baee93670ece695d0ca6`).

### RED evidence

After adding the review regressions and before changing production code, the focused command

`python -m pytest tests/gateway/test_gateway_models.py -q`

reported `3 failed, 24 passed`. The expected failures proved that:

- `ck_capability_invocation_protocol` was absent from SQLAlchemy metadata;
- an unsupported persisted invocation protocol did not raise `IntegrityError`;
- a direct PostgreSQL update could change `capability_version`.

### GREEN evidence

- Focused Gateway suite: `27 passed in 15.42s`.
- Required regression suite: `35 passed in 28.88s`.
- Full project suite: `68 passed, 1 warning in 65.42s`.
- Revised `0002` downgrade to `0001` and upgrade to head both completed successfully.
- `uv run alembic check`: `No new upgrade operations detected.`
- `git diff --check`: exit code 0.

All pytest and Alembic commands used
`postgresql+asyncpg://kbplatform:kbplatform@127.0.0.1:5432/kbplatform`.

### Review-fix scope

- Added the exact supported-protocol check to both `CapabilityInvocation` metadata and
  revision `0002`.
- Added a PostgreSQL trigger/function that rejects changes to an inserted invocation's
  `capability_version`, including direct/bulk SQL, while allowing status updates.
- Added explicit trigger/function removal to downgrade and verified the function is absent.
- Audited required constraints and unique/partial indexes in SQLAlchemy metadata and the
  PostgreSQL catalog after a fresh migration.
- Verified identical endpoint environment/name pairs remain valid across capabilities.

### Review concerns

- The full suite still emits the unrelated Qdrant server-version compatibility warning.
- The local Gateway tables were verified empty before rebuilding revision `0002` to exercise
  the revised migration; no application data was removed.
