# Plan: Install a multi-agent OpenClaw server environment

Slug: `multi-agent-server-environment`

## TL;DR

Build a shared, non-root OpenClaw Gateway on `217.149.19.21` for agents that belong to one
trusted operator boundary. Give every agent its own OpenClaw identity, workspace, skills, state,
LLM auth profile, and Mattermost bot account with an explicit account-to-agent binding. Run the
Recording Agent Backend and PostgreSQL in Docker, exposed only on host loopback so the existing
`127.0.0.1` skill contract remains unchanged.

Build application images in CI, publish immutable artifacts, and deploy only the files owned by
Recordings Saver. Shared Gateway configuration changes use a separate, approval-gated workflow
that rejects unexpected drift or deletion of another developer's agent. Server-owned secrets
never pass through Git, container images, workflow inputs, command-line arguments, or logs.

The current host has 2 vCPU, 1.9 GiB RAM, no swap, and no Docker/OpenClaw installation. The owner
has confirmed that the agents share one company trust boundary, GitHub Actions/GHCR will be used,
and the server capacity cannot be changed. Images must therefore be built in CI, runtime
concurrency must be bounded, and rollout must stop rather than overcommit the host if measured
memory does not fit.

## Target topology

```text
Mattermost bot: recordings-saver ----\
Mattermost bot: agent-b --------------> OpenClaw Gateway (host systemd, non-root)
Mattermost bot: agent-c --------------/    |
                                             +-- agent: recordings-saver
                                             |     workspace + skills + auth + sessions
                                             +-- agent: agent-b
                                             |     workspace + skills + auth + sessions
                                             +-- agent: agent-c
                                                   workspace + skills + auth + sessions

Recordings Saver skill
    -> http://127.0.0.1:18000
    -> Docker: Recording Agent Backend
    -> Docker: PostgreSQL
```

This is logical routing and state separation, not a hostile security boundary. If agents,
developers, or customers do not mutually trust the same host operator, replace the shared Gateway
with one Unix user plus Gateway/container, credential tree, systemd unit, and network per trust
domain.

### Mattermost ownership

| Concern | Owner |
|---|---|
| Inbound WebSocket events for one bot | Exactly one OpenClaw Mattermost account |
| Bot account to agent routing | Explicit OpenClaw binding; no wildcard/catch-all binding |
| Recruiter DM allowlist | Agent-specific OpenClaw and Backend configuration |
| Conversational replies | Bound OpenClaw agent only |
| Recording pipeline proactive notifications | Backend REST calls using the Recordings Saver bot identity |
| Durable question/outbox state | Recording Agent PostgreSQL |

OpenClaw is the only inbound consumer for the Recordings Saver bot. Backend may send outbound REST
messages as that bot but must not open a second event consumer. Tests must prove that bot-authored
events are ignored/deduplicated and that restart/reconnect does not duplicate notifications.

## Acceptance criteria

### Host and runtime

- The supported Docker Engine/Compose, Node.js, and OpenClaw versions are pinned and verified on
  Ubuntu 26.04 before mutation.
- OpenClaw runs under a dedicated non-root service user. Recording Agent containers also run
  non-root where their image/runtime permits.
- The CI deploy user has a dedicated key and constrained, path-scoped sudo commands. It is not
  added to the general Docker group unless its root-equivalent privilege is explicitly accepted.
- External inbound access is limited to approved SSH sources and intentional monitoring.
  OpenClaw Gateway, Backend, and PostgreSQL are not reachable through the public interface.
- Required outbound DNS, HTTPS, WSS, registry, LLM, Mattermost, Yandex, Notion, and Synology
  connectivity is documented and tested.
- A measured capacity gate passes on the fixed 1.9 GiB/no-swap host using strict service/container
  memory limits and reduced concurrency. Image builds never run on the VDS. If the measured
  Gateway, PostgreSQL, and Backend footprint does not fit with safe headroom, rollout stops and
  reports that the fixed host cannot safely run the requested agent count.
- Reboot restores the Gateway and the Compose stack without regenerating secrets or changing
  bindings.

### Multi-agent OpenClaw

- Every agent has a distinct ID, workspace, skills directory, state/auth directory, session store,
  LLM profile, and Mattermost account.
- Each Mattermost bot account has one explicit binding to one agent. No default or catch-all route
  can capture another bot's messages.
- Bot A cannot route a DM to Agent B, and an ordinary Recordings Saver deploy cannot edit or delete
  sibling workspaces, credentials, bots, bindings, or state.
