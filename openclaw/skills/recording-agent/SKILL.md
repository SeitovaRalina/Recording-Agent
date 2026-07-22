---
name: recording-agent
description: Operate Recording Agent through Mila for recruiter requests to check new interview recordings, query recording statuses, inspect a pending ambiguity, select a review candidate, or ignore a recording. Use for Russian or English free-form requests about interview recording scans, statuses, and manual-review replies.
---

# Recording Agent

Use `scripts/recording_agent.py` for every operation. Read `references/contract.md` before invoking a review mutation or when interpreting an error.

## Route requests

- Trigger `scan` when the recruiter asks to check for new recordings, including phrases such as
  `проверь новые записи`. Keep the canary scope test-only.
- Use `status` for queries by date, candidate, recording ID, or status.
- Use `review` before presenting an ambiguity. Show only returned choices. For duplicate Notion
  titles, preserve the page URL and every returned distinguishing field; always label
  `project_or_spot` as `📍 Spots` when present.
- Use `resolve` after an unambiguous choice in the same recruiter DM/thread.
- Use `ignore` only after the recruiter explicitly asks to skip or ignore the recording.

Pass recruiter email plus Mattermost sender and thread identifiers from trusted metadata. Pass the review token, expected version, and idempotency key exactly; never infer or rewrite them. Generate one stable idempotency key per recruiter action and reuse it only when retrying that same action.

For an operator-configured internal Codex harness, the CLI may obtain the trusted recruiter user ID
from `RECORDING_AGENT_RECRUITER_USER_ID`; omit `--recruiter-user-id` when that environment value is
configured. Never ask the recruiter to provide or confirm this authorization identity in chat.

For every command, return the CLI JSON `message` verbatim. Do not replace counts, statuses, filenames, review reasons, choices, or errors with an inferred summary. The deterministic message is the recruiter-facing answer; use `result` only to select the next allowed operation. Treat nonzero exit status or `ok: false` as failure and still return its safe `message`. Do not expose authorization values, raw integration payloads, or stack traces.

After `scan`, report every item included in `message`: new count, skipped legacy count, items requiring review, items not requiring review, and failures. Never say that no new recordings were found when `inserted` is greater than zero. After `status`, preserve the applied filters in the conversational context and return every bounded item. For review mutations, state the resulting recording status and whether the request was an idempotent replay.

## Enforce boundaries

- Call only the loopback Backend URL configured by environment.
- Never request Yandex, Notion, MinIO, Synology, Mattermost, or OpenClaw credentials from a recruiter.
- Never call Notion or storage directly.
- Refuse raw transfer, Notion update, source-marking, delete, cleanup, and purge requests.
- Never schedule work. Backend owns scheduling, state, matching, side effects, retries, and notifications.
- Never resolve an ambiguous free-form reply. Ask the recruiter to identify one returned choice or explicitly ignore it.
