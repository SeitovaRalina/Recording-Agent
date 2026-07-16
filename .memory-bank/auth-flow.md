# Auth Flow

All services use token-based auth. Operator sets up once. Agent runs autonomously after.

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
   Run: python tools/setup/yandex_oauth.py --recruiter anton@effective.band
   → prints auth URL
   → recruiter opens URL in browser, clicks "Разрешить"
   → redirect to callback with ?code=...
   → script exchanges code for access_token + refresh_token
   → prints refresh_token for that recruiter
3. Store in secrets:
   YANDEX_CLIENT_ID=...
   YANDEX_CLIENT_SECRET=...
   # Per-recruiter tokens (JSON map):
   YANDEX_REFRESH_TOKENS={"anton@effective.band": "...", "lili@effective.band": "..."}
```

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

**Per-recruiter database mapping (config, not secrets):**
```python
# config.py or env
RECRUITER_NOTION_DB_IDS: dict[str, str] = {
    "anton@company.com": "abc123-...",   # Anton's Interviews DB
    "lili@company.com":  "def456-...",   # Lili's DB — TBD
}
```

Values must be original database IDs. Do not configure or persist data-source IDs.

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
   `title`/`date`/`url`. Zero matches or multiple matches fail closed.
4. Candidate lookup uses `POST /v1/data_sources/{data_source_id}/query`.
5. Recording URL update uses `PATCH /v1/pages/{page_id}`.

The integration must be connected directly to the original database. Sharing a parent page or a
linked view is insufficient. A `403` or resource `404` blocks that recruiter until the database is
shared and its original ID is verified.

**Pre-deploy read-only probe:** First copy each recruiter database to a test location and connect
the integration to the copy. Use only database retrieval and data-source retrieval to verify that
exactly one schema has the configured `title`, `date`, and `url` properties. Do not query pages or
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
2. Add bot to relevant channel(s)
3. Store in secrets:
   MATTERMOST_URL=https://mm.company.com
   MATTERMOST_BOT_TOKEN=xxx...
   MATTERMOST_CHANNEL_ID=xxx...   # default notifications channel
```

**Usage:**
```python
headers = {"Authorization": f"Bearer {settings.mattermost_bot_token}"}
# POST /api/v4/posts  → send message
# GET  /api/v4/channels/{channel_id}/posts  → poll replies
# Preferred: Mattermost webhooks / WebSocket for real-time replies
```

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
| `MATTERMOST_CHANNEL_ID` | Mattermost | Config | — |
| `DATABASE_URL` | PostgreSQL | Connection string | — |

All secrets injected via `pydantic-settings` (`BaseSettings`). `SecretStr` for sensitive fields.
Never in code, logs, or git.
