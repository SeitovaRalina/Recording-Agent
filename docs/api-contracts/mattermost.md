---
type: reference
status: draft
last_updated: 2026-07-13
sources:
  - https://developers.mattermost.com/integrate/reference/bot-accounts/
  - https://developers.mattermost.com/integrate/reference/message-attachments/
  - https://developers.mattermost.com/integrate/plugins/interactive-messages/
  - https://developers.mattermost.com/integrate/slash-commands/custom/
  - https://developers.mattermost.com/integrate/webhooks/incoming/
  - https://github.com/mattermost/mattermost
---

# Mattermost Bot API

## Overview

**Base URL:** `https://{host}/api/v4`

**Auth header** (подтверждено):
```
Authorization: Bearer <bot_access_token>
```

Токен не истекает. Ротация через UI (System Console → Bot Accounts) или API (`RevokeUserAccessToken` + `CreateUserAccessToken`).

**Проверка токена:**
```
GET /api/v4/users/me
```

---

## Операция: найти user_id по email рекрутера

### GET /api/v4/users/email/{email}

```
GET /api/v4/users/email/recruiter@company.com
```

**Ответ 200 (User object — ключевые поля):**
```json
{
  "id": "abc123xyz...",
  "username": "anna.recruiter",
  "email": "anna@company.com",
  "first_name": "Anna",
  "last_name": "Recruiter"
}
```

Поле `id` — использовать для создания DM канала.

⚠️ Чувствительные поля могут быть скрыты в зависимости от server privacy settings.

**Ошибки:** `400` bad request, `401` unauthorized, `403` forbidden, `404` not found.

**Python + httpx:**
```python
import httpx

def _headers(bot_token: str) -> dict:
    return {"Authorization": f"Bearer {bot_token}"}

async def get_user_id_by_email(bot_token: str, base_url: str, email: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/v4/users/email/{email}",
            headers=_headers(bot_token),
        )
        resp.raise_for_status()
        return resp.json()["id"]
```

---

## Операция: создать DM канал

### POST /api/v4/channels/direct

**Body:** JSON-массив из двух user ID (бот + рекрутер).

```json
["bot_user_id", "recruiter_user_id"]
```

**Ответ 201 (Channel object):**
```json
{
  "id": "channel_id_here",
  "type": "D",
  "display_name": "",
  "name": "abc123__def456"
}
```

Идемпотентно — если DM уже существует, возвращает тот же `channel_id`.

**Python + httpx:**
```python
async def create_dm_channel(
    bot_token: str, base_url: str, bot_user_id: str, recruiter_user_id: str
) -> str:
    """Returns channel_id."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/v4/channels/direct",
            headers={**_headers(bot_token), "Content-Type": "application/json"},
            json=[bot_user_id, recruiter_user_id],
        )
        resp.raise_for_status()
        return resp.json()["id"]
```

---

## Операция: отправить сообщение

### POST /api/v4/posts

**Простое сообщение:**
```json
{
  "channel_id": "<channel_id>",
  "message": "Markdown-supported text"
}
```

**С numbered list (disambiguation):**
```json
{
  "channel_id": "<channel_id>",
  "message": "",
  "props": {
    "attachments": [
      {
        "fallback": "Manual review required for recording",
        "color": "#FF8000",
        "pretext": "⚠️ Требуется ручное сопоставление",
        "title": "Запись интервью",
        "text": "**Запись:** Telemost 2026-07-13 15-30.mp4\n**Дата:** 13.07.2026, 15:30\n**Рекрутер:** anna@company.com\n\nНайдено несколько карточек:\n1. Иванов Иван — Backend / Project A\n2. Иванов Иван — Backend / Project B\n\nОтветьте: `\"прикрепи к Project A\"`, `\"в обе\"` или вставьте Notion URL.",
        "footer": "Recording Agent"
      }
    ]
  }
}
```

**Примечание:** в REST API attachments идут в `props.attachments`. В incoming webhooks — в top-level `attachments`. Разные места!

**Python + httpx:**
```python
async def send_message(
    bot_token: str, base_url: str, channel_id: str, message: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/v4/posts",
            headers={**_headers(bot_token), "Content-Type": "application/json"},
            json={"channel_id": channel_id, "message": message},
        )
        resp.raise_for_status()
        return resp.json()


