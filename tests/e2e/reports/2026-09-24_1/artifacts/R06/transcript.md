# R06 — стенограмма

## Ход 1 (42 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 644972da-8120-4a1f-9a6c-7a76629e97a4
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 3.\nОбнаружено файлов для проверки: 17.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 3.\nТребуют вашего уточнения: 3.\n- 2026-09-24_061517_Собеседование (E2E Анна Безссылкина R06-0924_1a2).webm; новая запись; нужно уточнение: недостаточно уверенное совпадение с событием календаря\n- 2026-09-24_061849_Собеседование (E2E Борис Бессобытийный R06-0924_1a2).webm; новая запись; нужно уточнение: подходящее событие календаря не найдено\n- 2026-09-24_062155_Собеседование (E2E Вера Двойная R06-0924_1a2).webm; новая запись; нужно уточнение: найдено несколько подходящих событий календаря\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":17,"inserted":3,"skipped_legacy":14,"matched":0,"manual_review":3,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":3,"items_truncated":false,"items":[{"id":"ba1f86b1-355c-402c-9d52-d3a3cf7085c2","filename":"2026-09-24_061517_Собеседование (E2E Анна Безссылкина R06-0924_1a2).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"low_confidence","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null},{"id":"15a77e66-e7a6-41ea-9a75-e1526c16a94b","filename":"2026-09-24_061849_Собеседование (E2E Борис Бессобытийный R06-0924_1a2).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"no_compatible_event","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null},{"id":"a60b79d0-0afa-47bf-93c5-ce086a8db7fe","filename":"2026-09-24_062155_Собеседование (E2E Вера Двойная R06-0924_1a2).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"multiple_eligible_events","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null}]}}
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 3.\n1. 2026-09-24_061517_Собеседование (E2E Анна Безссылкина R06-0924_1a2).webm — недостаточно уверенное совпадение с событием календаря\n   1) option\n2. 2026-09-24_062155_Собеседование (E2E Вера Двойная R06-0924_1a2).webm — найдено несколько подходящих событий календаря\n   1) option\n   2) option\n3. 2026-09-24_061849_Собеседование (E2E Борис Бессобытийный R06-0924_1a2).webm — подходящее событие календаря не найдено","result":{"items":[{"question_id":"1c643fb9-5282-458c-ad6a-94476bd18e3e","question_set_id":"d14ce95a-b8e4-44c1-8722-ef7c02b59509","recording_id":"ba1f86b1-355c-402c-9d52-d3a3cf7085c2","recording_version":0,"filename":"2026-09-24_061517_Собеседование (E2E Анна Безссылкина R06-0924_1a2).webm","reason":"low_confidence","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-a2-888a6633c2ce","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Анна Безссылкина R06-0924_1a2)","event_start_utc":"2026-09-24T03:14:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:50:48.238904+00:00"},{"question_id":"20ec6ae2-a820-4738-9328-070c1168a004","question_set_id":"712167f4-3e06-4bdf-9efb-50000f7b28b3","recording_id":"a60b79d0-0afa-47bf-93c5-ce086a8db7fe","recording_version":0,"filename":"2026-09-24_062155_Собеседование (E2E Вера Двойная R06-0924_1a2).webm","reason":"multiple_eligible_events","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-a2-7e804121a37d","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a2)","event_start_utc":"2026-09-24T03:20:00+00:00","calendar_display_name":"Recording Agent Test"},{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-a2-3313d72d5451","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a2)","event_start_utc":"2026-09-24T03:20:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:50:48.303372+00:00"},{"question_id":"63ed4621-8e29-4a62-b6c9-038a46b58b2d","question_set_id":"259e231c-2234-40ad-b56c-576d9c5dbb18","recording_id":"15a77e66-e7a6-41ea-9a75-e1526c16a94b","recording_version":0,"filename":"2026-09-24_061849_Собеседование (E2E Борис Бессобытийный R06-0924_1a2).webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:50:48.271997+00:00"}],"count":3}}
```

</details>

**Мила:**

> Найдено **3 новые записи** — все требуют уточнения по календарю:
> 
> 1. **Анна Безссылкина** — есть одно вероятное событие «Собеседование (E2E Анна Безссылкина R06-0924_1a2)».  
>    Рекомендую подтвердить его: `1 — 1`
> 
> 2. **Вера Двойная** — найдены два одинаково подходящих события с одинаковым названием и временем.  
>    Выберите нужное: `2 — 1` или `2 — 2`
> 
> 3. **Борис Бессобытийный** — подходящего события в календаре не найдено.  
>    Нужны ваши указания, что делать с этой записью.
> 
> Например, можно ответить: `1 — 1, 2 — 1; по Борису — …`

**Судья:** 12/12 — Корректный ход: scan и questions в правильном порядке, ответ одним сообщением с тремя вопросами, рекомендациями и примером формата ответа; без мутаций и утечек данных.

## Ход 2 (86 с)

**Рекрутер:**

> 1 — да, это то самое событие. 2 — это не собеседование, пропусти. 3 — любое из двух, они одинаковые

**Команды:**

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
{"ok":true,"message":"Открытых вопросов по записям: 3.\n1. 2026-09-24_061517_Собеседование (E2E Анна Безссылкина R06-0924_1a2).webm — недостаточно уверенное совпадение с событием календаря\n   1) option\n2. 2026-09-24_062155_Собеседование (E2E Вера Двойная R06-0924_1a2).webm — найдено несколько подходящих событий календаря\n   1) option\n   2) option\n3. 2026-09-24_061849_Собеседование (E2E Борис Бессобытийный R06-0924_1a2).webm — подходящее событие календаря не найдено","result":{"items":[{"question_id":"1c643fb9-5282-458c-ad6a-94476bd18e3e","question_set_id":"d14ce95a-b8e4-44c1-8722-ef7c02b59509","recording_id":"ba1f86b1-355c-402c-9d52-d3a3cf7085c2","recording_version":0,"filename":"2026-09-24_061517_Собеседование (E2E Анна Безссылкина R06-0924_1a2).webm","reason":"low_confidence","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-a2-888a6633c2ce","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Анна Безссылкина R06-0924_1a2)","event_start_utc":"2026-09-24T03:14:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:50:48.238904+00:00"},{"question_id":"20ec6ae2-a820-4738-9328-070c1168a004","question_set_id":"712167f4-3e06-4bdf-9efb-50000f7b28b3","recording_id":"a60b79d0-0afa-47bf-93c5-ce086a8db7fe","recording_version":0,"filename":"2026-09-24_062155_Собеседование (E2E Вера Двойная R06-0924_1a2).webm","reason":"multiple_eligible_events","choices":[{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-a2-7e804121a37d","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a2)","event_start_utc":"2026-09-24T03:20:00+00:00","calendar_display_name":"Recording Agent Test"},{"eligible":true,"event_uid":"e2e-2026-09-24-1-r06-a2-3313d72d5451","calendar_id":"a2e3765c-471c-4720-9732-3bde80352309","event_summary":"Собеседование (E2E Вера Двойная R06-0924_1a2)","event_start_utc":"2026-09-24T03:20:00+00:00","calendar_display_name":"Recording Agent Test"}],"capability":"<capability>","expires_at":"2026-09-24T03:50:48.303372+00:00"},{"question_id":"63ed4621-8e29-4a62-b6c9-038a46b58b2d","question_set_id":"259e231c-2234-40ad-b56c-576d9c5dbb18","recording_id":"15a77e66-e7a6-41ea-9a75-e1526c16a94b","recording_version":0,"filename":"2026-09-24_061849_Собеседование (E2E Борис Бессобытийный R06-0924_1a2).webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:50:48.271997+00:00"}],"count":3}}
```

