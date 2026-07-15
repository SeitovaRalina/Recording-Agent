# Build Report: calendar-selection-title-match

## Status

Complete. No unresolved plan blockers.

## Python / FastAPI

- Added normalized recruiter calendar configuration, explicit default and selected-calendar state,
  immutable match provenance, typed manual-review reasons, and selection audit/version fields.
- Added credential-safe all-calendar CalDAV discovery and complete snapshot queries. Calendar
  selection uses opaque recruiter-owned IDs; arbitrary URLs are never accepted as request targets.
- Added strict Telemost filename title/time correlation, monitored-calendar eligibility,
  unmonitored-calendar collision detection, and fail-closed ambiguity behavior.
- Added internal calendar discovery/default/selection endpoints with constant-time service-secret
  authentication, localhost restriction, recruiter isolation, optimistic concurrency, and atomic
  default switching.
- Added a dry-run-first remediation CLI for existing non-terminal mismatches; `--apply` was not run.
- API changes:
  - `GET /internal/recruiters/{email}/calendars`
  - `POST /internal/recruiters/{email}/calendars/discover`
  - `PUT /internal/recruiters/{email}/calendars/selection`
  - `PUT /internal/recruiters/{email}/calendars/default`

## Database migrations

- Generated schema revision `2e68d69a2654_add_recruiter_calendar_selection.py` through Alembic
  autogenerate, then reviewed explicit PK/FK names and downgrade order.
- Added separate reversible data revision
  `20260715_1400_backfill_legacy_calendar_defaults.py`.
- Legacy HTTPS calendar URLs receive deterministic IDs and remain unavailable until runtime
  discovery validates recruiter ownership. The legacy column/data is preserved.
- Local development verification:
  - upgrade `20260714_1000 -> 2e68d69a2654 -> 20260715_1400` — pass;
  - downgrade to `20260714_1000` — pass;
  - re-upgrade to `20260715_1400` — pass;
  - `alembic check` — `No new upgrade operations detected.`;
  - `alembic heads` — `20260715_1400 (head)`.

## Documentation

- Updated Memory Bank architecture, decisions, and open questions.
- Updated data model, status machine, and Yandex CalDAV API contract.
- Documented the immutable shared Disk folder, default/effective selection, complete collision
  snapshots, strict title/time gate, provenance, manual reasons, and remediation workflow.

## Verification

- Ruff check and format check — pass.
- mypy — `Success: no issues found in 41 source files`.
- pytest — `77 passed in 57.17s`.
- Focused calendar/migration tests — `8 passed`.
- Documentation `git diff --check` and targeted semantic searches — pass.

## Cross-layer notes

- No Disk deletion, Notion mutation, Synology operation, or remediation apply was executed.
- The unrelated untracked `swarm-report/phase-3-transfer-plan.md` was preserved and excluded.
