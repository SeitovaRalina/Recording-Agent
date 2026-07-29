# Plan: Connect Synology inventory, folder mirror, and routing task (slug: synology-connect)

## TL;DR

Add an operator-only Synology rollout step before replacing MinIO in production: verify auth and
permissions, read-only scan exact roots `Recruiting-E` and `Recruiting-NE`, create an empty directory
mirror under the confirmed home roots, persist safe destinations as opaque IDs, and document a
separate routing task for choosing the right Synology destination, transferring a recording, and
creating a share link.

Current MinIO canary behavior remains unchanged. Production Synology requires explicit operator
approval after read-only inventory and permission proof.

## Acceptance Criteria

1. Synology credentials are configured only through environment variables or protected deployment
   secrets; passwords/API keys use `SecretStr` and are never logged.
2. Read-only inventory scans only the confirmed Synology source roots `Recruiting-E` and
   `Recruiting-NE`, with bounded depth, page count, and result count.
3. Inventory records canonical path, relative path, display name, writable flag, symlink flag,
   depth, and scan timestamp.
4. Inventory rejects traversal, non-absolute paths, symlinks, duplicate canonical paths, and paths
   outside the confirmed roots.
5. Mirror mode creates only missing empty folders under the confirmed target roots
   `/home/Recruiting-E` and `/home/Recruiting-NE`.
6. Mirror mode never uploads, downloads, deletes, overwrites, renames, or copies files.
7. Mirror mode is a production Synology mutation and runs only after an explicit approval following
   the read-only inventory report.
8. Existing MinIO remains the default and mandatory storage provider when `TEST_MODE_ENABLED=true`.
9. Production transfer is enabled only with `STORAGE_PROVIDER=synology`,
   `TEST_MODE_ENABLED=false`, and successful Synology preflight.
10. Discovered writable, symlink-safe folders are stored as `storage_destinations` with opaque IDs;
    Mila/OpenClaw receives bounded destination choices, not raw executable paths.
11. Agent routing task exists for recognizing the correct destination, asking a recruiter when
    ambiguous, moving/uploading the recording there through Backend, creating a Synology share
    link, and returning/persisting the link.
12. The agent never infers `external` versus `internal` from `📍 Spots` alone; if both allowed
    engineering roots contain the inferred role folder, Backend asks the recruiter whether the
    interview is for an external project or an internal role.
13. `Recording Root` and `Recording Folder` Notion fields are not part of the design.
14. Backend exposes bounded allowed Synology destination inventory and text signals to
    OpenClaw/Mila; OpenClaw/Mila's LLM performs semantic folder selection.
15. Backend does not hardcode semantic mappings such as `Java -> Backend` and does not call an LLM
    directly for folder selection.
16. If OpenClaw/Mila returns exactly one suitable allowed destination ID, Backend may route
    automatically after root containment, permission, symlink, and collision checks.
17. If OpenClaw/Mila returns zero or multiple suitable destinations, Mila asks the recruiter with a
    bounded list of candidates or offers safe new-folder creation under an allowed root.
18. A recruiter may override any inferred or stored destination by choosing another existing
    allowed folder or requesting creation of a safe new child folder under an allowed root.
19. Upload/share flow preserves the existing state machine:
    `transfer_started -> uploaded_to_synology -> synology_link_created`, then Notion update for
    interview routes or completed non-interview route without Notion update.
20. Storage collisions, ambiguous folder selection, inaccessible paths, invalid names, or share
    link failures fail closed and produce actionable manual review/errors.
21. Tests cover auth mode, inventory bounds, path canonicalization, symlink rejection, mirror
    create-only behavior, storage provider boundaries, transfer/share idempotency, and destination
    ID exposure.

## Plan

1. Resolve Synology auth before implementation.
   - Current memory says DSM 7.0+ is confirmed and API key auth is the target.
   - The new request provides URL, login, and password.
   - Preferred path: operator creates a Synology API key with File Station list/create/upload/share
     permissions.
   - Alternative path: explicitly reopen the auth decision and implement SID login with
     `SYNOLOGY_USER` and `SYNOLOGY_PASS`.

2. Add credential validation in `app/config.py`.
   - Keep `SYNOLOGY_BASE_URL`.
   - Keep `SYNOLOGY_API_KEY` as preferred production auth.
   - If SID login is approved, validate `SYNOLOGY_USER` and `SYNOLOGY_PASS` only for that mode.
   - Keep `STORAGE_PROVIDER=minio` as default.

3. Extend `app/tools/synology.py`.
   - Add a narrow auth abstraction if SID login is approved.
   - Add exact-root read-only inventory for `Recruiting-E` and `Recruiting-NE`.
   - Reuse existing canonical POSIX path checks.
   - Add bounded traversal and metadata collection.
   - Add a mirror helper that creates directories only, with `force_parent=false` per step where
     possible, and verifies the created folder is real and writable.

