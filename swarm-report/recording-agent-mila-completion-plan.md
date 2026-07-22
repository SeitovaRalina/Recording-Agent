# Plan: Complete Recording Agent and roll out the Mila canary

Slug: `recording-agent-mila-completion`

## TL;DR

Finish the product locally before touching Mila: replace thread-bound reviews with a durable
Backend-owned DM question queue, implement partial answers and deduplicated feedback, correct
Notion matching, add safe Synology/non-interview/manual-cleanup contracts, and make the 18:00
recruiter-local schedule fail-safe and initially disabled.

After two successful code reviews, repeat Mila read-only inventory, present an exact remote
mutation and rollback manifest, and wait for approval. Deploy an isolated test Backend,
PostgreSQL, and MinIO stack; install the repository-owned skill into Mila's production workspace
while keeping it pointed at the test Backend. Agent invocation, real allowlisted Mattermost DM,
the scheduled test, and production-scope integrations each require separate approvals.

The old `phase-4-openclaw-integration-plan.md` remains historical input. This plan is the
implementation authority for unfinished work.

## Current baseline and confirmed Mila facts

- Branch: `feature/openclaw-integration`; baseline commits: `3fd394e`, `14b4992`, `3320257`.
- Reported last full gate: `204 passed, 1 warning`; rerun before completion claims.
- Existing implementation has a thread-bound `ManualReview`, date-filtered Notion lookup,
  deterministic skill CLI, MinIO collision protection, bootstrap/reset tooling, and disabled
  local canary scheduler.
- Read-only Mila inventory on 2026-07-22 confirmed OpenClaw `2026.4.22`, active loopback Gateway
  `127.0.0.1:18789`, workspace `/root/.openclaw/workspace`, 19 GiB disk free, and approximately
  2.8 GiB available RAM.
- Docker, Docker Compose, Podman, and Nerdctl are absent on Mila. Any Compose deployment therefore
  requires an explicitly approved Docker/Compose package installation. Do not infer approval.
- `systemd-creds` exists. Final secret-injection design must be chosen from a fresh inventory and
  must not expose values or require a Gateway restart unless the exact restart is approved.
- Bundled Mila `skill-creator` is ready. Treat the repository skill as existing: audit/update,
  validate/package-check, and forward-test it; do not reinitialize it.

## Acceptance criteria

### Safety and ownership

1. Backend remains the only scheduler, PostgreSQL workflow-state owner, matcher, transfer
   executor, Notion/Yandex/Synology client, and side-effect coordinator. Normal deterministic
   processing does not invoke an LLM.
2. Scheduler, Yandex mutations, Notion writes, Mattermost delivery, Synology, cleanup, and
   production scope are opt-in and fail closed. Canary defaults keep them disabled unless a
   specific test step requires an approved enablement.
3. No raw transfer, Notion update, storage path, Yandex delete, or purge primitive is exposed to
   Mila. No shared Mattermost channel fallback exists.
4. Branch stays `feature/openclaw-integration`; commits are logical Conventional Commits; no push.

### Ordinary Mila DM and durable questions

5. PostgreSQL durably owns each question's recruiter, exact DM channel, recording/review ID,
   recording version, question-set identity, one-time capability hash, TTL, idempotency result,
   delivery claim, reminder state, answer, and terminal result.
6. Question lifecycle supports `pending`, `answered`, `processing`, `completed`, `failed`, and
   `suppressed`. Restart and concurrent workers recover only safely claimed work.
7. One daily DM summary contains bounded numbered questions for all currently presentable
   unresolved recordings. Threads are not required.
8. A free-form answer may address all or a subset. Mila first states its bounded interpretation.
   Backend receives exact question/action tuples, validates each independently, commits only
   unambiguous valid items, returns accepted/rejected/pending sets, and leaves omitted or
   ambiguous questions untouched.
9. Trusted recruiter and DM metadata comes from verified Mattermost/OpenClaw context or Backend
   lookup, never from free-form model text. Wrong recruiter, wrong/non-DM channel, expired token,
   stale version, conflicting replay, and reused capability fail closed.
