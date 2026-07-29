# Plan: Phase 1 Foundation   (slug: phase-1-foundation)

## TL;DR

Bootstrap project skeleton: pyproject.toml + poetry.lock, docker-compose (PostgreSQL + MinIO),
.env.example, pydantic-settings Config, all 5 ORM models with full columns per data-model.md,
Alembic async baseline migration, YandexTokenManager CRUD, OpenClaw event-receiver endpoint
with shared-secret auth, FastAPI entrypoint with APScheduler 3.x AsyncIOScheduler lifespan, and baseline tests.

---

## Acceptance criteria

1. `poetry install` completes without error; `poetry.lock` committed.
2. `docker compose up -d` starts postgres:16-alpine and minio healthy (healthchecks pass).
3. `alembic upgrade head` creates exactly 5 tables: `recordings`, `processing_attempts`,
   `recruiter_config`, `manual_reviews`, `yandex_tokens`.
4. `recordings.status` CHECK constraint contains all 13 values (verified in migration).
5. `from app.config import get_settings` succeeds; `notion_token`, `yandex_client_secret`,
   `database_url` are `SecretStr` instances.
6. `uvicorn app.main:app` starts without error; `GET /health` returns `{"status":"ok"}` 200.
7. `POST /events` with valid `X-OpenClaw-Secret` header + JSON body → 202 Accepted.
8. `POST /events` without or with wrong header → 401 Unauthorized.
9. `Recording.transition_to("invalid_target")` raises `ValueError`.
10. `pytest -v` — all baseline tests pass with anyio asyncio backend.

---

## Plan

### Files to create

| File | Change |
|------|--------|
| `pyproject.toml` | New. See spec below. |
| `docker-compose.yml` | New. PostgreSQL 16 + MinIO with healthchecks. |
| `.env.example` | New. All required env vars, no real values. |
| `.gitignore` | New. `.env`, `__pycache__`, `.venv`, `poetry.lock` not ignored. |
| `app/__init__.py` | New. Empty. |
| `app/config.py` | New. BaseSettings with all SecretStr fields + `@lru_cache get_settings()`. |
| `app/db/__init__.py` | New. Empty. |
| `app/db/base.py` | New. `class Base(DeclarativeBase): pass` |
| `app/db/engine.py` | New. Async engine + `async_sessionmaker` + `get_session` FastAPI dep. |
| `app/db/models/__init__.py` | New. Imports all 5 models so Alembic metadata scan picks them up. |
| `app/db/models/recording.py` | New. `RecordingStatus` enum (13 values) + `Recording` ORM (all columns from data-model.md) + `transition_to()` guard. |
| `app/db/models/processing_attempt.py` | New. `ProcessingAttempt` ORM per data-model.md. |
| `app/db/models/recruiter_config.py` | New. `RecruiterConfig` ORM per data-model.md. |
| `app/db/models/manual_review.py` | New. `ManualReviewStatus` enum + `ManualReview` ORM per data-model.md. |
| `app/db/models/yandex_token.py` | New. `YandexToken` ORM — see schema below. |
| `app/services/__init__.py` | New. Empty. |
| `app/services/yandex_token_manager.py` | New. CRUD skeleton + `refresh_token` stub. |
| `app/routers/__init__.py` | New. Empty. |
| `app/routers/events.py` | New. `POST /events` with `X-OpenClaw-Secret` auth. |
| `app/routers/health.py` | New. `GET /health`. |
| `app/main.py` | New. FastAPI + APScheduler 3.x `AsyncIOScheduler` lifespan (asyncio event loop). |
| `alembic.ini` | New. Standard alembic.ini; `sqlalchemy.url` empty (overridden in env.py). |
| `alembic/env.py` | New. **Async** env.py with `run_sync` pattern required by asyncpg. |
| `alembic/versions/20260714_0001_baseline.py` | New. Creates all 5 tables + all indexes from data-model.md. |
| `tests/__init__.py` | New. Empty. |
| `tests/conftest.py` | New. anyio fixture, async engine, session fixture, async_client, `get_settings.cache_clear()` teardown. |
| `tests/test_config.py` | New. Monkeypatch env vars; assert SecretStr; assert defaults. |
| `tests/test_models.py` | New. Round-trip Recording insert/query; duplicate disk_file_id → IntegrityError; 13 status values; transition_to guard; YandexToken upsert. |
| `tests/test_events_router.py` | New. POST /events with valid secret → 202; wrong secret → 401; missing type → 422. |

---

