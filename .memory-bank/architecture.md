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
├─ Backend: disk.list_new() → recordings with no processed marker
│
├─ For each new recording:
│   ├─ disk.get_metadata(file_id) → name, datetime, owner, url
│   ├─ calendar.find_events(date, owner) → CalDAV events ±2h
│   ├─ matching.score(recording, events) → best_event + confidence
│   └─ notion.search_cards(candidate_name, date, recruiter) → cards[]
│
├─ Case A: confidence >= threshold AND len(cards) == 1
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
    disk.mark_processed(file_id)
    db.set_status("source_marked_processed")
    [optional] disk.delete(file_id) — per retention policy
    db.set_status("completed")
    → Backend notifies OpenClaw → OpenClaw sends recruiter confirmation
```

## Interview detection logic

Agent must distinguish interview recordings from team meetings.
Confidence increases with each positive signal:

| Signal | Weight | Detection |
|--------|--------|-----------|
| Recording owner is a known recruiter | high | `disk_owner_email` in `recruiter_config` |
| CalDAV event DESCRIPTION contains `calink.ru` URL | high | `re.search(r'https://calink\.ru/', description)` |
| CalDAV event DESCRIPTION contains Telemost URL | high | `re.search(r'https://telemost\.360\.yandex\.ru/', description)` |
| Candidate name extracted from SUMMARY `(...)`  | medium | `re.search(r'\(([^)]+)\)$', summary)` — first name guaranteed, last name may be absent |
| Event title contains interview keywords | medium | `собеседование\|интервью\|interview\|candidate` in SUMMARY |
| Recording in designated Disk folder | medium | path starts with `/Записи Телемоста/` (confirmed Q4) |
| ATTENDEE email matches Notion card email | low | unreliable — candidate may use personal email (Q6 closed) |

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