10. Unrelated Mila messages, bare numbers without an active Recording Agent question-set
    reference, quoted/edited old messages, acknowledgements, and ambiguous delayed replies do not
    consume questions.
11. An unanswered question is repeated once in the next eligible 18:00 summary, then remains
    durable but is suppressed from later automatic summaries unless explicitly reopened.
    Closed/suppressed questions never repeat.
12. Accepted work generates one deduplicated `processing started` DM. Completion generates one
    completion DM. Failure generates one sanitized actionable error DM. A durable outbox with
    deterministic keys and stale-claim recovery prevents loss or duplication across restart.

### Notion and storage identity

13. Candidate lookup uses name without a `General Interview Date` filter. Email is optional
    supporting evidence; absence or mismatch never rejects an otherwise valid name match.
14. Backend-runtime preflight validates `Name:title`, `General Interview Date:date`,
    `General Interview recording:files`, `TBD:formula`, and `📍 Spots:relation` in test database
    `fe5fe300f311821b96fe01233947e4c2`. The data-source ID is discovered at runtime and never
    configured or persisted.
15. Runtime probing establishes the actual `TBD` formula payload. Only syntactically valid,
    case-normalized emails are extracted from mixed phone/email/Telegram text. Unknown formula
    shapes fail closed.
16. Duplicate Notion titles remain distinct choices. Every choice contains its Notion URL,
    `📍 Spots`, and additional bounded safe Candidate/project differentiators returned by Backend.
17. Zero `📍 Spots` uses `unspecified`; one relation resolves the related page title; multiple
    relations create a structured recruiter choice containing every bounded Spot title/URL.
    API order never selects a value. The selected Spot is persisted and collision-checked before
    transfer.
18. After storage succeeds, one idempotent Notion update writes the matched calendar event date
    to `General Interview Date` and the final storage link to `General Interview recording`.
19. Filename is
    `YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>` and key is
    `<recruiter>/<YYYY-MM-DD>/<candidate>/<generated_filename>` after deterministic sanitization.
20. Same recording retry reuses the same object. A different recording resolving to the same key
    enters manual review. No overwrite or silent suffix occurs.

### Synology, non-interview route, and cleanup

21. Synology preflight safely validates endpoint, DSM/File Station API access, configured
    recruiter root, permissions, and share-link capability without logging credentials.
22. Folder discovery is bounded by configured root, depth, page count, and result count. Mila
    selects opaque Backend destination IDs; it never submits executable raw paths.
23. Folder creation canonicalizes the destination, rejects traversal/root escape and symlink
    ambiguity, verifies permission, and creates only under the configured recruiter root.
24. A confirmed non-interview route transfers to an allowed destination, returns a link, and
    completes without a Notion update. It is distinct from `ignored`.
25. Manual cleanup is preview then explicit confirmation. Preview is bound to recruiter, DM,
    immutable bounded file IDs/versions, hash, one-time capability, and expiry.
26. Confirmation revalidates Backend-proven completion and durable final-storage link before each
    move, sends eligible sources only to Yandex Trash, and records idempotent per-file results.
    No minimum age, scheduled cleanup, or Mila-accessible permanent purge exists.
27. Initial Mila canary performs no production Synology or Yandex mutations. MinIO presigned URLs
    are test-only and do not prove durable production archival for cleanup eligibility.

### Scheduler, skill, deployment, and evidence

28. Backend schedules scan/summary at 18:00 in each recruiter's configured timezone with DST,
    misfire, restart, local-date deduplication, and concurrent-instance protection. Scheduler is
    disabled through the manual canary. OpenClaw heartbeat owns no schedule.
29. No scheduled Yandex cleanup job is registered. Temp-file TTL cleanup remains independent.
30. Repository source of truth remains `openclaw/skills/recording-agent/` with `SKILL.md`,
    `scripts/recording_agent.py`, and `references/contract.md`; no secrets are present.
31. Mila target is `/root/.openclaw/workspace/skills/recording-agent/`; installed skill calls only
    a loopback test Backend until a separate production promotion.