- Recordings Saver receives only the versioned
  `openclaw/skills/recording-agent/` artifact and continues to call the authenticated Backend at
  `http://127.0.0.1:18000`.
- Shared Gateway configuration is declarative, backed up before change, validated with the pinned
  OpenClaw version, and changed only through an approval-gated shared-infrastructure workflow.

### LLM and secrets

- Each agent uses a newly issued, agent-specific API key unless the administrator explicitly
  authorizes shared use and accepts mixed quota/audit/revocation impact.
- A non-secret manifest records provider name, base URL, API dialect, primary/fallback model IDs,
  timeout, rate/concurrency/token limits, billing owner, IP restrictions, expiry, and rotation
  contact.
- Per-agent auth files or supported SecretRefs are readable only by the OpenClaw service identity.
- Keys and tokens never appear in Git, `.env` examples, container layers, workflow inputs,
  workflow logs, shell history, process arguments, deployment records, or test output.
- A minimal redacted inference succeeds for each agent identity and its allowed models; invalid or
  revoked credentials fail closed without leaking authorization data.

### CI/CD and rollback

- Pull requests run `pytest`, `ruff check .`, `mypy app`, Compose/config validation, an image build,
  and secret scanning.
- A successful protected-branch/tag build publishes an immutable image identified by commit and
  digest. GitHub Actions and base images are pinned by commit/digest if GitHub/GHCR is selected.
- The application deploy workflow sends only artifact identifiers and release metadata. Secrets
  stay on the server.
- Deployment uses a pinned SSH host fingerprint, a dedicated deploy key, a protected production
  environment, named approvers, and an allowlisted deployment path.
- Alembic runs as a one-shot job after a verified backup. Every migration declares compatibility
  with the previous application release and follows expand/contract rules.
- Automatic image rollback occurs only when the previous image is compatible with the upgraded
  schema. Otherwise deployment stops writes and requires a forward fix or an operator-approved
  restore. A restore is never presented as a lossless automatic rollback.
- Repeating deployment of the same commit is idempotent. Failed health/smoke checks preserve
  PostgreSQL volumes, agent state, secrets, and sibling agents.
- Scheduler remains disabled through canary. Production has exactly one scheduler owner; overlap
  is prevented by deployment sequencing and a PostgreSQL advisory/distributed lock.

## Plan

### 1. Resolve ownership, trust, CI, and capacity gates

1. Repeat a read-only inventory immediately before installation: users, services, ports, files,
   repositories, containers, mounts, OpenClaw state, and recent changes.
2. Treat other developers' agents as out of scope. Refuse to overwrite any pre-existing target
   path, agent ID, Mattermost account, binding, or systemd unit; report a collision instead.
3. Use the confirmed shared-company trust boundary and one shared Gateway with logical separation.
4. Use the confirmed GitHub repository `SeitovaRalina/Recording-Agent`, GitHub Actions, and GHCR.
   Confirm private package access, server pull credentials, SSH reachability, branch protection,
   package retention, environment approvers, and shared-infrastructure ownership.
5. Measure estimated and observed memory for OpenClaw, PostgreSQL, Backend, and the required
   concurrent agents on the fixed host. Define strict memory limits, safe headroom, bounded logs,
   and initial concurrency of one agent turn/deployment operation at a time. Block rollout if the
   measured stack cannot fit; do not add swap or change server capacity.

### 2. Create declarative host and ownership manifests

Define the following non-secret ownership layout:

```text
/var/lib/openclaw/                       shared Gateway state
/srv/openclaw/workspaces/<agent>/        one workspace per agent
/etc/openclaw/                           protected shared config and secret references
/etc/openclaw/agents/<agent>/            protected per-agent auth material
/opt/recording-agent/releases/<commit>/  immutable Recordings Saver releases
/opt/recording-agent/current             atomic active-release link
/etc/recording-agent/                    Backend secrets, never mounted into workspace
```

Create an additive agent/account registry containing no tokens. A Recordings Saver application
deploy owns only its release subtree and its workspace skill subtree. It refuses unexpected drift
or deletion. Shared bindings/accounts are owned by a separate reviewed workflow.

### 3. Bootstrap and harden the host

