# R08 — стенограмма

## Ход 1 (44 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 4f1ffb78-d0ea-4d79-a454-508e42689c14
```

<details><summary>ответ</summary>

```text
Command still running (session wild-breeze, pid 1349675). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "wild-breeze", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": false, "eof": false, "offset": 0, "limit": 2000, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 2.\nОбнаружено файлов для проверки: 16.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 2.\nТребуют вашего уточнения: 2.\n- 2026-09-24_091031_Планёрка BizDev R08-0924_1a3.webm; новая запись; нужно уточнение: подходящее событие календаря не найдено\n- 2026-09-24_091338_Личный созвон R08-0924_1a3.webm; новая запись; нужно уточнение: подходящее событие календаря не найдено\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":16,"inserted":2,"skipped_legacy":14,"matched":0,"manual_review":2,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":2,"items_truncated":false,"items":[{"id":"f64d94c3-2db0-4f60-b05f-dec84b85163e","filename":"2026-09-24_091031_Планёрка BizDev R08-0924_1a3.webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"no_compatible_event","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null},{"id":"00732672-418f-4cf8-ba72-cb9bac1631d5","filename":"2026-09-24_091338_Личный созвон R08-0924_1a3.webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"no_compatible_event","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null}]}}


Process exited with code 0.
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 2.\n1. 2026-09-24_091031_Планёрка BizDev R08-0924_1a3.webm — подходящее событие календаря не найдено\n2. 2026-09-24_091338_Личный созвон R08-0924_1a3.webm — подходящее событие календаря не найдено","result":{"items":[{"question_id":"3eec0d94-f6a4-4946-9e6d-db90c5665b24","question_set_id":"1a386e76-48e0-4fa8-b153-4d269d2224bc","recording_id":"f64d94c3-2db0-4f60-b05f-dec84b85163e","recording_version":0,"filename":"2026-09-24_091031_Планёрка BizDev R08-0924_1a3.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T06:45:18.588671+00:00"},{"question_id":"c8cbf9aa-9066-4bc3-891e-5dd2da3a15ac","question_set_id":"6a15feed-d14c-4b7f-b8af-a79ac9280fb7","recording_id":"00732672-418f-4cf8-ba72-cb9bac1631d5","recording_version":0,"filename":"2026-09-24_091338_Личный созвон R08-0924_1a3.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T06:45:18.556202+00:00"}],"count":2}}
```

</details>

**Мила:**

> Найдено 2 новые записи — обе без подходящего события в календаре:
> 
> 1. **Планёрка BizDev** — это интервью (укажите кандидата), рабочая встреча (укажите папку) или пропустить?  
> 2. **Личный созвон** — это интервью (укажите кандидата), рабочая встреча (укажите папку) или пропустить?
> 
> Например: `1 — рабочая встреча, в BizDev; 2 — пропусти`.

**Судья:** 12/12 — Корректный ход: scan → questions, рекрутеру одним сообщением сообщено о двух записях без событий с предложением вариантов (интервью / рабочая встреча / пропустить) и примером ответа; факты, безопасность и структура сообщения без замечаний.

## Ход 2 (50 с)

**Рекрутер:**

> Планёрка BizDev — рабочая встреча, положи в папку BizDev. Личный созвон пропусти, это не собеседование.

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
{"ok":true,"message":"Открытых вопросов по записям: 2.\n1. 2026-09-24_091031_Планёрка BizDev R08-0924_1a3.webm — подходящее событие календаря не найдено\n2. 2026-09-24_091338_Личный созвон R08-0924_1a3.webm — подходящее событие календаря не найдено","result":{"items":[{"question_id":"3eec0d94-f6a4-4946-9e6d-db90c5665b24","question_set_id":"1a386e76-48e0-4fa8-b153-4d269d2224bc","recording_id":"f64d94c3-2db0-4f60-b05f-dec84b85163e","recording_version":0,"filename":"2026-09-24_091031_Планёрка BizDev R08-0924_1a3.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T06:45:18.588671+00:00"},{"question_id":"c8cbf9aa-9066-4bc3-891e-5dd2da3a15ac","question_set_id":"6a15feed-d14c-4b7f-b8af-a79ac9280fb7","recording_id":"00732672-418f-4cf8-ba72-cb9bac1631d5","recording_version":0,"filename":"2026-09-24_091338_Личный созвон R08-0924_1a3.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T06:45:18.556202+00:00"}],"count":2}}
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
python3 scripts/recording_agent.py non-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id f64d94c3-2db0-4f60-b05f-dec84b85163e --destination-id e48134fe-697d-4da4-aae5-edc63b9d7861 --expected-version 0 --idempotency-key 01ac4b2d-392a-49c6-92f6-a7f550a8572b
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись рабочей встречи сохранена.\nЗапись: https://gofile.me/7g8zN/QMwbTKsKi","result":{"recording_id":"f64d94c3-2db0-4f60-b05f-dec84b85163e","status":"completed","version":2,"safe_link":"https://gofile.me/7g8zN/QMwbTKsKi","replayed":false}}
```

</details>

```text
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"c8cbf9aa-9066-4bc3-891e-5dd2da3a15ac","question_set_id":"6a15feed-d14c-4b7f-b8af-a79ac9280fb7","action":"ignore","capability":"<capability>","expected_version":0,"idempotency_key":"174e7548-0929-4aad-b3da-b0e5c131dd1f"}]'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Принято ответов: 1; отклонено: 0; ещё ждут ответа: 0.\nОбработка по принятым ответам запущена.","result":{"accepted":[{"question_id":"c8cbf9aa-9066-4bc3-891e-5dd2da3a15ac","recording_id":"00732672-418f-4cf8-ba72-cb9bac1631d5","status":"ignored","version":1,"replayed":false}],"rejected":[],"pending":[]}}
```

</details>

**Мила:**

> Готово.
> 
> - Планёрка BizDev сохранена как рабочая встреча в папке **BizDev**: https://gofile.me/7g8zN/QMwbTKsKi  
> - Личный созвон пропущен — не будет обработан как собеседование.

**Судья:** 12/12 — Мила за один ход корректно классифицировала обе записи: рабочую встречу сохранила в папку BizDev через non-interview (без Notion), личный созвон пропустила через answer/ignore, итог совпадает с проверками системы.

