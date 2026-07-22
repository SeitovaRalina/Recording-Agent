# Architecture

For unfinished Recording Agent work, `swarm-report/recording-agent-mila-completion-plan.md` is the
implementation authority. The earlier Phase 4 plan remains historical input.

## Component diagram

```
┌──────────────────────────────────────────────────────────┐
│              Backend Tools Service                       │
│              Python 3.13 + FastAPI + APScheduler         │
│                                                          │
│  scheduler/                                              │
│    cron.py         APScheduler: scan Disk 1×/day         │
│                    + on Mattermost /recordings check      │
│                                                          │
│  tools/                                                  │
│    disk.py         Яндекс.Диск list/download/delete      │
│    calendar.py     CalDAV event search + parse           │
│    notion.py       search cards, update fields           │
│    synology.py     upload file, create share link        │
│    mattermost.py   send message, receive reply           │
│                                                          │
│  services/                                               │
│    matching.py     recording ↔ calendar event scoring    │
│    candidate.py    Notion card search + disambiguation   │
│    transfer.py     streaming Disk → Synology             │
│    status.py       PostgreSQL state machine ops          │
│    pipeline.py     deterministic scan/review execution   │
└───┬────────┬────────┬────────┬────────┬──────────────────┘
    │        │        │        │        │
  Яндекс  Яндекс  Notion  Synology  Mattermost
  Диск   Кален.            ↕ (bot)      ↕ (bot)
    │
  PostgreSQL                         OpenClaw
  (recording states + metadata)   Recording Agent
         ↑                              │
         └──── narrow loopback intents ─┘
                                        │
                                   tool calls
                                   back to Backend
```

**Key principle:**
- Backend = scheduler + executor. Scans Disk, owns PostgreSQL, runs all integrations.
- OpenClaw = recruiter interaction layer. Mila maps free-form Mattermost requests to narrow
  Backend intents and presents manual-review choices; it never owns scheduling or integration
  side effects.
- Deterministic matches complete entirely in Backend without an LLM call. Mila is invoked only
  for explicit recruiter interaction, bounded status reporting, or ambiguous review dialogue.

## Phase 4 Mila canary boundary

- Mila is the first OpenClaw canary; Sylvanas remains unchanged.
- The version-controlled workspace skill calls authenticated FastAPI intents over loopback. It
  contains no integration credentials and exposes no raw transfer, Notion, mark-processed, delete,
  or purge primitive.
- PostgreSQL is the durable source of truth for review correlation, expected versions, one-time
  token consumption, idempotency replay, scheduler ownership, and notification state.
- Canary storage is isolated MinIO and the selected Notion database is `Test Interviews`.
  Production Notion databases, Synology, Yandex source mutation, cleanup, and purge are disabled.
- Mattermost interaction is DM-only to the configured recruiter; no shared-channel fallback is
  allowed.

## Target conversation amendment (confirmed 2026-07-22; not yet implemented)

- Use Mila's ordinary recruiter DM without mandatory Mattermost threads.
- After a scheduled scan, send one complete summary and numbered actionable questions for all
  unresolved recordings.
- Recruiters may answer all questions or any subset in free form. Mila confirms the interpreted
  actions, reports processing start, and later reports completion/error.
- Backend/PostgreSQL owns the durable question queue, partial-answer progress, versions, one-time
  capabilities, TTL, idempotency, notification deduplication, and unanswered reminders. Mila's
  chat memory is not workflow state.
- Unrelated requests to Mila must continue normally and must not consume a pending recording
  question. Ambiguous answer-to-question mapping requires clarification.
- Send the consolidated summary at 18:00 in the recruiter's configured local timezone. An
  unanswered question is repeated once in the next eligible summary and then suppressed from
  later automatic summaries unless explicitly reopened. Accepted work receives immediate
  start/result feedback.
- `General Interview Date` is no longer a candidate-lookup prerequisite. Candidate lookup is by
  name. Email is an optional supporting signal extracted from the mixed contacts returned by the
  Notion `TBD` formula; Calendar attendee mismatch never rejects a name match. After a match,
  Backend writes the matched calendar event date and final storage link to Notion.
- Project/spot property is configured by both name and expected type. Test and production use
  the exact Notion API property `📍 Spots/relation` after their own schema preflights. One
  relation resolves the related page title, zero uses `unspecified`, and multiple relations
  create a structured recruiter choice. Every bounded Spot title/URL is shown, API order never
  chooses one, and the explicit selection is persisted before filename/key generation.
- A non-interview may be routed to a confirmed Synology destination and completed without a
  Notion candidate update. This is distinct from `ignored`. The recruiter may request a new folder,
  but Backend creates it only under the configured recruiter storage root after canonical-path and
  permission validation.
