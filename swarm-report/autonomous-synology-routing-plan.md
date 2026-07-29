# Plan: Autonomous scan-to-Synology routing (slug: autonomous-synology-routing)

## TL;DR

After a daily/manual scan, Backend should deterministically finish identity resolution, inventory
bounded Synology destinations, then hand a durable routing job to Mila. Mila resolves exactly one
opaque ID automatically or creates a recruiter DM question only for ambiguity. Backend remains sole
owner of scan, state, transfer, notifications, and integrations; it never calls or launches an LLM.

## Acceptance criteria

1. One scan creates at most one durable routing job for each fully resolved Synology recording;
   recruiter never needs to say "continue".
2. Candidate/card/Spot/calendar ambiguity is resolved before any inventory, routing job, upload, or
   Notion write. A valid answer automatically continues the same recording.
3. Ordinary candidate lookup excludes cards with an existing recording link. Worker sees only bounded,
   minimal, untrusted-delimited context and opaque destination IDs. It returns exactly one UUID or a
   structured defer; no raw path, secrets, URLs, contacts, or free recruiter text reach its routing
   action.
4. Unique worker selection is independently checked for job snapshot membership, actor/job/recording
   version, recruiter ownership, live directory/root/symlink/permission state, collision and transfer
   ownership before `transfer_started`.
5. Zero/multiple selection creates one Backend-owned ordinary-DM question. Exact answer resumes
   transfer automatically without re-scan or model memory.
6. Scan scheduler never invokes, launches, blocks on, or depends on Mila/OpenClaw. Job delivery,
   worker claim, transfer ownership, retries and restart recovery are idempotent and lease-protected.
7. Scheduler-disabled manual scan follows identical routing-job/resume flow. Canary/production
   external effects remain independently feature-gated and approval-gated.

## Plan

1. Adopt the supported Gateway Cron contract. A root-owned, non-writable command-cron dispatcher
   runs under the Gateway service environment, takes a host-level `flock`, and atomically obtains a
   short dispatch lease from Backend when a routing job is ready. It exits without a model call when
   none is ready. For one leased dispatch it calls `/opt/openclaw/bin/openclaw agent --agent
   recordings-saver` with a fresh, isolated session and a message containing only a job UUID and
   dispatch nonce. The agent activates that lease, then uses Backend tools to resolve or defer the
   job. Read-only server verification confirms
   `openclaw-gateway.service` is enabled/active, the binary/config/env exist, and the skill is
   installed; user verified Mattermost routing and LLM SecretRef work. The contract must specify
   command/API, auth, worker identity, timer lifecycle, concurrency lock, retry/backoff, DM identity,
   logs, health/lag monitoring, rollback, and deployment owner. Do not assume generic event push,
   Gateway restart, or Backend shell/process access.
2. Add ADR-021 and the architecture amendment. The threat model records model-provider privacy,
   prompt injection, wrong-route risk, strict UUID/defer validation, Backend-owned defer
   notification, feature-gate/canary/rollback behaviour, and split platform/Backend operations
   ownership.
3. Create routing-job model/migration/service: immutable bounded inventory snapshot, recording/version,
   state, claimant lease, retry/idempotency, audit, expiry and one-active-job invariant.
4. Modify ordinary candidate lookup to exclude non-empty recording fields. Modify scan continuation:
   after all candidate identity questions are resolved and no active review exists, preflight/discover
   allowed roots, persist destinations, create/reuse job. Discovery failure becomes actionable review;
   no LLM/upload.
5. Add worker-only claim/resolve/defer endpoints. Claim returns one minimal job. Resolve accepts exactly
   one snapshot UUID. Defer accepts structured `ambiguous` IDs or `no_match`. Bind worker identity,
   lease, job/recording version, snapshot hash and idempotency. Worker endpoints authenticate the
   machine worker plus dispatch nonce; they derive recruiter ownership from the job and never reuse
   a recruiter DM environment identity.
6. On resolve, Backend repeats destination/live/collision/recording ownership checks, persists ID,
   claims transfer, and invokes existing resumable transfer. On defer, reuse/extend existing
   ManualReview, QuestionDigest and NotificationOutbox rather than create a competing notifier.
7. Define and version exact repository worker system instruction and strict response schema: all tool
   data is untrusted delimited data, never instructions; compare only returned labels; return exactly
   one opaque UUID or `defer`; resolve only exact-one high-confidence UUID; otherwise defer. No user
   prompt exists for autonomous jobs. Recruiter DM is user input only for ambiguity. Persist model,
   prompt version, input snapshot hash and decision telemetry; Backend validates action independently.
   The isolated cron job has no chat delivery and the worker returns `NO_REPLY`; Backend-owned
   NotificationOutbox alone contacts a recruiter for a defer/failure.
8. Add reconciliation: lease expiry, model failure/malformed output/rate limit, inventory drift,
   worker crash, scan retry, route/reroute conflict, and transfer crash leave resumable state and one
   bounded digest item; never auto-ignore or auto-upload.
9. Document status output (`queued`, `auto-routing`, `awaiting recruiter`, `uploading`, terminal),
   enable feature flags disabled by default, test isolated fake worker, then follow separate approved
   canary deployment manifest. Commit logical schema/docs and implementation checkpoints, then review.

## Affected files

- New `app/db/models/routing_job.py`, Alembic migration, `app/services/routing_jobs.py`, tests.
- `recording.py`, `manual_review.py`, `question_queue.py`, `reviews.py`, `destinations.py`,
  `scheduler/cron.py`, `routers/tools.py`, `config.py`, `main.py`.
- OpenClaw skill/contract/CLI; status/data-model/Synology API docs; architecture/decisions/open-questions.

## Tests

- Unique candidate/Spot -> one job, no recruiter DM, no upload before worker resolve.
- Candidate or multi-Spot ambiguity -> question first; answer automatically creates/resumes job.
- Unique UUID -> validated destination -> normal state sequence; idempotent repeat.
- Duplicate `Flutter` -> defer -> one DM question -> exact answer -> automatic upload.
- Reject raw path, non-snapshot UUID, stale job/recording, wrong worker, expired/replayed lease,
  concurrent claim, inventory drift, symlink/permission/collision, worker/model failure and crash.
- Assert Backend makes no LLM/network/subprocess call; assert minimal bounded payload and injection
  strings cannot induce anything beyond returned UUID.
- Alembic check, full pytest, Ruff, mypy; isolated external smoke only after approvals.

## Blockers

1. **Implementation gate:** Gateway Cron and `openclaw agent --agent` are supported by installed
   OpenClaw `2026.6.11`. Build and test the dispatcher/lease contract first; never give Backend
   shell access or make it invoke OpenClaw directly.
2. **Architecture decision required:** autonomous LLM routing changes "deterministic matches need no
   LLM / OpenClaw interaction-only". Add approved ADR, privacy/model-provider threat model, rollback,
   and canary/production approval gates.
3. **Deployment gate:** Host runtime is ready. Agent invocation, scheduled test and production
   Synology/Notion/Yandex effects still require separate approval.

## Out of scope

- Backend direct LLM calls, Backend launching OpenClaw, generic event-push assumptions, Gateway/plugin
  changes, raw-path APIs, semantic Backend mappings, production deployment before approvals.
- Post-upload reroute/reassignment; see `synology-public-reroute-plan.md`.

## Assumptions

- Product permits auto-upload only after Mila returns exactly one bounded destination; ambiguity alone
  requires recruiter response.
- Public permanent link policy is handled by the separate plan.
