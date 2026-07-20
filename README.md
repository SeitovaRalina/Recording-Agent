# Recording Agent

Automates interview recording pipeline for recruiting teams.

**Flow:** Recruiter conducts Telemost interview → recording lands on Yandex.Disk → agent detects, matches to calendar event + Notion candidate card, transfers to Synology, updates Notion with link, notifies recruiter via Mattermost. Zero-touch: runs daily or on `/recordings check`.

## Stack

| Layer | Tech |
|-------|------|
| Runtime | Python 3.13, FastAPI 0.136 |
| Scheduler | APScheduler (inside FastAPI process) |
| DB | PostgreSQL + SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic |
| HTTP client | httpx (async) |
| Validation | Pydantic v2 |
| Package mgr | poetry |
| Tests | pytest + anyio |
| Storage (dev) | MinIO (S3-compatible, replaces Synology locally) |
| Agent layer | OpenClaw (reasoning + recruiter dialog) |
| Secrets | Yandex Lockbox (prod) / `.env` (dev) |

## Quickstart (dev)

```bash
# 1. Clone and install
poetry install

# 2. Copy env template
cp .env.example .env
# Fill in: YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET, NOTION_TOKEN,
#          MATTERMOST_BOT_TOKEN, DATABASE_URL, MINIO_* vars

# 3. Start the full local stack
# PostgreSQL, MinIO, automatic migration, and FastAPI app
docker compose up --build -d --wait

# 4. Open API documentation
# Swagger UI: http://localhost:8000/docs
# ReDoc:      http://localhost:8000/redoc
# Health:     http://localhost:8000/health

# 5. Generate a migration after ORM model changes
# The repository is bind-mounted to /app, so the generated file is saved locally
# under alembic/versions/ and can be reviewed and committed.
docker compose run --rm migrate poetry run alembic revision --autogenerate -m "describe change"

# 6. Review the generated migration, then apply it
docker compose run --rm migrate poetry run alembic upgrade head

# 7. Check that ORM metadata and the upgraded database have no schema drift
docker compose run --rm migrate poetry run alembic check

# 8. Inspect current revision or migration history when troubleshooting
docker compose run --rm migrate poetry run alembic current
docker compose run --rm migrate poetry run alembic history

# 9. Authorize Yandex per recruiter (one-time, Phase 2)
poetry run python tools/setup/yandex_oauth.py --recruiter anton@effective.band

# 10. Run tests outside Docker
poetry run pytest
```

## Development pipeline trace

For local end-to-end diagnosis only, enable both settings in `.env` and restart the app:

```env
APP_ENVIRONMENT=development
PIPELINE_TRACE_ENABLED=true
```

The application then writes structured `PIPELINE_TRACE` entries for filename parsing, calendar
event candidates and confidence signals, Notion data-source/page lookup, transfer paths, share-link
creation, and page updates. The trace is disabled in production even if the flag is set. Tokens,
raw ICS, and signed URL query parameters are redacted.

## Migration workflow

The `migrate` Compose service runs `alembic upgrade head` automatically before the application starts. Manual commands use the same image and Docker network, so a host Python process does not need direct access to PostgreSQL.

For every ORM schema change:

1. Start PostgreSQL: `docker compose up -d postgres`.
2. Generate the revision with `docker compose run --rm migrate poetry run alembic revision --autogenerate -m "describe change"`.
3. Review the new local file in `alembic/versions/`. Autogeneration is a draft and may require corrections.
4. Apply it with `docker compose run --rm migrate poetry run alembic upgrade head`.
5. Run `docker compose run --rm migrate poetry run alembic check`. Running `check` before `upgrade` reports `Target database is not up to date` by design.
6. Commit the migration together with the matching ORM change.

Do not delete a revision already recorded in `alembic_version`. For an empty, local-only head revision, first downgrade to its parent, then delete the file, run `upgrade head`, and finish with `check`. Keep applied migrations immutable in shared, staging, and production databases. If a migration file was deleted too early and Alembic cannot locate its revision, restore the exact revision file first; `stamp` cannot traverse a missing revision graph.

## Branch strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready, tagged releases only |
| `develop` | Integration branch — all PRs merge here |
| `feature/phase-{n}-{slug}` | Feature work per phase |
| `fix/{slug}` | Bug fixes |

PRs: `feature/*` → `develop`. Release: `develop` → `main` after full test pass.

## Dev loop

```
/plan "<feature>"  →  /build <slug>  →  /review <slug>  →  /debug "<error>"
```

Test-gate blocks completion until `pytest` runs. See `AGENTS.md` for agent routing.

Use `/commit` at each logical code-change checkpoint. It creates local Conventional Commits only, never pushes, and chooses a short or detailed message from the actual size and risk of the staged diff.

## Key docs

- `.memory-bank/index.md` — start here
- `.memory-bank/architecture.md` — component diagram + data flows
- `.memory-bank/decisions.md` — ADR log
- `.memory-bank/open-questions.md` — blockers to resolve before each phase
- `docs/api-contracts/` — integration API references
- `TOR.md` — original requirements
