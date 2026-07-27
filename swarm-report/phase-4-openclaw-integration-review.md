# Review: Phase 4 - Mila-first OpenClaw integration

## Verdict

`rework`

## Findings

- `app/scheduler/cron.py:94` — **CRITICAL:** Intermediate transfer states are never resumed after
  restart. Add stage-aware recovery.
- `app/services/storage.py:74` — **CRITICAL:** MinIO blindly overwrites existing keys. Implement
  ownership/content checks and same-recording reuse.
- `app/services/reviews.py:157` — **HIGH:** Replay bypasses token/thread/version/payload validation.
  Validate a persisted request fingerprint.
- `app/routers/tools.py:123` — **HIGH:** Manual scans omit review/completion/error notifications;
  scan idempotency persists after side effects.
- `app/routers/tools.py:277` — **HIGH:** Resolve/status paths do not enforce all test recruiter and
  Notion resource guards.
- `app/scheduler/cron.py:267` — **HIGH:** A boolean config unlocks Notion writes without persisted
  runtime schema and synthetic-row preflight.
- `tools/setup/configure_recruiter.py:36` — **MEDIUM:** Bootstrap probes twice and displays a
  placeholder database title.
- `tests/conftest.py:20` — **HIGH:** Required PostgreSQL+MinIO, restart, concurrency, collision,
  replay-binding, and manual-notification tests are absent.

## Acceptance criteria not met

- 2: incomplete canary resource enforcement.
- 6: replay binding incomplete.
- 7: durable exactly-once behavior incomplete.
- 9: collision/reuse policy incomplete.
- 10: Notion preflight does not gate writes.
- 12: production-resource guards incomplete.
- 13: required integration tests absent.
- 15: manual notification flow incomplete.

## Verification

Reviewer confirmed Ruff and formatting checks, strict mypy, `149 passed` in full pytest, and valid
Compose configuration. Remote Mila/canary execution remained outside the approval boundary.