32. Before remote changes, read-only inventory is repeated and the user receives exact remote
    paths, packages, files, services/containers, ports, commands, reload/restart operations,
    health checks, and rollback commands. No mutation occurs before approval of that manifest.
33. Mila test deployment uses isolated PostgreSQL and MinIO named volumes, test bucket/prefix,
    loopback-only bindings, protected service environment, Alembic upgrade, and inactive
    recruiter bootstrap. No production data migration occurs.
34. Skill passes local audit/validation, Mila bundled `skill-creator` audit and package/validation
    checks, and realistic forward tests. No Mila agent invocation occurs before separate approval.
35. Manual Mila canary proves all user-listed scan/status/unique/duplicate/partial-answer/
    feedback/exactly-once/rejection/restart/collision/boundary/regression cases.
36. Rollback rehearsal preserves named volumes, stops only test services, restores/removes only
    Recording Agent deployment, and verifies Gateway, existing Mila skills, and Mattermost still
    work. `docker compose down -v` is never run.
37. After manual canary and separate approval, one actual Backend-owned scheduled test executes at
    18:00 recruiter-local time. Manual trigger or clock falsification is not evidence. The test
    schedule is disabled again unless continued operation is separately approved.
38. Required focused tests, PostgreSQL+MinIO integration, restart/recovery, Compose validation,
    Ruff, formatting, mypy, and full pytest pass with exact output recorded.
39. First review checks implementation against this plan. HIGH/MED findings are fixed and
    committed; full gates rerun; mandatory second review returns `ship` before remote deployment.
    Post-canary evidence receives a final review.

## Plan

### Checkpoint 0: baseline and documentation

1. Verify branch, clean worktree, expected commits, Python/dependencies, current Alembic heads,
   and existing local test state. Stop on unrelated changes.
2. Update Memory Bank and contracts in English where required: make this plan authoritative,
   close Q15 with explicit multi-Spot selection, record one-reminder semantics, fixed 18:00 local
   schedule, operational blockers, and disabled scheduled cleanup.
3. Update overview/runbook to remove obsolete thread/date-filter/automatic-cleanup instructions.
4. Run documentation consistency checks and create a `docs(...)` Conventional Commit.

Affected files:

- `.memory-bank/{architecture,auth-flow,decisions,open-questions}.md`
- `docs/{data-model,status-machine}.md`
- `swarm-report/recording-agent-overview.ru.md`
- `swarm-report/phase-4-codex-agent-test-runbook.ru.md`

### Checkpoint 1: durable question queue, trusted DM boundary, and outbox

1. Generate an Alembic migration. Evolve existing reviews without creating competing workflow
   state. Add question lifecycle, digest/delivery dedupe, capability hashes, claims/leases,
   reminder count, results, recruiter timezone, route metadata, and cleanup preview state.
2. Define explicit migration mapping for existing `pending/resolved/expired` reviews. Test upgrade,
   downgrade, current/head, and `alembic check` on isolated data only.
3. Implement question issue/list/partial-answer services with row locking or CAS, stable request
   fingerprints, independent per-item validation, mixed-success response, and replay persistence.
4. Replace thread binding with verified recruiter + exact direct-channel binding. Verify channel
   type and membership are exactly bot plus allowlisted recruiter.
5. Add durable outbox delivery for summary, processing-start, completion, and error messages with
   deterministic keys, claims, retry policy, and restart recovery.
6. Add digest generation: one bounded summary, numbered active questions, one next-summary
   reminder, then automatic suppression.
7. Extend bounded loopback API for question sets and partial actions. Backend accepts only exact
   IDs/choices; free text remains Mila interpretation input, never direct side-effect input.
8. Run migration/model/service/router/Mattermost/concurrency/restart tests. Commit.

Primary affected files:

- `app/db/models/{manual_review,recruiter_config,recording}.py`
- new focused models for digest/outbox/cleanup state, exported by `app/db/models/__init__.py`
- generated `alembic/versions/*_add_question_queue_and_safe_routes.py`
- `app/services/reviews.py`, new focused digest/outbox service(s)
- `app/tools/mattermost.py`, `app/routers/tools.py`, `app/main.py`
- focused review/digest/router/Mattermost tests

