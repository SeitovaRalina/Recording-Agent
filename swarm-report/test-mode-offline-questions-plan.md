# Plan: Test-mode offline questions flow

## TL;DR

Make manual Mila test scans create and process durable DM-bound questions without Mattermost
credentials or network calls. Trust only invocation-injected environment metadata. Keep production
DM validation and delivery unchanged.

## Acceptance criteria

- Test manual `scan` requires trusted recruiter email, user ID, and DM channel environment metadata
  and sends all three to Backend.
- Missing/conflicting/non-allowlisted metadata fails before scan side effects.
- Scan idempotency fingerprint includes user and channel.
- With test mode enabled and Mattermost delivery disabled, a manual-review recording creates one
  durable pending question bound to the exact request user/channel, without Mattermost API calls.
- No `RecruiterConfig` channel mutation or automatic rebinding occurs.
- `questions` exposes capabilities only for the exact durable user/channel binding.
- `answer` resolve/ignore enforces binding, capability, question set, version, and idempotency;
  resolve resumes processing and ignore reaches `ignored`.
- Follow-up/reconciliation uses the same immutable interaction binding.
- Delivery-disabled processing creates no Mattermost notification outbox rows.
- Production configured-DM lookup, live channel validation, outbox, and delivery remain unchanged.
- No existing recording/config rows are manually edited.

## Plan

1. Extend scan CLI/request with bounded recruiter user and DM channel metadata. Require values from
   trusted invocation environment for scan/questions/answer; explicit fallback cannot establish
   identity. Reject conflicts. Include metadata in intent fingerprint.
2. Pass an immutable optional test interaction binding through router and manual scan. Scheduler
   receives none and cannot synthesize an offline channel.
3. Decouple durable question creation from external delivery. Offline test mode stores
   `ManualReview` against validated request binding and skips Mattermost validation; production
   uses configured exact DM plus live validation.
4. Make list/answer/reconcile mode-aware. Offline path validates active recruiter, authoritative
   configured user, allowlists, and exact persisted question channel. Reject cross-channel access
   and any existing pending question bound elsewhere.
5. Suppress processing/completion/error Mattermost outbox entries while delivery is disabled.
   Preserve durable state and CLI results.
6. Update skill contract and add targeted regression/security tests.

Affected files:

- `app/routers/tools.py`
- `app/scheduler/cron.py`
- `app/services/reviews.py`
- `app/services/question_queue.py`
- `openclaw/skills/recording-agent/scripts/recording_agent.py`
- `openclaw/skills/recording-agent/references/contract.md`
- `tests/test_scheduler.py`
- `tests/test_tools_router.py`
- `tests/test_question_queue.py`
- `tests/test_recording_agent_skill.py`
- `tests/test_recording_agent_skill_dm.py`

Tests: exact selectors for scan metadata rejection, offline question creation/list/resolve/ignore,
resume/reconcile/status, wrong binding/rebind/stale/replay rejection, zero Mattermost calls/outbox,
and unchanged production behavior; Ruff only touched Python files.

## Blockers

None.

## Out of scope

- Production Mattermost behavior changes.
- Persisting runtime channel into recruiter configuration.
- Rebinding existing questions.
- Live scans, external writes, migrations, full pytest, commits.

## Assumptions

- Manual Mila invocation metadata is trusted only when injected through environment variables.
- `RecruiterConfig.mattermost_user_id` remains authoritative; its DM channel may be empty in
  offline test mode.
- Existing `ManualReview` columns can hold the immutable test binding.
