# Plan: Phase 4 - Mila-first OpenClaw integration

## TL;DR

Deploy a separate test-mode Recording Agent Backend on the existing Mila host and expose it only
on loopback. Add a script-backed OpenClaw workspace skill to Mila's existing `main` agent. The
skill handles explicit Mattermost DM commands and manual-review dialogue; FastAPI remains the only
scheduler, state owner, Notion client, filename builder, and transfer executor.

Use MinIO and a test Notion database for the first canary. Do not enable scheduled scanning,
Yandex source mutation, cleanup, permanent purge, production Notion databases, or Synology. Mila's
built-in Notion credential is not reused by the Backend.

This plan replaces the previous speculative event-push/plugin design. Read-only discovery proved
that Mila runs OpenClaw `2026.4.22`, supports workspace `SKILL.md` packages with bundled scripts,
and exposes its authenticated Gateway only on `127.0.0.1:18789`.

## Confirmed decisions

- **Q1:** Phase 4 uses MinIO only. Object prefix mirrors the future storage layout:
  `<recruiter>/<YYYY-MM-DD>/<candidate>/`.
- **Q3:** Mattermost communication is DM-only. No shared-channel fallback.
- **Q5:** First canary uses a test Notion database. Production recruiter databases remain disabled.
- **OpenClaw packaging:** MVP result is a workspace skill, not a native plugin or MCP server.
- **Runtime:** testing happens on Mila, but in a separate test service and isolated data scope.
- **Sylvanas:** untouched until Mila canary passes.

## User-facing Mattermost workflow

The completed Phase 4 must support all customer-facing scenarios:

1. **Scheduled processing:** Backend scheduler scans and processes recordings at the configured
   interval. It does not spend an LLM turn on each normal scan. Mila joins only for dialogue or
   reporting.
2. **Manual start:** recruiter writes `Мила, проверь новые записи`; Mila invokes the skill's test or
   production scan intent and reports how many recordings were found.
3. **Ambiguity:** Mila sends a DM such as `Нашла запись ... Есть два подходящих события: 1) ...,
   2) ... . Ответьте 1, 2 или "пропустить".` The recruiter replies in the same DM/thread. Mila
   submits the bound choice; Backend resumes processing.
4. **Completion/error:** Mila sends a concise DM with candidate, generated filename, terminal
   status, and safe link or actionable error. Secrets and raw integration payloads are omitted.
5. **Status query:** recruiter writes `Мила, покажи статусы записей за сегодня` or asks for one
   candidate/recording. Mila returns bounded status rows from Backend without mutating anything.

OpenClaw provides natural-language entry and dialogue. Backend scheduler and state machine provide
reliable automation. This separation still satisfies the customer requirement that Mila/Sylvanas
can launch and supervise the workflow.

## Live evidence and current Notion blocker

- After sharing was updated, Mila's configured Notion key retrieved the exact page
  `397c8889-e4c8-814c-8acf-d7da92915220` with HTTP 200.
- The page contains original child database `Test Interviews`
  (`ef16e0bf-e91b-470f-90a1-749d0bae0ad3`) and data source
  `0788967f-04fe-43c3-a78b-d2572e031031`.
- Read-only schema retrieval confirms `Name` (title), `General Interview Date` (date),
  `General Interview recording` (files), `Spot Client` (rich_text), `Stage` (multi_select), and
  other copied production properties.
- Phase 4 general-interview naming uses `Spot Client` for `<project_or_spot>` and the explicit
  constant `general_interview` for `<interview_type>`. `Stage` is a candidate pipeline stage and
  must not be misused as recording type.

The schema-access gate is satisfied for Mila's currently configured token. Before the first write,
Backend must repeat the same probe using its actual configured `NOTION_TOKEN` and query a synthetic
test row.

## Credential boundary

`NOTION_TOKEN` and `NOTION_API_KEY` are environment-variable names, not different Notion credential
types. Both can contain the same access token issued for one Notion Connection:

- `NOTION_TOKEN`: Recording Agent Backend credential; it needs access to the selected test DB.
- `NOTION_API_KEY`: OpenClaw/Mila Notion skill credential; it belongs to Mila's configured Notion
  connection.

