# R01 — стенограмма

## Ход 1 (37 с)

**Рекрутер:**

> Проверь новые записи

**Команды:**

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/SKILL.md", "offset": 1, "limit": 240}
```

<details><summary>ответ</summary>

```text
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
     do not stop; 
```

</details>

```text
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 966ded50-4ae5-5534-8ca7-8e5797ac7b7b
```

<details><summary>ответ</summary>

```text
Command still running (session cool-crest, pid 1112467). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "cool-crest", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": false, "eof": false, "offset": 0, "limit": 2000, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
{"ok":false,"message":"Backend Recording Agent сейчас недоступен. Повторите запрос позже.","error":"Backend unavailable: TimeoutError"}

Process exited with code 1.
```

</details>

**Мила:**

> Сейчас не удалось проверить: Backend Recording Agent временно недоступен. Попробуйте запросить проверку чуть позже.

**Судья:** 10/12 — Мила корректно выполнила scan и верно сообщила об ошибке бэкенда, но сценарий не завершён: destinations и route-interview не вызваны из-за недоступности бэкенда.

