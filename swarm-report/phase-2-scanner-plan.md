# Plan: Phase 2 — Scanner, CalDAV, Matching   (slug: phase-2-scanner)

## TL;DR

Implement DiskScanner, YandexTokenManager.refresh_token (with race-condition guard),
CalDAVClient (PROPFIND discovery + REPORT + client-side filter), InterviewMatcher
(7-signal scoring), APScheduler daily cron with per-recruiter isolation, and a
7-day retention cleanup job. Add `icalendar` dependency. Alembic migration for
`yandex_tokens` if not already created in Phase 1.

## Acceptance criteria

1. `DiskScanner.list(recruiter)` returns only unprocessed video files from
   `/Записи Телемоста/` (skips `custom_properties.processed == "true"`;
   filters `mime_type` to `video/*` only).
2. `DiskScanner.mark_processed(path)` sets `custom_properties.processed=true`
   and `custom_properties.processed_at=<ISO8601>` via `PATCH /disk/resources`.
3. `DiskScanner.delete_expired()` deletes files where `processed=true`
   AND `processed_at` age ≥ `RECORDING_RETENTION_DAYS` (default 7).
   Moves to Trash first (`DELETE /disk/resources`), then permanent delete
   (`DELETE /disk/trash/resources`). Both steps logged.
4. `YandexTokenManager.refresh_token(recruiter_id)` uses `SELECT FOR UPDATE`
   on `yandex_tokens` row; re-reads token after lock — skips HTTP call if
   already valid (another process refreshed first). Catches HTTP 400
   `invalid_token` → sets recruiter status to `token_expired`, logs + notifies
   (placeholder Mattermost call), does NOT raise to caller.
5. `CalDAVClient.discover(recruiter)` calls `PROPFIND /calendars/{login}/`
   and returns primary calendar href. Caches per recruiter in DB or config.
6. `CalDAVClient.search(href, recording_dt)` issues REPORT calendar-query
   for window `[recording_dt - 2h, recording_dt + 2h]`. Parses VEVENT using
   `icalendar` library (handles TZID). Client-side re-filter to window
   (Yandex server-side filter is buggy). Returns `list[CalEvent]`.
7. `InterviewMatcher.match(recording, events)` scores 7 signals, returns
   `tuple[Optional[CalEvent], float]`. If `best_event is None` or
   `confidence < INTERVIEW_CONFIDENCE_THRESHOLD`, returns `(None, score)`.
   CalDAV app password authenticated separately from OAuth tokens.
8. Daily cron job iterates recruiters; per-recruiter scan wrapped in
   `try/except` — one recruiter failure does not stop others. Cleanup job
   runs after scan.
9. `pytest` passes: ≥ 1 test per component; token refresh race tested with
   two concurrent coroutines.

## Plan

### Step 0 — Alembic migration (prerequisite)

Check if `yandex_tokens` table exists in current migration history.
If not: `/migrate generate "create yandex_tokens"` and run `alembic upgrade head`.

Columns: `id UUID PK`, `recruiter_id UUID FK→recruiters.id`, `access_token TEXT`,
`refresh_token TEXT`, `expires_at TIMESTAMPTZ`, `token_status VARCHAR(32)` (default
`active`; values: `active`, `token_expired`), `created_at TIMESTAMPTZ`,
`updated_at TIMESTAMPTZ`.

> Security note: access_token and refresh_token stored plaintext in MVP.
> ADR entry: accept risk for now; encrypt with Fernet in post-MVP hardening.

### Step 1 — Config additions

File: `app/config.py`

Add:
- `INTERVIEW_CONFIDENCE_THRESHOLD: float = 0.6`
- `RECORDING_RETENTION_DAYS: int = 7`
- `CALDAV_BASE_URL: str` (e.g. `https://caldav.yandex.ru`)
- `CALDAV_APP_PASSWORD_{RECRUITER}: SecretStr` — one per recruiter
  (stored in env/Lockbox; NOT in yandex_tokens table)

### Step 2 — DiskScanner

File: `app/tools/disk.py`

