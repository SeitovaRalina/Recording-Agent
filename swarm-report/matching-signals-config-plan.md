# Plan: per-recruiter configurable matching signals   (slug: matching-signals-config)

## TL;DR

`NAME_PATTERN`/`INTERVIEW_PATTERN`/`BOOKING_PATTERN` in `app/services/matching.py` are today global
module constants shared by every recruiter, built entirely from Lilia's real examples. Make them
per-recruiter overridable by the same `notion_property_map` precedent
(`app/services/recruiter_schema.py`): a new nullable `recruiter_config.matching_signals` JSON
column, `NULL` = today's global defaults, any subset of keys overrides only those fields. **Pure
architecture, zero functional change** — every current recruiter (Ralina, Lilia) resolves to
exactly today's regexes; nobody's matching behavior changes until an operator explicitly sets an
override for a future recruiter whose calink scheme actually differs.

This is explicitly built ahead of a second real example (the user has no second recruiter's calink
data to compare against yet) — a deliberate, acknowledged tradeoff, not a mistake. See Assumptions.

## Acceptance criteria

- `recruiter_config` gains nullable `matching_signals` JSON column (additive migration,
  `expand-contract`, no backfill). A `NULL` row resolves byte-for-byte to today's compiled
  `NAME_PATTERN`/`INTERVIEW_PATTERN`/`BOOKING_PATTERN` — proven by a regression test, not assumed.
- `app/services/matching.py`: new `MatchingSignals` frozen dataclass (three `re.Pattern[str]`
  fields) + `DEFAULT_MATCHING_SIGNALS` built from the existing three constants (constants stay, not
  removed/recompiled). `InterviewMatcher.score(recording, events, signals: MatchingSignals | None =
  None)` resolves `active = signals or DEFAULT_MATCHING_SIGNALS` and threads it into `_score_event`
  and the booking-marker pool-entry check (replacing the direct `BOOKING_PATTERN.search(...)` call
  added by the calink-matching fix). `TELEMOST_PATTERN`/`FILENAME_PATTERN`/
  `MAX_EVENT_SPAN_FOR_POOL`/`confidence_threshold`/signal weights are unaffected — out of scope.
- `app/services/recruiter_schema.py`: `MatchingSignalsOverrides` (pydantic, `extra="forbid"`,
  `name_pattern`/`interview_pattern`/`booking_pattern: str | None`), `merge_matching_signals(...)`,
  `resolve_matching_signals(recruiter: RecruiterConfig | None) -> MatchingSignals` — same shape as
  `resolve_notion_property_map`, deviating only in not taking a `settings` argument (defaults live
  in `matching.py`, not `Settings`).
