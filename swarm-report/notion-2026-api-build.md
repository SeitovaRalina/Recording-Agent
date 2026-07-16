# Build Report: Notion API 2026-03-11 Migration

## Status

Complete. The implementation follows `swarm-report/notion-2026-api-plan.md`. No ORM model,
Alembic migration, or persisted recruiter setting changed. No commit was created during build.

## Changed Scope

### python-fastapi

- `app/tools/notion.py`
- `tests/test_notion.py`
- `tests/test_candidate.py`
- `tests/test_scheduler.py`

### backend documentation

- `docs/api-contracts/notion.md`
- `.memory-bank/auth-flow.md`
- `.memory-bank/open-questions.md`
- `swarm-report/phase-3-transfer-plan.md`
- `swarm-report/phase-3-transfer-build.md`

## Implementation

- Set every Notion request to `Notion-Version: 2026-03-11`.
- Preserved the original database ID at configuration, service, and persistence boundaries.
- Added database-to-data-source discovery and exact schema validation for the configured
  `title`, `date`, and `files` properties.
- Required exactly one compatible source and added typed errors for missing and ambiguous schemas.
- Switched candidate lookup to `POST /v1/data_sources/{data_source_id}/query` while preserving
  page parsing, candidate cardinality rules, and page URL updates.
- Added bounded LRU resolution caching, per-key single-flight discovery, and one stale-source
  invalidation/retry.
- Added sanitized typed failures for authentication, sharing, database/source availability,
  malformed responses, queries, and updates.
- Added operation-specific typed transport failures for discovery, schema retrieval, query, and
  update; raw transport URLs and credential-bearing context are suppressed.
- Aligned the recording property with the real `Test Interviews` schema: page updates now write
  one named external Synology link to the dedicated `files` property.
- Updated authoritative documentation and added the copied-database read-only rollout probe.

## Verification

The executing agent passed targeted migration tests (`53 passed`), then targeted transport tests
(`32 passed`) after review feedback. Its final full gate passed (`135 passed`). The orchestrator
then independently reran the complete gate after the review fix:

```text
$ poetry run ruff check app tests alembic
All checks passed!

$ poetry run ruff format --check app tests alembic
55 files already formatted

$ poetry run mypy app tests
Success: no issues found in 50 source files

$ poetry run pytest
135 passed, 1 warning in 85.31s
```

The warning is a sandbox-only `PytestCacheWarning`: the runner could not write `.pytest_cache`.
It did not affect collection or execution.

## Review Cycle

The first review returned `rework`: raw `httpx` transport/timeouts could escape the typed Notion
error contract. The build retry mapped transport failures to operation-specific sanitized errors
and added parameterized connect/timeout tests before rerunning the full gate.

## Rollout Notes

- Validate a copied Notion database before enabling any production recruiter.
- Share the original database with the integration; do not configure a data-source ID manually.
- Block a recruiter on missing sharing, incompatible schema, or multiple compatible sources.
- Production page updates remain an explicit operational step and were not executed by this build.
