# Plan: Configurable calendar selection with safe Telemost title matching (slug: calendar-selection-title-match)

## TL;DR

Let each recruiter select monitored Yandex CalDAV calendars while retaining one explicit default.
Because all Telemost recordings remain in one immutable Disk folder, query the full discovered
calendar set for collision evidence but allow automatic matches only from the effective monitored
set. A recording reaches `calendar_event_found` only when its official filename title and local
start time identify exactly one compatible eligible VEVENT; every ambiguous, incomplete, or
unmonitored case fails closed.

## Acceptance criteria

1. Calendar discovery returns all recruiter-owned VEVENT calendar collections with canonical
   same-origin HTTPS URLs and `DAV:displayname`; arbitrary user-provided URLs are never requested
   with recruiter credentials.
2. A recruiter has exactly one explicit default calendar and zero or more selected calendars.
   Effective calendars are the selected set when non-empty, otherwise the default only.
3. Existing non-null `recruiter_config.caldav_calendar_url` values are backfilled as defaults and
   remain a runtime compatibility fallback during this migration. A missing default is a visible
   configuration error; response ordering must never select one.
4. Calendar selection accepts only opaque discovered-calendar IDs owned by the recruiter. The
   idempotent replacement operation is atomic, rejects stale/unknown/cross-recruiter IDs, protects
   against lost updates, and returns the resulting effective set.
5. Every scan uses a complete immutable snapshot of all available discovered calendars. Only
   effective calendars are eligible for a match; unselected calendars are collision/source
   evidence. Any collection query failure forbids a partial automatic match and leaves the
   recording resumable.
6. Telemost filename parsing supports the verified
   `YYYY-MM-DD_HHMMSS_<meeting title>.webm` and `_audio_only.webm` shapes. The parsed timestamp is
   interpreted in `SCAN_LOCAL_TIMEZONE`; malformed, renamed, or unsupported filenames fail closed.
7. Title normalization is Unicode NFKC + casefold + trimmed/collapsed Unicode whitespace only.
   It never uses substring, token, punctuation-dropping, transliteration, edit-distance, or LLM
   comparison.
8. A compatible event must have exact normalized filename-title/SUMMARY equality and temporal
   compatibility using the parsed recording start. Deduplicate only identical occurrences by
   `(calendar_id, UID, RECURRENCE-ID)`.
9. Exactly one compatible event in the effective set, no compatible collision outside it, and
   the existing confidence threshold are all required for `calendar_event_found`.
10. Parser failure, no compatible event, an event found only in an unmonitored calendar, multiple
    compatible events, or a monitored/unmonitored collision transitions to
    `manual_review_required` with a structured reason. Automatic `ignored` remains forbidden.
11. The reported `2026-07-15_085411_Не рекрутинг встреча.webm` cannot match
    `Встреча на 30 минут (Иван Иванов)` despite overlapping time and calink/Telemost signals.
12. A confirmed match persists calendar row ID plus URL/display-name snapshots. Manual-review
    outcomes persist no confirmed event or calendar provenance, only bounded diagnostic candidate
    summaries without raw ICS or credentials.
13. Existing non-terminal false `calendar_event_found` rows can be identified by a dry-run
    remediation command and explicitly requeued with audit output; terminal rows are never
    rewritten automatically.
14. Calendar configuration endpoints are internal-only, use constant-time OpenClaw-secret
    verification and recruiter scoping, and audit actor/time/before/after selection state.
15. No Disk deletion, Notion mutation, retention change, fuzzy matching, or automatic non-interview
    classification is introduced.
16. Migration upgrade/downgrade/re-upgrade, Alembic checks, Ruff, formatting, strict mypy, and the
    full pytest suite pass.

## Plan

1. Update project truth before code.
   - Files: `.memory-bank/architecture.md`, `.memory-bank/decisions.md`,
     `.memory-bank/open-questions.md`, `docs/status-machine.md`.
   - Record the immutable shared Telemost folder, explicit default/selection semantics, exact
     title/time safety gate, full-set collision detection, and fail-closed behavior.
   - Keep the invariant that only a recruiter can choose `ignored`.

2. Add normalized calendar configuration and provenance through Alembic.
   - Files: `app/db/models/recruiter_calendar.py`, `app/db/models/recruiter_config.py`,
     `app/db/models/recording.py`, `app/db/models/__init__.py`, generated Alembic revision.
   - Generate the revision with `/migrate generate "add recruiter calendar selection"`.
   - Add `recruiter_calendar`: recruiter FK, canonical URL, display-name snapshot, `is_default`,
     `selected`, `available`, `last_seen_at`, selection version/audit fields, timestamps.
   - PostgreSQL constraints: unique `(recruiter_id, canonical_url)`, at most one default per
     recruiter, non-null booleans, stable IDs, and deterministic FK delete behavior.
   - Add nullable recording matched-calendar FK (`ON DELETE SET NULL`) plus immutable URL and
     display-name snapshots and a structured manual-review reason/candidate payload.
   - Backfill every validated non-null legacy `caldav_calendar_url` as the default. Preserve the
     legacy column and original data on downgrade; define the new table as authoritative after
     successful backfill and legacy as fallback only.

3. Make collection discovery complete and credential-safe.
   - File: `app/tools/calendar.py`.
   - Discover principal, calendar-home-set, and successful calendar `propstat` entries; require
     calendar resourcetype and VEVENT support; read `DAV:displayname`.
   - Canonicalize relative hrefs against the validated calendar-home-set. Require configured
     CalDAV HTTPS origin and reject cross-origin redirects.
   - Upsert discovery metadata without changing default/selection. Mark missing collections
     unavailable rather than deleting referenced rows.
   - Never infer a default from response order or display name. Null/unvalidated default means
     configuration incomplete and blocks automatic matching.

