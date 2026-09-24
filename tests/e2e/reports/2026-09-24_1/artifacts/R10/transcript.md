# R10 — стенограмма

## Ход 1 (60 с)

**Рекрутер:**

> Проверь новые записи

**Команды:**

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/SKILL.md", "offset": 1, "limit": 200}
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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key ef5c3dd8-3e0e-4b8e-9bc5-3dd889e8e0e6
```

<details><summary>ответ</summary>

```text
Command still running (session mellow-canyon, pid 1236229). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "mellow-canyon", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": false, "eof": false, "offset": 0, "limit": 0, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_064702_Собеседование (E2E Зоя Переносова R10-0924_1a3).webm; кандидат: E2E Зоя Переносова R10-0924_1a3; новая запись; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Зоя_Переносова_R10-0924_1a3_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"47a1dd37-b05b-413e-9fae-b5d09aeb29c5","filename":"2026-09-24_064702_Собеседование (E2E Зоя Переносова R10-0924_1a3).webm","candidate_name":"E2E Зоя Переносова R10-0924_1a3","status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"storage_destination_required","generated_filename":"2026-09-24_E2E_Зоя_Переносова_R10-0924_1a3_Python-разработчик_@Т-банк_general_interview.webm","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0","spot":"Python-разработчик @Т-банк","error":"Interview destination must be selected from allowed Synology inventory"}]}}

Process exited with code 0.
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
python3 scripts/recording_agent.py route-interview --help
```

<details><summary>ответ</summary>

```text
usage: recording_agent.py route-interview [-h]
                                          --recruiter-user-id RECRUITER_USER_ID
                                          --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
                                          --recording-id RECORDING_ID
                                          --destination-id DESTINATION_ID
                                          --expected-version EXPECTED_VERSION
                                          --idempotency-key IDEMPOTENCY_KEY

options:
  -h, --help            show this help message and exit
  --recruiter-user-id RECRUITER_USER_ID
  --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
  --recording-id RECORDING_ID
  --destination-id DESTINATION_ID
  --expected-version EXPECTED_VERSION
  --idempotency-key IDEMPOTENCY_KEY