### Checkpoint 2: Notion matching and multi-Spot resolution

1. Remove date from candidate query. Query by name; preserve bounded duplicate rows.
2. Extend runtime schema preflight for `TBD:formula` and `📍 Spots:relation`.
3. Probe supported formula shapes and implement strict valid-email extraction. Treat attendee email
   only as supporting evidence.
4. Resolve zero/one Spot deterministically; emit a structured multi-Spot question with title/URL
   choices; persist selection before filename/key creation.
5. Keep equal candidate titles distinct and include URL, Spots, and bounded safe differentiators.
6. Replace link-only update with one idempotent date-plus-file PATCH after storage success. Define
   safe retry/recovery for stale schemas/pages.
7. Recheck collision after any candidate or Spot choice. Run schema/email/candidate/filename/
   collision/update tests. Commit.

Primary affected files:

- `app/config.py`, `app/tools/notion.py`, `app/services/candidate.py`
- pipeline/transfer orchestration where the persisted choice resumes
- `tests/test_{notion,candidate,phase4_filename,storage,transfer}.py`

### Checkpoint 3: safe Synology destinations, non-interview route, and manual cleanup

1. Extend Synology client with sanitized preflight, bounded/paginated folder discovery,
   permission checks, canonical create-under-root, share links, and collision refusal.
2. Introduce opaque destination records/IDs. Never execute Mila-provided raw paths.
3. Extend ordered pipeline for interview and non-interview routes. Non-interview skips Notion but
   persists successful storage completion and link; `ignored` performs no transfer.
4. Implement cleanup preview with immutable snapshot binding and one-time confirmation. Revalidate
   status/link/version, then invoke only a narrow Trash move and persist per-file results.
5. Remove scheduled Yandex cleanup registration and age-based automatic behavior. Keep permanent
   purge unreachable. Keep Yandex mutation disabled in canary.
6. Run mocked Synology/Yandex, path traversal, pagination, permissions, collision, cleanup drift,
   state-machine, and restart tests. Commit.

Primary affected files:

- `app/tools/{synology,disk}.py`
- `app/services/{storage,transfer}.py`
- new focused destination and cleanup services
- `app/routers/tools.py`, `app/scheduler/cron.py`, model/migration fields as planned above
- focused Synology/cleanup/transfer/scheduler tests

### Checkpoint 4: recruiter-local scheduler, operator tooling, and repository skill

1. Implement 18:00 recruiter-local scheduling with one durable local-date delivery key, DST,
   misfire, restart, and multi-instance tests. Keep default disabled and preserve manual scan/status.
2. Update bootstrap/preflight/activation for timezone, DM validation, Notion formula/relation
   schema, and optional Synology root. Update safe test reset for new workflow tables.
3. Update Compose/env templates with fail-safe defaults and loopback binds. Add a dependency only
   if standards-compliant email validation cannot be implemented with current packages.
4. Audit/update existing skill per `skill-creator`: concise trigger metadata, deterministic CLI,
   one-level contract reference, bounded redacted output, partial-answer/destination/cleanup
   commands, unrelated-message rules, no secrets.
5. Run scheduler/manual/status/bootstrap/reset/skill CLI tests. Commit.

Primary affected files:

- `app/config.py`, `app/scheduler/cron.py`, `app/main.py`
- `tools/setup/{configure_recruiter,reset_recording_state}.py`
- `docker-compose.yml`, `.env.example`, optionally `pyproject.toml` and `poetry.lock`
- `openclaw/skills/recording-agent/{SKILL.md,scripts/recording_agent.py,references/contract.md}`
- focused operator/scheduler/skill tests

### Checkpoint 5: local integration, gates, and two reviews

1. Before external PostgreSQL+MinIO+Notion/Mattermost/Yandex tests, warn the user separately and
   name systems, exact test scopes, expected writes/messages, and cleanup/rollback.