- **Regex safety gate (closes a real ReDoS risk, not optional):** `merge_matching_signals` validates
  each overridden field with (1) `re.compile(value)` for syntax, AND (2) a static complexity check
  that rejects classic catastrophic-backtracking shapes — a parenthesized group containing its own
  `+`/`*` quantifier, itself followed by another `+`/`*`/`{...}` (e.g. `(a+)+`, `(a*)*`,
  `([a-zA-Z]+)*`). This is a heuristic, not an exhaustive ReDoS detector — proportionate to the real
  threat model (an authenticated operator's CLI typo, not adversarial/public input), not a
  general-purpose regex sandbox. Both the CLI write path and every `resolve_matching_signals` read
  go through this one function — no second, divergent validation path.
- Malformed override (bad JSON shape, invalid regex syntax, or a rejected dangerous pattern) raises
  `PermissionError` at resolve time — same exception type and "operator misconfiguration" handling
  as the existing `notion_preflight` failure path (deliberate consistency, not a misuse of the
  exception — see Assumptions). `cron.py`'s `_run_found_recording` catches it and advances the
  recording to `FAILED` (`error_step="matching_signals_config"`) instead of crashing the scan or
  silently falling back — loud and visible, matching this codebase's existing convention for
  operator-config errors. In the sanctioned path this can only happen from a raw DB edit, since the
  CLI write already validates before persisting.
- `recruiter: RecruiterConfig` (already in scope at `_scan_recruiter_unlocked`, **confirmed via
  grep at `app/scheduler/cron.py:226` — ast-index's `usages`/`callers` missed this intra-module
  private-function call site**, see note below) threads through as a new trailing **optional**
  `recruiter: RecruiterConfig | None = None` kwarg on `_resume_found_recording` and
  `_run_found_recording`, defaulting to `None` (→ global signals) so every existing call site in
  `tests/test_matching.py`/`tests/test_scheduler.py` (~30, not ~15 — corrected count) keeps
  compiling and passing unchanged. Only the one real call site (`cron.py:226`) is updated to pass
  the recruiter it already has.
- `tools/setup/rematch_calendar_events.py` needs **no changes** — confirmed (ast-index + direct
  read) it only calls `parse_recording_filename`, never `score()` or the three regex constants.
- `tools/setup/configure_recruiter.py` gains `set-matching-signals --email EMAIL --json <inline-or-
  @file> | --clear`, validated through `merge_matching_signals` before persisting — the only
  sanctioned way to populate the column until a real second recruiter scheme needs it.
- `docs/data-model.md` documents `matching_signals` next to `notion_property_map` (same NULL-
  inherits/per-field-merge wording), explicitly noting: an override that doesn't embed `(?i)` loses
  the implicit case-insensitivity the global `INTERVIEW_PATTERN`/`BOOKING_PATTERN` have today — a
  real behavior difference for whoever eventually writes an override, must not be a silent surprise.
- `deploy/release-metadata.json` bumped to the new revision, `expand-contract`,
  `previousApplicationCompatibleWithTargetSchema=true` (same shape as the two prior migrations this
  week).
- Tests: NULL-column regression (byte-identical to today); partial override changes only the
  overridden field; invalid-regex-syntax and dangerous-pattern overrides both raise at `merge_matching_signals`
  (CLI write time) and at `resolve_matching_signals` (read time, simulating a raw DB edit);
  `score()` with an explicit custom `signals` actually changes the outcome of the real calink
  fixture (proves it's consulted, not ignored); end-to-end `scan_recruiter` test showing a
  recruiter with an override matches differently than one with `NULL`; the 4 existing
  `_resume_found_recording` call sites in `tests/test_scheduler.py` pass unmodified.
- `poetry run pytest -q` full suite passes; cite the real count.

## Plan

### Steps

1. `ast-index usages`/`search` for `NAME_PATTERN`/`INTERVIEW_PATTERN`/`BOOKING_PATTERN` to confirm
   no other module reads them as bare globals before touching `matching.py`. **Also grep** for
   `_resume_found_recording`/`_run_found_recording` call sites — ast-index missed the real one at
   `cron.py:226` in this session's own investigation; do not trust ast-index alone for
   underscore-prefixed intra-module functions, per the repo's own tooling gap found today.
2. `app/services/matching.py`: add `MatchingSignals`/`DEFAULT_MATCHING_SIGNALS`; thread `signals`
   through `score()`/`_score_event()` with `signals=None` default; replace the direct
   `BOOKING_PATTERN.search(...)` pool-entry check with `active.booking_pattern.search(...)`.
3. `app/services/recruiter_schema.py`: add `MatchingSignalsOverrides`, the dangerous-regex static
   check helper, `merge_matching_signals`, `resolve_matching_signals`.
4. `app/db/models/recruiter_config.py`: add the `matching_signals` column.
5. Generate the Alembic migration (`/migrate generate "add recruiter matching_signals override
   column"`, `down_revision` = current head), review the diff (JSON column only).
6. `deploy/release-metadata.json`: bump revision.
7. `app/scheduler/cron.py`: thread `recruiter` through `_resume_found_recording`/
   `_run_found_recording` (optional, default `None`); resolve signals right after
   `active_settings = settings or get_settings()`; catch `PermissionError` → `FAILED` with
   `error_step="matching_signals_config"`; pass `signals=signals` into both `matcher.score(...)`
   call sites (~1293 filename-parse-failure branch, ~1336 main branch).
8. `tools/setup/configure_recruiter.py`: add `set-matching-signals` subcommand.
9. `docs/data-model.md`: document the column and the case-sensitivity caveat.
10. Tests per Acceptance criteria.
11. `ast-index usages` for `BOOKING_PATTERN`/`NAME_PATTERN`/`INTERVIEW_PATTERN` again after editing
    to confirm no stale direct references survive outside `matching.py`'s own default wiring.
12. `poetry run pytest -q` (full) + scoped `pytest tests/test_matching.py
    tests/test_recruiter_schema.py tests/test_scheduler.py -q`; `ruff check`/`format --check`/`mypy`
    on changed files only (repo's installed ruff reformats unrelated pre-existing lines elsewhere —
    do not run it on the whole repo).

### Affected files

`app/services/matching.py`, `app/services/recruiter_schema.py`, `app/db/models/recruiter_config.py`,
new Alembic migration, `deploy/release-metadata.json`, `app/scheduler/cron.py`,
`tools/setup/configure_recruiter.py`, `docs/data-model.md`, `tests/test_matching.py`,
`tests/test_recruiter_schema.py`, `tests/test_scheduler.py`.

## Blockers

None. The ReDoS risk the skeptic flagged as HIGH is resolved in this plan (static complexity gate
at the single validation choke point, applied at both write and read time) — not deferred.

## Out of scope

- Changing any actual regex value for any recruiter — Ralina and Lilia both resolve to current
  global defaults; this ships pure architecture.
- `TELEMOST_PATTERN`, `FILENAME_PATTERN`, `MAX_EVENT_SPAN_FOR_POOL`, `confidence_threshold`, or any
  `_score_event` weight.
- A UI/Mattermost-facing way for recruiters to self-service their own matching signals — operator-
  only CLI/DB column, same tier as `notion_property_map` today.
- Backfilling `matching_signals` for existing recruiters.
- Any change to `tools/setup/rematch_calendar_events.py`.
- A general-purpose ReDoS-proof regex sandbox (timeout-based execution, the third-party `regex`
  module, subprocess isolation) — the static complexity gate is the proportionate choice given the
  threat model; revisit only if this column ever accepts untrusted (non-operator) input.

## Assumptions

- **Named tradeoff, not hidden:** this is built ahead of need — there is exactly one recruiter
  (Lilia) with any demonstrated calink-specific signal requirement, and that need was already fixed
  via a shared-logic change (the booking-marker pool-entry path), not a per-recruiter override. No
  second recruiter's real scheme exists to validate this architecture against. The user made this
  call explicitly, accepting the risk of unexercised code paths until a real second case arrives;
  this plan keeps the override path minimal (no CLI ergonomics polish beyond correctness) per that
  same reasoning.
- `PermissionError` for a malformed `matching_signals` column is a deliberate reuse of this
  codebase's existing "operator misconfiguration → fail loud, not silent" convention (same pattern
  as `notion_preflight` failures), not an overload of an unrelated exception's meaning — chosen
  over a silent per-field fallback specifically because write-time CLI validation should prevent
  this in the sanctioned path, and a silent fallback risks masking a real operator mistake.
- An override that omits `(?i)` loses the implicit case-insensitivity `INTERVIEW_PATTERN`/
  `BOOKING_PATTERN` have today — documented, not silently different; no live recruiter is affected
  since nobody overrides anything yet.
- `resolve_matching_signals` takes no `settings` argument (unlike `resolve_notion_property_map`)
  because its defaults live in `matching.py` module constants, not a `Settings` field — a deliberate
  deviation from the precedent, noted in the module docstring so a future reader isn't confused by
  the signature asymmetry.
