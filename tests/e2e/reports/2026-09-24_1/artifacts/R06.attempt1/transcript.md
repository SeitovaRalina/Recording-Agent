# R06 — стенограмма

## Ход 1 (39 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 486905bc-c61f-4d92-7dbb-f60fc3700000
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 3.\nОбнаружено файлов для проверки: 17.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 3.\nТребуют вашего уточнения: 3.\n- 2026-09-24_052905_Собеседование (E2E Анна Безссылкина R06-0924_1a1).webm; новая запись; нужно уточнение: недостаточно уверенное совпадение с событием календаря\n- 2026-09-24_053218_Собеседование (E2E Борис Бессобытийный R06-0924_1a1).webm; новая запись; нужно уточнение: подходящее событие календаря не найдено\n- 2026-09-24_053524_Собеседование (E2E Вера Двойная R06-0924_1a1).webm; новая запись; нужно уточнение: найдено несколько подходящих событий календаря\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":17,"inserted":3,"skipped_legacy":14,"matched":0,"manual_review":3,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":3,"items_truncated":false,"items":[{"id":"a1bf7bdc-2157-4b0f-843e-f65e4eef6242","filename":"2026-09-24_052905_Собеседование (E2E Анна Безссылкина R06-0924_1a1).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"low_confidence","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null},{"id":"1f91ad95-1983-44a5-aa19-01eee4c6ec17","filename":"2026-09-24_053218_Собеседование (E2E Борис Бессобытийный R06-0924_1a1).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"no_compatible_event","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null},{"id":"4ea17ff5-75c5-49c9-b4b7-d74f7ce81c60","filename":"2026-09-24_053524_Собеседование (E2E Вера Двойная R06-0924_1a1).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"multiple_eligible_events","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null}]}}
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 3.\n1. 2026-09-24_052905_Собеседование (E2E Анна Безссылкина R06-0924_1a1).webm — недостаточно уверенное совпадение с событием календаря\n   1) option\n2. 2026-09-24_053218_Собеседование (E2E Борис Бессобытийный R06-0924_1a1).webm — подходящее событие календаря не найдено\n3. 2026-09-24_053524_Собеседование (E2E Вера Двойная R06-0924_1a1).webm — найдено несколько подходящих событий календаря\n   1) option\n   2) option","result":{"items":[{"question_id":"3ac26dc3-c808-46dd-b960-c5940458cc99","question_set_id":"1c1b04dd-14dd-40a9-869c-77ef45204d04","recording_id":"a1bf7bdc-2157-4b0f-843e-f65e4eef6242","recording_version":0,"filename":"2026-09-24_052905_Собеседование (E2E Анна Безссылкина R06-0924_1a1).webm","reason":"low_confidence","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-14baa706ebab","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Анна Безссылкина R06-0924_1a1)","event_start_utc":"2026-09-24T02:28:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:04:12.277276+00:00"},{"question_id":"a00f8497-7b40-4cfc-ae14-ec766427f747","question_set_id":"f3ed6475-d4d9-496b-97ef-e2e46cd0eb33","recording_id":"1f91ad95-1983-44a5-aa19-01eee4c6ec17","recording_version":0,"filename":"2026-09-24_053218_Собеседование (E2E Борис Бессобытийный R06-0924_1a1).webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:04:12.307627+00:00"},{"question_id":"e1dd763b-6e9d-4a19-99ba-5ac4b47b3a1d","question_set_id":"4260c5fd-4d68-454e-860d-2db706091f45","recording_id":"4ea17ff5-75c5-49c9-b4b7-d74f7ce81c60","recording_version":0,"filename":"2026-09-24_053524_Собеседование (E2E Вера Двойная R06-0924_1a1).webm","reason":"multiple_eligible_events","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-7ecb2aceb3b8","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a1)","event_start_utc":"2026-09-24T02:34:00+00:00","calendar_display_name":"Recording Agent Test"},{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-f591c8061007","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a1)","event_start_utc":"2026-09-24T02:34:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:04:12.244453+00:00"}],"count":3}}
```

</details>

**Мила:**

> Проверка завершена: добавлено **3 новые записи**. Всего найдено 17 файлов, 14 старых записей пропущены.
> 
> Нужно уточнить:
> 
> 1. **Анна Безссылкина** — найдено одно подходящее событие, но совпадение недостаточно уверенное. Рекомендую подтвердить его: `1 — 1`.
> 2. **Борис Бессобытийный** — подходящего события в календаре не найдено. Уточните, пожалуйста, с каким кандидатом/событием связать запись.
> 3. **Вера Двойная** — найдены два одинаковых подходящих события на 02:34. Выберите: `3 — 1` или `3 — 2`.
> 
> Можно ответить, например: `1 — 1, 3 — 1`; по Борису напишите кандидата или данные нужного события.

**Судья:** 12/12 — Идеальный ход: scan + questions, один сводный ответ с тремя нумерованными вопросами, рекомендациями и примером ответа, без утечек capability/ID и без лишних мутаций.

## Ход 2 (82 с)

**Рекрутер:**

> 1 — да, это то самое событие. 2 — это не собеседование, пропусти. 3 — любое из двух, они одинаковые

**Команды:**

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/SKILL.md", "offset": 240, "limit": 150}
```

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 3.\n1. 2026-09-24_052905_Собеседование (E2E Анна Безссылкина R06-0924_1a1).webm — недостаточно уверенное совпадение с событием календаря\n   1) option\n2. 2026-09-24_053218_Собеседование (E2E Борис Бессобытийный R06-0924_1a1).webm — подходящее событие календаря не найдено\n3. 2026-09-24_053524_Собеседование (E2E Вера Двойная R06-0924_1a1).webm — найдено несколько подходящих событий календаря\n   1) option\n   2) option","result":{"items":[{"question_id":"3ac26dc3-c808-46dd-b960-c5940458cc99","question_set_id":"1c1b04dd-14dd-40a9-869c-77ef45204d04","recording_id":"a1bf7bdc-2157-4b0f-843e-f65e4eef6242","recording_version":0,"filename":"2026-09-24_052905_Собеседование (E2E Анна Безссылкина R06-0924_1a1).webm","reason":"low_confidence","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-14baa706ebab","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Анна Безссылкина R06-0924_1a1)","event_start_utc":"2026-09-24T02:28:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:04:12.277276+00:00"},{"question_id":"a00f8497-7b40-4cfc-ae14-ec766427f747","question_set_id":"f3ed6475-d4d9-496b-97ef-e2e46cd0eb33","recording_id":"1f91ad95-1983-44a5-aa19-01eee4c6ec17","recording_version":0,"filename":"2026-09-24_053218_Собеседование (E2E Борис Бессобытийный R06-0924_1a1).webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:04:12.307627+00:00"},{"question_id":"e1dd763b-6e9d-4a19-99ba-5ac4b47b3a1d","question_set_id":"4260c5fd-4d68-454e-860d-2db706091f45","recording_id":"4ea17ff5-75c5-49c9-b4b7-d74f7ce81c60","recording_version":0,"filename":"2026-09-24_053524_Собеседование (E2E Вера Двойная R06-0924_1a1).webm","reason":"multiple_eligible_events","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-7ecb2aceb3b8","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a1)","event_start_utc":"2026-09-24T02:34:00+00:00","calendar_display_name":"Recording Agent Test"},{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-f591c8061007","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a1)","event_start_utc":"2026-09-24T02:34:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:04:12.244453+00:00"}],"count":3}}
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
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"3ac26dc3-c808-46dd-b960-c5940458cc99","question_set_id":"1c1b04dd-14dd-40a9-869c-77ef45204d04","action":"resolve","capability":"<capability>","expected_version":0,"idempotency_key":"c983924e-5013-44d8-b5fb-2d5ef8093780","choice":1},{"question_id":"a00f8497-7b40-4cfc-ae14-ec766427f747","question_set_id":"f3ed6475-d4d9-496b-97ef-e2e46cd0eb33","action":"ignore","capability":"<capability>","expected_version":0,"idempotency_key":"6bd4343f-9fb1-4661-b29f-1e48007a5696"},{"question_id":"e1dd763b-6e9d-4a19-99ba-5ac4b47b3a1d","question_set_id":"4260c5fd-4d68-454e-860d-2db706091f45","action":"resolve","capability":"<capability>","expected_version":0,"idempotency_key":"81be5dfd-7b45-4cb6-b99f-686fc9c9d095","choice":1}]'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Принято ответов: 3; отклонено: 0; ещё ждут ответа: 0.\nОбработка по принятым ответам запущена.","result":{"accepted":[{"question_id":"3ac26dc3-c808-46dd-b960-c5940458cc99","recording_id":"a1bf7bdc-2157-4b0f-843e-f65e4eef6242","status":"calendar_event_found","version":1,"replayed":false},{"question_id":"a00f8497-7b40-4cfc-ae14-ec766427f747","recording_id":"1f91ad95-1983-44a5-aa19-01eee4c6ec17","status":"ignored","version":1,"replayed":false},{"question_id":"e1dd763b-6e9d-4a19-99ba-5ac4b47b3a1d","recording_id":"4ea17ff5-75c5-49c9-b4b7-d74f7ce81c60","status":"calendar_event_found","version":1,"replayed":false}],"rejected":[],"pending":[]}}
```

</details>

```text
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено записей: 19.\n- 2026-09-24_053524_Собеседование (E2E Вера Двойная R06-0924_1a1).webm; кандидат: E2E Вера Двойная R06-0924_1a1; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Вера_Двойная_R06-0924_1a1_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c88127aa37fcecaf1bc03d\n- 2026-09-24_053218_Собеседование (E2E Борис Бессобытийный R06-0924_1a1).webm; статус: запись проигнорирована\n- 2026-09-24_052905_Собеседование (E2E Анна Безссылкина R06-0924_1a1).webm; кандидат: E2E Анна Безссылкина R06-0924_1a1; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Анна_Безссылкина_R06-0924_1a1_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c881de8dabf30b7148afd5\n- 2026-09-24_052301_Собеседование (E2E Павел Двуспотов R05-0924_1a2).webm; кандидат: E2E Павел Двуспотов R05-0924_1a2; проект: Java-разработчик @Т-банк; статус: запись проигнорирована; имя в хранилище: 2026-09-24_E2E_Павел_Двуспотов_R05-0924_1a2_Java-разработчик_@Т-банк_general_interview.webm; ошибка: Interview destination must be selected from allowed Synology inventory; карточка Notion: https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602\n- 2026-09-24_051938_Собеседование (E2E Ирина Лебедева R04-0924_1a2).webm; кандидат: E2E Ирина Лебедева R04-0924_1a2; проект: Java-разработчик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Ирина_Лебедева_R04-0924_1a2_Java-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R04-0924_1a2-3e5c8889e4c881c5b91ed6b2df454b06; запись: https://gofile.me/7g8zN/akP5BNyfv\n- 2026-09-24_051607_Собеседование (E2E Денис Дизайнов R03-0924_1a2).webm; кандидат: E2E Денис Дизайнов R03-0924_1a2; проект: Discovery @Дизайн машина; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Денис_Дизайнов_R03-0924_1a2_Discovery_@Дизайн_машина_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R03-0924_1a2-3e5c8889e4c8811cb971f9382f9c2da9; запись: https://gofile.me/7g8zN/RpZ0MKmc4\n- 2026-09-24_051248_Собеседование (E2E Марина Аналитикова R02-0924_1a2).webm; кандидат: E2E Марина Аналитикова R02-0924_1a2; проект: Бизнес-аналитик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Марина_Аналитикова_R02-0924_1a2_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R02-0924_1a2-3e5c8889e4c8810e8384c83b38d0f2d0; запись: https://gofile.me/7g8zN/WqOgMKAmI\n- 2026-09-24_050546_Собеседование (E2E Павел Двуспотов R05-0924_1a1).webm; статус: запись проигнорирована\n- 2026-09-24_045942_Собеседование (E2E Ирина Лебедева R04-0924_1a1).webm; статус: запись проигнорирована\n- 2026-09-24_045436_Собеседование (E2E Денис Дизайнов R03-0924_1a1)
```

</details>

```text
python3 scripts/recording_agent.py destinations --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Доступные папки в Synology: 52.\n1. /home/Recruiting-NE/2. Interviews\n2. /home/Recruiting-NE/2. Interviews/BizDev\n3. /home/Recruiting-NE/2. Interviews/Delivery Manager\n4. /home/Recruiting-NE/2. Interviews/DevFest 2025 (оргсостав)\n5. /home/Recruiting-NE/2. Interviews/Labs 2025 (оргсостав)\n6. /home/Recruiting-NE/2. Interviews/Outreach Manager\n7. /home/Recruiting-NE/2. Interviews/Revenue Manager\n8. /home/Recruiting-NE/2. Interviews/Администратор Академии\n9. /home/Recruiting-NE/2. Interviews/Ассистент в отдел продаж\n10. /home/Recruiting-NE/2. Interviews/Бизнес ассистент\n11. /home/Recruiting-NE/2. Interviews/Бухгалтер в единственном лице\n12. /home/Recruiting-NE/2. Interviews/Волонтёры DevFest\n13. /home/Recruiting-NE/2. Interviews/Дизайнер\n14. /home/Recruiting-NE/2. Interviews/ИТ_рекрутер\n15. /home/Recruiting-NE/2. Interviews/ИТ_ресечер\n16. /home/Recruiting-NE/2. Interviews/Коммерский директор\n17. /home/Recruiting-NE/2. Interviews/Копирайтер\n18. /home/Recruiting-NE/2. Interviews/Менеджер по персоналу\n19. /home/Recruiting-NE/2. Interviews/Менеджер по продажам\n20. /home/Recruiting-NE/2. Interviews/Менеджер проектов\n21. /home/Recruiting-NE/2. Interviews/Офис-менеджер\n22. /home/Recruiting-NE/2. Interviews/Руководитель отдела продаж\n23. /home/Recruiting-NE/2. Interviews/СЕО Ventures\n24. /home/Recruiting-NE/2. Interviews/Системный Администратор\n25. /home/Recruiting-NE/2. Interviews/Специалист по договорам и оплатам\n26. /home/Recruiting-NE/2. Interviews/Специалист по кадрам\n27. /home/Recruiting-E/2. Interviews external\n28. /home/Recruiting-E/2. Interviews external/Aldo\n29. /home/Recruiting-E/2. Interviews external/Analyst\n30. /home/Recruiting-E/2. Interviews external/Android\n31. /home/Recruiting-E/2. Interviews external/Backend\n32. /home/Recruiting-E/2. Interviews external/E2E Discovery\n33. /home/Recruiting-E/2. Interviews external/Flutter\n34. /home/Recruiting-E/2. Interviews external/Frontend\n35. /home/Recruiting-E/2. Interviews external/Fullstack\n36. /home/Recruiting-E/2. Interviews external/IOS\n37. /home/Recruiting-E/2. Interviews external/Python\n38. /home/Recruiting-E/2. Interviews external/QA\n39. /home/Recruiting-E/2. Interviews external/Support Engineer\n40. /home/Recruiting-E/2. Interviews external/Обмен записями с Recruiting-NB\n41. /home/Recruiting-E/2. Interviews external/Aldo/2022\n42. /home/Recruiting-E/2. Interviews external/IOS/Veriflix + Heramed, iOS Dev, Sep '22\n43. /home/Recruiting-E/3. Interviews internal\n44. /home/Recruiting-E/3. Interviews internal/Analyst\n45. /home/Recruiting-E/3. Interviews internal/Android\n46. /home/Recruiting-E/3. Interviews internal/DevOps\n47. /home/Recruiting-E/3. Interviews internal/Flutter\n48. /home/Recruiting-E/3. Interviews internal/iOS\n49. /home/Recruiting-E/3. Interviews internal/QA manual\n50. /home/Recruiting-E/3. Interviews internal/Uncategorised\n51. /home/Recruiting-E/3. Interviews internal/Web\n52. /home/Recruiting-E/3. Interviews internal
```

</details>

```text
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id a1bf7bdc-2157-4b0f-843e-f65e4eef6242 --destination-id ce009880-84e7-48b7-8bc4-5351f716ff25 --expected-version 2 --idempotency-key e185df56-e73e-4f75-8f3c-adc23d5ec3f5
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Анна Безссылкина R06-0924_1a1) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c881de8dabf30b7148afd5\nЗапись: https://gofile.me/7g8zN/IJRkNsZrz","result":{"recording_id":"a1bf7bdc-2157-4b0f-843e-f65e4eef6242","status":"completed","version":3,"safe_link":"https://gofile.me/7g8zN/IJRkNsZrz","notion_url":"https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c881de8dabf30b7148afd5","candidate_name":"E2E Анна Безссылкина R06-0924_1a1","replayed":false}}
```

</details>

```text
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 4ea17ff5-75c5-49c9-b4b7-d74f7ce81c60 --destination-id ce009880-84e7-48b7-8bc4-5351f716ff25 --expected-version 2 --idempotency-key 2ea8351b-50ac-4bf6-b40d-e3d998c4898a
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Вера Двойная R06-0924_1a1) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c88127aa37fcecaf1bc03d\nЗапись: https://gofile.me/7g8zN/Wy7kBYY0p","result":{"recording_id":"4ea17ff5-75c5-49c9-b4b7-d74f7ce81c60","status":"completed","version":3,"safe_link":"https://gofile.me/7g8zN/Wy7kBYY0p","notion_url":"https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c88127aa37fcecaf1bc03d","candidate_name":"E2E Вера Двойная R06-0924_1a1","replayed":false}}
```

</details>

**Мила:**

> Приняла все 3 ответа: 2 записи обработаны, 1 пропущена как несобеседование.
> 
> - **Анна Безссылкина** — запись сохранена: [Notion](https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c881de8dabf30b7148afd5) · [запись](https://gofile.me/7g8zN/IJRkNsZrz)
> - **Вера Двойная** — запись сохранена: [Notion](https://app.notion.com/p/E2E-R06-0924_1a1-3e5c8889e4c88127aa37fcecaf1bc03d) · [запись](https://gofile.me/7g8zN/Wy7kBYY0p)
> - **Борис Бессобытийный** — запись пропущена.

**Судья:** 12/12 — Мила корректно обработала все три ответа одним ходом: questions → answer с тремя действиями (resolve/ignore/resolve), затем доводит Анну и Веру до сохранения через route-interview с однозначной папкой Python, и сообщает итог со ссылками на Notion и запись.

