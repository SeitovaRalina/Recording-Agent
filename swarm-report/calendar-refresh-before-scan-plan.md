# Plan: Refresh calendar discovery before every scan (slug: calendar-refresh-before-scan)

## TL;DR

Every manual and scheduled recruiter scan refreshes and validates the CalDAV collection snapshot
before any Disk, matching, transfer, or review work. Refresh failure aborts safely with one bounded
scan-level error. Existing recordings remain unchanged and retryable.

## Acceptance criteria

- `scan_recruiter` refreshes exactly once before `disk.list_new` for both manual and scheduled
  entry paths.
- Discovery parses and validates a complete non-empty collection set before mutating persisted
  calendars.
- Existing selected/default flags are preserved by canonical URL.
- Missing/unavailable selected calendars, or absence of exactly one available default when no
  calendars are selected, abort the refresh. No automatic fallback or response-order selection.
- Failed HTTP/auth/XML/empty/incomplete discovery preserves the previous persisted snapshot.
- Successful refresh atomically updates availability and `last_seen_at`, then scan continues.
- Refresh failure prevents Disk listing, FOUND matching, transfer resume, review creation, and
  other recording mutations for that recruiter.
- Existing `found` and resumable rows remain unchanged and retryable.
- Manual scan returns one sanitized bounded error with stage `calendar_discovery`, stable code,
  retryability, and no raw exception, URL, credential, or CalDAV payload.
- A scheduled failure for one recruiter does not stop other recruiters.
- `found` items are pending/retryable, not `without_review`.
- Same completed idempotency key replays the same failed result. A new recruiter action uses a new
  key after recovery.
- Concurrent scans for one recruiter are serialized inside the current single Backend process.
- No database migration, manual row edit, commit, full pytest, or live external scan.

## Plan

1. Refactor `app/tools/calendar.py`.
   - Fetch and parse discovery into an in-memory staged set.
   - Reject HTTP/auth/XML errors and empty collection sets before database mutation.
   - Validate staged URLs against persisted selected/default invariants.
   - Atomically upsert the staged set and mark missing unselected rows unavailable only after all
     validation succeeds.
   - Expose `refresh_snapshot(recruiter_email)` for scan preflight.
2. Update `app/scheduler/cron.py`.
   - Serialize scan execution per recruiter in-process.
   - Refresh once at the start of `scan_recruiter`.
   - On refresh failure, return an aborted `ScanSummary` with one safe structured scan error and
     perform no later scan stage.
   - Keep other recruiters isolated in scheduled aggregation.
3. Update `app/routers/tools.py`.
   - Add bounded aborted/error fields to the scan response.
   - Exclude `FOUND`, `MANUAL_REVIEW_REQUIRED`, and `FAILED` from `without_review`.
   - Report `FOUND` separately as pending/retryable.
4. Update `openclaw/skills/recording-agent/scripts/recording_agent.py`.
   - Render calendar-discovery aborts actionably.
   - Render `found` items as pending, never successful no-review items.
5. Add targeted tests.
   - `tests/test_calendar.py`: successful atomic refresh; empty/malformed/auth/incomplete refresh
     preserves prior snapshot; selected/default invariants.
   - `tests/test_scheduler.py`: refresh-before-Disk ordering; exactly once; abort has no downstream
     calls or row changes; per-recruiter serialization; scheduled recruiter isolation.
   - `tests/test_tools_router.py`: safe bounded error, replay semantics, pending count, and
     `without_review` exclusion.
   - `tests/test_recording_agent_skill.py`: Russian aborted-scan and pending-item output.
6. Update English documentation.
   - `.memory-bank/architecture.md`: mandatory refresh-before-scan precondition.
   - `docs/api-contracts/yandex-caldav.md`: atomic persistence, completeness gate, and bounded
     failure contract.
7. Run only exact new/affected test selectors and Ruff on changed Python files.

## Blockers

None for the current single-instance Backend deployment.

## Out of scope

- Cross-process or multi-instance distributed scan locking.
- Automatic calendar selection/default repair.
- Internal retry loops for CalDAV.
- Event REPORT batching or scan-wide event caching.
- Database migrations or edits to existing recordings.
- Full pytest, Docker integration canary, live scan, or commits.

## Assumptions

- Production and current canary run one Backend process. In-process recruiter serialization closes
  manual-versus-scheduled overlap there; multi-instance deployment requires a later DB advisory
  lock.
- A completed failed scan intent remains replayable under its original key; after operator/network
  recovery, a new user action receives a new key.
- Refresh failure aborts the entire recruiter scan, including transfer resumes, for a consistent
  prerequisite boundary.
