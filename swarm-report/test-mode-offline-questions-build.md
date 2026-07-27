# Build report: Test-mode offline questions flow

## Result

Implemented the approved offline test interaction binding without database migrations, configuration
mutation, live scans, or external Mattermost calls.

## Changes

- Manual `scan` now carries recruiter email, recruiter user ID, and DM channel in its bounded
  request. All three values must originate in trusted invocation environment variables.
- Backend scan idempotency fingerprints include the immutable user/channel metadata.
- Offline test scans create durable questions using the exact request binding without validating
  or sending through Mattermost.
- Existing pending questions cannot be rebound to another interaction.
- Offline question list and answer operations validate the configured recruiter, test allowlists,
  exact persisted channel, capability, question set, recording version, and idempotency.
- Offline ignore reaches `ignored`; resolve preserves the selected choice and can replay only the
  same completed idempotent action.
- Reconciliation uses the immutable interaction binding.
- Processing and terminal offline transitions create no notification outbox rows.
- Production configured-DM validation and notification behavior remain unchanged.

## Files

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

## Verification

```text
poetry run pytest -q tests/test_recording_agent_skill.py::test_scan_uses_trusted_recruiter_email_from_environment tests/test_recording_agent_skill.py::test_scan_rejects_conflicting_explicit_recruiter_email tests/test_recording_agent_skill.py::test_scan_rejects_explicit_identity_without_trusted_metadata tests/test_recording_agent_skill_dm.py::test_questions_use_trusted_dm_metadata tests/test_recording_agent_skill_dm.py::test_questions_reject_conflicting_explicit_dm_metadata tests/test_recording_agent_skill_dm.py::test_explicit_dm_metadata_cannot_establish_missing_trusted_environment tests/test_recording_agent_skill_dm.py::test_partial_answer_sends_only_validated_exact_actions tests/test_tools_router.py::test_offline_scan_binding_is_exact_and_in_request_payload tests/test_tools_router.py::test_offline_question_recruiter_rejects_non_allowlisted_user tests/test_scheduler.py::test_offline_manual_scan_creates_exact_bound_question_without_mattermost tests/test_question_queue.py::test_offline_questions_enforce_immutable_binding_and_create_no_outbox

11 passed, 1 warning in 0.46s
```

```text
poetry run pytest -q tests/test_question_queue.py::test_partial_answer_accepts_exact_item_and_leaves_other_pending tests/test_question_queue.py::test_reconcile_processing_marks_terminal_and_queues_completion tests/test_question_queue.py::test_digest_rotates_digest_bound_capability_with_next_day_ttl tests/test_scheduler.py::test_scan_enqueues_manual_review_question_for_daily_digest tests/test_scheduler.py::test_test_mode_scan_skips_dm_review_enqueue_when_delivery_disabled tests/test_recording_agent_skill_dm.py::test_conflict_failure_does_not_print_backend_secret tests/test_tools_router.py::test_tools_authenticate_docker_bridge_peer_by_secret

7 passed, 1 warning in 0.39s
```

```text
poetry run pytest -q tests/test_question_queue.py::test_offline_resolve_preserves_choice_version_and_idempotent_replay tests/test_question_queue.py::test_offline_questions_enforce_immutable_binding_and_create_no_outbox tests/test_scheduler.py::test_offline_manual_scan_creates_exact_bound_question_without_mattermost tests/test_tools_router.py::test_offline_scan_binding_is_exact_and_in_request_payload tests/test_tools_router.py::test_offline_question_recruiter_rejects_non_allowlisted_user

5 passed, 1 warning in 0.33s
```

```text
poetry run ruff check app/routers/tools.py app/scheduler/cron.py app/services/reviews.py app/services/question_queue.py openclaw/skills/recording-agent/scripts/recording_agent.py tests/test_scheduler.py tests/test_tools_router.py tests/test_question_queue.py tests/test_recording_agent_skill.py tests/test_recording_agent_skill_dm.py

All checks passed!
```

The pytest warning is the existing sandbox denial when pytest attempts to write `.pytest_cache`.

## Review retry

The scan binding conflict gate now runs inside the same in-process recruiter lock and before
calendar refresh, Disk listing, or recording mutation. Concurrent offline scans using different
channels produce one durable binding; the second request receives a bounded conflict. The router
returns HTTP 409 and releases its owned pending scan intent, so the key is not stranded until the
claim TTL.

API-level answer tests now cover both offline actions through the real router contract:

- `ignore`: commit, reconciliation, idempotent replay, and status reporting as `ignored`;
- `resolve`: commit, pipeline resume, reconciliation, idempotent replay, and final `completed`
  status;
- both preserve exact binding and create no Mattermost calls or notification outbox rows.

```text
poetry run pytest -q tests/test_scheduler.py::test_concurrent_offline_channels_bind_once_and_reject_before_second_scan_effects tests/test_tools_router.py::test_offline_scan_binding_race_returns_409_and_releases_intent tests/test_tools_router.py::test_offline_answer_api_commits_reconciles_replays_and_reports_status

4 passed, 1 warning in 0.37s
```

```text
poetry run pytest -q tests/test_recording_agent_skill.py::test_scan_uses_trusted_recruiter_email_from_environment tests/test_recording_agent_skill.py::test_scan_rejects_conflicting_explicit_recruiter_email tests/test_recording_agent_skill.py::test_scan_rejects_explicit_identity_without_trusted_metadata tests/test_recording_agent_skill_dm.py::test_questions_use_trusted_dm_metadata tests/test_recording_agent_skill_dm.py::test_questions_reject_conflicting_explicit_dm_metadata tests/test_recording_agent_skill_dm.py::test_explicit_dm_metadata_cannot_establish_missing_trusted_environment tests/test_recording_agent_skill_dm.py::test_partial_answer_sends_only_validated_exact_actions tests/test_tools_router.py::test_offline_scan_binding_is_exact_and_in_request_payload tests/test_tools_router.py::test_offline_question_recruiter_rejects_non_allowlisted_user tests/test_scheduler.py::test_offline_manual_scan_creates_exact_bound_question_without_mattermost tests/test_question_queue.py::test_offline_questions_enforce_immutable_binding_and_create_no_outbox tests/test_question_queue.py::test_offline_resolve_preserves_choice_version_and_idempotent_replay

12 passed, 1 warning in 0.34s
```

```text
poetry run pytest -q tests/test_question_queue.py::test_partial_answer_accepts_exact_item_and_leaves_other_pending tests/test_question_queue.py::test_reconcile_processing_marks_terminal_and_queues_completion tests/test_question_queue.py::test_digest_rotates_digest_bound_capability_with_next_day_ttl tests/test_scheduler.py::test_scan_enqueues_manual_review_question_for_daily_digest tests/test_scheduler.py::test_test_mode_scan_skips_dm_review_enqueue_when_delivery_disabled tests/test_recording_agent_skill_dm.py::test_conflict_failure_does_not_print_backend_secret tests/test_tools_router.py::test_tools_authenticate_docker_bridge_peer_by_secret

7 passed, 1 warning in 0.35s
```
