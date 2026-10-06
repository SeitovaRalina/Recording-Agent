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

## Deployment path (decided 2026-09-30)

The canary stack from `deploy/README.md` («Canary and activation») is NOT viable: the server runs
out of resources and falls over when it runs next to production. Changes go straight to
production. During the E2E week this was done by hot-swapping the backend image in the prod
Compose stack (`docker compose up -d --no-deps backend` with a `canary-build` image) — that path
skips the `migrate` service, the DB backup and the release checks, so it is FORBIDDEN for any
change with an Alembic migration (multi-tenancy has one).

Use the regular path instead: PR → `main` → CI → Deploy. `deploy.sh` checks the single Alembic
head against `deploy/release-metadata.json`, stops the old backend, takes and validates a
`pg_dump` backup, runs `alembic upgrade head` via the `migrate` service and recovers the previous
image when the migration is declared compatible. For multi-tenancy: additive, nullable columns
(empty = global defaults) so the old app works on the new schema; update
`deploy/release-metadata.json` in the same PR (new target revision, `expand-contract`,
`previousApplicationCompatibleWithTargetSchema=true`); deploy at an agreed quiet time; verify the
release, migration, skill files, flags and logs afterwards.

## Multi-tenancy on production (2026-09-30)

The user chose a manual rollout before merging to `main`. Commit `a5cec1d` (branch pushed, then
squashed later the same day — see `backup/pre-squash-20260930` for the pre-squash hashes; the
deployed commit was `022c173` before the rewrite) was built by `canary-build` run 36662325389,
which produced image `…@sha256:9de7cec2…`. At 03:06 UTC the image was rolled out with the steps
from `deploy.sh`: stop backend → `pg_dump` backup
`/var/backups/recording-agent/20260930T030620Z-022c173…-manual.dump` (filename keeps the
pre-squash hash it was made under; verified) → `migrate`
(`20260729_1100 → 20260930_1000`) → backend on the new image (healthy, ~10 s downtime). Compose,
the skill and `current` still point to release `bd40428` (unchanged files). The PR → `main` → CI
deploy later reconciles the release dir; `upgrade head` will then be a no-op. Rollback: backend on
the old image `…@sha256:f1003091…` (schema compatible). Ralina's row: both new columns NULL; her
stored preflight hash matches and `require_notion_preflight` passes on the new code.

Lilia's Notion was verified read-only with the new code. Interviews DB: `Candidate` (relation →
Candidates) and `Vacancy` (relation). The test card resolves via `search_pages`: vacancy resolved,
the linked candidate card is readable, and its `Contacts` is empty. Onboarding flags:
`--notion-project-prop Vacancy --notion-project-prop-type relation --notion-contacts-mode relation
--notion-contacts-relation-prop Candidate --notion-contacts-target-prop Contacts
--synology-roots "/Recruiting-NE/2. Interviews"`. `.env.lilya` has
`LILYA_STORAGE_PREFIX=/home/Recruiting-E`, which contradicts the 29.09 decision; use
`/Recruiting-NE/2. Interviews` (confirmed by the user 2026-09-30).

Lilia's onboarding progress (2026-09-30):
- Done: the user merged her Yandex keys into `backend.env` (backup
  `backend.env.bak-20260930T034856Z`), and the backend was recreated on the new image. `configure`
  created an inactive row with the map above. `synology_base_folder` was fixed by hand to
  `/Recruiting-NE/2. Interviews`: configure stripped the leading `/`; the code is fixed in
  `46d9505` (pre-squash `43729df`), not deployed yet. Her calendar was discovered (`Мои события`,
  row `1192d414-…`), and
  `preflight` passed (Yandex, CalDAV, Mattermost, Synology root, Notion).
- Done by the user at 03:59 UTC (the auto-mode classifier blocks the agent from secret writes
  and account/allowlist changes): `activate`, her id in Mila's `allowFrom` (backup
  `/etc/openclaw/openclaw.json.bak-20260930T035910Z`), Gateway restart. Gateway is active, and
  Mattermost is connected as `@bot.recordings_saver`. The Gateway start-up warnings (EROFS
  last-good, loopback callbackUrl, empty plugins.allow, OpenRouter pricing 403) predate this change.
- Left: her first scan (daily run or a request to Mila in her DM), then PR → `main` → CI deploy.
  That deploy brings `46d9505` and moves the release dir; the migration is already applied.