```
class DiskScanner:
    async def list(recruiter: Recruiter) -> list[DiskFile]
        # GET /disk/resources?path=disk:/Записи%20Телемоста/&limit=100&offset=0
        # Paginate via _embedded.items + total
        # Filter: mime_type.startswith("video/")
        # Filter: custom_properties.get("processed") != "true"

    async def mark_processed(path: str) -> None
        # PATCH /disk/resources?path=<path>
        # Body: {"custom_properties": {"processed": "true",
        #        "processed_at": datetime.now(UTC).isoformat()}}

    async def delete_expired() -> int
        # GET /disk/resources?path=disk:/Записи%20Телемоста/... — list processed
        # For each: if processed_at age >= RECORDING_RETENTION_DAYS:
        #   DELETE /disk/resources?path=<path>  (→ Trash)
        #   DELETE /disk/trash/resources?path=<path>  (permanent)
        # Return count deleted
        # IMPORTANT: log each deletion (path, recruiter, processed_at)
        # Per AGENTS.md: destructive op — log at WARNING level
```

Auth: Bearer `access_token` from YandexTokenManager.

### Step 3 — YandexTokenManager.refresh_token

File: `app/services/yandex_token_manager.py`

Replace stub with:
```python
async def refresh_token(recruiter_id: UUID) -> str:
    async with db_session() as session:
        # SELECT FOR UPDATE — prevents race
        row = await session.execute(
            select(YandexToken)
            .where(YandexToken.recruiter_id == recruiter_id)
            .with_for_update()
        )
        token = row.scalar_one()
        # Re-check after lock acquired
        if token.expires_at > utcnow() + timedelta(minutes=5):
            return token.access_token  # another process refreshed
        try:
            resp = await httpx_client.post(
                "https://oauth.yandex.ru/token",
                data={"grant_type": "refresh_token",
                      "refresh_token": token.refresh_token,
                      "client_id": settings.YANDEX_CLIENT_ID,
                      "client_secret": settings.YANDEX_CLIENT_SECRET},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                body = e.response.json()
                if body.get("error") == "invalid_token":
                    token.token_status = "token_expired"
                    await session.commit()
                    logger.warning("refresh_token expired for recruiter %s", recruiter_id)
                    # TODO Phase 4: notify Mattermost
                    return ""  # caller checks empty string → skip scan
            raise
        data = resp.json()
        token.access_token = data["access_token"]
        token.refresh_token = data.get("refresh_token", token.refresh_token)
        token.expires_at = utcnow() + timedelta(seconds=data["expires_in"])
        token.token_status = "active"
        await session.commit()
        return token.access_token
```

### Step 4 — CalDAVClient

File: `app/tools/calendar.py`

```
class CalDAVClient:
    async def discover(recruiter: Recruiter) -> str
        # PROPFIND /calendars/{recruiter.yandex_login}/
        # Depth: 1, find: calendar-home-set or cal:calendar
        # Return href of primary calendar (heuristic: DISPLAYNAME == "Яндекс.Календарь"
        # or first calendar found)
        # Auth: Basic(recruiter.yandex_login, CALDAV_APP_PASSWORD_{recruiter.slug})

    async def search(href: str, recruiter: Recruiter, recording_dt: datetime) -> list[CalEvent]
        # REPORT {href} calendar-query
        # time-range: start=recording_dt-2h, end=recording_dt+2h
        # Parse response XML → extract VEVENT bodies
        # Parse each VEVENT with icalendar.Calendar.from_ical()
        # Client-side filter: event.dtstart in [recording_dt-2h, recording_dt+2h]
        # Return list[CalEvent(summary, description, dtstart, dtend, attendees)]
```

### Step 5 — InterviewMatcher (7-signal scoring)

File: `app/services/matching.py`

Signals and weights:

