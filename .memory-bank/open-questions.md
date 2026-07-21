# Open Questions

Resolve these BEFORE starting the affected phase. Each one is a blocker for specific code.

## Q1: Storage folder/key structure ✅ CLOSED FOR PHASE 4
**Answer (2026-07-21):** Phase 4 uses MinIO only. Synology is unavailable and remains a later
production decision. The logical object prefix is
`<recruiter>/<YYYY-MM-DD>/<candidate>/`; MinIO represents folders as `/`-delimited object-key
prefixes. The generated basename is
`YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>`.
**Collision rule:** A retry of the same recording reuses the same key. A different recording that
resolves to an existing key requires manual review; never overwrite or silently auto-suffix.
**Status:** Closed for the MinIO canary. Reopen before Synology production rollout to confirm the
real share and base path.

## Q2: Synology DSM version ✅ CLOSED
**Answer:** DSM 7.0+ confirmed → API Key auth available.
**Consequence for synology.py:** Use API Key header only. No Session SID fallback needed.
**ADR:** ADR-005 confirmed, ADR-012 (MinIO for dev testing) added.

## Q3: Mattermost routing — channel vs DM ✅ CLOSED
**Answer (2026-07-21):** DM-only to the configured recruiter. No shared-channel fallback.
Manual-review replies must be bound to recruiter ID, DM post/thread ID, recording/review version,
an opaque one-time token, and an expiry. Wrong-user, stale, expired, and replayed replies fail
closed.

## Q4: Яндекс.Диск — where Telemost recordings land ✅ CLOSED
**Answer:** Fixed folder `/Записи Телемоста/` on organizer's Яндекс.Диск.
**Additional:** After meeting ends, email arrives with:
- Direct yadi.sk share links for video + audio
- Link to folder: `https://disk.yandex.ru/client/disk/Записи%20Телемоста`
**Consequence for disk.py:** Scan path `/Записи Телемоста/` per recruiter account. Both video and audio files land there.

