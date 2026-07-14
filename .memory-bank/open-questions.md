# Open Questions

Resolve these BEFORE starting the affected phase. Each one is a blocker for specific code.

## Q1: Synology folder structure [BLOCKER for transfer.py]
**Question:** What is the folder tree in Synology for recordings? Which path per recruiter? Per candidate?
**Proposed solution:** Define folder rules in a Notion table so agent can query them as config. Recruiter adds rows as new projects/positions appear.
**Needs:** Synology access + recruiter input on naming conventions.
**Status:** Open

## Q2: Synology DSM version ✅ CLOSED
**Answer:** DSM 7.0+ confirmed → API Key auth available.
**Consequence for synology.py:** Use API Key header only. No Session SID fallback needed.
**ADR:** ADR-005 confirmed, ADR-012 (MinIO for dev testing) added.

## Q3: Mattermost routing — channel vs DM [BLOCKER for mattermost.py]
**Question:** Notifications and disambiguation: shared `#recordings` channel, or DM to specific recruiter?
**Proposed:** DM bot to recruiter directly (avoids noise in shared channels). Recruiter must add bot as contact.
**Status:** Open

## Q4: Яндекс.Диск — where Telemost recordings land ✅ CLOSED
**Answer:** Fixed folder `/Записи Телемоста/` on organizer's Яндекс.Диск.
**Additional:** After meeting ends, email arrives with:
- Direct yadi.sk share links for video + audio
- Link to folder: `https://disk.yandex.ru/client/disk/Записи%20Телемоста`
**Consequence for disk.py:** Scan path `/Записи Телемоста/` per recruiter account. Both video and audio files land there.

## Q5: Notion database IDs + field IDs [BLOCKER for notion.py]
**Question:** Need exact database IDs and property IDs (not just names) for each recruiter's DB.
**Known (Anton's Interviews DB):** Name (title), General Interview Date (date), General Interview recording (url), TBD (formula), Spots (relation).
**Action:** Call Notion API: `GET /v1/databases/{database_id}` → get property IDs.
**Status:** Open — need database_ids from recruiter

## Q6: calink.ru calendar event markers ✅ CLOSED
**Answer (from Yandex Calendar screenshot, 2026-07-14):**
calink.ru events in CalDAV have two **guaranteed** markers visible in the event detail:
1. **DESCRIPTION contains `https://calink.ru/{recruiter-slug}/{type}/{id}?code=...`** — reliable HIGH-confidence signal that meeting was booked via calink scheduling link.
2. **DESCRIPTION contains `https://telemost.360.yandex.ru/j/{id}`** — confirms this is a Telemost video meeting.
3. **SUMMARY pattern**: `"Встреча на N минут (Кандидат Имя)"` — candidate name in parentheses at end of title. First name guaranteed; last name present in the example but may be absent.
4. **ATTENDEE**: email present (`strokan-dima@mail.ru`) but **unreliable for Notion matching** — may differ from Notion DB email. Treat as LOW signal.
5. **ORGANIZER**: recruiter account ("Я") — already assumed.
**PRODID/custom CalDAV properties**: not needed — calink.ru URL in DESCRIPTION is sufficient marker.

**Consequences for matching.py:**
- Source of truth is Yandex Calendar via CalDAV — matcher works regardless of booking service.
- `has_telemost_url(description)` → `re.search(r'https://telemost\.360\.yandex\.ru/', description)` — **HIGH weight (0.35)**
- `time_overlap` — recording time within [dtstart-15min, dtend+15min] — **HIGH weight (0.30)**
- `extract_candidate_name(summary)` → `re.search(r'\(([^)]+)\)$', summary)` — **HIGH weight (0.20)**
- `booking_source_marker` — any scheduling URL (calink.ru, calendly, etc.) in DESCRIPTION — **LOW weight (0.05), OPTIONAL** — absence never blocks match
- calink.ru URL is NOT a required or HIGH signal; it is one of many possible booking sources
- Attendee email → **LOW (0.05), STUBBED Phase 2**; never block match on email mismatch
- No PRODID inspection needed

## Q7: Multiple Яндекс accounts ✅ CLOSED
**Answer:** All recruiters are in the same Яндекс 360 org — corporate accounts `@effective.band`.
**Consequence for OAuth:** Each recruiter still has their own Disk. MVP approach: one `refresh_token` per recruiter (Anton + Lili = 2 tokens). Tokens keyed by recruiter email in config.
**Future:** Яндекс 360 Directory API may allow org-admin access to all users' Disks — investigate after MVP.

## Q8: Lili's Notion database
**Question:** What is Lili's Notion database structure? Same schema as Anton's or different fields?
**Status:** Open — need Lili's database_id and field listing

## Q10: OpenClaw tool registration method [BLOCKER for tool contract design]
**Question:** How does OpenClaw register/discover tools from Backend?
- MCP server endpoint
- OpenAPI spec (`/openapi.json` at startup)
- JSON Schema config file
**Strategy:** Design Backend as standard HTTP endpoints first. Adapt tool descriptions to OpenClaw format after confirming. Backend design is independent of registration format.
**Status:** Open — check OpenClaw docs/source

## Q9: Recording retention policy on Яндекс.Диск ✅ CLOSED
**Answer (2026-07-14):** Two-stage retention:
1. On successful Synology upload: set custom property `app:recording_agent:processed=true` via `PATCH /disk/resources` (Yandex Disk custom_properties).
2. DiskScanner skips files with this property → no double processing.
3. Separate cleanup cron (daily): delete files where `processed=true` AND `processed_at` older than 7 days → `DELETE /disk/resources` (to Trash) then `DELETE /disk/trash/resources` to permanent delete.

**Consequences for disk.py:**
- `DiskScanner.list()` filters out items with `custom_properties.processed == "true"`.
- `DiskScanner.mark_processed(path)` → PATCH custom_properties: `{"processed": "true", "processed_at": "<ISO8601>"}`.
- `DiskScanner.delete_expired()` → list processed items, check processed_at age, delete those ≥7 days.
- `DELETE /disk/resources` moves to Trash; `DELETE /disk/trash/resources` permanently removes. Implement both steps. Ask before permanent delete per AGENTS.md destructive-ops rule.

**Note:** custom_properties reads require extra API call per file (not returned in folder listing by default). Batch by reading only after scanner confirms file is candidate for processing — not on every scan.