2. After approval, run isolated PostgreSQL+MinIO integration, Alembic upgrade/current/check,
   restart/recovery, object persistence/collision, and two-worker claim tests.
3. Run Backend-runtime read-only Notion schema/formula probe. Perform test Notion writes or
   allowlisted Mattermost/Yandex actions only after their own required approval.
4. Validate skill locally using skill-creator validation/package workflow and realistic isolated
   forward tests with no leaked expected answers.
5. Run:

   ```text
   docker compose --env-file .env.example config --quiet
   poetry run ruff check app tools tests alembic
   poetry run ruff format --check app tools tests alembic
   poetry run mypy app tools tests
   poetry run pytest
   ```

6. Record exact output and write build report. Commit final local checkpoint.
7. Run `/review recording-agent-mila-completion`. Fix HIGH/MED through `/debug`, focused tests,
   full gates, and commit. Run mandatory second `/review`; require `ship`.

### Checkpoint 6: fresh Mila inventory and exact mutation approval

1. Repeat read-only inventory: disk/RAM/ports; container runtimes; systemd; OpenClaw version/status;
   workspace skill conventions; bundled skill-creator; targeted supported secret injection.
   Never dump config, `.env`, process environment, or credential values.
2. Because Docker/Compose is currently absent, run a read-only package-install simulation and pin
   exact Ubuntu package versions/dependencies. Decide between Docker Compose and a separately
   reviewed native-systemd alternative; Docker Compose is preferred by current deployment design.
3. Present exact manifest and wait for approval. It must include:

   - Docker/Compose packages and service enable/start commands, if chosen;
   - repository/staging/config/secret/skill/backup paths with owners/modes;
   - Compose project, container, network, named-volume, bucket, and loopback port names;
   - image versions/digests;
   - copy/build/config/migrate/bootstrap/start commands;
   - any `systemctl daemon-reload`, service restart, or Gateway restart;
   - health/preflight commands;
   - exact stop/disable/package-removal/skill-restore rollback commands;
   - explicit preservation of named volumes and ban on `docker compose down -v`.

No remote mutation occurs before approval for this exact manifest.

### Checkpoint 7: approved test deployment and skill validation

1. Install only approved runtime packages. Deploy isolated `recording-agent-test` PostgreSQL,
   MinIO, and Backend with named volumes and loopback-only ports.
2. Inject secrets through the approved protected service mechanism without printing values or
   placing them in repository, skill, workspace docs, command arguments, or logs.
3. Install the repository skill atomically at
   `/root/.openclaw/workspace/skills/recording-agent/`, with checksum/backup evidence; point it to
   loopback test Backend.
4. Run Alembic, inactive recruiter bootstrap, Backend-runtime read-only Notion schema/formula
   probe against `fe5...`, and approved safe preflights. Production database `ef16...` must be
   absent from canary config and traffic.
5. Run Mila bundled skill-creator audit and package/validation check plus direct CLI/Backend health
   without invoking Mila agent.
6. Present forward-test prompts/effects and request separate Mila agent-invocation approval. A
   real allowlisted Mattermost test DM requires another explicit approval.

### Checkpoint 8: manual Mila canary and rollback rehearsal

After approvals, prove:

1. Manual free-form scan.
2. Status by date, candidate, recording ID, and status.
3. Unique Notion card.
4. Duplicate cards with distinct URLs and `📍 Spots`.
5. Partial free-form answer and interpretation confirmation.
6. Unanswered question remains pending; unrelated messages do not consume it.
7. Start/completion/actionable-error feedback exactly once.
8. Resolve exactly once.
9. Expiry, wrong user, wrong DM, stale version, and replay rejection.
10. Restart/outbox/claim recovery.
11. MinIO reuse/collision policy.
12. No production Notion/Yandex/Synology access.
13. No shared Mattermost fallback.
14. Existing Mila purposes/skills/Gateway remain healthy.

Then rehearse rollback: stop only test services without deleting volumes, restore/remove only the
Recording Agent skill/environment changes declared in the manifest, verify Mila health, restore
the canary, and prove recovery without duplicate effects.