1. Pin exact Docker Engine/Compose, Node.js, and OpenClaw versions after compatibility probes.
2. Create dedicated `openclaw` and `deploy` users, directories, ACLs, and constrained sudo rules.
3. Install Docker/Compose and host-level OpenClaw. Do not build application images on the host.
4. Configure systemd restart policy and hardening for the Gateway.
5. Configure firewall rules:
   - inbound: approved SSH sources and intentional monitoring only;
   - loopback-only: Gateway UI/API, Backend `18000`, PostgreSQL;
   - outbound: DNS/HTTPS/WSS and required integration destinations.
6. Configure service/container memory limits, OOM monitoring, bounded logs, disk alerts, and a
   concurrency ceiling. Do not configure swap or perform a server resize.
7. Run bootstrap twice and verify that the second run preserves users, secrets, bindings, and
   sibling workspaces.
8. Disable root SSH only in a separately approved hardening change after deploy access and recovery
   access have been proven.

### 4. Configure multi-agent OpenClaw

1. Validate the exact pinned OpenClaw schema and commands for:
   - multiple agents and per-agent workspaces/auth directories;
   - multiple Mattermost accounts;
   - deterministic account-to-agent binding precedence;
   - default-agent behavior;
   - configuration validation and reload/restart semantics.
2. Create Recordings Saver and every known sibling agent additively.
3. Install each agent's own skills only into its workspace.
4. Register one Mattermost bot account per agent and bind the exact account to the exact agent.
5. Forbid wildcard bindings. Configure agent-specific DM allowlists and minimum bot permissions.
6. Back up, validate, and atomically activate the shared configuration.
7. Test positive and negative routing before any production integration is enabled.

### 5. Transfer and configure new LLM credentials

Do not send key values in ChatGPT, Mattermost, GitHub issues, Git, or CI workflow inputs.

Preferred handoff:

1. The administrator creates a separate key for each agent and shares it through the
   organization's approved password/secret manager to an authorized operator.
2. The operator installs the key directly into the server-side secret store or per-agent OpenClaw
   auth profile without exposing it to CI.

Fallback handoff when no secret manager exists:

1. Save the issued secret locally outside this repository, for example:
   `$env:USERPROFILE\.ssh\recordings-saver-llm.env`.
2. Restrict the Windows ACL to the current user.
3. Tell the deployment operator only the local file path, never the key value.
4. Copy it directly with SCP to a temporary server path readable only by the receiving operator.
5. Install it into the pinned OpenClaw version's per-agent auth store with mode `0600`.
6. Verify only profile name, permissions, and a cryptographic file fingerprint.
7. Remove the temporary transfer copy; retain only the managed runtime secret and approved backup.

For every key, obtain and validate:

- provider and billing owner;
- base URL and TLS hostname;
- API dialect;
- primary and fallback model IDs;
- RPM/TPM/concurrency/context limits and total quota;
- IP allowlist;
- expiry, rotation, and revocation process.

The owner has confirmed that Recordings Saver must use the same non-secret provider settings as
Mila: base URL `https://llm.effective.land/v1`, API dialect `openai-completions`, primary model
`gpt-5.4`, and fallback `gpt-5.4-mini`. Only the newly rotated Recordings Saver key may be reused;
Mila's key must not be copied.

Use a minimal synthetic prompt for the preflight. Never copy Mila's key to this host.

The repository `.env` is ignored by Git. The required Recordings Saver Mattermost variables
(`MATTERMOST_URL`, `MATTERMOST_BOT_TOKEN`, and `MATTERMOST_BOT_USER_ID`) are present and non-empty;
their values must remain local/server-owned and must never be printed.

The first attempted `recordings_saver_llm_auth.json` contained two nested JSON objects and was not
a valid OpenClaw auth store. Its diagnostic output exposed both contained LLM keys, so both keys
must be revoked/reissued before deployment. After rotation, create exactly one protected profile:

```json
{
  "version": 1,
  "profiles": {
    "llm-gateway:default": {
      "type": "api_key",
      "provider": "llm-gateway",
      "key": "<new-rotated-key>"
    }
  }
}
```

Do not paste the replacement key into chat. Validate the replacement file with a non-echoing
validator that reports only valid/invalid schema, profile ID, provider, type, file permissions,
and a one-way fingerprint. Parser exceptions must be sanitized so they cannot echo source text.

### 6. Define the production Recording Agent stack

1. Create a production Compose manifest separate from the current test-only
   `docker-compose.yml`.
2. Include PostgreSQL, one-shot migration, and Backend services with named volumes, healthchecks,
   restart/resource limits, and localhost-only Backend port `18000`.
