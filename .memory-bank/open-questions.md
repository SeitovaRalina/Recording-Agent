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

## Q6: calink.ru calendar event markers [BLOCKER for matching.py interview detection]
**Question:** Do CalDAV events created via calink.ru have a recognizable marker (PRODID, organizer format, custom property) we can use for filtering?
**Action:** Export a real calink.ru-created event as `.ics` and inspect all fields.
**Status:** Open

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

## Q9: Recording retention policy on Яндекс.Диск
**Question:** After successful transfer to Synology: delete immediately, or move to `/processed/` archive folder, or keep?
**Per TOR:** Delete if all steps successful. But what is the grace period?
**Status:** Open — decision from client needed
