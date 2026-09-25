# R02 — стенограмма

## Ход 1 (64 с)

**Рекрутер:**

> Проверь новые записи

**Команды:**

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/SKILL.md", "offset": 1, "limit": 400}
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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 20260924-0324-z1cn9tz3opg6fm7e8d7phcs88r-scan
```

<details><summary>ответ</summary>

```text
python3: can't open file '/srv/openclaw/workspaces/recordings-saver/scripts/recording_agent.py': [Errno 2] No such file or directory

(Command exited with code 2)
```

</details>

```text
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 20260924-0324-z1cn9tz3opg6fm7e8d7phcs88r-scan
```

<details><summary>ответ</summary>

```text
Command still running (session plaid-tidepool, pid 1201541). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "plaid-tidepool", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": true, "eof": false, "offset": 0, "limit": 2000, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_060503_Собеседование (E2E Марина Аналитикова R02-0924_1a3).webm; кандидат: E2E Марина Аналитикова R02-0924_1a3; новая запись; проект: Бизнес-аналитик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Марина_Аналитикова_R02-0924_1a3_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R02-0924_1a3-3e5c8889e4c881ee94c9e7da2ef30b98\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"8afffbf2-f7b7-4284-9329-d66ffc802dd5","filename":"2026-09-24_060503_Собеседование (E2E Марина Аналитикова R02-0924_1a3).webm","candidate_name":"E2E Марина Аналитикова R02-0924_1a3","status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"storage_destination_required","generated_filename":"2026-09-24_E2E_Марина_Аналитикова_R02-0924_1a3_Бизнес-аналитик_@Т-банк_general_interview.webm","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R02-0924_1a3-3e5c8889e4c881ee94c9e7da2ef30b98","spot":"Бизнес-аналитик @Т-банк","error":"Interview destination must be selected from allowed Synology inventory"}]}}

Process exited with code 0.
```

</details>

```text
python3 scripts/recording_agent.py destinations --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
Command still running (session fast-lagoon, pid 1201686). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "fast-lagoon", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": true, "eof": false, "offset": 0, "limit": 4000, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
home/Recruiting-E/2. Interviews external/Обмен записями с Recruiting-NB","writable":true},{"id":"2ed4c50e-9553-42c5-a6b5-5e085526ad57","display_name":"2022","path_label":"/home/Recruiting-E/2. Interviews external/Aldo/2022","writable":true},{"id":"878e5306-2826-4e7d-9770-d408307088e0","display_name":"Veriflix + Heramed, iOS Dev, Sep '22","path_label":"/home/Recruiting-E/2. Interviews external/IOS/Veriflix + Heramed, iOS Dev, Sep '22","writable":true},{"id":"75a6671b-aa04-46c8-a1f7-027c5b7f7af9","display_name":"3. Interviews internal","path_label":"/home/Recruiting-E/3. Interviews internal","writable":true},{"id":"2f3a7c4a-c126-4511-bc20-185328777419","display_name":"Analyst","path_label":"/home/Recruiting-E/3. Interviews internal/Analyst","writable":true},{"id":"162c5720-2450-4fd6-9514-58c7fb7d7fa3","display_name":"Android","path_label":"/home/Recruiting-E/3. Interviews internal/Android","writable":true},{"id":"b09879d0-8bb2-4b31-b90c-be5ff8a5f433","display_name":"DevOps","path_label":"/home/Recruiting-E/3. Interviews internal/DevOps","writable":true},{"id":"d33dff23-16ee-41b6-a7b8-31c49f8a605e","display_name":"Flutter","path_label":"/home/Recruiting-E/3. Interviews internal/Flutter","writable":true},{"id":"50e5fd17-3cb2-4f8a-b0bf-4333d021f46a","display_name":"iOS","path_label":"/home/Recruiting-E/3. Interviews internal/iOS","writable":true},{"id":"9c13dfc6-de6c-450d-923f-d80a7046bdcb","display_name":"QA manual","path_label":"/home/Recruiting-E/3. Interviews internal/QA manual","writable":true},{"id":"b57a02b0-36d1-4436-89db-7932f2aa035a","display_name":"Uncategorised","path_label":"/home/Recruiting-E/3. Interviews internal/Uncategorised","writable":true},{"id":"3faf057c-1884-4b64-9293-e62957da5bdb","display_name":"Web","path_label":"/home/Recruiting-E/3. Interviews internal/Web","writable":true},{"id":"ba772114-c108-43ec-bc43-a9008830e8cb","display_name":"client","path_label":"/home/Recruiting-E/3. Interviews internal/Android/client","writable":true}],"count":51}}