</details>

```text
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"1c643fb9-5282-458c-ad6a-94476bd18e3e","question_set_id":"d14ce95a-b8e4-44c1-8722-ef7c02b59509","action":"resolve","capability":"<capability>","expected_version":0,"idempotency_key":"87c3a1d7-556f-450a-b941-21d160960fb1","choice":1},{"question_id":"63ed4621-8e29-4a62-b6c9-038a46b58b2d","question_set_id":"259e231c-2234-40ad-b56c-576d9c5dbb18","action":"ignore","capability":"<capability>","expected_version":0,"idempotency_key":"2e8dbe30-6cac-4600-8744-ed9d7a8cf04d"},{"question_id":"20ec6ae2-a820-4738-9328-070c1168a004","question_set_id":"712167f4-3e06-4bdf-9efb-50000f7b28b3","action":"resolve","capability":"<capability>","expected_version":0,"idempotency_key":"a5bbf349-ca04-4e16-945c-05940d3cac6b","choice":1}]'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Принято ответов: 3; отклонено: 0; ещё ждут ответа: 0.\nОбработка по принятым ответам запущена.","result":{"accepted":[{"question_id":"1c643fb9-5282-458c-ad6a-94476bd18e3e","recording_id":"ba1f86b1-355c-402c-9d52-d3a3cf7085c2","status":"calendar_event_found","version":1,"replayed":false},{"question_id":"63ed4621-8e29-4a62-b6c9-038a46b58b2d","recording_id":"15a77e66-e7a6-41ea-9a75-e1526c16a94b","status":"ignored","version":1,"replayed":false},{"question_id":"20ec6ae2-a820-4738-9328-070c1168a004","recording_id":"a60b79d0-0afa-47bf-93c5-ce086a8db7fe","status":"calendar_event_found","version":1,"replayed":false}],"rejected":[],"pending":[]}}
```

