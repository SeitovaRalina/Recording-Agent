# Backend contract

Configure `RECORDING_AGENT_BACKEND_URL` with a loopback HTTP(S) base URL. It defaults to
`http://127.0.0.1:8000`. Configure `RECORDING_AGENT_BACKEND_SECRET` in the OpenClaw process
environment. The CLI sends it as a bearer token and never prints it.

All commands emit one bounded JSON object. Success has `{"ok":true,"result":...}`. Failure has
`{"ok":false,"error":"..."}` and exit status 1. Backend responses larger than 64 KiB fail closed.

## Commands

```text
recording_agent.py scan --recruiter-email EMAIL --idempotency-key KEY
recording_agent.py status --recruiter-user-id ID [--date YYYY-MM-DD] [--candidate TEXT]
                          [--recording-id UUID] [--status STATUS] [--limit 1..50]
recording_agent.py review --review-id UUID --recruiter-user-id ID
                          --mattermost-thread-id ID --token TOKEN
recording_agent.py resolve --review-id UUID --recruiter-user-id ID
                           --mattermost-thread-id ID --token TOKEN
                           --expected-version N --idempotency-key KEY --choice CHOICE
recording_agent.py ignore --review-id UUID --recruiter-user-id ID
                          --mattermost-thread-id ID --token TOKEN
                          --expected-version N --idempotency-key KEY
```

## Endpoints

| Command | Request |
|---|---|
| `scan` | `POST /tools/scans/trigger` with recruiter email, fixed `test` scope, and idempotency key |
| `status` | `GET /tools/recordings/status` with bounded filters |
| `review` | `GET /tools/reviews/{review_id}` with recruiter/thread binding and token in `X-Review-Token` |
| `resolve` | `POST /tools/reviews/{review_id}/resolve` with binding, token, version, idempotency key, and choice |
| `ignore` | `POST /tools/reviews/{review_id}/ignore` with binding, token, version, and idempotency key |

Treat `401` and `403` as authorization failure. Treat `404` as missing or inaccessible context.
Treat `409` as stale version, consumed token, replay conflict, or invalid state; fetch fresh review
context before further action. Treat `410` as expired review. Never retry a mutation with a new
idempotency key unless the recruiter performs a new action.

Backend owns response schemas and bounds. Display only safe fields returned by Backend: recording
identity, candidate, generated filename, status, safe link, actionable error, and allowed review
choices. Never display internal payloads or credentials.
