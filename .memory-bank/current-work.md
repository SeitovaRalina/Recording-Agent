# Current work — week of 2026-09-28

Source of truth for in-flight scope. Update it when a task starts, finishes or changes. A new
agent session should read this file right after `index.md`.

## State on 2026-09-29

- PR #8 (`HOTFIX - Prod E2E Verification & Agent Fixes`) is merged into `main` (`bd40428`) and
  deployed by the regular CI → Deploy workflow (run 36097148219, success). Verified 2026-09-29:
  backend runs from `/opt/recording-agent/releases/bd40428…` (healthy; the image has no revision
  label, the release dir is the evidence); SKILL.md, scripts/recording_agent.py and both
  references equal `main`; the routing dispatcher equals `deploy/scripts/`; backend, Postgres and
  notion-proxy are healthy; no errors in backend logs since the deploy; the daily scan + 18:00
  digest ran every day (calendar snapshot 2026-09-28 12:00 UTC, digests 25–28 sent). The only
  log noise is the routing dispatcher's expected 409 every 2 min (autonomous routing disabled).
- Prod flags: `SCHEDULER_ENABLED=true`, `NOTION_WRITES_ENABLED=true`,
  `MATTERMOST_DELIVERY_ENABLED=true`, `AUTONOMOUS_ROUTING_ENABLED=false`,
  `YANDEX_SOURCE_MUTATION_ENABLED=false`, `CONFIDENCE_THRESHOLD=0.7`.
- One active recruiter: Ralina (Anton's Notion interviews database). E2E run `2026-09-24_1`
  reports live in `tests/e2e/reports/2026-09-24_1/`; its test data still awaits an approved
  cleanup (`cleanup.json`), plus the demo candidate `E2E Демо Кандидатова 1451`.
- SSH to the server needs the passphrase-protected key `~/.ssh/access_K0DE` loaded into the
  Windows ssh-agent (the user does `ssh-add`; never handle the passphrase).

## Next steps (as of 2026-09-29 evening)

1. **Multi-tenancy first** (item 0). The 29.09 update to the lead already reports it as done, so
   it must land next: `/plan` → `/build` → tests → canary deploy. Per-recruiter Notion property
   mapping (name, date, recording, project/vacancy relation + its type, optional contacts) and
   per-recruiter Synology interview roots, stored per recruiter via an Alembic migration, global
   settings as defaults, schema preflight per recruiter. Lilia: `Vacancy` relation, no contacts,
   root `/Recruiting-NE/2. Interviews`. Decide Ralina's roots (today the `/home/…` test copy).
2. **Meeting summary (item 4)** — announced to the lead as today's work. Start with `/plan`; the
   open decisions are listed in section 4 above.
3. **Lilia onboarding** (credentials complete since 2026-09-30):
   `backend.env` (server copy of the refresh token) → `configure` → `preflight` → `activate` →
   `allowFrom` + Gateway restart → first scan. Every prod change needs the user's confirmation.
4. **calink matching (item 3)**: calendar access works now — analyse her events first.

Update 2026-09-30: the new CalDAV app password works (calendar «Мои события»,
`/calendars/<email>/events-37127417/`, 205 events in the last 14 days + next 3). The candidates DB
is `1bfc8889-e4c8-8175-8f1f-c3064d8d6eba` «Candidates [Recruiting-NB]» (connection added by Lilia on
2026-09-30, actively edited). Fields: `Name` (title), `Contacts` (rich_text), `Interviews`
(relation → «Interviews [Recruiting-NE]»), `Vacancy` (rollup), `CV` (files), `Last Name`
(formula) and others. Contacts therefore live in the candidates DB, not in the interviews DB —
the per-recruiter mapping must allow a contacts field reached through a relation. The older
«Кандидаты» DB `…81ae…` is a stale copy (last edit 2025-03-23); ignore it. Nothing is waiting
on Lilia any more; onboarding is blocked only by multi-tenancy.

Writing rules for texts to colleagues: `docs/internal-update-style.md` (impersonal form, «Вы»,
no hand-wrapped lines). Uncommitted local edit by the user: `presentation/04-recruiter-onboarding.ru.md`
— leave it alone unless asked.

## Week plan (manager view; all items are in scope)

0. Multi-tenancy (added 2026-09-29, prerequisite for item 1): every recruiter gets their own
   Notion property mapping (name, date, recording, project/vacancy relation, optional contacts)
   and their own Synology interview roots, stored per recruiter (Alembic migration), with the
   schema preflight per recruiter. Global settings stay as defaults.


1. Onboard Lilia (production path) and verify the new-recruiter flow — 2 h.
2. Analyse Lilia's real Disk recordings and calendar events (calink file names, event title and
   description, where the broadcast link is, what ties a file to its meeting) — 3 h.
