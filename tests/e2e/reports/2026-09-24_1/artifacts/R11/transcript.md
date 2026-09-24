# R11 — стенограмма

## Ход 1 (55 с)

**Рекрутер:**

> По записи E2E Лидия Автоаналитик R11-0924_1a4 — во внешние

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

1. For ea
```

</details>

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/references/contract.md", "offset": 1, "limit": 240}
```

<details><summary>ответ</summary>

```text
# Backend contract

`RECORDING_AGENT_BACKEND_URL` must be loopback HTTP(S), defaulting to
`http://127.0.0.1:18000`. `RECORDING_AGENT_BACKEND_SECRET` exists only in the recruiter-facing
process/service environment. The CLI never prints it. Autonomous routing commands never require,
read, or send this secret.

Trusted invocation metadata is supplied through `RECORDING_AGENT_RECRUITER_EMAIL`,
`RECORDING_AGENT_RECRUITER_USER_ID`, and `RECORDING_AGENT_MATTERMOST_DM_CHANNEL_ID`. When a trusted
value exists, a conflicting explicit CLI value is rejected; model-generated arguments cannot
override invocation identity. Never obtain these identities from recruiter text.

All commands emit one bounded JSON object. Success is
`{"ok":true,"message":"...","result":...}`. Failure is
`{"ok":false,"message":"...","error":"..."}` with exit status 1. Return `message` verbatim.
Backend responses above 64 KiB fail closed.

## Commands

```text
recording_agent.py scan --idempotency-key KEY
recording_agent.py status [trusted metadata and bounded filters]
recording_agent.py questions [trusted metadata] [--question-set-id UUID] [--limit 1..50]
recording_agent.py answer [trusted metadata] --actions-json JSON
recording_agent.py destinations [trusted metadata]
recording_agent.py create-destination [trusted metadata] --parent-destination-id UUID --name NAME
recording_agent.py route-interview [trusted metadata] --recording-id UUID --destination-id UUID
                                  --expected-version N --idempotency-key KEY
recording_agent.py non-interview [trusted metadata] --recording-id UUID --destination-id UUID
                                 --expected-version N --idempotency-key KEY
recording_agent.py cleanup-preview [trusted metadata] [--limit 1..100]
recording_agent.py cleanup-confirm [trusted metadata] --preview-id UUID --capability <capability>
                                   --snapshot-hash SHA256 --idempotency-key KEY
recording_agent.py routing-activate --job-id UUID --dispatch-nonce NONCE
recording_agent.py routing-resolve --job-id UUID --dispatch-nonce NONCE --snapshot-hash SHA256
                                    --destination-id UUID
recording_agent.py routing-defer --job-id UUID --dispatch-nonce NONCE
                                  --snapshot-hash SHA256
                                  --reason ambiguous|no_match|model_error
```

`answer --actions-json` accepts 1..50 objects containing only `question_id`, `question_set_id`,
`action`, `capability`, `expected_version`, `idempotency_key`, and optional `choice`. `resolve`
requires choice 1..10; `ignore` forbids choice. Free text is never sent to Backend.

## Endpoints and safety

