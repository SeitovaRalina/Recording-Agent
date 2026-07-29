# Decisions

## ADR-001: Notion — Scenario A (single workspace, multiple DBs)
**Decision:** All recruiters share one Notion workspace. Each recruiter has their own database within it.
**Consequence:** Single `NOTION_TOKEN` (Internal Integration). Per-recruiter `database_id` map in config.
**Alternative considered:** OAuth per recruiter (Scenario B) — rejected, unnecessary complexity.
**Date:** 2026-07-13

## ADR-002: Direct HTTP integration, no yx360-cli
**Decision:** Implement Яндекс integrations directly via `httpx`. CalDAV for Calendar, REST API for Disk.
**Why:** yx360-cli doesn't cover Яндекс.Диск. Direct implementation has no external CLI dependency, easier to test, fewer moving parts.
**Date:** 2026-07-13

## ADR-003: PostgreSQL as source of truth for recording pipeline state
**Decision:** PostgreSQL tracks all 13 statuses + metadata for every recording. Not Notion, not files on disk.
**Why:** Notion holds candidate data, not pipeline state. PostgreSQL provides transactional guarantees and queryable history.
**Date:** 2026-07-13

## ADR-004: Streaming file transfer Disk → Synology
**Decision:** Stream recording file chunk-by-chunk. No full copy on agent server.
**Why:** Recordings can be 500MB–2GB. Agent server is not a storage system.
**Fallback:** Temp file in `/tmp/recording-agent/` with immediate cleanup after Synology confirms upload. TTL guard: auto-delete temp files older than 4h.
**Date:** 2026-07-13

## ADR-005: Synology auth via API Key (DSM 7.0+)
**Decision:** Use API Key for stateless, TTL-free auth.
**Fallback:** Session SID login if DSM version < 7.0 (check at setup time, document result in open-questions.md).
**Date:** 2026-07-13

## ADR-006: Mattermost for human-in-the-loop
**Decision:** All recruiter interaction (commands, disambiguation, confirmations) goes through Mattermost.
**Why:** Recruiters already use Mattermost. No new tool. Free-text replies parsed by OpenClaw NLU.
**Date:** 2026-07-13

## ADR-007: Interview detection via multi-signal scoring
**Decision:** Don't rely on a single field to identify interview recordings. Time overlap and the `calink.ru` booking marker are high signals for the current effective.band flow; candidate name is medium/high; Telemost confirms only a video call and is a low diagnostic signal. Low confidence → `manual_review_required`, not auto-ignore.
**Why:** False negatives (missed interviews) worse than false positives (asking recruiter to confirm).
**Date:** 2026-07-13

## ADR-009: Backend-first — OpenClaw only for ambiguous cases
**Decision:** Backend runs full deterministic pipeline autonomously. OpenClaw invoked only when confidence low, multiple Notion cards match, or recruiter input needed.
**Date:** 2026-07-13

## ADR-010: OpenClaw is a running service — Backend exposes narrow intents
**Decision:** OpenClaw runs continuously. Backend does not launch it per cron tick. Phase 4 uses a
workspace-skill CLI to call authenticated loopback Backend intents; speculative generic event-push
and tool-registration endpoints are not part of the Mila MVP.
**Date:** 2026-07-13

## ADR-011: MVP tool list (10 tools)
1. `list_new_recordings`, 2. `get_recording_details`, 3. `get_calendar_events`, 4. `find_notion_candidates`, 5. `transfer_recording`, 6. `update_notion_card`, 7. `mark_processed`, 8. `get_pending_reviews`, 9. `resolve_manual_review`, 10. `reject_recording`
`resolve_manual_review` replaces `reject_match` — universal for all recruiter responses.
**Date:** 2026-07-13

## ADR-012: MinIO as test storage provider
**Decision:** Use MinIO (S3-compatible) instead of Synology during development and testing.
**Why:** No Synology access during development. MinIO provides identical S3 API surface.
**Production path:** Replace MinIO config with Synology File Station API once access available.
**Config:** `STORAGE_PROVIDER=minio|synology` toggle in `.env`.
**Date:** 2026-07-13

## ADR-013: Per-recruiter Yandex OAuth tokens
**Decision:** One `refresh_token` per recruiter (Anton, Lili, etc.), stored in Lockbox keyed by recruiter email.
**Why:** All recruiters in one Yandex 360 org (@effective.band) but each has own Disk — no shared org-admin Disk access at MVP.
**Config:** `RECRUITER_YANDEX_TOKENS = {"anton@effective.band": "...", "lili@effective.band": "..."}`
**Future:** Yandex 360 Directory API may allow org-admin access to all Disks — investigate post-MVP.
**Date:** 2026-07-13

## ADR-008: Test environment mandatory before production
**Decision:** Full test environment (test Disk folder, test Calendar, test Notion DB copy, test Synology folder, test Mattermost channel) required before any production access.
**Date:** 2026-07-13