Process exited with code 0.
```

</details>

```text
{"action": "log", "sessionId": "fast-lagoon", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": true, "eof": false, "offset": 0, "limit": 10000, "timeout": 0}
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Доступные папки в Synology: 51.\n1. /home/Recruiting-NE/2. Interviews\n2. /home/Recruiting-NE/2. Interviews/BizDev\n3. /home/Recruiting-NE/2. Interviews/Delivery Manager\n4. /home/Recruiting-NE/2. Interviews/DevFest 2025 (оргсостав)\n5. /home/Recruiting-NE/2. Interviews/Labs 2025 (оргсостав)\n6. /home/Recruiting-NE/2. Interviews/Outreach Manager\n7. /home/Recruiting-NE/2. Interviews/Revenue Manager\n8. /home/Recruiting-NE/2. Interviews/Администратор Академии\n9. /home/Recruiting-NE/2. Interviews/Ассистент в отдел продаж\n10. /home/Recruiting-NE/2. Interviews/Бизнес ассистент\n11. /home/Recruiting-NE/2. Interviews/Бухгалтер в единственном лице\n12. /home/Recruiting-NE/2. Interviews/Волонтёры DevFest\n13. /home/Recruiting-NE/2. Interviews/Дизайнер\n14. /home/Recruiting-NE/2. Interviews/ИТ_рекрутер\n15. /home/Recruiting-NE/2. Interviews/ИТ_ресечер\n16. /home/Recruiting-NE/2. Interviews/Коммерский директор\n17. /home/Recruiting-NE/2. Interviews/Копирайтер\n18. /home/Recruiting-NE/2. Interviews/Менеджер по персоналу\n19. /home/Recruiting-NE/2. Interviews/Менеджер по продажам\n20. /home/Recruiting-NE/2. Interviews/Менеджер проектов\n21. /home/Recruiting-NE/2. Interviews/Офис-менеджер\n22. /home/Recruiting-NE/2. Interviews/Руководитель отдела продаж\n23. /home/Recruiting-NE/2. Interviews/СЕО Ventures\n24. /home/Recruiting-NE/2. Interviews/Системный Администратор\n25. /home/Recruiting-NE/2. Interviews/Специалист по договорам и оплатам\n26. /home/Recruiting-NE/2. Interviews/Специалист по кадрам\n27. /home/Recruiting-E/2. Interviews external\n28. /home/Recruiting-E/2. Interviews external/Aldo\n29. /home/Recruiting-E/2. Interviews external/Analyst\n30. /home/Recruiting-E/2. Interviews external/Android\n31. /home/Recruiting-E/2. Interviews external/Backend\n32. /home/Recruiting-E/2. Interviews external/Flutter\n33. /home/Recruiting-E/2. Interviews external/Frontend\n34. /home/Recruiting-E/2. Interviews external/Fullstack\n35. /home/Recruiting-E/2. Interviews external/IOS\n36. /home/Recruiting-E/2. Interviews external/Python\n37. /home/Recruiting-E/2. Interviews external/QA\n38. /home/Recruiting-E/2. Interviews external/Support Engineer\n39. /home/Recruiting-E/2. Interviews external/Обмен записями с Recruiting-NB\n40. /home/Recruiting-E/2. Interviews external/Aldo/2022\n41. /home/Recruiting-E/2. Interviews external/IOS/Veriflix + Heramed, iOS Dev, Sep '22\n42. /home/Recruiting-E/3. Interviews internal\n43. /home/Recruiting-E/3. Interviews internal/Analyst\n44. /home/Recruiting-E/3. Interviews internal/Android\n45. /home/Recruiting-E/3. Interviews internal/DevOps\n46. /home/Recruiting-E/3. Interviews internal/Flutter\n47. /home/Recruiting-E/3. Interviews internal/iOS\n48. /home/Recruiting-E/3. Interviews internal/QA manual\n49. /home/Recruiting-E/3. Interviews internal/Uncategorised\n50. /home/Recruiting-E/3. Interviews internal/Web\n51. /home/Recruiting-E/3. Interviews internal/Android/client","result":{"items":[{"id":"9ace2fdb-d1bc-4619
```

</details>

**Мила:**

> Найдена **1 новая запись**:
> 
> - **Кандидат:** E2E Марина Аналитикова R02-0924_1a3  
> - **Проект:** Бизнес-аналитик @Т-банк  
> - **Карточка Notion:** https://app.notion.com/p/E2E-R02-0924_1a3-3e5c8889e4c881ee94c9e7da2ef30b98
> 
> Запись пока не сохранена — нужно выбрать папку в Synology. Подходят два варианта:
> 
> 1. **Внешний проект:** `2. Interviews external/Analyst` — рекомендую этот вариант, так как запись относится к проекту Т-банк.
> 2. **Внутренний проект:** `3. Interviews internal/Analyst`
> 
> Ответьте, пожалуйста: **`1 — внешний проект`** или **`2 — внутренний проект`**.

**Судья:** 12/12 — Идеальный ход: scan → destinations, без сохранения, один вопрос с нумерованными вариантами, рекомендацией (внешний, т.к. Т-банк) и шаблоном ответа.

## Ход 2 (36 с)

**Рекрутер:**

> Внешний проект, положи во внешние

**Команды:**

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_060503_Собеседование (E2E Марина Аналитикова R02-0924_1a3).webm — нужно выбрать папку в Synology","result":{"items":[{"question_id":"837d2c9e-8d2d-43b2-8cf2-a125629f9c36","question_set_id":"ceafc93f-3c3e-4885-a1ce-f5d0fdcc25f2","recording_id":"8afffbf2-f7b7-4284-9329-d66ffc802dd5","recording_version":1,"filename":"2026-09-24_060503_Собеседование (E2E Марина Аналитикова R02-0924_1a3).webm","reason":"storage_destination_required","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:40:01.183434+00:00"}],"count":1}}
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
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 8afffbf2-f7b7-4284-9329-d66ffc802dd5 --destination-id 7bcfe562-c4e4-444c-ac66-ae2c47229af1 --expected-version 1 --idempotency-key 20260924-0325-z1cn9tz3opg6fm7e8d7phcs88r-external-analyst
```

<details><summary>ответ</summary>

```text
Command still running (session tide-bison, pid 1202405). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "tide-bison", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": true, "eof": false, "offset": 0, "limit": 4000, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Марина Аналитикова R02-0924_1a3) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R02-0924_1a3-3e5c8889e4c881ee94c9e7da2ef30b98\nЗапись: https://gofile.me/7g8zN/htq6q0RWM","result":{"recording_id":"8afffbf2-f7b7-4284-9329-d66ffc802dd5","status":"completed","version":2,"safe_link":"https://gofile.me/7g8zN/htq6q0RWM","notion_url":"https://app.notion.com/p/E2E-R02-0924_1a3-3e5c8889e4c881ee94c9e7da2ef30b98","candidate_name":"E2E Марина Аналитикова R02-0924_1a3","replayed":false}}

Process exited with code 0.
```

</details>

**Мила:**

> Готово — запись Марины Аналитиковой сохранена во внешнюю папку **Analyst**.
> 
> - Карточка Notion: https://app.notion.com/p/E2E-R02-0924_1a3-3e5c8889e4c881ee94c9e7da2ef30b98  
> - Запись: https://gofile.me/7g8zN/htq6q0RWM  
> 
> Ссылка также добавлена в карточку Notion.

**Судья:** 12/12 — Корректно: Мила получила recording_id через questions, вызвала route-interview с верным destination-id (внешний проект Analyst), дождалась результата и сообщила рекрутеру обе ссылки без лишних уточнений.

