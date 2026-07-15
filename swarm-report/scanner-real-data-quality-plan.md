# Plan: Improve Phase 2 scanner quality for real Yandex data (slug: scanner-real-data-quality)

## TL;DR

Tighten Phase 2 scanner behavior around real Yandex Calendar/Disk data: first scan ignores pre-today legacy recordings, matcher no longer treats Telemost URL as a strong interview signal, calink/name/time signals drive confident matches, and scheduler logs successful runs clearly.

## Acceptance criteria

1. First scan for a recruiter imports only Disk recordings whose `disk_created_at` is today or later in the configured local scan timezone; older unprocessed recordings are skipped without DB rows.
2. The cutoff is deterministic and testable: tests can inject/freeze current time or pass a clock so "today" does not depend on wall-clock execution.
3. Existing DB rows in `recordings` still resume normally even when their `disk_created_at` is before today's cutoff; cutoff applies only to newly discovered Disk files.
4. A real calink-style event like `Встреча на 30 минут (Дмитрий Aqa)` with calink URL plus matching time reaches `calendar_event_found`.
5. A self-test/manual event with only Yandex-added Telemost block and matching time does not reach auto-match threshold.
6. An event with candidate-like name plus matching time but no calink/booking marker remains `manual_review_required`.
7. Telemost URL remains a weak/diagnostic signal only; Memory Bank Q6 and architecture docs no longer describe it as HIGH confidence.
8. Scheduler logs successful scenarios at `INFO`: job start, active recruiter count, per-recruiter file counts, each new DB recording inserted, each match decision with status/confidence/signals, per-recruiter summary, job completion, and registered next run time.
9. Logs never include OAuth refresh tokens, CalDAV passwords, full raw ICS, or secret env values.
10. Tests cover cutoff, revised matcher weights, and successful-run logging.

## Plan

1. Update Memory Bank first.
   - Affected files:
     - `.memory-bank/open-questions.md`
     - `.memory-bank/architecture.md`
     - `.memory-bank/decisions.md`
   - Change Q6: real Yandex data shows Calendar prepends Telemost details to every video event, so Telemost confirms "video call", not "interview".
   - Change interview detection table:
     - `time_overlap`: high signal.
     - `booking_source_marker` with `calink.ru`: high signal for current effective.band flow.
     - `name_in_summary`: medium/high signal, depending on final weights.
     - `has_telemost_url`: low signal only.
     - absence of calink never blocks manual review, but calink presence should strongly help auto-match.
   - Keep invariant: low confidence goes to `manual_review_required`, not `ignored`.

2. Add scanner cutoff setting and clock.
   - Affected files:
     - `app/config.py`
     - `.env.example`
     - tests for config/scheduler
   - Add `scanner_first_run_from_today: bool = True` or clearer equivalent.
   - Add local scan timezone setting, defaulting to the operator/test timezone currently used for scheduling decisions, e.g. `Asia/Omsk`.
   - Prefer explicit setting names:
     - `SCAN_IGNORE_BEFORE_TODAY=true`
     - `SCAN_LOCAL_TIMEZONE=Asia/Omsk`
   - Compute cutoff as start of current local date converted to UTC.
   - Implement with injectable clock helper/function so tests are deterministic.

3. Apply cutoff only during discovery persistence.
   - Affected file:
     - `app/scheduler/cron.py`
   - In `_persist_found_recording`, after metadata fetch and before insert:
     - parse `disk_created_at`;
     - if cutoff enabled and `disk_created_at < local_today_start_utc`, skip insert and log one concise `INFO`;
     - do not mark Disk resource processed;
     - do not write `ignored`, because the user did not make a decision about legacy files.
   - Existing `FOUND` rows remain eligible for `_resume_found_recording`.
   - If `disk_created_at` is missing, keep current safe behavior: insert and later route to `manual_review_required`.

4. Rebalance matcher weights against real data.
   - Affected files:
     - `app/services/matching.py`
     - `tests/test_matching.py`
   - Proposed starting weights:
     - `time_overlap`: `0.35`
     - `booking_source_marker`: `0.30`
     - `name_in_summary`: `0.25`
     - `has_telemost_url`: `0.05`
     - `interview_keywords`: `0.05`
     - attendee email remains Phase 3 stub.
   - Keep `CONFIDENCE_THRESHOLD=0.70`.
   - Expected outcomes:
     - time + calink + candidate name = `0.90`, auto-match.
     - time + Telemost only = `0.40`, manual review.
     - time + candidate name + Telemost = `0.65`, manual review.
     - time + candidate name + calink without Telemost = `0.90`, auto-match.
   - Keep tie-break by closest event start.

5. Add successful-run logging.
   - Affected files:
     - `app/scheduler/cron.py`
     - `app/main.py`
     - tests in `tests/test_scheduler.py`
   - Log at scheduler registration:
     - `scan_all_recruiters registered: hour=<UTC>, minute=<UTC>, next_run=<UTC>`
     - cleanup next run separately.
   - Log at scan job start/end:
     - active recruiter count;
     - duration;
     - totals: discovered, inserted, skipped_legacy, matched, manual_review, failed.
   - Log per recruiter summary.
   - Log each inserted recording with safe fields only:
     - recording id, recruiter email, Disk filename, Disk created timestamp, status.
   - Log each match decision:
     - recording id, status, confidence, signals, event summary if present.
   - Do not add DB audit tables in this feature. Application logs are enough for operator visibility; DB remains state store.

6. Update docs.
   - Affected files:
     - `docs/status-machine.md`
     - `docs/data-model.md` if field notes mention scoring behavior.
     - `swarm-report/phase-2-scanner-build.md` only if it contains now-obsolete behavior claims that reviewers will read.
   - English-only prose per `AGENTS.md`.
   - Document that first-run local testing ignores legacy recordings before local today by default.
   - Document that DB insert logs are application logs, not PostgreSQL logs.

7. Tests.
   - `tests/test_matching.py`:
     - calink + time + name auto-matches;
     - Telemost + time only manual review;
     - Telemost + time + name manual review;
     - no Telemost but calink + time + name auto-matches;
     - tie-break still uses closest event.
   - `tests/test_scheduler.py`:
     - new Disk file before local today is not inserted;
     - new Disk file at/after local today is inserted;
     - existing `FOUND` row before cutoff still resumes;
     - logs include inserted/match/summary lines using `caplog`.
   - `tests/test_config.py`:
     - new settings defaults and env aliases.
   - Run:
     - `poetry run ruff check app tests alembic`
     - `poetry run ruff format --check app tests alembic`
     - `poetry run mypy app tests`
     - `poetry run pytest`

## Blockers

None.

## Out of scope

- No automatic `ignored` classification for non-interviews.
- No Mattermost manual-review UX changes.
- No Notion candidate lookup improvements.
- No multiple-calendar allowlist in this feature; useful later, but separate from matcher/cutoff/logging.
- No DB audit/event-log table.
- No production secret storage changes.
- No change to the existing UTC cron schedule semantics.

## Assumptions

- "After connecting the agent, first scan imports from today" means from start of current local date, not from exact OAuth connection timestamp, because no connection timestamp is currently stored.
- Local date should be configurable; `Asia/Omsk` is appropriate for current local testing.
- Telemost details being prepended by Yandex is stable enough to demote Telemost from HIGH to LOW immediately.
- False positives remain worse than extra manual review, so ambiguous events stay `manual_review_required`.
- Subagent execution for this `/plan` was technically blocked by the current agent tree; this plan follows the same `.claude/agents/planner.md` and `.claude/agents/skeptic.md` structure locally.
