# Memory Bank — Recording Agent

> Source of truth. `/plan`, `/build`, `/review`, `/debug` agents read this FIRST before doing anything.
> If something here contradicts the code, surface it — don't invent facts.

## Project

- **What:** OpenClaw agent that automates interview recording processing. Detects new recordings on Яндекс.Диск, matches them to calendar events + Notion candidate cards, transfers to Synology, updates Notion with Synology link, notifies recruiter via Mattermost.
- **Goal:** Zero-touch archival. Recruiter conducts interview → recording appears in Synology + Notion card within 24h (or immediately on `/recordings check`).
- **Stack:** Python 3.13 + FastAPI · PostgreSQL · OpenClaw (agent framework) · httpx · SQLAlchemy 2.0 async + asyncpg · Alembic · uv · Pydantic v2

## Integrations

| Service | Protocol | Purpose |
|---------|----------|---------|
| Яндекс.Диск | REST API `cloud-api.yandex.net/v1/disk` | Source of recordings |
| Яндекс.Календарь | CalDAV `caldav.yandex.ru` | Match recording → interview event |
| Notion | REST API `api.notion.com` | Candidate cards — update with Synology link |
| Synology File Station | REST API `SYNO.FileStation.*` | Final video storage |
| Mattermost | Bot API | Recruiter notifications + manual disambiguation |

## Notion topology (confirmed)

**Scenario A** — single shared workspace, per-recruiter databases.
- One `NOTION_TOKEN` (Internal Integration)
- Per-recruiter `database_id` mapping in config
- Known databases: Anton's Interviews DB, Lili's (TBD)
- Key fields in Interviews DB: `Name`, `General Interview Date`, `General Interview recording`, `TBD` (contacts formula), `Spots` (relation)

## Recording statuses (PostgreSQL state machine)

`found` → `calendar_event_found` → `candidate_matched` → `transfer_started`
→ `uploaded_to_synology` → `synology_link_created` → `notion_updated`
→ `source_marked_processed` → `source_deleted` → `completed`

Branches: `manual_review_required` (human-in-the-loop), `ignored` (not an interview), `failed`

## Where to look

- Architecture + data flows → `.memory-bank/architecture.md`
- Auth setup for all services → `.memory-bank/auth-flow.md`
- Key decisions → `.memory-bank/decisions.md`
- Open questions (fill before coding) → `.memory-bank/open-questions.md`
- Original requirements → `TOR.md`
- API contracts → `docs/api-contracts/`
- Status machine → `docs/status-machine.md`
- Data model → `docs/data-model.md`
