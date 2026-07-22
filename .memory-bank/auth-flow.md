# Auth Flow

All services use token-based auth. Operator sets up once. Agent runs autonomously after.

## MVP onboarding limitation

There is currently no self-service recruiter onboarding or implemented OAuth callback flow. Before
a recruiter can be enabled, an operator must provision that recruiter's Yandex refresh token and
CalDAV app password in the Backend secret environment, connect the Notion integration to the
correct database, and create an inactive `recruiter_config` row. Mila/Sylvanas may guide and
validate this process, but they cannot grant access or invent credentials.

The local development `.env` is not copied automatically to Mila/Sylvanas. Each Backend deployment
gets its own protected service environment. OpenClaw skills never receive Yandex, Notion, MinIO, or
Mattermost integration credentials. Do not run two schedulers with the same recruiter credentials
without an explicit active/standby ownership mechanism.

## Setup checklist (operator, one-time)

- [ ] Яндекс OAuth app registered, refresh token obtained
- [ ] Notion Internal Integration created, added to all recruiter DBs
- [ ] Synology API Key created
- [ ] Mattermost Bot account created, token issued
- [ ] All secrets stored in Lockbox / `.env`

---

## 1. Яндекс OAuth (Диск + Календарь)

**Method:** Authorization Code + refresh token (no PKCE — server app with `client_secret`)

**Scopes needed:**
- `cloud_api:disk.read` — list/download recordings
- `cloud_api:disk.write` — mark processed / delete
- `calendar:read` — read CalDAV events (verify exact scope name with Яндекс docs)

**One-time setup (per recruiter):**
```
1. oauth.yandex.ru/client → Create app → get client_id + client_secret
2. For EACH recruiter (Anton, Lili, etc.):
   Complete Yandex Authorization Code consent for that account.
   → recruiter opens the authorization URL and clicks "Разрешить"
   → operator exchanges the returned code for access_token + refresh_token
   → create a separate CalDAV app password for the same account
3. Store in secrets:
   YANDEX_CLIENT_ID=...
   YANDEX_CLIENT_SECRET=...
   # Per-recruiter tokens (JSON map):
   YANDEX_REFRESH_TOKENS={"anton@effective.band": "...", "lili@effective.band": "..."}
```

`tools/setup/yandex_oauth.py` is described by earlier design notes but is not present in the
repository. Until a setup helper or callback service is implemented, this is a manual operator
step. Never ask a recruiter to paste tokens or passwords into Mattermost.

**Why per-recruiter:** Each recruiter has their own Яндекс.Диск under corporate @effective.band org. No org-admin API for cross-user Disk access at MVP.

**Runtime token refresh:**
```python
# POST https://oauth.yandex.ru/token
# Body: grant_type=refresh_token&refresh_token=...&client_id=...&client_secret=...
# Returns: {"access_token": "...", "expires_in": 3600}
# Cache access_token in memory. On 401 → refresh → retry once.
```

**Important:** Яндекс requires `client_secret` for refresh (unlike PKCE flows).
Refresh token does not expire unless revoked.

---

## 2. Notion — Internal Integration

**Method:** Static bearer token (no expiry)

**One-time setup:**
```
1. notion.so/my-integrations → New integration
   → Name: "Recording Agent"
   → Capabilities: Read content, Update content
   → Get token: secret_xxxx...
2. In Notion, for each recruiter's database:
   → Open database → ··· menu → Connections → Add connection → "Recording Agent"
3. Store in secrets:
   NOTION_TOKEN=secret_xxxx...
```

**Per-recruiter database mapping (PostgreSQL config, not secrets):**
```python
# recruiter_config row
notion_database_id = "abc123-..."  # original database ID
```

The operator supplies a Notion database/page URL or original database ID. An operator-only
bootstrap command may resolve a directly referenced database, or exactly one child database from a
provided page, but it must display the title and compatible schema for explicit confirmation. It
must never choose from workspace-wide search results. Store the confirmed original database ID in
`recruiter_config.notion_database_id`; do not configure or persist data-source IDs.

Create the recruiter row with `active=false`. Enable it only after Yandex credentials are present,
calendar discovery/default selection succeeds, Notion sharing/schema validation succeeds, and the
Mattermost user mapping is confirmed.

**Runtime discovery and usage:**
```python
headers = {
    "Authorization": f"Bearer {settings.notion_token}",
    "Notion-Version": "2026-03-11",
    "Content-Type": "application/json",
}
```

1. `GET /v1/databases/{database_id}` returns the database's `data_sources` descriptors.
2. `GET /v1/data_sources/{data_source_id}` returns each source schema.
3. Select exactly one source whose configured name/date/recording properties have types
   `title`/`date`/`files`. Zero matches or multiple matches fail closed.
4. Candidate lookup uses `POST /v1/data_sources/{data_source_id}/query`.
5. Recording URL update uses `PATCH /v1/pages/{page_id}`.

The integration must be connected directly to the original database. Sharing a parent page or a
linked view is insufficient. A `403` or resource `404` blocks that recruiter until the database is
shared and its original ID is verified.

