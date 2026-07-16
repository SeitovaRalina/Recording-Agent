# Plan: Phase 3 — Candidate Matching + Transfer Pipeline   (slug: phase-3-transfer)

## TL;DR

Phase 2 leaves recordings at `calendar_event_found`. Phase 3 advances them through the full
transfer pipeline: Notion candidate search → streaming Disk→Synology/MinIO → Notion recording
field update → `source_marked_processed`. Every status transition is atomic; partial failure
lands in `failed` with `error_step`. MinIO is the dev/test substitute (ADR-012);
`STORAGE_PROVIDER=synology` activates real Synology FileStation.

**Source of truth for blockers:**
- Q1 (Synology folder): resolved — `recruiter_config.synology_base_folder` exists; subdirectory
  template `{base_folder}/{YYYY-MM-DD}/{candidate_name}/` coded as configurable default.
- Q5 (Notion DB IDs): resolved — `recruiter_config.notion_database_id` exists; property names
  are global configurable settings with known defaults from Q5 (`General Interview Date`,
  `General Interview recording`, `Name`).
- No new Alembic migration needed — `recordings` table already has all transfer fields from
  Phase 1 baseline.

## Acceptance criteria

1. `NotionClient.search_pages(database_id, candidate_name, date)` calls
   `POST /v1/databases/{id}/query` with a filter on the configured name property (contains, case-
   insensitive) AND the configured date property (equals local date). Returns typed page list.
   `database_id` **must be the original database ID** (UUID format from Notion URL or API), not
   a linked-database view page ID. The Notion Integration must be shared directly with the
   original database — sharing only with a page that embeds a linked view is insufficient and
   returns 404 or 0 results. Chosen endpoint: **database query** (`/v1/databases/{id}/query`);
   Notion has no separate "data source" query endpoint.
2. `NotionClient.update_recording_url(page_id, url, prop_name)` patches the Notion page with
   `PATCH /v1/pages/{page_id}`; the field is a URL property.
3. Zero matching Notion pages → recording transitions to `manual_review_required` with
   `manual_review_reason = "no_candidate_found"` and bounded candidate list `[]`.
4. Exactly one matching page → `candidate_matched`; `candidate_name`, `candidate_email` (if
   present in page), `notion_database_id`, `notion_page_id`, `notion_page_url` persisted.
5. More than one matching page → `manual_review_required` with
   `manual_review_reason = "multiple_candidates"` and bounded candidate summaries (name + URL
   only; no raw Notion data, no credentials).
6. `StorageBackend` is a `typing.Protocol`: `upload(folder, filename, stream, size)`,
   `create_share_link(path)`, `ensure_folder(path)`. Two implementations:
   `SynologyBackend` (real API) and `MinIOBackend` (S3/pre-signed URL). Toggle via
   `STORAGE_PROVIDER`.
7. `SynologyBackend` uses DSM 7.0 API Key header (`X-SYNO-Token` / `Authorization: Bearer`).
   Authenticates with `synology_api_key`. Never uses session SID (Q2 closed: DSM 7.0+).
   `ensure_folder` creates intermediate directories. `create_share_link` returns a permanent share
   link URL.
8. `MinIOBackend` uploads to `minio_bucket`; `create_share_link` returns a pre-signed GET URL
   with long expiry for dev use. Path mirrors `SynologyBackend` path so test assertions are
   portable.
9. Transfer is streaming by default: `httpx.AsyncClient` streams Disk download chunk-by-chunk
   into the storage upload. Temp file fallback (ADR-004): if storage backend signals chunked
   upload is unsupported, write to `/tmp/recording-agent/{uuid}/{filename}`, upload from file,
   delete immediately after backend confirms. A background TTL guard deletes any
   `/tmp/recording-agent/*` older than 4 hours.
10. Destination folder: `{synology_base_folder}/{YYYY-MM-DD}/{candidate_name}/`.
    `synology_base_folder` comes from `recruiter_config` row, never from config literals.
    `candidate_name` is the name extracted from the calendar event summary (Phase 2 match result);
    path components are sanitized (replace `/\:*?"<>|` with `_`).
