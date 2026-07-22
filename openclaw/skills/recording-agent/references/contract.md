# Backend contract

Configure `RECORDING_AGENT_BACKEND_URL` with a loopback HTTP(S) base URL. It defaults to
`http://127.0.0.1:8000`. Configure `RECORDING_AGENT_BACKEND_SECRET` in the OpenClaw process
environment. The CLI sends it as a bearer token and never prints it.

For internal Codex harnesses, configure `RECORDING_AGENT_RECRUITER_USER_ID` with the single
allowlisted test recruiter identity. The CLI uses it as the default for status and review intents;
an explicit trusted Mattermost metadata value may override it. If neither exists, the CLI fails
closed. Never obtain this identity from recruiter chat text.

All commands emit one bounded JSON object. Success has
`{"ok":true,"message":"...","result":...}`. Failure has
`{"ok":false,"message":"...","error":"..."}` and exit status 1. `message` is a deterministic,
safe recruiter-facing rendering and must be returned verbatim. Backend responses larger than
64 KiB fail closed.

## Commands

```text
recording_agent.py scan --recruiter-email EMAIL --idempotency-key KEY
recording_agent.py status [--recruiter-user-id ID] [--date YYYY-MM-DD] [--candidate TEXT]
                          [--recording-id UUID] [--status STATUS] [--limit 1..50]
recording_agent.py review --review-id UUID [--recruiter-user-id ID]
                          --mattermost-thread-id ID --token TOKEN
recording_agent.py resolve --review-id UUID [--recruiter-user-id ID]
                           --mattermost-thread-id ID --token TOKEN
                           --expected-version N --idempotency-key KEY --choice CHOICE
recording_agent.py ignore --review-id UUID [--recruiter-user-id ID]
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

The scan response includes bounded per-recording items plus `discovered`, `inserted`,
`skipped_legacy`, `matched`, `manual_review`, `without_review`, `failed_recordings`, `processed`,
`items_truncated`, and `failed`. Each item includes recording identity, filename, `is_new`, status,
whether review is required, a safe review reason, generated filename/link when available, and an
actionable error when present. `items` contains bounded recordings owned and processed by that
scan, including explicit restart recovery; `is_new` distinguishes new insertions from resumed
work. A repeated scan may correctly report zero new items while status queries still return
existing recordings.

Treat `401` and `403` as authorization failure. Treat `404` as missing or inaccessible context.
Treat `409` as stale version, consumed token, replay conflict, or invalid state; fetch fresh review
context before further action. Treat `410` as expired review. Never retry a mutation with a new
idempotency key unless the recruiter performs a new action.

Backend owns response schemas and bounds. Display only safe fields returned by Backend: recording
identity, candidate, generated filename, status, safe link, actionable error, and allowed review
choices. Never display internal payloads or credentials.

Status items also include `requires_review` and `review_reason`; use the reason label in the
deterministic message instead of repeating the raw `manual_review_required` status.