- Yandex source cleanup is manual-only: preview, explicit confirmation, and Trash move only for
  Backend-proven successfully processed files. There is no minimum age after successful
  processing. No scheduled cleanup or Mila-accessible permanent purge.

## Data flow — happy path

```
TRIGGER (Backend APScheduler — 1×/day OR /recordings check via Mattermost)
│
├─ Backend: disk.list_new() → recordings absent from PostgreSQL and without
│  custom_properties.processed == "true"
│  (processed=true + missing/invalid processed_at is repaired to now UTC and still skipped)
│  On first-run discovery, files created before the current local date are skipped by default;
│  the cutoff is configurable and does not apply to existing database rows.
│
├─ For each new recording:
│   ├─ disk.get_metadata(file_id) → name, datetime, owner, url
│   ├─ calendar.find_events(date, owner) → complete all-calendar snapshot for the window
│   ├─ matching.compatible(recording, events) → exact filename title + local start-time gate
│   ├─ matching.score(unique eligible event) → confidence, only after collision checks
│   └─ notion.search_cards(candidate_name, optional_parsed_contacts_email, recruiter) → cards[]
│
├─ Case A: unique eligible compatible event, no outside collision,
│  confidence >= threshold, AND len(cards) == 1
│   └─ Backend executes HAPPY PATH directly; no LLM call
│
└─ Case B: ambiguous (low confidence OR multiple cards OR no calendar event)
    └─ Backend persists a versioned manual review and sends a recruiter-only DM summary
        → Mila presents numbered bounded questions and accepts partial free-form answers;
          duplicate Notion titles retain page URLs and distinguishing fields, at minimum 📍 Spots
        → skill CLI submits one or more narrow actions with review token,
          expected version, DM binding, and idempotency key
        → Backend consumes the token once and executes HAPPY PATH or marks ignored

HAPPY PATH (Backend executes from scheduler or a validated review resolution):
    db.set_status("transfer_started")
    transfer.stream(disk_download_url → synology_path)   # chunk-by-chunk
    db.set_status("uploaded_to_synology")
    synology.create_share_link(path) → url
    db.set_status("synology_link_created")
    notion.update_card(card_id, fields={
        "General Interview Date": matched_calendar_event_date,
        "General Interview recording": url,
    })
    db.set_status("notion_updated")
    disk.mark_processed(file_id)  # PATCH processed=true + processed_at=<UTC ISO 8601>
    db.set_status("source_marked_processed")
    → Backend persists notification state and sends a completion/error recruiter DM

MANUAL SOURCE CLEANUP (never scheduled):
    recruiter requests cleanup of successfully processed recordings
    Backend returns a bounded preview of DB-proven eligible source files
    recruiter explicitly confirms the preview
    DELETE /disk/resources moves only those sources to Trash
    Backend records an idempotent per-file result
    permanent Trash purge is not exposed to Mila
```

The manual message-triggered scan is a first-class flow and remains available while the scheduler
is disabled. It uses the same Backend scan, idempotency, and status paths as a scheduled run.

The current code still contains the older `processed=true` plus seven-day scheduled cleanup model,
but that behavior is superseded for the target workflow and remains disabled. The Telemost folder
is reported to expire automatically after 90 days without consuming normal cloud quota. Exact
manual-cleanup eligibility begins immediately after Backend-proven success, but preview and
explicit confirmation remain mandatory. Permanent deletion remains destructive, unscheduled, and
unavailable to Mila.

## Interview detection logic

Agent must distinguish interview recordings from team meetings.
Confidence increases with each positive signal:

**Source of truth: Yandex Calendar via CalDAV. Matcher must work regardless of booking service.**

Every recruiter has exactly one explicit default calendar and zero or more explicitly selected
calendars. When selected calendars exist, they are the effective eligible set; otherwise only the
default is eligible. A validated legacy `caldav_calendar_url` remains a temporary default fallback.
Discovery never infers a default from server ordering or display names.

All discovered, available recruiter calendars are queried as one immutable snapshot. Events from
the effective set are match candidates; events from other calendars are collision/source evidence
only. Stale discovery or any collection query failure makes the snapshot incomplete and forbids an
automatic match.

Before confidence scoring, the Telemost filename must match one of these anchored shapes:
`YYYY-MM-DD_HHMMSS_<meeting title>.webm` or
`YYYY-MM-DD_HHMMSS_<meeting title>_audio_only.webm`. The timestamp is interpreted in
`RECORDING_FILENAME_TIMEZONE` (default: `Europe/Moscow`). `SCAN_LOCAL_TIMEZONE` separately defines
the recruiter's business date. Titles are normalized with Unicode NFKC, casefold, and
trimmed/collapsed Unicode whitespace only. Compatibility requires exact normalized
filename-title/SUMMARY equality and the existing time tolerance; no fuzzy, substring, token,
punctuation-dropping, transliteration, edit-distance, or LLM comparison is permitted.

