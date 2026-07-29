# Plan: Safe Local Manual Scan Trigger   (slug: manual-scan-trigger)

## TL;DR

Add a developer-only `POST /internal/scans` endpoint for immediate Phase 2 discovery and
matching. It is disabled by default, protected by a dedicated secret, limited to an explicit
test-recruiter allowlist, and uses the same dependencies and shared scan gate as cron. It never
calls retention cleanup or permanent deletion. Complete the Docker and secret-injection gaps so
the container can run the scanner with the same Phase 2 configuration as a Poetry host process.

## Acceptance criteria

1. `POST /internal/scans` returns 404 unless `MANUAL_SCAN_ENABLED=true`.
2. When enabled, requests without a correct non-empty `X-Manual-Scan-Secret` return 401; use
   constant-time comparison and do not reuse `OPENCLAW_SECRET`.
3. The request must name one recruiter email. It is accepted only when the email is in the
   non-empty `MANUAL_SCAN_ALLOWED_RECRUITERS` allowlist; all other emails return 403 without a
   scan.
4. A valid request scans only the selected active recruiter and returns 202. It does not invoke
   cleanup, Trash operations, or permanent purge.
5. Cron and manual requests use one shared in-process scan gate. If a scan is running, manual
   endpoint returns 409 and does not start another scan.
6. Router reuses the `session_factory`, DiskScanner, CalDAVClient, and InterviewMatcher built by
   FastAPI lifespan; it creates no extra engine, scheduler, or integration clients.
7. Docker Compose binds the app only to `127.0.0.1` and injects all Phase 2 Yandex/CalDAV,
   schedule, and manual-trigger variables. No secret is hardcoded.
8. `.env.example` and README distinguish local `.env` from production Lockbox-injected
   environment variables, document UTC schedule, and give a PowerShell immediate-test command.
9. Tests cover disabled, unauthorized, forbidden recruiter, busy gate, valid scan/dependency
   reuse, and guarantee no retention call.

## Plan

### Affected files

| File | Change |
|---|---|
| `app/config.py` | Add manual-scan feature flag, dedicated secret, test-recruiter allowlist, validators. |
| `app/main.py` | Store lifespan-owned scan dependencies and one shared scan gate on `app.state`; register internal router. |
| `app/scheduler/cron.py` | Extract/use a shared scan-gate-aware selected-recruiter execution path for cron and manual scan. |
| `app/routers/internal.py` | New protected local endpoint; feature gate, constant-time secret check, allowlist, busy response, safe selected scan. |
| `tests/test_internal_router.py` | New router contract and no-retention tests. |
| `tests/test_scheduler.py` | Gate contention and selected active-recruiter scan tests. |
| `tests/test_config.py` | Default-off and SecretStr/allowlist parsing tests. |
| `docker-compose.yml` | Loopback app port binding and configuration passthrough. |
| `.env.example` | Safe empty test placeholders for Phase 2/manual config. |
| `README.md` | Correct Poetry-vs-Docker guidance and test procedure. |
| `.memory-bank/architecture.md` | Record local-only trigger boundary and no-retention invariant. |
| `.memory-bank/auth-flow.md` | Clarify local `.env` versus production Lockbox injection. |

### Steps

1. Add `MANUAL_SCAN_ENABLED=false`, `MANUAL_SCAN_SECRET: SecretStr`, and
   `MANUAL_SCAN_ALLOWED_RECRUITERS: set[str]` settings. Parse JSON allowlist; enabled mode with
   an empty secret or empty allowlist remains unavailable/fails closed.
2. In lifespan, retain the existing scanner dependencies on `app.state`. Create one
   `asyncio.Lock` scan gate and expose an application service that executes scan work for a set
   of active recruiter emails.
3. Make cron use that service for all active recruiters. Keep its existing `max_instances=1`;
   manual scans also acquire the same gate. The manual endpoint returns 409 if locked.
4. Add `POST /internal/scans` with a Pydantic request body containing `recruiter_email`.
   Feature-gate before processing; compare the dedicated header secret with `hmac.compare_digest`;
   then enforce the configured allowlist and active recruiter lookup.
5. Await selected-recruiter scan work and return 202. Explicitly do not call
   `cleanup_expired_recordings`, `delete_expired`, or `purge_expired_from_trash`.
6. Bind Compose app port to loopback and pass the scanner config using environment interpolation.
   Do not copy secrets into files or image layers.
7. Update `.env.example`, README, and Memory Bank documentation in English: container runtime is
   normal for deployment; `poetry run uvicorn` is the host-development path; schedule is UTC;
   `.env` is development only and production injects Lockbox values.
8. Run Poetry lint, format, strict mypy, and full pytest. Validate Compose configuration without
   displaying secrets.

## Tests

- Disabled endpoint returns 404 even with a valid-looking header.
- Missing, wrong, or empty configured secret returns 401.
- Recruiter outside allowlist returns 403; inactive/missing recruiter does not scan.
- Allowed request uses exact lifespan-owned dependencies and invokes selected scan once.
- Busy shared gate returns 409 and does not invoke scan.
- Manual endpoint never calls cleanup or either Disk deletion method.
- Cron preserves concurrent per-recruiter isolation with the shared gate.
- Compose static check confirms loopback binding and expected variable passthrough.
- Full gate: `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run mypy app tests`, `poetry run pytest`.

## Blockers

None. The endpoint is explicitly restricted to configured test recruiter accounts. Production
deployment must independently bind the backend to loopback/private network as documented.

## Out of scope

- Mattermost `/recordings check`, OpenClaw tool registration, scan history/progress API,
  cancellation, OAuth bootstrap script, and Lockbox provisioning.
- Disk retention cleanup or permanent deletion through the endpoint.

## Assumptions

- Phase 2 scan may create/update `recordings` statuses, but uses only test Disk, Calendar, and
  database data.
- Single-process FastAPI is the supported runtime for this manual gate. Multi-replica deployment
  needs a future database/distributed lease lock.