Using the same token for both processes is technically valid and will give Backend the same access
as Mila. Separate least-privilege integrations are a security recommendation, not a requirement.
Regardless of token reuse, the Recording Agent skill calls Backend intents and does not call Notion
directly.

## Acceptance criteria

1. Mila keeps OpenClaw Gateway loopback-only; no Gateway, FastAPI, PostgreSQL, or MinIO management
   port is published to the Internet.
2. A separate `recording-agent-test` service runs on Mila loopback with an explicit test-mode
   allowlist for recruiter, Notion database, MinIO bucket/prefix, and Mattermost user.
3. Mila workspace contains a versioned `recording-agent` skill with `SKILL.md`, a bundled CLI
   script, and a contract reference. No secret exists in those files.
4. Skill is explicit-invocation-only during the first canary. After it passes, Backend scheduler is
   enabled at the configured interval; OpenClaw heartbeat does not own deterministic scanning.
5. Skill can trigger a scan, query bounded recording statuses, request bounded review context,
   resolve one review, and ignore one review. It cannot call raw transfer, Notion-update,
   mark-processed, delete, or purge operations.
6. DM replies are accepted only from the configured recruiter and are bound to review ID,
   recording ID/version, Mattermost post or thread ID, opaque one-time token, and expiry.
7. Every mutation requires `expected_version` and an idempotency key. Retry/replay returns the
   persisted result and causes no duplicate upload, Notion update, or notification.
8. MinIO object name is
   `YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>` after deterministic
   sanitization. Full key is
   `<recruiter>/<YYYY-MM-DD>/<candidate>/<generated_filename>`.
9. Retry of the same recording reuses the same object. A different recording resolving to an
   existing key enters manual review; it is never overwritten or silently auto-suffixed.
10. Test Notion schema is probed read-only before enablement. Missing, inaccessible, ambiguous, or
    wrong-typed properties fail closed and disable Notion writes.
11. MinIO pre-signed URL is labeled temporary/test-only. Phase 4 does not claim permanent archival.
12. The canary cannot mark Yandex files processed, move them to Trash, permanently purge them, or
    access production recruiter resources.
13. Unit, contract, and integration tests pass, followed by the full `pytest` gate.
14. Rollback removes/disables only the test Backend service and Recording Agent skill; existing
    OpenClaw, Mattermost, and unrelated Mila skills keep working.
15. Scheduled and manual runs send DM completion or actionable error notifications, while normal
    status queries remain read-only.

## Plan

### 1. Reconcile project documentation and config contract

Update `.memory-bank/open-questions.md`, `.memory-bank/architecture.md`,
`.memory-bank/decisions.md`, and `.memory-bank/auth-flow.md`:

- Backend owns deterministic workflow and all integration credentials.
- Mila owns natural-language interaction and manual-review presentation only.
- Mila is primary canary; Sylvanas is deferred.
- MinIO is test storage; Synology remains a later production decision.
- Mattermost is DM-only.
- Document separate Backend and Mila Notion integrations.

Add config fields only when implementation starts. Expected categories:

- test-mode enable flag and resource allowlists;
- loopback bind/port and Backend skill secret;
- test MinIO bucket/prefix;
- Notion property names and property kinds;
- Mattermost recruiter user ID;
- review-token TTL and idempotency settings.

All secrets use `SecretStr` and service environment. IDs and paths remain configuration, never
code literals.

### 1A. Add operator-only recruiter bootstrap

Current code has no self-service onboarding, and the `tools/setup/yandex_oauth.py` mentioned in
older auth documentation does not exist. Phase 4 keeps credential issuance outside the agent:

- operator provisions each recruiter's Yandex refresh token and CalDAV app password in the Backend
  secret environment before activation;
- OpenClaw never asks for or receives those credentials;
- add an operator-only bootstrap command that accepts recruiter email, explicit Notion URL/ID,
  Mattermost user ID, and test storage prefix;
- resolve `notion_database_id` only from the explicit Notion target, show database title and schema,
  require confirmation, and store an inactive `recruiter_config` row;
- reject workspace-wide inferred matches, linked-view ambiguity, missing credentials, incompatible
  schemas, and duplicate recruiter email;
- activate the row only after calendar discovery/default selection and all integration preflights
  succeed.

