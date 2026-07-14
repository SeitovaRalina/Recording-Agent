# Plan: Phase 2 Scanner   (slug: phase-2-scanner)

## TL;DR

Implement five components that turn the agent from a skeleton into a working scanner:
`DiskScanner` lists `/Записи Телемоста/` per recruiter, skips custom-property-marked files,
marks successful sources with custom properties, and performs gated seven-day cleanup;
`CalDAVClient` queries **Yandex Calendar via CalDAV** ±2h from recording time and parses
VEVENTs — **CalDAV is the source of truth for interview events, not any booking service**;
`InterviewMatcher` scores 6 signals (Telemost URL + time proximity + candidate name primary;
calink/booking URL optional LOW signal only) and returns `best_event + confidence`;
a daily APScheduler cron job wired into existing `AsyncIOScheduler` from Phase 1 `app/main.py`;
and `YandexTokenManager.refresh_token` implements the real Yandex OAuth HTTP refresh,
persisting `access_token + expires_at` in the `yandex_tokens` table (already created in Phase 1).

Output of the phase: recordings advance to `calendar_event_found` or `manual_review_required`.
Notion, Synology, Mattermost, and OpenClaw are Phase 3+.

---

## Acceptance criteria

Observable, checkable "done" conditions — `/review` verifies these:

1. `DiskScanner.list_new(recruiter_email)` returns only files under `disk:/Записи Телемоста/`
   whose `disk_file_id` is absent from `recordings` table (idempotent; all non-terminal
   statuses excluded, not just "processed").
2. `DiskScanner.get_metadata(path, recruiter_email)` returns dict with all `recordings`
   Disk-section fields from `docs/data-model.md`.
3. Disk retention follows closed Memory Bank Q9 exactly:
   - `list_new()` reads candidate metadata after path/media filtering and excludes
     `custom_properties.processed == "true"`. If `processed_at` is missing or invalid, it
     repairs it to current UTC and still excludes the source so it cannot be processed twice.
   - `mark_processed()` PATCHes `processed="true"` and UTC ISO 8601 `processed_at` without
     moving or renaming the source.
   - Scheduled `delete_expired()` selects only marked files at least seven days old and moves
     them to Trash with `DELETE /disk/resources`; if it encounters `processed=true` with
     missing/invalid `processed_at`, it repairs the timestamp and does not delete that resource
     in the current run. Cron has no permanent-delete authority.
   - Separate `purge_expired_from_trash()` enumerates actual Trash resources and deletes their
     `trash:/...` paths only with a fresh per-run `PermanentDeleteApproval` containing a named
     operator, timezone-aware timestamp no more than five minutes old, and non-empty unique nonce.
     Freshness uses a trusted injected aware UTC clock; callers cannot pass `now`. Approval is
     consumed before any request and cannot be reused after success or failure. A failed/partial
     purge is resumable only with a newly issued approval.
4. `CalDAVClient.find_events(recruiter_email, window_start, window_end)` returns
   `list[ParsedVEVENT]` with server out-of-range items filtered client-side in Python. When no
   URL is configured, discovery enumerates `calendar-home-set`, selects an actual calendar
   collection, caches that collection URL, and REPORTs the collection rather than its container.
5. `CalDAVClient` parses SUMMARY, DTSTART (→ UTC), DTEND, DESCRIPTION, ORGANIZER, ATTENDEE,
   UID; handles `TZID=Europe/Moscow` via `icalendar` `.decoded()`; handles Windows-1251
   fallback via `charset-normalizer`.
6. `InterviewMatcher.score(recording, events)` returns `MatchResult(best_event, confidence:
   float 0.0–1.0, signals: list[str], manual_review_required: bool)`.
7. All 6 signals scored with numeric weights per signals table. ATTENDEE signal **stubbed
   as always-absent** in Phase 2 (no Notion access yet) with `# TODO Phase 3` comment.
8. Tie-breaking: equal-scoring events resolved by smallest
   `abs(event.dtstart_utc - recording_time_utc)`.
9. `confidence >= settings.CONFIDENCE_THRESHOLD` (default `0.7`) → status
   `calendar_event_found`; below → `manual_review_required`.
10. APScheduler cron job fires `scan_all_recruiters()` daily at `settings.SCAN_HOUR` UTC;
    wired into **existing** `AsyncIOScheduler` from `app/main.py`; `max_instances=1`,
    `misfire_grace_time=3600`.