## ADR-014: Explicit calendar selection and exact filename correlation
**Decision:** Each recruiter has one explicit default calendar and optional selected calendars. A non-empty selection is the effective eligible set; otherwise the default alone is eligible. Scans query every discovered available calendar for collision evidence, but unselected calendars can never supply a confirmed match. Automatic matching requires an exact conservatively normalized Telemost filename title/SUMMARY match, compatible filename start time, one eligible occurrence, no outside collision, and the confidence threshold.
**Why:** All recordings share one immutable Telemost Disk folder, so calendar choice cannot filter discovery. Exact title/time compatibility and full-set collision evidence prevent nearby unrelated events from being auto-matched.
**Safety:** Discovery accepts only same-origin canonical HTTPS collections returned by CalDAV. Missing defaults, stale discovery, incomplete collection queries, malformed filenames, ambiguity, and collisions fail closed to a resumable or structured manual-review path. Only a recruiter can choose `ignored`.
**Date:** 2026-07-15

## ADR-009B: Backend is the scheduler, OpenClaw is the interaction layer
**Decision:** APScheduler lives in Backend Tools Service, not in OpenClaw. Backend scans Yandex
Disk on schedule, performs deterministic matching, owns integrations, and manages PostgreSQL
state. Mila provides natural-language entry and manual-review presentation through narrow Backend
intents. Deterministic matches do not require an LLM call.
**Why:** Backend already provides reliable state and side-effect ordering. OpenClaw is useful for
free-form recruiter interaction, not as another scheduler or state owner.
**Consequence:** Backend exposes only bounded scan, status, review-context, resolve, and ignore
intents. Raw transfer, Notion update, source mutation, delete, and purge operations remain private.
**Date:** 2026-07-13

## ADR-015: Mila-first script-backed OpenClaw integration
**Decision:** Phase 4 integrates the existing Mila `main` agent through a repository-owned
workspace skill whose deterministic CLI calls narrow authenticated Backend intents over loopback.
Backend remains the sole scheduler, PostgreSQL state owner, matcher, transfer executor, Notion
client, storage client, and notification state owner. Normal deterministic processing does not
invoke an LLM. Mila handles free-form request routing and manual-review presentation only.
**Canary:** Use isolated PostgreSQL, MinIO, `Test Interviews`, and one allowlisted Mattermost DM
identity. Keep scheduler disabled until the manual canary passes. Hard-disable Yandex source
mutation, cleanup, purge, Synology, and production resources.
**Compatibility:** Use OpenClaw `2026.4.22` workspace-skill conventions. Do not upgrade OpenClaw,
change Gateway bind, or add a native plugin/MCP server without evidence that the script-backed
contract is insufficient. Sylvanas is unchanged and can reuse the same skill later.
**Date:** 2026-07-21

## ADR-016: One ordinary Mila DM with a Backend-owned question queue
**Decision:** Recording Agent uses the recruiter's existing direct conversation with Mila and does
not require Mattermost threads. A scheduled run produces one summary followed by numbered,
actionable questions for every unresolved recording. The recruiter may answer all questions or a
subset in free form. Mila confirms how it understood each answer, reports processing start, and
later reports completion or an actionable error.
**Reliability:** PostgreSQL owns pending-question state, partial-answer progress, versions,
idempotency, reminders, and notification deduplication. Replies are bound to recruiter, DM
channel, recording/review ID, version, one-time capability, and TTL. If several mappings are
possible, Mila asks a clarifying question rather than guessing. Unrelated Mila conversations do
not consume Recording Agent questions.
**Why:** Mila already serves multiple purposes. One ordinary DM is simpler for recruiters than
opening a separate thread for every recording, while durable Backend state prevents conversational
memory from becoming the workflow source of truth.
**Status:** Target decision; current Phase 4 review contract still requires a thread and must be
reconciled before Mila deployment.
**Reminder cadence:** Send the consolidated summary at 18:00 in the recruiter's configured local
timezone. An unanswered question is repeated once in the next eligible summary, then remains
durable but is suppressed from later automatic summaries unless explicitly reopened. Accepted
answers receive immediate processing-start and completion/error feedback.
**Date:** 2026-07-22

## ADR-017: Notion interview date and recording link are pipeline outputs
**Decision:** Candidate-card lookup must not require a prefilled `General Interview Date`. Use the
candidate name as the primary lookup key. Email may be an additional signal only after its Notion
formula value is parsed safely. Contacts come from the `TBD` formula
`prop("Candidate").map(current.prop("Contacts"))`; extract and normalize only valid email
addresses from the mixed phone/email/Telegram output. Calendar attendee email is supporting
evidence, never a mandatory rejection condition. Multiple matches require recruiter selection.
After a confirmed match, write the matched calendar event date to
`General Interview Date` and the final storage URL to `General Interview recording`.
**Why:** Recruiters do not fill these fields before processing. Requiring the date prevents the
agent from finding the intended card.
**Ambiguity presentation:** Interview card titles are not unique. Each numbered option must retain
the Notion page URL and bounded distinguishing fields. Always show `📍 Spots` when available because
the same candidate can have separate Interview cards for different projects; additional safe
Candidate or project evidence may be shown when Backend returns it. Equal titles must never be
collapsed into indistinguishable links.
**Date:** 2026-07-22

