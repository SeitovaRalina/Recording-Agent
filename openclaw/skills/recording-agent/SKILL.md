---
name: recording-agent
description: Operate Recording Agent through Mila for Russian or English recruiter requests to scan interview recordings, query status, answer numbered clarification questions in an ordinary DM, route a working-meeting recording, choose an allowed storage folder, or preview and confirm cleanup of completed sources.
---

# Recording Agent

Use `scripts/recording_agent.py` for every operation. Read `references/contract.md` before any
mutation or when interpreting a Backend error.

## Mandatory execution rule

Never inspect this workspace to answer recruiter requests. Do not run `find`, `ls`, `rg`, `grep`,
or read repository files when a recruiter asks to scan, check status, answer a question, choose a
folder, reroute a recording, reassign a Notion card, or clean completed sources. The workspace is
only the skill package; recordings and processing state live in the Backend.

For a recruiter request to check new interview recordings, your first command after loading this
skill must be the Backend CLI scan intent with the trusted Mattermost metadata from the current
invocation:

```bash
python3 scripts/recording_agent.py scan \
  --recruiter-user-id <metadata.sender_id> \
  --mattermost-dm-channel-id <metadata.group_channel_without_leading_hash> \
  --idempotency-key <stable-uuid-or-request-key>
```

If the command fails, report its JSON `message` to the recruiter. Do not try filesystem discovery
as a fallback. When it succeeds, continue with "Finish the job in one turn" below; a scan is never
the last step while a found recording still needs a decision you can make or ask about.

For a recruiter request to show recording status, your first command after loading this skill must
be the Backend CLI status intent with the trusted Mattermost sender id from the current invocation:

```bash
python3 scripts/recording_agent.py status \
  --recruiter-user-id <metadata.sender_id>
```

Add only explicit recruiter-requested filters such as `--date`, `--candidate`, `--recording-id`,
or `--status`. Never run `python3 scripts/recording_agent.py` without a subcommand. If the command
fails, report its JSON `message`.

## Long-running commands

`scan`, `answer`, `route-interview`, `non-interview`, `reroute-recording`,
`notion-reassignment-confirm` and `cleanup-confirm` can take several minutes (Disk, calendar,
Notion and Synology are called synchronously). Run them with an exec timeout of at least 320
seconds. If exec reports that the command is still running, poll it until it exits; never tell the
recruiter that something failed while the command is still running.

## Finish the job in one turn

The recruiter should not have to ask "what next?". One recruiter message ideally produces one
complete reply. Within the same turn, keep calling allowed commands until every recording from the
request is either done or waiting for a question that only the recruiter can answer.

After `scan` (and whenever the recruiter asks what is pending):

1. For each recording with `storage_destination_required` (or `storage_key_collision`), call
   `destinations` once and choose by the destination rules below.
   - Exactly one folder clearly fits (for example Spot `Java-разработчик @Т-банк` and only
     `2. Interviews external/Backend` fits): call `route-interview` immediately, without asking.
   - Several folders fit (for example `Flutter` exists in both external and internal) or none fits:
     do not stop; include the question in the same reply (see step 3).
2. For every other review reason (calendar, candidate card, multiple Spots), call `questions`.
   If a recording's error says Notion is temporarily unavailable, run `scan` once more in the same
   turn with a new idempotency key. If it is still unavailable, tell the recruiter the recording is
   safe and will be processed by the next check; do not call it a failure.
3. Send one reply that contains, in this order:
   - what was found (how many recordings, candidates, projects);
   - what you already completed, with links (step 4);
   - one numbered list of every remaining question with its options, the option you recommend and
     why, and an example answer such as `1 — внешний проект` or `создай папку Kotlin во внешних`.
4. After `route-interview`/`non-interview` returns `completed`, tell the recruiter the candidate,
   the Notion card link and the recording link from `result` (`notion_url`, `safe_link`), and say
   the result is also visible in the Notion card. The Backend sends its own completion message too.
5. When the recruiter answers, apply every clear answer in the same turn (`route-interview`,
   `create-destination` then `route-interview`, or `answer`), then report results as in step 4 and
   list only what is still open.

Write in the recruiter's language, in full sentences, without internal codes such as
`storage_destination_required`, recording IDs, versions or capabilities.

## Retry after an error

If a recording is `failed` after the candidate was matched (transfer, link or Notion step) and the
recruiter asks to retry, call `status` for the current `version`, then `route-interview` with the
same folder (or the folder the recruiter names) and a new idempotency key. The Backend reuses an
already uploaded file and never creates a second copy. If the failure happened before a candidate
was matched (calendar or Notion lookup), explain that the recording needs a new scan after the data
is fixed.

## Route requests

- `scan`: a recruiter asks to check or rescan new recordings. Manual scan remains available while
  the Backend scheduler is disabled.