Automatic matching requires exactly one compatible occurrence in the effective set, no compatible
occurrence outside it, and confidence at or above the threshold. Deduplication is limited to
`(calendar_id, UID, RECURRENCE-ID)`. Parser failure, no compatible event, unmonitored-only matches,
multiple compatible events, or monitored/unmonitored collisions go to `manual_review_required`
with a structured reason. Only confirmed matches persist calendar ID plus URL/display-name
snapshots; manual review stores bounded candidate diagnostics without raw ICS or credentials.

| Signal | Weight | Detection |
|--------|--------|-----------|
| Time overlap (parsed filename start within event window) | HIGH = 0.35 | Parsed local filename timestamp within `[dtstart - 15min, dtend + 15min]` |
| Booking source marker (`calink.ru`) | HIGH = 0.30 | Current effective.band booking flow; absence never blocks manual review |
| Candidate name extracted from SUMMARY `(...)` | MEDIUM/HIGH = 0.25 | `re.search(r'\(([^)]+)\)$', summary)` — first name guaranteed, last name may be absent |
| DESCRIPTION contains Telemost URL | LOW = 0.05 | Yandex adds it to every video event; diagnostic only |
| Interview keywords in SUMMARY | LOW = 0.05 | `собеседование\|интервью\|interview\|candidate` in SUMMARY |
| ATTENDEE email matches Notion card email | LOW = 0.05 | **STUBBED Phase 2** — always 0; resolved Phase 3 |

If total confidence < threshold → status `manual_review_required`, not `ignored`.
Only an explicit recruiter decision may end review. `ignored` means no transfer. A separately
confirmed non-interview route transfers to an allowed Synology destination, returns a link, and
completes without a Notion candidate update.

## File transfer

Streaming — no full file on agent server:
```
Яндекс.Диск (GET with stream=True)
  → httpx AsyncClient, chunk iteration
  → Synology FileStation upload (multipart, chunked)
```

Fallback if streaming blocked by Synology API:
- Download to `/tmp/<uuid>/<filename>`
- Upload from temp file
- Delete temp file immediately after Synology confirms (200 OK)
- If upload fails → delete temp, set status `failed`, log error

Temp file TTL guard: background task deletes any `/tmp/recording-agent/*` older than 4h.

## Mattermost interaction

Example intents in the ordinary recruiter DM:
```
"check new recordings"                 → trigger manual scan now
"show today's recording statuses"      → bounded status summary
"for Ivan choose the second card"      → answer one pending question
"save the team meeting in folder X"    → route a non-interview after safe destination resolution
"clean successfully processed files"  → preview a manual cleanup; never delete immediately
```

Disambiguation flow:
```
Mila → recruiter: one summary + numbered questions for every unresolved recording
Recruiter → Mila: answers all questions or a subset in ordinary free-form text
Mila → recruiter: confirms the interpreted subset and reports processing start
Backend → PostgreSQL: closes answered questions and leaves unanswered questions pending
Mila → recruiter: reports completion/error and later repeats only unanswered questions
```

Only the next eligible summary repeats an unanswered question. After that one reminder, Backend
keeps it durable but suppresses it from further automatic summaries until explicit reopening.

## Deployment

- **Runtime:** VDS (Yandex Cloud or bare metal)
- **Process management:** systemd or supervisor
- **Backend Tools Service:** uvicorn, port 8000, localhost only (not public)
- **OpenClaw Agent:** connects to Backend Tools Service as tool provider
- **PostgreSQL:** managed service or Docker container
- **Secrets:** Yandex Lockbox (production) / `.env` file (development)
- **Scheduler:** APScheduler inside Backend Tools Service (not OpenClaw)

### Mila deployment gates (confirmed 2026-07-22)

- Mila currently has no Docker, Docker Compose, Podman, or Nerdctl. Installing Docker/Compose,
  starting/enabling its services, and creating the isolated test stack are remote mutations that
  require an exact manifest and explicit approval.
- Installing the repository skill into
  `/root/.openclaw/workspace/skills/recording-agent/` is allowed only after that manifest approval;
  it initially calls a loopback test Backend.
- Mila agent invocation, the first real allowlisted Mattermost DM, the one actual scheduled 18:00
  test, and any production Notion/Yandex/Synology scope each require separate approvals.
- OpenClaw, its loopback Gateway bind, Sylvanas, and existing Mila skills/connections are not
  changed. Rollback preserves named volumes; `docker compose down -v` is forbidden.

## Test environment

Separate credentials + isolated data for every integration:
- Яндекс.Диск: test folder `/recordings-test/`
- Яндекс.Календарь: test calendar
- Notion: copied test database (same schema, dummy data)
- Synology: `/test-recordings/` folder
- Mattermost: allowlisted test recruiter DM only; no shared-channel fallback
