# Build: Manual root-SSH canary release workflow

## Status

Implemented. Test execution intentionally deferred to `/debug` by user instruction.

## DevOps

- Changed: `.github/workflows/canary-build.yml`, `compose.canary.yml`,
  `deploy/scripts/validate-static.sh`.
- Result: secretless immutable candidate build; isolated canary Compose; static invariants.
- Verification: `git diff --check` — pass; CRLF conversion warnings only.
- Tests: not run.

## Backend operations

- Changed: `.env.canary.example`, `deploy/scripts/canary-package.sh`,
  `deploy/scripts/canary-deploy.sh`, `deploy/scripts/canary-smoke-test.sh`,
  `deploy/scripts/canary-rollback.sh`, `deploy/scripts/canary-teardown.sh`, `deploy/README.md`.
- Result: root-only package/deploy/smoke/rollback/teardown with canary-only path/resource,
  integrity, capacity, effect-disablement, and acknowledgement guards.
- Tests: not run.

## Python

- Changed: `tools/setup/preflight_notion.py`, `tests/test_notion_preflight_cli.py`.
- Result: noninteractive GET-only Notion schema CLI, restricted to test mode, exact test DB
  allowlist, and disabled side effects.
- Tests: not run.

## Cross-layer notes

- Compose deliberately has no MinIO service. Schema smoke receives an unreachable test endpoint;
  no storage network endpoint is available.
- `VPN_SUB_URL` remains host-only in `/etc/recording-agent/canary/notion-proxy.env`.
- The plan named additional static test modules. They were not created by this build; `/review`
  must assess whether existing static validation provides enough coverage.
