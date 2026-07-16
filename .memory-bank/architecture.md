# Architecture

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
│    openclaw.py     push events → OpenClaw Agent          │
└───┬────────┬────────┬────────┬────────┬──────────────────┘
    │        │        │        │        │
  Яндекс  Яндекс  Notion  Synology  Mattermost
  Диск   Кален.            ↕ (bot)      ↕ (bot)
    │
  PostgreSQL                         OpenClaw
  (recording states + metadata)   Recording Agent
         ↑                              │
         └──── event push (Backend) ────┘
                                        │
                                   tool calls
                                   back to Backend
```

**Key principle:**
- Backend = scheduler + executor. Scans Disk, owns PostgreSQL, runs all integrations.
- OpenClaw = reasoning agent. Wakes only when Backend pushes an event (new recording / manual review). Forms decision or recruiter message. Calls Backend tools as needed.
- OpenClaw is always running. Backend does NOT start OpenClaw — it sends events to the already-running process.

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
│   └─ notion.search_cards(candidate_name, date, recruiter) → cards[]
│
├─ Case A: unique eligible compatible event, no outside collision,
│  confidence >= threshold, AND len(cards) == 1
│   └─ Backend pushes event to OpenClaw:
│       {"type": "recording_ready", "recording": ..., "event": ..., "card": ...}
│       → OpenClaw verifies, calls Backend tool: confirm_and_transfer()
│       → HAPPY PATH below
│
└─ Case B: ambiguous (low confidence OR multiple cards OR no calendar event)
    └─ Backend pushes event to OpenClaw:
        {"type": "manual_review_required", "recording": ..., "candidates": [...]}
        → OpenClaw composes recruiter message in Mattermost
        → db.set_status("manual_review_required")
        → awaits recruiter reply
        → recruiter replies → Mattermost webhook → Backend → push event to OpenClaw
        → OpenClaw parses reply (NLU) → calls confirm_and_transfer()
        → HAPPY PATH below

HAPPY PATH (Backend executes on OpenClaw tool call):
    db.set_status("transfer_started")
    transfer.stream(disk_download_url → synology_path)   # chunk-by-chunk
    db.set_status("uploaded_to_synology")
    synology.create_share_link(path) → url
    db.set_status("synology_link_created")
    notion.update_card(card_id, field="General Interview recording", value=url)
    db.set_status("notion_updated")
    disk.mark_processed(file_id)  # PATCH processed=true + processed_at=<UTC ISO 8601>
    db.set_status("source_marked_processed")
    → Backend notifies OpenClaw → OpenClaw sends recruiter confirmation

DAILY RETENTION CRON (soft delete only; separate from the happy path):
    disk.delete_expired() selects files with processed=true and processed_at >= 7 days old
    missing/invalid processed_at is repaired to now UTC; source is not deleted in that run
    DELETE /disk/resources moves each eligible source to Trash

SEPARATE PERMANENT PURGE (never scheduled):
    operator gives fresh per-run PermanentDeleteApproval(approved_by, approved_at, nonce)
    identity/unique nonce must be non-empty; timestamp must be aware and <=5 minutes old
    validate with trusted injected UTC clock; caller cannot provide now
    consume nonce before any request; approval cannot be reused after success/failure
    disk.purge_expired_from_trash() enumerates current Trash resources
    validate origin_path, processed markers, and >=7-day age
    DELETE /disk/trash/resources uses each actual trash:/... path
    db.set_status("source_deleted") after both deletion stages succeed
    db.set_status("completed")
```

The source file remains in its original folder during the seven-day retention window. The
scanner skips it by reading its custom properties. The cron job cannot permanently delete.
Permanent deletion is destructive and must never run without the explicit approval required by
`AGENTS.md`; approval is valid only for one invocation and cannot be stored in configuration.
If a purge partially fails, a later run requires newly issued approval with a new nonce and
resumes by enumerating the
remaining real Trash resources rather than reconstructing paths from their original locations.

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
Only explicit recruiter "ignore" command → status `ignored`.

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

Commands (Bot receives in channel or DM):
```
/recordings check         → trigger manual scan now
/recordings pending       → list recordings in manual_review_required
/recordings status        → summary of all statuses
/recordings retry <id>    → re-process a failed recording
```

Disambiguation flow:
```
Bot → recruiter: "Found recording X. Multiple cards match: [1] … [2] … Reply with number, Notion URL, or 'ignore'."
Recruiter → Bot: "2" | "прикрепи к Project A" | "https://notion.so/..." | "ignore"
Bot parses free text via OpenClaw NLU → resumes processing
```

## Deployment

- **Runtime:** VDS (Yandex Cloud or bare metal)
- **Process management:** systemd or supervisor
- **Backend Tools Service:** uvicorn, port 8000, localhost only (not public)
- **OpenClaw Agent:** connects to Backend Tools Service as tool provider
- **PostgreSQL:** managed service or Docker container
- **Secrets:** Yandex Lockbox (production) / `.env` file (development)
- **Scheduler:** APScheduler inside Backend Tools Service (not OpenClaw)

## Test environment

Separate credentials + isolated data for every integration:
- Яндекс.Диск: test folder `/recordings-test/`
- Яндекс.Календарь: test calendar
- Notion: copied test database (same schema, dummy data)
- Synology: `/test-recordings/` folder
- Mattermost: `#recordings-test` channel or separate bot
