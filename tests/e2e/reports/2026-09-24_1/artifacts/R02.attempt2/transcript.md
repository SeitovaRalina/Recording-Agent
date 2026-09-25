# R02 — стенограмма

## Ход 1 (51 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 8efa5bf9-7643-f652-09a7-9a3408c00001
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_051248_Собеседование (E2E Марина Аналитикова R02-0924_1a2).webm; кандидат: E2E Марина Аналитикова R02-0924_1a2; новая запись; проект: Бизнес-аналитик @Т-банк; нужно уточнение: нужно выбрать папку в Synology; имя в хранилище: 2026-09-24_E2E_Марина_Аналитикова_R02-0924_1a2_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R02-0924_1a2-3e5c8889e4c8810e8384c83b38d0f2d0\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"3dd111e2-919f-4cc8-b5ac-1e8a7239846e","filename":"2026-09-24_051248_Собеседование (E2E Марина Аналитикова R02-0924_1a2).webm","candidate_name":"E2E Марина Аналитикова R02-0924_1a2","status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"storage_destination_required","generated_filename":"2026-09-24_E2E_Марина_Аналитикова_R02-0924_1a2_Бизнес-аналитик_@Т-банк_general_interview.webm","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R02-0924_1a2-3e5c8889e4c8810e8384c83b38d0f2d0","spot":"Бизнес-аналитик @Т-банк","error":"Interview destination must be selected from allowed Synology inventory"}]}}
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

**Мила:**

> Проверка завершена: найдена **1 новая запись** — кандидат **E2E Марина Аналитикова**, проект **Бизнес-аналитик @Т-банк**.  
> Карточка: https://app.notion.com/p/E2E-R02-0924_1a2-3e5c8889e4c8810e8384c83b38d0f2d0
> 
> Нужно выбрать папку для записи:
> 
> 1. **Внешний проект — Analyst** *(рекомендую, так как вакансия у Т-Банка)*  
> 2. **Внутренний проект — Analyst**
> 
> Ответьте, например: `1 — внешний проект`.

**Судья:** 0/12 — 

## Ход 2 (31 с)

**Рекрутер:**

> Внешний проект, положи во внешние

**Команды:**

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_051248_Собеседование (E2E Марина Аналитикова R02-0924_1a2).webm — нужно выбрать папку в Synology","result":{"items":[{"question_id":"e2235b15-cae7-4f93-8ea5-01c56e02ec47","question_set_id":"928d35dd-a4ba-4775-b76d-9bd56021168e","recording_id":"3dd111e2-919f-4cc8-b5ac-1e8a7239846e","recording_version":1,"filename":"2026-09-24_051248_Собеседование (E2E Марина Аналитикова R02-0924_1a2).webm","reason":"storage_destination_required","choices":[],"capability":"<capability>","expires_at":"2026-09-24T02:47:46.099371+00:00"}],"count":1}}
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
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id 3dd111e2-919f-4cc8-b5ac-1e8a7239846e --destination-id 7bcfe562-c4e4-444c-ac66-ae2c47229af1 --expected-version 1 --idempotency-key 057c1a7e-41be-4c0e-bc0d-71e8e5a96500
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Марина Аналитикова R02-0924_1a2) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R02-0924_1a2-3e5c8889e4c8810e8384c83b38d0f2d0\nЗапись: https://gofile.me/7g8zN/WqOgMKAmI","result":{"recording_id":"3dd111e2-919f-4cc8-b5ac-1e8a7239846e","status":"completed","version":2,"safe_link":"https://gofile.me/7g8zN/WqOgMKAmI","notion_url":"https://app.notion.com/p/E2E-R02-0924_1a2-3e5c8889e4c8810e8384c83b38d0f2d0","candidate_name":"E2E Марина Аналитикова R02-0924_1a2","replayed":false}}
```

</details>

**Мила:**

> Готово — запись собеседования **E2E Марины Аналитиковой** сохранена во внешнюю папку Analyst.
> 
> - Карточка Notion: https://app.notion.com/p/E2E-R02-0924_1a2-3e5c8889e4c8810e8384c83b38d0f2d0  
> - Запись: https://gofile.me/7g8zN/WqOgMKAmI
> 
> Ссылка также добавлена в карточку Notion.

**Судья:** 12/12 — Мила корректно обработала ответ рекрутера: вызвала route-interview (а не reroute-recording) с правильным destination_id, завершила работу за один ход и сообщила итог со ссылками на Notion и запись, без лишних уточнений и без утечек внутренних данных.