| Signal | Weight | Source |
|--------|--------|--------|
| `has_calink_url(description)` | 0.30 | `re.search(r'https://calink\.ru/', description)` |
| `has_telemost_url(description)` | 0.25 | `re.search(r'https://telemost\.360\.yandex\.ru/', description)` |
| `name_in_summary(recording_filename, summary)` | 0.20 | extract name from `(...)` at end of SUMMARY |
| `time_overlap(recording_dt, event)` | 0.15 | recording_dt within [dtstart-15min, dtend+15min] |
| `folder_path_match` | 0.05 | recording from `/Записи Телемоста/` (always true in scanner) |
| `attendee_email_match` | 0.03 | LOW — email may differ |
| `duration_plausible` | 0.02 | event duration 20–120 min (typical interview) |

Return: `tuple[Optional[CalEvent], float]`
- Pick event with highest score
- If score < `INTERVIEW_CONFIDENCE_THRESHOLD` → return `(None, score)`
- If `events` is empty → return `(None, 0.0)`

```python
@dataclass
class MatchResult:
    event: Optional[CalEvent]
    confidence: float
    routed_to: Literal["auto", "manual_review_required"]
```

### Step 6 — APScheduler wiring

File: `app/scheduler/cron.py`

```python
async def daily_scan_job():
    recruiters = await get_all_recruiters()
    for recruiter in recruiters:
        try:
            await run_scan_for_recruiter(recruiter)
        except Exception:
            logger.exception("Scan failed for recruiter %s", recruiter.id)
            # continue to next recruiter

async def cleanup_job():
    scanner = DiskScanner(...)
    deleted = await scanner.delete_expired()
    logger.info("Cleanup: deleted %d expired recordings", deleted)
```

Register both in FastAPI lifespan:
```python
scheduler.add_job(daily_scan_job, "cron", hour=2, minute=0)
scheduler.add_job(cleanup_job, "cron", hour=3, minute=0)
```

### Step 7 — pyproject.toml

Add to dependencies: `icalendar>=6.0`

### Step 8 — Tests

| File | Tests |
|------|-------|
| `tests/test_disk_scanner.py` | list() filters video+unprocessed; mark_processed sets properties; delete_expired counts |
| `tests/test_calendar.py` | discover() parses PROPFIND XML; search() client-side filters out-of-range events; DTSTART;TZID=Europe/Moscow parsed correctly |
| `tests/test_matching.py` | full score=1.0 case; no events → (None, 0.0); below threshold → manual_review_required |
| `tests/test_token_manager.py` | race condition: two coroutines, first refreshes, second skips HTTP; 400 invalid_token → token_expired status |

All tests use httpx `MockTransport` / `respx` — no real Yandex API calls.

## Affected files

```
app/config.py
app/tools/disk.py                  (new)
app/tools/calendar.py              (new)
app/services/matching.py           (new)
app/services/yandex_token_manager.py
app/scheduler/cron.py              (new)
pyproject.toml
alembic/versions/XXXX_yandex_tokens.py   (if not exists)
tests/test_disk_scanner.py         (new)
tests/test_calendar.py             (new)
tests/test_matching.py             (new)
tests/test_token_manager.py        (new)
```

## Blockers

None. All blockers resolved:
- Q6 (calink markers) ✅ closed
- Q9 (retention policy) ✅ closed 2026-07-14 — custom_properties + 7-day delete
- B1 (CalDAV URL) ✅ resolved — operator-provided `recruiter_config.caldav_calendar_url`
  in DB/env; PROPFIND auto-discovery runs as fallback when field is NULL.

## Out of scope

- Mattermost notification on token_expired (placeholder only; full impl in Phase 4)
- Synology upload (Phase 3)
- Notion update (Phase 4)
- OpenClaw tool registration (Phase 5)

## Assumptions

- `yandex_tokens` table exists (Phase 1 scope); if not, `/migrate` runs as Step 0
- CalDAV app password is a separate credential from OAuth tokens (Yandex 360 org setting)
- Yandex CalDAV REPORT time-range filter is unreliable — client-side filter is canonical
- `icalendar>=6.0` API: `Calendar.from_ical(raw).walk("VEVENT")` returns components with `.get("DTSTART").dt` as timezone-aware datetime
- APScheduler 3.x (`AsyncIOScheduler`) — 4.x not released on PyPI
- `respx` available as dev dep for mocking httpx
