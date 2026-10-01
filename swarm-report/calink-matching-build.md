# Build: calink-matching

Plan: `swarm-report/calink-matching-plan.md`. Scope: python-fastapi (all files).

## Commits

- `a914f2e` fix(matching): add booking-marker pool-entry path for calink bookings
- `12cd70c` fix(tools): stop flagging correct calink matches as false matches
- `c1b7d5e` docs(memory-bank): mark calink matching implemented with final numbers (also carries a
  pre-existing uncommitted hunk from the digest-toggle task — disclosed in the commit body, nothing
  lost or altered)

## Implementation vs. plan

Matches the plan's narrow design exactly — did **not** take the planner's broader "drop title gate
for all events" draft; implemented the skeptic-safe version: `score()` builds `compatible` from one
loop with two independent per-event entry conditions (both still require the ±15 min window, both
excluded for events spanning ≥20h):
- title-exact-match (unchanged, default path), OR
- `BOOKING_PATTERN.search(event.description)` (calink.ru/calendly.com/cal.com) — bypasses the title
  check only when a real booking-link marker independently corroborates a genuine external booking.

Also fixed `INTERVIEW_PATTERN` to match the stem `собеседован` instead of the full nominative
`собеседование`, so inflected forms (genitive `собеседования`, etc.) are caught. No change to
`NAME_PATTERN`, `BOOKING_PATTERN`, `_score_event` weights, `confidence_threshold`, or
`FILENAME_PATTERN`.

`tools/setup/rematch_calendar_events.py`: `title_mismatch` heuristic removed entirely (the plan's
sanctioned smaller/safer option) — it would otherwise flag every correct calink match as false and
`--apply` would destructively requeue it. `find_false_calendar_matches()` now only flags
unparseable filenames.

## Verification (run by the orchestrator)

```
poetry run pytest -q
473 passed, 2 skipped in 31.97s

poetry run ruff check app/services/matching.py tests/test_matching.py tests/test_scheduler.py \
  tools/setup/rematch_calendar_events.py tests/test_rematch_calendar_events.py
All checks passed!

poetry run ruff format --diff app/services/matching.py tools/setup/rematch_calendar_events.py
2 files already formatted

poetry run mypy app/services/matching.py tools/setup/rematch_calendar_events.py
Success: no issues found in 2 source files
```

Reviewed the diffs directly (not just the agent's report): the booking-marker gate, the all-day
span guard, the regex stem fix, the new tests, and the rematch-tool removal all match the plan's
acceptance criteria line for line.

## Real confidence numbers (from tests/test_matching.py, built from real prod data)

- Четова Дарья calink case (calink.ru in description, mismatched title — both the generic
  Telemost-default filename and the manually-renamed one) — **1.0**, auto-matched.
- Денис Васильев / Михаил Кононенко consultation (exact title, no calink link) — **0.40**,
  `LOW_CONFIDENCE`, not auto-matched, not `NO_COMPATIBLE_EVENT`. Weights intentionally not widened.
- Bare calink-link case ("Ссылка для собеседования с Лилией Акентьевой", exact title, no calink.ru
  URL) — **0.45** after the regex fix, still `LOW_CONFIDENCE` — this calink template carries no
  machine-readable candidate identity; not fixable by scoring.
- `test_reported_non_recruiting_title_cannot_match_other_event` — **unchanged assertions, still
  passes** (`NO_COMPATIBLE_EVENT`) — proof the booking-marker path did not reopen the skeptic's
  HIGH-1 safety hole. The shared `event()` test helper's description defaults to a calink.ru URL
  for other tests' convenience; this test now passes `description=""` explicitly so it keeps
  testing "no booking marker" rather than silently becoming a different (passing-by-accident) case.
  The same incidental filler existed in one `tests/test_scheduler.py` fixture
  (`test_resume_regression_title_mismatch_persists_bounded_reason_only`) and was fixed the same way.
- All-day event alongside a real match — excluded by the ≥20h span guard, no spurious
  `MULTIPLE_ELIGIBLE`/`UNMONITORED_COLLISION`.

## Out of scope, confirmed untouched

`NAME_PATTERN`/`INTERVIEW_PATTERN` keyword widening or weight changes, `FILENAME_PATTERN`,
`confidence_threshold`, `app/scheduler/cron.py`'s `title_exact` diagnostic field,
`UNMONITORED_COLLISION` multi-calendar behavior for Anton/future recruiters.
