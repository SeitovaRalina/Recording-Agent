# Backend contract

`RECORDING_AGENT_BACKEND_URL` must be loopback HTTP(S), defaulting to
`http://127.0.0.1:8000`. `RECORDING_AGENT_BACKEND_SECRET` exists only in the process/service
environment. The CLI never prints it.

Trusted invocation metadata is supplied through `RECORDING_AGENT_RECRUITER_EMAIL`,
`RECORDING_AGENT_RECRUITER_USER_ID`, and `RECORDING_AGENT_MATTERMOST_DM_CHANNEL_ID`. When a trusted
value exists, a conflicting explicit CLI value is rejected; model-generated arguments cannot
override invocation identity. Never obtain these identities from recruiter text.

All commands emit one bounded JSON object. Success is
`{"ok":true,"message":"...","result":...}`. Failure is
`{"ok":false,"message":"...","error":"..."}` with exit status 1. Return `message` verbatim.
Backend responses above 64 KiB fail closed.

## Commands

```text
recording_agent.py scan --idempotency-key KEY
recording_agent.py status [trusted metadata and bounded filters]
recording_agent.py questions [trusted metadata] [--question-set-id UUID] [--limit 1..50]
recording_agent.py answer [trusted metadata] --actions-json JSON
recording_agent.py destinations [trusted metadata]
recording_agent.py create-destination [trusted metadata] --parent-destination-id UUID --name NAME
recording_agent.py route-interview [trusted metadata] --recording-id UUID --destination-id UUID
                                  --expected-version N --idempotency-key KEY
recording_agent.py non-interview [trusted metadata] --recording-id UUID --destination-id UUID
                                 --expected-version N --idempotency-key KEY
recording_agent.py cleanup-preview [trusted metadata] [--limit 1..100]
recording_agent.py cleanup-confirm [trusted metadata] --preview-id UUID --capability TOKEN
                                   --snapshot-hash SHA256 --idempotency-key KEY
```

`answer --actions-json` accepts 1..50 objects containing only `question_id`, `question_set_id`,
`action`, `capability`, `expected_version`, `idempotency_key`, and optional `choice`. `resolve`
requires choice 1..10; `ignore` forbids choice. Free text is never sent to Backend.

## Endpoints and safety

| Command | Backend endpoint |
|---|---|
| `scan` | `POST /tools/scans/trigger` with fixed test scope |
| `status` | `GET /tools/recordings/status` |
| `questions` | `GET /tools/questions` |
| `answer` | `POST /tools/questions/answer` |
| `destinations` | `GET /tools/storage/destinations` |
| `create-destination` | `POST /tools/storage/destinations` |
| `route-interview` | `POST /tools/recordings/{id}/route-interview` |
| `non-interview` | `POST /tools/recordings/{id}/route-non-interview` |
| `cleanup-preview` | `POST /tools/cleanup/previews` |
| `cleanup-confirm` | `POST /tools/cleanup/previews/{id}/confirm` |

Destination IDs are opaque. `destinations` may show a safe full folder label so the LLM can
disambiguate duplicate display names; do not construct or submit a path. `route-interview` is valid
only after the Backend has matched the recording to a candidate and returned the current recording
version. Cleanup preview is non-mutating; confirmation must reuse its exact preview ID, hash,
capability, recruiter, DM, and one stable idempotency key. MinIO test links are not eligible durable
archival proof.

Treat 401/403 as authorization failure, 404 as inaccessible context, 409 as stale/consumed/
conflicting state, and 410 as expired capability. Do not retry a mutation under a new key unless
the recruiter performs a new action.
`scan`, `questions`, and `answer` require all applicable identity fields from trusted invocation
environment variables: `RECORDING_AGENT_RECRUITER_EMAIL`,
`RECORDING_AGENT_RECRUITER_USER_ID`, and
`RECORDING_AGENT_MATTERMOST_DM_CHANNEL_ID`. Command-line values may only repeat those injected
values; they cannot establish a missing identity or channel.