## 18:00 digest opt-out (2026-10-01)

Lilia asked (via the lead's channel) not to get the automatic 18:00 Mattermost summary during
onboarding. No existing lever did only that: `active=false` stops the whole scan/transfer/Notion
pipeline, and clearing her Mattermost binding would also kill manual-review question delivery.
Added `recruiter_config.daily_digest_enabled` (migration `20261001_0900`, default `true`, no
backfill) and gated only the outbound summary inside `QuestionQueueService.build_digest`
(`send=False`): the scan, matching, transfer, Notion write-back and the settled-review
auto-complete/suppress hygiene keep running unchanged. `configure_recruiter.py set-digest --email
<email> --state enabled|disabled` flips it for an existing recruiter. Plan:
`swarm-report/recruiter-digest-toggle-plan.md`.

Rolled out the same way as multi-tenancy (manual canary-build + swap, not the canary stack — see
«Deployment path» above): commit `6aa8c52` built by `canary-build` run 36796806954 → image
`…@sha256:03755e6b…`. At 00:36 UTC: backup
`/var/backups/recording-agent/20261001T003641Z-6aa8c52…-manual.dump` (verified) → `migrate`
(`20260930_1000 → 20261001_0900`) → backend swapped (healthy). Then
`set-digest --email lilia.akentyeva@effective.band --state disabled` ran on the server:
`lilia.akentyeva@effective.band|t|f`, Ralina unchanged (`ralina.seitova@effective.band|t|t`).
Not yet done: PR → `main` → CI deploy to make this the regular release (same gap as the
multi-tenancy rollout).

## calink-matching + per-recruiter matching signals on production (2026-10-02)

Same manual rollout pattern again. Commit `956eba9` built by `canary-build` run 36960037539 →
image `…@sha256:b098454e…`. At 03:26 UTC: backup
`/var/backups/recording-agent/20261002T032648Z-956eba9…-manual.dump` (verified) → `migrate`
(`20261001_0900 → 20261002_1000`, adds `recruiter_config.matching_signals`) → backend swapped
(healthy). Both recruiters still active; `matching_signals` is NULL for both (pure architecture,
no override set for anyone — see section 3 and `swarm-report/matching-signals-config-plan.md`).
Carries, on top of the digest-toggle rollout already on prod: the calink booking-marker pool-entry
fix (`swarm-report/calink-matching-plan.md`) and the per-recruiter matching-signals override
column. Not yet done: PR → `main` → CI deploy (three features now ahead of `main`: multi-tenancy,
digest-toggle, calink-matching + matching-signals).

## PR #9 merged to main (2026-10-02)

`feature/lilia-onboarding` → `main` (multi-tenancy, digest-toggle, calink-matching + matching-signals)
merged via GitHub PR, which triggered the **regular CI → Deploy pipeline automatically** —
`release-manifest.json` on prod shows `commit: cdde9c2`, `status: deployed`, confirming the
`PR → main → CI → Deploy` path works end-to-end for this repo. The three-rollouts-ahead-of-`main`
gap from the two sections above is resolved as of this merge.

## Meeting-summary (item 4) on production (2026-10-06)

Full scope shipped (`/plan` → `/build` → `/review`, `swarm-report/meeting-summary-*.md`), on
`feature/meeting-summary` (not yet merged to `main` — manual rollout again, same reason as
before: canary-build, not the canary stack). New `RecordingStatus.AWAITING_SUMMARY_EMAIL` +
per-recruiter IMAP summary-email search (`app/services/summary_email.py`), two new recruiter-scoped
tool endpoints (`GET/POST .../summary-source`, `.../summary`), Notion toggle-list
(`«Конспект общего собеседования»`) + comment APIs, approval reuses `ManualReview`. Mila's skill
(`openclaw/skills/recording-agent/`) updated to fetch/summarize/submit — this skill is version-
controlled IN this repo, not external work (an earlier note in this session wrongly assumed
otherwise; corrected in `swarm-report/meeting-summary-plan.md`).

Rollout: commit `eaa72bd` built by `canary-build` run 37413267463 (first attempt, run 37412967579,
failed the secret scanner on a fake IMAP test password literal — fixed, re-pushed) → image
`…@sha256:a6766d26…`. Backup `/var/backups/recording-agent/20261006T042659Z-eaa72bd…-manual.dump`.

**Incident**: the first rollout attempt (piping the deploy script into `ssh … 'bash -s'` via
PowerShell stdin) silently died after the backup step — no error, no rollback trap fired (the
shell was killed by a dying SSH transport, not a command failure, so the `ERR` trap never ran).
Backend was left stopped for roughly 1–2 minutes before this was caught and the previous image
restarted manually. Root cause: passing multi-line scripts as piped stdin over this Windows
OpenSSH/PowerShell setup is unreliable; embedding the script inline with a base64-encoded
single-line `echo … | base64 -d | bash` command is not. Switched to that pattern for the retry,
which completed cleanly: fresh backup `…manual2.dump` → `migrate` (`20261002_1000 → 20261006_1000`)
→ backend swapped → healthy after 4 health-check polls → spot-checked Alembic head directly in
Postgres (`20261006_1000`). Skill deployed via `tests/e2e/lib/deploy_skill.py`; all 4 files'
sha256 verified to match the local repo exactly. Smoke-tested both new endpoints live
(404 on an unknown recording id — route and auth path both real, not a 404-route-not-found) and
confirmed both paths listed in `/openapi.json`; `/health` still 200.

Notion Connection comment permission — user confirmed already granted (same Connection, no new
grant needed).

## Meeting-summary live E2E on prod (2026-10-06) — 4 real bugs found and fixed

Ran the full live E2E on Ralina's own accounts, authorized explicitly ("Да, я разрешаю, делай
Live E2E на моих доступах"): seeded a demo interview via `tests.e2e.demo`, sent a real
"Конспект встречи: <candidate>" email to her own mailbox via SMTP, then drove real
`openclaw agent` turns against Mila (`tests/e2e/lib/mila.turn`, the same mechanism the R01-R15
E2E suite uses — real LLM, real tool calls, not simulated) asking her to scan, summarize, and
confirm. Each bug below was found live, fixed, re-deployed (canary-build + manual backup/
migrate-noop/swap), and re-verified in the same session:

1. **Cyrillic IMAP SEARCH crashes.** `imaplib` encodes every SEARCH argument through a
   hardcoded ASCII encoder regardless of CHARSET — a Cyrillic candidate name in
   `subject_contains` raised `UnicodeEncodeError` deep inside `imaplib`, swallowed by cron.py's
   broad `except Exception`, silently stuck at `NOT_FOUND` forever. Fix: never send
   `subject_contains` to SEARCH; filter fetched candidates by subject client-side
   (`app/tools/mail_imap.py`).
2. **Yandex rejects `HEADER "Message-ID"` search outright**, quoted or not, with
   `[UNAVAILABLE] SEARCH Backend error` — confirmed live, a real Yandex IMAP server limitation,
   not a quoting bug. `fetch_by_message_id` (used by `GET summary-source` to re-read the body)
   now re-runs the same server-accepted `SINCE` search and matches client-side instead.
3. **`list_active`/`build_digest`'s settled-recording filter hid and then would have
   auto-closed `summary_assessment_approval`/`summary_email_ambiguous` forever** — those two
   question types are created ON an already-`completed` recording by design, but the generic
   "settled recording = stale question" assumption (built for routing/candidate questions) did
   not carve them out. Without the fix, the recruiter's pending approval was invisible to
   `/tools/questions` and the next digest run would have silently discarded it with no comment
   ever posted. Fixed in `app/services/question_queue.py` (both call sites now exempt
   `DISCARD_ONLY_QUESTION_TYPES`).
4. **`recording.status.value` crashed with `AttributeError: 'str' object has no attribute
   'value'`** on a real request. Every other `ReviewService.mutate` branch calls
   `transition_to(...)` first, which reassigns `recording.status` to a real `RecordingStatus`
   enum instance in memory — masking that the ORM actually loads the column as a plain `str`.
   Our two new branches never call `transition_to` (status must stay unchanged by design), so
   this was the first branch to expose it. Fixed by using `str(recording.status)` instead of
   `.value` (correct for both cases).

None of these were caught by the unit test suite (545+ tests passing throughout) — each is a
real-infrastructure-only failure mode (real `imaplib` ASCII encoding, a real Yandex server
quirk, real DB-reload-vs-Python-construction attribute typing) that mocked tests structurally
cannot exercise. Regression tests were added for all four after the fact.

End-to-end proof, fully real: Mila found the email, summarized it with her own model strictly
from that email's text, wrote the toggle `«Конспект общего собеседования»` to the real Notion
card, created a real `ManualReview`, and — after an explicit recruiter confirmation — posted a
real Notion comment addressed to the hiring manager with a strengths/weaknesses breakdown and an
explicit move-forward recommendation. Verified by reading the live Notion page directly (not
trusting Mila's chat reply alone).

One non-bug friction point: a review's capability token has a 15-minute TTL (existing design,
shared by every question type) — debugging the above meant the first approval attempt's token
expired before it could be used. Not a defect; just means approvals must happen reasonably
soon after the question is created, same as any other recruiter question in this system.

**5th issue, found right after, by the user — not by this E2E run**: the whole matching/
extraction design above was built without ever having checked a real "Хранитель встреч
Телемоста" email. The user pointed at a real one in her own inbox (`keeper@telemost.yandex.ru`,
subject `Конспект встречи «Воркшоп "Бизнес-контекст в AI-разработке"» от 06.10.2026`) and it
immediately showed the design was structurally wrong, not just buggy:
- The subject's quoted title is the *meeting's own title*, not the candidate's name — subject/
  candidate-name substring matching could never have worked for a real interview.
