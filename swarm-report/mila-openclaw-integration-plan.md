# Plan: Mila-first OpenClaw integration   (slug: mila-openclaw-integration)

## TL;DR

Mila discovery is complete. Pin a local OpenClaw environment to `2026.4.22`, then build a
workspace `SKILL.md` plus bundled CLI client for narrow Backend intents. FastAPI remains the deterministic scheduler,
integration executor, and PostgreSQL state owner. OpenClaw handles ambiguous reviews and recruiter
dialog only. Prove the complete workflow against isolated test systems before an approval-gated
Mila canary. Sylvanas remains untouched until Mila passes.

The existing `phase-4-openclaw-integration-plan.md` is not implementation-ready: it assumes an
unknown event endpoint, an unknown tool-registration mechanism, overly broad mutating endpoints,
and a duplicate-prone fallback. This plan supersedes those assumptions without modifying that
untracked file.

## Acceptance criteria

1. A sanitized Mila discovery report records the installed OpenClaw and Node versions, install and
   runtime methods, process owner, Gateway bind/port, agent/workspace paths, skill roots, plugin/tool
   policy, supported agent invocation API, and authentication mode. Secret values are never read
   into reports or logs.
2. Discovery performs no install, restart, config edit, agent invocation, production API call, or
   remote filesystem write.
3. The Mila dashboard is reachable only through an SSH local-forward to its loopback listener. The
   Gateway is not exposed publicly.
4. Architecture names exactly one automatic scan owner. The confident path remains Backend-only;
   Mila handles `manual_review_required` cases and recruiter dialog.
5. A Mila workspace skill supplies `SKILL.md` plus a bundled CLI client that calls only narrow,
   validated Backend intents over loopback. The skill contains no credentials and does not
   reimplement matching, transfer, or state transitions. A classic native plugin is optional,
   not required for MVP.
6. Mutating intents require a stable idempotency key and expected recording/review state. Replays,
   timeouts, and restarts produce one logical transfer, Notion update, and notification.
7. Local E2E runs exact-version OpenClaw, PostgreSQL, MinIO, and isolated test integrations. It
   covers happy path, ambiguity, resolve, ignore, authentication failure, retry, replay, and
   OpenClaw restart.
8. `pytest` passes, including new contract and E2E tests. Config/lint/type gates already present in
   the repository also pass.
9. Mila receives only versioned locally tested artifacts after explicit approval. Canary uses one
   test recruiter and test recording, with source deletion and permanent purge disabled.
10. Rollback is documented and tested. Sylvanas receives no change in this phase.

## Plan

### Phase 4A: read-only Mila discovery

1. Preserve the dirty worktree. The existing untracked
   `swarm-report/phase-4-openclaw-integration-plan.md` belongs to the user.
2. Authenticate with the supplied SSH key through an in-memory `ssh-agent`. Never place its
   passphrase in a command, file, environment variable, log, report, or shell history.
3. Run read-only inventory:
   - identity, OS, time, OpenClaw executable path/version, and Node version;
   - `openclaw gateway status --deep`, health/status commands supported by the installed version;
   - `openclaw skills list --json` and plugin inspection commands supported by that version;
   - process manager/service metadata and `ss -lntp`;
   - file-name-only inventory of the selected agent workspace, skills, and plugin manifests.
4. Inspect only required sanitized config keys. Do not recursively grep or print JSON/YAML configs;
   they may contain Gateway tokens, provider keys, cookies, webhook URLs, or channel credentials.
5. Determine from evidence:
   - Mila agent ID and workspace;
   - Gateway bind/port and auth mode;
   - skill discovery/reload rules and per-agent allowlist;
   - plugin SDK/tool policy supported by the installed version;
   - supported inbound agent-run surface: installed-version Gateway RPC, `/hooks/agent`,
     `/v1/responses`, or another documented surface;
   - whether a generic safe HTTP/MCP tool already exists.
6. Verify dashboard access with a local SSH tunnel to Mila loopback. Do not change bind, firewall,
   auth, or device-pairing settings.
7. Write `swarm-report/mila-openclaw-discovery.md`, separating observed facts, inferences, and
   unknowns. Close Q10 only with evidence.

### Phase 4B: contract and architecture reconciliation

1. Update `.memory-bank/architecture.md`, `.memory-bank/decisions.md`,
   `.memory-bank/open-questions.md`, and `.memory-bank/auth-flow.md` in English.
2. Preserve ADR-009 semantics:
   - Backend owns cron, matching, transfer order, integrations, and PostgreSQL state;
   - confident matches never require an LLM;
   - OpenClaw receives only ambiguous review context and recruiter replies;
   - Mila is active primary; Sylvanas is disabled standby until a separate rollout.
3. Choose network topology from discovery. Preferred first option: Backend adapter and Mila
   Gateway are co-located or connected through private authenticated networking, with management
   surfaces loopback-only. Never publish FastAPI or Gateway directly to the Internet.
4. Replace speculative event delivery with the installed version's documented API. Do not use
   `/tools/invoke` to register Backend tools; it invokes tools already registered in OpenClaw.
5. Define minimal tool contract, normally:
   - `recording_review_get(review_id)`;
   - `recording_review_resolve(review_id, choice, expected_version, idempotency_key)`;
   - `recording_review_ignore(review_id, expected_version, idempotency_key)`;
   - optional `recording_scan_trigger(...)` only if operationally required.
6. Backend executes the ordered transfer pipeline after a valid resolution. Do not expose separate
   model-callable transfer, Notion-update, mark-processed, or delete steps.
7. Bind each review to an opaque one-time token, recruiter, channel/thread, expiry, and DB version.
   Reject ambiguous, expired, replayed, wrong-user, and wrong-channel replies.

