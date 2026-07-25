# Multi-agent server deployment

This directory defines the secretless local artifacts for one trusted-company OpenClaw Gateway
and the Recordings Saver application. It does not authorize a remote rollout.

## Ownership and topology

OpenClaw runs on the host as the non-login `openclaw` user. The example contains Recordings Saver
and one sibling to prove that every agent has a distinct workspace, `agentDir`/auth store, session
directory, LLM profile, Mattermost account, and exact account binding. It has no explicit default
agent or wildcard binding. The static validator requires a one-to-one account/binding mapping, so
an unbound sibling bot cannot fall through to Recordings Saver. These are logical boundaries
inside one trusted Gateway, not tenant isolation.

The Backend and PostgreSQL run in Docker. Backend is published only on
`127.0.0.1:18000`; PostgreSQL is not published. A Recordings Saver release may change only
`/opt/recording-agent/releases/<commit>` and
`/srv/openclaw/workspaces/recordings-saver/skills/recording-agent`. Shared accounts, bindings,
sibling workspaces, credentials, sessions, and services belong to the separately approved
shared-infrastructure workflow.

## Approval gates

Before host mutation:

1. Repeat the read-only inventory and stop on any target-path, ID, account, binding, unit, or port
   collision.
2. Confirm exact Docker Engine, Compose, Node.js, and OpenClaw versions against Ubuntu 26.04.
3. Approve the package/service/firewall manifest. Root SSH hardening is a separate change.
4. Measure idle and peak memory. The fixed 1.9 GiB/no-swap host starts with one concurrent agent
   turn and one deployment operation. Stop unless Gateway, PostgreSQL, and Backend fit with at
   least 384 MiB available headroom and no OOM events.
5. Name the GitHub production-environment approver and confirm GHCR pull and Actions SSH policy.

The bootstrap refuses unpinned versions and pre-existing unowned target paths. Before creating
anything, it records the exact approved path/owner/group/mode layout in the root-owned
`/etc/recording-agent-bootstrap.paths`. A rerun must match that manifest and every existing path
exactly; this permits safe resume after a package/plugin/service failure without adopting an
unowned collision.

```bash
sudo APPROVE_HOST_MUTATION=yes ./deploy/scripts/bootstrap-host.sh
```

The script pins Ubuntu 26.04 Docker `29.1.3-0ubuntu4.1`, Compose
`2.40.3+ds1-0ubuntu1`, Node `24.15.0`, OpenClaw/Mattermost `2026.6.11`, and the official
local-prefix installer by commit SHA. Override a pin only through a reviewed repository change;
missing/latest/wildcard versions are refused.

Run it twice. The second run must preserve users, secrets, bindings, and sibling workspaces.
Install the reviewed systemd unit, sudoers file (validated with `visudo -cf`), and root-owned
scripts under `/usr/local/sbin`. Do not add `deploy` to the Docker group.

## Secrets and agent onboarding

Examples contain names and placeholders only. Runtime Backend secrets live in
`/etc/recording-agent/backend.env`, root-owned mode `0600`. Gateway shared environment is
the single `/etc/openclaw/gateway.env`, root-owned mode `0600`. It contains distinctly named
SecretRef variables for every approved agent and Mattermost account; systemd injects values into
the Gateway process without exposing them in the shared JSON. Provision and rotate this file
out-of-band before deploying a config that references new variables. CI and shared deployment
artifacts never receive it. OpenClaw's per-agent auth/profile store remains in each distinct
writable `agentDir` under `/var/lib/openclaw/agents/<agent>/agent`. Never mount Backend or Gateway
secrets into a workspace.

Use a separate LLM key and Mattermost bot per agent. Transfer secrets through the company secret
manager. If none exists, copy a protected local file directly to a root-only staging path, install
it mode `0600`, verify only schema/profile/provider/type/permissions/fingerprint, then remove the
staging copy. Never put values in Git, chat, CI inputs, command arguments, logs, or shell history.

For Recordings Saver the non-secret LLM settings are `https://llm.effective.land/v1`,
`openai-completions`, primary `gpt-5.4`, fallback `gpt-5.4-mini`. The account label is metadata;
the OpenClaw provider ID is `llm-gateway`. Confirm quota, RPM/TPM/concurrency, IP restrictions,
billing, expiry, rotation, and revocation before activation.

Add agents through the shared-infrastructure workflow only: inventory live state, merge
additively, back up config, validate with the pinned OpenClaw binary, activate atomically, and
test positive and negative bot routing. Wildcard/default catch-all bindings are forbidden.

## CI/CD