3. New recording ↔ meeting matching for calink recordings — 5–6 h.
4. Meeting summary from e-mail into the Notion card + assessment comment — 8–9 h.
5. Canary deploy, E2E on Lilia's real data, review — 3 h.

## 1. Lilia onboarding — PRODUCTION data, be careful

- Recruiter: `lilia.akentyeva@effective.band`, timezone `Asia/Omsk`, calendar «Мои события»,
  Mattermost user id `nem4cfr4zigg7f1smjj3ygwoky` (found by e-mail on 2026-09-29; the id she
  sent first does not exist), DM channel with the bot `44gt6g9mntypz8fbaejyipqwih` (exists, she
  wrote to the bot on 2026-09-25).
- Local secrets file `.env.lilya` (git-ignored) holds her Yandex refresh token and CalDAV app
  password; a copy of the token is on the server at `/root/lilya-yandex-refresh-token`.
- Notion: interviews database `1bfc8889e4c8816e8914e2413896830b` «Interviews [Recruiting-NE]»,
  test card `3d5c8889e4c880c0aed5dcdb5952081e`. Connection «Agent: Mila (Recordings Saver)»
  sees the database, the card and the related «Vacancies [Recruiting-NB]» database.
- Order (user requirement): first verify visibility read-only — interviews DB, every related DB,
  calendar events, Disk folder, Synology roots — then change config, then analyse data.
- Steps: merge her token/password into the JSON maps `YANDEX_REFRESH_TOKENS` and
  `YANDEX_CALDAV_PASSWORDS` in `/etc/recording-agent/backend.env` without touching other entries
  → restart backend → `tools/setup/configure_recruiter.py configure` → `preflight` →
  `activate` → add her Mattermost id to Mila's `allowFrom` (`/etc/openclaw/openclaw.json`,
  `dmPolicy=allowlist`; Gateway restart needs approval) → her first scan.
- Every prod mutation (backend.env, recruiter row, activation, Gateway restart) needs the user's
  explicit confirmation.

### Visibility check 2026-09-29 (read-only)

- Post-merge server: backend `releases/bd40428…`, healthy; workspace SKILL.md equals `main`;
  dispatcher unchanged; flags unchanged.
- Yandex OAuth + Disk: OK. `Записи Телемоста` holds 90 files. Yandex ROTATES the refresh token
  on every refresh: the only current copy is `/root/lilya-yandex-refresh-token` on the server
  (the value in `.env.lilya` is stale). Use the server copy when writing `backend.env`.
- CalDAV: 401 for every login/URL variant (rechecked on the user's request, still 401,
  `WWW-Authenticate: Basic realm="CalDAV"`). The value (32 hex chars) does not look like a Yandex
  app password (16 lowercase letters). BLOCKER: a new «Календарь (CalDAV)» app password is needed,
  or the Yandex 360 org admin has app passwords / CalDAV disabled.
- Notion: interviews DB, Vacancies DB and the test card are visible to the connection.
- Synology: `/Recruiting-NE/2. Interviews`, `/Recruiting-E/2. Interviews external`,
  `/Recruiting-E/3. Interviews internal` all exist, and so do the `/home/Recruiting-…` paths the
  backend uses today. OPEN: whether `/home/Recruiting-…` is the same share or the service
  account's private home — if private, recruiters do not see files filed there (Ralina's real
  recordings were filed under `/home/…`).
