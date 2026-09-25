# R11 — стенограмма

## Ход 1 (58 с)

**Рекрутер:**

> По записи E2E Лидия Автоаналитик R11-0924_1a3 — во внешние

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

After `scan` (an
```

</details>

```text
{"path": "/srv/openclaw/workspaces/recordings-saver/skills/recording-agent/references/contract.md", "offset": 1, "limit": 200}
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
| `destinations` | `GET /tools/stor
```

</details>

```text
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --recording-id 'E2E Лидия Автоаналитик R11-0924_1a3'
```

<details><summary>ответ</summary>

```text
usage: recording_agent.py status [-h] --recruiter-user-id RECRUITER_USER_ID
                                 [--date DATE] [--candidate CANDIDATE]
                                 [--recording-id RECORDING_ID]
                                 [--status STATUS] [--limit 1..50]
recording_agent.py status: error: argument --recording-id: invalid UUID value: 'E2E Лидия Автоаналитик R11-0924_1a3'

(Command exited with code 2)
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям нет.","result":{"items":[],"count":0}}
```

</details>

```text
python3 scripts/recording_agent.py status --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --candidate 'Лидия'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Найдено записей: 2.\n- 2026-09-24_073105_Собеседование (E2E Лидия Автоаналитик R11-0924_1a3).webm; кандидат: E2E Лидия Автоаналитик R11-0924_1a3; проект: Бизнес-аналитик @Т-банк; статус: кандидат найден в Notion; имя в хранилище: 2026-09-24_E2E_Лидия_Автоаналитик_R11-0924_1a3_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R11-0924_1a3-3e5c8889e4c881cda60ae2f66ea1a3e3\n- 2026-09-24_065655_Собеседование (E2E Лидия Автоаналитик R11-0924_1a2).webm; кандидат: E2E Лидия Автоаналитик R11-0924_1a2; проект: Бизнес-аналитик @Т-банк; статус: обработка завершена; имя в хранилище: 2026-09-24_E2E_Лидия_Автоаналитик_R11-0924_1a2_Бизнес-аналитик_@Т-банк_general_interview.webm; карточка Notion: https://app.notion.com/p/E2E-R11-0924_1a2-3e5c8889e4c881f3a9dade9db7db8971; запись: https://gofile.me/7g8zN/JijXc49UL","result":{"items":[{"id":"d561d736-a0ab-42e5-9dbe-a8e663563321","filename":"2026-09-24_073105_Собеседование (E2E Лидия Автоаналитик R11-0924_1a3).webm","generated_filename":"2026-09-24_E2E_Лидия_Автоаналитик_R11-0924_1a3_Бизнес-аналитик_@Т-банк_general_interview.webm","candidate_name":"E2E Лидия Автоаналитик R11-0924_1a3","status":"candidate_matched","requires_review":false,"review_reason":null,"version":1,"found_at":"2026-09-24T04:48:18.294952+00:00","safe_link":null,"notion_url":"https://app.notion.com/p/E2E-R11-0924_1a3-3e5c8889e4c881cda60ae2f66ea1a3e3","spot":"Бизнес-аналитик @Т-банк","error":null},{"id":"2c10f54c-da61-4968-a8bc-bc318b01b113","filename":"2026-09-24_065655_Собеседование (E2E Лидия Автоаналитик R11-0924_1a2).webm","generated_filename":"2026-09-24_E2E_Лидия_Автоаналитик_R11-0924_1a2_Бизнес-аналитик_@Т-банк_general_interview.webm","candidate_name":"E2E Лидия Автоаналитик R11-0924_1a2","status":"completed","requires_review":false,"review_reason":"autonomous_routing_ambiguous","version":3,"found_at":"2026-09-24T04:13:56.160518+00:00","safe_link":"https://gofile.me/7g8zN/JijXc49UL","notion_url":"https://app.notion.com/p/E2E-R11-0924_1a2-3e5c8889e4c881f3a9dade9db7db8971","spot":"Бизнес-аналитик @Т-банк","error":null}],"count":2}}
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
python3 scripts/recording_agent.py route-interview --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --recording-id d561d736-a0ab-42e5-9dbe-a8e663563321 --destination-id 7bcfe562-c4e4-444c-ac66-ae2c47229af1 --expected-version 1 --idempotency-key 89506e7c-ee1a-4cd9-a34b-7fddff9291ac
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Готово: запись собеседования (E2E Лидия Автоаналитик R11-0924_1a3) сохранена.\nКарточка в Notion: https://app.notion.com/p/E2E-R11-0924_1a3-3e5c8889e4c881cda60ae2f66ea1a3e3\nЗапись: https://gofile.me/7g8zN/YQhjyaRNr","result":{"recording_id":"d561d736-a0ab-42e5-9dbe-a8e663563321","status":"completed","version":2,"safe_link":"https://gofile.me/7g8zN/YQhjyaRNr","notion_url":"https://app.notion.com/p/E2E-R11-0924_1a3-3e5c8889e4c881cda60ae2f66ea1a3e3","candidate_name":"E2E Лидия Автоаналитик R11-0924_1a3","replayed":false}}
```

</details>

**Мила:**

> Готово: запись Лидии сохранена во **внешние / Analyst**.
> 
> Карточка Notion: https://app.notion.com/p/E2E-R11-0924_1a3-3e5c8889e4c881cda60ae2f66ea1a3e3  
> Запись: https://gofile.me/7g8zN/YQhjyaRNr
> 
> Ссылка также отображается в карточке Notion.

**Судья:** 12/12 — Мила корректно обработала запрос: нашла запись через status --candidate, получила список папок через destinations, выполнила route-interview в Recruiting-E/2. Interviews external/Analyst и сообщила итог с обеими ссылками. Все действия уместны, факты совпадают с ответами бэкенда, безопасность соблюдена.