- The body states the exact call link ("Ссылка на встречу: https://telemost.360.yandex.ru/j/
  ...") — the same link `app/services/matching.py` already parses into
  `Recording.calendar_telemost_url`. That is the correct, deterministic match key.
- The real conspectus (a "Задачи" section + numbered "Тема N" sections) lives in the inline
  HTML body; a separate text/plain part is the full call transcript sent as an attachment
  (filename set) — the user explicitly does not want that read, only what the email itself
  shows.

Fixed (commit `2b7d53e`, same manual rollout pattern, image `…@sha256:e8227503…`): search by
`FROM keeper@telemost.yandex.ru` + exact `calendar_telemost_url` match in the body (no event
link parsed → `UNAVAILABLE`, permanent, not retried); added HTML→text stripping for the inline
body. Not yet re-verified live with a real interview's email (today's live E2E used a
synthetic plain-text test email that happened to work by accident under the old, wrong design —
needs a fresh live pass once a real calink-booked interview produces a real Telemost summary
email, to confirm the subject-title assumption and the exact-link-match actually holds for that
case too).

Cleanup done for all three demo candidates (1220, 1228, 1608) created during this run: Notion
cards archived, Disk files trashed, Synology files deleted (1608 never reached Synology —
unrelated transient `SynologyAPIError: Synology API returned HTTP 200` blocked its folder
choice; settled via `stand settle` → `ignored`, not a meeting-summary bug), calendar events
deleted, and the three test emails removed from Ralina's real inbox via IMAP.

