# Plan: Phase 2 Scanner   (slug: phase2-scanner)

## TL;DR

Implement five components that turn the agent from a skeleton into a working scanner:
`DiskScanner` lists `/Записи Телемоста/` per recruiter and marks files processed;
`CalDAVClient` queries Yandex CalDAV ±2h from recording time and parses VEVENTs;
`InterviewMatcher` scores 6 signals (from architecture.md Q6) and returns `best_event + confidence`;
a daily APScheduler cron job wired into the existing `AsyncIOScheduler` in `app/main.py`;
and `YandexTokenManager.refresh_token` does a real Yandex OAuth HTTP refresh via httpx,
persisting `access_token + expires_at` in a new `yandex_tokens` DB table.

Output of the phase: recordings advance to `calendar_event_found` or `manual_review_required`.
Notion, Synology, Mattermost, and OpenClaw are Phase 3+.

---

## Acceptance criteria

Observable, checkable "done" conditions — `/review` verifies these:

1. `DiskScanner.list_new(recruiter_email)` returns only files under `disk:/Записи Телемоста/` whose `disk_file_id` is absent from `recordings` table (idempotent across cron cycles; all non-terminal statuses excluded, not just "processed").
2. `DiskScanner.get_metadata(path, recruiter_email)` returns dict with all `recordings` Disk-section fields from `docs/data-model.md`.
3. `DiskScanner.mark_processed(path, filename, recruiter_email)` moves file to `disk:/Записи Телемоста/processed/<filename>`; handles 201 sync and 202 async (polls `/disk/operations/{id}` with hard cap 60 × 2s = 120s; raises on timeout/failure).
4. `CalDAVClient.find_events(recruiter_email, window_start, window_end)` returns `list[ParsedVEVENT]` with server out-of-range items filtered in Python.
5. `CalDAVClient` parses SUMMARY, DTSTART (→ UTC), DTEND, DESCRIPTION, ORGANIZER, ATTENDEE, UID; handles `TZID=Europe/Moscow` via `icalendar` `.decoded()`; handles Windows-1251 fallback via `charset-normalizer`.
6. `InterviewMatcher.score(recording, events, recruiter_emails)` returns `MatchResult(best_event, confidence: float 0.0–1.0, signals: list[str], manual_review_required: bool)`.
7. All 6 signals scored with numeric weights (see signals table below). ATTENDEE signal is **stubbed as always-absent** in Phase 2 (no Notion access yet) with a `TODO` comment.
8. Tie-breaking: equal-scoring events resolved by smallest `abs(event.dtstart_utc - recording_time_utc)`.
9. `confidence >= settings.CONFIDENCE_THRESHOLD` (default `0.7`) → status `calendar_event_found`; below → `manual_review_required`.
10. APScheduler cron job fires `scan_all_recruiters()` daily at `settings.SCAN_HOUR` UTC; uses existing `AsyncIOScheduler` from `app/main.py`; `max_instances=1`, `misfire_grace_time=3600`.
11. Recruiter jobs run concurrently via `asyncio.gather(..., return_exceptions=True)`; one recruiter failure does not cancel others.
12. `YandexTokenManager.refresh_token(recruiter_email)` POSTs to `https://oauth.yandex.ru/token` with `grant_type=refresh_token`; acquires `SELECT FOR UPDATE` on `yandex_tokens` row before HTTP call; upserts `access_token + expires_at`; returns fresh token.
13. On 401 from Disk or CalDAV API: refresh token → retry exactly once → propagate error if second attempt also fails.
14. `yandex_tokens` table exists (Alembic migration).
15. Unit tests pass for all components (mock httpx, mock DB).

---

## Signals table (numeric weights, Phase 2)