### pyproject.toml spec

```toml
[tool.poetry]
name = "recording-agent"
version = "0.1.0"
description = "Automates interview recording pipeline"
authors = []
readme = "README.md"

[tool.poetry.dependencies]
python = "^3.13"
fastapi = "0.136.*"             # 0.136.x confirmed on PyPI
uvicorn = {extras = ["standard"], version = ">=0.30"}
sqlalchemy = {extras = ["asyncio"], version = ">=2.0"}
asyncpg = ">=0.30.0"            # 0.30.0 = first release with Python 3.13 support
alembic = ">=1.13"
httpx = ">=0.27"
pydantic = ">=2.0"
pydantic-settings = ">=2.0"
apscheduler = ">=3.10"          # 3.x only on PyPI; use AsyncIOScheduler
aiobotocore = ">=2.13"          # async S3 client for MinIO (dev) + future S3 backends

[tool.poetry.group.dev.dependencies]
pytest = ">=8.0"
anyio = {extras = ["asyncio"], version = ">=4.0"}   # ships pytest plugin; no pytest-anyio needed
httpx = ">=0.27"
aiosqlite = "*"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.pytest.ini_options]
asyncio_mode = "auto"           # anyio pytest plugin: all async tests run without explicit mark
anyio_backend = "asyncio"
testpaths = ["tests"]
```

---

### docker-compose.yml spec

Services:
- **postgres**: `postgres:16-alpine` — env: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD — port 5432 — healthcheck: `pg_isready -U ${POSTGRES_USER}` — named volume `pgdata`.
- **minio**: `minio/minio:latest` — env: MINIO_ROOT_USER, MINIO_ROOT_PASSWORD — ports 9000/9001 — command: `server /data --console-address :9001` — healthcheck: `curl -f http://localhost:9000/minio/health/live` — named volume `miniodata`.
- Both services on shared bridge network `recording-net`.

---

### .env.example vars

```
# Database
DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/recording_agent

# Yandex OAuth (per-recruiter tokens seeded via tools/setup/yandex_oauth.py — Phase 2)
YANDEX_CLIENT_ID=
YANDEX_CLIENT_SECRET=

# Notion
NOTION_TOKEN=

# Synology (prod)
SYNOLOGY_BASE_URL=
SYNOLOGY_API_KEY=
SYNOLOGY_USER=
SYNOLOGY_PASS=

# Mattermost
MATTERMOST_URL=
MATTERMOST_BOT_TOKEN=
MATTERMOST_CHANNEL_ID=

# MinIO (dev only — replaces Synology)
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=recordings
STORAGE_PROVIDER=minio      # minio | synology

# OpenClaw
OPENCLAW_EVENTS_URL=http://localhost:8001/events
OPENCLAW_SECRET=            # local shared test value for X-OpenClaw-Secret

# Pipeline
CONFIDENCE_THRESHOLD=0.7
```

---

### yandex_tokens table schema

Not in data-model.md — designed here:

```sql
CREATE TABLE yandex_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recruiter_email TEXT NOT NULL UNIQUE,
    access_token    TEXT,               -- nullable: absent until first code exchange
    refresh_token   TEXT NOT NULL,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`YandexTokenManager` methods (Phase 1 — all pure DB, no HTTP):
- `async get_token(recruiter_email) -> YandexToken`  — raises `KeyError` if absent
- `async upsert_token(recruiter_email, access_token, refresh_token, expires_at) -> YandexToken`
- `async is_expired(recruiter_email) -> bool`
- `async refresh_token(recruiter_email) -> str`  — **raises `NotImplementedError`** (Phase 2 wires Yandex OAuth refresh)

---

### RecordingStatus transition table

`Recording.transition_to(new_status)` enforces this map:

```python
TRANSITIONS: dict[RecordingStatus, set[RecordingStatus]] = {
    found:                    {calendar_event_found, manual_review_required, ignored, failed},
    calendar_event_found:     {candidate_matched, manual_review_required, failed},
    candidate_matched:        {transfer_started, failed},
    manual_review_required:   {candidate_matched, ignored, failed},
    transfer_started:         {uploaded_to_synology, failed},
    uploaded_to_synology:     {synology_link_created, failed},
    synology_link_created:    {notion_updated, failed},
    notion_updated:           {source_marked_processed, failed},
    source_marked_processed:  {source_deleted, completed},
    source_deleted:           {completed},
    completed:                set(),   # terminal
    ignored:                  set(),   # terminal
    failed:                   set(),   # terminal — retry via /recordings retry <id> resets to found
}
```

Raises `ValueError(f"Invalid transition {current} → {new_status}")` on invalid move.

---

### POST /events auth

`app/routers/events.py`:
```python
OPENCLAW_SECRET_HEADER = "X-OpenClaw-Secret"  # pragma: allowlist secret