11. On successful storage upload: `uploaded_to_synology`, `synology_folder_path`,
    `synology_file_path` persisted. On share link creation: `synology_link_created`,
    `synology_share_url` persisted.
12. Notion recording URL field updated → `notion_updated`, `notion_page_url` persisted.
13. `source_marked_processed`: `DiskScanner.mark_processed(disk_path)` called (Phase 2 contract);
    `recording.source_processed = True`, `disk_deletable_after = utcnow() + 7 days` persisted.
    Status transitions to `source_marked_processed`.
14. `StatusService` is the single entry point for status transitions; it validates via
    `Recording.transition_to()`, persists all provided field kwargs atomically, and sets
    `last_attempted_at` on every call. No direct `recording.status =` assignments outside it.
15. `scan_recruiter` in `cron.py` resumes any `calendar_event_found` rows not yet processed in
    the current or previous runs (same resume logic as Phase 2 `found` rows). Errors during any
    transfer step set `failed` with `error_step` (string name of the step) and `error_message`.
    Recruiter isolation: one recruiter failure does not affect others.
16. `SecretStr` for `notion_token`, `synology_api_key`, `synology_pass`, `minio_secret_key`.
    Unwrapped only at HTTP boundary (`get_secret_value()`). Never logged.
17. No hardcoded recruiter emails, Notion DB IDs, Synology paths, Mattermost IDs in code.
    All from `recruiter_config` rows or `Settings`.
18. Ruff clean, format clean, strict mypy, all pytest pass.

## Phase 3 extends Phase 1/2 — do NOT recreate existing files

| File | Action | Reason |
|---|---|---|
| `app/config.py` | **Extend** | Add Notion prop names; `synology_*`, `minio_*`, `storage_provider` already present |
| `app/scheduler/cron.py` | **Extend** | Add post-`calendar_event_found` pipeline in `scan_recruiter` |
| `app/main.py` | **Extend** | Register Notion, storage backend in lifespan; inject on `app.state` |
| `app/tools/__init__.py` | **Extend** | Export new tool clients |
| `app/db/models/recording.py` | **No change** | All transfer fields exist from Phase 1 |
| `app/db/models/recruiter_config.py` | **No change** | `notion_database_id`, `synology_base_folder` exist |
| `alembic/` | **No change** | No new migration needed |
| `app/tools/notion.py` | **New** | NotionClient |
| `app/tools/synology.py` | **New** | SynologyBackend |
| `app/services/storage.py` | **New** | StorageBackend protocol + MinIOBackend |
| `app/services/candidate.py` | **New** | CandidateService (Notion search + disambiguation) |
| `app/services/transfer.py` | **New** | TransferService (streaming Disk → storage) |
| `app/services/status.py` | **New** | StatusService (atomic status transitions) |
| `tests/test_notion.py` | **New** | |
| `tests/test_synology.py` | **New** | |
| `tests/test_storage.py` | **New** | |
| `tests/test_candidate.py` | **New** | |
| `tests/test_transfer.py` | **New** | |
| `tests/test_status.py` | **New** | |

## Plan

### Step 1 — Extend `app/config.py`

Add global Notion property name settings (not per-recruiter — MVP uses uniform schema):
```python
notion_name_prop: str = "Name"
notion_date_prop: str = "General Interview Date"
notion_recording_prop: str = "General Interview recording"
```

Update `parse_string_mapping` validator to cover any new dict fields if added.

### Step 2 — `app/tools/notion.py`

`NotionClient(token: SecretStr, client: httpx.AsyncClient)`:

- `async search_pages(database_id, candidate_name, date, name_prop, date_prop) → list[NotionPage]`
  - `POST https://api.notion.com/v1/databases/{database_id}/query`
  - Filter: `{"and": [{"property": name_prop, "rich_text": {"contains": candidate_name}}, {"property": date_prop, "date": {"equals": date.isoformat()}}]}`
  - Page size: 10 max (return all, bounded)
  - Returns typed `NotionPage(id, url, title, date_str)`
  - HTTP errors: 401 → `NotionAuthError`, 404 → `NotionDatabaseNotFoundError`, 4xx/5xx → `NotionAPIError`
  - **Operational requirement:** Notion Integration must be connected (shared) with the **original**
    database, not only with a workspace page that contains a linked view of it. A linked-view page
    has a different ID and is not queryable via `/v1/databases/`. Confirm the correct database ID
    from `GET /v1/databases/{id}` (returns `object: "database"`) before seeding `recruiter_config`.
