# Debug: Phase 4 - Mila-first OpenClaw integration

## Fixed findings

- Added restart recovery for every committed transfer checkpoint and serialized recovery with a
  PostgreSQL row lock.
- Added MinIO object ownership/content metadata, same-recording reuse, conditional no-overwrite,
  and manual review for conflicting owners.
- Bound review replay to an exact hashed request and rechecked replay after row-lock contention.
- Added leased scan-intent claims before side effects with atomic ownership-checked completion.
- Wired manual scans to review and terminal DM notifications.
- Enforced authoritative recruiter, Notion database, Mattermost user, and test storage-prefix scope
  for every intent, including replay paths.
- Added persisted Backend-token/schema/synthetic-row Notion preflight evidence and gated both
  normal and restart Notion mutations on it.
- Reused one read-only Notion inspection in recruiter bootstrap and displayed the real database
  title/schema.
- Added focused restart, collision, replay, lease, prefix, preflight, bootstrap, and notification
  regression tests.

## Verification

```text
poetry run ruff check app tools tests alembic
All checks passed!

poetry run ruff format --check app tools tests alembic
77 files already formatted

poetry run mypy app tools tests
Success: no issues found in 70 source files

poetry run pytest -q
164 passed, 1 warning in 52.17s

docker compose --env-file .env.example config --quiet
exit 0

quick_validate.py openclaw/skills/recording-agent
Skill is valid!

poetry run alembic heads
20260721_1300 (head)
```

The pytest warning is limited to denied cache-directory creation and does not affect tests.

## Deferred by user

Real PostgreSQL + MinIO integration execution is postponed. The local Docker engine and service
credentials are unavailable. Warn the user and obtain confirmation before starting that test
stack. Do not claim the integration canary passed until it runs.