- Recording names seen on her Disk (input for item 3): `…_Собеседование с <Имя Фамилия>.webm`,
  `…_Ссылка для собеседования с Лилией Акентьевой.webm`, `…_<Фамилия Имя>_<роль> с Лилией
  Акентьевой.webm`, `…_Созвон с <Имя Фамилия> .webm`; each has an `_audio_only.mp3` twin that
  must be ignored.

### Blocker: Notion properties are global, Lilia's schema differs

`app/config.py` has one property mapping for the whole backend (`NOTION_NAME_PROP`,
`NOTION_DATE_PROP`, `NOTION_RECORDING_PROP`, `NOTION_CONTACTS_PROP`, `NOTION_PROJECT_PROP`,
`NOTION_PROJECT_PROP_TYPE`). Anton's database uses `📍 Spots` (relation) and `TBD` (contacts
formula). Lilia's database (inspected 2026-09-29):

| Setting | Anton | Lilia |
|---|---|---|
| name | `Name` (title) | `Name` (title) |
| interview date | `General Interview Date` (date) | same |
| recording | `General Interview recording` (files) | same |
| project / Spot | `📍 Spots` (relation) | `Vacancy` (relation → «Vacancies [Recruiting-NB]», title `Название вакансии`) |
| contacts | `TBD` (formula) | none |

Needed before `configure`: a per-recruiter Notion property mapping (e.g. a JSON column on
`recruiter_config`, defaulting to the global settings), an optional contacts property, and the
schema preflight/hash per recruiter. Alembic migration required. Also open: the user said the
interviews DB links to a candidates DB, but no such relation exists in the schema — confirm.

### Decided 2026-09-29: Synology roots and `/home`

`/home/Recruiting-NE` and `/home/Recruiting-E` are a TEST COPY of the production share structure
used during testing. Production data lives in `/Recruiting-NE` and `/Recruiting-E` (no `/home`).
Lilia's root: `/Recruiting-NE/2. Interviews`. Today `SYNOLOGY_INTERVIEW_ROOTS` still points at
the `/home/…` copy for everyone, so Ralina's recordings (incl. the real «Дмитрий Голуб» one) were
filed into the test copy — revisit Ralina's roots together with multi-tenancy.

### Old note: Lilia's Synology roots (superseded by the decision above)

She interviews non-engineers. The user wants prod paths without the `/home` prefix (the current
roots `/home/Recruiting-…` are the service account's home view). To confirm with a read-only
DSM listing: whether her roots are `/Recruiting-NE/2. Interviews` (non-engineering) or
`/Recruiting-E/2. Interviews external` + `/Recruiting-E/3. Interviews internal` — the user's
notes contradict each other. `SYNOLOGY_INTERVIEW_ROOTS` is global today, so per-recruiter roots
are another code change.

## 3. calink matching (scope)

calink recordings are named like `25_09_11_10_Собеседование_с_Лилей.webm` (date/time prefix,
generic meeting title, no candidate). The calendar event title ends with the first name only,
e.g. `(Иван)`; the description carries a broadcast link unique per meeting. The current title
gate (`app/services/matching.py`: exact normalized title + ±15 min window) never matches these.
Work: parse the new file-name format, a compatibility gate on time + meeting title with the
broadcast link as the unique key, candidate lookup by first name (several namesakes → narrow by
vacancy, else ask the recruiter with all card links), re-weight signals, keep old names working,
tests.

## 4. Meeting summary (scope)

After an interview a meeting summary arrives by e-mail. The agent must find it, summarise it,
put the summary into the candidate's Notion card in a dedicated toggle list, and add a comment
with an assessment (passes / recommend or not). Decisions pending: mail access (new OAuth scope,
recruiters re-consent), where the LLM runs (Mila vs. a backend model; the backend has no LLM
today), assessment labelled as the agent's and published only after recruiter confirmation,
Notion connection needs the comment capability.

## Known agent issues (for slides and backlog)

Offers a Disk-cleanup preview instead of refusing an unavailable operation (R13-D4, 2 of 3
runs); mis-retells long status lists; no open-question reminder after an off-topic message (the
off-topic turn loads another skill); extra read-only calls.
