# R05 — стенограмма

## Ход 1 (38 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key fe65308f-2fef-c235-9f0d-16827c1a0001
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_050546_Собеседование (E2E Павел Двуспотов R05-0924_1a1).webm; новая запись; нужно уточнение: у карточки несколько проектов (📍 Spots), нужно выбрать один\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"df2feb8e-850b-4258-a1ad-acc129254f5a","filename":"2026-09-24_050546_Собеседование (E2E Павел Двуспотов R05-0924_1a1).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"multiple_spots","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null}]}}
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_050546_Собеседование (E2E Павел Двуспотов R05-0924_1a1).webm — у карточки несколько проектов (📍 Spots), нужно выбрать один\n   1) E2E Павел Двуспотов R05-0924_1a1 — 📍 Spots: Python-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1\n   2) E2E Павел Двуспотов R05-0924_1a1 — 📍 Spots: Java-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1","result":{"items":[{"question_id":"249831de-b357-4407-afc9-8e3fd9b386a6","question_set_id":"50bdbd26-aae9-4fa2-bede-72558a5dc5d9","recording_id":"df2feb8e-850b-4258-a1ad-acc129254f5a","recording_version":0,"filename":"2026-09-24_050546_Собеседование (E2E Павел Двуспотов R05-0924_1a1).webm","reason":"multiple_spots","choices":[{"id":"3e5c8889-e4c8-8136-be3f-e803258d20b1","url":"https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1","name":"E2E Павел Двуспотов R05-0924_1a1","spot_id":"397c8889-e4c8-81d7-8bcb-f77c42da96e8","spot_url":"https://app.notion.com/p/Python-397c8889e4c881d78bcbf77c42da96e8","candidate_email":"","project_or_spot":"Python-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""},{"id":"3e5c8889-e4c8-8136-be3f-e803258d20b1","url":"https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1","name":"E2E Павел Двуспотов R05-0924_1a1","spot_id":"397c8889-e4c8-8118-ac1b-e5efbe7f83f2","spot_url":"https://app.notion.com/p/Java-397c8889e4c88118ac1be5efbe7f83f2","candidate_email":"","project_or_spot":"Java-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""}],"capability":"<capability>","expires_at":"2026-09-24T02:40:37.690794+00:00"}],"count":1}}
```

</details>

**Мила:**

> Найдена 1 новая запись — собеседование с Павлом Двуспотовым. В карточке указаны два проекта, нужно выбрать:
> 
> 1. **Python-разработчик @Т-банк** — рекомендую этот вариант: в названии записи есть «E2E», но других признаков роли нет.  
> 2. **Java-разработчик @Т-банк**
> 
> Ответьте, например: **1 — Python** или **1 — Java**.

**Судья:** 9/12 — Команды выбраны верно и работа доведена до вопроса за один ход, но Мила безосновательно рекомендует один из спотов вместо нейтральной постановки вопроса и не приводит ссылки Notion.

## Ход 2 (40 с)

**Рекрутер:**

> По джаве

**Команды:**

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_050546_Собеседование (E2E Павел Двуспотов R05-0924_1a1).webm — у карточки несколько проектов (📍 Spots), нужно выбрать один\n   1) E2E Павел Двуспотов R05-0924_1a1 — 📍 Spots: Python-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1\n   2) E2E Павел Двуспотов R05-0924_1a1 — 📍 Spots: Java-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1","result":{"items":[{"question_id":"249831de-b357-4407-afc9-8e3fd9b386a6","question_set_id":"50bdbd26-aae9-4fa2-bede-72558a5dc5d9","recording_id":"df2feb8e-850b-4258-a1ad-acc129254f5a","recording_version":0,"filename":"2026-09-24_050546_Собеседование (E2E Павел Двуспотов R05-0924_1a1).webm","reason":"multiple_spots","choices":[{"id":"3e5c8889-e4c8-8136-be3f-e803258d20b1","url":"https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1","name":"E2E Павел Двуспотов R05-0924_1a1","spot_id":"397c8889-e4c8-81d7-8bcb-f77c42da96e8","spot_url":"https://app.notion.com/p/Python-397c8889e4c881d78bcbf77c42da96e8","candidate_email":"","project_or_spot":"Python-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""},{"id":"3e5c8889-e4c8-8136-be3f-e803258d20b1","url":"https://app.notion.com/p/E2E-R05-0924_1a1-3e5c8889e4c88136be3fe803258d20b1","name":"E2E Павел Двуспотов R05-0924_1a1","spot_id":"397c8889-e4c8-8118-ac1b-e5efbe7f83f2","spot_url":"https://app.notion.com/p/Java-397c8889e4c88118ac1be5efbe7f83f2","candidate_email":"","project_or_spot":"Java-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""}],"capability":"<capability>","expires_at":"2026-09-24T02:40:37.690794+00:00"}],"count":1}}
```

</details>

```text
python3 scripts/recording_agent.py answer --help
```

<details><summary>ответ</summary>

```text
usage: recording_agent.py answer [-h] --recruiter-user-id RECRUITER_USER_ID
                                 --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
                                 --actions-json ACTIONS_JSON

options:
  -h, --help            show this help message and exit
  --recruiter-user-id RECRUITER_USER_ID
  --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
  --actions-json ACTIONS_JSON
```

</details>

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/references/contract.md", "offset": 1, "limit": 260}
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
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '{"question_id":"249831de-b357-4407-afc9-8e3fd9b386a6","question_set_id":"50bdbd26-aae9-4fa2-bede-72558a5dc5d9","action":"resolve","choice":2,"capability":"<capability>","expected_version":0,"idempotency_key":"9cb17c1c-a981-6b5b-8f01-b7f284500002"}'
```

<details><summary>ответ</summary>

```text
{"ok":false,"message":"Не удалось выполнить запрос Recording Agent: Question actions must contain 1..50 items","error":"Question actions must contain 1..50 items"}

(Command exited with code 1)
```

</details>

```text
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"249831de-b357-4407-afc9-8e3fd9b386a6","question_set_id":"50bdbd26-aae9-4fa2-bede-72558a5dc5d9","action":"resolve","choice":2,"capability":"<capability>","expected_version":0,"idempotency_key":"9cb17c1c-a981-6b5b-8f01-b7f284500002"}]'
```

<details><summary>ответ</summary>

```text
{"ok":false,"message":"Не удалось выполнить запрос Recording Agent: Backend returned invalid JSON (HTTP 500)","error":"Backend returned invalid JSON (HTTP 500)"}

(Command exited with code 1)
```

</details>

**Мила:**

> Поняла: выбираю вариант **Java-разработчик @Т-банк**. Но Backend сейчас вернул техническую ошибку при сохранении выбора. Повторить обработку можно после восстановления сервиса — запись остаётся в безопасности и ждёт уточнения.

**Судья:** 9/12 — Сопоставление с Java-спотом верное, но ход не доведён: ошибка формата JSON, лишние обращения к help/contract, нет destinations и route-interview.

