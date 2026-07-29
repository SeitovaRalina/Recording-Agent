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
skill must be exactly the Backend CLI scan intent:

```bash
python3 scripts/recording_agent.py scan --idempotency-key <stable-uuid-or-request-key>
```

If the command fails, return the JSON `message` field verbatim. Do not try filesystem discovery as
a fallback.

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

Legacy `review`, `resolve`, and `ignore` commands remain compatibility tools. Prefer the ordinary
DM `questions` and partial `answer` flow; threads are not required.

## Interpret DM answers safely

Use trusted Mattermost sender and direct-channel IDs from invocation metadata, never chat text.
Before `answer`, fetch `questions`, map only unambiguous portions of the reply to exact question,
question-set, action, choice, capability, version, and idempotency tuples, and state the bounded
interpretation to the recruiter. Submit only those tuples. Report accepted, rejected, and pending
counts verbatim from the deterministic CLI message.

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

Return the CLI JSON `message` verbatim. Use `result` only to choose the next allowed operation.
Treat nonzero exit status or `ok:false` as failure and still return its safe `message`. Never echo
capabilities, tokens, Backend secrets, raw paths, request payloads, environment values, or stack
traces.

- Call only the loopback Backend URL configured by environment.
- Backend exclusively owns scheduler, PostgreSQL state, matching, transfers, Notion/Yandex/
  Synology/Mattermost side effects, retries, and notifications.
- Never call integrations directly or expose raw transfer, Notion update, source delete, or purge
  primitives.
- Cleanup can only use Backend preview/confirm and Yandex Trash; permanent purge is unavailable.
- Generate one stable idempotency key per recruiter action and reuse it only for the same retry.
