# R01 — стенограмма

## Ход 1 (64 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 9f9dc9c2-93e1-4f1c-8c09-5e1af1b69c7a
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_044747_Собеседование (E2E Олег Тестов R01-0924_1a7).webm; кандидат: E2E Олег Тестов R01-0924_1a7; новая запись; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Олег_Тестов_R01-0924_1a7_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R01-0924_1a7-3e5c8889e4c88153b402ec3336f7cae4\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"95be6fb9-2337-4dbe-91cb-f0cdcbebba3d","filename":"2026-09-24_044747_Собеседование (E2E Олег Тестов R01-0924_1a7).webm","candidate_name":"E2E Олег Тестов R01-0924_1a7","status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"storage_destination_required","generated_filename":"2026-09-24_E2E_Олег_Тестов_R01-0924_1a7_Python-разработчик_@Т-банк_general_interview.webm","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R01-0924_1a7-3e5c8889e4c88153b402ec3336f7cae4","spot":"Python-разработчик @Т-банк","error":"Interview destination must be selected from allowed Synology inventory"}]}}
```

</details>

```text
python3 scripts/recording_agent.py destinations --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Доступные папки в Synology: 51.\n1. /home/Recruiting-NE/2. Interviews\n2. /home/Recruiting-NE/2. Interviews/BizDev\n3. /home/Recruiting-NE/2. Interviews/Delivery Manager\n4. /home/Recruiting-NE/2. Interviews/DevFest 2025 (оргсостав)\n5. /home/Recruiting-NE/2. Interviews/Labs 2025 (оргсостав)\n6. /home/Recruiting-NE/2. Interviews/Outreach Manager\n7. /home/Recruiting-NE/2. Interviews/Revenue Manager\n8. /home/Recruiting-NE/2. Interviews/Администратор Академии\n9. /home/Recruiting-NE/2. Interviews/Ассистент в отдел продаж\n10. /home/Recruiting-NE/2. Interviews/Бизнес ассистент\n11. /home/Recruiting-NE/2. Interviews/Бухгалтер в единственном лице\n12. /home/Recruiting-NE/2. Interviews/Волонтёры DevFest\n13. /home/Recruiting-NE/2. Interviews/Дизайнер\n14. /home/Recruiting-NE/2. Interviews/ИТ_рекрутер\n15. /home/Recruiting-NE/2. Interviews/ИТ_ресечер\n16. /home/Recruiting-NE/2. Interviews/Коммерский директор\n17. /home/Recruiting-NE/2. Interviews/Копирайтер\n18. /home/Recruiting-NE/2. Interviews/Менеджер по персоналу\n19. /home/Recruiting-NE/2. Interviews/Менеджер по продажам\n20. /home/Recruiting-NE/2. Interviews/Менеджер проектов\n21. /home/Recruiting-NE/2. Interviews/Офис-менеджер\n22. /home/Recruiting-NE/2. Interviews/Руководитель отдела продаж\n23. /home/Recruiting-NE/2. Interviews/СЕО Ventures\n24. /home/Recruiting-NE/2. Interviews/Системный Администратор\n25. /home/Recruiting-NE/2. Interviews/Специалист по договорам и оплатам\n26. /home/Recruiting-NE/2. Interviews/Специалист по кадрам\n27. /home/Recruiting-E/2. Interviews external\n28. /home/Recruiting-E/2. Interviews external/Aldo\n29. /home/Recruiting-E/2. Interviews external/Analyst\n30. /home/Recruiting-E/2. Interviews external/Android\n31. /home/Recruiting-E/2. Interviews external/Backend\n32. /home/Recruiting-E/2. Interviews external/Flutter\n33. /home/Recruiting-E/2. Interviews external/Frontend\n34. /home/Recruiting-E/2. Interviews external/Fullstack\n35. /home/Recruiting-E/2. Interviews external/IOS\n36. /home/Recruiting-E/2. Interviews external/Python\n37. /home/Recruiting-E/2. Interviews external/QA\n38. /home/Recruiting-E/2. Interviews external/Support Engineer\n39. /home/Recruiting-E/2. Interviews external/Обмен записями с Recruiting-NB\n40. /home/Recruiting-E/2. Interviews external/Aldo/2022\n41. /home/Recruiting-E/2. Interviews external/IOS/Veriflix + Heramed, iOS Dev, Sep '22\n42. /home/Recruiting-E/3. Interviews internal\n43. /home/Recruiting-E/3. Interviews internal/Analyst\n44. /home/Recruiting-E/3. Interviews internal/Android\n45. /home/Recruiting-E/3. Interviews internal/DevOps\n46. /home/Recruiting-E/3. Interviews internal/Flutter\n47. /home/Recruiting-E/3. Interviews internal/iOS\n48. /home/Recruiting-E/3. Interviews internal/QA manual\n49. /home/Recruiting-E/3. Interviews internal/Uncategorised\n50. /home/Recruiting-E/3. Interviews internal/Web\n51. /home/Recruiting-E/3. Interviews internal/Android/client","result":{"items":[{"id":"9ace2fdb-d1bc-4619
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
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --recording-id 95be6fb9-2337-4dbe-91cb-f0cdcbebba3d
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено записей: 1.\n- 2026-09-24_044747_Собеседование (E2E Олег Тестов R01-0924_1a7).webm; кандидат: E2E Олег Тестов R01-0924_1a7; проект: Python-разработчик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Олег_Тестов_R01-0924_1a7_Python-разработчик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R01-0924_1a7-3e5c8889e4c88153b402ec3336f7cae4","result":{"items":[{"id":"95be6fb9-2337-4dbe-91cb-f0cdcbebba3d","filename":"2026-09-24_044747_Собеседование (E2E Олег Тестов R01-0924_1a7).webm","generated_filename":"2026-09-24_E2E_Олег_Тестов_R01-0924_1a7_Python-разработчик_@Т-банк_general_interview.webm","candidate_name":"E2E Олег Тестов R01-0924_1a7","status":"manual_review_required","requires_review":true,"review_reason":"storage_destination_required","version":1,"found_at":"2026-09-24T02:07:40.459369+00:00","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R01-0924_1a7-3e5c8889e4c88153b402ec3336f7cae4","spot":"Python-разработчик @Т-банк","error":"Interview destination must be selected from allowed Synology inventory"}],"count":1}}
```

</details>

```text
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 95be6fb9-2337-4dbe-91cb-f0cdcbebba3d --destination-id ce009880-84e7-48b7-8bc4-5351f716ff25 --expected-version 1 --idempotency-key 00f31e94-bd28-4cdb-8f42-1278dd920a85
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Олег Тестов R01-0924_1a7) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R01-0924_1a7-3e5c8889e4c88153b402ec3336f7cae4\nЗапись: https://gofile.me/7g8zN/bBzj5cipZ","result":{"recording_id":"95be6fb9-2337-4dbe-91cb-f0cdcbebba3d","status":"completed","version":2,"safe_link":"https://gofile.me/7g8zN/bBzj5cipZ","notion_url":"https://app.notion.com/p/E2E-R01-0924_1a7-3e5c8889e4c88153b402ec3336f7cae4","candidate_name":"E2E Олег Тестов R01-0924_1a7","replayed":false}}
```

</details>

**Мила:**

> Проверка завершена: найдена 1 новая запись — собеседование с **E2E Олегом Тестовым R01-0924_1a7** на позицию Python-разработчика @Т-банк.
> 
> Я сохранила её в папку Python, запись и карточка обновлены:
> - Notion: https://app.notion.com/p/E2E-R01-0924_1a7-3e5c8889e4c88153b402ec3336f7cae4
> - Запись: https://gofile.me/7g8zN/bBzj5cipZ
> 
> Также просмотрено 15 файлов: 14 старых записей пропущены, ошибок нет.

**Судья:** 12/12 — Идеальный ход: scan → destinations → route-interview в однозначную папку Python без вопросов рекрутеру, корректный итог с кандидатом и обеими ссылками, без утечек внутренних идентификаторов.