For the Mila canary, store confirmed Test Interviews database ID
`ef16e0bf-e91b-470f-90a1-749d0bae0ad3`. Discover its data-source ID at runtime; never persist it as
recruiter configuration. Self-service OAuth remains a later feature.

### 2. Resolve the test Notion data source

Run this read-only gate with the **Backend** integration token:

1. Retrieve original database by configured database ID.
2. Retrieve every advertised data source with Notion API `2026-03-11`.
3. Require exactly one compatible data source.
4. Confirm configured title/date/project/type/recording properties and their types.
5. Query one synthetic test row only after schema validation; do not update it yet.

Confirmed canary mapping:

- candidate: `Name` (`title`);
- date: `General Interview Date` (`date`);
- project/spot: `Spot Client` (`rich_text`);
- interview type: configured constant `general_interview`;
- recording destination: `General Interview recording` (`files`).

Production IDs remain absent from test service config. Repeat this probe using Backend's runtime
token before live writes; do not assume Mila process configuration equals Backend configuration.

### 3. Implement deterministic filename and collision policy

Move the Phase 3 deferred filename rule into Backend code before storage upload:

```text
YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>
```

- Date: matched calendar event local date.
- Candidate: persisted matched candidate display name.
- Project/spot: configured Notion source; exactly one normalized value required.
- Interview type: configured Notion select or explicit constant.
- Extension: original recording extension, lower-cased and allowlisted.
- Sanitization: Unicode normalization, trim/collapse whitespace, replace path-reserved characters,
  reject empty components, and cap component/key lengths.
- Persist generated filename and full storage key before upload.
- Same `recording_id` + same content identity + same key is idempotent success.
- Existing key owned by another recording is `manual_review_required`.

MinIO has no directories; `/` in the object key provides the same logical prefix as future
Synology folders. No Synology-specific API is needed for this canary.

### 4. Add narrow Backend review intents

Create/adapt authenticated loopback endpoints for:

- `GET /tools/reviews/{review_id}`: bounded, redacted context and allowed choices;
- `POST /tools/reviews/{review_id}/resolve`: choice, one-time token, expected version,
  idempotency key;
- `POST /tools/reviews/{review_id}/ignore`: same concurrency/replay guards;
- `POST /tools/scans/trigger`: explicit scan trigger, test/prod scope enforced by service config;
- `GET /tools/recordings/status`: bounded filters for date, candidate, recording ID, and status.

One resolve intent invokes the existing ordered Backend pipeline. Do not expose individual storage,
Notion, Yandex mutation, or deletion primitives to the model. Use row locking/compare-and-swap and
persist idempotency response replay.

### 5. Add DM-only Mattermost review flow

- Map recruiter config to one Mattermost user ID.
- Send a DM containing bounded candidate choices and opaque review token; never include secrets.
- Persist DM channel/post or thread ID, recruiter ID, review token hash, expiry, recording version,
  and status.
- Reject wrong sender, wrong thread, expired token, already-consumed token, stale version, and
  ambiguous free-form reply.
- No fallback to a shared channel.
- Backend remains able to report failures without asking Mila to perform side effects.

### 6. Build the Mila workspace skill

Version-controlled source layout:

```text
openclaw/skills/recording-agent/
  SKILL.md
  scripts/recording_agent.py
  references/contract.md
```

Deployment target after approval:

```text
/root/.openclaw/workspace/skills/recording-agent/
```

`SKILL.md` defines activation phrases, explicit test-only scope, reply grammar, status-query
behavior, and refusal rules.
The CLI calls only loopback Backend endpoints and emits bounded JSON. Backend secret comes from
process environment. Skill never reads Mila's Notion key and never implements matching/transfer.

Use Mila's eligible bundled `skill-creator` workflow: initialize the version-controlled skill,
keep `SKILL.md` concise, place deterministic behavior in `scripts/`, put the API schema in one-level
`references/`, validate/package it, then forward-test realistic prompts. Use existing OpenClaw
`2026.4.22`; no upgrade, native plugin install, Gateway bind change, or Gateway restart is part of
Phase 4.

### 7. Prepare isolated test service on Mila

Before remote writes, inventory available Docker/systemd/runtime and disk capacity read-only. Then
request approval for exact files/services.

Run a distinct `recording-agent-test` service:

- loopback-only API on a non-conflicting port;
- separate test DB/schema;
- test MinIO bucket and prefix;
- Backend integration token shared only with the test Notion DB;
- one allowlisted Mattermost test user;
- scheduler off initially;
- `mark_processed`, Trash cleanup, permanent purge, Synology, and production configs hard-disabled.

Seed or manually select one synthetic recording. Do not use an uncontrolled production Yandex
recording for first canary.

After manual canary, enable Backend scheduler for the same allowlisted test scope and prove one
scheduled run. Production scheduling remains disabled until a separate promotion approval.

### 8. Test in layers

1. Unit tests: schema mapping, filename normalization, collision handling, one-time tokens,
   expected-version checks, and idempotency replay.
2. Contract tests: skill CLI request/response JSON and auth failures.
3. Integration tests: PostgreSQL + MinIO + mocked Notion/Mattermost.
4. Mila dry run: skill discovery and read-only review retrieval.
5. Mila canary: one synthetic recording, test Notion row, test MinIO prefix, DM-only interaction.
6. Retry the same resolve request and restart the test Backend; prove no duplicate effects.
7. Enable test-scope Backend schedule and prove one scheduled scan plus completion/error DM.
8. Query statuses by today, candidate, recording ID, and status through natural-language prompts.
9. Run repository lint/type gates and full `pytest`; record exact output in build report.

### 9. Rollback and promotion

Rollback triggers: unexpected production access, duplicate side effect, schema mismatch, wrong DM
sender accepted, secret exposure, public listener, or existing Mila regression.

Rollback disables the test service, removes/disables only the Recording Agent skill deployment,
and restores its versioned backup if needed. It does not upgrade/restart OpenClaw or alter other
skills. Promote to scheduled Mila processing only in a separate approval after canary evidence.
Inspect Sylvanas read-only and create a separate rollout plan afterward.

## Affected files during `/build`

- `.memory-bank/architecture.md`
- `.memory-bank/decisions.md`
- `.memory-bank/open-questions.md`
- `.memory-bank/auth-flow.md`
- `app/config.py`
- `app/tools/notion.py`
- `app/services/transfer.py`
- `app/services/candidate.py`
- `app/services/pipeline.py` (new only if extraction is required)
- `app/routers/tools.py`
- `app/tools/mattermost.py`
- `app/main.py`
- `tools/setup/configure_recruiter.py`
- deployment service/container files selected after Mila runtime inventory
- `openclaw/skills/recording-agent/SKILL.md`
- `openclaw/skills/recording-agent/scripts/recording_agent.py`
- `openclaw/skills/recording-agent/references/contract.md`
- focused unit, contract, integration, and scheduler tests
- operator-bootstrap tests for explicit Notion target resolution, inactive creation, validation,
  confirmation, and failure-closed behavior

Exact Python file changes must be rechecked against current symbols before `/build`; do not create a
parallel pipeline if current services can be extended safely.

## Blockers

### Blocks first live Notion write

- Backend runtime is not deployed yet, so its actual `NOTION_TOKEN` has not repeated the successful
  read-only schema probe. If it uses Mila's same access token, access should be identical; verify,
  do not infer.
- A synthetic test row for the canary must be selected or created before mutation testing.

### Blocks remote mutation

- Explicit approval is required before installing the skill, deploying a service, changing config,
  or restarting/reloading anything on Mila.
- Existing plaintext OAuth token in Mila workspace must be rotated/removed before deployment.
- Shared root access should be replaced or rotated; production rollout should use least privilege.

## Out of scope

- Sylvanas changes.
- Public exposure of OpenClaw Gateway or Backend.
- OpenClaw upgrade, native plugin, or MCP server.
- Production Notion databases, Synology, or production Yandex recordings.
- Yandex `mark_processed`, Trash cleanup, and permanent purge.
- Permanent archive URLs from MinIO pre-signed links.
- Lili production schema.

## Assumptions

- Existing FastAPI/PostgreSQL code remains source of truth.
- Mila `main` agent and existing Mattermost connection remain available.
- A separate test service can be installed on Mila after runtime preflight and approval.
- Test Notion sharing and original database ID are confirmed through Mila; Backend runtime must
  repeat the probe with its configured token before the live canary.
- Every MVP recruiter is pre-provisioned by an operator. Self-service onboarding is not assumed.