3. Remove MinIO/test defaults from production. Start with scheduler, Notion writes, Yandex
   mutations, Synology transfer, Mattermost delivery, and cleanup effects disabled as required by
   the existing canary gates.
4. Keep Backend integration secrets in `/etc/recording-agent/`; do not mount them into OpenClaw
   workspaces.
5. Configure the Recordings Saver skill with only its loopback Backend URL, trusted invocation
   metadata, and a scoped shared Backend authentication secret.
6. Enforce a single Backend scheduler replica and add a database-backed ownership lock before
   scheduler activation.

### 7. Implement CI

Using the confirmed GitHub Actions and GHCR platform:

1. Run tests, lint, type checking, Compose/OpenClaw config validation, secret scanning, and image
   build on every pull request.
2. Build a deterministic production image from locked dependencies and pinned base images.
3. Produce SBOM/provenance where supported.
4. Publish by commit tag and immutable digest only after checks pass.
5. Do not store production application, LLM, Mattermost, or integration secrets in repository CI.
   CI may hold only the scoped deploy key and registry credentials needed for delivery.

### 8. Implement scoped CD

Separate two deployment workflows:

1. **Recordings Saver application deploy**
   - automatic after protected-branch/tag approval;
   - restricted to `/opt/recording-agent` and the Recordings Saver skill subtree;
   - pulls image by digest;
   - records previous commit/digest/skill artifact;
   - takes and verifies the database backup;
   - runs the migration compatibility gate and one-shot migration;
   - switches the Backend and skill release atomically;
   - runs health and smoke tests;
   - cannot edit shared Gateway accounts or sibling agents.
2. **Shared OpenClaw infrastructure deploy**
   - always manual and approval-gated;
   - inventories and compares live config;
   - rejects unexpected drift/deletions by default;
   - backs up shared config;
   - validates bindings using the pinned OpenClaw version;
   - applies additive changes and tests every bot/agent route;
   - rolls back the config artifact if routing or Gateway health fails.

The deploy user uses a pinned `known_hosts` fingerprint and constrained server-side commands. Do
not grant arbitrary shell, unrestricted sudo, or unscoped Docker control to CI.

### 9. Test, canary, and activate

1. Validate configuration offline with placeholders.
2. Start PostgreSQL and Backend with scheduler and external mutations disabled.
3. Confirm Backend health and authenticated loopback access.
4. Run per-agent LLM preflights.
5. Run one allowlisted Recordings Saver Mattermost DM and prove:
   - correct bot identity;
   - correct agent/workspace/skills;
   - no sibling routing;
   - no duplicate response;
   - reconnect after Gateway restart;
   - no shared-channel fallback.
6. Test proactive Backend delivery and confirm OpenClaw ignores/deduplicates the bot's own outbound
   event.
7. Regress every sibling bot after a Recordings Saver release.
8. Enable the scheduler and each production integration only through the separate approvals
   already required by the Memory Bank.

### 10. Backup and rollback

1. Back up PostgreSQL before migrations and test restoration on a separate volume.
2. Back up secretless OpenClaw configuration, agent registry, workspace metadata, and release
   manifests. Back up secrets only through the approved secret-management process.
3. Record whether each migration is backward-compatible with the previous image.
4. On failed deploy:
   - if schema-compatible, restore the previous image digest and skill/config artifact;
   - if not schema-compatible, stop writes and forward-fix;
   - use operator-approved database restore only after acknowledging loss of post-backup writes.
5. Never use `docker compose down -v`, delete named volumes, or purge agent state during rollback.

## Affected files

| Path | Planned change |
|---|---|
| `Dockerfile` | Deterministic production, non-root image with pinned dependencies. |
| `.dockerignore` | Exclude Git data, `.env*`, credentials, caches, test artifacts, and local secrets. |
| `compose.prod.yml` | Production PostgreSQL, migration, and Backend services with loopback exposure and limits. |
| `.env.production.example` | Variable names and safe placeholders only. |
| `deploy/inventory/agents.example.yml` | Secretless additive agent/account ownership registry. |
| `deploy/openclaw/openclaw.example.json` | Secretless multi-agent/account/binding template for the pinned version. |
| `deploy/systemd/openclaw-gateway.service` | Non-root Gateway service and hardening. |
| `deploy/systemd/recording-agent-deploy.sudoers` | Constrained deploy command allowlist. |
| `deploy/scripts/bootstrap-host.sh` | Idempotent host bootstrap without secrets. |
| `deploy/scripts/deploy.sh` | Scoped immutable release, backup, migration gate, activation, and verification. |
| `deploy/scripts/rollback.sh` | Schema-aware release/config rollback without volume deletion. |
| `deploy/scripts/smoke-test.sh` | Backend, LLM, binding, routing, and sibling regression checks. |
| `deploy/README.md` | Topology, ownership, secret handoff/rotation, onboarding, CI/CD, backup, and rollback runbook. |
| `.github/workflows/ci.yml` | Conditional on GitHub decision: checks, build, scan, evidence. |
| `.github/workflows/deploy.yml` | Conditional on GitHub decision: protected, digest-based scoped deployment. |
| `openclaw/skills/recording-agent/` | No contract change; package as an atomic Recordings Saver artifact. |