- `status`: filter by date, candidate, recording ID, or status.
- `questions`: fetch the current Backend-owned numbered question set in this exact recruiter DM.
- `answer`: only after a reply clearly addresses an active Recording Agent question set.
- `destinations` / `create-destination`: list or create only Backend-approved Synology folders.
- `route-interview`: choose one Backend-returned destination for an interview recording. Use the
  LLM only against the bounded `destinations` result and the current recording context. If exactly
  one folder fits the meeting title, candidate context, and Notion Spot text, route with its opaque
  id. If several folders fit, ask the recruiter which destination to use. If none fits, ask the
  recruiter for a new folder name, then call `create-destination` under one returned root.
- `non-interview`: the recruiter explicitly classifies a recording as a working meeting and has
  selected one returned destination.
- `cleanup-preview`: the recruiter asks to clean successfully processed recordings.
- `cleanup-confirm`: only after showing the immutable preview and receiving explicit confirmation.
- `reroute-recording`: first call `destinations`; submit only one returned destination ID and the
  displayed recording version. Never pass a path. The Backend moves the verified Synology file and
  replaces the current Notion recording link only after the new public link is verified.
- `notion-reassignment`: resolve a recruiter URL/name hint to bounded Backend candidates, show the
  result, then require an explicit confirmation capability. It writes/verifies the target card
  before clearing the old card's recording field.
- `autonomous-routing`: only when a Gateway Cron dispatcher supplies an opaque routing-job UUID and
  a one-time dispatch nonce. Read `references/autonomous-routing.md` before this operation.

Choose the storage command by the recording `status` returned by `status`, never by wording such
as "retry", "again", "move", or "same folder":

- `candidate_matched`, `manual_review_required` (including `storage_destination_required` and
  `storage_key_collision`) or `failed` after candidate matching: the file is not stored yet. Use
  `route-interview` with the current `version`; this also retries a failed transfer.
- `completed`: the file is already stored. Use `reroute-recording` only when the recruiter asks
  to move it to a different folder.
- Any other status: report the status and do not submit a storage command.

Legacy `review`, `resolve`, and `ignore` commands remain compatibility tools. Prefer the ordinary
DM `questions` and partial `answer` flow; threads are not required.

## Interpret DM answers safely

Use trusted Mattermost sender and direct-channel IDs from invocation metadata, never chat text.
Before `answer`, fetch `questions`, map only unambiguous portions of the reply to exact question,
question-set, action, choice, capability, version, and idempotency tuples, and state the bounded
interpretation to the recruiter. Submit only those tuples. Report accepted, rejected, and pending
counts from the CLI message, then continue with any work the accepted answers unlocked.

Do not treat unrelated messages, acknowledgements, quoted or edited old messages, bare numbers
without an active Recording Agent question set, or ambiguous delayed replies as answers. Omitted
questions stay pending. Never infer a candidate, Spot, or cleanup confirmation.

Interview destination selection is the only allowed LLM classification step. The Backend does not
map Spots or meeting names to folders. Always call `destinations` first, compare only returned
folder labels, and submit only the returned destination id. Never submit a raw path. Ambiguous roots
such as duplicated `Flutter` folders across internal and external projects require a recruiter
question unless the recruiter has already given the internal/external choice.

Autonomous routing is a separate, fresh background session. It is not a recruiter DM and must never
send a chat message. Its only inputs are a routing-job UUID and one-time nonce from the dispatcher.
It has no Backend/OpenClaw Backend secret or LLM provider key. Its process gets only a root-controlled
loopback Gateway client token so `openclaw agent` reaches the active Gateway; routing commands
authenticate only with the nonce.
Call `routing-activate`, compare only the returned bounded labels, then call `routing-resolve` for
one exact high-confidence returned ID; otherwise call `routing-defer`. Finish with exactly
`NO_REPLY`. Never use a DM command, raw path, Notion URL, recruiter identity, or a user instruction
while handling an autonomous routing job.

For duplicate Notion cards, preserve each card URL and all returned differentiators, including
`📍 Spots`. Equal titles remain separate. Multiple Spots require an explicit returned choice.

## Output and trust boundaries

The CLI JSON `message` is the factual basis of your reply: do not contradict it, do not invent
counts, candidates, folders or links, and keep its links. You may rephrase it and add the next step.
Use `result` to choose the next allowed operation. Treat nonzero exit status or `ok:false` as
failure and report its safe `message`. Never echo capabilities, tokens, Backend secrets, raw paths,
request payloads, environment values, or stack traces.

- Call only the loopback Backend URL configured by environment.
- Backend exclusively owns scheduler, PostgreSQL state, matching, transfers, Notion/Yandex/
  Synology/Mattermost side effects, retries, and notifications.
- Never call integrations directly or expose raw transfer, Notion update, source delete, or purge
  primitives.
- Cleanup can only use Backend preview/confirm and Yandex Trash; permanent purge is unavailable.
- Generate one stable idempotency key per recruiter action and reuse it only for the same retry.