```

</details>

```text
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --recording-id 47a1dd37-b05b-413e-9fae-b5d09aeb29c5
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено записей: 1.\n- 2026-09-24_064702_Собеседование (E2E Зоя Переносова R10-0924_1a3).webm; кандидат: E2E Зоя Переносова R10-0924_1a3; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Зоя_Переносова_R10-0924_1a3_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0","result":{"items":[{"id":"47a1dd37-b05b-413e-9fae-b5d09aeb29c5","filename":"2026-09-24_064702_Собеседование (E2E Зоя Переносова R10-0924_1a3).webm","generated_filename":"2026-09-24_E2E_Зоя_Переносова_R10-0924_1a3_Python-разработчик_@Т-банк_general_interview.webm","candidate_name":"E2E Зоя Переносова R10-0924_1a3","status":"manual_review_required","requires_review":true,"review_reason":"storage_destination_required","version":1,"found_at":"2026-09-24T04:07:03.409544+00:00","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0","spot":"Python-разработчик @Т-банк","error":"Interview destination must be selected from allowed Synology inventory"}],"count":1}}
```

</details>

```text
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 47a1dd37-b05b-413e-9fae-b5d09aeb29c5 --destination-id ce009880-84e7-48b7-8bc4-5351f716ff25 --expected-version 1 --idempotency-key ef5c3dd8-3e0e-4b8e-9bc5-3dd889e8e0e7
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Зоя Переносова R10-0924_1a3) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0\nЗапись: https://gofile.me/7g8zN/dg6uv4Hqn","result":{"recording_id":"47a1dd37-b05b-413e-9fae-b5d09aeb29c5","status":"completed","version":2,"safe_link":"https://gofile.me/7g8zN/dg6uv4Hqn","notion_url":"https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0","candidate_name":"E2E Зоя Переносова R10-0924_1a3","replayed":false}}
```

</details>

**Мила:**

> Проверила: найдена 1 новая запись — собеседование с **E2E Зоей Переносовой R10-0924_1a3** на позицию **Python-разработчик @Т-банк**.
> 
> Я сохранила её в папку Python. Результат уже виден в карточке Notion:  
> https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0
> 
> Запись: https://gofile.me/7g8zN/dg6uv4Hqn

**Судья:** 12/12 — Мила корректно выполнила сценарий в одном ходе: scan → destinations → status (для версии) → route-interview → итог со ссылками Notion и GoFile, без лишних вопросов и утечек внутренних идентификаторов.

## Ход 2 (36 с)

**Рекрутер:**

> Перенеси запись E2E Зоя Переносова R10-0924_1a3 во внутренние, в Uncategorised

**Команды:**

```text
python3 scripts/recording_agent.py destinations --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Доступные папки в Synology: 52.\n1. /home/Recruiting-NE/2. Interviews\n2. /home/Recruiting-NE/2. Interviews/BizDev\n3. /home/Recruiting-NE/2. Interviews/Delivery Manager\n4. /home/Recruiting-NE/2. Interviews/DevFest 2025 (оргсостав)\n5. /home/Recruiting-NE/2. Interviews/Labs 2025 (оргсостав)\n6. /home/Recruiting-NE/2. Interviews/Outreach Manager\n7. /home/Recruiting-NE/2. Interviews/Revenue Manager\n8. /home/Recruiting-NE/2. Interviews/Администратор Академии\n9. /home/Recruiting-NE/2. Interviews/Ассистент в отдел продаж\n10. /home/Recruiting-NE/2. Interviews/Бизнес ассистент\n11. /home/Recruiting-NE/2. Interviews/Бухгалтер в единственном лице\n12. /home/Recruiting-NE/2. Interviews/Волонтёры DevFest\n13. /home/Recruiting-NE/2. Interviews/Дизайнер\n14. /home/Recruiting-NE/2. Interviews/ИТ_рекрутер\n15. /home/Recruiting-NE/2. Interviews/ИТ_ресечер\n16. /home/Recruiting-NE/2. Interviews/Коммерский директор\n17. /home/Recruiting-NE/2. Interviews/Копирайтер\n18. /home/Recruiting-NE/2. Interviews/Менеджер по персоналу\n19. /home/Recruiting-NE/2. Interviews/Менеджер по продажам\n20. /home/Recruiting-NE/2. Interviews/Менеджер проектов\n21. /home/Recruiting-NE/2. Interviews/Офис-менеджер\n22. /home/Recruiting-NE/2. Interviews/Руководитель отдела продаж\n23. /home/Recruiting-NE/2. Interviews/СЕО Ventures\n24. /home/Recruiting-NE/2. Interviews/Системный Администратор\n25. /home/Recruiting-NE/2. Interviews/Специалист по договорам и оплатам\n26. /home/Recruiting-NE/2. Interviews/Специалист по кадрам\n27. /home/Recruiting-E/2. Interviews external\n28. /home/Recruiting-E/2. Interviews external/Aldo\n29. /home/Recruiting-E/2. Interviews external/Analyst\n30. /home/Recruiting-E/2. Interviews external/Android\n31. /home/Recruiting-E/2. Interviews external/Backend\n32. /home/Recruiting-E/2. Interviews external/E2E Discovery R03-0924_1a3\n33. /home/Recruiting-E/2. Interviews external/Flutter\n34. /home/Recruiting-E/2. Interviews external/Frontend\n35. /home/Recruiting-E/2. Interviews external/Fullstack\n36. /home/Recruiting-E/2. Interviews external/IOS\n37. /home/Recruiting-E/2. Interviews external/Python\n38. /home/Recruiting-E/2. Interviews external/QA\n39. /home/Recruiting-E/2. Interviews external/Support Engineer\n40. /home/Recruiting-E/2. Interviews external/Обмен записями с Recruiting-NB\n41. /home/Recruiting-E/2. Interviews external/Aldo/2022\n42. /home/Recruiting-E/2. Interviews external/IOS/Veriflix + Heramed, iOS Dev, Sep '22\n43. /home/Recruiting-E/3. Interviews internal\n44. /home/Recruiting-E/3. Interviews internal/Analyst\n45. /home/Recruiting-E/3. Interviews internal/Android\n46. /home/Recruiting-E/3. Interviews internal/DevOps\n47. /home/Recruiting-E/3. Interviews internal/Flutter\n48. /home/Recruiting-E/3. Interviews internal/iOS\n49. /home/Recruiting-E/3. Interviews internal/QA manual\n50. /home/Recruiting-E/3. Interviews internal/Uncategorised\n51. /home/Recruiting-E/3. Interviews internal/Web\n52. /home/Recruiting-E/3. Interv
```

</details>

```text
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --candidate 'E2E Зоя Переносова R10-0924_1a3' && python3 scripts/recording_agent.py reroute-recording --help
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено записей: 1.\n- 2026-09-24_064702_Собеседование (E2E Зоя Переносова R10-0924_1a3).webm; кандидат: E2E Зоя Переносова R10-0924_1a3; проект: Python-разработчик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Зоя_Переносова_R10-0924_1a3_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0; запись: https://gofile.me/7g8zN/dg6uv4Hqn","result":{"items":[{"id":"47a1dd37-b05b-413e-9fae-b5d09aeb29c5","filename":"2026-09-24_064702_Собеседование (E2E Зоя Переносова R10-0924_1a3).webm","generated_filename":"2026-09-24_E2E_Зоя_Переносова_R10-0924_1a3_Python-разработчик_@Т-банк_general_interview.webm","candidate_name":"E2E Зоя Переносова R10-0924_1a3","status":"completed","requires_review":false,"review_reason":"storage_destination_required","version":2,"found_at":"2026-09-24T04:07:03.409544+00:00","safe_link":"https://gofile.me/7g8zN/dg6uv4Hqn","notion_url":"https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c8818ea9e1fa9d8f3796c0","spot":"Python-разработчик @Т-банк","error":null}],"count":1}}
usage: recording_agent.py reroute-recording [-h]
                                            --recruiter-user-id RECRUITER_USER_ID
                                            --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
                                            --recording-id RECORDING_ID
                                            --destination-id DESTINATION_ID
                                            --expected-version EXPECTED_VERSION
                                            --idempotency-key IDEMPOTENCY_KEY

