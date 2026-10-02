# Review: matching-signals-config

Diff `1834c18~3..1834c18` (swarm-report excluded). Initial verdict: **rework** (1 HIGH).

## Finding (resolved)

HIGH — `reject_dangerous_regex` only flagged the nested-quantifier ReDoS shape (`(a+)+`), not the
other classic family, alternation-based backtracking (`(a|a)*`, `(a|aa)*`). Reviewer demonstrated
live: `re.compile(r'^(a|a)*$').match('a'*25+'X')` took 2.26s, exponential growth per extra
character — a plausible operator typo bypassed the exact gate built to close this risk.

**Fixed in `624cc1b`:** `reject_dangerous_regex` now also rejects a quantified group whose body
contains unescaped alternation, not just one containing its own quantifier. Accepts the cost of a
false positive on genuinely safe alternation (e.g. `(cat|dog)+`) — acceptable since nothing uses
this override today.

## Everything else, confirmed directly by the reviewer (not just the build report)

- Single choke point: CLI write path and every `resolve_matching_signals` read both route through
  `reject_dangerous_regex` via `merge_matching_signals`. No second path.
- `cron.py`: a `resolve_matching_signals` failure advances only that one recording to `FAILED`
  (`error_step="matching_signals_config"`), never reaches `cal.find_events`, and the scan loop for
  other recordings is unaffected (confirmed via `calendar.find_events.assert_not_awaited()`).
- Exactly one production call site (`cron.py:226`); `_resume_found_recording`/
  `_run_found_recording`'s new optional `recruiter`/`signals` parameters don't change any existing
  test's behavior — `DEFAULT_MATCHING_SIGNALS` wraps the original compiled constant objects, not
  recompiled copies.
- Both `BOOKING_PATTERN` consumers (the calink-matching pool-entry check and `_score_event`) read
  `active_signals.booking_pattern` consistently — no stale direct reference left anywhere outside
  the default definition.
- `tools/setup/rematch_calendar_events.py` genuinely untouched; no `out_of_scope` item crept in.

## Post-fix verification (orchestrator)

```
poetry run pytest tests/test_recruiter_schema.py tests/test_matching.py tests/test_scheduler.py -q
120 passed in 3.04s

poetry run pytest -q   (first run)
1 failed (test_transfer_failure_is_isolated_between_recruiters — SQLite "cannot commit
transaction" — a known order-dependent flake), 498 passed, 2 skipped

poetry run pytest tests/test_scheduler.py::test_transfer_failure_is_isolated_between_recruiters -q
1 passed   (confirms flake, not a regression — unrelated to this change)

poetry run pytest -q   (second run)
499 passed, 2 skipped

poetry run ruff check app/services/recruiter_schema.py tests/test_recruiter_schema.py
All checks passed!

poetry run mypy app/services/recruiter_schema.py
Success: no issues found in 1 source file
```

**Final verdict: ship.**