- `async update_page_url(page_id, prop_name, url) → None`
  - `PATCH https://api.notion.com/v1/pages/{page_id}`
  - Body: `{"properties": {prop_name: {"url": url}}}`
- `Notion-Version: 2022-06-28` header on all requests
- `Authorization: Bearer <token>` — unwrap `SecretStr` only here

### Step 3 — `app/services/storage.py`

```python
class StorageBackend(Protocol):
    async def ensure_folder(self, path: str) -> None: ...
    async def upload(self, folder: str, filename: str,
                     stream: AsyncIterator[bytes], size: int | None) -> str: ...  # returns full path
    async def create_share_link(self, path: str) -> str: ...  # returns URL
```

`MinIOBackend(endpoint, access_key, secret_key: SecretStr, bucket)`:
- Uses `aioboto3` or sync `boto3` in `asyncio.get_event_loop().run_in_executor` (simpler MVP)
- `ensure_folder`: no-op (S3 has no real folders; key prefix is the folder)
- `upload`: `put_object` with streaming body; path = `{folder}/{filename}`
- `create_share_link`: `generate_presigned_url("get_object", ExpiresIn=604800)` (7 days)

`StorageFactory.create(settings: Settings) → StorageBackend`:
- `settings.storage_provider == "synology"` → `SynologyBackend(...)`
- else → `MinIOBackend(...)`

### Step 4 — `app/tools/synology.py`

`SynologyBackend(base_url, api_key: SecretStr, client: httpx.AsyncClient)`:

Synology FileStation REST API (DSM 7.0, API Key auth header `X-SYNO-Token: <key>`):

- `ensure_folder(path)`:
  - `GET /webapi/entry.cgi?api=SYNO.FileStation.Info&method=get&version=2` to verify reachability
  - `POST /webapi/entry.cgi?api=SYNO.FileStation.CreateFolder` — create all intermediate dirs
  - Idempotent: 409/already-exists treated as success
- `upload(folder, filename, stream, size)`:
  - `POST /webapi/entry.cgi?api=SYNO.FileStation.Upload&method=upload&version=2`
  - Multipart form: `path={folder}`, `create_parents=true`, `file=<stream>`
  - Returns `{folder}/{filename}`
- `create_share_link(path)`:
  - `POST /webapi/entry.cgi?api=SYNO.FileStation.Sharing&method=create&version=3`
  - `path={path}`, `date_expired=-1` (no expiry), `date_available=0`
  - Returns `data.links[0].url`

Error handling: non-2xx → `SynologyAPIError(status_code, payload)`. `error.code == 408` (file exists) → idempotent success for upload.

### Step 5 — `app/services/candidate.py`

`CandidateService(notion: NotionClient, settings: Settings)`:

```python
async def find_and_match(
    recording: Recording,
    recruiter: RecruiterConfig,
    session: AsyncSession,
) -> CandidateMatchResult:
```

- Extract `candidate_name` from `recording.calendar_event_summary` via
  `re.search(r'\(([^)]+)\)$', summary)` — same regex as Phase 2 matching signal
- If no name extractable → `manual_review_required`, reason `no_candidate_name_in_event`
- Call `notion.search_pages(recruiter.notion_database_id, candidate_name, event_date, ...)`
- 0 pages → `manual_review_required`, reason `no_candidate_found`
- 1 page → return `CandidateMatchResult(page, confidence=1.0)`
- >1 pages → `manual_review_required`, reason `multiple_candidates`,
  candidates = `[{"name": p.title, "url": p.url} for p in pages[:10]]`

`CandidateMatchResult` dataclass: `page: NotionPage | None`, `reason: str | None`,
`candidates: list[dict] | None`.

### Step 6 — `app/services/transfer.py`