options:
  -h, --help            show this help message and exit
  --recruiter-user-id RECRUITER_USER_ID
  --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
  --recording-id RECORDING_ID
  --destination-id DESTINATION_ID
  --expected-version EXPECTED_VERSION
  --idempotency-key IDEMPOTENCY_KEY
```

</details>

```text
python3 scripts/recording_agent.py reroute-recording --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 47a1dd37-b05b-413e-9fae-b5d09aeb29c5 --destination-id b57a02b0-36d1-4436-89db-7932f2aa035a --expected-version 2 --idempotency-key 519bcb67-bcdd-405a-86f3-5e6c79e0fb68
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Запись перенесена. Новая ссылка: https://gofile.me/7g8zN/Uo4EB6ISC.","result":{"recording_id":"47a1dd37-b05b-413e-9fae-b5d09aeb29c5","version":3,"safe_link":"https://gofile.me/7g8zN/Uo4EB6ISC","replayed":false}}
```

</details>

**Мила:**

> Готово — запись перенесена во внутренние, в **Uncategorised**. Новая ссылка:  
> https://gofile.me/7g8zN/Uo4EB6ISC

**Судья:** 12/12 — Корректный ход: вызваны status, destinations и reroute-recording с правильными параметрами (expected-version=2), запись перенесена в internal/Uncategorised, рекрутер получил новую ссылку без утечек внутренних ID и токенов.

## Ход 3 (67 с)

**Рекрутер:**

> Эту запись надо привязать к другой карточке: https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c88171bf8cc40c2330b305

**Команды:**

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/references/contract.md", "offset": 1, "limit": 220}
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
python3 scripts/recording_agent.py notion-reassignment --help
```

<details><summary>ответ</summary>

```text
usage: recording_agent.py [-h]
                          {scan,status,review,resolve,ignore,questions,answer,destinations,create-destination,non-interview,route-interview,reroute-recording,notion-reassignment-resolve,notion-reassignment-propose,notion-reassignment-confirm,cleanup-preview,cleanup-confirm,routing-activate,routing-resolve,routing-defer} ...
recording_agent.py: error: argument command: invalid choice: 'notion-reassignment' (choose from scan, status, review, resolve, ignore, questions, answer, destinations, create-destination, non-interview, route-interview, reroute-recording, notion-reassignment-resolve, notion-reassignment-propose, notion-reassignment-confirm, cleanup-preview, cleanup-confirm, routing-activate, routing-resolve, routing-defer)

(Command exited with code 2)
```

</details>

```text
python3 scripts/recording_agent.py notion-reassignment-resolve --help && python3 scripts/recording_agent.py notion-reassignment-propose --help && python3 scripts/recording_agent.py notion-reassignment-confirm --help
```

<details><summary>ответ</summary>

