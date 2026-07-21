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