| Signal | Weight | Detection |
|--------|--------|-----------|
| Recording owner is a known recruiter | HIGH = 0.35 | `disk_owner_email` in active `recruiter_config` rows |
| DESCRIPTION contains `calink.ru` URL | HIGH = 0.35 | `re.search(r'https://calink\.ru/', description)` |
| DESCRIPTION contains Telemost URL | HIGH = 0.35 | `re.search(r'https://telemost\.360\.yandex\.ru/', description)` |
| Candidate name extracted from SUMMARY `(...)` | MEDIUM = 0.15 | `re.search(r'\(([^)]+)\)$', summary)` |
| SUMMARY contains interview keywords | MEDIUM = 0.15 | `re.search(r'собеседование\|интервью\|interview\|candidate', summary, re.I)` |
| File path starts with `/Записи Телемоста/` | MEDIUM = 0.15 | always true for Phase 2 files — but included for completeness |
| ATTENDEE email matches Notion card email | LOW = 0.05 | **STUBBED** — always returns 0 in Phase 2 (Notion not wired); `# TODO Phase 3` |

Raw sum capped at 1.0. Max achievable in Phase 2 (without ATTENDEE) = 1.10 → clamp to 1.0.

---

## Plan

### Affected files

| File | Change |
|------|--------|
| `pyproject.toml` | Create — uv project; deps listed below |
| `app/config.py` | Create — `pydantic-settings` `BaseSettings`; Yandex + CalDAV + scheduler settings |
| `app/db/__init__.py` | Create — empty |
| `app/db/session.py` | Create — async engine, `AsyncSessionLocal`, `get_session()` |
| `app/db/models.py` | Create — `Recording`, `RecruiterConfig`, `YandexToken` mapped models |
| `alembic.ini` | Create — standard ini, no hardcoded URL |
| `alembic/env.py` | Create — async-compatible, imports `Base` from models |
| `alembic/versions/20260714_1000_create_core_tables.py` | Create — all tables from `docs/data-model.md` |
| `alembic/versions/20260714_1100_create_yandex_tokens.py` | Create — `yandex_tokens` table |
| `app/services/__init__.py` | Create — empty |
| `app/services/yandex_token_manager.py` | Create — `YandexTokenManager` with `get_access_token` + `refresh_token` |
| `app/tools/__init__.py` | Create — empty |
| `app/tools/disk.py` | Create — `DiskScanner` |
| `app/tools/calendar.py` | Create — `CalDAVClient`, `ParsedVEVENT` |
| `app/services/matching.py` | Create — `InterviewMatcher`, `MatchResult` |
| `app/scheduler/__init__.py` | Create — empty |
| `app/scheduler/cron.py` | Create — `scan_all_recruiters()`, `register_jobs()` |
| `app/main.py` | Create — FastAPI app + lifespan wiring |
| `tests/test_disk_scanner.py` | Create |
| `tests/test_calendar.py` | Create |
| `tests/test_matching.py` | Create |
| `tests/test_token_manager.py` | Create |

### Implementation steps (ordered)

**Step 1 — `pyproject.toml`**
```
fastapi>=0.115
uvicorn[standard]>=0.30
httpx>=0.27
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
alembic>=1.13
pydantic-settings>=2.3
apscheduler>=3.10,<4.0
icalendar>=6.0
python-dateutil>=2.9
charset-normalizer>=3.0
tzdata                    # zoneinfo TZID coverage on Windows/Docker
pytest>=8
pytest-asyncio>=0.23
respx>=0.21               # httpx mock
```

**Step 2 — `app/config.py`**
Fields: `DATABASE_URL`, `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET (SecretStr)`,
`YANDEX_REFRESH_TOKENS (JSON → dict[str,str])`, `YANDEX_CALDAV_PASSWORDS (JSON → dict[str,str])`,
`SCAN_HOUR (int, default 2)`, `SCAN_MINUTE (int, default 0)`,
`CONFIDENCE_THRESHOLD (float, default 0.7)`.
Use `@field_validator(..., mode='before')` + `json.loads()` for JSON map fields.

**Step 3 — DB layer** (`app/db/session.py`, `app/db/models.py`)
- `YandexToken` model: `id UUID PK`, `recruiter_email TEXT UNIQUE NOT NULL`, `access_token TEXT NOT NULL`, `refresh_token TEXT NOT NULL`, `expires_at TIMESTAMPTZ NOT NULL`, `updated_at TIMESTAMPTZ DEFAULT now()`.
- `RecruiterConfig` model: must include `caldav_calendar_url TEXT` column (override for CalDAV discovery; see Blocker B1).