11. Recruiter jobs run concurrently via `asyncio.gather(..., return_exceptions=True)`; one
    recruiter failure does not cancel others.
12. `YandexTokenManager.refresh_token(recruiter_email)` POSTs to
    `https://oauth.yandex.ru/token`; acquires `SELECT FOR UPDATE` on `yandex_tokens` row
    before HTTP call; upserts `access_token + expires_at`; returns fresh token.
13. On a Disk API 401, refresh the OAuth token and retry exactly once; propagate a second 401.
    CalDAV uses an app password, so a CalDAV 401 raises `CalDAVAuthError` immediately without
    OAuth refresh or retry.
14. `yandex_tokens` table already exists (Phase 1 migration `20260714_0001`). No new
    migration needed for this table.
15. Unit tests pass for all components (mock httpx via `respx`, mock DB), including Q9
    marking/filtering/repair, exact retention boundary, async deletion and recovery, Trash-path
    enumeration, fresh approval validation, scheduler isolation/no standing purge authority,
    terminal `found` transitions, and exact CalDAV collection discovery.
16. Refresh tokens and CalDAV passwords use `SecretStr` values in settings mappings and are
    unwrapped only at outbound HTTP authentication boundaries; settings repr/dumps do not expose
    credential values.
17. Persisted `found` rows remain resumable after a transient CalDAV/matching failure, or are
    transitioned explicitly after retry exhaustion; scanner idempotency cannot strand them.

---

## Signals table

**Source of truth: Yandex Calendar via CalDAV.**
The matcher must work whether events are created by calink.ru, Calendly, manually, or any
other booking service. calink.ru is an **optional LOW-weight signal** only — never required.

| Signal | Weight | Detection |
|--------|--------|-----------|
| `has_telemost_url` | HIGH = 0.35 | `re.search(r'https://telemost\.360\.yandex\.ru/', description)` — confirms Telemost video call |
| `time_overlap` | HIGH = 0.30 | `recording.disk_created_at` within `[event.dtstart_utc - 15min, event.dtend_utc + 15min]` |
| `name_in_summary` | HIGH = 0.20 | `re.search(r'\(([^)]+)\)$', summary)` — candidate name in parens at end of SUMMARY |
| `interview_keywords` | LOW = 0.05 | `re.search(r'собеседование\|интервью\|interview\|candidate', summary, re.I)` |
| `booking_source_marker` | LOW = 0.05 | Any scheduling-service URL in DESCRIPTION (e.g. calink.ru, calendly.com). Pattern: `re.search(r'https://(?:calink\.ru\|calendly\.com\|cal\.com)/', description)`. Add services as needed — **never block match on absence** |
| `attendee_email_match` | LOW = 0.05 | **STUBBED** — always returns 0 in Phase 2 (Notion not wired); `# TODO Phase 3` |

Sum of weights = 1.00.  Max achievable in Phase 2 (without attendee) = 0.95 → no clamping
needed; still clamp to 1.0 as guard.

> **Design invariant:** If `has_telemost_url`, `time_overlap`, AND `name_in_summary` all fire
> (score = 0.85), the matcher auto-confirms regardless of booking service. calink.ru absence
> never causes manual review.

---

## Plan

### Phase 2 extends Phase 1 — do NOT recreate existing files

Phase 1 (`feature/phase-1-foundation`, merged to `develop`) already created:
`pyproject.toml`, `app/config.py`, `app/db/`, `app/db/session.py`, `app/db/models.py`,
`app/services/__init__.py`, `app/services/yandex_token_manager.py`, `app/tools/__init__.py`,
`app/main.py`, `alembic.ini`, `alembic/env.py`,
`alembic/versions/20260714_0001_*.py` (all tables including `yandex_tokens`),
`tests/conftest.py`.

**Rule for exec agent:** Use `Edit` for existing files. Use `Write` only for genuinely new
files. Running `ast-index rebuild` after checkout gives exact symbol list.

### Affected files

