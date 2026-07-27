# Build report: Multi-agent server environment

## Status

Implementation and deploy-only server bootstrap complete. The Recordings Saver application,
skill, OpenClaw production config, auth profile, and integration secrets were intentionally not
deployed; their activation remains CI-controlled.

## DevOps scope

Changed:

- `Dockerfile`
- `.dockerignore`
- `compose.prod.yml`
- `.github/workflows/ci.yml`
- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-openclaw.yml`

Implemented:

- deterministic non-root production image with a digest-pinned Python base;
- production PostgreSQL/migration/Backend Compose stack with loopback-only Backend exposure,
  healthchecks, bounded logs, and fixed-host resource limits;
- GitHub Actions checks, immutable GHCR publication, SBOM/provenance, and changed-file secret scan;
- protected production deployment using pinned host keys, chrooted SFTP-only staging identities,
  separate forced-command deploy identities, and SSH-authenticated commit/image/artifact hashes;
- a manual, production-environment-approved shared OpenClaw deployment which stages only the
  reviewed registry/config pair and invokes the constrained server-side dispatcher;
- CI validation for deployment scripts, workflow syntax, multi-agent routing invariants, and the
  pinned OpenClaw package/config in a secretless environment.

DevOps verification:

```text
docker compose -f compose.prod.yml config --quiet: pass
PyYAML workflow/Compose parsing: pass
pinned docker build: pass
container runtime user: 10001:10001
container health: healthy
GET /health: {"status":"ok"}
detect-secrets changed scope: 0 findings
```

## Deployment/OpenClaw scope

Changed:

- `.env.production.example`
- `deploy/inventory/agents.example.yml`
- `deploy/openclaw/openclaw.example.json`
- `deploy/systemd/openclaw-gateway.service`
- `deploy/systemd/recording-agent-deploy.sudoers`
- `deploy/systemd/openclaw-shared-deploy.sudoers`
- `deploy/release-metadata.json`
- `deploy/firewall/recording-agent.nft.example`
- `deploy/scripts/bootstrap-host.sh`
- `deploy/scripts/deploy.sh`
- `deploy/scripts/install-firewall.sh`
- `deploy/scripts/install-ci-keys.sh`
- `deploy/scripts/openclaw-shared-deploy.sh`
- `deploy/scripts/rollback.sh`
- `deploy/scripts/smoke-test.sh`
- `deploy/scripts/validate-static.sh`
- `deploy/README.md`

Implemented:

- additive one-company trusted Gateway/agent registry with explicit Mattermost account
  bindings, no wildcard/default route, separate workspace/state/auth paths, and per-agent
  concurrency;
- Mila-compatible secretless LLM provider/model configuration;
- pinned, approval-gated Ubuntu 26.04 bootstrap with collision refusal, non-root Gateway service,
  constrained staging/deploy identities, and no Docker-group grant;
- commit/digest-bound staged release validation, safe skill archive checks, database backup and
  verification, write quiescing before one-shot Alembic migration, atomic release/skill
  activation, post-start memory/OOM checks, and metadata-driven schema-aware failure handling;
- additive shared OpenClaw rollout with current-state drift/deletion refusal, root-owned backup,
  pinned config validation, explicit positive/negative route assertions, atomic activation,
  service probes, and automatic restore on failure;
- collision refusal for pre-existing unmanifested shared OpenClaw files and strict verification of
  the root-owned live manifest before additive updates;
- one protected root-owned Gateway environment for arbitrary inventoried agents, used without
  printing values by both the service and approved external preflight;
- candidate-image Alembic head verification against the authenticated migration metadata before
  backup or migration;
- an explicit nftables template and check/apply/confirm utility with unresolved-CIDR refusal,
  syntax checking, default-deny policy, a timed automatic rollback, and reconnect confirmation;
- resumable bootstrap ownership checks and actual SFTP chroots with writable child directories;
- runbook for capacity, secrets, GitHub environment setup, canary, activation, and recovery.

Deployment/OpenClaw verification:

```text
bash -n for the original deployment scripts: pass
final bash -n including openclaw-shared-deploy.sh: unavailable (local approval quota)
OpenClaw JSON parse and explicit routing assertions: pass
agent inventory YAML parse, unique IDs, concurrency limits: pass
second-review invariants (managed manifest, Gateway env, image schema head, firewall): pass
poetry run alembic heads: b9b12bbd4cb0 (head)
credential-pattern scan: no findings
git diff --check: clean
```

## Combined verification

```text
poetry run pytest -q
290 passed, 1 warning in 111.05s

poetry run ruff check app tools tests alembic
All checks passed!

poetry run mypy app tools tests
Success: no issues found in 84 source files

RECORDING_AGENT_ENV_FILE=.env.production.example docker compose \
  --env-file .env.production.example -f compose.prod.yml config --quiet
pass

JSON/YAML parse for OpenClaw, migration metadata, inventory, and workflows
4 YAML and 2 JSON files validated
```

The pytest warning is the existing Windows permission failure while writing `.pytest_cache`.
The final deploy tree was copied to Ubuntu 26.04 and both `bash -n deploy/scripts/*.sh` and
`deploy/scripts/validate-static.sh` passed there.

## Server environment rollout

Installed on `217.149.19.21`:

```text
Docker package: 29.1.3-0ubuntu4.1 (enabled, active)
Compose package: 2.40.3+ds1-0ubuntu1
Node: 24.15.0, local-prefix OpenClaw runtime
OpenClaw: 2026.6.11 (e085fa1)
Mattermost plugin: 2026.6.11
bootstrap second run: Result=success, ExecMainStatus=0
visudo (both policies): parsed OK
sshd -t: pass
systemd-analyze verify openclaw-gateway.service: pass
recording-stage SFTP cwd: /incoming
openclaw-stage SFTP cwd: /shared-incoming
deploy/openclaw-deploy arbitrary command: rejected
Docker group members: none
containers: none
OpenClaw Gateway: disabled, inactive
nftables: inactive (CIDRs remain an administrator-owned gate)
```

The correct bootstrap source remains `/root/recording-agent-server/deploy`. The erroneous duplicate
copy and temporary public-key staging files were removed. Private CI keys remain only in the local
`.ssh` directory and were not printed or copied into the repository.

## Remaining activation gates

The following remain intentionally unexecuted:

- normalize the rotated local auth profile to `provider: "llm-gateway"` and transfer it without
  printing the key;
- confirm LLM quota/IP/expiry/billing/rotation metadata;
- create the single GitHub `production` environment and set `PRODUCTION_STAGE_KEY` and
  `PRODUCTION_DEPLOY_KEY`; GitHub Variables are not required;
- provide a server-side GHCR pull credential if the package is private;
- merge to `main` before allowing CI to deploy the application and skill;
- replace the firewall template CIDR placeholders only after reviewing the actual SSH/monitoring
  sources, then run its check/apply/reconnect/confirm sequence;
- perform the allowlisted external LLM/Mattermost canary;
- separately approve scheduler and production integration effects.

## Cross-scope notes

- The existing `docker-compose.yml` remains test-only.
- The application deploy owns only `/opt/recording-agent` and the Recordings Saver skill subtree.
- Shared OpenClaw config/agent registry changes remain separately manual and approval-gated.
- Other developers' agents are not inventoried, modified, or adopted; collisions fail closed.
- No database volume or OpenClaw state is deleted during deploy or rollback.
