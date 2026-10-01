# Plan: per-recruiter opt-out from the 18:00 automatic digest message   (slug: recruiter-digest-toggle)

Small enough (one boolean column, one gate, one CLI command) that this plan was written directly
instead of through planner/skeptic subagents — the design has no open questions once the existing
code was read, and the agent AGREEMENT, `/plan` is for 2+ files with unclear scope, which this is
not.

## TL;DR

`recruiter_config` gets `daily_digest_enabled: bool` (default `true`, no backfill needed —
unaffected recruiters keep today's behaviour byte for byte). The scheduled scan/digest job
(`run_due_recruiter_summaries` → `QuestionQueueService.build_digest`) keeps scanning, matching,
transferring and writing Notion for a recruiter whose flag is `false`; it only stops queuing the
Mattermost summary message. Manual-review hygiene inside `build_digest` (auto-closing settled
reviews) keeps running regardless of the flag. A new `configure_recruiter.py set-digest` CLI
command flips the flag for an existing (active or inactive) recruiter.

## Why not the existing levers

- `recruiter.active = false` stops the scan, Synology transfer and Notion writes too — much wider
  than "stop the 18:00 message."
- Clearing `mattermost_user_id`/`mattermost_dm_channel` also stops manual-review question
  delivery and terminal-status notifications, which go through the same DM binding
  (`drain_notification_outbox`) — not requested.
- No existing per-recruiter flag distinguishes "scan silently" from "scan and announce."

## Acceptance criteria

- `recruiter_config.daily_digest_enabled` exists, `NOT NULL DEFAULT true`; every current row
  (Ralina, Lilia) stays enabled unless explicitly turned off.
- `QuestionQueueService.build_digest` accepts `send: bool = True`. When `False`: the settled-review
  auto-complete and the `automatic_delivery_count >= 2` suppression update still run; the pending
  question query still runs (for the row's own idempotency); no `NotificationOutbox` "summary" row
  is queued; an existing `QuestionDigest` row for that local date is marked `SENT` (closes the
  claim without ever sending a message), mirroring the current "no pending questions" branch.
- `app/scheduler/cron.py: run_due_recruiter_summaries` passes `send=recruiter.daily_digest_enabled`
  into `build_digest`. The scan (`scan_recruiter`) itself is untouched — it always runs for an
  active recruiter regardless of the flag.
- `tools/setup/configure_recruiter.py` gains `set_daily_digest(session, *, recruiter_email, enabled)`
  and a `set-digest --email EMAIL --state {enabled,disabled}` CLI subcommand that works on an
  active recruiter (unlike `preflight`/`activate`, which require an inactive row).
- `deploy/release-metadata.json` target revision bumped; additive `NOT NULL DEFAULT true` column
  is compatible with the previous release (`expand-contract` / `automatic-application-rollback`,
  same policy as the last migration).
- Tests: migration-level default is `true`; `build_digest(send=False)` with pending questions
  queues no notification and marks the digest row `SENT`; `build_digest(send=False)` still
  auto-completes a settled review and suppresses a review at `automatic_delivery_count >= 2`;
  `run_due_recruiter_summaries` calls `build_digest` with `send=False` for a recruiter whose flag
  is off and the scan still runs; `set_daily_digest` CLI round-trip.
- `docs/data-model.md` `recruiter_config` section mentions the new column.

## Affected files

- `alembic/versions/<new>_add_recruiter_daily_digest_enabled.py`
- `app/db/models/recruiter_config.py`
- `app/services/question_queue.py` (`build_digest`)
- `app/scheduler/cron.py` (`run_due_recruiter_summaries` call site)
- `tools/setup/configure_recruiter.py` (`set_daily_digest`, CLI subcommand)
- `docs/data-model.md`
- `deploy/release-metadata.json`
- Tests: `tests/test_question_queue.py` (or wherever `build_digest` is already tested),
  `tests/test_scheduler.py`, `tests/test_configure_recruiter.py`

## Out of scope

- Any other recruiter-facing toggle (digest content, manual-review ladder timing).
- Changing Lilia's or Ralina's flag value in this change — that is a separate prod step after
  this ships, done by the user's command via the new CLI.

## Rollout

Same path as multi-tenancy: PR → `main` → CI → Deploy (migration is additive and compatible).
No canary stack (server does not have the headroom). After deploy, the user runs `set-digest
--email lilia.akentyeva@effective.band --state disabled` with their own confirmation (prod
mutation).