| File | Change |
|------|--------|
| `pyproject.toml` | **Extend** — add `icalendar>=6.0`, `charset-normalizer>=3.0`, `tzdata`, `respx>=0.21` |
| `app/config.py` | **Extend** — add `CALDAV_BASE_URL`, `YANDEX_CALDAV_PASSWORDS`, `SCAN_HOUR`, `SCAN_MINUTE`, `CONFIDENCE_THRESHOLD` fields |
| `app/db/models.py` | **Extend** — add `caldav_calendar_url TEXT` column to `RecruiterConfig` model |
| `alembic/versions/20260714_1000_add_caldav_calendar_url.py` | **New migration** — `ALTER TABLE recruiter_config ADD COLUMN caldav_calendar_url TEXT` |
| `app/services/yandex_token_manager.py` | **Extend** — implement real `refresh_token()` body (was stub); add `get_access_token()` |
| `app/tools/disk.py` | **New** — `DiskScanner`, custom-property marking/filtering, gated retention cleanup |
| `app/tools/calendar.py` | **New** — `CalDAVClient`, `ParsedVEVENT` |
| `app/services/matching.py` | **New** — `InterviewMatcher`, `MatchResult` |
| `app/scheduler/__init__.py` | **New** — empty |
| `app/scheduler/cron.py` | **New** — `scan_all_recruiters()`, retention cleanup, `register_jobs()` |
| `app/main.py` | **Extend** — add scheduler init + `register_jobs()` call to existing lifespan |
| `tests/test_disk_scanner.py` | **New** |
| `tests/test_calendar.py` | **New** |
| `tests/test_matching.py` | **New** |
| `tests/test_token_manager.py` | **New** |

### Implementation steps (ordered)

**Step 1 — `pyproject.toml` (Extend)**

Add to `[tool.poetry.dependencies]`:
```
icalendar = ">=6.0"
charset-normalizer = ">=3.0"
tzdata = "*"           # zoneinfo TZID coverage on Windows/Docker
```

Add to `[tool.poetry.group.dev.dependencies]`:
```
respx = ">=0.21"       # httpx mock for tests
```

Do NOT change existing Poetry sections or deps.

**Step 2 — `app/config.py` (Extend)**

Add fields to existing `Settings` class:
- `CALDAV_BASE_URL: str = "https://caldav.yandex.ru"` — override for tests
- `YANDEX_CALDAV_PASSWORDS: dict[str, SecretStr] = {}` — JSON env var; key = recruiter email
- `SCAN_HOUR: int = 2` — UTC hour for daily cron
- `SCAN_MINUTE: int = 0`
- `CONFIDENCE_THRESHOLD: float = 0.7`

Use `@field_validator(..., mode='before') + json.loads()` for `YANDEX_CALDAV_PASSWORDS`.
`YANDEX_REFRESH_TOKENS` must likewise be `dict[str, SecretStr]`; unwrap values only where the
HTTP client constructs an authentication request.

**Step 3 — `app/db/models.py` + migration (Extend)**

Add `caldav_calendar_url: Mapped[str | None] = mapped_column(Text, nullable=True)` to
`RecruiterConfig` model. Generate and commit Alembic migration:
```
ALTER TABLE recruiter_config ADD COLUMN caldav_calendar_url TEXT;
```

**Step 4 — `app/services/yandex_token_manager.py` (Extend)**

Replace stub body with:
- `get_access_token(email)`: SELECT from `yandex_tokens` where `expires_at > now() + 5min`
  → return cached. Else call `refresh_token(email)`.
- `refresh_token(email)`:
  1. `SELECT ... FOR UPDATE` on `yandex_tokens` row (row-level lock; prevents concurrent
     double-refresh).
  2. Re-check `expires_at` after acquiring lock (another coroutine may have refreshed).
  3. `POST https://oauth.yandex.ru/token` body (URL-encoded form, NOT JSON):
     `grant_type=refresh_token&refresh_token=...&client_id=...&client_secret=...`
  4. Parse `{access_token, expires_in}`; compute `expires_at = utcnow + expires_in seconds`.
  5. `INSERT ... ON CONFLICT (recruiter_email) DO UPDATE` with new values.
  6. Return `access_token`.
- If `yandex_tokens` row absent: seed from `YANDEX_REFRESH_TOKENS` env map on first call.

**Step 5 — `app/tools/disk.py` (New)**