`TransferService(disk: DiskScanner, storage: StorageBackend, client: httpx.AsyncClient)`:

```python
async def transfer(
    recording: Recording,
    recruiter: RecruiterConfig,
    candidate_name: str,
    session: AsyncSession,
) -> TransferResult:
```

1. Build destination:
   - `date_str = recording.calendar_dtstart.strftime("%Y-%m-%d")`
   - `safe_name = re.sub(r'[/\\:*?"<>|]', "_", candidate_name)`
   - `folder = f"{recruiter.synology_base_folder}/{date_str}/{safe_name}"`
   - `filename = recording.disk_filename`  ← Phase 3 uses raw Disk filename
   - **Phase 4 note (out of scope here):** before Synology upload the agent must construct a
     meaningful filename from Notion card data. Planned template:
     `YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>`
     where `project_or_spot` comes from the matched Notion card's Spots/project relation and
     `interview_type` from the card's stage field. Implementation deferred until Q5 property IDs
     and Q8 (Lili schema) are resolved.

2. `await storage.ensure_folder(folder)`

3. Stream download + upload:
   ```python
   async with client.stream("GET", disk_download_url, headers=auth_headers) as resp:
       resp.raise_for_status()
       path = await storage.upload(folder, filename, resp.aiter_bytes(), 
                                   int(resp.headers.get("Content-Length", 0)) or None)
   ```

4. On upload failure → `TempFileFallback`: download to `/tmp/recording-agent/{uuid}/{filename}`,
   upload from file handle, delete temp immediately after backend confirms.
   TTL guard: scheduled coroutine deletes any `/tmp/recording-agent/*` older than 4h.

5. `share_url = await storage.create_share_link(path)`

6. Returns `TransferResult(folder_path=folder, file_path=path, share_url=share_url)`

`TransferError(step: str, cause: Exception)` — raised on any step failure; `step` maps to
`error_step`.

### Step 7 — `app/services/status.py`

`StatusService`:

```python
async def advance(
    session: AsyncSession,
    recording: Recording,
    new_status: RecordingStatus,
    *,
    error_step: str | None = None,
    error_message: str | None = None,
    **field_updates: object,
) -> None:
```

- Calls `recording.transition_to(new_status)` — raises `ValueError` on illegal transition
- Sets `recording.last_attempted_at = utcnow()`
- Applies all `field_updates` as `setattr(recording, k, v)`
- `await session.flush()` — does not commit (caller owns transaction)

This is the **only** place in Phase 3 code where `recording.status` changes.

### Step 8 — Extend `app/scheduler/cron.py`

After existing `scan_recruiter` lands a recording at `calendar_event_found`, add pipeline:

```
calendar_event_found
  └─ CandidateService.find_and_match()
       ├─ no match / ambiguous → advance(MANUAL_REVIEW_REQUIRED, reason=...)
       └─ matched
            └─ advance(CANDIDATE_MATCHED, candidate_name=..., notion_page_id=...)
                 └─ TransferService.transfer()
                      ├─ error → advance(FAILED, error_step=..., error_message=...)
                      └─ ok → advance(UPLOAD_TO_SYNOLOGY, synology_folder_path=..., synology_file_path=...)
                            └─ advance(SYNOLOGY_LINK_CREATED, synology_share_url=...)
                                 └─ NotionClient.update_page_url(...)
                                      ├─ error → advance(FAILED, ...)
                                      └─ ok → advance(NOTION_UPDATED, notion_page_url=...)
                                            └─ DiskScanner.mark_processed(disk_path)
                                                 └─ advance(SOURCE_MARKED_PROCESSED,
                                                            source_processed=True,
                                                            disk_deletable_after=utcnow()+7d)
```

Resume logic: `scan_recruiter` already queries `found` resumable rows. Add parallel query for
`calendar_event_found` rows with `last_attempted_at` null or < 24h ago (same resume window).

### Step 9 — Extend `app/main.py`

In lifespan startup, create and attach to `app.state`:
- `app.state.notion_client = NotionClient(settings.notion_token, httpx_client)`
- `app.state.storage_backend = StorageFactory.create(settings)`
- `app.state.candidate_service = CandidateService(notion_client, settings)`
- `app.state.transfer_service = TransferService(disk_scanner, storage_backend, httpx_client)`
- `app.state.status_service = StatusService()`

