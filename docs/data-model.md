---
type: reference
status: target
last_updated: 2026-07-22
sources:
  - .memory-bank/architecture.md
  - .memory-bank/decisions.md
  - swarm-report/recording-agent-mila-completion-plan.md
---

# Data Model — Recording Agent

PostgreSQL is the authoritative workflow-state store. It keeps recording metadata, matching
provenance, questions, capabilities, delivery claims, and side-effect results. It never stores
video bytes or plaintext integration credentials.

The approved completion plan is authoritative for unfinished schema work. Existing tables and
columns remain historical migration input; Checkpoint 1 must evolve them with an explicit Alembic
mapping rather than create a competing review subsystem.

## Core entities

### `recordings`

One row represents one Yandex Disk source object. `disk_file_id` is unique and is the primary
idempotency identity. The row contains:

- immutable source identity and bounded metadata;
- parsed calendar event data and immutable calendar collection provenance;
- candidate name and optional attendee email evidence;
- selected Notion page ID and URL;
- selected Spot identity and title, when the card has multiple `📍 Spots` relations;
- generated filename, canonical storage key, durable final link, and route type;
- status, optimistic `version`, retry/error metadata, and timestamps.

The data-source ID discovered from Notion is never configured or persisted. Raw ICS, authorization
headers, tokens, passwords, and unrestricted external payloads are not persisted.

Candidate lookup uses the normalized candidate name. `General Interview Date` is an output, not a
lookup filter. Email extracted from the `TBD` formula is optional supporting evidence. A missing or
mismatched attendee email cannot reject an otherwise valid name match.

Storage identity is deterministic:

```text
YYYY-MM-DD_<candidate_name>_<project_or_spot>_<interview_type>.<ext>
<recruiter>/<YYYY-MM-DD>/<candidate>/<generated_filename>
```

Zero Spot relations use `unspecified`; one relation resolves directly; multiple relations require
an explicit recruiter selection that is persisted before filename/key generation. Relation API
order is never authoritative.

### `processing_attempts`

Append-only audit rows record step, before/after state, success, safe error, duration, and bounded
metadata. They must not contain secrets or raw third-party payloads.

### `recruiter_config`

Operator-owned recruiter configuration contains stable recruiter identity, allowlisted Mattermost
user and exact DM channel, configured IANA timezone, Notion database ID, storage root, calendar
selection version, enablement flags, and scheduler activation state.

The schedule is fixed at 18:00 in the recruiter's configured local timezone. The scheduler is
disabled by default and remains disabled through manual canary. Manual message-triggered scan and
status intents remain available while the scheduler is disabled.

### Calendar inventory and provenance

`recruiter_calendar` is the authoritative inventory of recruiter-owned CalDAV VEVENT collections.
It uses a stable opaque ID, recruiter ID, canonical same-origin HTTPS URL, display-name snapshot,
default/selected/available flags, and last-seen timestamp. The database enforces uniqueness on
`(recruiter_id, canonical_url)` and at most one default per recruiter.

Confirmed recordings store `matched_calendar_id` plus immutable URL and display-name snapshots.
Manual-review outcomes retain bounded diagnostics but clear confirmed event/provenance fields.

## Durable question queue

The existing `manual_reviews` concept is evolved into the single Backend-owned question workflow.
Each question or question-set row must persist:

- recruiter ID and exact verified direct-message channel;
- recording/review ID and expected recording version;
- stable question-set identity and bounded numbered choices;
- lifecycle: `pending`, `answered`, `processing`, `completed`, `failed`, or `suppressed`;
- one-time capability hash and expiry; plaintext capability values are never stored;
- stable request fingerprint, idempotency result, and answer/action tuple;
- delivery claim/lease, attempt count, and stale-claim recovery fields;
- initial presentation date, reminder count, and suppression timestamp;
- safe terminal result and timestamps.

Threads are not part of the target binding. Trusted recruiter and DM metadata comes from verified
Mattermost/OpenClaw context or Backend lookup, never from free-form text.

An unanswered question is included in its initial eligible summary, repeated once in the next
eligible 18:00 summary, and then remains durable but becomes `suppressed` for later automatic
summaries. Explicit reopening creates an audited new presentation opportunity. Answered,
completed, failed, and suppressed questions never repeat automatically.

Partial replies are applied per exact question/action tuple. Accepted unambiguous items advance;
omitted or ambiguous items remain untouched. Acknowledgements, unrelated messages, edited or
quoted old messages, and bare numbers without an active question-set reference consume nothing.

## Notification outbox and digest delivery

A durable outbox stores summaries, processing-start feedback, completion messages, and sanitized
actionable errors. Each row contains a deterministic delivery key, recruiter/DM binding, payload
kind, bounded payload, claim/lease fields, attempt state, and terminal delivery result. Unique
delivery keys prevent duplicate DMs across retries and restarts.

A daily digest record uses a unique recruiter plus local-date key. This enforces one eligible
18:00 summary per recruiter-local date across restarts, DST transitions, misfires, and multiple
Backend instances.

## Storage destinations and cleanup previews

Synology destinations use opaque Backend-owned IDs. A destination record contains recruiter,
canonical path under the configured root, bounded display metadata, permissions/preflight state,
and expiry where appropriate. Mila never supplies an executable raw path.

A cleanup preview is an immutable bounded snapshot bound to recruiter, exact DM, source file IDs
and versions, content hash, one-time capability hash, and expiry. Confirmation revalidates every
item against Backend-proven completion and a durable production storage link, then records an
idempotent per-file Trash-move result.

There is no minimum cleanup age, scheduled Yandex cleanup, or permanent-purge entity/API. Test
MinIO links do not make a source eligible for production cleanup.

## Required integrity constraints

- unique `recordings.disk_file_id`;
- unique digest `(recruiter_id, local_date)`;
- unique outbox deterministic delivery key;
- one-time capability consumption with replay-equivalent result for an identical fingerprint;
- conflicting replay, stale version, wrong recruiter/DM, and expired capability fail closed;
- one storage key may belong to only one recording; same-recording retry reuses it, another
  recording produces manual review;
- canonical storage and folder paths must remain under the configured recruiter root;
- secrets are supplied only through protected Backend service configuration.

## Migration requirements

Checkpoint 1 generates the actual Alembic revision after inspecting current ORM models and heads.
It must define and test the mapping from legacy `pending`, `resolved`, and `expired` review rows to
the target lifecycle, including upgrade, downgrade, `current`, and `alembic check` on isolated
data. Applied shared migrations are never deleted.
