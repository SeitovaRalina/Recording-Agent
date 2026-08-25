# Build: notion-proxy-vpn

## Status

Implemented; review pending. Full tests deferred by explicit user instruction until `/debug`.

## python-fastapi

- Changed: `app/config.py`, `app/main.py`, `tests/conftest.py`, `tests/test_config.py`,
  `tests/test_notion.py`, `tests/test_main.py`.
- Added production fail-closed `NOTION_PROXY_URL`, dedicated Notion proxy client, direct shared
  client with `trust_env=False`, and close lifecycle coverage.
- Tests: deferred by user.

## devops

- Changed: `compose.prod.yml`.
- Added internal Mihomo sidecar with isolated proxy environment, no published host port,
  hardening, readiness dependency, and fixed internal Backend proxy URL.
- Verification: `git diff --check` passed.
- Tests: deferred by user.

## backend assets and release packaging

- Changed: `deploy/mihomo/config.yaml`, `deploy/mihomo/entrypoint.sh`, `.env.example`,
  `.env.production.example`, `tests/test_compose_prod.py`, `deploy/scripts/deploy.sh`,
  `.github/workflows/deploy.yml`.
- Added runtime subscription bootstrap, Notion-only Mihomo routing/readiness assets, protected
  environment documentation, and authenticated release packaging of Mihomo assets.
- Tests: deferred by user.

## Cross-layer notes

- Host bootstrap must be rerun under separate approval before deploy: it must install the updated
  forced dispatcher accepting the sixth `MIHOMO_SHA` argument.
- Live subscription parsing, remote egress check, Notion preflight, and synthetic write remain
  deployment-stage checks, not performed in this build.

## Debug verification

- Review found proxy-network isolation, immutable-image validation, and Compose-test defects.
- `/debug` fixed them with separate proxy egress/internal networks, an allowlisted immutable
  `ghcr.io/metacubex/mihomo@sha256:<64hex>` deployment gate, and robust rendered Compose tests.
- Focused regression: `12 passed, 1 warning in 0.74s`.
- Full regression: `341 passed, 1 warning in 76.55s (0:01:16)`.
- Warning: pytest could not write its local cache due to workspace permissions.