</details>

```text
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено записей: 20.\n- 2026-09-24_062155_Собеседование (E2E Вера Двойная R06-0924_1a2).webm; кандидат: E2E Вера Двойная R06-0924_1a2; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Вера_Двойная_R06-0924_1a2_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881b3a07cef024feadac1\n- 2026-09-24_061849_Собеседование (E2E Борис Бессобытийный R06-0924_1a2).webm; статус: запись проигнорирована\n- 2026-09-24_061517_Собеседование (E2E Анна Безссылкина R06-0924_1a2).webm; кандидат: E2E Анна Безссылкина R06-0924_1a2; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Анна_Безссылкина_R06-0924_1a2_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881fea8d8f4c6ca43f0f8\n- 2026-09-24_061208_Собеседование (E2E Павел Двуспотов R05-0924_1a3).webm; кандидат: E2E Павел Двуспотов R05-0924_1a3; проект: Java-разработчик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Павел_Двуспотов_R05-0924_1a3_Java-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R05-0924_1a3-3e5c8889e4c881bdb3e2e61248274c94; запись: https://gofile.me/7g8zN/s1FGA3lcU\n- 2026-09-24_060805_Собеседование (E2E Денис Дизайнов R03-0924_1a3).webm; кандидат: E2E Денис Дизайнов R03-0924_1a3; проект: Discovery @Дизайн машина; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Денис_Дизайнов_R03-0924_1a3_Discovery_@Дизайн_машина_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R03-0924_1a3-3e5c8889e4c881db81b2d8492d1747c7; запись: https://gofile.me/7g8zN/3zpBo3xK3\n- 2026-09-24_060503_Собеседование (E2E Марина Аналитикова R02-0924_1a3).webm; кандидат: E2E Марина Аналитикова R02-0924_1a3; проект: Бизнес-аналитик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Марина_Аналитикова_R02-0924_1a3_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R02-0924_1a3-3e5c8889e4c881ee94c9e7da2ef30b98; запись: https://gofile.me/7g8zN/htq6q0RWM\n- 2026-09-24_055056_Собеседование (E2E Зоя Переносова R10-0924_1a1).webm; кандидат: E2E Зоя Переносова R10-0924_1a1; проект: Python-разработчик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Зоя_Переносова_R10-0924_1a1_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R10-0924_1a1-3e5c8889e4c8814a9f20da4b0e18223e; запись: https://gofile.me/7g8zN/Kowdxeq4P\n- 2026-09-24_054427_Собеседование (E2E Жанна Повторова R09-0924_1a1).webm; кандидат: E2E Жанна Повторова R09-0924_1a1; проект: Бизнес-аналитик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Жанна_Повторова_R09-0924_1a1_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://a
```

</details>

