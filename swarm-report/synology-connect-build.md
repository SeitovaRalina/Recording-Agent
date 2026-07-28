# Build Report: synology-connect

## Status

Complete.

## Scope

Python/FastAPI backend and operator tooling.

## Changed Files

- `app/config.py`
- `app/tools/synology.py`
- `app/services/storage.py`
- `app/services/destinations.py`
- `app/services/transfer.py`
- `app/scheduler/cron.py`
- `app/routers/tools.py`
- `openclaw/skills/recording-agent/SKILL.md`
- `openclaw/skills/recording-agent/references/contract.md`
- `openclaw/skills/recording-agent/scripts/recording_agent.py`
- `tools/setup/synology_sid_inventory.py`
- `swarm-report/synology-connect-plan.md`
- `swarm-report/synology-routing-agent-task.md`
- `tests/test_synology.py`
- `tests/test_storage.py`
- `tests/test_transfer.py`
- `tests/test_scheduler.py`
- `tests/test_safe_storage_cleanup.py`
- `tests/test_config.py`
- `.env.example`
- `.env.production.example`

## Implementation Notes

- Added Synology SID login support with `SYNOLOGY_USER`, `SYNOLOGY_PASS`, and optional
  `SYNOLOGY_DEVICE_ID`; API key remains supported when available.
- `StorageFactory` now passes SID credentials/device token into `SynologyBackend`.
- Synology calls use SID auth automatically when no API key is configured.
- Destination discovery is bounded to `SYNOLOGY_INTERVIEW_ROOTS`, configured as a JSON array or
  comma-separated list. Backend code does not contain recruiter-specific Synology root literals.
- Backend exposes bounded allowed destination candidates and validates selected destination IDs.
- Destination API and CLI now include a safe full path label for LLM disambiguation while mutation
  commands accept only opaque `destination_id`.
- Backend no longer performs semantic folder matching and contains no hardcoded mapping such as
  `Java -> Backend`; OpenClaw/Mila's LLM owns that reasoning over the bounded inventory.
- Synology interview flow stops after candidate match when no `storage_destination_id` exists and
  enters `manual_review_required` with reason `storage_destination_required`.
- Added `route-interview` CLI/API command. Mila sends `recording_id`, `destination_id`,
  `expected_version`, and `idempotency_key`; Backend validates recruiter DM binding, version,
  route type, candidate state, and allowed Synology destination before resuming transfer.
- Transfer can use a persisted `storage_destination_id` for Synology uploads and rejects
  destinations outside the allowed roots.
- Added operator script `tools/setup/synology_sid_inventory.py` for SID/device-token inventory and
  create-only mirror operations.

## Gaps Found

- Duplicate display names such as `Flutter` were not disambiguable from API/CLI output. Fixed with
  `path_label`.
- There was no interview routing intent for Mila/OpenClaw to submit a selected destination. Fixed
  with `route-interview`.
- Synology provider could still auto-upload using the old generated `storage_key` immediately after
  candidate match. Fixed: Synology waits for a selected destination ID; MinIO keeps legacy behavior.
- Transfer checked `storage_key` before `storage_destination_id`. Fixed: Synology destination ID now
  wins over old key state.
- Operator mirror helper had prior spelling ambiguity. Fixed target root names are
  `/home/Recruiting-E` and `/home/Recruiting-NE`.
- Allowed interview roots were initially hardcoded in `DestinationService` and `TransferService`.
  Fixed: both now use `Settings.synology_interview_roots`, and Synology production config rejects
  startup without `SYNOLOGY_INTERVIEW_ROOTS`.

## Remaining Gaps

- Rerouting after a completed Synology upload is specified but not implemented. It needs safe move
  or superseded-path tracking before any old-file cleanup.
- Share-link policy is still operationally undefined: expiry, password, and audience must be
  decided before production rollout.
- Raw Synology inventory is not committed because folder names may be sensitive. Production docs
  need an approved redacted inventory summary or a private artifact.
- Backend still needs a production smoke test with one synthetic recording, one selected
  destination, a Synology upload, share link creation, and Notion update.

## Verification

Rework verification for reviewer findings:

Command:

```powershell
.\.venv\Scripts\python.exe -m ruff check app\config.py app\main.py app\tools\synology.py app\services\storage.py app\services\destinations.py app\services\transfer.py app\scheduler\cron.py app\routers\tools.py openclaw\skills\recording-agent\scripts\recording_agent.py tests\test_config.py tests\test_synology.py tests\test_storage.py tests\test_transfer.py tests\test_scheduler.py tests\test_safe_storage_cleanup.py tests\test_tools_router.py tools\setup\synology_sid_inventory.py
```

Result:

```text
All checks passed!
```

Command:

```powershell
.\.venv\Scripts\python.exe -m mypy app\config.py app\main.py app\tools\synology.py app\services\storage.py app\services\destinations.py app\services\transfer.py app\scheduler\cron.py app\routers\tools.py
```

Result:

```text
Success: no issues found in 8 source files
```

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config.py tests\test_synology.py tests\test_storage.py tests\test_transfer.py tests\test_scheduler.py tests\test_safe_storage_cleanup.py tests\test_tools_router.py tests\test_recording_agent_skill_dm.py
```

Result:

```text
112 passed, 1 warning in 9.19s
```

Command:

```powershell
.\.venv\Scripts\python.exe -m ruff check app\config.py app\tools\synology.py app\services\storage.py app\services\destinations.py app\services\transfer.py app\scheduler\cron.py app\routers\tools.py openclaw\skills\recording-agent\scripts\recording_agent.py tests\test_synology.py tests\test_storage.py tests\test_transfer.py tests\test_scheduler.py tests\test_safe_storage_cleanup.py tests\test_tools_router.py tools\setup\synology_sid_inventory.py
```

Result:

```text
All checks passed!
```

Command:

```powershell
.\.venv\Scripts\python.exe -m mypy app\config.py app\tools\synology.py app\services\storage.py app\services\destinations.py app\services\transfer.py app\scheduler\cron.py app\routers\tools.py
```

Result:

```text
Success: no issues found in 7 source files
```

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config.py tests\test_synology.py tests\test_storage.py tests\test_transfer.py tests\test_scheduler.py tests\test_safe_storage_cleanup.py tests\test_tools_router.py tests\test_recording_agent_skill_dm.py
```

Result:

```text
110 passed, 1 warning in 9.72s
```

Warning:

```text
PytestCacheWarning: could not create cache path ... .pytest_cache ... [WinError 5] Access denied
```

The warning is limited to pytest cache writing and did not fail tests.

## Sources

- Synology File Station Official API guide was used to verify `SYNO.FileStation.CreateFolder` and
  `SYNO.FileStation.Rename` method existence and request parameters.
