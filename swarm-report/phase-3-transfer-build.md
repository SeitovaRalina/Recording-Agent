# Build Report: Phase 3 — Candidate Matching and Transfer Pipeline

## Status

Complete. The `python-fastapi` scope implemented the approved
`swarm-report/phase-3-transfer-plan.md`. No migration was added and no commit was created.

## Scope

### python-fastapi

Changed application files:

- `app/config.py`
- `app/main.py`
- `app/scheduler/cron.py`
- `app/tools/__init__.py`
- `app/tools/notion.py`
- `app/tools/synology.py`
- `app/services/storage.py`
- `app/services/candidate.py`
- `app/services/transfer.py`
- `app/services/status.py`

Changed test files:

- `tests/test_notion.py`
- `tests/test_synology.py`
- `tests/test_storage.py`
- `tests/test_candidate.py`
- `tests/test_transfer.py`
- `tests/test_status.py`
- `tests/test_scheduler.py`

## Implementation

- Added typed Notion database query and page URL update client behavior.
- Added Synology FileStation backend with DSM 7 API-key authentication.
- Added `StorageBackend`, bounded-memory MinIO multipart uploads, ordered completion, and abort-on-failure cleanup.
- Added candidate matching with configured-local-timezone date selection and bounded ambiguity data.
- Added streaming transfer, controlled temporary-file fallback, and four-hour TTL cleanup.
- Added `StatusService` as the only application status-transition entry point.
- Added scheduler resume and full post-calendar transfer pipeline with per-recruiter isolation.
- Added lifespan wiring for Notion, storage, candidate, transfer, and status services.
- Corrected the Notion default name-property query to use the title filter contract.
- Implemented valid recursive Synology folder creation with explicit parent/name requests.
- Split upload and share-link steps so uploaded paths are committed before share-link creation.
- Enforced calendar-summary candidate names for destination paths.
- Added scheduler tests for no-candidate, transfer failure, resume, and recruiter isolation.

No HTTP endpoint or external wire-schema change was introduced.

## Verification

Orchestrator reran the complete gate after implementation and acceptance-audit fixes:

```text
$ poetry run ruff check app tests alembic
All checks passed!

$ poetry run ruff format --check app tests alembic
55 files already formatted

$ poetry run mypy app tests
Success: no issues found in 50 source files

$ poetry run pytest
110 passed, 1 warning in 33.01s
```

The warning is a sandbox-only `PytestCacheWarning`: the runner could not write `.pytest_cache`.
It did not affect test collection or execution.

## Audit Notes

- A first independent run exposed a repository-local temporary-file test failure
  (`1 failed, 101 passed`). The test now isolates filesystem boundaries and still verifies
  re-uploaded bytes plus cleanup invocation.
- Acceptance audit removed direct scheduler status assignments; only the recording model's
  internal transition method assigns `status`, and application code calls it through
  `StatusService`.
- Acceptance audit replaced full-file MinIO spooling with bounded-memory multipart streaming.
- The first review returned `rework` with five findings covering the Notion title filter,
  Synology folder request contract, upload-before-share persistence, calendar-derived destination
  names, and missing scheduler branch tests. The retry addressed all five findings before this
  verification run.
- `.memory-bank/open-questions.md` still marks Q1 and Q5 open. The approved plan explicitly
  declares itself the blocker source of truth and resolves both through existing
  `recruiter_config.synology_base_folder` and `recruiter_config.notion_database_id` fields.
  The implementation follows the approved plan; the stale memory entry was not edited.

## Cross-Layer Notes

- No frontend, mobile, DevOps, Terraform, or database-migration scope was required.
- Production Notion setup must use the original database UUID and share that database directly
  with the integration.
- Production Synology setup requires DSM 7 API-key access. MinIO remains the development and test
  provider.