```
class DiskScanner:
    _request(method, url, recruiter_email, **kwargs)
        # get token via token_manager; Authorization: OAuth <token>
        # on 401 → refresh_token() + single retry

    list_new(recruiter_email) → list[dict]
        # paginate GET /disk/resources/files?media_type=video&limit=100&offset=N
        # filter: item.path.startswith("disk:/Записи Телемоста/")
        # fetch GET /disk/resources metadata only for path/media candidates
        # exclude metadata.custom_properties.processed == "true"
        # if processed=true and processed_at is missing/invalid: repair to now UTC, then exclude
        # batch-check disk_file_id NOT IN recordings via SELECT ... WHERE = ANY($1)
        # idempotent: exclude ALL statuses (not just completed)

    get_metadata(path, recruiter_email) → dict
        # GET /disk/resources?path=<path>

    mark_processed(path, recruiter_email) → None
        # PATCH /disk/resources?path=<path>
        # JSON custom_properties: processed="true", processed_at=<UTC ISO 8601>
        # source remains at its original path
        # read existing properties and repair either incomplete half of the marker pair

    delete_expired(recruiter_email) → list[str]
        # inspect processed custom properties and select processed_at age >= 7 days
        # malformed/missing processed_at: repair to now UTC and skip deletion for this run
        # DELETE /disk/resources?path=<path> moves source to Trash
        # soft delete only; safe for daily cron; never accepts permanent-delete authority

    purge_expired_from_trash(recruiter_email, approval: PermanentDeleteApproval) → list[str]
        # validate named operator + aware approved_at <=5 minutes old + non-empty unique nonce
        # use injected/trusted aware UTC clock; caller cannot provide now
        # consume approval before the first HTTP request; reuse fails after success or failure
        # enumerate GET /disk/trash/resources and inspect origin_path/custom properties
        # DELETE /disk/trash/resources?path=<actual trash:/... path>
        # retry/recovery requires a newly issued approval and then re-enumerates Trash
```

`PermanentDeleteApproval` is an immutable per-invocation value object with `approved_by: str`
`approved_at: datetime`, and `nonce: str`. It is not loaded from settings or environment
variables. Nonces are single-use within the purge authority and are consumed before I/O.

**Step 6 — `app/tools/calendar.py` (New)**

```python
@dataclass
class ParsedVEVENT:
    uid: str
    summary: str
    dtstart_utc: datetime
    dtend_utc: datetime
    description: str
    organizer_email: str
    attendees: list[str]
    raw_ics: str
```

`find_events(recruiter_email, window_start, window_end) → list[ParsedVEVENT]`:
1. Get `calendar_url` from `recruiter_config.caldav_calendar_url`; if null, PROPFIND the
   principal for `calendar-home-set`, then PROPFIND that container to enumerate resources,
   select an actual calendar collection, and cache the collection URL (never the home container).
2. `httpx.AsyncClient` with `BasicAuth(email, caldav_password from settings)`.
3. REPORT calendar-query XML time range `[window_start, window_end]` UTC
   (+15min buffer each side to account for Yandex server-side timezone bug).
4. Decode bytes: try UTF-8; on decode error use `charset_normalizer.detect()` fallback.
5. Parse XML → extract `calendar-data` → `icalendar.Calendar.from_ical()` → VEVENT.
6. `component.decoded('DTSTART')` → timezone-aware datetime → `.astimezone(UTC)`.
7. **Client-side filter** (mandatory): `window_start <= dtstart_utc <= window_end`.
8. On 401: raise `CalDAVAuthError` (no retry — CalDAV uses app password, not refresh token).

**RRULE note**: recurring events not expanded in Phase 2.
`# TODO Phase 3: expand RRULE via recurring-ical-events`

**Step 7 — `app/services/matching.py` (New)**

```python
@dataclass
class MatchResult:
    best_event: ParsedVEVENT | None
    confidence: float
    signals: list[str]
    manual_review_required: bool
```

`_score_event(recording, event) → tuple[float, list[str]]`:
- Score each of 6 signals per weights table.
- `booking_source_marker`: match any known booking-service URL pattern; absence scores 0
  but does NOT block match.
- ATTENDEE: always 0.0 with `# TODO Phase 3`.
- Return `(min(raw_score, 1.0), signal_names)`.

`score(recording, events) → MatchResult`:
- Empty events → `MatchResult(None, 0.0, [], manual_review_required=True)`.
- Score each event; pick best.
- Tie-break: smallest `abs(event.dtstart_utc - recording.disk_created_at.astimezone(UTC))`.
- `manual_review_required = best_confidence < settings.CONFIDENCE_THRESHOLD`.

**Step 8 — `app/scheduler/cron.py` (New)**

