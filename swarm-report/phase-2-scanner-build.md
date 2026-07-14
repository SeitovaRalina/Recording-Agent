# Build Report: Phase 2 Scanner

## Status

`complete`

## Scope: python-fastapi

Implemented the Phase 2 scanner end to end:

- Yandex OAuth access-token caching, refresh, atomic first-use seeding, row locking, and one-retry Disk authentication.
- Yandex Disk video discovery, database idempotency, metadata mapping, and synchronous/asynchronous move to `processed/`.
- CalDAV calendar discovery, REPORT queries, safe XML parsing, charset fallback, VEVENT parsing, UTC normalization, and client-side time filtering.
- Six-signal interview matching with the Phase 2 attendee stub, confidence threshold, and proximity tie-breaking.
- Concurrent per-recruiter daily scanning registered in the existing FastAPI lifespan scheduler.
- Recruiter CalDAV URL schema field and reversible Alembic migration.
- Focused unit coverage for Disk, CalDAV, matching, configuration, and token refresh concurrency.

## Changed files

- `pyproject.toml`
- `poetry.lock`
- `app/config.py`
- `app/db/models/recruiter_config.py`
- `alembic/versions/20260714_1000_add_caldav_calendar_url.py`
- `app/services/yandex_token_manager.py`
- `app/tools/__init__.py`
- `app/tools/disk.py`
- `app/tools/calendar.py`
- `app/services/matching.py`
- `app/scheduler/__init__.py`
- `app/scheduler/cron.py`
- `app/main.py`
- `tests/test_config.py`
- `tests/test_disk_scanner.py`
- `tests/test_calendar.py`
- `tests/test_matching.py`
- `tests/test_token_manager.py`

The plan named `app/db/models.py`, but the repository uses model modules; the actual owner is `app/db/models/recruiter_config.py`. `poetry.lock` was updated because the approved dependency changes made the previous lock stale.

## Verification

Commands:

```text
poetry run ruff check app tests alembic
poetry run ruff format --check app tests alembic
poetry run mypy app tests
poetry run pytest
```

Results:

```text
All checks passed!
35 files already formatted
Success: no issues found in 32 source files
32 passed, 1 warning in 11.20s
```

The warning is a non-fatal `PytestCacheWarning`: Windows denied creation of `.pytest_cache`; all tests executed and passed.

## Cross-layer and plan notes

- No HTTP API contract changed.
- The approved plan's `mark_processed()` behavior moves files to `/processed/`. This conflicts with the later Memory Bank Q9 custom-properties and seven-day retention design; this build follows the approved plan and leaves reconciliation to review/planning.
- CalDAV uses an app password. A 401 raises `CalDAVAuthError` per the plan's detailed CalDAV step; OAuth refresh-and-retry applies to Yandex Disk.
- No production credentials or recruiter-specific identifiers were added.