async def send_disambiguation_request(
    bot_token: str,
    base_url: str,
    channel_id: str,
    recording_name: str,
    recording_date: str,
    recruiter_email: str,
    calendar_event_title: str,
    candidates: list[str],  # ["Иванов — Project A", "Иванов — Project B"]
) -> str:
    """Returns post_id for tracking thread."""
    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(candidates))
    text = (
        f"**Запись:** {recording_name}\n"
        f"**Дата:** {recording_date}\n"
        f"**Рекрутер:** {recruiter_email}\n"
        f"**Событие календаря:** {calendar_event_title}\n\n"
        f"Найдено несколько карточек:\n{numbered}\n\n"
        f'Ответьте: `"прикрепи к N"`, `"в обе"` или вставьте Notion URL.'
    )
    body = {
        "channel_id": channel_id,
        "message": "",
        "props": {
            "attachments": [
                {
                    "fallback": "Требуется ручное сопоставление записи",
                    "color": "#FF8000",
                    "pretext": "⚠️ Требуется ручное сопоставление",
                    "title": "Запись интервью",
                    "text": text,
                    "footer": "Recording Agent",
                }
            ]
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/v4/posts",
            headers={**_headers(bot_token), "Content-Type": "application/json"},
            json=body,
        )
        resp.raise_for_status()
        return resp.json()["id"]
```

---

## Полный Post Object

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | string | Post GUID |
| `user_id` | string | User GUID автора |
| `channel_id` | string | Channel GUID |
| `message` | string | Текст сообщения |
| `create_at` | int64 | Unix milliseconds |
| `root_id` | string | Parent post ID (если reply в thread) |
| `file_ids` | string[] | Прикреплённые файлы |
| `props` | object | Произвольные данные (включая attachments) |

---

## Операция: получить ответ от рекрутера

### Вариант 1: Polling — GET /api/v4/channels/{channel_id}/posts

**Параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `since` | int64 (Unix ms) | Все посты после этого timestamp (до 1000 шт.) |
| `per_page` | int | Кол-во постов (без `since`) |
| `page` | int | Страница (без `since`) |

⚠️ `since` нельзя комбинировать с `before`, `after`, `page`, `per_page`.

**Стратегия инкрементального polling:**
```python
import asyncio
import time

async def poll_for_reply(
    bot_token: str,
    base_url: str,
    channel_id: str,
    since_ms: int,
    bot_user_id: str,
    timeout_s: int = 3600,
) -> str | None:
    """Poll until recruiter replies. Returns message text or None on timeout."""
    deadline = time.time() + timeout_s
    last_ts = since_ms

    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            resp = await client.get(
                f"{base_url}/api/v4/channels/{channel_id}/posts",
                headers=_headers(bot_token),
                params={"since": last_ts},
            )
            resp.raise_for_status()
            data = resp.json()

            for post_id in data.get("order", []):
                post = data["posts"][post_id]
                # Skip bot's own messages
                if post["user_id"] == bot_user_id:
                    continue
                if post["create_at"] > since_ms:
                    return post["message"]
                last_ts = max(last_ts, post["create_at"])

            await asyncio.sleep(30)  # poll every 30s
    return None
```

### Вариант 2: WebSocket (real-time, рекомендуется)

⚠️ Официальные WebSocket docs вернули 404 при fetching. Паттерн восстановлен из client code.

**URL:** `wss://{host}/api/v4/websocket`

**Auth после подключения:**
```json
{"seq": 1, "action": "authentication_challenge", "data": {"token": "<bot_token>"}}
```

**Событие `posted` (новый пост):**
```json
{
  "event": "posted",
  "data": {
    "channel_id": "...",
    "channel_type": "D",
    "post": "{...Post JSON as string...}",
    "sender_name": "@username"
  },
  "broadcast": {"channel_id": "..."},
  "seq": 42
}
```

⚠️ `data.post` — строка с JSON внутри (двойная сериализация). Парсить дважды: `json.loads(event["data"]["post"])`.

---

## Slash Commands: /recordings

### Регистрация команды

```
POST /api/v4/commands
```

**Body:**
```json
{
  "team_id": "<team_id>",
  "trigger": "recordings",
  "url": "https://your-agent/api/mattermost/command",
  "method": "P",
  "description": "Управление записями интервью",
  "auto_complete": true,
  "auto_complete_hint": "check | pending | status | retry <id>",
  "auto_complete_desc": "Команды агента записей"
}
```

### Что получает бот (form-encoded POST от Mattermost):

```
channel_id=...&command=/recordings&text=check&user_id=...&token=...
```

### Ответ бота на команды:

```json
{
  "response_type": "in_channel",
  "text": "Запуск проверки записей...",
  "username": "recording-agent"
}
```

Для приватных ответов (только инициатору): `"response_type": "ephemeral"`.

Медленные ответы (до 30 мин): использовать `response_url` из payload для follow-up.

**Обработчики команд:**
```python
async def handle_slash_command(payload: dict) -> dict:
    text = payload.get("text", "").strip().lower()
    
    if text == "check":
        # Trigger manual scan
        return {"response_type": "ephemeral", "text": "Запускаю проверку..."}
    elif text == "pending":
        # List manual_review_required recordings
        return {"response_type": "in_channel", "text": await get_pending_list()}
    elif text == "status":
        return {"response_type": "in_channel", "text": await get_status_summary()}
    elif text.startswith("retry "):
        rec_id = text.removeprefix("retry ").strip()
        return {"response_type": "ephemeral", "text": f"Повторяю обработку {rec_id}..."}
    else:
        return {
            "response_type": "ephemeral",
            "text": "Команды: `check`, `pending`, `status`, `retry <id>`",
        }
```

---

## Rate Limits

**Лимит по умолчанию:** 10 req/s (подтверждено).

**Response headers:**
```
X-Ratelimit-Limit: 10
X-Ratelimit-Remaining: 9
X-Ratelimit-Reset: 1720000000
```

**При 429:** тело `"limit exceeded"` (plain text). ⚠️ `Retry-After` header не верифицирован.

---

## Обработка ошибок

```json
{
  "id": "error.identifier",
  "message": "Human-readable description",
  "request_id": "string",
  "status_code": 404,
  "is_oauth": false
}
```

| HTTP | Описание | Действие |
|------|----------|---------|
| 400 | Bad params | Проверить body |
| 401 | Invalid/missing token | Проверить bot token |
| 403 | Insufficient permissions | Добавить бота в канал |
| 404 | Resource not found | Проверить IDs |
| 429 | Rate limit | Backoff + retry |

---

## Incoming Webhooks (альтернатива для notifications)

Для односторонних уведомлений (не требует чтения ответов):

```bash
curl -X POST https://mm.company.com/hooks/<webhook_key> \
  -H 'Content-Type: application/json' \
  -d '{"text": "Запись обработана!", "channel": "@recruiter"}'
```

**Ключевое отличие от Bot REST API:**
- Webhooks: `attachments` на **верхнем уровне**
- Bot REST API: `attachments` внутри `props.attachments`

---

## Связи

- [[auth-flow]] → Mattermost bot setup
- [[status-machine]] → `manual_review_required` flow
- [[data-model]] → поля `mattermost_thread_id`, `mattermost_channel_id`
- open-questions: Q3 (channel vs DM routing)
