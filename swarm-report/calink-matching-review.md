# Review: calink-matching

Diff `7d54c9f~4..7d54c9f` (swarm-report excluded). Verdict: **ship**. `acceptance_unmet: []`.

## Verification

1. Core safety property (`app/services/matching.py:166-187`): confirmed via direct code reading —
   `if not title_matches and not has_booking_marker: continue` is the exact De Morgan form of
   "admit only if title match OR real booking marker." Being the sole event in a time window is
   never sufficient on its own.
2. All-day/multi-day guard (`matching.py:169`): the `>= MAX_EVENT_SPAN_FOR_POOL` (20h) check runs
   unconditionally before the title/booking-marker branch, excluding degenerate events from both
   paths. Matches `test_all_day_event_in_pool_window_does_not_cause_spurious_collision`.
3. `tools/setup/rematch_calendar_events.py`: no dead imports or leftover `title_mismatch`
   references; `apply_requeue` can no longer touch a correctly-matched calink recording.
4. `INTERVIEW_PATTERN` stem change (`собеседован`): checked morphology — no unintended false
   positives on unrelated Russian word forms; this signal is scoring-only (+0.05), not a gate.
5. No regression: `test_unique_exact_title_time_and_calink_auto_match` unaffected by the new
   OR-branch. The `description=""` override in `test_reported_non_recruiting_title_cannot_match_other_event`
   is necessary (not cosmetic) — the shared `event()` test helper defaults to a calink.ru URL,
   which would otherwise have silently made this regression test vacuous post-fix. The equivalent
   latent issue in `tests/test_scheduler.py` was also real and correctly fixed.

Manually recomputed signal weights for all 3 real-case tests (Четова Дарья 1.0, Денис/Михаил 0.40,
bare-calink 0.45) against the shipped code and confirmed they match exactly.
