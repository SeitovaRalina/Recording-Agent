# Plan: shared Mattermost channel for observing recruiter-bot conversations (slug: shared-mattermost-observer)

## TL;DR

Reject the literal "3-person group channel" shape. Ship a **mirrored notification** instead:
Backend copies every digest/question/confirmation text it already sends to a recruiter (Lilia)
to Ralina's own existing DM with the bot, prefixed with the recruiter's name, read-only, via the
existing `MattermostClient.send_dm` path. No group-channel membership, no change to
`validate_direct_channel`, no new recruiter identity inside Lilia's channel, no interaction with
`_bound_recruiter`/`_scan_recruiter`/`_question_recruiter`. Planner and skeptic reached this
independently (skeptic: group channel is HIGH-risk on three fronts; planner: mirrored notification
avoids all three by construction).

**Blocker before `/build`:** this deviates from the literal 2026-10-16 wording ("Ralina creates a
channel and adds Lilia to it") and from Q3's closed decision ("no shared-channel fallback"). Needs
explicit user confirmation that the mirrored-notification shape satisfies what Lilia/Ralina actually
need (watch exchanges + reply quality in one place) before writing code.

## Acceptance criteria

- Every 18:00 digest sent to Lilia (`daily_digest_enabled`) is also sent, verbatim content but
  prefixed `[Лилия]`, to Ralina's DM — only when an observer target is configured on Lilia's row.
- Every numbered manual-review question sent to Lilia, and her own free-form reply text once
  Backend has parsed/bound it, is mirrored to Ralina the same way.
- Mirroring never creates, answers, or mutates anything. If the mirrored send fails (Mattermost API
  error), Lilia's own primary send/flow still completes unaffected; failure is logged, not retried
  against the primary path.
- No observer configured on a recruiter row → zero behavior change (no extra API calls, no new
  column populated, existing tests unaffected).
- Regression test: `observer_mattermost_user_id`/`observer_mattermost_dm_channel` are never read
  by `_bound_recruiter`, `_scan_recruiter`, or `_question_recruiter` — an observer can never
  trigger a scan/mutation for any recruiter, including their own.
- Regression test: an observer's message in Ralina's own DM (not Lilia's channel — there is no
  shared channel) never matches or consumes a `ManualReview` capability token bound to Lilia.
- `configure_recruiter.py set-observer --email lilia... --observer-user-id ... --observer-dm-channel ...`
  / `clear-observer` manage the new column pair; existing `configure`/`preflight`/`activate` flows
  unaffected.
- Full suite green: `poetry run pytest -q` — cite pass count before shipping.

## Plan

**Decision A — channel shape: mirrored notification, not a group channel.**
`MattermostClient.validate_direct_channel` (`app/tools/mattermost.py:64-87`) hard-requires
`channel.type == "D"` and exact `{bot, recruiter}` 2-member set-equality — this is not a narrow
relaxation to widen for type `"G"`, it is the one shared validator's entire safety invariant
(this channel contains exactly the bot and one named recruiter) for every existing recruiter
(Anton, Lilia) too. Group-channel membership also puts a second real sender inside Lilia's
channel — and OpenClaw's Gateway runs **one shared conversation session per Mattermost bot
account today**, no per-sender/per-channel isolation (`deploy-and-ops.md` → "Known architecture
gap"). A group channel would not just reopen that gap, it would turn an accidental bug (today's
DM cross-talk) into an intentional feature that two real people share one undifferentiated LLM
context by design — worse, not better. Mirroring sidesteps all of it: Ralina's DM is her own
already-provisioned 1:1 channel, untouched by `validate_direct_channel` changes.

**Decision B — identity: observer is a notification destination, never a recruiter.**
Observer fields live on the *observed* recruiter's row (Lilia's `RecruiterConfig`), pointing at
Ralina's `mattermost_user_id`/`dm_channel` — nullable, additive, one observer per recruiter
(matches today's 1:1-per-recruiter style). They are never fed into `_bound_recruiter` /
`_scan_recruiter` / `_question_recruiter`'s matching — mirroring is a one-way fan-out of text
Backend already rendered, not an inbound-message path. No observer-vs-recruiter ambiguity is
possible by construction: there is no third binding state to invent, no RecruiterConfig row for
Ralina pointing at Lilia's channel, no silent fallthrough.

**Session-isolation timing — not a blocker for this shape.** The one-shared-session gap stays
live and independent (tracked separately; the 19.10/22.10 exec-failure incident shares some of
its symptom surface but is a different root cause — see the debug report). It is not a
prerequisite here because mirroring never adds a second sender into Lilia's session. It **would**
become a hard blocker again if the user later insists on the literal group-channel shape instead.

**Affected files:**
- `alembic/versions/<new>_add_recruiter_observer_mattermost.py` — additive migration: nullable
  `recruiter_config.observer_mattermost_user_id`, `recruiter_config.observer_mattermost_dm_channel`
  (Text, Text), no backfill.
- `app/db/models/recruiter_config.py` — add the two new nullable columns.
- `app/services/question_queue.py` — `build_digest`: after the existing recruiter send, if
  observer fields are set, send the same rendered text (prefixed with recruiter display name) to
  the observer channel via `MattermostClient`; wrap in try/except, log-only on failure.
- `app/routers/tools.py` — at the question-send and reply-acknowledgment call sites (wherever
  `_question_recruiter`'s output is dispatched to Mattermost, and wherever a recruiter's parsed
  reply is acknowledged back), add the same observer-mirror call. Do **not** touch
  `_bound_recruiter`/`_scan_recruiter`/`_question_recruiter` matching logic itself.
- `app/tools/mattermost.py` — no signature change expected; confirm `send_dm` works unmodified
  against Ralina's own already-provisioned DM.
- `tools/setup/configure_recruiter.py` — add `set-observer` / `clear-observer` subcommand pair.
- `tests/test_question_queue.py` — digest mirrors when observer set; no-op when unset; mirror
  failure doesn't block primary send.
- `tests/test_tools_router.py` (or wherever `_bound_recruiter` is tested) — regression:
  observer fields never satisfy `RecruiterConfig.mattermost_user_id` matching for a different
  recruiter row.
- `tests/test_configure_recruiter.py` — set-observer/clear-observer round-trip.
- `.memory-bank/current-work.md`, `open-questions.md` — record this decision under item 5 /
  close Q17 with the mirrored-notification answer; cross-reference Q3 explicitly instead of
  silently overriding its text (Q3 said "no shared-channel fallback" — this plan agrees and
  reinforces that, since mirroring is not a shared channel).
- `docs/data-model.md` — document the two new columns.

**Steps:**
1. **Confirm with the user/Lilia** that "mirrored notification to Ralina's existing DM" satisfies
   the 2026-10-16 agreement, given it deviates from the literal "group channel" wording. Do not
   build past this without that confirmation.
2. Alembic migration: two nullable columns, additive, no backfill.
3. Add fields to `RecruiterConfig` model.
4. Add `set-observer`/`clear-observer` to `configure_recruiter.py`.
5. Add a small `mirror_to_observer(settings, recruiter, text)` helper — no-op when observer
   fields are NULL, else sends via existing `send_dm`, swallows and logs Mattermost errors.
6. Call the helper from `build_digest`, the question-send path, and the reply-acknowledgment
   path in `app/routers/tools.py`.
7. Regression test proving observer fields are never read by the three binding-resolution
   functions, and that an observer's own DM message never consumes a capability token bound to
   another recruiter.
8. Update `current-work.md` item 5 and `open-questions.md` Q17/Q3 cross-reference.
9. Full suite: `poetry run pytest -q`; cite pass count.
10. Deploy per `current-work.md` "Deployment path" — this has an Alembic migration, so the
    canary-swap fast path is **forbidden**; use PR → `main` → CI → `deploy.sh`.

**Tests:**
- Unit: `build_digest` mirrors verbatim text to observer channel when set.
- Unit: `build_digest` is a no-op for mirroring when observer fields are NULL (assert no extra
  `MattermostClient` call).
- Unit: mirror-send exception does not prevent or alter the primary recruiter send (primary send
  still happens, error logged not raised).
- Regression: observer fields never satisfy any of `_bound_recruiter`/`_scan_recruiter`/
  `_question_recruiter`'s matching for a request claiming to be that recruiter.
- Regression: observer's own message never matches/consumes a pending `ManualReview` capability
  token bound to the observed recruiter.
- `configure_recruiter` set-observer/clear-observer CLI round-trip against a test DB row.
- Alembic: upgrade/downgrade clean on an empty and a populated `recruiter_config` table.

## Blockers — all resolved 2026-10-27, cleared for `/build`

1. ~~User must confirm the shape before `/build`.~~ **Resolved:** user confirmed mirrored
   notification over the literal group channel (2026-10-27).
2. ~~Privacy call: mirrored text includes Lilia's own free-form replies shown to Ralina
   verbatim.~~ **Resolved:** Lilia's consent obtained (2026-10-27).
3. ~~Confirm Ralina already has her own `mattermost_user_id` + `dm_channel`.~~ **Resolved:**
   confirmed live via read-only `recruiter_config` query — Ralina
   (`ralina.seitova@effective.band`) already has both set (`active=t`, `has_mm_user=t`,
   `has_dm_channel=t`). No onboarding step needed; observer fields on Lilia's row point at her
   existing DM.

## Out of scope

- Group/channel membership changes; widening `validate_direct_channel` to accept type `"G"`.
- Fixing the one-session-per-bot-account architecture gap (separate, already-open backlog item;
  not resolved or required by this plan under the mirrored-notification shape).
- Mirroring raw Mila/OpenClaw session transcripts or ad hoc tool-call chatter outside the
  digest/question/confirmation flow — e.g. Mila improvising a reply outside her allowed commands
  (as seen in the 19.10/22.10 incident) stays invisible to Ralina under this design, since it
  never reaches Backend's rendered-text path at all.
- Self-service observer onboarding UI; multiple observers per recruiter.
- Investigating the 19.10/22.10 exec-failure incident (separate item — see debug report, same
  session).

## Assumptions

- One observer per recruiter row is sufficient; matches current 1:1-everything-per-recruiter
  style. Multiple observers is out of scope.
- "Mirror the text Backend already renders" is acceptable fidelity for what Ralina needs to see.
- Ralina's observer channel reuses her own existing DM with the bot (she is already a recruiter
  row), not a new Mattermost-side object.