### Phase 4C: local adapter, skill, and E2E

1. Install or run OpenClaw `2026.4.22` with Node `22.22.2` in an isolated local profile.
2. Add `openclaw/skills/recording-agent/SKILL.md`, `scripts/recording_agent.py`, and a concise
   contract reference matching Mila's confirmed workspace-skill pattern. Keep the skill a thin
   workflow and safety policy over Backend intents.
3. Keep a classic TypeScript tool plugin out of MVP unless local testing proves the script-backed
   approach cannot meet policy or reliability requirements.
4. Add only evidence-backed FastAPI settings and endpoints. Credentials use `SecretStr`; no
   recruiter IDs, channel IDs, database IDs, or storage paths are literals.
5. Extract scheduler-owned pipeline code only where needed to let the review-resolution service
   reuse it. Preserve status transition guards and transaction boundaries.
6. Add durable delivery/idempotency semantics. Never run inline transfer merely because an
   OpenClaw delivery timed out after it may have been accepted.
7. Run local stack with test-only Yandex folder/calendar, copied Notion DB, MinIO, and test
   Mattermost route. Add startup allowlists that reject production identities and resources.
8. Prove:
   - deterministic confident match completes without OpenClaw;
   - ambiguous match reaches Mila/local OpenClaw;
   - resolve triggers one ordered Backend pipeline;
   - ignore never transfers;
   - retries, duplicate events, duplicate tool calls, and restart do not duplicate side effects;
   - OpenClaw outage leaves recoverable DB state and performs no destructive fallback.
9. Run repository quality gates and full `pytest`; record exact output in build report.

### Phase 5: approval-gated Mila rollout

1. Resolve production inputs needed for the chosen canary: Q1 Synology path, Q3 Mattermost route,
   and Q5 test/production Notion database sharing. Keep Lili disabled until Q8 closes.
2. Before any Mila write, request explicit approval and identify exact target files/services.
   Capture sanitized current metadata and a recoverable backup/rollback path.
3. Deploy versioned plugin and skill to Mila only. Use the discovered supported reload method.
4. Validate tool discovery, policy, Gateway health, dashboard-through-tunnel, and auth failure before
   allowing a mutating test.
5. Run one test-recruiter canary with source deletion and permanent purge disabled. Observe
   OpenClaw, Backend, PostgreSQL, and integration logs plus every status transition.
6. Roll back on duplicate action, auth leak, unexpected production resource access, schema
   mismatch, failed idempotency, dashboard exposure, or unrecoverable state.
7. After Mila acceptance, inspect Sylvanas read-only for version/config skew and write a separate
   approval-gated standby/parity rollout.

## Affected files

- `swarm-report/mila-openclaw-discovery.md`
- `swarm-report/phase-5-mila-rollout-plan.md`
- `.memory-bank/architecture.md`
- `.memory-bank/decisions.md`
- `.memory-bank/open-questions.md`
- `.memory-bank/auth-flow.md`
- `app/config.py`
- `app/routers/events.py` (adapt or remove the speculative stub)
- `app/routers/tools.py`
- `app/services/openclaw.py` (only if outbound invocation is required)
- `app/scheduler/cron.py`
- `app/main.py`
- `docker-compose.yml`
- `openclaw/skills/recording-agent/SKILL.md`
- `openclaw/skills/recording-agent/scripts/recording_agent.py`
- `openclaw/skills/recording-agent/references/contract.md`
- contract, plugin, and E2E tests

Exact plugin and skill paths remain provisional until Mila discovery confirms its layout.

## Tests

- Before/after read-only inventory shows no remote file or service-state change.
- Dashboard works through SSH forwarding; direct public Gateway access remains closed.
- Contract fixtures match the installed Mila auth, payload, tool, response, and error schemas.
- Missing/wrong credentials fail closed; logs contain no secret values.
- Local confident and ambiguous paths reach correct statuses.
- Duplicate delivery/tool call, timeout retry, and restart create one logical side effect set.
- Test mode rejects production recruiter, Notion DB, storage path, Mattermost route, and deletion.
- Full `pytest` and repository quality gates pass.
- Mila canary and rollback checks pass before any broader enablement.

## Blockers

1. **Manual-review invocation:** choose and locally contract-test co-located `openclaw agent` CLI
   or authenticated Gateway WebSocket RPC. Generic webhook and OpenResponses endpoints are not
   currently enabled/proven on Mila.
2. **Mattermost correlation:** Q3 must define DM/channel routing, recruiter identity, thread binding,
   and opaque one-time review tokens.
3. **Production canary inputs:** Q1 and Q5 remain open. They do not block discovery or isolated
   local E2E, but they block a mutating production canary.
4. **Credentials:** the disclosed root/shared credential should be rotated. Production rollout
   should use a named least-privilege account and audited elevation.

No `/build` until blockers 1-2 have approved contracts.

## Out of scope

- Any Sylvanas change.
- Production data processing during discovery.
- Public Gateway/FastAPI exposure or unapproved firewall/VPN/reverse-proxy changes.
- Permanent Yandex Disk purge or Synology deletion.
- Reimplementing deterministic matching, transfer, or integrations inside `SKILL.md`.
- Resolving Lili's Notion schema in the Mila-first phase.

## Assumptions

1. User authorizes read-only Mila SSH discovery, but not remote writes, restarts, installs, config
   changes, agent runs, or production integration calls.
2. Existing FastAPI/PostgreSQL Backend remains source of truth and deterministic executor.
3. Official OpenClaw documentation is guidance; installed Mila version and sanitized live evidence
   decide the final contract.
4. A local exact-version Gateway can be installed or a protocol-faithful mock used temporarily,
   but real local OpenClaw is required before Mila deployment.