```python
async def scan_recruiter(recruiter, session_factory, disk, cal, matcher):
    """Per-recruiter job; exceptions caught by gather."""
    ...

async def scan_all_recruiters(session_factory, disk, cal, matcher):
    async with session_factory() as session:
        recruiters = (await session.execute(
            select(RecruiterConfig).where(RecruiterConfig.active == True)
        )).scalars().all()

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
3. `window_start = disk_created_at - 2h`, `window_end = disk_created_at + 2h`.
   **Assumption:** `disk_created_at` ≈ call end time for short/prompt uploads; documented
   gap for long recordings or delayed uploads.
4. `find_events(email, window_start, window_end)`.
5. `matcher.score()` → `UPDATE recordings SET status=..., calendar_event_uid=..., calendar_dtstart=...`.
6. Commit per recording (not per batch) to avoid partial failures.

Persisted `found` rows are resumable: a later scan must load and continue incomplete `found`
rows rather than excluding them forever. If CalDAV or matching fails transiently after insert,
the row remains eligible for retry; permanent/exhausted failures transition explicitly to
`failed` with the error recorded.

The separate daily cleanup job calls only `delete_expired()` after scanning. It has soft-delete
authority only. Permanent purge is invoked separately and is never registered with APScheduler;
every invocation requires a newly constructed `PermanentDeleteApproval` for that run.

**Step 9 — `app/main.py` (Extend)**

Add to existing `lifespan` context manager (do NOT replace — extend):
```python
# Phase 2 additions inside existing lifespan
token_mgr = YandexTokenManager(AsyncSessionLocal)
disk = DiskScanner(token_mgr, AsyncSessionLocal)
cal = CalDAVClient(settings)
matcher = InterviewMatcher(settings)
register_jobs(scheduler, AsyncSessionLocal, disk, cal, matcher)
# scheduler.start() and scheduler.shutdown() already present or add if absent
```

**Step 10 — Tests**

Write `tests/test_disk_scanner.py`, `tests/test_calendar.py`, `tests/test_matching.py`,
`tests/test_token_manager.py`. See tests table below.

---

## Tests

| Test | How |
|------|-----|
| `DiskScanner.list_new` skips existing `disk_file_id` | `respx` mock 2 pages; mock DB returns 1 existing ID; assert only new returned |
| `DiskScanner.list_new` pagination | 2 pages (100 + 30 items); assert 130 total checked |
| `DiskScanner.list_new` filters non-Телемост paths | Include item with `disk:/Photos/...`; assert not returned |
| `DiskScanner.list_new` repairs malformed marked source | `processed="true"` with missing/invalid `processed_at` is repaired to current UTC and excluded before DB insertion |
| `DiskScanner.mark_processed` custom properties | Assert PATCH sets `processed="true"` and UTC `processed_at`; assert no move request |
| `DiskScanner.delete_expired` age boundary | Files younger than 7 days are untouched; exactly 7 days and older are eligible |
| `DiskScanner.delete_expired` marker fallback | Missing/invalid `processed_at` is repaired to current UTC and the source is not deleted in that run |
| `DiskScanner.delete_expired` Trash stage | Assert eligible file receives `DELETE /disk/resources` before any permanent delete |
| `DiskScanner.purge_expired_from_trash` fresh approval | Reject empty operator/nonce, naive/future timestamp, and approval older than 5 minutes using the trusted injected UTC clock |
| `DiskScanner.purge_expired_from_trash` single use | Consume nonce before any request; reject reuse after either successful or failed purge; retry requires a new approval |
| `DiskScanner.purge_expired_from_trash` actual paths | Enumerate Trash; correlate `origin_path`; permanently delete the returned `trash:/...` path, never the original Disk path |
| `DiskScanner.purge_expired_from_trash` recovery | First permanent delete fails; freshly approved rerun re-enumerates Trash and completes |
| Processed-marker repair | Existing `processed` without `processed_at`, or vice versa, is repaired by `mark_processed` |
| Async deletion operations | Poll 202 through success; surface failed operation and timeout |
| `DiskScanner._request` 401 retry | First call → 401; mock `refresh_token`; second → 200; assert refresh called once |
| `CalDAVClient.parse_vevent` full fixture | VEVENT with Telemost URL + SUMMARY `(Иван Иванов)` → all fields populated |
| `CalDAVClient.parse_vevent` TZID→UTC | `DTSTART;TZID=Europe/Moscow:20260714T120000` → `2026-07-14T09:00:00Z` |
| `CalDAVClient.find_events` out-of-range filter | Server returns 3 events (1 in range, 2 outside); assert returns 1 |
| `CalDAVClient` Windows-1251 decode | Bytes in windows-1251 → correct Cyrillic summary |
| `CalDAVClient` collection discovery | PROPFIND calendar-home-set container, enumerate child resources, select/cache actual calendar collection, then REPORT that URL |
| `CalDAVClient` app-password 401 | Assert `CalDAVAuthError` and no OAuth refresh/retry |
| `InterviewMatcher` telemost + time + name → auto-match | Score = 0.85 ≥ 0.7; `manual_review_required=False` |
| `InterviewMatcher` telemost + time only → auto-match | Score = 0.65; with booking_source_marker = 0.70 ≥ 0.7 (optional bonus) |
| `InterviewMatcher` no calink URL → still matches | Fixture with no calink/booking URL; telemost + time + name = 0.85; assert auto-match |
| `InterviewMatcher` 0 signals → 0.0 | Empty event, no URLs, no name; assert 0.0, `manual_review_required=True` |
| `InterviewMatcher` empty events → `None` | `best_event=None`, `confidence=0.0` |
| `InterviewMatcher` tie-break by proximity | Two events equal score; closer dtstart wins |
| `YandexTokenManager.get_access_token` cached | Valid non-expired token in DB → no HTTP call |
| `YandexTokenManager.get_access_token` expired → refresh | Expired row → calls `refresh_token` → returns new token |
| `YandexTokenManager.refresh_token` correct POST body | Assert `grant_type=refresh_token`, `client_id`, `client_secret`, `refresh_token` in form body |
| `YandexTokenManager.refresh_token` DB upsert | Assert `yandex_tokens` row updated with new `access_token` and correct `expires_at` |
| `YandexTokenManager.refresh_token` race condition | Two concurrent calls; `SELECT FOR UPDATE` ensures one HTTP POST; second reads updated row |
| Scheduler registration/concurrency | Assert daily scanner and soft-delete-only cleanup registration, recruiter/cleanup isolation, and no standing permanent-delete authority |
| Persisted `found` retry | Simulate transient CalDAV failure after insert; next scan resumes and matches the existing row |
| Terminal `found` transition | CalDAV auth, missing config, and invalid payload move `found` to `failed` with error diagnostics |

---

## Blockers

**B1 — CalDAV calendar URL discovery** (partially resolved)

Yandex CalDAV requires PROPFIND to discover exact per-user calendar collection URL.
Hardcoding `/calendars/<email>/` may return 404 for some accounts.

**Resolution:** Add `caldav_calendar_url TEXT` to `recruiter_config` (included in affected
files above). Operator fills on onboarding. `CalDAVClient.find_events()` reads from DB;
if null → discover and enumerate `calendar-home-set`, select an actual calendar collection,
then cache that collection URL to DB.
**MVP decision:** operator-provided URL is acceptable for MVP.

---

## Out of scope

- Notion candidate card search, disambiguation, update (Phase 3)
- Synology file transfer and share link (Phase 3)
- Mattermost bot integration and recruiter notifications (Phase 4)
- OpenClaw event push / `openclaw.py` service (Phase 5)
- Audio file handling (only `video` `media_type` scanned)
- Manual review resolution flow
- `/recordings` command handlers
- One-time OAuth setup script
- RRULE / recurring event expansion (documented TODO Phase 3)
- ATTENDEE→Notion signal (stubbed TODO, resolved Phase 3)

---

## Assumptions

- Phase 1 files exist on `feature/phase-2-scanner` branch (merged from `develop`). Exec
  agent must verify with `ast-index rebuild` before implementing.
- `yandex_tokens` table exists from Phase 1 migration `20260714_0001`. No new migration
  for this table.
- `app/main.py` has existing `lifespan` context manager with `AsyncIOScheduler`. Phase 2
  extends it — does not replace.
- `recruiter_config` onboarded with ≥ 2 rows (Anton, Lili) before first cron run; if
  empty, `scan_all_recruiters` logs warning and exits cleanly.
- `YANDEX_REFRESH_TOKENS` env map seeds `yandex_tokens` on first `get_access_token` call.
- `disk_created_at` used as proxy for recording end time (documented gap for long recordings).
- CalDAV login = recruiter corporate email (`@effective.band`); app password in
  `YANDEX_CALDAV_PASSWORDS` config map (JSON, never in code).
- `icalendar>=6.0` handles TZID-aware datetime via `.decoded()`; `tzdata` provides IANA
  timezone database on Windows.
- `apscheduler>=3.10,<4.0` — APScheduler 4.x has incompatible API, not on PyPI.
- `CONFIDENCE_THRESHOLD = 0.7` (configurable via `settings`).
- Poetry is the exclusive dependency and environment manager for this project.