**Step 4 — Alembic**
- `alembic.ini` + async `alembic/env.py`.
- Migration `20260714_1000`: `recordings`, `processing_attempts`, `recruiter_config`, `manual_reviews` + all indexes from `docs/data-model.md`. Add `caldav_calendar_url TEXT` column to `recruiter_config`.
- Migration `20260714_1100`: `yandex_tokens` table + unique index on `recruiter_email`.

**Step 5 — `app/services/yandex_token_manager.py`**
- `get_access_token(email)`: SELECT from `yandex_tokens` where `expires_at > now() + 5min` → return cached. Else call `refresh_token()`.
- `refresh_token(email)`:
  1. `SELECT ... FOR UPDATE` on `yandex_tokens` row (row-level lock; prevents concurrent double-refresh).
  2. Re-check `expires_at` after acquiring lock (another coroutine may have already refreshed).
  3. `POST https://oauth.yandex.ru/token` body: `grant_type=refresh_token&refresh_token=...&client_id=...&client_secret=...` (URL-encoded form, NOT JSON).
  4. Parse `{access_token, expires_in}`; compute `expires_at = utcnow + expires_in seconds`.
  5. `INSERT ... ON CONFLICT (recruiter_email) DO UPDATE` with new values.
  6. Return `access_token`.
- If `yandex_tokens` row absent for email: seed from `YANDEX_REFRESH_TOKENS` env map on first call, then proceed with refresh.

**Step 6 — `app/tools/disk.py`**
- `_request(method, url, recruiter_email, **kwargs)`: gets token via `token_manager`; `Authorization: OAuth <token>`; on 401 → `refresh_token()` + single retry.
- `list_new(recruiter_email)`: paginate `GET /disk/resources/files?media_type=video&limit=100&offset=N`; filter `item.path.startswith("disk:/Записи Телемоста/")` and NOT already under `/processed/`; batch-check `disk_file_id NOT IN recordings` via `SELECT ... WHERE disk_file_id = ANY($1)`. Excludes **all** statuses (not just completed) → idempotency.
- `get_metadata(path, recruiter_email)`: `GET /disk/resources?path=<path>`.
- `mark_processed(path, filename, recruiter_email)`: `POST /disk/resources/move?from=<path>&path=disk:/Записи Телемоста/processed/<filename>`. 201 → done. 202 → poll `GET /disk/operations/{id}` with cap `60 × asyncio.sleep(2)`; raise `TimeoutError` at cap.

**Step 7 — `app/tools/calendar.py`**
- `ParsedVEVENT` dataclass: `uid`, `summary`, `dtstart_utc: datetime`, `dtend_utc: datetime`, `description`, `organizer_email`, `attendees: list[str]`, `raw_ics`.
- `find_events(recruiter_email, window_start, window_end)`:
  1. Get `calendar_url` from `recruiter_config.caldav_calendar_url`; if null → PROPFIND principal discovery fallback (see Blocker B1).
  2. `httpx.AsyncClient` with `BasicAuth(email, caldav_password from config)`.
  3. `REPORT` calendar-query XML (from `docs/api-contracts/yandex-caldav.md`) time range `[window_start - buffer, window_end + buffer]` UTC (add 15min buffer to account for Yandex timezone bug).
  4. Decode response bytes: try UTF-8; on decode error use `charset_normalizer.detect()` fallback.
  5. Parse XML → extract `calendar-data` blocks → `icalendar.Calendar.from_ical()` → get VEVENT component.
  6. `component.decoded('DTSTART')` → timezone-aware datetime → `.astimezone(UTC)`.
  7. Filter: `window_start <= dtstart_utc <= window_end`.
  8. On 401: raise `CalDAVAuthError` (no retry — CalDAV uses app password, not refresh token).
- **RRULE note**: recurring events not expanded in Phase 2. Add `# TODO: expand RRULE via recurring-ical-events in Phase 3`.

**Step 8 — `app/services/matching.py`**
- `MatchResult` dataclass: `best_event: ParsedVEVENT | None`, `confidence: float`, `signals: list[str]`, `manual_review_required: bool`.
- `_score_event(recording, event, recruiter_emails) → tuple[float, list[str]]`:
  - Check each of 6 signals; accumulate score; collect signal name strings.
  - ATTENDEE signal: always returns 0.0 with `# TODO Phase 3`.
  - Raw sum may exceed 1.0; clamp: `min(raw_score, 1.0)`.