```text
python3 scripts/recording_agent.py destinations --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Доступные папки в Synology: 52.\n1. /home/Recruiting-NE/2. Interviews\n2. /home/Recruiting-NE/2. Interviews/BizDev\n3. /home/Recruiting-NE/2. Interviews/Delivery Manager\n4. /home/Recruiting-NE/2. Interviews/DevFest 2025 (оргсостав)\n5. /home/Recruiting-NE/2. Interviews/Labs 2025 (оргсостав)\n6. /home/Recruiting-NE/2. Interviews/Outreach Manager\n7. /home/Recruiting-NE/2. Interviews/Revenue Manager\n8. /home/Recruiting-NE/2. Interviews/Администратор Академии\n9. /home/Recruiting-NE/2. Interviews/Ассистент в отдел продаж\n10. /home/Recruiting-NE/2. Interviews/Бизнес ассистент\n11. /home/Recruiting-NE/2. Interviews/Бухгалтер в единственном лице\n12. /home/Recruiting-NE/2. Interviews/Волонтёры DevFest\n13. /home/Recruiting-NE/2. Interviews/Дизайнер\n14. /home/Recruiting-NE/2. Interviews/ИТ_рекрутер\n15. /home/Recruiting-NE/2. Interviews/ИТ_ресечер\n16. /home/Recruiting-NE/2. Interviews/Коммерский директор\n17. /home/Recruiting-NE/2. Interviews/Копирайтер\n18. /home/Recruiting-NE/2. Interviews/Менеджер по персоналу\n19. /home/Recruiting-NE/2. Interviews/Менеджер по продажам\n20. /home/Recruiting-NE/2. Interviews/Менеджер проектов\n21. /home/Recruiting-NE/2. Interviews/Офис-менеджер\n22. /home/Recruiting-NE/2. Interviews/Руководитель отдела продаж\n23. /home/Recruiting-NE/2. Interviews/СЕО Ventures\n24. /home/Recruiting-NE/2. Interviews/Системный Администратор\n25. /home/Recruiting-NE/2. Interviews/Специалист по договорам и оплатам\n26. /home/Recruiting-NE/2. Interviews/Специалист по кадрам\n27. /home/Recruiting-E/2. Interviews external\n28. /home/Recruiting-E/2. Interviews external/Aldo\n29. /home/Recruiting-E/2. Interviews external/Analyst\n30. /home/Recruiting-E/2. Interviews external/Android\n31. /home/Recruiting-E/2. Interviews external/Backend\n32. /home/Recruiting-E/2. Interviews external/E2E Discovery R03-0924_1a3\n33. /home/Recruiting-E/2. Interviews external/Flutter\n34. /home/Recruiting-E/2. Interviews external/Frontend\n35. /home/Recruiting-E/2. Interviews external/Fullstack\n36. /home/Recruiting-E/2. Interviews external/IOS\n37. /home/Recruiting-E/2. Interviews external/Python\n38. /home/Recruiting-E/2. Interviews external/QA\n39. /home/Recruiting-E/2. Interviews external/Support Engineer\n40. /home/Recruiting-E/2. Interviews external/Обмен записями с Recruiting-NB\n41. /home/Recruiting-E/2. Interviews external/Aldo/2022\n42. /home/Recruiting-E/2. Interviews external/IOS/Veriflix + Heramed, iOS Dev, Sep '22\n43. /home/Recruiting-E/3. Interviews internal\n44. /home/Recruiting-E/3. Interviews internal/Analyst\n45. /home/Recruiting-E/3. Interviews internal/Android\n46. /home/Recruiting-E/3. Interviews internal/DevOps\n47. /home/Recruiting-E/3. Interviews internal/Flutter\n48. /home/Recruiting-E/3. Interviews internal/iOS\n49. /home/Recruiting-E/3. Interviews internal/QA manual\n50. /home/Recruiting-E/3. Interviews internal/Uncategorised\n51. /home/Recruiting-E/3. Interviews internal/Web\n52. /home/Recruiting-E/3. Interv
```

</details>

```text
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id ba1f86b1-355c-402c-9d52-d3a3cf7085c2 --destination-id ce009880-84e7-48b7-8bc4-5351f716ff25 --expected-version 2 --idempotency-key 84cc2877-276c-4f42-b8e8-3e598c407758 && python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id a60b79d0-0afa-47bf-93c5-ce086a8db7fe --destination-id ce009880-84e7-48b7-8bc4-5351f716ff25 --expected-version 2 --idempotency-key 1b051034-57a4-4e6f-859e-c153cff88826
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Анна Безссылкина R06-0924_1a2) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881fea8d8f4c6ca43f0f8\nЗапись: https://gofile.me/7g8zN/O7RUSlNRS","result":{"recording_id":"ba1f86b1-355c-402c-9d52-d3a3cf7085c2","status":"completed","version":3,"safe_link":"https://gofile.me/7g8zN/O7RUSlNRS","notion_url":"https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881fea8d8f4c6ca43f0f8","candidate_name":"E2E Анна Безссылкина R06-0924_1a2","replayed":false}}
{"ok":true,"message":"Готово: запись собеседования (E2E Вера Двойная R06-0924_1a2) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881b3a07cef024feadac1\nЗапись: https://gofile.me/7g8zN/1tftD1wch","result":{"recording_id":"a60b79d0-0afa-47bf-93c5-ce086a8db7fe","status":"completed","version":3,"safe_link":"https://gofile.me/7g8zN/1tftD1wch","notion_url":"https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881b3a07cef024feadac1","candidate_name":"E2E Вера Двойная R06-0924_1a2","replayed":false}}
```

</details>

**Мила:**

> Принято 3 ответа, открытых вопросов больше нет.
> 
> - **Анна Безссылкина** — собеседование сохранено в папку Python. [Карточка Notion](https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881fea8d8f4c6ca43f0f8) · [запись](https://gofile.me/7g8zN/O7RUSlNRS)
> - **Вера Двойная** — выбрано первое из одинаковых событий; собеседование сохранено в папку Python. [Карточка Notion](https://app.notion.com/p/E2E-R06-0924_1a2-3e5c8889e4c881b3a07cef024feadac1) · [запись](https://gofile.me/7g8zN/1tftD1wch)
> - **Борис Бессобытийный** — запись отмечена как не являющаяся собеседованием и пропущена.
> 
> Результаты также отображены в карточках Notion.

**Судья:** 12/12 — Корректно обработаны все три ответа за один ход: questions → answer (resolve/ignore/resolve) → destinations → route-interview ×2; итог с ссылками Notion и gofile, без утечек и без лишних вопросов.

