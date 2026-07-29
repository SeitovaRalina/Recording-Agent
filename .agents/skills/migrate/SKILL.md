---
name: migrate
description: Generate or run Alembic migrations. Actions: generate "<message>", upgrade, downgrade, history, check. Delegates to python-fastapi agent for complex schema changes; runs Alembic CLI for routine ops.
---

# Skill: /migrate

ORCHESTRATOR. Manages Alembic migrations for the PostgreSQL schema.

## Invocation
```
/migrate generate "<message>"   # autogenerate new migration from model diff
/migrate upgrade                # apply all pending migrations (head)
/migrate downgrade              # roll back one revision
/migrate history                # list applied revisions
/migrate check                  # verify DB is up-to-date (no pending migrations)
```

## Steps

### generate "<message>"
1. Verify `alembic.ini` and `alembic/env.py` exist. Missing → abort: "Run `/plan \"Alembic baseline\"`."
2. Confirm all ORM models imported in `alembic/env.py` `target_metadata`. If new model added in this phase and not yet imported → warn and ask.
3. Run: `docker compose run --rm migrate poetry run alembic revision --autogenerate -m "<message>"`
4. Read generated file (`alembic/versions/<hash>_<message>.py`). Check:
   - `upgrade()` and `downgrade()` both present and non-empty.
   - No `drop_table` or `drop_column` on tables that look production-critical without explicit user confirmation.
   - No data migrations mixed with schema migrations (split if needed).
5. Report: path to file + diff summary. Offer to spawn python-fastapi agent if complex transforms needed.

### upgrade
1. Run: `docker compose run --rm migrate poetry run alembic upgrade head`
2. Quote output. Any `ERROR` → stop, quote verbatim, do not retry.

### downgrade
1. Confirm with user: "This rolls back one revision. Irreversible if data was written. Proceed?"
2. Run: `docker compose run --rm migrate poetry run alembic downgrade -1`
3. Quote output.

### history
Run: `docker compose run --rm migrate poetry run alembic history --verbose`

### check
Run: `docker compose run --rm migrate poetry run alembic check`
Exit 0 = clean. Non-zero → list pending revisions.

## Rules
- Never run `alembic upgrade` on production DB without explicit user confirmation.
- Never edit generated migration files without noting the change in the report.
- Always quote real CLI output — no "migration applied successfully" without proof.
- Destructive ops (`drop_table`, `drop_column`) → require explicit user sign-off.

## Return
```yaml
status: complete | blocked
action: <generate|upgrade|downgrade|history|check>
migration_file: <path or null>
output: <real CLI output>
warnings: <any destructive ops flagged>
blocked_reason: <only if blocked>
```
