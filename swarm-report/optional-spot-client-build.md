# Build report: optional-spot-client

## Status

Complete. No commits. No existing database rows changed.

## Python/FastAPI scope

Changed:

- `app/services/filename.py`
- `app/scheduler/cron.py`
- `tests/test_phase4_filename.py`
- `tests/test_scheduler.py`
- `tests/test_phase4_reviews.py`

Behavior:

- Null, empty, or Unicode-whitespace-only `Spot Client` uses `unspecified`.
- Nonblank values keep existing sanitization behavior.
- Storage collision and bounded review/ignore guards remain unchanged.

Verification:

```text
poetry run pytest tests/test_phase4_filename.py -q
11 passed, 1 warning in 0.03s

poetry run pytest tests/test_scheduler.py::test_unique_candidate_with_blank_spot_reaches_source_marked_processed tests/test_scheduler.py::test_blank_spot_storage_key_collision_requires_manual_review tests/test_phase4_reviews.py::test_review_resolution_is_bound_and_idempotent -q
3 passed, 1 warning in 0.24s

poetry run pytest tests/test_phase4_reviews.py::test_review_rejects_wrong_thread_before_consuming -q
1 passed, 1 warning in 0.09s

poetry run ruff check app/services/filename.py app/scheduler/cron.py tests/test_phase4_filename.py tests/test_scheduler.py tests/test_phase4_reviews.py
All checks passed!
```

Warnings were limited to Windows `.pytest_cache` `WinError 5`.

## Backend documentation scope

Changed:

- `.memory-bank/open-questions.md`

Q1 now states that the `Spot Client` schema property remains required while its per-page value is
optional for future recordings. Blank values use `unspecified`; collision behavior is unchanged.

## Cross-layer notes

- No API or database schema change.
- Existing Anna, Artem, and Ralina rows were not requeued, resolved, ignored, or otherwise edited
  during build.
- Full pytest and live canary were not run per user request.
