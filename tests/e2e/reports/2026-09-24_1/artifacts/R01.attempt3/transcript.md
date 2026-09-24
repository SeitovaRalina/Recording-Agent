# R01 — стенограмма

## Ход 1 (40 с)

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
python3 scripts/recording_agent.py scan --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r --idempotency-key 14a2d3d1-8a17-4df4-9d6f-14f5801bfd0a
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Проверка завершена.\nНовых записей добавлено: 1.\nОбнаружено файлов для проверки: 15.\nСтарых записей пропущено (созданы до начала работы агента): 14.\nОбработано в этом запуске: 1.\nТребуют вашего уточнения: 1.\n- 2026-09-24_042317_Собеседование (E2E Олег Тестов).webm; новая запись; нужно уточнение: в Notion найдено несколько подходящих карточек\nОжидают повторной обработки: 0.\nОбработаны без вопросов: 0.\nС ошибкой: 0.","result":{"accepted":true,"recruiter_email":"ralina.seitova@effective.band","discovered":15,"inserted":1,"skipped_legacy":14,"matched":1,"manual_review":1,"without_review":0,"pending":0,"failed":0,"failed_recordings":0,"aborted":false,"errors":[],"processed":1,"items_truncated":false,"items":[{"id":"9f45d78c-a3b3-4ac5-b1c0-2dacd022da84","filename":"2026-09-24_042317_Собеседование (E2E Олег Тестов).webm","candidate_name":null,"status":"manual_review_required","is_new":true,"requires_review":true,"review_reason":"multiple_candidates","generated_filename":null,"safe_link":null,"notion_url":null,"spot":null,"error":null}]}}
```

</details>

```text
python3 scripts/recording_agent.py questions --recruiter-user-id z1cn9tz3opg6fm7e8d7phcs88r --mattermost-dm-channel-id gg3pjz8uypf3xxs33o5hhyy3ny__z1cn9tz3opg6fm7e8d7phcs88r
```

<details><summary>ответ</summary>

```text
{"ok":true,"message":"Открытых вопросов по записям: 1.\n1. 2026-09-24_042317_Собеседование (E2E Олег Тестов).webm — в Notion найдено несколько подходящих карточек\n   1) E2E Олег Тестов — 📍 Spots: Python-разработчик @Т-банк — https://app.notion.com/p/E2E-3e5c8889e4c8818e9d93fd2699e7ec7d\n   2) E2E Олег Тестов — 📍 Spots: Python-разработчик @Т-банк — https://app.notion.com/p/E2E-3e5c8889e4c88124bd8af3611f14e5da\n   3) E2E Олег Тестов — 📍 Spots: Python-разработчик @Т-банк — https://app.notion.com/p/E2E-3e5c8889e4c881178a02d5c7c20f8f71","result":{"items":[{"question_id":"9b7306e3-244e-4600-8d03-041a33b1b6f2","question_set_id":"6a291dc1-8180-4ce7-b45e-d8c6b8bbe382","recording_id":"9f45d78c-a3b3-4ac5-b1c0-2dacd022da84","recording_version":0,"filename":"2026-09-24_042317_Собеседование (E2E Олег Тестов).webm","reason":"multiple_candidates","choices":[{"id":"3e5c8889-e4c8-818e-9d93-fd2699e7ec7d","url":"https://app.notion.com/p/E2E-3e5c8889e4c8818e9d93fd2699e7ec7d","name":"E2E Олег Тестов","spot_id":"397c8889-e4c8-81d7-8bcb-f77c42da96e8","spot_url":"https://app.notion.com/p/Python-397c8889e4c881d78bcbf77c42da96e8","candidate_email":"","project_or_spot":"Python-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""},{"id":"3e5c8889-e4c8-8124-bd8a-f3611f14e5da","url":"https://app.notion.com/p/E2E-3e5c8889e4c88124bd8af3611f14e5da","name":"E2E Олег Тестов","spot_id":"397c8889-e4c8-81d7-8bcb-f77c42da96e8","spot_url":"https://app.notion.com/p/Python-397c8889e4c881d78bcbf77c42da96e8","candidate_email":"","project_or_spot":"Python-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""},{"id":"3e5c8889-e4c8-8117-8a02-d5c7c20f8f71","url":"https://app.notion.com/p/E2E-3e5c8889e4c881178a02d5c7c20f8f71","name":"E2E Олег Тестов","spot_id":"397c8889-e4c8-81d7-8bcb-f77c42da96e8","spot_url":"https://app.notion.com/p/Python-397c8889e4c881d78bcbf77c42da96e8","candidate_email":"","project_or_spot":"Python-разработчик @Т-банк","candidate_emails":[],"general_interview_date":""}],"capability":"<capability>","expires_at":"2026-09-24T01:58:01.691343+00:00"}],"count":1}}
```

</details>

**Мила:**

> Найдена 1 новая запись: **«Собеседование (E2E Олег Тестов)»**.
> 
> В Notion есть три одинаково подходящие карточки кандидата для позиции **Python-разработчик @Т-банк**. Уточните, к какой прикрепить запись:
> 
> 1. https://app.notion.com/p/E2E-3e5c8889e4c8818e9d93fd2699e7ec7d  
> 2. https://app.notion.com/p/E2E-3e5c8889e4c88124bd8af3611f14e5da  
> 3. https://app.notion.com/p/E2E-3e5c8889e4c881178a02d5c7c20f8f71  
> 
> Например: `1`.

**Судья:** 10/12 — Мила корректно обработала неоднозначность backend (3 карточки Notion) и задала понятный вопрос, но не выполнила ожидаемый сценарием R01 полный цикл scan→destinations→route-interview за один ход.

