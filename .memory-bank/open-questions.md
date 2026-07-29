# Open Questions

Resolve these BEFORE starting the affected phase. Each one is a blocker for specific code.

## Q1: Storage folder/key structure ✅ CLOSED FOR PHASE 4
**Answer (2026-07-21):** Phase 4 uses MinIO only. Synology is unavailable and remains a later
production decision. The logical object prefix is
`<recruiter>/<YYYY-MM-DD>/<candidate>/`; MinIO represents folders as `/`-delimited object-key
prefixes. The generated basename is
`YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>`.
**Source amendment (2026-07-22):** Project source must be configured as an explicit property
name/type pair. A UTF-8-safe read-only probe confirms that test database `fe5...` exposes the
literal property `📍 Spots: relation`; the earlier probe missed it because its console output failed
on Unicode. Test and production therefore use `📍 Spots/relation` after independent preflights.
For one relation, resolve the related Spot page
and use its title as `<project_or_spot>`. Empty rich text or an empty relation uses the deterministic
component `unspecified`. A nonblank resolved title keeps existing sanitization; if it sanitizes to
empty, fail closed as `invalid_storage_identity`. Multiple related `📍 Spots` must not be silently
ordered or joined. This policy does not update or reprocess existing recording rows.
**Collision rule:** A retry of the same recording reuses the same key. A different recording that
resolves to an existing key requires manual review; never overwrite or silently auto-suffix.
**Status:** Closed for the MinIO canary. Reopen before Synology production rollout to confirm the
real share and base path.

## Q2: Synology DSM version ✅ CLOSED
**Answer:** DSM 7.0+ confirmed → API Key auth available.
**Consequence for synology.py:** Use API Key header only. No Session SID fallback needed.
**ADR:** ADR-005 confirmed, ADR-012 (MinIO for dev testing) added.

## Q3: Mattermost routing and conversation UX ✅ CLOSED FOR TARGET UX
**Answer (updated 2026-07-22):** Use one ordinary DM conversation with the configured recruiter;
do not require the recruiter to open or reply in Mattermost threads. No shared-channel fallback.
Mila first sends one daily summary, then presents every unresolved recording as a numbered,
actionable question. A recruiter may answer all questions or any subset in free form. Mila must
state how it understood the answer, report that processing started, and later report completion or
an actionable error.

PostgreSQL, not Mila's conversational memory, owns the durable set of pending, answered,
processing, completed, failed, and suppressed questions. Replies remain bound to recruiter,
DM channel, recording/review ID, recording version, an opaque one-time capability, and expiry;
thread ID is not part of the target binding. Wrong-user, stale, expired, ambiguous, and replayed
answers fail closed. An unrelated Mila conversation must not consume a Recording Agent question.

An unanswered question remains pending and is repeated once in the next eligible 18:00
recruiter-local summary. It is then automatically suppressed from later summaries unless
explicitly reopened. Do not send reminder spam between summaries. Closed or suppressed questions
are never repeated automatically.

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
recording (files), TBD (formula), 📍 Spots (relation).
**Action:** Keep only the original database ID in configuration. With `Notion-Version: 2026-03-11`,
call `GET /v1/databases/{database_id}`, then retrieve every advertised schema through
`GET /v1/data_sources/{data_source_id}`. Property IDs and types come from data-source retrieval,
not database retrieval. Enable the recruiter only when exactly one source has the configured
name/date/recording properties with types `title`/`date`/`files`.
**Phase 4 decision (corrected 2026-07-22):** Use a test database first; production recruiter
databases stay disabled. The confirmed `Test Interviews` database ID is
`<test-notion-database-id>`, stored outside Git. Database
`ef16e0bfe91b470f90a1749d0bae0ad3` is production and must never be configured in the canary.
The read-only schema probe must confirm `Name` (title), `General Interview Date` (date),
`General Interview recording` (files), and configured `📍 Spots` (relation). Production must
independently validate the same literal property and type. General-interview naming
uses the resolved configured project property plus constant `general_interview`; `Stage` is not
the interview type. Discover
the data-source ID at runtime and never persist it.

**Candidate matching amendment (confirmed by Anton, 2026-07-22):** `General Interview Date` is an
output, not a prefilled lookup constraint. Candidate lookup must not require it. Match by candidate
name; email is an optional additional signal. Production contacts are exposed through the `TBD`
property of type `formula`, based on
`prop("Candidate").map(current.prop("Contacts"))`. A rendered Contacts value may contain phone,
email, and Telegram data on separate lines, for example `example@gmail.com`. Runtime schema/value
probing must confirm the exact Notion API formula representation. Parse only syntactically valid
email addresses, normalize them case-insensitively, and never treat phone/Telegram text as email.
Use a calendar attendee email only as supporting evidence; absence or mismatch must not reject an
otherwise valid name match. Multiple candidate cards or multiple conflicting emails require an
actionable recruiter choice. After processing, write the matched calendar event date to
`General Interview Date` and the final storage link to `General Interview recording`.
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

## Q9: Recording retention policy on Яндекс.Диск ✅ CLOSED FOR TARGET UX
**Answer (updated 2026-07-22):** The Telemost recordings folder is reported to be removed by
Yandex after 90 days and not to consume the normal cloud-storage quota. Recording Agent therefore
must not schedule automatic source cleanup for the target workflow.

