---
type: reference
status: target
last_updated: 2026-07-22
sources:
  - .memory-bank/architecture.md
  - .memory-bank/decisions.md
  - swarm-report/recording-agent-mila-completion-plan.md
---

# Status Machine — Recording Processing

The approved completion plan is authoritative for unfinished behavior. PostgreSQL owns every
workflow transition; Mila presents bounded intents and never becomes workflow memory.

## Recording lifecycle

```text
found
  -> calendar_event_found
  -> candidate_matched
  -> transfer_started
  -> uploaded_to_synology
  -> synology_link_created
  -> notion_updated
  -> source_marked_processed
  -> completed

Any ambiguous matching/storage decision -> manual_review_required
Explicit no-transfer decision           -> ignored
Exhausted or permanent safe failure      -> failed
Confirmed non-interview route            -> transfer_started -> ... -> completed
```

`source_deleted` may remain as historical compatibility state for migrated rows, but it is not a
scheduled target transition. There is no automatic source cleanup or permanent-purge transition.

### `found`

The source is durably discovered and deduplicated by `disk_file_id`. Calendar correlation uses
the timestamp parsed from a supported Telemost filename and the complete eligible calendar
snapshot. An incomplete snapshot remains resumable in `found`.

Manual message-triggered scans may enter this state at any time, including while the scheduler is
disabled. The same idempotency rules apply to manual and scheduled scans.

### `calendar_event_found`

Exactly one compatible occurrence exists in the effective selected calendar set, no compatible
outside collision exists, and the confidence threshold is met. Calendar provenance is persisted.
Next, search Notion by candidate name without a `General Interview Date` filter.

### `candidate_matched`

The candidate card and required storage identity are unambiguous. Email from the `TBD` formula is
supporting evidence only. Duplicate cards remain distinct by page ID/URL and bounded differences.
Multiple `📍 Spots` relations require an explicit recruiter selection before entering this state;
API order never selects a Spot.

### `manual_review_required`

The recording needs one or more durable Backend-owned questions: calendar ambiguity, no/duplicate
Notion card, multi-Spot choice, storage collision, route choice, or another bounded reason.

The question queue, not chat memory, stores recruiter, exact DM channel, recording/review,
recording version, question-set identity, capability hash, TTL, idempotency, reminder state, and
result. Threads are not required.

An initial daily summary presents bounded numbered questions. A free-form reply is interpreted by
Mila, confirmed to the recruiter, and submitted as exact question/action tuples. Backend closes
only independently valid unambiguous items. Omitted or ambiguous questions remain pending.
Unrelated messages consume nothing.

### `transfer_started`

The destination and collision check are persisted before upload. Same-recording retry may reuse
the same object; a different recording with the same key returns to manual review. No overwrite or
silent suffix is allowed.

### `uploaded_to_synology`

Storage confirmed the upload. Test canary may use isolated MinIO, but a test presigned URL is not
proof of durable production archival. A fallback temp file is removed immediately; a separate
four-hour temp-file TTL guard may clean abandoned local temp files.

### `synology_link_created`

A durable storage link exists. Interview flow proceeds to one idempotent Notion update containing
both matched calendar date and recording link. Non-interview flow skips Notion and proceeds toward
completion.

### `notion_updated`

Notion confirmed the idempotent date-plus-link update. This state is used only for interview
routes. Schema/page drift fails safely without repeating completed storage work.

### `source_marked_processed`

This is historical/current-code compatibility for a Yandex custom-property marker. Initial canary
keeps all Yandex mutations disabled. The target workflow does not schedule a later delete from
this state.

### `completed`

The selected route has a durable final link and all required side effects completed. The row
remains for audit and idempotency. A deduplicated completion DM is emitted through the outbox.

### `ignored`

An explicit recruiter decision ends processing without transfer. This differs from a confirmed
non-interview route, which transfers to an allowed destination and completes with a storage link.

### `failed`

The retry budget is exhausted or a safe permanent error occurred. Source data remains untouched.
A deduplicated sanitized actionable error DM is emitted; stack traces and credentials are never
included.

## Question lifecycle

```text
pending -> answered -> processing -> completed
   |          |            |
   |          |            -> failed
   |          -> pending (item rejected/ambiguous; no consumption)
   -> suppressed (after one next-summary reminder)
```

- `pending`: eligible for an answer; initial presentation or one reminder may be due.
- `answered`: an exact validated action has consumed the one-time capability.
- `processing`: Backend owns execution; one processing-start outbox item exists.
- `completed`: action and required effects succeeded; never repeated.
- `failed`: safe terminal/actionable result is recorded and notified once.
- `suppressed`: still durable and reopenable, but absent from automatic summaries.

An unanswered question appears initially, repeats once in the next eligible 18:00 recruiter-local
summary, then is automatically suppressed. There is no reminder spam between summaries.

## Scheduler lifecycle

Backend schedules one scan/summary at 18:00 in each active recruiter's configured IANA timezone.
A recruiter/local-date key and claim lease provide DST, restart, misfire, and concurrent-instance
deduplication. OpenClaw heartbeat is not a scheduler.

The scheduler defaults to disabled and stays disabled through manual canary. Enabling the single
real scheduled test requires separate approval; it is disabled again afterward unless continued
operation is separately approved. Manual scan and status remain supported while disabled.

No scheduled Yandex cleanup job is registered. Manual cleanup is a separate preview/confirm
workflow and can move only revalidated Backend-proven completed sources with durable production
storage links to Yandex Trash. Permanent purge is unavailable.

## Notification lifecycle

Summary, processing-start, completion, and error notifications enter a durable outbox with stable
delivery keys. Workers claim with expiring leases. Restart recovery may reclaim stale rows but may
not create a second logical delivery. Mattermost delivery is exact-DM-only; no shared-channel
fallback exists.

## Retry and safety invariants

- network/rate-limit failures use bounded backoff and persisted attempt state;
- discovery and matching ambiguity return to a resumable/manual state, never `ignored`;
- each side effect is guarded by stored identity, expected version, and idempotency result;
- stale version, expired/reused capability, wrong recruiter, or wrong/non-DM channel fails closed;
- Notion writes occur only after a fresh Backend-runtime schema probe;
- canary cannot access production Notion, Yandex mutations, or Synology;
- normal deterministic processing does not invoke an LLM.
