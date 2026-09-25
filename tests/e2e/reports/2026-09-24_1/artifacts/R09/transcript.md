# R09 — стенограмма

## Ход 1 (78 с)

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

Run every command with the skill directory as the working directory: `workdir` =
`/srv/openclaw/workspaces/recordings-saver/skills/recording-agent` (the folder that holds this
SKILL.md). All `scripts/…` and `references/…` paths in this skill are relative to it. If exec says
`No such file or directory` or `can't open file`, the working directory was wrong: run the same
command again from the skill directory. Never report that as the service being unavailable.

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
seconds. If exec reports that the command is still running, poll it until it exits; neve
```

</details>

```text
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 3167fcfd7eed937a7293b4f38b
```

<details><summary>ответ</summary>

```text
Command still running (session neat-coral, pid 1384491). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "neat-coral", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": false, "eof": false, "offset": 0, "limit": 0, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm; кандидат: E2E Жанна Повторова R09-0924_1a4; новая запись; проект: Бизнес-аналитик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Жанна_Повторова_R09-0924_1a4_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R09-0924_1a4-3e5c8889e4c88116bb5fc2b7d307bcb0\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"b3b6e782-1d99-4a5d-9d3b-01b495f38b38","filename":"2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm","candidate_name":"E2E Жанна Повторова R09-0924_1a4","status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"storage_destination_required","generated_filename":"2026-09-24_E2E_Жанна_Повторова_R09-0924_1a4_Бизнес-аналитик_@Т-банк_general_interview.webm","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R09-0924_1a4-3e5c8889e4c88116bb5fc2b7d307bcb0","spot":"Бизнес-аналитик @Т-банк","error":"Interview destination must be selected from allowed Synology inventory"}]}}


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
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm — нужно выбрать папку в Synology","result":{"items":[{"question_id":"bf58ec2f-5c12-4d9f-bde7-838331d84b62","question_set_id":"bb307b5d-e6b9-4b60-af07-38b0920c702b","recording_id":"b3b6e782-1d99-4a5d-9d3b-01b495f38b38","recording_version":1,"filename":"2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm","reason":"storage_destination_required","choices":[],"capability":"<capability>","expires_at":"2026-09-24T07:35:24.388161+00:00"}],"count":1}}
```

</details>

**Мила:**

> Нашла 1 новую запись:
> 
> - **E2E Жанна Повторова R09-0924_1a4**, проект **«Бизнес-аналитик @Т-банк»**  
>   Карточка: https://app.notion.com/p/E2E-R09-0924_1a4-3e5c8889e4c88116bb5fc2b7d307bcb0
> 
> Нужно выбрать папку для сохранения:
> 
> 1. **Внешние / Analyst** — рекомендую этот вариант: позиция относится к бизнес-аналитике.  
> 2. **Внутренние / Analyst**
> 
> Ответьте, например: `1 — внешние` или `2 — внутренние`.

**Судья:** 11/12 — Мила корректно обработала новую запись, дала одну рекомендацию с двумя вариантами Analyst и понятным примером ответа; единственный минус — лишний вызов `questions` перед тем, как рекрутер успел ответить.

## Ход 2 (54 с)

**Рекрутер:**

> Во внешние

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
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm — нужно выбрать папку в Synology","result":{"items":[{"question_id":"bf58ec2f-5c12-4d9f-bde7-838331d84b62","question_set_id":"bb307b5d-e6b9-4b60-af07-38b0920c702b","recording_id":"b3b6e782-1d99-4a5d-9d3b-01b495f38b38","recording_version":1,"filename":"2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm","reason":"storage_destination_required","choices":[],"capability":"<capability>","expires_at":"2026-09-24T07:35:24.388161+00:00"}],"count":1}}
```

</details>

