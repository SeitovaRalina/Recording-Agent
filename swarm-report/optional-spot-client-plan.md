# Plan: Make Spot Client values optional for future recordings (slug: optional-spot-client)

## TL;DR

Allow null or blank `Spot Client` page values to use the deterministic storage component
`unspecified`. Keep the Notion schema property required, preserve nonblank naming and collision
handling, and leave all existing recording rows unchanged.

## Acceptance criteria

- A future unique Notion match whose `Spot Client` value is null, empty, or Unicode whitespace
  continues through storage upload, link creation, and Notion update.
- Its generated basename is
  `YYYY-MM-DD_<candidate>_unspecified_<interview_type>.<ext>`.
- Its storage key remains
  `<prefix>/<recruiter>/<date>/<candidate>/<generated_filename>`.
- Nonblank `Spot Client` values keep byte-for-byte compatible filename behavior.
- Nonblank values that sanitize to empty still fail closed as `invalid_storage_identity`.
- Cross-recording key collisions still become `manual_review_required`; no overwrite or silent
  suffix is allowed.
- Future Artem-like duplicate Notion matches remain `manual_review_required`; no card is selected
  automatically. After an authorized bounded choice, a blank `Spot Client` may use the fallback.
- Future Ralina-like low-confidence matches remain `manual_review_required`; only the existing
  authenticated, thread-bound, token/version/idempotency-guarded `ignore` may set `ignored`.
- Existing Anna, Artem, and Ralina rows are not updated, requeued, rescanned, resolved, or ignored.
- Only targeted tests run; the full suite and live canary do not run in this change.

## Plan

1. Update `app/services/filename.py`.
   - Accept `project_or_spot: str | None`.
   - Map only null, empty, or Unicode-whitespace-only values to `unspecified`.
   - Keep normal sanitization and rejection for nonblank malformed values.
   - Preserve current filename/key layout and length checks.
2. Update `app/scheduler/cron.py`.
   - Pass nullable project values to the storage identity builder on unique matches and bounded
     review resolutions.
   - Do not change ambiguity, low-confidence, authorization, or existing-row recovery behavior.
3. Add focused regression coverage.
   - `tests/test_phase4_filename.py`: null, empty, whitespace, nonblank, malformed nonblank,
     deterministic filename/key, and marker-like input.
   - `tests/test_scheduler.py`: future Anna-like unique blank-spot happy path and storage collision.
   - `tests/test_phase4_reviews.py`: future Artem-like bounded resolution with blank spot; preserve
     token/thread/version/idempotency and Ralina-like ignore guards.
4. Update `.memory-bank/open-questions.md` Q1 in English.
   - `Spot Client` remains a required `rich_text` schema property.
   - Its per-page value is optional and blank values use `unspecified`.
   - Collision semantics remain unchanged.
5. Run only targeted tests:
   - `poetry run pytest tests/test_phase4_filename.py`
   - Exact new scheduler test selectors.
   - Exact new review test selectors.

## Blockers

None. `unspecified` is the canonical fallback because it already exists in the Notion page model;
the storage collision guard covers a real value with the same text.

## Out of scope

- Database migrations or edits to existing rows.
- Requeue, rescan, retry, resolve, or ignore of current recordings.
- Making the `Spot Client` schema property itself optional.
- Automatic selection among duplicate Notion candidates.
- Automatic ignore of low-confidence recordings.
- Changes to storage providers, source mutation, scheduler policy, or review authorization.
- Full pytest or live integration canary.

## Assumptions

- “Optional” means a null or blank page value, not an absent Notion schema property.
- Future recordings include new scans and future bounded review resolutions only.
- `unspecified` is acceptable recruiter-facing filename text for a missing spot.
