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

## ADR-010: OpenClaw is a running service — Backend sends events
**Decision:** OpenClaw runs continuously. Backend emits events to the already-running process, does NOT launch it per cron tick.
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

## ADR-009: Backend is the scheduler, OpenClaw is the reasoner
**Decision:** APScheduler lives in Backend Tools Service, not in OpenClaw. Backend scans Yandex Disk on schedule, does all integrations, manages PostgreSQL state. When a decision point is reached (new recording found, ambiguity detected, manual review reply received), Backend pushes an event to OpenClaw. OpenClaw wakes up, reasons about the event, sends messages to recruiter, and calls Backend tools back as needed.
**Why:** OpenClaw has no guaranteed cron capability. Backend already owns integrations and state. LLM reasoning (matching confidence, NLU, recruiter dialog) is the only part that belongs in OpenClaw. Clean separation: Backend = reliable executor, OpenClaw = intelligent reasoner.
**Consequence:** Backend exposes two surfaces: (a) tool endpoints that OpenClaw calls, (b) event push endpoint that Backend uses to wake OpenClaw (`POST /openclaw/agents/recording/invoke` or equivalent).
**Open question:** Exact OpenClaw event push API — confirm with developer (see Q10 in open-questions.md).
**Date:** 2026-07-13
