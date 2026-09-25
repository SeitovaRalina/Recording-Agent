# R08 — стенограмма

## Ход 1 (41 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key b371ae48-7805-4a7d-89ef-9f796b000001
```

<details><summary>ответ</summary>

```text
Command still running (session nova-cloud, pid 1186200). Use process (list/poll/log/write/send-keys/submit/paste/kill/clear/remove) for follow-up.
```

</details>

```text
{"action": "poll", "sessionId": "nova-cloud", "data": "", "keys": [], "hex": [], "literal": "", "text": "", "bracketed": false, "eof": false, "offset": 0, "limit": 0, "timeout": 30000}
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 2.\nОбнаружено файлов для проверки: 16.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 2.\nТребуют вашего уточнения: 2.\n- 2026-09-24_054129_Планёрка BizDev R08-0924_1a1.webm; новая запись; нужно уточнение: подходящее событие календаря не найдено\n- 2026-09-24_054436_Личный созвон R08-0924_1a1.webm; новая запись; нужно уточнение: подходящее событие календаря не найдено\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":16,"inserted":2,"skipped_legacy":14,"matched":0,"manual_review":2,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":2,"items_truncated":false,"items":[{"id":"b53821de-6fa6-4b52-9bac-1e99d7644eea","filename":"2026-09-24_054129_Планёрка BizDev R08-0924_1a1.webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"no_compatible_event","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null},{"id":"ac45f0e1-ab75-42c5-88ed-158c7c588368","filename":"2026-09-24_054436_Личный созвон R08-0924_1a1.webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"no_compatible_event","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null}]}}


Process exited with code 0.
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 2.\n1. 2026-09-24_054436_Личный созвон R08-0924_1a1.webm — подходящее событие календаря не найдено\n2. 2026-09-24_054129_Планёрка BizDev R08-0924_1a1.webm — подходящее событие календаря не найдено","result":{"items":[{"question_id":"52d8ad2c-90fc-45e8-8d6f-3d650fafaf59","question_set_id":"fd939952-e05c-4732-a848-9552e90b05b7","recording_id":"ac45f0e1-ab75-42c5-88ed-158c7c588368","recording_version":0,"filename":"2026-09-24_054436_Личный созвон R08-0924_1a1.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:16:15.658675+00:00"},{"question_id":"a96994f0-8acc-420c-9682-a077c499295a","question_set_id":"02151798-9231-4507-97af-0219b1b4deca","recording_id":"b53821de-6fa6-4b52-9bac-1e99d7644eea","recording_version":0,"filename":"2026-09-24_054129_Планёрка BizDev R08-0924_1a1.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:16:15.624717+00:00"}],"count":2}}
```

</details>

**Мила:**

> Нашла 2 новые записи — обе требуют уточнения, потому что для них не найдено подходящее событие в календаре:
> 
> 1. `Личный созвон R08-0924`  
> 2. `Планёрка BizDev R08-0924`
> 
> Подскажите, это рабочие встречи или интервью? Если интервью — пришлите, пожалуйста, имя кандидата или ссылку на его карточку.

**Судья:** 10/12 — Технически ход корректен: скан + questions выполнены, факты и безопасность в порядке, но в уточнении не хватает варианта «пропустить» и примера формата ответа.

## Ход 2 (52 с)

**Рекрутер:**

> Первая — рабочая встреча, положи в BizDev. Вторую пропусти, это не собеседование.

**Команды:**

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
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 2.\n1. 2026-09-24_054436_Личный созвон R08-0924_1a1.webm — подходящее событие календаря не найдено\n2. 2026-09-24_054129_Планёрка BizDev R08-0924_1a1.webm — подходящее событие календаря не найдено","result":{"items":[{"question_id":"52d8ad2c-90fc-45e8-8d6f-3d650fafaf59","question_set_id":"fd939952-e05c-4732-a848-9552e90b05b7","recording_id":"ac45f0e1-ab75-42c5-88ed-158c7c588368","recording_version":0,"filename":"2026-09-24_054436_Личный созвон R08-0924_1a1.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:16:15.658675+00:00"},{"question_id":"a96994f0-8acc-420c-9682-a077c499295a","question_set_id":"02151798-9231-4507-97af-0219b1b4deca","recording_id":"b53821de-6fa6-4b52-9bac-1e99d7644eea","recording_version":0,"filename":"2026-09-24_054129_Планёрка BizDev R08-0924_1a1.webm","reason":"no_compatible_event","choices":[],"capability":"<capability>","expires_at":"2026-09-24T03:16:15.624717+00:00"}],"count":2}}
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
python3 scripts/recording_agent.py non-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id ac45f0e1-ab75-42c5-88ed-158c7c588368 --destination-id e48134fe-697d-4da4-aae5-edc63b9d7861 --expected-version 0 --idempotency-key 9a99d8ab-2d80-4cb5-bd59-51e3b8d3b582
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись рабочей встречи сохранена.\nЗапись: https://gofile.me/7g8zN/86XCR2Iy8","result":{"recording_id":"ac45f0e1-ab75-42c5-88ed-158c7c588368","status":"completed","version":2,"safe_link":"https://gofile.me/7g8zN/86XCR2Iy8","replayed":false}}
```

</details>

```text
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"a96994f0-8acc-420c-9682-a077c499295a","question_set_id":"02151798-9231-4507-97af-0219b1b4deca","action":"ignore","capability":"<capability>","expected_version":0,"idempotency_key":"579e9e61-11cf-4c41-b9ef-d856393cd399"}]'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Принято ответов: 1; отклонено: 0; ещё ждут ответа: 0.\nОбработка по принятым ответам запущена.","result":{"accepted":[{"question_id":"a96994f0-8acc-420c-9682-a077c499295a","recording_id":"b53821de-6fa6-4b52-9bac-1e99d7644eea","status":"ignored","version":1,"replayed":false}],"rejected":[],"pending":[]}}
```

</details>

**Мила:**

> Готово.
> 
> - Рабочую встречу сохранила в **BizDev**: https://gofile.me/7g8zN/86XCR2Iy8  
> - Вторую запись пометила как не-собеседование и пропустила.

**Судья:** 12/12 — Чистое выполнение R08: questions → destinations → non-interview в BizDev для первой записи и answer/ignore для второй, краткий итог с safe-ссылкой и без утечек идентификаторов/токенов.