```text
python3 scripts/recording_agent.py destinations --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r && python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id b3b6e782-1d99-4a5d-9d3b-01b495f38b38 --destination-id 7bcfe562-c4e4-444c-ac66-ae2c47229af1 --expected-version 1 --idempotency-key 424960770653b271437a36f4f1
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Доступные папки в Synology: 52.\n1. /home/Recruiting-NE/2. Interviews\n2. /home/Recruiting-NE/2. Interviews/BizDev\n3. /home/Recruiting-NE/2. Interviews/Delivery Manager\n4. /home/Recruiting-NE/2. Interviews/DevFest 2025 (оргсостав)\n5. /home/Recruiting-NE/2. Interviews/Labs 2025 (оргсостав)\n6. /home/Recruiting-NE/2. Interviews/Outreach Manager\n7. /home/Recruiting-NE/2. Interviews/Revenue Manager\n8. /home/Recruiting-NE/2. Interviews/Администратор Академии\n9. /home/Recruiting-NE/2. Interviews/Ассистент в отдел продаж\n10. /home/Recruiting-NE/2. Interviews/Бизнес ассистент\n11. /home/Recruiting-NE/2. Interviews/Бухгалтер в единственном лице\n12. /home/Recruiting-NE/2. Interviews/Волонтёры DevFest\n13. /home/Recruiting-NE/2. Interviews/Дизайнер\n14. /home/Recruiting-NE/2. Interviews/ИТ_рекрутер\n15. /home/Recruiting-NE/2. Interviews/ИТ_ресечер\n16. /home/Recruiting-NE/2. Interviews/Коммерский директор\n17. /home/Recruiting-NE/2. Interviews/Копирайтер\n18. /home/Recruiting-NE/2. Interviews/Менеджер по персоналу\n19. /home/Recruiting-NE/2. Interviews/Менеджер по продажам\n20. /home/Recruiting-NE/2. Interviews/Менеджер проектов\n21. /home/Recruiting-NE/2. Interviews/Офис-менеджер\n22. /home/Recruiting-NE/2. Interviews/Руководитель отдела продаж\n23. /home/Recruiting-NE/2. Interviews/СЕО Ventures\n24. /home/Recruiting-NE/2. Interviews/Системный Администратор\n25. /home/Recruiting-NE/2. Interviews/Специалист по договорам и оплатам\n26. /home/Recruiting-NE/2. Interviews/Специалист по кадрам\n27. /home/Recruiting-E/2. Interviews external\n28. /home/Recruiting-E/2. Interviews external/Aldo\n29. /home/Recruiting-E/2. Interviews external/Analyst\n30. /home/Recruiting-E/2. Interviews external/Android\n31. /home/Recruiting-E/2. Interviews external/Backend\n32. /home/Recruiting-E/2. Interviews external/E2E Discovery R03-0924_1a3\n33. /home/Recruiting-E/2. Interviews external/Flutter\n34. /home/Recruiting-E/2. Interviews external/Frontend\n35. /home/Recruiting-E/2. Interviews external/Fullstack\n36. /home/Recruiting-E/2. Interviews external/IOS\n37. /home/Recruiting-E/2. Interviews external/Python\n38. /home/Recruiting-E/2. Interviews external/QA\n39. /home/Recruiting-E/2. Interviews external/Support Engineer\n40. /home/Recruiting-E/2. Interviews external/Обмен записями с Recruiting-NB\n41. /home/Recruiting-E/2. Interviews external/Aldo/2022\n42. /home/Recruiting-E/2. Interviews external/IOS/Veriflix + Heramed, iOS Dev, Sep '22\n43. /home/Recruiting-E/3. Interviews internal\n44. /home/Recruiting-E/3. Interviews internal/Analyst\n45. /home/Recruiting-E/3. Interviews internal/Android\n46. /home/Recruiting-E/3. Interviews internal/DevOps\n47. /home/Recruiting-E/3. Interviews internal/Flutter\n48. /home/Recruiting-E/3. Interviews internal/iOS\n49. /home/Recruiting-E/3. Interviews internal/QA manual\n50. /home/Recruiting-E/3. Interviews internal/Uncategorised\n51. /home/Recruiting-E/3. Interviews internal/Web\n52. /home/Recruiting-E/3. Interv
```

</details>

**Мила:**

> Запись Жанны Повторовой сохранена во **внешнюю папку Analyst**.
> 
> Ссылка на запись: https://gofile.me/7g8zN/9EBFyIVXM  
> Карточка кандидата: https://app.notion.com/p/E2E-R09-0924_1a4-3e5c8889e4c88116bb5fc2b7d307bcb0
> 
> Notion сейчас временно недоступен — ссылка появится в карточке при следующей проверке. Повторно сохранять запись не нужно.

**Судья:** 12/12 — Мила корректно вызвала route-interview после выбора папки, честно сообщила о сохранении в Synology и временной недоступности Notion, не утверждая, что ссылка уже в карточке. Все проверки пройдены, ответ по делу и с понятным следующим шагом.

## Ход 3 (37 с)

**Рекрутер:**

> Notion снова работает, повтори сохранение

**Команды:**

```text
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 76832aa2743542eb9d164f285a
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 0.\nОбнаружено файлов для проверки: 14.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 0.\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 1.\n- 2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm; кандидат: E2E Жанна Повторова R09-0924_1a4; повторная обработка; проект: Бизнес-аналитик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Жанна_Повторова_R09-0924_1a4_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R09-0924_1a4-3e5c8889e4c88116bb5fc2b7d307bcb0; запись: https://gofile.me/7g8zN/9EBFyIVXM\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":14,"inserted":0,"skipped_legacy":14,"matched":0,"manual_review":0,"without_review":1,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"b3b6e782-1d99-4a5d-9d3b-01b495f38b38","filename":"2026-09-24_100012_Собеседование (E2E Жанна Повторова R09-0924_1a4).webm","candidate_name":"E2E Жанна Повторова R09-0924_1a4","status":"completed","is_new":false,"requires_review":false,"review_reason":"storage_destination_required","generated_filename":"2026-09-24_E2E_Жанна_Повторова_R09-0924_1a4_Бизнес-аналитик_@Т-банк_general_interview.webm","safe_link":"https://gofile.me/7g8zN/9EBFyIVXM","notion_url":"https://app.notion.com/p/E2E-R09-0924_1a4-3e5c8889e4c88116bb5fc2b7d307bcb0","spot":"Бизнес-аналитик @Т-банк","error":null}]}}
```

</details>

**Мила:**

> Готово: повторная проверка обновила карточку Notion, обработка завершена.
> 
> - Кандидат: E2E Жанна Повторова R09-0924_1a4  
> - Карточка: https://app.notion.com/p/E2E-R09-0924_1a4-3e5c8889e4c88116bb5fc2b7d307bcb0  
> - Запись: https://gofile.me/7g8zN/9EBFyIVXM

**Судья:** 12/12 — Идеальный ход: scan корректно завершил обработку, повторно использовал уже загруженный файл, статус completed, обе ссылки и папка совпадают с проверками.

