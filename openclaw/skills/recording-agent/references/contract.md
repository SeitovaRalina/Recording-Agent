# Backend contract

`RECORDING_AGENT_BACKEND_URL` must be loopback HTTP(S), defaulting to
`http://127.0.0.1:18000`. `RECORDING_AGENT_BACKEND_SECRET` exists only in the recruiter-facing
process/service environment. The CLI never prints it. Autonomous routing commands never require,
read, or send this secret.

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
recording_agent.py routing-activate --job-id UUID --dispatch-nonce NONCE
recording_agent.py routing-resolve --job-id UUID --dispatch-nonce NONCE --snapshot-hash SHA256
                                    --destination-id UUID
recording_agent.py routing-defer --job-id UUID --dispatch-nonce NONCE
                                  --snapshot-hash SHA256
                                  --reason ambiguous|no_match|model_error
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
| `routing-activate` | `POST /internal/routing-jobs/{id}/activate` |
| `routing-resolve` | `POST /internal/routing-jobs/{id}/resolve` |
| `routing-defer` | `POST /internal/routing-jobs/{id}/defer` |

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

## Autonomous routing worker

The root-owned Gateway command-cron dispatcher alone calls
`POST /internal/routing-jobs/dispatch` with the existing loopback OpenClaw secret. It receives either
`null` or `{ "job_id": UUID, "dispatch_nonce": NONCE }`. `null` is a successful no-work result and
must not start an agent turn.

The dispatcher starts the child with an allowlisted empty environment (`env -i`), not inherited
Gateway variables. It passes only the loopback Backend URL, non-secret OpenClaw state/config paths,
and the root-controlled loopback Gateway client URL/token before starting a fresh, non-delivering
`recordings-saver` session through the active Gateway. It never uses `--local`, passes no LLM
provider credential, and passes no Backend/OpenClaw Backend secret. The worker receives
only `job_id` and `dispatch_nonce`; it does not receive recruiter identity, raw Synology paths,
Notion URLs, share links, secrets, or the dispatcher credential. Routing endpoints authenticate
solely with the one-time nonce and send only these bodies:

```json
{ "worker_id": "recordings-saver", "dispatch_nonce": "<one-time nonce>" }
```

`routing-activate` returns opaque `recording_id`, `version`, `snapshot_hash`, bounded candidate/date
context, and destination choices containing only `{ "id", "label" }`. `routing-resolve` adds only
`snapshot_hash` and one returned `destination_id`. `routing-defer` adds the same `snapshot_hash` and
accepts only `ambiguous`, `no_match`, or `model_error`. A defer creates exactly one durable Backend
ManualReview and one NotificationOutbox item. Its ordinary-DM text contains only numbered stored
destination labels; it never contains IDs or paths. A recruiter number maps to that same stored
choice before live destination validation and transfer resume. The Backend independently verifies the
lease, worker, snapshot,
recording version, ownership, live destination state, collision, and transfer claim. A worker must
finish with `NO_REPLY`; recruiter messages remain Backend-owned.

Before installing or enabling the cron job, a root operator runs
`recording-agent-routing-cron-admin preflight`. It verifies the active Gateway through a transient
`openclaw` user process with only loopback Gateway client settings, then verifies that
`recordings-saver` is visible through Gateway RPC. It does not run a model turn or expose provider
credentials.
