---
name: seed
description: Populate the local/test database with fixture data for development. Actions: run (all fixtures), clean (truncate seed tables), status (list seeded rows). Never runs against production DATABASE_URL.
---

# Skill: /seed

ORCHESTRATOR. Loads fixture data into local dev/test DB. Safe to re-run — idempotent by design.

## Invocation
```
/seed run            # load all fixture data (recruiters, recordings, Notion IDs)
/seed clean          # truncate all seed-managed tables (keeps schema)
/seed status         # count rows per seeded table
```

## Fixture data scope

| Table / config | Fixture content |
|----------------|-----------------|
| `recruiters` (config) | Anton `anton@effective.band`, Lili `lili@effective.band` with placeholder Notion DB IDs |
| `recordings` | 5 mock recordings: 2 high-confidence, 1 ambiguous, 1 no-calendar-match, 1 already-processed |
| `recording_statuses` | State history matching the 13-status machine (populated per recording above) |
| MinIO buckets | `recordings-dev` bucket created if absent |
| `.env.test` check | Verifies `DATABASE_URL` points to dev/test, not production |

## Steps

### run
1. **Safety check:** read `DATABASE_URL` from env. If it contains `prod`, `production`, or the literal production host → ABORT. Print: "Refusing to seed: DATABASE_URL looks like production. Set DATABASE_URL to dev/test DB."
2. Verify DB is migrated: run `uv run alembic check`. Pending migrations → abort: "Run `/migrate upgrade` first."
3. Run fixture loader: `uv run python tools/seed/main.py`
   - If `tools/seed/main.py` does not exist → spawn python-fastapi agent to create it from `tools/seed/fixtures/` definitions (see below).
4. Quote output row counts per table.

### clean
1. Confirm: "This truncates all seeded tables. Local dev data will be lost. Proceed?"
2. Run: `uv run python tools/seed/main.py --clean`
3. Quote output.

### status
Run: `uv run python tools/seed/main.py --status`

## Fixture file layout (created by python-fastapi agent on first /seed run)

```
tools/seed/
  main.py               # entry point: --clean, --status, default=run
  fixtures/
    recruiters.py       # RECRUITER_FIXTURES list[dict]
    recordings.py       # RECORDING_FIXTURES list[dict] (5 mock recordings)
    statuses.py         # STATUS_HISTORY_FIXTURES list[dict]
  minio_setup.py        # create dev bucket if absent (boto3/aiobotocore)
```

## Rules
- Idempotent: `INSERT ... ON CONFLICT DO NOTHING` or equivalent. Safe to re-run.
- No real Yandex Disk URLs, no real Notion IDs — use placeholder strings (`PLACEHOLDER_NOTION_ID_ANTON`).
- MinIO fixture uses local `MINIO_*` env vars only.
- Never commit fixture data with real credentials or real file paths.

## Return
```yaml
status: complete | blocked
action: <run|clean|status>
rows_inserted: {table: count, ...}
minio_buckets: [<name>, ...]
warnings: <any skipped fixtures>
blocked_reason: <only if blocked>
```
