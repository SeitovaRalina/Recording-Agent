# Plan: Public permanent Synology links and safe reroute/reassignment (slug: synology-public-reroute)

## TL;DR

Restore explicitly approved public permanent Synology links (`date_expired=-1`, no password, no
expiry). Add durable, idempotent post-upload reroute and Notion-card reassignment operations. Both
accept only Backend-validated opaque IDs; folder text and Notion URL/name remain Mila lookup hints.
Artifact history is preserved. Verified CopyMove is an actual move: it removes the physical source
only after the target task and destination verification succeed. No raw path, arbitrary page mutation,
rename, overwrite, or other automatic deletion is introduced.

## Acceptance criteria

1. Production Synology sharing intentionally creates public, no-password, no-expiry links with
   `date_expired=-1`; URL is persisted. No expiry/password settings or validation remain.
2. Public exposure risk, explicit no-human-owner waiver, technical account, revocation procedure, and exact File Station request are documented
   in Memory Bank and Synology contract; tests assert no password/expiry field is sent.
3. Current uncommitted expiring-link retry is reconciled in an isolated checkpoint without losing
   live destination validation and no-parent-creation fixes.
4. A recruiter can request folder reroute only through a returned `destination_id`. Mila may
   compare a name/path fragment only with fresh bounded labels; zero/multiple match requires a DM
   question. Backend receives no raw path.
5. Reroute validates DM/recruiter binding, ownership, expected version, idempotency, active-workflow
   exclusion, allowed root, current writable real non-symlink directory, collision and owner marker.
6. Reroute executes verified CopyMove move or source re-upload fallback, creates a new
   public link, and switches active artifact after durable checkpoints. Immutable history retains the
   prior artifact even when physical source removal is explicitly approved.
7. Crash/retry at every external step is idempotent, recoverable, auditable, and never blindly
   repeats an ambiguous NAS mutation.
8. A Notion URL/name returns only capped candidates from the configured recruiter database with
   verified schema. URL parsing alone never authorizes a page.
9. Notion reassignment needs a one-time, TTL, DM-, target-, recording-version-, and idempotency-
   bound explicit confirmation before any Notion write.
10. Ordinary candidate lookup excludes cards with a non-empty `General Interview recording` value;
    only an explicit confirmed reassignment may target an occupied card.
11. Existing MinIO, initial route, non-interview route, source cleanup, and terminal recording state
    semantics remain unchanged.

## Plan

1. Inspect current dirty diff. Revert only expiring-policy changes in `.env*`, config, Synology,
   transfer, tests, and build report. Retain live destination safety changes. Commit this policy
   checkpoint through `/commit`.
2. Update `.memory-bank/architecture.md`, `decisions.md`, `open-questions.md`, API docs, examples,
   `synology-connect` plan/build report: public permanent policy is explicit, accepted risk;
   document File Station link revocation procedure, the `inerview_recordis_saver` technical
   account, and the user-approved absence of a dedicated human incident owner.
3. Before code, prove deployed DSM `SYNO.FileStation.CopyMove` API version, same/cross-share behavior,
   permissions, async task polling, collision behavior, `remove_src` semantics, and owner-marker/
   file preservation. If unsupported, allow re-upload only while Yandex source is available; otherwise
   fail actionable without mutation.
4. Generate an Alembic migration via `/migrate`: immutable `recording_storage_artifacts`, reroute
   operation/audit state, and Notion reassignment proposal state. Backfill only rows with complete,
   proven Synology path/link identity; mark all others legacy/unreroutable, never guess.
5. Add reroute saga service. Use recording-level ownership lease plus operation lease/checkpoints:
   validate target, CopyMove with `remove_src=true`/re-upload with `overwrite=false`, poll/verify
   marker and size, create
   link, write pending/new artifact, replace the current card's `General Interview recording` value
   with exactly the new link, switch active artifact, record prior artifact, complete. Reconciliation
   resumes known checkpoints; old active card link remains until verified replacement succeeds.
6. Add narrow `reroute-recording` API/CLI/skill flow. It supports only opaque destination IDs,
   expected versions, DM identity, and idempotency. Reject active transfer/review/cleanup, MinIO,
   legacy records, and non-durable/unsupported states.
7. Exclude pages with non-empty configured recording fields from ordinary candidate search. Add
   Backend-bounded Notion resolver and two-stage explicit reassignment: URL canonicalization and exact
   normalized name lookup are hints; candidates must belong to configured recruiter DB/schema.
   Persist source/target snapshots plus one-time proposal/capability; confirm re-reads both fields,
   writes target with exactly active link, verifies it, clears source only afterwards, then updates
   recording metadata. Drift/failure leaves source unchanged and actionable.
8. Update state/data/API docs, Mila skill, CLI and tests. Commit schema/runtime checkpoint, then
   docs/skill checkpoint. Run `/review synology-public-reroute`.

## Affected files

- `.env.example`, `.env.production.example`, `app/config.py`, `app/tools/synology.py`,
  `app/services/storage.py`, `app/services/transfer.py`, `app/services/destinations.py`
- New: `app/services/reroute.py`, `app/services/notion_reassignment.py`,
  `app/db/models/recording_storage_artifact.py`, `recording_reroute.py`,
  `notion_reassignment_proposal.py`, Alembic revision
- `app/routers/tools.py`, `app/scheduler/cron.py`, `app/tools/notion.py`
- OpenClaw skill, contract, CLI; Synology/tools/data-model/status docs; related Memory Bank files
- New focused reroute/reassignment tests plus existing config/Synology/transfer/router/skill tests

## Tests

- Public link payload: `date_expired=-1`, no password/expiry setting; production config accepted.
- Reroute: UUID-only API, label ambiguity, current root/symlink/permission/collision rejection,
  CopyMove move/re-upload success, operation recovery, idempotency, immutable artifact history, and
  no unapproved delete/rename/overwrite.
- Notion: occupied-card exclusion from ordinary matching; URL/name DB/schema validation, duplicate
  candidates, proposal TTL/DM/version/idempotency, no write before confirm, target-first exact-link
  write, source clear only after target verification, and drift recovery.
- Alembic upgrade/downgrade/check, focused pytest, full pytest, Ruff, mypy.
- Approved isolated Synology smoke only after production-write approval: public URL, reroute removes
  source only after verified target, newest artifact/card is active, old artifact remains in history.

## Blockers

1. **RESOLVED 2026-07-29 — CopyMove implementation proof:** isolated DSM v3 smoke under
   `/home/Recruiting-E/3. Interviews internal/Flutter` proved separate source file and owner-marker
   CopyMove tasks with `remove_src=true`, `overwrite=false`, task completion, target size/marker
   verification, physical source absence, public permanent link creation, and generated-test-tree cleanup.
2. **RESOLVED BY USER WAIVER 2026-07-29 — Public-link incident owner:** public permanent URLs
   deliberately have no dedicated human incident owner. `inerview_recordis_saver` is the technical
   File Station account. Documentation must retain the File Station link-revocation procedure and
   explicitly state this accepted operational risk.

## Out of scope

- Automatic old-file deletion other than verified CopyMove move mode, rename,
  overwrite, link revocation, or arbitrary old-card clearing.
- Arbitrary raw filesystem paths, arbitrary Notion workspace page mutation, Backend semantic mapping.
- Automatic scan-to-LLM orchestration; see `autonomous-synology-routing-plan.md`.

## Assumptions

- User approved public/no-password/no-expiry Synology links.
- User approved physical source deletion only through verified CopyMove move after target success.
- `tools/setup/synology_sid_inventory.py` remains temp-only and outside runtime scope.
