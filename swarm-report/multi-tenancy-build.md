# Build: multi-tenancy

Plan: `swarm-report/multi-tenancy-plan.md`. Scope: python-fastapi (all files). First exec run
died from an API auth error before any edit; the retry completed.

## Commits

- `5fe5a22` feat(recruiter): per-recruiter Notion property map and Synology roots
- `f04d16d` feat(notion): contacts modes none, formula and relation
- `93bae81` refactor(services): resolve Notion props and roots per recruiter
- `bb61e1e` feat(setup): per-recruiter Notion map and roots in configure CLI
- `27ea72c` docs: per-recruiter Notion property map and Synology roots
- `3e05530` chore(deploy): target Alembic revision 20260930_1000 (added by the orchestrator: the
  exec agent missed it, and deploy fails closed on a head/metadata mismatch)

## Changed files

- New: `alembic/versions/20260930_1000_add_recruiter_notion_schema_and_roots.py` (two nullable
  JSON columns, no backfill, reversible), `app/services/recruiter_schema.py`, tests
  `test_recruiter_schema.py`, `test_notion_contacts.py`, `test_multi_tenancy.py`,
  `test_configure_recruiter_tenancy.py`.
- Changed: `app/db/models/recruiter_config.py`, `app/tools/notion.py`, `app/services/canary.py`,
  `candidate.py`, `notion_reassignment.py`, `destinations.py`, `transfer.py`, `reroute.py`,
  `app/scheduler/cron.py`, `app/routers/tools.py`, `tools/setup/configure_recruiter.py`,
  `docs/api-contracts/notion.md`, `docs/data-model.md`, `deploy/release-metadata.json`, and
  existing tests that called `notion_schema_hash(settings)`.

## Verification (run by the orchestrator, not copied from the agent)

```
poetry run pytest -q
444 passed, 2 skipped in 30.12s

poetry run ruff check .
All checks passed!

poetry run mypy <10 changed modules>
Success: no issues found in 10 source files

bash deploy/scripts/validate-static.sh
deployment static validation passed

poetry run alembic heads
20260930_1000 (head)
```

The full `mypy app tools` run reports 12 errors in `app/routers/tools.py:1213-1218` and
`tools/setup/synology_sid_inventory.py`. The agent reports they predate this change (blame
`365b861c`, 2026-08-06); not re-verified by the orchestrator.

## Behaviour notes

- Anton's row (both columns NULL) resolves to the global settings. For that default shape
  `notion_schema_hash` produces the old payload byte for byte, so his stored preflight hash stays
  valid after deploy and no re-preflight is needed (covered by a test).
- Relation contacts: zero, several or malformed links, or a missing/non-rich_text target, give
  `emails=()` and never block matching. Transport/HTTP errors on the linked card raise
  `NotionQueryError`, as Spots resolution does.
- API change: `POST /tools/notion-reassignment/{proposal_id}/confirm` now resolves the bound
  recruiter first (same 404/403 as propose) and returns 409 when the recording belongs to another
  recruiter. Mila's skill script must keep sending the recruiter/DM binding fields on confirm.
- Left on the global settings on purpose: `tools/setup/preflight_notion.py` (global probe CLI),
  `notion_interview_type`.
- Migration not applied locally (no local DB); deploy runs `alembic upgrade head`.