## Required tests

- Bootstrap a clean Ubuntu 26.04 test VM twice; second run makes no destructive or secret changes.
- Validate `compose.prod.yml` with missing required secrets failing clearly and rendered output not
  containing token values.
- Run and cite `pytest`; also pass `ruff check .` and `mypy app`.
- Verify the application image runs non-root and reaches healthy state within a bounded timeout.
- Prove public IP access fails for Gateway, Backend, and PostgreSQL.
- Restart systemd, Docker, and the host; confirm deterministic recovery.
- Route Bot A only to Agent A and Bot B only to Agent B; test missing, wrong, wildcard, stale, and
  duplicate account/binding cases.
- Prove the Recordings Saver skill calls only the authenticated loopback Backend and fails closed
  with an invalid Backend secret.
- Test valid, invalid, expired, and revoked per-agent LLM keys without token leakage in logs.
- Deploy release N, deploy N+1, and repeat N+1 to prove idempotence and exact commit/digest records.
- Force a health failure and test both rollback paths: schema-compatible image rollback and
  incompatible-schema stop/forward-fix.
- Start overlapping Backend instances and prove only one scheduler obtains ownership.
- Restore a production-like PostgreSQL backup into a separate volume and verify schema/data.
- Verify a Recordings Saver deploy leaves every sibling workspace, bot binding, credential file,
  service, and session store unchanged.

## Blockers

There are no unresolved blockers for the local implementation and review cycle.

Remote rollout remains gated on:

1. **LLM runtime file:** the key has been reissued, but the local auth file must use
   `provider: "llm-gateway"` before transfer. The separately supplied account/login label is
   metadata, not the OpenClaw provider ID.
2. **LLM operational metadata:** confirm limits, IP policy, expiry, billing owner, and
   rotation/revocation for the new per-agent key. Endpoint and models are already confirmed from
   Mila.
3. **GitHub deployment policy:** name the production environment approver and confirm that GHCR
   package access and SSH deployment from GitHub Actions are allowed.
4. **Host mutation approval:** approve the exact pinned package/service/firewall/directory manifest
   produced by this build after the final read-only inventory.

## Out of scope

- Copying Mila credentials or personal OAuth tokens.
- Putting real secret values in this plan, Git, CI, chat, or container images.
- Changing Recording Agent business logic, matching, integration contracts, or destructive-action
  policy.
- Enabling production Notion writes, Synology transfer, Yandex mutation/cleanup, or scheduler
  before their separate approvals.
- Public Gateway ingress, reverse proxy, or domain/TLS unless the selected Mattermost transport
  requires inbound callbacks.
- High availability, multiple scheduler replicas, Kubernetes, or multi-host orchestration.
- Treating one shared Gateway as isolation for hostile tenants.
- Discovering, modifying, or taking ownership of another developer's agent. Deployment only
  detects and refuses collisions with out-of-scope paths or bindings.

## Assumptions

- The agents belong to one company and share one trusted operator/security boundary.
- Each agent receives a distinct Mattermost bot and preferably a distinct LLM key.
- The Mattermost adapter uses outbound HTTPS/WSS for ordinary DM operation; native inbound slash
  command callbacks remain disabled unless separately required.
- OpenClaw runs on the host so the existing loopback-only Recordings Saver skill contract remains
  valid.
- Backend/PostgreSQL run in Docker; images are built in CI rather than on the 2 GiB VDS.
- Source and CI/CD use `SeitovaRalina/Recording-Agent`, GitHub Actions, and GHCR.
- Server capacity is fixed at 2 vCPU, 1.9 GiB RAM, and no swap; the implementation must fit within
  measured limits or fail the rollout gate.
- The current `docker-compose.yml` remains test-only and is never reused as the production
  manifest.
