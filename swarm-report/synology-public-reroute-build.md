# Build Report: Synology public reroute

## Implemented

- Kept public permanent File Station links: `date_expired=-1`, `date_available=0`, no password
  or expiry payload.
- Added immutable storage-artifact, reroute-operation, and Notion-reassignment proposal models and
  migration `20260729_1100`.
- Added verified Synology CopyMove v3: no overwrite, separate data/owner-marker moves, task polling,
  target size/owner verification, and physical source/marker absence checks.
- Rework: DSM polling now uses the proven CopyMove `status` API and error `599` completion contract;
  it never treats malformed status data as success and uses bounded async backoff. A persisted recording lease prevents concurrent
  reroutes while a NAS mutation is in flight.
- Rework: initial successful durable Synology transfers now persist an active artifact, so reroute
  history is usable without guessing legacy placements.
- Added opaque-destination-only reroute API and skill CLI. It preserves the prior artifact, writes
  and verifies the new public Notion link, then switches the active artifact.
- Added bounded Notion reassignment resolver/proposal/confirmation. Target write+verify happens
  before source clear. Ordinary candidate lookup already filters non-empty recording fields.
- Rework: reassignment completion validates the same DM/capability/idempotency binding on replay and
  checkpoints a verified target write before source clear. URL/page-ID hints are canonicalized and
  require a configured database/data-source parent.
- Final rework: reroute phases are committed after CopyMove and link creation, then resume without
  repeating ambiguous NAS moves; immutable destination/version mismatch is rejected. A target-written
  reassignment re-reads target and source before source clear and fails closed on drift.
- Final recovery hardening: the exact target path is persisted before CopyMove. A pending retry
  reconciles that path and source before any NAS call; a moved operation without a committed link
  checkpoint recovers the exact-path permanent link through File Station Sharing `list` before any
  create call.
- Final audit: pending recovery now proves target size and owner marker before advancing to moved.
  Share-link recovery paginates File Station results with a hard 1,000-link bound.
- Added focused reroute/reassignment regression coverage for task identity, allowed-root rejection,
  Notion page-ID canonicalization, and active artifact representation.
- Documented accepted public-link risk, technical account, and File Station revocation procedure.

## Verification

```text
poetry run ruff check app alembic  -> All checks passed
poetry run mypy app                -> Success: no issues found in 55 source files
poetry run pytest                  -> 319 passed, 1 Windows pytest-cache permission warning
poetry run pytest tests/test_notion.py tests/test_synology.py -> 60 passed, same warning
poetry run pytest tests/test_synology.py tests/test_notion.py tests/test_scheduler.py -> 107 passed, same warning
poetry run pytest tests/test_reroute_reassignment.py tests/test_synology.py tests/test_notion.py -> 64 passed, same warning
poetry run pytest tests/test_reroute_reassignment.py tests/test_synology.py tests/test_notion.py -> 65 passed, same warning
poetry run pytest tests/test_synology.py tests/test_reroute_reassignment.py tests/test_notion.py -> 66 passed, same warning
poetry run alembic heads           -> 20260729_1100 (head)
git diff --check                   -> passed
```

## Operational dependency

The separately user-approved DSM smoke proved CopyMove under the test root. Runtime deployment still
requires applying the new Alembic migration and enabling the existing Synology Backend configuration;
no server or secret mutation occurred in this build.
