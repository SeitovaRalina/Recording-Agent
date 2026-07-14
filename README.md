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
| Package mgr | uv |
| Tests | pytest + anyio |
| Storage (dev) | MinIO (S3-compatible, replaces Synology locally) |
| Agent layer | OpenClaw (reasoning + recruiter dialog) |
| Secrets | Yandex Lockbox (prod) / `.env` (dev) |

## Quickstart (dev)

```bash
# 1. Clone and install
uv sync

# 2. Copy env template
cp .env.example .env
# Fill in: YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET, NOTION_TOKEN,
#          MATTERMOST_BOT_TOKEN, DATABASE_URL, MINIO_* vars

# 3. Start local services
docker compose up -d   # PostgreSQL + MinIO

# 4. Run migrations
alembic upgrade head

# 5. Authorize Yandex per recruiter (one-time)
python tools/setup/yandex_oauth.py --recruiter anton@effective.band

# 6. Start backend
uvicorn app.main:app --reload

# 7. Run tests
pytest
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
