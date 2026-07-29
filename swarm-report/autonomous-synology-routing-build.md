# Build: Autonomous scan-to-Synology routing

## Status

Implemented locally. The autonomous feature flag is disabled by default. No server, secrets, or
external Synology, Notion, Yandex, Mattermost, or LLM side effects were performed during this build.

## Python FastAPI scope

- Added durable `routing_jobs` ORM model and reversible Alembic revision
  `20260729_1000_add_routing_jobs.py`.
- Added bounded job snapshots, one-active-job constraint, short dispatch lease, hashed nonce,
  worker activation, destination resolve/defer, stale-state validation and idempotency handling.
- Added internal dispatcher and worker endpoints. The dispatcher authenticates with the existing
  OpenClaw secret; the worker receives only a job UUID and one-time nonce.
- Wired completed scan continuation to create jobs only after candidate resolution and destination
  discovery. The Backend never starts OpenClaw or calls an LLM.
- Excluded Notion cards with a populated recording field from ordinary candidate lookup.
- Added `AUTONOMOUS_ROUTING_ENABLED=false` by default. It gates job creation and every routing
  dispatch/worker endpoint.

## Gateway scope

- Added a Gateway command-cron dispatcher. It takes a host lock, polls Backend every two minutes,
  exits `NO_REPLY` without an LLM call when no job exists, and starts a fresh isolated
  `recordings-saver` turn only for a leased job.
- Added the autonomous skill protocol and CLI commands: activate, resolve, defer. The agent has no
  recruiter DM identity, no master Backend secret, no raw path, and no chat delivery.
- Added root-owned installer/admin scripts. They use a transient systemd unit with the existing
  Gateway EnvironmentFile, so SecretRef-backed credentials are not read, copied, or printed.
- Added deployment/runbook/static-validator coverage for the cron contract.

## Verification

| Scope | Command | Result |
|---|---|---|
| Routing/Notion | `poetry run pytest tests/test_routing_jobs.py tests/test_candidate.py tests/test_notion.py -q` | `63 passed` |
| Security retry | `poetry run pytest tests/test_routing_jobs.py tests/test_recording_agent_skill.py tests/test_tools_router.py tests/test_question_queue.py -q` | `53 passed` |
| Feature flag | `poetry run pytest tests/test_config.py tests/test_routing_jobs.py` | `11 passed` (existing pytest cache permission warning) |
| Skill | `poetry run pytest tests/test_recording_agent_skill.py` | `16 passed` (existing pytest cache permission warning) |
| Lint | focused Ruff commands | passed |
| Types | `poetry run mypy app` | passed, 50 source files |
| Migration | `poetry run alembic heads` | `20260729_1000 (head)` |
| Full suite | split after the 60-second local command limit | `157 passed + 162 passed = 319 passed, 1 warning per batch` |

The full-suite blocker exposed an uncommitted expiring-link policy that contradicted the approved
public-permanent policy. The retry removed that policy while preserving live destination validation
and no-parent-creation behavior. Public links now send `date_expired=-1`, `date_available=0`, and no
password/expiry payload. The remaining warning is an existing denied `.pytest_cache` write on
Windows. Bash static validation is pending server-side validation because local Windows WSL/Git-Bash
cannot create required pipes (`E_ACCESSDENIED`).

## Review rework

The first review found two HIGH issues. The retry makes worker endpoints nonce-and-worker-ID only;
the routing CLI omits Authorization even when the ordinary Backend secret exists, and the dispatcher
uses `env -i` to prevent the child agent process inheriting it. A defer now creates/reuses one
Backend-owned ManualReview and deduplicated NotificationOutbox item. ADR-021 documents the trust
boundary, prompt-injection policy, feature gate, canary and rollback requirements.

The second retry adds the autonomous destination-choice branch to `ReviewService`: it live-validates
the stored destination UUID, persists it, transitions to `transfer_started`, and resumes exactly
once. The dispatcher is a Gateway client, not a local model process: its clean child environment has
only loopback Gateway URL/token, Backend loopback URL, and OpenClaw paths. LLM-provider, Mattermost,
and Backend secrets are not forwarded. A root-only preflight validates Gateway RPC and agent binding
without a model turn.

The final review retry renders bounded numbered destination labels in the deferred Backend-owned DM,
deduplicates by routing-job and recording version, never includes UUIDs or paths, and proves that a
number maps to exactly one stored destination. Final review verdict: `ship`.

## Deployment gate

Install the Gateway cron only after the reviewed Backend release is deployed, migration applied, and
`AUTONOMOUS_ROUTING_ENABLED` is deliberately enabled. Installation command:

```bash
sudo APPROVE_ROUTING_CRON_INSTALL=yes ./deploy/scripts/install-routing-cron.sh
```

Then execute one controlled `recording-agent-routing-cron-admin run` with no pending job before any
canary routing job. The installer and test run must execute on the server; they are not yet run.

## Architecture retry amendment

ADR-021, the architecture amendment, and Q16 now record the approved ownership and threat model:
Backend owns scan/jobs/transfers/notifications; the command-cron only leases and starts isolated
workers; worker input is UUID+nonce plus a bounded snapshot; raw paths, recruiter identity and
master secrets are excluded; prompt-injection data is delimited and untrusted; Backend owns defer
notifications; flag/canary/rollback and platform-versus-Backend operational ownership are explicit.