4. Add an operator CLI, `tools/setup/synology_sid_inventory.py`.
   - Commands: `preflight`, `inventory --dry-run`, `mirror-empty-tree`.
   - Output machine-readable JSON plus a redacted/safe Markdown summary.
   - Do not print secrets.
   - Dry-run must make no write calls.
   - Mirror command must show exact planned creations before requiring approval.

5. Extend `app/services/destinations.py`.
   - Discover only the approved roots.
   - Persist writable, symlink-safe folders as `StorageDestination`.
   - Leave read-only folders in the inventory report but do not expose them as route targets.

6. Document the discovered Synology folder set.
   - Create or update `docs/synology-inventory.md` only after deciding whether real folder names
     are safe to commit.
   - If folder names are sensitive, write a redacted summary in Git and keep the raw inventory
     outside the repository.
   - Keep raw inventory outside Git unless folder names are approved for repository docs.

7. Create the routing task spec.
   - Add `swarm-report/synology-routing-agent-task.md`.
   - Define signals the agent may use to suggest a destination.
   - Backend must resolve only stored destination IDs.
   - Ambiguity requires a recruiter choice.
   - `📍 Spots` may suggest the role/project subfolder, but it is not a source of truth for
     `external` versus `internal`.
   - `📍 Spots` is not a direct folder field; OpenClaw/Mila's LLM may reason that names such as
     `Java-разработчик @Т-банк` fit a folder such as `Backend`.
   - Backend must not contain semantic alias/scoring rules for folder choice.
   - Duplicate role folders under `/home/Recruiting-E/2. Interviews external` and
     `/home/Recruiting-E/3. Interviews internal` require a recruiter question.
   - Unique role folders such as `Aldo` or `Frontend`, when present in only one allowed root, may
     be selected automatically.
   - A recruiter override may select another existing allowed destination or request a safe new
     child folder under an allowed root.
   - Free-form folder text can request creation only under the configured recruiter root and only
     after Backend validation.
   - Share link policy must be explicit: no expiry vs expiry, password, public exposure rules.

8. Preserve MinIO canary.
   - No test-mode Synology writes.
   - No production Notion/Yandex mutations during inventory/mirror.
   - Production transfer rollout is separate from read-only inventory and empty folder mirroring.

## Affected Files

- `app/config.py`
- `app/tools/synology.py`
- `app/services/destinations.py`
- `app/scheduler/cron.py`
- `app/routers/tools.py`
- `openclaw/skills/recording-agent/SKILL.md`
- `openclaw/skills/recording-agent/references/contract.md`
- `openclaw/skills/recording-agent/scripts/recording_agent.py`
- `tools/setup/synology_sid_inventory.py`
- `docs/api-contracts/synology.md`
- `docs/synology-inventory.md`
- `.memory-bank/open-questions.md`
- `swarm-report/synology-routing-agent-task.md`
- `tests/test_synology.py`
- `tests/test_storage.py`
- `tests/test_transfer.py`
- `tests/test_safe_storage_cleanup.py`
- `tests/test_recording_agent_skill_dm.py`

## Tests

- `pytest tests/test_synology.py`
- `pytest tests/test_storage.py tests/test_transfer.py`
- `pytest tests/test_safe_storage_cleanup.py`
- `pytest tests/test_recording_agent_skill_dm.py`
- Manual approved dry-run: inventory `Recruiting-E` and `Recruiting-NE`; verify no create/upload/share
  calls.
- Manual approved mirror run: create only missing empty folders; verify no files copied and no
  source folders mutated.
- Manual approved transfer smoke test: upload one synthetic/test recording to a selected
  destination, create a share link, persist it, and verify idempotent retry.

## Resolved And Remaining Gaps

1. Auth contradiction resolved for this build: API key remains supported, and SID login is
   implemented for `SYNOLOGY_USER`, `SYNOLOGY_PASS`, and optional `SYNOLOGY_DEVICE_ID`.
2. Exact source roots are confirmed as `/Recruiting-E` and `/Recruiting-NE`.
3. Exact target roots are confirmed as `/home/Recruiting-E` and `/home/Recruiting-NE`.
4. Empty-folder mirroring was an approved production Synology write. Future mirror or cleanup
   mutations still require explicit operator approval.
5. Real folder names may be sensitive. Decide whether raw inventory can be committed to
   `docs/synology-inventory.md`; otherwise commit a redacted summary and keep raw inventory
   outside Git.
6. Share link policy is not specified: permanent vs expiring links, password protection, and who
   may access the generated link.

## Out Of Scope

- Copying existing Synology files.
- Deleting, renaming, or moving existing Synology folders/files during inventory or mirror.
- Yandex source cleanup.
- Production Notion writes during Synology inventory/mirror.
- Self-service recruiter onboarding.
- Replacing MinIO in test mode.

## Assumptions

- Empty folder replication means directory tree only; no file content or metadata preservation.
- Operator credentials have read access to source roots and create/write/share permissions under
  the target roots.
- Backend remains the only component allowed to perform storage mutations.
- Mila/OpenClaw receives safe choices and submits narrow Backend intents, never raw Synology
  credentials or unchecked paths.
