# Build report: calendar-refresh-before-scan

## Status

Complete. No commits, database edits, live scans, or full-suite run.

## Python/FastAPI scope

Changed:

- `app/tools/calendar.py`
- `app/scheduler/cron.py`
- `app/routers/tools.py`
- `openclaw/skills/recording-agent/scripts/recording_agent.py`
- `tests/test_calendar.py`
- `tests/test_scheduler.py`
- `tests/test_tools_router.py`
- `tests/test_recording_agent_skill.py`

Behavior:

- Every recruiter scan refreshes CalDAV discovery once before Disk access.
- Refresh stages and validates a non-empty collection set before atomic persistence.
- Missing selected/default calendars abort the scan without changing the old snapshot or recording
  state.
- Same-recruiter scans are serialized in-process.
- Scan responses expose bounded `aborted`, `errors`, and `pending` fields.
- `found` recordings are pending, not `without_review`.

Verification:

```text
9 new targeted selectors: 9 passed, 1 warning in 0.37s
5 nearby regression selectors: 5 passed, 1 warning in 1.00s
Ruff on all changed Python files: All checks passed!
git diff --check: clean
```

Warnings were limited to the existing Windows `.pytest_cache` permission warning.

## Backend documentation scope

Changed:

- `.memory-bank/architecture.md`
- `docs/api-contracts/yandex-caldav.md`

Documented mandatory refresh-before-scan, staged atomic persistence, selected/default completeness,
bounded fail-closed behavior, and current single-process serialization.

## Cross-layer notes

- No database schema or migration change.
- Full pytest and live external integration scan were intentionally not run.
- Multi-instance distributed scan locking remains out of scope.
