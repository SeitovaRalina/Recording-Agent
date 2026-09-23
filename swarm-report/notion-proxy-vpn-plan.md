# Plan: Dedicated Notion VPN proxy sidecar (slug: notion-proxy-vpn)

## TL;DR

Add a hardened Mihomo/Clash sidecar that consumes `VPN_SUB_URL`. The Backend uses a separate
HTTP client to send only `api.notion.com` traffic through the internal proxy. All other
integrations stay direct. A failed proxy or invalid route blocks Notion operations; it never
falls back to the Moscow egress path.

## Acceptance criteria

- Production Compose starts an internal-only `notion-proxy` service; it publishes no host port.
- `VPN_SUB_URL` is available only to the proxy service. Backend receives only
  `NOTION_PROXY_URL`.
- Notion receives a dedicated `httpx.AsyncClient` configured with `NOTION_PROXY_URL`; Disk,
  CalDAV, MinIO/Synology, Mattermost, and transfer clients retain direct HTTP clients.
- Production startup fails if `NOTION_PROXY_URL` is missing or invalid. No Notion direct fallback
  exists.
- Mihomo routes `api.notion.com` through the subscription-selected tunnel and all other
  destinations direct.
- The sidecar readiness check proves a proxied Notion API response has an API JSON shape and
  rejects Cloudflare HTML.
- Subscription URLs, Notion tokens, proxy credentials, and proxy URLs are not logged.
- Focused tests, Ruff, format check, mypy, full pytest, and rendered production Compose pass.

## Plan

1. Never print or commit `VPN_SUB_URL`.
2. Update `app/config.py` with `notion_proxy_url: SecretStr`. Validate an internal `http`/`https`
   proxy URL. Require it in production; preserve no-proxy mocked local tests.
3. Update `app/main.py` to retain the direct shared client and create a separate proxy-configured
   Notion client. Close both in lifespan shutdown. Do not use global `HTTP_PROXY`, `HTTPS_PROXY`,
   or `ALL_PROXY` variables.
4. Add `notion-proxy` to `compose.prod.yml`, pinned by immutable Mihomo image digest. No `ports`.
   Use a private network shared only with Backend, read-only filesystem, tmpfs runtime config,
   non-root execution, no-new-privileges, resource limits, and a healthy Backend dependency.
5. Add `deploy/mihomo/config.yaml` and `deploy/mihomo/entrypoint.sh`. Consume the subscription at
   runtime, atomically retain last-known-good config, use bounded refresh/retry, route
   `api.notion.com` through the tunnel and terminal `MATCH,DIRECT` for all other hosts.
6. Add proxy readiness verification using a harmless Notion API request through the proxy. Accept
   expected Notion API JSON auth results; reject HTML, Cloudflare, and connection failures.
7. Update `.env.production.example` and `.env.example`: documented placeholders only, proxy scope,
   pinned image requirement, rollout/rollback commands. Keep `VPN_SUB_URL` proxy-only.
8. Add tests for settings validation/redaction, separate HTTP client wiring, direct-client
   preservation, sanitized proxy failures without retry, and static production Compose isolation.
9. Run quality gates. After a separately approved remote deployment: test egress/API response,
   Backend schema and synthetic-row preflight, then controlled test-database canary.

## Affected files

- `app/config.py`
- `app/main.py`
- `compose.prod.yml`
- `deploy/mihomo/config.yaml` (new)
- `deploy/mihomo/entrypoint.sh` (new)
- `.env.example`
- `.env.production.example`
- `tests/test_config.py`
- `tests/test_notion.py`
- `tests/test_main.py` (new)
- `tests/test_compose_prod.py` (new)

## Tests

- `pytest tests/test_config.py tests/test_notion.py tests/test_main.py tests/test_compose_prod.py`
- Render production Compose with non-secret fixtures; assert no proxy host ports, subscription
  isolation, Backend health dependency, and Notion-only route.
- Verify proxy timeout/connection error/Cloudflare HTML yield sanitized typed errors and no direct
  retry.
- `docker compose -f compose.prod.yml --env-file <protected-env> config --quiet`
- `poetry run ruff check app tests`
- `poetry run ruff format --check app tests`
- `poetry run mypy app tests`
- `poetry run pytest`

## Blockers

- Confirm the provider subscription parses in the selected pinned Mihomo image before enabling the
  Backend. The subscription page indicates Clash compatibility, but one live parse/egress test is
  still required.
- Remote deployment, Notion schema probe, synthetic write, and external side effects remain
  separate approvals.

## Out of scope

- Moving the Notion worker to another VPS.
- Host-wide or recruiter-device VPN.
- Proxying Yandex, Synology, Mattermost, or other integrations.
- Scheduler, Yandex mutation, Synology, Mattermost, or production database changes.

## Assumptions

- `VPN_SUB_URL` is Clash/Mihomo-compatible.
- Docker Compose remains the production deployment target.
- `api.notion.com` is the only Backend Notion API hostname required.