- `score(recording, events, recruiter_emails) → MatchResult`:
  - Empty events → `MatchResult(None, 0.0, [], manual_review_required=True)`.
  - Score each event; pick best.
  - Tie-break: smallest `abs(event.dtstart_utc - recording.disk_created_at.astimezone(UTC))`.
  - `manual_review_required = best_confidence < settings.CONFIDENCE_THRESHOLD`.

**Step 9 — `app/scheduler/cron.py`**
```python
async def scan_recruiter(recruiter, session_factory, disk, cal, matcher):
    """Per-recruiter job; exceptions are caught by gather."""
    ...

async def scan_all_recruiters(session_factory, disk, cal, matcher):
    async with session_factory() as session:
        recruiters = (await session.execute(
            select(RecruiterConfig).where(RecruiterConfig.active == True)
        )).scalars().all()
    
    # Concurrent per recruiter, failures isolated
    await asyncio.gather(
        *(scan_recruiter(r, session_factory, disk, cal, matcher) for r in recruiters),
        return_exceptions=True,
    )

def register_jobs(scheduler, session_factory, disk, cal, matcher):
    scheduler.add_job(
        scan_all_recruiters,
        CronTrigger(hour=settings.SCAN_HOUR, minute=settings.SCAN_MINUTE),
        args=[session_factory, disk, cal, matcher],
        max_instances=1,
        misfire_grace_time=3600,
        id="scan_all_recruiters",
        replace_existing=True,
    )
```

Per-recruiter flow inside `scan_recruiter`:
1. `list_new(email)` → new file dicts.
2. For each file: `get_metadata()` → `INSERT INTO recordings (status='found') ON CONFLICT DO NOTHING`.
3. `window_start = disk_created_at - 2h`, `window_end = disk_created_at + 2h`. **Document assumption:** `disk_created_at` is upload time, not recording start; for short/prompt uploads this is accurate; long recordings or delayed uploads may shift the window.
4. `find_events(email, window_start, window_end)`.
5. `matcher.score()` → `UPDATE recordings SET status=..., calendar_event_uid=..., calendar_dtstart=..., ...`.
6. Commit per recording (not per batch) to avoid partial failures.

