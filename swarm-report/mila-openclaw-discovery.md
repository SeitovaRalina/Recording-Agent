# Mila OpenClaw read-only discovery

Date: 2026-07-20 UTC

## Scope

Read-only SSH inventory of Mila (`31.130.128.236`). No remote file writes, config changes,
installs, restarts, agent invocations, production integration calls, or firewall changes were
performed.

Secret values are intentionally omitted. A local dashboard tunnel was created; it does not change
Mila's listener or firewall.

## Observed facts

### Host and runtime

- Host: `ams-1-vm-gfe4`, Ubuntu 24.04.4 LTS, x86_64.
- SSH user: `root`.
- OpenClaw executable: `/usr/bin/openclaw`.
- OpenClaw: `2026.4.22` (`00bd2cf`), stable channel, package install managed with pnpm.
- Node: `22.22.2`; installed OpenClaw package declares Node `>=22.14.0`.
- npm: `10.9.7`.
- A newer OpenClaw version exists, but no update was attempted.

### Gateway and dashboard

- Gateway mode: local.
- Gateway service: OpenClaw-managed user systemd unit
  `~/.config/systemd/user/openclaw-gateway.service`.
- Service state: enabled and running.
- Command: Node runs OpenClaw Gateway on port `18789`.
- Bind: loopback only, `127.0.0.1:18789` and `[::1]:18789`.
- Authentication mode: token.
- Dashboard: `http://127.0.0.1:18789/` on Mila.
- A second OpenClaw-owned listener exists on `127.0.0.1:18791`; its purpose was not established.
- Other related services reported by Gateway diagnostics: user
  `openclaw-watchdog.service` and system `mila-prober.service`.
- Local SSH forwarding `127.0.0.1:18790 -> Mila 127.0.0.1:18789` returned HTTP 200 and the
  OpenClaw UI. Mila's Gateway remained loopback-only.

### Agent and workspace

- Default and only reported agent: `main`.
- Workspace: `/root/.openclaw/workspace`.
- Session store: `/root/.openclaw/agents/main/sessions/sessions.json`.
- Model reported by current main sessions: `gpt-5.4`.
- Heartbeat is enabled every 30 minutes.
- Mattermost direct and channel sessions already exist.
- Existing workspace is a general-purpose personal agent workspace with unrelated operational and
  document artifacts. Recording Agent must therefore be isolated by skill scope, narrow Backend
  endpoints, and explicit test/production guards.

### Skills

- Workspace skill root is confirmed as `/root/.openclaw/workspace/skills`.
- Existing eligible workspace skills include `gog` and `yandex-forms`.
- Both demonstrate the accepted Mila pattern: a small `SKILL.md` that instructs the agent to use a
  bundled CLI/script.
- Managed skill directory `/root/.openclaw/skills` contains no files.
- No skill allowlist currently blocks the eligible workspace skills.
- Existing `yandex-forms` confirms that workspace skill changes can supply scripts without a
  native OpenClaw tool plugin.

### Tools, plugins, MCP, and channels

- Agent tool policy does not define an allow/deny override. Only web search is disabled and web
  fetch is enabled. The existing script-backed skills therefore rely on the normal host execution
  tool surface.
- Mattermost bundled channel plugin `2026.4.22` is explicitly enabled and loaded.
- Mattermost plugin registers one HTTP channel route but no agent-callable tools.
- No MCP servers are configured.
- Installed OpenClaw exports the classic plugin SDK, including `plugin-sdk/plugin-entry`, and can
  install local `.ts`/`.js` plugins. The newer `defineToolPlugin` workflow documented for
  OpenClaw `>=2026.5.17` must not be assumed compatible with this host.
- Several bundled extensions in this version register tools through the classic plugin API.

### Supported invocation surfaces

- `openclaw agent --agent <id> --message <text>` is available and runs a turn through the Gateway.
- It supports JSON output and optional delivery to Mattermost.
- `openclaw gateway call <method>` is available over authenticated WebSocket RPC.
- OpenResponses `/v1/responses` is not enabled in current config.
- This version's `openclaw webhooks` CLI exposes Gmail helpers only; a generic `/hooks/agent`
  contract was not established from the installed CLI.
- `/tools/invoke` must not be treated as Backend-tool registration. It invokes tools already owned
  by OpenClaw.

## Security finding

`/root/.openclaw/workspace/TOOLS.md` contains an OAuth token in plaintext. The value is omitted from
this report. It should be rotated, removed from workspace instructions and history where practical,
and supplied through OpenClaw secrets or service environment. No remote remediation was performed
because it would be a production write and credential change.

The shared root credential disclosed for this task should also be rotated. Long-term access should
use a named least-privilege account with audited elevation.

## Conclusions

### Recommended Mila MVP boundary

Use a workspace skill package, not a new native plugin initially:

```text
/root/.openclaw/workspace/skills/recording-agent/
  SKILL.md
  scripts/recording_agent.py
  references/contract.md
```

The script calls narrow authenticated FastAPI endpoints. Deploy Backend on Mila and bind it to
`127.0.0.1:8000`; the skill script also calls loopback. Secrets stay in Backend/OpenClaw service
environment, never in `SKILL.md`, `TOOLS.md`, command examples, or script literals.

Backend remains the only scheduler, matcher, transfer executor, and PostgreSQL state owner.
Confident matches never invoke OpenClaw. Mila handles only ambiguous review presentation and the
recruiter's resolve/ignore intent. Backend then executes the ordered transfer pipeline.

Expose narrow intents only:

- get a bounded review context;
- resolve a review with expected state/version and idempotency key;
- ignore a review with expected state/version and idempotency key;
- optionally trigger a scan if the operational Mattermost command requires it.

Do not expose model-callable transfer, Notion update, mark-processed, or deletion primitives.

### Why not a native plugin first

- Mila already uses script-backed workspace skills successfully.
- It avoids an OpenClaw upgrade and Gateway restart during the first integration.
- It is easier to reproduce locally at exactly `2026.4.22`.
- Backend owns type validation and side-effect ordering.

A classic native plugin remains a later option if typed tool discovery, richer UI, or removal of
host `exec` dependency becomes valuable.

### Dashboard access

Dashboard is available through an SSH local-forward. During discovery it was reachable at
`http://127.0.0.1:18790/`. Authentication still uses Mila's Gateway token. The token must not be
printed or embedded in documentation. Do not expose port `18789` publicly.

## Remaining blockers

1. Decide how Backend starts a Mila turn for a new manual review. Installed-version candidates are
   co-located `openclaw agent` CLI or authenticated Gateway WebSocket RPC. Contract-test the chosen
   route locally; do not invent an HTTP endpoint.
2. Resolve Mattermost delivery and reply correlation (Q3): DM versus channel, recruiter identity,
   thread binding, opaque one-time review token, expiry, and replay protection.
3. Resolve Q1 and Q5 before a mutating production canary: Synology path rules and directly shared
   Notion database ID/schema.
4. Pin a local OpenClaw `2026.4.22` test environment before implementation. Upgrade planning is a
   separate change with its own compatibility and rollback review.

## Read-only command families used

- OpenClaw version, status, Gateway status/help, skills list, plugin list/inspect, MCP list, and CLI
  help.
- `ss -ltnp` and process metadata without command-line secret arguments.
- `jq` projections limited to non-secret configuration fields.
- File-name inventory and selected instruction/skill reads.

No recursive configuration dump or secret-bearing environment inspection was performed.