**Pre-deploy read-only probe:** First copy each recruiter database to a test location and connect
the integration to the copy. Use only database retrieval and data-source retrieval to verify that
exactly one schema has the configured `title`, `date`, and `files` properties. Do not query pages or
write recording URLs during the probe. Repeat discovery against production only after explicit
sharing; block enablement on sharing, schema, or ambiguity failure.

---

## 3. Synology File Station

**Method:** API Key (DSM 7.0+) — preferred. Session SID (DSM <7.0) — fallback.

**One-time setup (DSM 7.0+):**
```
1. DSM → Control Panel → File Services → Advanced → Enable WebDAV (optional)
2. DSM → Control Panel → API Portal → API Key → Create
   → App: "Recording Agent"
   → Permissions: FileStation (read, write, delete, share link)
   → Get key
3. Store in secrets:
   SYNOLOGY_BASE_URL=http://synology.local:5000
   SYNOLOGY_API_KEY=xxx...
```

**Usage:**
```python
# GET /webapi/entry.cgi?api=SYNO.FileStation.List&version=2&method=list&folder_path=/...
# Header: X-Syno-Token: {SYNOLOGY_API_KEY}
# OR query param: _sid={SYNOLOGY_API_KEY}
```

**Fallback (DSM <7.0 — session login):**
```python
# POST /webapi/auth.cgi?api=SYNO.API.Auth&version=3&method=login
# &account=SYNOLOGY_USER&passwd=SYNOLOGY_PASS&session=FileStation&format=sid
# Returns SID, store in memory, re-auth on 403
# Secrets needed: SYNOLOGY_USER, SYNOLOGY_PASS
```

---

## 4. Mattermost Bot

**Method:** Bot token (static, no expiry unless regenerated)

**One-time setup:**
```
1. Mattermost → System Console → Integrations → Bot Accounts → Add bot
   → Username: recording-agent
   → Role: Member
   → Get token
2. Confirm the bot can resolve the allowlisted recruiter and open a direct-message channel.
3. Store in secrets:
   MATTERMOST_URL=https://mm.company.com
   MATTERMOST_BOT_TOKEN=xxx...
   MATTERMOST_BOT_USER_ID=xxx...
```

**Usage:**
```python
headers = {"Authorization": f"Bearer {settings.mattermost_bot_token}"}
# POST /api/v4/channels/direct → resolve/open recruiter DM
# POST /api/v4/posts           → send summary, questions, reminders, and results
# Preferred: Mattermost webhooks / WebSocket for real-time replies
```

Recording Agent uses the recruiter's ordinary Mila DM without mandatory threads and without a
shared-channel fallback. Backend persists the DM channel and pending-question state. The bot token
is required for proactive scheduled summaries, reminders, processing-start feedback, and
completion/error messages. OpenClaw never receives or prints the bot token.

The initial question may be presented once and repeated only in the next eligible 18:00
recruiter-local summary. Backend then suppresses it from later automatic summaries unless an
explicit audited reopen occurs. Manual message-triggered scan and status requests do not require
the scheduler to be enabled.

## Mila production-host approval boundary

As of the 2026-07-22 read-only inventory, Mila has no Docker/Compose runtime. Before any remote
mutation, repeat the targeted inventory and present exact packages, paths, files, services,
containers, loopback ports, commands, reload/restart operations, health checks, and rollback
commands. Obtain approval for that exact manifest before installing Docker, starting services,
deploying the isolated test stack, or installing the workspace skill.

The following approvals remain separate and are not implied by deployment approval:

- invoking the Mila agent for forward/canary prompts;
- sending the first real DM to the allowlisted Mattermost user;
- enabling the one actual Backend-owned scheduled test at 18:00 recruiter-local;
- any production Notion write, Yandex mutation, or Synology operation;
- promotion from test Backend/test Notion/MinIO scope to production scope.

Mattermost values are read from Mila's existing configuration only through an approved safe
operator mechanism and injected into the Backend service environment or protected credential
file. Never print them, copy them into the repository/workspace skill, dump the full OpenClaw
configuration, or restart the Gateway without explicit approval.

---

## Secrets reference

| Env var | Service | Type | Expiry |
|---------|---------|------|--------|
| `YANDEX_CLIENT_ID` | Yandex OAuth | App credential | Never |
| `YANDEX_CLIENT_SECRET` | Yandex OAuth | App credential | Never |
| `YANDEX_REFRESH_TOKENS` | Yandex OAuth | Per-recruiter JSON map `{email: token}` | Never (unless revoked) |
| `NOTION_TOKEN` | Notion | Integration token | Never (unless revoked) |
| `SYNOLOGY_BASE_URL` | Synology | Config | — |
| `SYNOLOGY_API_KEY` | Synology | API key | Never (unless deleted) |
| `MATTERMOST_URL` | Mattermost | Config | — |
| `MATTERMOST_BOT_TOKEN` | Mattermost | Bot token | Never (unless regenerated) |
| `MATTERMOST_BOT_USER_ID` | Mattermost | Config | — |
| `DATABASE_URL` | PostgreSQL | Connection string | — |

All secrets injected via `pydantic-settings` (`BaseSettings`). `SecretStr` for sensitive fields.
Never in code, logs, or git.