async def verify_openclaw_secret(
    x_openclaw_secret: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.openclaw_secret.get_secret_value()  # pragma: allowlist secret
    if not expected or x_openclaw_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid OpenClaw secret")
```

Applied as `Depends(verify_openclaw_secret)` on the POST route.

---

### Async Alembic env.py pattern

```python
from sqlalchemy.ext.asyncio import create_async_engine
import asyncio

def run_async_migrations():
    engine = create_async_engine(get_settings().database_url.get_secret_value())
    async def _run():
        async with engine.connect() as conn:
            await conn.run_sync(do_run_migrations)
    asyncio.run(_run())
```

---

### Implementation steps (ordered)

1. Create `pyproject.toml`; run `poetry install`; commit `poetry.lock`.
2. Create `docker-compose.yml`; verify `docker compose up -d` shows both services healthy.
3. Create `.env.example`; create `.env` from it locally (fill DATABASE_URL + OPENCLAW_SECRET at minimum).
4. Create `.gitignore`.
5. Create `app/config.py` with all fields.
6. Create `app/db/base.py` and `app/db/engine.py`.
7. Create all 5 ORM model files; create `app/db/models/__init__.py`.
8. Create `app/services/yandex_token_manager.py`.
9. Create `app/routers/events.py` (with auth) and `app/routers/health.py`.
10. Create `app/main.py` (AsyncIOScheduler lifespan + router registration).
11. Run `alembic init alembic`; replace `alembic/env.py` with async version.
12. Write `alembic/versions/20260714_0001_baseline.py` — all 5 tables + indexes.
13. Run `alembic upgrade head`; verify all tables created.
14. Create `tests/conftest.py`, `tests/test_config.py`, `tests/test_models.py`, `tests/test_events_router.py`.
15. Run `pytest -v` — all pass.

---

## Blockers

> Resolve before `/build` starts if possible; none are hard-blockers for scaffolding.

| # | Issue | Impact | Action |
|---|-------|--------|--------|
| ~~B1~~ | ~~FastAPI 0.136 on PyPI~~ | **RESOLVED** — 0.136.0–0.136.3 confirmed on PyPI (latest stable 0.139.0). Keeping `fastapi==0.136.*` per README. | — |
| B2 | **yandex_tokens schema not in data-model.md** | Schema is designed here — needs review. | Confirm schema is correct before writing migration; update data-model.md after. |
| B3 | **OPENCLAW_SECRET value** — must be set in `.env` for tests to pass POST /events auth. | Test `test_events_router.py` fails if env var empty. | Set any non-empty value in local `.env`. |

---

## Out of scope

- APScheduler job definitions (disk scan, reminder cron) — Phase 2
- Outbound push from Backend → OpenClaw (`services/openclaw.py`) — Phase 2
- Yandex OAuth code-exchange script (`tools/setup/yandex_oauth.py`) — Phase 2
- All 10 OpenClaw tools — Phase 2
- Mattermost bot — Phase 4
- `STORAGE_PROVIDER` toggle implementation — config var only, Phase 3
- Yandex Lockbox integration — dev uses `.env`; Lockbox wiring Phase 7
- Encryption of tokens at rest in `yandex_tokens`
- Confidence scoring engine
- Retry/backoff logic
- Streaming transfer
- MinIO bucket creation bootstrap script

---

## Assumptions

- No existing Python code in repo — confirmed by `git status` (single init commit).
- `yandex_tokens` table schema is new (not in `data-model.md`) — designed here; needs sign-off.
- `YANDEX_REFRESH_TOKENS` from env used in Phase 2 to seed `yandex_tokens` table; not needed in Phase 1.
- Test suite uses `TEST_DATABASE_URL` or real Postgres from docker-compose — aiosqlite fallback acceptable for ORM tests only, Alembic migration tests require real Postgres.
- APScheduler 4.x does NOT exist on PyPI (latest is 3.11.3). Using `AsyncIOScheduler` from `apscheduler.schedulers.asyncio` — runs jobs inside the asyncio event loop. `AsyncScheduler` API from unreleased 4.x is not available.
- `aiobotocore` covers MinIO S3 access in Phase 3; dep added now to avoid config churn later.
