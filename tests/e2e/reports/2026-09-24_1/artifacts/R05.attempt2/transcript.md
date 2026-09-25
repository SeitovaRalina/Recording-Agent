# R05 — стенограмма

## Ход 1 (42 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 3a441b56-157e-4c62-ade7-3d4eb2b1093d
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_052301_Собеседование (E2E Павел Двуспотов R05-0924_1a2).webm; новая запись; нужно уточнение: у карточки несколько проектов (📍 Spots), нужно выбрать один\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"090002a3-e24d-4f26-ad6d-98b91f7ea55a","filename":"2026-09-24_052301_Собеседование (E2E Павел Двуспотов R05-0924_1a2).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"multiple_spots","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null}]}}
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_052301_Собеседование (E2E Павел Двуспотов R05-0924_1a2).webm — у карточки несколько проектов (📍 Spots), нужно выбрать один\n   1) E2E Павел Двуспотов R05-0924_1a2 — 📍 Spots: Python-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602\n   2) E2E Павел Двуспотов R05-0924_1a2 — 📍 Spots: Java-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602","result":{"items":[{"question_id":"ce049c5a-eb72-4fb0-8e68-cfcc51ecbc9e","question_set_id":"13f67eb8-6402-476a-9ed8-7c1704580862","recording_id":"090002a3-e24d-4f26-ad6d-98b91f7ea55a","recording_version":0,"filename":"2026-09-24_052301_Собеседование (E2E Павел Двуспотов R05-0924_1a2).webm","reason":"multiple_spots","choices":[{"id":"3e5c8889-e4c8-8109-bdbd-c5e1cbc23602","url":"https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602","name":"E2E Павел Двуспотов R05-0924_1a2","spot_id":"397c8889-e4c8-81d7-8bcb-f77c42da96e8","spot_url":"https://app.notion.com/p/Python-397c8889e4c881d78bcbf77c42da96e8","candidate_email":"","project_or_spot":"Python-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""},{"id":"3e5c8889-e4c8-8109-bdbd-c5e1cbc23602","url":"https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602","name":"E2E Павел Двуспотов R05-0924_1a2","spot_id":"397c8889-e4c8-8118-ac1b-e5efbe7f83f2","spot_url":"https://app.notion.com/p/Java-397c8889e4c88118ac1be5efbe7f83f2","candidate_email":"","project_or_spot":"Java-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""}],"capability":"<capability>","expires_at":"2026-09-24T02:57:55.548746+00:00"}],"count":1}}
```

</details>

**Мила:**

> Нашла 1 новую запись — собеседование с Павлом Двуспотовым. В карточке указаны два проекта, нужно выбрать:
> 
> 1. **Python-разработчик @Т-банк** — рекомендую этот вариант: в названии записи нет указания на Java, поэтому Python выглядит более вероятным.
> 2. **Java-разработчик @Т-банк**
> 
> Ответьте, например: **«1 — Python»** или **«2 — Java»**.

**Судья:** 10/12 — Корректная последовательность scan+questions, всё доведено до вопроса за один ход, но пропущены ссылки на споты и дана непрошеная рекомендация вместо нейтрального уточнения.

## Ход 2 (45 с)

**Рекрутер:**

> По джаве

**Команды:**

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_052301_Собеседование (E2E Павел Двуспотов R05-0924_1a2).webm — у карточки несколько проектов (📍 Spots), нужно выбрать один\n   1) E2E Павел Двуспотов R05-0924_1a2 — 📍 Spots: Python-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602\n   2) E2E Павел Двуспотов R05-0924_1a2 — 📍 Spots: Java-разработчик @Т-банк — https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602","result":{"items":[{"question_id":"ce049c5a-eb72-4fb0-8e68-cfcc51ecbc9e","question_set_id":"13f67eb8-6402-476a-9ed8-7c1704580862","recording_id":"090002a3-e24d-4f26-ad6d-98b91f7ea55a","recording_version":0,"filename":"2026-09-24_052301_Собеседование (E2E Павел Двуспотов R05-0924_1a2).webm","reason":"multiple_spots","choices":[{"id":"3e5c8889-e4c8-8109-bdbd-c5e1cbc23602","url":"https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602","name":"E2E Павел Двуспотов R05-0924_1a2","spot_id":"397c8889-e4c8-81d7-8bcb-f77c42da96e8","spot_url":"https://app.notion.com/p/Python-397c8889e4c881d78bcbf77c42da96e8","candidate_email":"","project_or_spot":"Python-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""},{"id":"3e5c8889-e4c8-8109-bdbd-c5e1cbc23602","url":"https://app.notion.com/p/E2E-R05-0924_1a2-3e5c8889e4c88109bdbdc5e1cbc23602","name":"E2E Павел Двуспотов R05-0924_1a2","spot_id":"397c8889-e4c8-8118-ac1b-e5efbe7f83f2","spot_url":"https://app.notion.com/p/Java-397c8889e4c88118ac1be5efbe7f83f2","candidate_email":"","project_or_spot":"Java-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""}],"capability":"<capability>","expires_at":"2026-09-24T02:57:55.548746+00:00"}],"count":1}}
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
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"ce049c5a-eb72-4fb0-8e68-cfcc51ecbc9e","question_set_id":"13f67eb8-6402-476a-9ed8-7c1704580862","action":"choose_spot","choice":"397c8889-e4c8-8118-ac1b-e5efbe7f83f2","capability":"<capability>","version":0,"idempotency_key":"5a47e8aa-3d9a-4ab9-987e-4aecbe493fb7"}]'
```

<details><summary>ответ</summary>

```text
{"ok":false,"message":"Не удалось выполнить запрос Recording Agent: Question action contains unsupported fields","error":"Question action contains unsupported fields"}

(Command exited with code 1)
```

</details>

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
python3 scripts/recording_agent.py answer --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --actions-json '[{"question_id":"ce049c5a-eb72-4fb0-8e68-cfcc51ecbc9e","question_set_id":"13f67eb8-6402-476a-9ed8-7c1704580862","action":"resolve","choice":2,"capability":"<capability>","expected_version":0,"idempotency_key":"5a47e8aa-3d9a-4ab9-987e-4aecbe493fb7"}]'
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Принято ответов: 1; отклонено: 0; ещё ждут ответа: 0.\nОбработка по принятым ответам запущена.","result":{"accepted":[{"question_id":"ce049c5a-eb72-4fb0-8e68-cfcc51ecbc9e","recording_id":"090002a3-e24d-4f26-ad6d-98b91f7ea55a","status":"candidate_matched","version":1,"replayed":false}],"rejected":[],"pending":[]}}
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

> Приняла: **Java-разработчик @Т-банк**. Ответ сохранён, запись готова к размещению.
> 
> Папки Java среди доступных нет. Уточните, пожалуйста, куда её сохранить: создать папку **Java** во **внешних** или во **внутренних** интервью? Рекомендую **во внешних**.

**Судья:** 0/12 — 