CI builds on GitHub, pushes `ghcr.io/seitovaralina/recording-agent` by immutable digest, and stages
the secretless Compose file, skill archive, and reviewed `release-metadata.json`. SFTP sees
`/incoming/<40-hex-commit>/` inside the root-owned
`ChrootDirectory /opt/recording-agent/sftp`; its writable host child is
`/opt/recording-agent/sftp/incoming`. Protected CD computes all three artifact hashes and invokes:

```text
sudo /usr/local/sbin/recording-agent-deploy \
  <commit> <GHCR-image@sha256:digest> <compose-sha256> <skill-sha256> <metadata-sha256>
```

The SSH-authenticated forced command binds the commit, image, Compose, skill, and migration
metadata. Server-generated sidecars are not trusted. After successful health and capacity checks,
the server persists those exact values plus compatibility policy and previous release in
root-owned mode-`0444` `release-manifest.json`. Repeating the exact manifest is verification-only;
any changed field is a collision.

The deploy SSH key must use a pinned host fingerprint and a dedicated `deploy` user. Sudoers
grants only the root-owned dispatcher and rollback executables. The non-root dispatcher validates
the exact command and argument shapes from `SSH_ORIGINAL_COMMAND` before invoking constrained sudo;
the root branch validates every value again.
Use separate restricted keys for `recording-stage` and `deploy`. Keys live in root-owned
`/etc/ssh/authorized_keys/<user>`. The installed sshd `Match` rules chroot the staging identity at
`/opt/recording-agent/sftp`, start internal SFTP in its writable `/incoming` child, and force the
deployment identity through `/usr/local/sbin/recording-agent-deploy`; add `restrict` to both
`authorized_keys` entries as defense in depth. The deploy dispatcher validates
`SSH_ORIGINAL_COMMAND` before using constrained sudo. Neither identity may open an interactive
shell, forward ports, use an agent, or allocate a PTY.
The repository uses one GitHub Environment named `production` with a named approver. Server host,
port, restricted usernames, and the verified SSH host key are versioned non-secret deployment
metadata. GitHub needs only `PRODUCTION_STAGE_KEY` and `PRODUCTION_DEPLOY_KEY`; the same public
keys may be installed for the two staging identities and the two forced-command identities because
their server-side chroots and forced commands enforce scope. Production/LLM/Mattermost/integration
secrets remain server-owned.

Install the two CI public keys after bootstrap:

```bash
sudo deploy/scripts/install-ci-keys.sh \
  /root/recording_agent_production_stage.pub \
  /root/recording_agent_production_deploy.pub
```

The script installs the staging key for `recording-stage` and `openclaw-stage`, and the deploy key
for `deploy` and `openclaw-deploy`. Files are root-owned, group-readable by only the matching
service identity, and not writable by it. All four entries use the OpenSSH `restrict` option;
sshd then applies the per-user chroot or forced command.

### Shared OpenClaw workflow

Shared Gateway changes use different `openclaw-stage` and `openclaw-deploy` keys and always require
manual production approval. SFTP is chrooted at `/opt/recording-agent/sftp` and sees the writable
path `/shared-incoming/<commit>/`, containing only `openclaw.json` and `agents.yml`. The forced
command is:

```text
sudo /usr/local/sbin/openclaw-shared-deploy \
  <commit> <openclaw-config-sha256> <agent-inventory-sha256>
```

The server verifies the SSH-authenticated hashes and requires a valid root-owned mode-`0444`
managed manifest before touching any pre-existing config or inventory. Initial adoption of
unmanaged files is forbidden in this workflow. It rejects live hashes that differ from the
manifest and rejects any candidate that changes or omits an existing agent, Mattermost account,
or binding. Existing inventory bytes must be an exact prefix of the candidate inventory, making
the operation additive. A clean server may start with one real agent; other repositories later
submit the full existing registry plus their own real entry. It validates the candidate with the
pinned OpenClaw binary and runs explicit positive/negative routing checks before mutation.

Before activation it saves the current config, inventory, managed manifest, and a secretless live
binding snapshot under `/opt/recording-agent/shared-backups`. Config and inventory are installed
atomically, Gateway is restarted, RPC and all Mattermost accounts are probed, and routes are
revalidated. Any failure restores the prior files and restarts the prior Gateway. Success writes a
root-owned mode-`0444` manifest binding commit and both hashes. It never copies auth profiles,
sessions, workspace contents, or secret environment files.

Candidate validation, the live binding snapshot, and post-activation RPC/channel probes run as
UID/GID `openclaw` in protected transient systemd units. Each unit loads the root-owned mode-`0600`
`/etc/openclaw/gateway.env` through `EnvironmentFile`, receives the staged or live
`OPENCLAW_CONFIG_PATH` explicitly, and suppresses CLI output where it is not the bounded backup.
The shared deploy refuses to invoke OpenClaw CLI if the environment file is missing, symlinked, or
has different ownership or permissions.

