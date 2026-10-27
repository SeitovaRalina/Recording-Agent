# Build: shared Mattermost channel observer (mirror) (slug: shared-mattermost-observer)

Plan: `swarm-report/shared-mattermost-observer-plan.md`. All blockers resolved before build
(shape confirmed = mirror, Lilia's consent obtained, Ralina's existing DM binding confirmed live).

## python-fastapi agent

**Changed files:**
- `alembic/versions/20261027_1000_add_recruiter_observer_mattermost.py` (new) — additive,
  nullable `observer_mattermost_user_id`/`observer_mattermost_dm_channel`, `down_revision=20261006_1000`.
- `app/db/models/recruiter_config.py` — two new nullable `Text` columns.
- `app/services/question_queue.py` — new `mirror_to_observer()` helper; called from
  `build_digest` (after the summary `queue_notification`) and `apply_partial` (after the
  `processing_started` ack). Best-effort: `MattermostError` is caught and logged, never raised,
  never blocks/alters the primary send. No-op when either observer field is unset or in
  offline test mode.
- `tools/setup/configure_recruiter.py` — `set-observer`/`clear-observer` CLI subcommands,
  same confirm-prompt pattern as `set-digest`.
- `tests/test_question_queue.py`, `tests/test_tools_router.py`, `tests/test_configure_recruiter.py`
  — new tests (see below).

**Deviation from plan (not a blocker, functionally equivalent):** the plan's affected-files
list named `app/routers/tools.py` for the question-send/reply-ack mirror calls. Verified
`tools.py` never itself renders or sends a Mattermost message — every recruiter-facing message
(digest, processing_started, terminal completion/error, routing_deferred) is rendered and queued
inside `question_queue.py`. Mirror calls were placed at the two real call sites there instead.
`_bound_recruiter`/`_scan_recruiter`/`_question_recruiter` in `tools.py` are untouched, as the
plan required.

**Tests run:** `poetry run pytest -q` → `571 passed, 2 skipped`. `poetry run ruff check .` →
`All checks passed!`. Re-verified independently by the orchestrator (same commands, same result).

**New tests, mapped to plan acceptance criteria:**
- `test_digest_mirrors_verbatim_text_to_observer_when_configured` — digest mirror, verbatim text, `[Лилия]` prefix, correct `expected_channel_id`.
- `test_digest_is_a_noop_for_mirroring_when_observer_unset` — zero behavior change when unset.
- `test_mirror_failure_does_not_block_or_alter_the_primary_digest_send` — mirror `MattermostError` doesn't block the primary `NotificationOutbox` summary.
- `test_reply_acknowledgment_mirrors_to_observer_when_configured` — reply-ack mirror.
- `test_observer_identity_never_resolves_as_a_recruiter_binding` — observer fields never satisfy `_validate_dm`'s binding lookup, for the observed row or any other.
- `test_bound_recruiter_never_matches_via_a_recruiters_observer_fields` (in `test_tools_router.py`) — same invariant against `_bound_recruiter`.
- `test_observer_cannot_consume_a_capability_token_bound_to_the_observed_recruiter` — Ralina (observer, with her own real recruiter row) cannot consume Lilia's `ManualReview` capability token through her own valid DM binding; rejected by scope enforcement before token comparison, question stays `PENDING`.
- `configure_recruiter.py` set-observer/clear-observer round-trip + validation tests.

**Independent verification (orchestrator):** read every diff (`model`, migration, `mirror_to_observer`,
both call sites, CLI subcommands, all new tests) line by line; confirmed `display_name` field
exists on `RecruiterConfig`; re-ran full suite and ruff myself — same green result.

## backend (docs/memory-bank fallback) agent

**Changed files:**
- `.memory-bank/current-work.md` — item 5 updated: shape = mirror to Ralina's existing DM
  (not group channel); observer config = two nullable columns on the observed recruiter's row;
  observer never a recruiter identity; Lilia's consent (2026-10-27) and Ralina's pre-existing
  Mattermost binding (confirmed live) both noted.
- `.memory-bank/open-questions.md` — Q17 closed with the mirrored-notification answer,
  cross-referenced against Q3 (mirror reinforces "no shared-channel fallback" rather than
  overriding it).
- `docs/data-model.md` — documented the two new columns in the `recruiter_config` section,
  matching the existing `daily_digest_enabled` style.

No `.py` files touched (correctly out of scope); no migration revision id was guessed or cited
(none needed — the docs reference the plan and column names, not the revision id).

## Cross-check

Migration revision `20261027_1000` and both column names match exactly what docs/data-model.md
and current-work.md describe. No discrepancy to fix.

## Status: ship-ready pending deploy

Code complete, tests green, docs updated. Not yet committed or deployed — this has an Alembic
migration, so the canary-swap fast path is **forbidden**; deploy must go PR → `main` → CI →
`deploy.sh` per `current-work.md` → "Deployment path".