Still open: PR → `main` for `feature/meeting-summary` (same `main`-catch-up gap as the other
rollouts — resolved for the prior branch when PR #9 merged and auto-deployed; this one is still
ahead of `main`).

## Next steps (as of 2026-09-29 evening)

1. **Multi-tenancy first** (item 0). The 29.09 update to the lead already reports it as done, so
   it must land next: `/plan` → `/build` → tests → PR → regular deploy (see «Deployment path»; no canary stack). Per-recruiter Notion property
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

## 3. calink matching (scope) — corrected 2026-10-02 from Lilia's real Disk + Calendar data

**The 2026-09-29 note above (2-digit-date filename, `(Name)$` as the only signal) was wrong —
replaced by what the data actually shows.** Read `app/services/matching.py` before touching this;
`FILENAME_PATTERN` (`YYYY-MM-DD_HHMMSS_<title>.webm`) already matches every real filename seen,
no format-parsing work needed.

**Real calink-booked event (confirmed twice, 2026-09-21 and 2026-09-23 on her live calendar):**
```
SUMMARY: Собеседование в Effective c Лилией Акентьевой (Четова Дарья)
DESCRIPTION: Участник: Четова Дарья (dashachetova@gmail.com)
  https://telemost.360.yandex.ru/j/2973463676
  Детали встречи, отмена и перенос: https://calink.ru/liliya-akenteva/45min/45409?code=FAtvM1
```
Existing signals already score this ~1.0 once it reaches `_score_event`: `(Четова Дарья)` matches
`NAME_PATTERN`, `Собеседование` matches `INTERVIEW_PATTERN`, `calink.ru` matches `BOOKING_PATTERN`,
plus `time_overlap` and `has_telemost_url`. **Scoring is not the problem.**