### Checkpoint 9: separately approved scheduled proof and final review

1. Report manual canary with `Completed/Evidence/Tests/Commit/Next/Blockers`.
2. Present exact scheduler enable/disable commands and next recruiter-local 18:00 execution time;
   request separate approval.
3. Enable only test Backend schedule. Observe actual planned fire time and actual execution. Prove
   one summary/reminder, durable local-date dedupe, no duplicate effects, and retained state.
4. Disable test schedule again unless continued operation has separate approval.
5. Run final review over code, deployment evidence, rollback proof, and scheduled proof.
   Production promotion remains a separate future checkpoint.

## Required tests

- Filename/schema/relation/collision/token/version/idempotency unit tests.
- Question queue lifecycle, partial/mixed replies, simultaneous answers, stale capabilities,
  reminder-once, suppression, outbox claims, DM outage, and restart recovery.
- Notion name-only query, formula variants, valid-email extraction, phone/Telegram rejection,
  optional/mismatched attendee email, duplicate cards, multi-Spot choice, and date+file update.
- MinIO retry/collision and Synology preflight/discovery/root-containment/permission/create/share.
- Interview, non-interview, ignored, failed/retry/suppress, and restart route tests.
- Cleanup eligibility, immutable preview, drift/version/TTL/replay, Trash-only result, and absence
  of purge/scheduled cleanup.
- Scheduler-disabled default, recruiter-local 18:00/DST/misfire/multi-instance dedupe, manual scan,
  and all status filters.
- Operator bootstrap/reset and skill CLI/refusal/redaction tests.
- Mocked Notion, Mattermost, Yandex, and Synology tests.
- Approved PostgreSQL+MinIO integration, Alembic, restart/recovery, Compose, Ruff, format, mypy,
  full pytest, Mila skill validation/forward tests, canary, rollback, and scheduled proof.

## Blockers

These do not block local implementation unless stated:

1. Mila lacks Docker/Compose. Exact package installation, daemon start/enable, and rollback require
   a remote-mutation manifest and explicit approval before deployment.
2. Production Synology endpoint, API key, share/base path, network reachability, and permissions
   are missing. This blocks live Synology/non-interview production proof, not mocked implementation
   or MinIO canary.
3. Production Mattermost values are unavailable to the repository process. Safe Mila-side
   transfer and first real allowlisted DM need separate approval.
4. Backend runtime Notion token must repeat read-only schema/formula probe, and a synthetic test
   row must be selected before the first test write.
5. Lili Notion sharing/schema is unknown; Lili production activation remains blocked.
6. Mila agent invocation, real test DM, scheduler enablement, and all production Notion/Yandex/
   Synology mutations require separate explicit approvals.
7. The known plaintext OAuth token in Mila workspace remains a production security blocker.
   Rotation/removal is a separate credential-remediation operation; never print or recursively
   search its value.

No HIGH design blocker remains for local build: multiple `📍 Spots` and one-reminder semantics are
resolved by the latest user requirements.

## Out of scope

- Push, PR, merge, or branch rewrite.
- OpenClaw upgrade, native plugin, MCP server, Gateway public exposure, or heartbeat scheduling.
- Sylvanas changes.
- Production data migration or production resource mutation during test rollout.
- Permanent Yandex Trash purge or scheduled source cleanup.
- Raw folder/path execution from Mila text.
- Self-service OAuth/recruiter onboarding.
- Lili production enablement before schema/sharing proof.
- Continued production schedule after the single approved scheduled test.
- Production PostgreSQL/Synology retention policy.

## Assumptions

- Latest user requirements supersede the old Phase 4 plan and Q15 wording.
- Existing thread-bound rows can be migrated with explicit compatibility mapping rather than
  creating a second parallel review subsystem.
- Test database `fe5...` remains shared with Backend token; verify, never infer.
- Production database `ef16...` remains disabled throughout canary.
- Mila's existing Mattermost configuration is usable, but values are transferred only by an
  approved operator-safe method.
- Actual 18:00 proof may require waiting until the next configured local execution; system clock
  is not altered to manufacture evidence.
