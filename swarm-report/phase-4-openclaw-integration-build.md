# Build: Phase 4 - Mila-first OpenClaw integration

## Status

Local implementation complete. Remote Mila deployment, OpenClaw invocation, Mattermost messages,
and Notion mutations were not performed because they require separate approval.

## Python/FastAPI scope

- Added fail-closed Mila canary settings and resource allowlists.
- Added deterministic filename/key generation, persisted storage identity, and collision review.
- Added durable manual-review token, recruiter/thread/version/TTL binding and intent replay state.
- Added authenticated scan, bounded status, review context, resolve, and ignore intents.
- Added DM-only Mattermost review and terminal notifications.
- Added restart-resumable scheduler/pipeline integration and operator-only recruiter bootstrap.
- Added Alembic migration `20260721_1200_add_phase4_intents`.

Verification:

```text
poetry run ruff check app tools tests alembic
All checks passed!

poetry run ruff format --check app tools tests alembic
72 files already formatted

poetry run mypy app tools tests
Success: no issues found in 66 source files

poetry run pytest -q
149 passed, 1 warning in 52.36s
```

The warning was limited to pytest cache-directory access.

## OpenClaw skill scope

- Added the repository source-of-truth package at `openclaw/skills/recording-agent/`.
- Kept deterministic HTTP behavior in the bundled CLI and detailed schema in one reference file.
- Enforced loopback-only Backend access and excluded all raw integration/destructive primitives.

Verification:

```text
quick_validate.py: Skill is valid!
ruff check: All checks passed!
ruff format --check: 1 file already formatted
offline CLI contract: 7 passed
CLI help: passed
```

Remote forward-testing was deferred to the approval-gated Mila turn.

## DevOps scope

- Added isolated `recording-agent-test` Compose topology with loopback-only ports.
- Added persistent PostgreSQL and MinIO named volumes and test-bucket initialization.
- Removed source and `.env` mounts from runtime/migration containers.
- Injected Phase 4 settings with scheduler and Yandex source mutation disabled initially.

Verification:

```text
docker compose --env-file .env.example config --quiet
exit 0

docker compose --env-file .env.example build --print
exit 0
```

An actual image build was unavailable because the local Docker Desktop engine pipe was absent.

## Cross-scope notes

- Skill and Backend use bearer authentication from `RECORDING_AGENT_BACKEND_SECRET` /
  `OPENCLAW_SECRET`; the review token is sent in `X-Review-Token`, never in a URL.
- The obsolete untracked `swarm-report/mila-openclaw-integration-plan.md` was not staged or
  committed.
- Known review input: recruiter bootstrap currently performs a duplicate Notion inspection and
  displays a placeholder database title instead of the discovered title.