| Command | Backend endpoint |
|---|---|
| `scan` | `POST /tools/scans/trigger` with fixed test scope |
| `status` | `GET /tools/recordings/status` |
| `questions` | `GET /tools/questions` |
| `answer` | `POST /tools/questions/answer` |
| `destinations` | `GET /tools/storage/destinations` |
| `create-destination` | `POST /t
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 2.\n1. 2026-09-24_074712_Собеседование (E2E Максим Автодискавери R11-0924_1a4).webm — подходящая папка в Synology не найдена\n2. 2026-09-24_074343_Собеседование (E2E Лидия Автоаналитик R11-0924_1a4).webm — подходят несколько папок в Synology\n   1) Recruiting-E/2. Interviews external/Analyst\n   2) Recruiting-E/3. Interviews internal/Analyst","result":{"items":[{"question_id":"61a1dc7e-7afa-4501-bd3d-ee8e5d882cd4","question_set_id":"1022820f-5b73-41e1-91d6-dc94591c9548","recording_id":"e24935ec-00ce-48f8-9a2f-508ae54eb378","recording_version":2,"filename":"2026-09-24_074712_Собеседование (E2E Максим Автодискавери R11-0924_1a4).webm","reason":"autonomous_routing_no_match","choices":[],"capability":"<capability>","expires_at":"2026-09-24T05:19:13.426035+00:00"},{"question_id":"c38ddf03-0060-422d-b2ca-b22bd1ccfa06","question_set_id":"f0e25339-3be5-48f7-ab7f-f3c3887bf49a","recording_id":"6af73183-725b-4ad5-81a9-3f1d4952530f","recording_version":2,"filename":"2026-09-24_074343_Собеседование (E2E Лидия Автоаналитик R11-0924_1a4).webm","reason":"autonomous_routing_ambiguous","choices":[{"name":"Recruiting-E/2. Interviews external/Analyst","destination_id":"7bcfe562-c4e4-444c-ac66-ae2c47229af1"},{"name":"Recruiting-E/3. Interviews internal/Analyst","destination_id":"2f3a7c4a-c126-4511-bc20-185328777419"}],"capability":"<capability>","expires_at":"2026-09-24T05:24:26.368258+00:00"}],"count":2}}
```

</details>

```text
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"c38ddf03-0060-422d-b2ca-b22bd1ccfa06","question_set_id":"f0e25339-3be5-48f7-ab7f-f3c3887bf49a","action":"resolve","choice":1,"capability":"<capability>","expected_version":2,"idempotency_key":"963cb9af-23e6-4b2a-9c76-f1a1e2d08f64"}]'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Принято ответов: 1; отклонено: 0; ещё ждут ответа: 1.\nОбработка по принятым ответам запущена.","result":{"accepted":[{"question_id":"c38ddf03-0060-422d-b2ca-b22bd1ccfa06","recording_id":"6af73183-725b-4ad5-81a9-3f1d4952530f","status":"transfer_started","version":3,"replayed":false}],"rejected":[],"pending":["61a1dc7e-7afa-4501-bd3d-ee8e5d882cd4"]}}
```

</details>

```text
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --recording-id 6af73183-725b-4ad5-81a9-3f1d4952530f
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено записей: 1.\n- 2026-09-24_074343_Собеседование (E2E Лидия Автоаналитик R11-0924_1a4).webm; кандидат: E2E Лидия Автоаналитик R11-0924_1a4; проект: Бизнес-аналитик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Лидия_Автоаналитик_R11-0924_1a4_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R11-0924_1a4-3e5c8889e4c88120a246d8d4269ef330; запись: https://gofile.me/7g8zN/cJqTWtHFt","result":{"items":[{"id":"6af73183-725b-4ad5-81a9-3f1d4952530f","filename":"2026-09-24_074343_Собеседование (E2E Лидия Автоаналитик R11-0924_1a4).webm","generated_filename":"2026-09-24_E2E_Лидия_Автоаналитик_R11-0924_1a4_Бизнес-аналитик_@Т-банк_general_interview.webm","candidate_name":"E2E Лидия Автоаналитик R11-0924_1a4","status":"completed","requires_review":false,"review_reason":"autonomous_routing_ambiguous","version":3,"found_at":"2026-09-24T05:01:23.325445+00:00","safe_link":"https://gofile.me/7g8zN/cJqTWtHFt","notion_url":"https://app.notion.com/p/E2E-R11-0924_1a4-3e5c8889e4c88120a246d8d4269ef330","spot":"Бизнес-аналитик @Т-банк","error":null}],"count":1}}
```

</details>

**Мила:**

> Запись Лидии отправлена во **внешние / Analyst** и обработана.
> 
> Карточка Notion: https://app.notion.com/p/E2E-R11-0924_1a4-3e5c8889e4c88120a246d8d4269ef330  
> Запись: https://gofile.me/7g8zN/cJqTWtHFt
> 
> Результат также виден в карточке Notion.

**Судья:** 12/12 — Мила корректно запросила вопросы, выбрала вариант Recruiting-E/2. Interviews external/Analyst через answer, проверила статус и сообщила итог с ссылками на Notion и запись — безопасно и по делу.