## Canary and activation

Keep scheduler, Notion writes, Mattermost delivery, Yandex mutations, Synology transfer, and
cleanup effects disabled initially. Validate local health and authenticated loopback Backend
access, then explicitly approve external preflights. Test each LLM identity, exact bot-to-agent
routing, wrong/missing/wildcard/stale/duplicate bindings, reconnect deduplication, own-bot event
suppression, and every sibling route. Public access to ports 18789, 18000, and 5432 must fail.

The deploy captures the kernel OOM counter, starts the candidate, waits for steady state, then
requires the fixed 1.9 GiB/no-swap profile, at least 384 MiB `MemAvailable`, no OOM counter
increase, and no OOM-killed Backend/PostgreSQL container. It records bounded Gateway/container
memory metrics. Failure enters the same schema-aware recovery decision as a failed health check.

Enable exactly one scheduler only after its PostgreSQL ownership lock and the Memory Bank's
integration-specific approval gates pass.

## Backup and rollback

The old Backend is stopped before backup and remains quiesced through migration and candidate
activation. Before quiescing or backing up, deploy executes the pinned candidate migration image
with `poetry run alembic heads`. Exactly one head must be returned and it must equal the
authenticated `targetAlembicRevision`; zero, multiple, or mismatched heads fail closed. The same
candidate service later runs `poetry run alembic upgrade head`. Every deploy creates and validates
a custom-format PostgreSQL backup. The versioned
`deploy/release-metadata.json` records the target Alembic revision and one reviewed policy:

- `expand-contract` + `previousApplicationCompatibleWithTargetSchema=true` permits automatic
  previous image/skill recovery after a failed candidate.
- `forward-only` + `false` requires `stop-writes-forward-fix`; the failure trap keeps Backend
  stopped and records a root-only failure marker. An operator may instead approve restoring the
  verified backup after acknowledging loss of post-backup writes.

The current metadata is conservative and declares the existing chain forward-only. Update it in
the same reviewed change as any migration; its authenticated hash is part of the release command
and manifest. Rollback never restores a database automatically and never deletes Compose volumes,
OpenClaw state, secrets, sibling agents, or sessions.

Run `deploy/scripts/validate-static.sh` in CI. It validates Bash syntax, multiple distinct agents,
one exact binding per Mattermost account, no wildcard/default capture, migration metadata
coherence, forced-command hashing, and the SFTP chroot declaration.

Clean-VM bootstrap, pinned package availability on Ubuntu 26.04, live OpenClaw schema/plugin
validation, reboot recovery, public-port denial, measured capacity, LLM failure modes, real
Mattermost positive/negative routing, restore, scheduler lock, and sibling-preservation checks
remain explicit remote rollout gates. Local validation does not claim those tests passed.

## Firewall

`deploy/firewall/recording-agent.nft.example` is intentionally not deployable. Copy it outside
Git, replace the required SSH IPv4/IPv6 CIDR placeholders with administrator-approved source
networks, and replace the monitoring placeholder with explicitly source-restricted rules or a
comment stating that no monitoring ingress is approved. Delete an unused address-family rule;
never substitute a world-open CIDR. No CIDR is guessed by this repository.

The policy accepts loopback and established traffic, accepts new SSH only from approved source
CIDRs, and defaults inbound traffic to drop. It contains no accept rule for Gateway `18789`,
Backend `18000`, or PostgreSQL `5432`; those services must remain loopback-only.

Validate without mutation:

```bash
sudo /usr/local/sbin/recording-agent-firewall check /root/reviewed-firewall.nft
```

Apply only with console/recovery access available:

```bash
sudo APPROVE_FIREWALL_APPLY=yes \
  /usr/local/sbin/recording-agent-firewall apply /root/reviewed-firewall.nft
```

Apply snapshots the complete active ruleset and arms a 120-second automatic rollback before
changing the `recording_agent` table. Establish a new SSH connection from an approved CIDR. Only
from that proven connection confirm and persist:

```bash
sudo APPROVE_FIREWALL_CONFIRM=yes /usr/local/sbin/recording-agent-firewall confirm
```

If reconnect or validation fails, do not confirm; the timer restores the snapshot. Preserve the
backup for recovery. The firewall artifact does not authorize disabling root SSH or changing
provider-level network controls.

Required outbound access is DNS plus HTTPS/WSS to GHCR, the LLM Gateway, Mattermost, Яндекс,
Notion, and the approved Synology endpoint. Inbound access is restricted to approved SSH sources
and intentional monitoring; no public Gateway, Backend, or PostgreSQL listener is allowed.