4. Add internal calendar configuration contracts.
   - Files: `app/routers/calendars.py`, `app/main.py`, existing auth dependency/module as applicable,
     `docs/api-contracts/yandex-caldav.md`.
   - GET discovered/current/effective calendar state for one recruiter.
   - Idempotent PUT replaces selected opaque calendar IDs; `[]` clears selection and restores
     default-only behavior. Require a version/ETag, validate ownership/availability atomically,
     and return the resulting state.
   - Provide an explicit operation to set/change the default from a discovered available calendar.
   - Keep endpoints localhost/internal-only, compare the service secret in constant time, scope
     every mutation to the requested recruiter, and audit actor/time/before/after IDs.

5. Query calendars as one safe snapshot.
   - File: `app/tools/calendar.py`.
   - Resolve all discovered available collections and the effective eligible subset in one DB
     snapshot. Query every available collection for the recording window, tagging each event with
     calendar ID/URL/display name and `RECURRENCE-ID`.
   - If discovery is stale or any required REPORT fails, raise an aggregate/incomplete-set error;
     do not return a partial event list that could create a false unique match.
   - Only effective-calendar events are eligible; other events remain collision/source evidence.

6. Add deterministic filename correlation and ambiguity rules.
   - Files: `app/services/matching.py`, `app/scheduler/cron.py`.
   - Parse video/audio filenames with an anchored parser. Extract local recording start and title;
     Unicode-normalize title conservatively.
   - Use filename start as the authoritative event-correlation timestamp. Disk timestamps remain
     operational metadata; a materially inconsistent or unparseable filename fails closed.
   - Define compatibility before scoring: exact normalized title equality plus the existing time
     tolerance. Deduplicate only `(calendar_id, UID, RECURRENCE-ID)`.
   - Zero compatible events, unmonitored-only compatibility, multiple compatibility, or any
     monitored/unmonitored collision => manual review with a typed reason and bounded candidate
     summaries. Do not persist a confirmed event/provenance.
   - One eligible compatible event with no collision is scored using existing signals and threshold;
     only a passing result persists event fields and calendar provenance in the same transaction.
   - Transient/incomplete calendar snapshots leave `found` resumable under existing failure logic.

7. Add explicit remediation for already-bad non-terminal matches.
   - File: `tools/setup/rematch_calendar_events.py` and tests.
   - Default dry-run lists non-terminal `calendar_event_found` rows whose stored event title is not
     compatible with the recording filename, including IDs and reasons.
   - `--apply` explicitly clears confirmed calendar fields/provenance and requeues only listed
     non-terminal rows to `found`, with operator identity and audit output. Never touch terminal
     rows, Disk, Notion, or Synology. Do not run `--apply` automatically during build/migration.

8. Update documentation and reports.
   - Files: `docs/data-model.md`, `docs/status-machine.md`,
     `docs/api-contracts/yandex-caldav.md`, build/review reports.
   - Document default fallback, explicit selection replacement, collision-only calendar queries,
     title parser limitations, review reasons, provenance, remediation, and operational setup.

9. Test the full contract.
   - `tests/test_calendar.py`: discovery propstat/origin/redirect/canonicalization, stable default,
     selection/effective set, all-calendar query tagging, partial failure, stale collections.
   - `tests/test_matching.py`: real Cyrillic/Latin filenames, audio/video, underscores, NFKC,
     whitespace/case, renamed/malformed/duplicate suffixes, strict non-fuzzy mismatch, timestamp.
   - `tests/test_scheduler.py`: reported regression, positive unique match, unmonitored-only,
     monitored/unmonitored collision, duplicates, incomplete set, manual reasons, provenance.
   - Router tests: authentication, recruiter isolation, opaque IDs, versions, atomic replacement,
     clear-to-default, set-default, audit metadata.
   - Migration/model tests against PostgreSQL: backfill/null/canonical duplicate cases, constraints,
     ownership/delete behavior, upgrade/downgrade/re-upgrade and heads.
   - Remediation tests: dry-run, explicit apply, mismatch-only scope, terminal exclusion, audit.
   - Run `poetry run ruff check app tests alembic tools`,
     `poetry run ruff format --check app tests alembic tools`, `poetry run mypy app tests tools`,
     `poetry run alembic heads`, `poetry run alembic check`, and `poetry run pytest`.

## Blockers

None. Default-calendar selection is explicit when no validated legacy URL exists; no server response
ordering or guessed Yandex metadata is used.

## Out of scope

- Changing the shared `/Записи Телемоста/` Disk folder.
- Fuzzy, transliterated, token-based, or LLM title matching.
- Automatic `ignored` classification.
- Mattermost/UI implementation for calendar selection or manual review.
- Notion candidate matching changes.
- Disk deletion, retention, purge, processed-marker, Synology, or transfer changes.
- Removing `recruiter_config.caldav_calendar_url` in this migration.
- Automatic mutation of existing matched/terminal rows.
- Recurrence expansion beyond preserving/deduplicating available `RECURRENCE-ID` values.

## Assumptions

- The verified Yandex Disk video naming convention is
  `YYYY-MM-DD_HHMMSS_<meeting title>.webm`; deviations fail closed rather than being guessed.
- `SCAN_LOCAL_TIMEZONE` is the organizer's filename timezone for the current deployment.
- Existing non-null `caldav_calendar_url` values are intended defaults but must validate as
  recruiter-owned discovered collections.
- The current OpenClaw secret is service authentication, not end-user authentication; calendar
  endpoints remain internal and record the supplied operator identity for audit.
- Querying unselected calendars is permitted only for collision/source classification; their events
  can never become confirmed matches.