**The actual bug:** the corresponding Disk recording is never titled like the event. Seen on her
real Disk: a generic Telemost-default title shared by many unrelated bookings
(`2026-09-21_144443_Ссылка для собеседования с Лилией Акентьевой_audio_only.mp3`) *and*, for the
same exact timestamp, a sibling `.webm` someone/something renamed to
`2026-09-21_144443_Чегова Дарья DM Junior с Лилией Акентьевой.webm` — neither string equals the
calendar summary `Собеседование в Effective c Лилией Акентьевой (Четова Дарья)`. The hard gate at
`matching.py:165` (`normalize_title(event.summary) == parsed.normalized_title`) rejects the event
before scoring ever runs → `NO_COMPATIBLE_EVENT`, even though a near-perfect signal (calink URL,
candidate email, unique Telemost room, correct time window) was sitting right there. This affects
every calink-booked interview, not just a "generic-title" subset: a calink event's calendar summary
and the Telemost recording's filename are independently generated strings that essentially never
match, whether the file keeps the Telemost default name or gets manually/automatically renamed
afterward.

**Separately confirmed, likely NOT a bug:** two real recordings
(`2026-09-30_110310_Консультация по инфраструктуре с Денисом Васильевым.webm`,
`…113314_…Михаилом Кононенко.webm`) exact-title-match a real calendar event (so the gate passes)
but score only ~0.35–0.40 (`time_overlap` + `has_telemost_url`) — below the 0.7 threshold — because
the title has no `(Name)$`, no `calink.ru`, and "Консультация" isn't an `INTERVIEW_PATTERN`
keyword. These are plausibly genuine 1:1 technical consultations, not calink-booked candidate
interviews; the recruiter can confirm via the existing manual-review question. Do not widen
`INTERVIEW_PATTERN`/`NAME_PATTERN` just to force these above threshold without her confirmation —
she has many non-candidate named 1:1 meetings on the same calendar (colleagues, vendors) that must
not start auto-matching.

**Third real pattern, found 2026-10-02, corrected 2026-10-02 after the user's follow-up:**
`Ссылка для собеседования с Лилией Акентьевой` is the Disk-side signal — Telemost's own default
recording title, seen on dozens of her real files. It is NOT a distinct calink calendar-event
template. The one real calendar event sharing that exact summary (2026-09-07T19:00) is read as an
ad-hoc/un-customized Telemost call whose generic room name was inherited into the calendar entry,
not a second calink product config. Net effect on matching is identical either way: when a
recording's default title happens to equal its calendar event's summary too, it passes the
exact-title gate (path 1, unchanged) but still can't auto-match — the description carries only a
bare Telemost link, no `calink.ru` URL, no candidate name/email — `BOOKING_PATTERN`/`NAME_PATTERN`
never fire, and there is no machine-readable candidate identity anywhere (not a code bug; nothing
here captures it). Separately, a real regex bug: `INTERVIEW_PATTERN` matches literal `собеседование`
(nominative), but this title has `собеседования` (genitive, "для собеседования") — not a substring
match, so `interview_keywords` never fires here even though a human reads it as obviously
interview-related. Cheap fix: match the stem `собеседован` instead of the full nominative word.
Worth fixing regardless, but won't by itself resolve candidate-identity for this case — recommend
telling Lilia to prefer her richer calink booking (the one with `Участник: Имя (email)` +
`calink.ru` URL, `/45min/` in current examples) for interviews, since only that one carries enough
signal to fully automate; recordings that stay on the generic Telemost title will keep landing as a
manual-review question either way, regardless of whether she renames the Disk file or leaves it
untouched. Confirmed 2026-10-02: Lilia will stop renaming/manually filing recordings to Synology
herself going forward — not required by the fix (the booking-marker path never depended on the
filename), but removes her current manual workaround once the fix deploys.