Inject into `scan_recruiter` call from `register_jobs`.

### Step 10 — Tests

`tests/test_notion.py`:
- Search: 0 / 1 / many results; date filter; auth error; not-found error
- Update URL: success; API error
- All via `respx` mocking `api.notion.com`

`tests/test_storage.py`:
- `MinIOBackend`: upload path/key construction, presigned URL shape (mock boto3)
- `StorageFactory`: returns correct type per `storage_provider`

`tests/test_synology.py`:
- `ensure_folder`: already-exists treated as success
- `upload`: multipart form fields, success path
- `create_share_link`: returns URL from response payload
- API error propagation
- All via `respx`

`tests/test_candidate.py`:
- No name in summary → reason `no_candidate_name_in_event`
- 0 Notion results → reason `no_candidate_found`
- 1 result → `CandidateMatchResult` with page
- >1 results → reason `multiple_candidates`, candidate list bounded

`tests/test_transfer.py`:
- Happy path: folder construction, streaming, path/URL returned
- Temp file fallback: triggered, temp deleted after upload
- Path sanitization: special chars replaced
- `TransferError` step propagated on upload failure

`tests/test_status.py`:
- Valid transition: status updated, fields set, `last_attempted_at` set
- Invalid transition raises `ValueError`
- Multiple `field_updates` persisted atomically

Extended `tests/test_scheduler.py`:
- Full pipeline: `calendar_event_found → ... → source_marked_processed`
- Candidate not found → `manual_review_required`
- Transfer failure → `failed` with `error_step`
- Resume: `calendar_event_found` row picked up in next scan
- Recruiter isolation: one transfer failure doesn't abort others

### Step 11 — Gate

```bash
poetry run ruff check app tests alembic
poetry run ruff format --check app tests alembic
poetry run mypy app tests
poetry run pytest
```

All must pass. Quote real output.

## Blockers

None.
- Q1 resolved: `recruiter_config.synology_base_folder` provides base; date/name subdirectory is
  a code convention, not external data.
- Q5 resolved: `recruiter_config.notion_database_id` provides DB ID; property names are global
  settings with defaults matching known Anton schema. Lili assumed same schema for MVP (Q8 open
  but non-blocking — same code path, same property names).
- Q3 (Mattermost) and Q10 (OpenClaw) are Phase 4/5 blockers, not Phase 3.

## Out of scope

- Mattermost notifications (Phase 4)
- OpenClaw event push (Phase 5)
- Intelligent Synology filename from Notion card data — template
  `YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>` — Phase 4, requires
  Q5 property IDs and Q8 Lili schema resolved
- Notion candidate search by email (Q5 property IDs, Phase 4 refinement)
- Synology folder structure per-position or per-project (Q1 advanced design, post-MVP)
- Disk retention / cleanup / Trash / permanent purge (Phase 2, unchanged)
- `source_deleted` / `completed` status transitions (require cleanup cron, already Phase 2)
- Multi-recruiter Lili schema differences (Q8, Phase 4)
- New Alembic migrations

## Assumptions

- All recruiters use the same Notion DB property names for MVP (Q8 open but non-blocking).
- `recruiter_config.notion_database_id` holds the **original Notion database UUID** (not a
  linked-view page ID). Verify with `GET /v1/databases/{id}` → `"object": "database"` before
  seeding. The Notion Integration must be explicitly shared with that original database.
- `disk_filename` matches the Yandex Disk original filename exactly; no renaming before transfer.
- Synology DSM 7.0+ confirmed (Q2 closed) — API Key auth only, no Session SID.
- `candidate_name` for path construction comes from `recording.calendar_event_summary`
  parentheses extraction (same as Phase 2 signal). If absent, `manual_review_required`.
- MinIO is the test/dev backend; real Synology tested in integration environment.
- `source_marked_processed` is the terminal happy-path status for Phase 3.
  `source_deleted → completed` are Phase 2 retention cron territory (already implemented).