Keep a manual recruiter command equivalent to "clean successfully processed recordings". It
must first return a bounded preview and require explicit confirmation. Eligibility must be proven
from Backend state: the recording completed successfully and has a durable final-storage link.
Never include pending review, processing, failed, ignored-without-transfer, or otherwise
unverified files. A confirmed cleanup may only move eligible source files to Yandex Trash; it must
be idempotent and report each result. Permanent purge remains unavailable to Mila and is never
scheduled.

The current code's older `processed=true` plus automatic seven-day cleanup model is superseded by
this target decision and must remain disabled until it is reconciled. There is no minimum age:
an item becomes eligible immediately after Backend proves successful processing. Preview and
explicit confirmation remain mandatory because moving a source file to Trash is destructive.

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
`<test-notion-database-id>` is the confirmed test target and its real ID is stored outside Git. Database
`ef16e0bfe91b470f90a1749d0bae0ad3` is production and is forbidden in canary configuration.
Repeat the schema probe with the Backend runtime token before enabling writes; discover the
data-source ID at runtime and never persist it.

**Future:** Self-service OAuth/onboarding is a separate feature and requires consent callbacks,
secure secret storage, revocation, audit, and deactivation flows.

## Q13: Non-interview routing to Synology ✅ CLOSED FOR TARGET UX

**Confirmed requirement (Anton, 2026-07-22):** A recruiter may explain that an unresolved
recording is not an interview, identify it as another work meeting, choose a Synology folder, and
ask Mila to store it there and return a link. This is not the same as `ignored`: a successful
non-interview route uploads the file and completes without updating a candidate Notion card.

**Safety requirement:** Do not expose an arbitrary raw storage-path primitive to OpenClaw. The
Backend must resolve the request to recruiter-owned, discovered, bounded Synology destinations
and persist the chosen destination before upload.

**Answer (2026-07-22):** Recruiters may choose an existing folder or ask Mila to create a new one.
Backend must create it only under the recruiter's configured storage root after canonical path
validation and permission checks; free-form text never becomes an unchecked raw path. The exact
production base path and credentials remain an operational Synology preflight requirement.

## Q14: Reminder policy for unanswered review questions ✅ CLOSED FOR TARGET UX

**Confirmed requirement (2026-07-22):** Mila must identify questions left unanswered after a
partial free-form reply and repeat them later. Closed questions must never be repeated. Reminder
state and deduplication belong to Backend/PostgreSQL.

**Answer (2026-07-22):** Send the consolidated summary at 18:00 in the recruiter's configured
local timezone. Repeat each unanswered question once in the next eligible summary, then keep it
durable but set it to `suppressed` so it does not appear in later automatic summaries unless
explicitly reopened. Do not send additional reminders during the day. A user may still answer an
active question at any time; accepted work gets immediate start and completion or error feedback.
"Skip" closes the relevant question according to the selected action.

## Q15: Multiple related `📍 Spots` in Notion ✅ CLOSED FOR TARGET UX

**Question:** If a candidate card relates to more than one `📍 Spots` page, which value belongs in the
single `<project_or_spot>` filename component and Synology path?
**Known:** Zero relations use `unspecified`; exactly one relation resolves that page's title. The
reported `unspecified` result came from reading the legacy `Spot Client/rich_text` property instead
of the literal `📍 Spots/relation` property; explicit relation resolution is being added.
**Answer (2026-07-22):** Fail closed and create a structured recruiter question. Show every
bounded related Spot title and Notion URL. The recruiter explicitly selects one Spot; Backend
persists that selection and rechecks the filename/storage collision before transfer. Never choose
or merge relations by API order. An unanswered selection follows the normal one-reminder then
automatic-suppression policy.

## Operational rollout blockers (2026-07-22)

- Mila has no Docker/Compose runtime. Exact package installation and service mutations require an
  approved remote manifest.
- Production Synology endpoint/API key/share/root and permission proof are unavailable.
- Mattermost values require an approved safe Mila-side transfer; the first real allowlisted DM is
  separately approved.
- Backend runtime must repeat the read-only Notion schema/formula probe before the first test
  write. Lili production activation remains blocked on sharing/schema proof.
- Mila agent invocation, the actual scheduled 18:00 test, and all production Notion/Yandex/
  Synology effects require separate explicit approvals.
- Manual message-triggered scan remains supported while the scheduler is disabled. No scheduled
  Yandex cleanup is part of the target system.

## Q16: Autonomous Synology routing delivery ownership — CLOSED

**Answer (2026-07-29):** Backend creates a durable routing job after daily/manual scan matching;
it does not start OpenClaw or call an LLM. A root-owned Gateway command-cron dispatcher polls for
one ready job, takes a short lease, and starts one isolated worker with only a job UUID and one-time
nonce. The worker selects one opaque destination UUID or defers. Backend validates again and owns
all transfer and recruiter notification side effects.

**Safety:** Job context is untrusted delimited data under a versioned worker system instruction.
No raw Synology path, recruiter identity, Notion/Yandex URL, master secret, or integration
credential reaches the worker. Defer/failure notification belongs to Backend NotificationOutbox,
not the worker. Feature flag and cron remain disabled until no-job smoke and an approved canary.
