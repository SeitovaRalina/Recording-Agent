# Debug: Manual root-SSH canary release workflow

## Symptom

Review returned rework: unusable Notion smoke CLI call, image digest not bound to commit, no disk
capacity gate, and missing focused canary test coverage.

## Root cause and fix

- Smoke called nonexistent `--test-only-schema` and did not provide the required database ID.
  It now reads exactly one nonempty ID from the canary-only allowlist and calls
  `preflight_notion.py --database-id`.
- Candidate images had no OCI revision label and deploy only shape-validated their digest. The
  build labels the image with `org.opencontainers.image.revision`; deploy inspects and requires it
  to equal the supplied full SHA before Docker mutation.
- Deploy had only the RAM/no-swap guard. It now requires 4 GiB free under the canary root parent
  before extraction, pull, or Compose startup.
- Added focused static tests for smoke argument/allowlist, OCI revision binding, disk gate, and
  candidate label. Fixed the preflight test fixture to supply the required Notion title/project
  property.

## Verification

- Focused canary/preflight suite: `11 passed, 1 warning in 2.12s`.
- Full suite: `poetry run pytest -q` — `352 passed, 1 warning in 250.35s`.
- Warning: pytest cache cannot be written due existing Windows permissions under `.pytest_cache`.
  No test failure.

## Follow-up review coverage

- Added workflow and Compose isolation tests plus hermetic Linux shell tests for OCI-revision and
  disk-gate rejection. The two shell executions are skipped on Windows because the root-only Bash
  scripts execute on the Linux canary host.
- Focused suite: `15 passed, 2 skipped, 1 warning in 1.30s`.
- Final full suite: `356 passed, 2 skipped, 1 warning in 174.43s`.
