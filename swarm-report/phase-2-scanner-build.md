# Build Report: Phase 2 Scanner

## Status

`complete`

## Scope: python-fastapi

Implemented the Phase 2 scanner end to end:

- Yandex OAuth access-token caching, refresh, atomic first-use seeding, row locking, and one-retry Disk authentication.
- Yandex Disk video discovery, database idempotency, metadata mapping, Q9 custom-property
  filtering/marking, seven-day soft deletion, and separately approved permanent Trash purge.
- CalDAV principal/home discovery, exact calendar-collection enumeration and caching, REPORT
  queries, safe XML parsing, charset fallback, VEVENT parsing, UTC normalization, and
  client-side time filtering.
- Six-signal interview matching with the Phase 2 attendee stub, confidence threshold, and proximity tie-breaking.
- Concurrent per-recruiter daily scanning with resumable `found` rows, terminal failure
  transitions, and isolated recruiter failures.
- Transient Disk/CalDAV failures leave `found` rows eligible for a later scan; known permanent
  CalDAV authentication, missing configuration, and invalid payload failures transition to
  `failed` with `error_step`, `error_message`, and `last_attempted_at`.
- Soft-delete-only cleanup cron. Permanent deletion is a separate invocation requiring a fresh
  per-run `PermanentDeleteApproval`; it enumerates and deletes actual `trash:/...` paths and can
  resume safely after partial failure.
- `SecretStr` mappings for refresh tokens and CalDAV passwords, unwrapped only at HTTP auth
  boundaries.
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
- `tests/test_scheduler.py`
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
36 files already formatted
Success: no issues found in 33 source files
53 passed, 1 warning
```

The warning is a non-fatal `PytestCacheWarning`: Windows denied creation of `.pytest_cache`; all tests executed and passed.

## Cross-layer and plan notes

- No HTTP API contract changed.
- Memory Bank Q9 is authoritative: `mark_processed()` PATCHes `processed=true` and
  `processed_at`; scanner discovery repairs `processed=true` with missing/invalid `processed_at`
  to current UTC and excludes the source, preventing duplicate processing. Cleanup applies the
  same repair fallback but does not delete that resource during the repair run. Daily cleanup
  only moves validly marked sources aged at least seven days to Trash.
- Permanent purge is never scheduled and has no standing configuration authority. Each run
  requires `PermanentDeleteApproval(approved_by, approved_at, nonce)` with a non-empty operator,
  timezone-aware timestamp no more than five minutes old, and non-empty unique nonce. Validation
  uses an injected/trusted aware UTC clock; callers cannot supply `now`. Approval is consumed
  before any Disk request and cannot be reused after success or failure. Every retry needs a
  newly issued approval before enumerating real Trash paths.
- CalDAV uses an app password. A 401 raises `CalDAVAuthError` per the plan's detailed CalDAV step; OAuth refresh-and-retry applies to Yandex Disk.
- No production credentials or recruiter-specific identifiers were added.

## Historical review context

The initial July 14 review and Re-review 1 both returned `rework`. Their findings and the
subsequent implementation resolutions are preserved in
`swarm-report/phase-2-scanner-review.md`. This build report records completed implementation;
it does not replace the required final independent review verdict.