**Step 10 — `app/main.py`**
```python
@asynccontextmanager
async def lifespan(app):
    # Init DB
    token_mgr = YandexTokenManager(AsyncSessionLocal)
    disk = DiskScanner(token_mgr, AsyncSessionLocal)
    cal = CalDAVClient(settings)
    matcher = InterviewMatcher(settings)
    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, AsyncSessionLocal, disk, cal, matcher)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 11 — Tests**
Write `tests/test_disk_scanner.py`, `tests/test_calendar.py`, `tests/test_matching.py`, `tests/test_token_manager.py`.

---

## Tests

| Test | How |
|------|-----|
| `DiskScanner.list_new` skips existing `disk_file_id` | `respx` mock 2 pages; mock DB returns 1 existing ID; assert only new returned |
| `DiskScanner.list_new` pagination | 2 pages (100 + 30 items); assert 130 total checked |
| `DiskScanner.list_new` filters non-Телемост paths | Include item with `disk:/Photos/...`; assert not returned |
| `DiskScanner.mark_processed` sync 201 | Mock POST → 201; assert no polling |
| `DiskScanner.mark_processed` async 202 + poll | Mock POST → 202; mock operations → pending→pending→success; assert completes |
| `DiskScanner.mark_processed` poll timeout | Mock operations always returns `in-progress`; assert `TimeoutError` at cap |
| `DiskScanner._request` 401 retry | First call → 401; mock `refresh_token`; second → 200; assert refresh called once |
| `CalDAVClient.parse_vevent` full Q6 fixture | VEVENT with calink URL + Telemost URL + SUMMARY with `(Иван Иванов)` → all fields populated |
| `CalDAVClient.parse_vevent` TZID→UTC | `DTSTART;TZID=Europe/Moscow:20260714T120000` → `2026-07-14T09:00:00Z` |
| `CalDAVClient.find_events` out-of-range filter | Server returns 3 events (1 in range, 2 outside); assert returns 1 |
| `CalDAVClient` Windows-1251 decode | Bytes in windows-1251 encoding → correct Cyrillic summary |
| `InterviewMatcher` all signals → ~1.0 | Fixture with recruiter match + calink + telemost + name + keywords + folder; assert confidence ≥ 0.9 |
| `InterviewMatcher` 0 signals → 0.0 | Empty event, non-recruiter owner, no URLs; assert 0.0, `manual_review_required=True` |
| `InterviewMatcher` calink + telemost only → auto-match | Sum = 0.70 ≥ 0.7 threshold; `manual_review_required=False` |
| `InterviewMatcher` empty events → `None` | `best_event=None`, `confidence=0.0` |
| `InterviewMatcher` tie-break by proximity | Two events equal score; closer dtstart wins |
| `YandexTokenManager.get_access_token` cached | Valid non-expired token in DB → no HTTP call |
| `YandexTokenManager.get_access_token` expired → refresh | Expired row → calls `refresh_token` → returns new token |
| `YandexTokenManager.refresh_token` correct POST body | Assert `grant_type=refresh_token`, `client_id`, `client_secret`, `refresh_token` in form body |
| `YandexTokenManager.refresh_token` DB upsert | Assert `yandex_tokens` row updated with new `access_token` and correct `expires_at` |
| `YandexTokenManager.refresh_token` race condition | Two concurrent calls; `SELECT FOR UPDATE` ensures only one HTTP POST; second reads updated row |

---

## Blockers

**B1 — CalDAV calendar URL discovery** (skeptic HIGH, partially resolved)

Yandex CalDAV requires PROPFIND to discover the exact per-user calendar collection URL.
Hardcoding `/calendars/<email>/` may return 404 for some accounts.

**Resolution path:** Add `caldav_calendar_url TEXT` column to `recruiter_config`.
Operator fills it on recruiter onboarding (one-time PROPFIND, copy URL to config).
`CalDAVClient.find_events()` reads from DB; if null → attempts PROPFIND discovery and caches result.
**Decision needed before `/build`:** Is operator-provided URL acceptable for MVP, or must auto-discovery be mandatory?

---

## Out of scope

- Notion candidate card search, disambiguation, update (Phase 3)
- Synology file transfer and share link (Phase 3)
- Mattermost bot integration and recruiter notifications (Phase 4)
- OpenClaw event push / `openclaw.py` service (Phase 5)
- Audio file handling (only `video` `media_type` scanned)
- Disk file download or streaming transfer
- Manual review resolution flow
- `/recordings` command handlers
- One-time OAuth setup script (`tools/setup/yandex_oauth.py`)
- Temp file TTL cleanup
- RRULE / recurring event expansion (documented as known gap with TODO)
- Disk file deletion (retention policy Q9 open)
- ATTENDEE→Notion signal (stubbed TODO, resolved in Phase 3)

---

## Assumptions

- `app/main.py` is greenfield (confirmed — no existing files); `AsyncIOScheduler` created fresh.
- `recruiter_config` table onboarded with at least 2 rows (Anton, Lili) before first cron run; if empty, `scan_all_recruiters` logs warning and exits cleanly.
- `YANDEX_REFRESH_TOKENS` env map used to seed `yandex_tokens` on first `get_access_token` call per recruiter.
- `disk_created_at` used as proxy for recording time (upload time ≈ call end time for short recordings; documented gap for long recordings).
- CalDAV login = recruiter corporate email (`@effective.band`); app password in `YANDEX_CALDAV_PASSWORDS` config map.
- Alembic not yet initialized in repo (no `alembic/` dir in file listing) — steps include full Alembic bootstrap.
- `icalendar` (PyPI) handles TZID-aware datetime via `.decoded()`; `tzdata` package provides IANA timezone database on Windows.
- `apscheduler>=3.10,<4.0` pinned — APScheduler 4.x has incompatible `AsyncIOScheduler` API.
- `CONFIDENCE_THRESHOLD = 0.7` (configurable via `settings`).