**Proposed direction (confirm in `/plan`, do not just implement):** stop treating title-equality as
a hard pre-filter. Build the compatible-event pool from time-window overlap alone (keep the
existing `eligible`/`unmonitored` split and the `NO_COMPATIBLE_EVENT` /
`UNMONITORED_ONLY` / `MULTIPLE_ELIGIBLE` / `UNMONITORED_COLLISION` safety checks — Q11's
"never silently auto-`ignored`" invariant is unaffected, ambiguity still goes to manual review).
Score every pool member with the existing signal set unchanged (it already works once an event is
reachable). Optionally add a new low-weight "filename title matches event summary" signal so the
already-working exact-match path (Anton, and Lilia's directly-scheduled named meetings) keeps its
current confidence or better. Must not regress Anton's current matching — his exact-match cases
stay single-eligible-event in the same time window either way. Needs: unit tests reproducing both
real cases above (calink event now matches; consultation stays manual-review), a regression test
for Anton's existing exact-match path, and confirmation that broadening the pool doesn't turn
unrelated recorded meetings into false auto-matches (scoring threshold is the existing safety net).

**Status: implemented 2026-10-02 (`app/services/matching.py`).** Shipped per `/plan`
`swarm-report/calink-matching-plan.md`, not the broader "drop title gate for all events" idea
above — the skeptic's safety hole (HIGH-1) stays closed. `score()` now builds `compatible` from one
loop with two independent entry conditions per event (title-exact-match OR
`BOOKING_PATTERN.search(event.description)`), both still requiring the ±15 min time window, both
excluding events with span ≥ 20 hours (all-day/multi-day blocks), deduped by
`(calendar_id, uid, recurrence_id)` as before. `INTERVIEW_PATTERN` now matches the stem
`собеседован` instead of the full nominative word, so it also catches genitive/other case forms.
`NAME_PATTERN`/`BOOKING_PATTERN`/`_score_event` weights/`confidence_threshold` unchanged.

Final confidence numbers from real prod data (`tests/test_matching.py`):
- Четова Дарья calink case (calink.ru in description, mismatched title) — **confidence 1.0**,
  `manual_review_required=False`, for both the generic Telemost-default filename and the
  manually-renamed filename.
- Денис Васильев / Михаил Кононенко consultation case (exact title match, no calink link) —
  **confidence 0.40**, `ManualReviewReason.LOW_CONFIDENCE` (not auto-matched, not
  `NO_COMPATIBLE_EVENT`). Weights not widened, per Out-of-scope.
- Generic-Telemost-title case ("Ссылка для собеседования с Лилией Акентьевой" — the Disk-side
  default recording title, not a distinct calink template — exact title match, no calink.ru URL)
  — **confidence 0.45** after the regex fix (`interview_keywords` now fires on the genitive form),
  still `LOW_CONFIDENCE`.
- Regression `test_reported_non_recruiting_title_cannot_match_other_event` (mismatched title, no
  booking marker) — unchanged, still `NO_COMPATIBLE_EVENT`; proves the booking-marker path did not
  reopen the safety hole.
- All-day/multi-day event alongside a real match — excluded from the pool by the ≥20h span guard;
  no spurious `MULTIPLE_ELIGIBLE`/`UNMONITORED_COLLISION`.

`tools/setup/rematch_calendar_events.py`: `title_mismatch` heuristic removed entirely (not
recomputed) — it is now the expected shape of a correct calink match, not a false-match signal.
`find_false_calendar_matches()` only flags `CALENDAR_EVENT_FOUND` rows whose `disk_filename` fails
to parse at all (`filename_invalid`); `--apply` only requeues those. `tests/test_rematch_calendar_events.py`
updated to the new semantics (a real calink-style mismatch and an exact-title match are both no
longer findings; only an unparseable filename is).

Full suite: `poetry run pytest -q` → 473 passed, 2 skipped. Scoped `pytest tests/test_matching.py
tests/test_scheduler.py tests/test_rematch_calendar_events.py -q` → 74 passed (required one
incidental fixture fix in `tests/test_scheduler.py::test_resume_regression_title_mismatch_persists_bounded_reason_only`:
its `ParsedVEVENT.description` literally contained a `calink.ru` URL used only as filler, which the
new booking-marker path would otherwise treat as a real marker and auto-match — changed to `""` to
keep testing the intended "no booking marker" regression, not a different scenario).

Out of scope, not touched: `NAME_PATTERN`/`INTERVIEW_PATTERN` keyword widening or weight changes to
push Денис/Михаил above threshold; `FILENAME_PATTERN`; `confidence_threshold`;
`UNMONITORED_COLLISION` multi-calendar behavior for Anton/future multi-calendar recruiters.

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
