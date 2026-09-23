# Plan: Manual root-SSH canary release workflow (slug: manual-canary-workflow)

## TL;DR

Build a manually dispatched, immutable candidate image, then let a root SSH operator package,
copy, and deploy it into an isolated same-host canary. No GitHub Environment, deployment key, or
server credential enters GitHub. Canary proves VPN-proxied, read-only Notion schema access only.

## Acceptance criteria

- `canary-build` accepts a full lowercase SHA reachable from a non-main ref, runs CI-equivalent
  checks before publishing, and reports only an immutable GHCR digest.
- No GitHub Environment, deployment/stage secret, deploy key, canary Unix user, sudoers entry,
  forced command, or production-workflow change is introduced.
- A root operator deploy accepts only SHA, immutable image digest, and verified package hashes. It
  rejects tags, main commits, production identifiers, hash mismatch, and unsafe archives before
  Docker mutation.
- Canary has fixed separate identifiers: project `recording-agent-canary`, root
  `/opt/recording-agent-canary`, distinct loopback port, networks, volume, PostgreSQL user/database,
  and root-only `/etc/recording-agent/canary/{backend.env,notion-proxy.env}`.
- Canary fails closed: `TEST_MODE_ENABLED=true`; test recruiter and Notion database allowlists;
  scheduler, autonomous routing, Notion writes, Mattermost delivery, Yandex source mutation,
  cleanup, and Synology transfer are disabled and asserted before smoke.
- `VPN_SUB_URL` exists only in root-owned mode-0600 `notion-proxy.env`; never Git, GitHub workflow,
  image, artifact, log, or command-line argument.
- Smoke proves backend health, a Mihomo-proxied Notion JSON response, then calls only Notion
  database/data-source GET schema inspection for the configured test database. No page query, write,
  storage/source mutation, delivery, scheduler, or routing execution occurs.
- Capacity and production-state preflight are hard gates. Rollback and acknowledged teardown affect
  only verified canary resources; production containers, paths, database/volume, current release,
  and secrets are unchanged before and after.

## Plan

1. Add secretless manual `canary-build`: verify exact full non-main SHA, run the same checks as CI,
   publish an exact candidate tag, resolve/reverify its immutable digest, and expose SHA/digest as
   run output. It has no host credentials or VPN value.
2. Add deterministic local package creation for the exact checkout. Produce only allowlisted
   canary assets and a SHA-256 manifest; reject symlinks, traversal, unknown files, and mismatched
   metadata during root deployment.
3. Add `compose.canary.yml` and `.env.canary.example`. Use explicit canary project/resource names,
   distinct DB credentials, private networks, a non-production loopback diagnostic port, and safe
   resource limits. Reuse only the application/Mihomo image digests, never production mounts/env.
4. Add root-invoked canary deploy. Validate root, SHA/digest/provenance/package hashes, canary-only
   paths/resources, rendered Compose, production health, disk space, and `MemAvailable` sufficient
   for exact canary reservations plus production headroom. Refuse before `docker compose up` on any
   failed check. Do not modify or rerun `bootstrap-host.sh`.
5. Add a dedicated noninteractive Notion schema command. It creates the configured Notion client and
   calls `inspect_database` only; validates exact test-database allowlist plus required property
   types. It must not open a DB session, query pages, invoke mutation endpoints, or run scheduler,
   transfer, source mutation, or delivery code.
6. Add canary smoke: verify canary service health, verify the local proxy returns Notion JSON rather
   than Cloudflare/HTML, then run the read-only schema command. Avoid shell tracing and secret dumps.
7. Add canary-only rollback and teardown. Rollback selects a previously verified canary manifest.
   Teardown requires a literal acknowledgement, checks every target name/root, and only then stops
   the canary project and deletes named canary resources. `docker system prune` is forbidden.
8. Extend static validation and focused tests for workflow provenance, package integrity, Compose
   isolation, disabled effects, scripts, and read-only Notion behavior.
9. Document the root-SSH operator runbook: build candidate, package, SCP, create root mode-0600
   host env files, deploy, smoke, compare production state, rollback/teardown, and promote only via
   normal PR to main.

## Affected files

- `.github/workflows/canary-build.yml` (new)
- `compose.canary.yml` (new)
- `.env.canary.example` (new)
- `deploy/scripts/canary-package.sh` (new)
- `deploy/scripts/canary-deploy.sh` (new)
- `deploy/scripts/canary-smoke-test.sh` (new)
- `deploy/scripts/canary-rollback.sh` (new)
- `deploy/scripts/canary-teardown.sh` (new)
- `deploy/scripts/validate-static.sh`
- `tools/setup/preflight_notion.py` (new)
- `deploy/README.md`
- `tests/test_canary_workflow.py` (new)
- `tests/test_canary_compose.py` (new)
- `tests/test_canary_scripts.py` (new)
- `tests/test_notion_preflight_cli.py` (new)

## Tests

- Workflow rejects short, uppercase, main, unresolved, and mutable candidate inputs before publish.
- Compose render proves distinct project/path/network/volume/database/port/env-file references and
  all side-effect flags false.
- Script tests prove root/provenance/hash/capacity guards, canary-only target checks, literal
  teardown acknowledgement, and no VPN value in workflow/package/arguments.
- Notion command tests prove compatible database/data-source GET schema inspection and reject
  incompatible schemas/errors without calling page or write endpoints.
- In `/debug`: focused canary tests, then full `pytest`.
- After separate remote execution approval: snapshot production state; deploy, smoke, compare;
  rollback and teardown with proof that only canary resources changed.

## Blockers

None for repository implementation. Remote execution remains a separate checkpoint: root operator
must provide the test-only host env values and the capacity preflight must pass. Failure is a safe
no-deploy result, not permission to weaken limits.

## Out of scope

- GitHub Environments, GitHub deployment/stage secrets, deploy keys, dedicated canary users,
  forced commands, sudoers, or `bootstrap-host.sh` changes.
- Feature auto-deploy, main merge/push, or changes to the production workflow.
- Production Notion database access/writes, Yandex mutation, Synology transfer, Mattermost,
  scheduler, routing, or cleanup.
- Moving the Notion worker/proxy outside Russia.

## Assumptions

- User accepts temporary same-host failure-domain risk and confirms root SSH works.
- The host can pull the candidate GHCR image without exposing registry credentials in logs.
- Test recruiter, test Notion database, MinIO values, and test data are maintained outside Git.
- `VPN_SUB_URL` is Mihomo-compatible and will be written only to the root host proxy env file.
