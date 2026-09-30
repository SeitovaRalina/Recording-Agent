# Inspecting production data (read-only)

How an agent checks that a recruiter's production data sources are reachable and pulls the
information needed to analyse them (calendar events, Disk file names, Notion schemas, Synology
roots, Mattermost DM). Everything here is **read-only**; any write to production needs the user's
explicit confirmation and is out of scope of this page.

## Prerequisites

- SSH to the server works only while the passphrase-protected key `~/.ssh/access_K0DE` is loaded
  into the Windows ssh-agent. Symptom when it is not: "Server accepts key" then "Permission denied
  (publickey)". Ask the user to run (admin PowerShell) `Start-Service ssh-agent` and
  `ssh-add $env:USERPROFILE\.ssh\access_K0DE`. Never ask for or handle the passphrase.
- Use the poetry venv interpreter from the repo root:
  `C:/Users/seito/AppData/Local/pypoetry/Cache/virtualenvs/recording-agent-iHkGfopY-py3.13/Scripts/python.exe`.
- In Git Bash prefix commands that pass absolute server paths with `MSYS_NO_PATHCONV=1`
  (otherwise `/Recruiting-NE/…` becomes `C:/Program Files/Git/Recruiting-NE/…`).
- Transport: `tests/e2e/lib/remote.py` (`bash`, `stand`, `psql`). Secrets never leave the server:
  remote code reads them from the backend container settings or `/etc/recording-agent/backend.env`.

## The tool: `tests/e2e/inspect_prod.py`

`python -u -X utf8 -m tests.e2e.inspect_prod <command>`

| Command | What it shows | Credentials |
|---|---|---|
| `notion-search` | every database the Notion connection can see | `NOTION_TOKEN_PROD` from local `.env` |
| `notion-db <id or URL>` | fields with types, relation targets, last edit; 404 = connection not added | same |
| `disk --email E [--folder F] [--limit N]` | newest files in a Disk folder (default «Записи Телемоста»), `processed` marker | backend token manager (onboarded recruiter) |
| `disk --email E --token-file /root/<name>-yandex-refresh-token` | same, before onboarding | root-only file on the host; Yandex ROTATES the refresh token, the file is rewritten |
| `calendar --email E [--env .env.<name>] [--calendar NAME] [--days-back N] [--days-ahead N] [--full] [--recurring]` | calendars, then events: start, title, link hosts; `--full` adds description, location, organizer; recurring series hidden by default | backend `YANDEX_CALDAV_PASSWORDS`, or the local `.env.<name>` before onboarding |
| `synology <path> …` | whether paths exist | backend settings (via `stand syno_exists`) |
| `mattermost --email E` | user id by e-mail, DM channel with the bot, message count | backend settings |

Other read-only building blocks: `remote.stand("sql", {"query": "select …", "params": {}})`
(SELECT only) for backend state — tables `recordings`, `manual_reviews`, `recruiter_config`,
`recruiter_calendar`, `notification_outbox`, `question_digests`, `routing_jobs`;
`remote.stand("disk_list")` for the default recruiter's Disk.

## Order for a new recruiter (user requirement)

1. Visibility first, nothing changed: `notion-db` for the interviews DB and every related DB
   (vacancies, candidates), `calendar` (401 = wrong app password — Yandex app passwords are 16
   lowercase letters), `disk`, `synology` for their production roots (no `/home` prefix — `/home/…`
   is a test copy), `mattermost` (the id the recruiter sends may be wrong; trust the e-mail lookup).
2. Record findings in `.memory-bank/current-work.md`; recruiter credentials live only in the
   git-ignored `.env.<name>` and on the server.
3. Only then, with the user's confirmation, change production config.

## Rules for the output

- Output contains real candidate names and meeting titles: keep it in the session, never commit it,
  never paste it into shared chats or updates. Summaries may use patterns («Собеседование с <Имя
  Фамилия>»), not names.
- Never print tokens, passwords, OAuth codes. If a helper would print one, change the helper.
- Do not commit or push anything unless the user says so.