## Q5: Notion database IDs and schema validation [OPERATIONAL BLOCKER per recruiter]
**Question:** What is each recruiter's original database ID, and is it shared directly with the
Recording Agent integration?
**Known (Anton's Interviews DB):** Name (title), General Interview Date (date), General Interview
recording (files), TBD (formula), Spots (relation).
**Action:** Keep only the original database ID in configuration. With `Notion-Version: 2026-03-11`,
call `GET /v1/databases/{database_id}`, then retrieve every advertised schema through
`GET /v1/data_sources/{data_source_id}`. Property IDs and types come from data-source retrieval,
not database retrieval. Enable the recruiter only when exactly one source has the configured
name/date/recording properties with types `title`/`date`/`files`.
**Phase 4 decision (2026-07-21):** Use a test database first; production recruiter databases stay
disabled. After sharing was updated, Mila's configured token retrieved page
`397c8889-e4c8-814c-8acf-d7da92915220`, child database `Test Interviews`
(`ef16e0bf-e91b-470f-90a1-749d0bae0ad3`), and data source
`0788967f-04fe-43c3-a78b-d2572e031031`. The read-only schema probe confirms `Name` (title),
`General Interview Date` (date), `General Interview recording` (files), and `Spot Client`
(rich_text). General-interview naming uses `Spot Client` plus constant `general_interview`;
`Stage` is not the interview type.
**Credential boundary:** Backend `NOTION_TOKEN` and Mila/OpenClaw `NOTION_API_KEY` are environment
variable names. They may contain the same Connection access token; using separate least-privilege
tokens is recommended but not required. The skill still calls Backend intents rather than Notion.
**Status:** Test database selection, sharing, and schema are confirmed through Mila. Before a live
write, repeat the probe using Backend's runtime token and select a synthetic test row. Data-source
IDs are discovered at runtime and never configured.

## Q6: calink.ru calendar event markers ✅ CLOSED
**Answer (from Yandex Calendar screenshot, 2026-07-14):**
calink.ru events in CalDAV have two **guaranteed** markers visible in the event detail:
1. **DESCRIPTION contains `https://calink.ru/{recruiter-slug}/{type}/{id}?code=...`** — a reliable HIGH-confidence signal that the meeting was booked through the current effective.band flow.
2. **DESCRIPTION contains `https://telemost.360.yandex.ru/j/{id}`** — confirms only that this is a Telemost video meeting. Yandex prepends this block to every video event, including self-tests and manual events; it is a low diagnostic signal, not evidence of an interview.
3. **SUMMARY pattern**: `"Встреча на N минут (Кандидат Имя)"` — candidate name in parentheses at end of title. First name guaranteed; last name present in the example but may be absent.
4. **ATTENDEE**: email present (`strokan-dima@mail.ru`) but **unreliable for Notion matching** — may differ from Notion DB email. Treat as LOW signal.
5. **ORGANIZER**: recruiter account ("Я") — already assumed.
**PRODID/custom CalDAV properties**: not needed — calink.ru URL in DESCRIPTION is sufficient marker.

**Consequences for matching.py:**
- Source of truth is Yandex Calendar via CalDAV — matcher works regardless of booking service.
- `time_overlap` — recording time within [dtstart-15min, dtend+15min] — **HIGH weight (0.35)**
- `booking_source_marker` — `calink.ru` URL in DESCRIPTION — **HIGH weight (0.30)** for the current effective.band flow; absence never blocks manual review
- `extract_candidate_name(summary)` → `re.search(r'\(([^)]+)\)$', summary)` — **MEDIUM/HIGH weight (0.25)**
- `has_telemost_url(description)` → `re.search(r'https://telemost\.360\.yandex\.ru/', description)` — **LOW weight (0.05)**
- Interview keywords — **LOW weight (0.05)**
- Attendee email → **LOW (0.05), STUBBED Phase 2**; never block match on email mismatch
- No PRODID inspection needed

## Q7: Multiple Яндекс accounts ✅ CLOSED
**Answer:** All recruiters are in the same Яндекс 360 org — corporate accounts `@effective.band`.
**Consequence for OAuth:** Each recruiter still has their own Disk. MVP approach: one `refresh_token` per recruiter (Anton + Lili = 2 tokens). Tokens keyed by recruiter email in config.
**Future:** Яндекс 360 Directory API may allow org-admin access to all users' Disks — investigate after MVP.

## Q8: Lili's Notion database
**Question:** What is Lili's Notion database structure? Same schema as Anton's or different fields?
**Validation:** Run the read-only copied-database probe first: retrieve the copied database, retrieve
all advertised data-source schemas, and require exactly one compatible schema. Do not query or
update candidate pages during this probe.
**Status:** Open — production enablement is blocked for Lili until direct sharing and unique schema
compatibility are verified. Source order must not resolve ambiguity.

## Q10: OpenClaw integration method ✅ CLOSED FOR MILA MVP
**Answer (Mila discovery, 2026-07-20):** Mila runs OpenClaw `2026.4.22`. Use the existing workspace
skill pattern: `SKILL.md` plus a bundled CLI script calling narrow authenticated Backend intents on
loopback. Do not assume a generic event-push endpoint, use `/tools/invoke` as registration, or
require MCP/OpenAPI/native-plugin registration for MVP.
**Boundary:** Backend owns scheduler, matching, transfers, Notion, storage, and state. Mila handles
explicit Mattermost interaction and manual-review language only. A native plugin remains a later
option if the script-backed contract proves insufficient.
**Status:** Closed for Mila Phase 4. Re-evaluate for Sylvanas or an OpenClaw upgrade.

## Q9: Recording retention policy on Яндекс.Диск ✅ CLOSED
**Answer (2026-07-14):** Two-stage retention:
1. On successful Synology upload: set custom property `app:recording_agent:processed=true` via `PATCH /disk/resources` (Yandex Disk custom_properties).
2. DiskScanner skips files with this property → no double processing.
3. Separate daily cleanup cron: for files where `processed=true` and `processed_at` is at least
   7 days old, call `DELETE /disk/resources` to move them to Trash. This cron is soft-delete-only.
4. Permanent deletion is a separate, never-scheduled operation. Every run requires a new
   `PermanentDeleteApproval` with a non-empty operator identity, timezone-aware timestamp no
   more than 5 minutes old, and non-empty unique nonce. Freshness uses an injected/trusted aware
   UTC clock; callers cannot provide `now`. The nonce is consumed before any request and cannot
   be reused after success or failure. The purge enumerates real Trash resources and deletes
   their actual `trash:/...` paths. No environment/configuration boolean may grant standing
   authority.

**Consequences for disk.py:**
- `DiskScanner.list()` filters out items with `custom_properties.processed == "true"`. If
  `processed_at` is missing or invalid, it repairs the timestamp to current UTC and still
  excludes the item, preventing duplicate processing.
- `DiskScanner.mark_processed(path)` → PATCH custom_properties: `{"processed": "true", "processed_at": "<ISO8601>"}`.
- `DiskScanner.delete_expired()` → list processed items, check `processed_at` age, and move those
  aged at least 7 days to Trash. If a processed item has missing/invalid `processed_at`, repair
  it to current UTC and do not delete it during that run. It never permanently deletes.
- `DiskScanner.purge_expired_from_trash(approval)` → validate fresh per-run approval, enumerate
  Trash, correlate `origin_path`, validate markers/age, and permanently delete actual Trash paths.
- A partial purge is resumable: a later run requires fresh approval and re-enumerates remaining
  Trash resources. The prior nonce remains consumed even when the purge failed, so retry requires
  a newly issued approval. Ask before every purge run per the `AGENTS.md` destructive-operations
  rule.

**Note:** custom_properties reads require extra API call per file (not returned in folder listing by default). Batch by reading only after scanner confirms file is candidate for processing — not on every scan.

## Q11: Multiple Calendar selection and Telemost filename correlation ✅ CLOSED
**Answer (2026-07-15):** The shared `/Записи Телемоста/` Disk folder is immutable and contains
recordings for all recruiter calendars. Calendar selection therefore controls match eligibility,
not Disk discovery.

**Consequences:**
- Each recruiter has exactly one explicit default calendar and zero or more selected calendars.
  The effective set is the selected set when non-empty, otherwise the default only. A validated
  legacy `caldav_calendar_url` is a migration fallback; response order never chooses a default.
- Discovery stores recruiter-owned canonical same-origin HTTPS VEVENT collections and display
  names. Configuration accepts only opaque discovered IDs; arbitrary URLs are never requested
  with recruiter credentials.
- Every scan queries all available calendars as one complete snapshot. Unselected calendars are
  collision evidence only and can never become the confirmed source.
- Official video and audio-only filenames must parse as either
  `YYYY-MM-DD_HHMMSS_<meeting title>.webm` or
  `YYYY-MM-DD_HHMMSS_<meeting title>_audio_only.webm`. The parsed local start and exact
  Unicode NFKC + casefold + whitespace-normalized title must agree with one eligible VEVENT.
- Parser failure, no compatible event, unmonitored-only compatibility, duplicates, or any
  monitored/unmonitored collision requires structured `manual_review_required`; automatic
  `ignored` remains forbidden.
- Confirmed matches store calendar row ID and immutable URL/display-name snapshots. Manual-review
  diagnostics are bounded and exclude raw ICS, passwords, and authorization material.

## Q12: Recruiter onboarding and Notion database selection ✅ CLOSED FOR MVP

**Answer (2026-07-21):** There is no self-service onboarding in the current code. MVP requires an
operator to provision each recruiter's Yandex refresh token and CalDAV app password before
activation. The Backend deployment owns these secrets; OpenClaw skills do not receive them.

`recruiter_config.notion_database_id` is mandatory PostgreSQL configuration, not an environment
variable and not an LLM decision. An operator supplies a Notion URL/ID. The bootstrap flow may
resolve the original database ID only from that explicit target, must validate sharing and schema,
must show the result for confirmation, and then stores the ID on an inactive recruiter row.
Workspace-wide search must never silently select a database. Data-source IDs remain runtime-only.

**Current canary:** `Test Interviews` database
`ef16e0bf-e91b-470f-90a1-749d0bae0ad3` is confirmed through Mila. Repeat the schema probe with the
Backend runtime token before enabling writes.

**Future:** Self-service OAuth/onboarding is a separate feature and requires consent callbacks,
secure secret storage, revocation, audit, and deactivation flows.
