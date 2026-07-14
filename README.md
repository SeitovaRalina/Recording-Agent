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

# 5. Check migration drift (runs through the app image)
docker compose run --rm migrate poetry run alembic check

# 6. Generate a migration after ORM model changes
docker compose run --rm migrate poetry run alembic revision --autogenerate -m "describe change"

# 7. Apply migration explicitly when needed
docker compose run --rm migrate poetry run alembic upgrade head

# 8. Authorize Yandex per recruiter (one-time, Phase 2)
poetry run python tools/setup/yandex_oauth.py --recruiter anton@effective.band

# 9. Run tests outside Docker
poetry run pytest
```

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

## Key docs

- `.memory-bank/index.md` — start here
- `.memory-bank/architecture.md` — component diagram + data flows
- `.memory-bank/decisions.md` — ADR log
- `.memory-bank/open-questions.md` — blockers to resolve before each phase
- `docs/api-contracts/` — integration API references
- `TOR.md` — original requirements