## ADR-018: No scheduled Yandex cleanup; keep a manual safe cleanup action
**Decision:** Do not schedule Yandex source deletion. Keep a manual recruiter command that previews
and, after explicit confirmation, moves only Backend-proven successfully processed source files to
Trash. Never expose permanent purge to Mila. The action is idempotent and excludes pending,
failed, unresolved, and unverified files.
**Why:** The Telemost folder is reported to expire automatically after 90 days and not consume the
normal storage quota. Automatic cleanup adds risk without a clear capacity benefit, while a narrow
manual function preserves operator control.
**Eligibility age:** None. A file may appear in the preview immediately after Backend proves the
recording completed successfully. Explicit preview confirmation remains mandatory.
**Status:** Target decision; current automatic seven-day cleanup code must remain disabled and be
reconciled.
**Date:** 2026-07-22

## ADR-019: Recruiter-requested Synology folders stay under a configured root
**Decision:** For a non-interview recording, the recruiter may select an existing Synology folder
or ask Mila to create a new folder. Backend canonicalizes and creates the destination only under
the recruiter's configured storage root and only after permission validation. OpenClaw never gets
a raw storage mutation primitive and free-form text never becomes an unchecked filesystem path.
**Consequence:** A successful non-interview route returns the storage link and completes without a
candidate Notion update. An invalid, escaping, inaccessible, or ambiguous destination fails closed
and remains actionable.
**Date:** 2026-07-22

## ADR-020: The Mila completion plan supersedes unfinished Phase 4 design
**Decision:** `swarm-report/recording-agent-mila-completion-plan.md` is authoritative for all
unfinished implementation and rollout work. Earlier Phase 4 documents retain historical facts but
do not override its ordinary-DM queue, one-reminder suppression, explicit multi-Spot selection,
fixed 18:00 recruiter-local schedule, manual-only Yandex cleanup, or approval gates.
**Manual trigger:** A recruiter can always ask Mila to scan for new recordings. The narrow manual
scan remains supported while the Backend scheduler is disabled and uses the same durable Backend
state and idempotency boundaries.
**Deployment:** Mila currently lacks Docker/Compose. Runtime installation, test-stack deployment,
skill installation, agent invocation, real Mattermost DM, scheduled proof, and production effects
follow the separate approval checkpoints in the plan.
**Date:** 2026-07-22

## ADR-021: Autonomous Synology routing is a leased Gateway worker, not Backend orchestration
**Decision:** Backend remains the sole owner of scans, matching, routing jobs, PostgreSQL state,
destination validation, transfers, Notion writes, and recruiter notifications. After a successful
daily or manual scan it persists a routing job; it never starts OpenClaw, calls an LLM, or waits for
one. A root-owned Gateway command-cron dispatcher polls only for ready jobs, obtains one short
lease, and starts an isolated `recordings-saver` worker turn only when a job exists.
**Worker boundary:** The isolated worker receives only a routing-job UUID and one-time dispatch
nonce. Backend returns a bounded immutable snapshot and opaque destination UUIDs. The worker may
resolve one snapshot UUID or defer. It never receives a raw Synology path, recruiter identity,
Notion/Yandex URL, persistent Backend secret, or integration credential. Backend independently
checks lease, nonce, worker identity, snapshot/version, ownership, live destination state, and
transfer collision before side effects.
**Prompt-injection boundary:** Job context, recording metadata, Notion-derived labels, and folder
labels are untrusted data, delimited from the versioned worker instruction. They cannot request
tools, change policy, or override the strict UUID-or-defer response schema. There is no recruiter
user prompt in the autonomous turn. A defer/failure is sent only by Backend NotificationOutbox.
**Rollout:** `AUTONOMOUS_ROUTING_ENABLED` is off by default. Enable only after a no-job dispatcher
smoke test, then one isolated canary recruiter/root with external effects independently approved.
Rollback disables the flag and cron job; active leases expire safely and no job is auto-uploaded.
**Operations:** Platform owner owns the root dispatcher, systemd timer, Gateway environment and
logs; Backend owner owns job APIs, migrations, flag, reconciliation and notification policy.
**Why:** This preserves Backend side-effect ownership while providing reliable, restart-safe,
low-frequency worker delivery without a generic event-push assumption or polling LLM calls.
**Date:** 2026-07-29
# ADR-022: Public permanent Synology links and reroute safety

- Synology links are intentionally public, passwordless, and permanent: File Station Sharing
  `create` version 3 sends `date_expired=-1` and `date_available=0` only.
- The public-link risk is accepted without a dedicated human incident owner. The technical File
  Station account is `inerview_recordis_saver`. To revoke a leaked URL, an operator opens File
  Station -> Tools -> Shared Links, finds the link/path and removes the share; this does not
  delete the stored recording.
- Reroute accepts a persisted opaque destination UUID only. File Station CopyMove uses
  `remove_src=true` and `overwrite=false`, separately moves the data and owner-marker files,
  polls the task, then verifies target size/owner and physical source absence.
- Ordinary candidate lookup filters `General Interview recording` to empty. Explicit Notion
  reassignment writes and verifies the target link before clearing the source field.