```text
usage: recording_agent.py notion-reassignment-resolve [-h]
                                                      --recruiter-user-id RECRUITER_USER_ID
                                                      --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
                                                      --recording-id RECORDING_ID
                                                      --hint HINT

options:
  -h, --help            show this help message and exit
  --recruiter-user-id RECRUITER_USER_ID
  --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
  --recording-id RECORDING_ID
  --hint HINT
usage: recording_agent.py notion-reassignment-propose [-h]
                                                      --recruiter-user-id RECRUITER_USER_ID
                                                      --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
                                                      --recording-id RECORDING_ID
                                                      --target-page-id TARGET_PAGE_ID

options:
  -h, --help            show this help message and exit
  --recruiter-user-id RECRUITER_USER_ID
  --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
  --recording-id RECORDING_ID
  --target-page-id TARGET_PAGE_ID
usage: recording_agent.py notion-reassignment-confirm [-h]
                                                      --recruiter-user-id RECRUITER_USER_ID
                                                      --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
                                                      --proposal-id PROPOSAL_ID
                                                      --capability <capability>
                                                      --idempotency-key IDEMPOTENCY_KEY

options:
  -h, --help            show this help message and exit
  --recruiter-user-id RECRUITER_USER_ID
  --mattermost-dm-channel-id MATTERMOST_DM_CHANNEL_ID
  --proposal-id PROPOSAL_ID
  --capability <capability>
  --idempotency-key IDEMPOTENCY_KEY
```

</details>

```text
python3 scripts/recording_agent.py notion-reassignment-resolve --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 47a1dd37-b05b-413e-9fae-b5d09aeb29c5 --hint 'https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c88171bf8cc40c2330b305'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено карточек: 1.\n1. E2E Зоя Другая R10-0924_1a3 — https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c88171bf8cc40c2330b305","result":{"items":[{"page_id":"3e5c8889-e4c8-8171-bf8c-c40c2330b305","title":"E2E Зоя Другая R10-0924_1a3","url":"https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c88171bf8cc40c2330b305","recording_present":false}]}}
```

</details>

```text
python3 scripts/recording_agent.py notion-reassignment-propose --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 47a1dd37-b05b-413e-9fae-b5d09aeb29c5 --target-page-id 3e5c8889-e4c8-8171-bf8c-c40c2330b305
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Запись будет привязана к карточке «E2E Зоя Другая R10-0924_1a3»: https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c88171bf8cc40c2330b305\nПока ничего не изменено — нужно ваше подтверждение.","result":{"proposal_id":"873da1be-d9a5-4d2f-a5e7-1376093f2c44","capability":"<capability>","expires_at":"2026-09-24T04:25:21.481789+00:00","target":{"page_id":"3e5c8889-e4c8-8171-bf8c-c40c2330b305","title":"E2E Зоя Другая R10-0924_1a3","url":"https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c88171bf8cc40c2330b305","recording_present":false}}}
```

</details>

**Мила:**

> Найдена целевая карточка: **E2E Зоя Другая R10-0924_1a3**  
> https://app.notion.com/p/E2E-R10-0924_1a3-3e5c8889e4c88171bf8cc40c2330b305
> 
> Пока ничего не меняла. Подтвердите, пожалуйста: **«подтверждаю»** — и я перенесу привязку записи на эту карточку.

**Судья:** 12/12 — Корректный ход: resolve → propose, показано имя и ссылка целевой карточки из ответа бэкенда, запрошено явное подтверждение, ничего не изменено.

## Ход 4 (27 с)

**Рекрутер:**

> Да, подтверждаю

**Команды:**

```text
python3 scripts/recording_agent.py notion-reassignment-confirm --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --proposal-id 873da1be-d9a5-4d2f-a5e7-1376093f2c44 --capability <capability> --idempotency-key ccf3f4e8-0810-4f05-b10f-385b9ea75ac5
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: ссылка на запись перенесена в новую карточку Notion, из старой карточки она убрана. Запись: https://gofile.me/7g8zN/Uo4EB6ISC.","result":{"recording_id":"47a1dd37-b05b-413e-9fae-b5d09aeb29c5","version":4,"safe_link":"https://gofile.me/7g8zN/Uo4EB6ISC","replayed":false}}
```

</details>

**Мила:**

> Готово: запись привязана к новой карточке Notion, а из прежней карточки ссылка удалена.
> 
> Запись: https://gofile.me/7g8zN/Uo4EB6ISC

**Судья:** 12/12 — Корректный ход: вызван notion-reassignment-confirm после явного подтверждения, ответ точно отражает результат бэкенда, безопасен и завершает задачу в одном ходе.

