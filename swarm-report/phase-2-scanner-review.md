# Review: Phase 2 Scanner

## Verdict

`rework`

## Findings

- **HIGH — `app/tools/disk.py:76`:** Scanner never reads `custom_properties`, so
  Q9-processed files are rediscovered unless a DB row still exists; `mark_processed` at line
  122 moves files instead of PATCHing `processed`/`processed_at`, and `delete_expired` plus the
  Trash/permanent-delete flow are absent. Implement Q9 exactly and add intent-level tests, with
  an explicit approval gate before permanent deletion.
- **HIGH — `swarm-report/phase-2-scanner-plan.md:29`:** The plan/docs still specify moving to
  `/processed/` and line 360 defers retention, contradicting closed Memory Bank Q9 and the
  user's resolution; `.memory-bank/index.md` also still names uv despite Poetry-only operation.
  Reconcile the plan, build report, and relevant project documentation with Q9 and Poetry.
- **HIGH — `app/tools/calendar.py:124`:** Null-URL discovery caches `calendar-home-set` itself
  and immediately REPORTs it, but `calendar-home-set` is a container, not the exact calendar
  collection required by the plan; deployments without an operator-provided URL can fail.
  Discover/enumerate the actual calendar collection, cache that URL, and test the fallback.
- **HIGH — `app/scheduler/cron.py:51`:** A recording is committed as `found` before
  CalDAV/matching; any later transient exception aborts that recruiter, while `list_new`
  permanently excludes the row on future scans, leaving it stuck forever. Make persisted
  `found` rows resumable or make discovery+matching failure transition/retry semantics explicit
  and tested.
- **MEDIUM — `app/tools/calendar.py:75`:** Acceptance criterion 13 says CalDAV 401 must refresh
  and retry once, but implementation raises immediately; the detailed plan separately says
  CalDAV app-password 401 must not retry. Reconcile this contradictory acceptance criterion and
  test the chosen auth behavior.
- **MEDIUM — `app/config.py:24`:** Refresh tokens and CalDAV passwords are stored as plain
  strings in mappings, violating the project rule that sensitive settings use `SecretStr` and
  allowing model repr/dumps to expose credentials. Use secret-valued mappings and unwrap only at
  HTTP boundaries.
- **MEDIUM — `tests/test_disk_scanner.py:105`:** Tests encode the obsolete move-to-processed
  design, and there is no coverage for custom-property filtering/marking, seven-day cleanup,
  Trash then permanent deletion, scheduler registration/concurrency, or CalDAV discovery.
  Replace/add intent-level tests for the resolved requirements.

## Acceptance unmet

- Q9 custom-property marking/filtering.
- Q9 `>=7`-day Trash/permanent deletion with approval gate.
- Exact CalDAV collection discovery.
- Acceptance criterion 13 as originally written; the reconciled contract is Disk-only OAuth
  refresh/retry and immediate `CalDAVAuthError` for CalDAV app-password 401.
- Acceptance criterion 15 coverage.

## Verification

Tests were independently verified by the reviewer. Passing tests do not satisfy the unmet
intent-level requirements above.

## Documentation resolution

Memory Bank Q9 is authoritative. This review updates the plan and relevant documentation to
custom-property marking, a seven-day minimum retention interval, Trash-first deletion, and an
explicit approval gate before permanent deletion. Poetry is the project dependency/environment
manager. These documentation changes do not resolve the implementation findings; the verdict
remains `rework` until code and tests are corrected and re-reviewed.

## Re-review 1

### Verdict

`rework`

### Findings

- **Standing environment boolean is unsafe:** permanent deletion authority must not be a
  persistent configuration flag available to unattended cron execution. Approval must be
  explicit and scoped to one purge run.
- **Original path / non-resumable Trash purge:** the implementation attempted permanent delete
  using the original Disk path after soft deletion. It must enumerate actual `trash:/...`
  resource paths, correlate them through `origin_path`, and remain safe to rerun after partial
  failure.
- **Incomplete marker repair:** a source with only one of `processed` or `processed_at` could be
  skipped or left malformed. `mark_processed` must repair incomplete marker pairs
  idempotently.
- **Missing boundary, async, and recovery tests:** coverage did not prove the exact seven-day
  cutoff, 202 operation polling/failure behavior, marker repair, or purge recovery after a
  partial failure.
- **Missing scheduler isolation / no-standing-authority tests:** coverage did not prove cleanup
  failure isolation or that registered cron jobs carry no permanent-delete approval.
- **Missing terminal `found` transition:** known permanent CalDAV/config/payload failures could
  remain resumable forever instead of transitioning `found` to `failed` with diagnostic state.
- **Stale build report:** the report still described the first implementation and old test
  counts rather than the current rework.

## Rework resolution

- Removed standing permanent-delete configuration authority. `delete_expired()` is
  soft-delete-only and is the only retention operation registered with cron.
- Added separate `purge_expired_from_trash()` with a per-run `PermanentDeleteApproval` carrying
  a non-empty operator identity and timezone-aware approval timestamp no more than five minutes
  old.
- Permanent purge enumerates current Trash resources, uses real `trash:/...` paths, validates
  `origin_path`, processed markers, and retention age, and is safe to invoke again after partial
  failure.
- Incomplete processed markers are repaired idempotently. Discovery repairs
  `processed=true` with missing/invalid `processed_at` to current UTC and still excludes the
  resource; cleanup repairs it and does not delete it in that run.
- Added seven-day boundary, asynchronous operation, marker repair, partial-purge recovery,
  scheduler isolation/no-standing-authority, and terminal `found` failure coverage.
- Exact CalDAV collection discovery, `SecretStr` credential mappings, resumable transient
  failures, and explicit terminal permanent failures are implemented and covered.
- At the Re-review 1 checkpoint, Poetry verification was Ruff clean, 36 files formatted, mypy
  clean across 33 source files, and 50 tests passed with only the cache warning.

This section records implementation resolution only. No final `ship` verdict is claimed until
another independent review is completed.

## Re-review 2

### Verdict

`rework`

### Findings

- **Caller-controlled clock and reusable approval:** permanent purge accepted a caller-supplied
  `now`, allowing approval freshness checks to be influenced externally, and the same approval
  object could be reused after success or failure. A destructive approval must be validated
  against a trusted internal clock and consumed exactly once before any request.
- **Missing negative coverage:** tests did not prove rejection of an empty nonce, caller clock
  control, or approval reuse after both successful and failed purge attempts.

## Re-review 2 resolution

- `purge_expired_from_trash()` no longer accepts caller-controlled `now`; freshness is evaluated
  with an injected/trusted timezone-aware UTC clock.
- `PermanentDeleteApproval` now requires a non-empty unique `nonce` in addition to the named
  operator and timezone-aware timestamp.
- Approval is consumed before the first Disk request and cannot be reused after either success
  or failure. Any retry or partial-failure recovery requires a newly issued approval with a new
  nonce, then re-enumerates Trash.
- Negative coverage now verifies empty-nonce rejection and single-use behavior across successful
  and failed purge attempts.
- Current Poetry verification is Ruff clean, 36 files formatted, mypy clean across 33 source
  files, and 53 tests passed with only the cache warning.

At the Re-review 2 resolution checkpoint, this was an implementation-resolution record rather
than a final `ship` verdict; the independent final review below was still required.

## Final re-review

```yaml
verdict: ship
findings: []
acceptance_unmet: []
tests_verified: yes
```

Independent Poetry gate: Ruff clean, 36 files formatted, mypy clean across 33 source files, and
53 tests passed with only the non-fatal pytest cache warning.
