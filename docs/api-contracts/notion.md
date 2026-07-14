---
type: reference
status: draft
last_updated: 2026-07-13
sources:
  - https://developers.notion.com/reference/intro
  - https://developers.notion.com/reference/post-database-query
  - https://developers.notion.com/reference/retrieve-a-database
  - https://developers.notion.com/reference/errors
  - https://developers.notion.com/docs/working-with-databases
---

# Notion API

## Overview

**Base URL:** `https://api.notion.com/v1`

**Auth headers** (обязательны все три):
```
Authorization: Bearer <notion_token>
Notion-Version: 2026-03-11
Content-Type: application/json
```

⚠️ **Актуальная версия `Notion-Version`: `2026-03-11`** (не `2022-06-28` — устарела).

Без заголовка `Notion-Version` API вернёт `400 missing_version`.

**Токен:** Internal Integration token (`secret_xxx...`). Создаётся на notion.so/my-integrations. Не истекает.

**Важно:** интеграция должна быть добавлена к каждой базе данных через меню `···` → Connections → Add connection.

---

## Операция: получить схему БД

### GET /v1/databases/{database_id}

Возвращает metadata базы данных.

⚠️ **Deprecation notice:** с версии `2025-09-03` список свойств (property schema) вынесен в новый endpoint `/v1/data-sources/{id}`. В текущей версии `2026-03-11` проверить, возвращает ли `GET /databases/{id}` поле `properties` — если нет, использовать новый endpoint.

**Ответ (поля верхнего уровня):**
```json
{
  "object": "database",
  "id": "abc123-...",
  "title": [{"type": "text", "plain_text": "Interviews DB"}],
  "description": [],
  "parent": {"type": "page_id", "page_id": "..."},
  "is_inline": false,
  "in_trash": false,
  "created_time": "2026-01-01T00:00:00.000Z",
  "last_edited_time": "2026-07-13T00:00:00.000Z",
  "data_sources": [{"id": "uuid", "name": "Source Name"}],
  "url": "https://www.notion.so/..."
}
```

**Как определить ID свойства (для старых версий):**
```python
db = await get_database(database_id)
# db["properties"]["General Interview Date"]["id"]  # → property_id
# db["properties"]["General Interview Date"]["type"]  # → "date"
```

Каждая база имеет ровно одно свойство с `"type": "title"`. Его отображаемое имя произвольное (не всегда `"Name"`).

**Python + httpx:**
```python
import httpx

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2026-03-11",
        "Content-Type": "application/json",
    }

async def get_database_schema(token: str, database_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.notion.com/v1/databases/{database_id}",
            headers=_headers(token),
        )
        resp.raise_for_status()
        return resp.json()
```

---

## Операция: поиск карточек

### POST /v1/databases/{database_id}/query

⚠️ Endpoint объявлен deprecated с `2025-09-03`. Замена: `POST /v1/data-sources/{id}/query`. Синтаксис фильтров совместим.

**Параметры тела запроса:**

| Поле | Тип | Описание |
|------|-----|----------|
| `filter` | object | Условие фильтрации |
| `sorts` | array | Сортировка |
| `start_cursor` | string | Курсор пагинации |
| `page_size` | int | Кол-во результатов (max 100, default 100) |

### Фильтры

**Title contains:**
```json
{
  "property": "Name",
  "title": {"contains": "Иванов"}
}
```

**Date equals:**
```json
{
  "property": "General Interview Date",
  "date": {"equals": "2026-07-13"}
}
```

**Date on_or_after / on_or_before:**
```json
{"property": "General Interview Date", "date": {"on_or_after": "2026-07-01"}}
{"property": "General Interview Date", "date": {"on_or_before": "2026-07-31"}}
```

**AND compound filter:**
```json
{
  "filter": {
    "and": [
      {"property": "Name", "title": {"contains": "Иванов"}},
      {"property": "General Interview Date", "date": {"on_or_after": "2026-07-13"}},
      {"property": "General Interview Date", "date": {"on_or_before": "2026-07-13"}}
    ]
  }
}
```

**Формат дат:** ISO 8601 `"YYYY-MM-DD"`.

⚠️ Синтаксис `title` и `date` фильтров не показан на странице `/reference/post-database-query` — восстановлен из смежных страниц API.

### Пример полного запроса

```bash
curl -X POST https://api.notion.com/v1/databases/DATABASE_ID/query \
  -H "Authorization: Bearer secret_xxx" \
  -H "Notion-Version: 2026-03-11" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "and": [
        {"property": "Name", "title": {"contains": "Иванов Иван"}},
        {"property": "General Interview Date", "date": {"on_or_after": "2026-07-13"}},
        {"property": "General Interview Date", "date": {"on_or_before": "2026-07-13"}}
      ]
    },
    "page_size": 10
  }'
```

### Пример ответа

```json
{
  "object": "list",
  "results": [
    {
      "object": "page",
      "id": "3d6c6e3b-1234-abcd-5678-9ef012345678",
      "created_time": "2026-07-01T09:00:00.000Z",
      "last_edited_time": "2026-07-10T12:00:00.000Z",
      "in_trash": false,
      "url": "https://www.notion.so/3d6c6e3b...",
      "public_url": null,
      "parent": {"type": "database_id", "database_id": "DATABASE_ID"},
      "properties": {
        "Name": {
          "id": "title",
          "type": "title",
          "title": [
            {
              "type": "text",
              "text": {"content": "Иванов Иван", "link": null},
              "plain_text": "Иванов Иван",
              "href": null
            }
          ]
        },
        "General Interview Date": {
          "id": "abc%3D",
          "type": "date",
          "date": {"start": "2026-07-13", "end": null, "time_zone": null}
        },
        "General Interview recording": {
          "id": "xyz%3D",
          "type": "url",
          "url": null
        }
      }
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

**Python + httpx:**
```python
async def search_candidate_cards(
    token: str,
    database_id: str,
    candidate_name: str,
    interview_date: str,  # "YYYY-MM-DD"
) -> list[dict]:
    """Search Notion DB for candidate by name + date. Returns page objects."""
    body = {
        "filter": {
            "and": [
                {"property": "Name", "title": {"contains": candidate_name}},
                {"property": "General Interview Date", "date": {"on_or_after": interview_date}},
                {"property": "General Interview Date", "date": {"on_or_before": interview_date}},
            ]
        },
        "page_size": 20,
    }

    results = []
    start_cursor = None
    async with httpx.AsyncClient() as client:
        while True:
            if start_cursor:
                body["start_cursor"] = start_cursor
            resp = await client.post(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                headers=_headers(token),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            results.extend(data["results"])
            if not data["has_more"]:
                break
            start_cursor = data["next_cursor"]
    return results
```

---

## Структура Page Object — как читать поля

### Вспомогательные функции

```python
def get_title(page: dict, prop_name: str) -> str | None:
    prop = page["properties"].get(prop_name, {})
    title_items = prop.get("title", [])
    return "".join(t.get("plain_text", "") for t in title_items) or None

def get_date(page: dict, prop_name: str) -> str | None:
    prop = page["properties"].get(prop_name, {})
    date_obj = prop.get("date")
    return date_obj["start"] if date_obj else None

def get_url(page: dict, prop_name: str) -> str | None:
    prop = page["properties"].get(prop_name, {})
    return prop.get("url")

def get_rich_text(page: dict, prop_name: str) -> str | None:
    prop = page["properties"].get(prop_name, {})
    items = prop.get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in items) or None
```

### Типы свойств

| Тип | Структура в `properties` |
|-----|--------------------------|
| `title` | `{"type": "title", "title": [{"plain_text": "..."}]}` |
| `rich_text` | `{"type": "rich_text", "rich_text": [{"plain_text": "..."}]}` |
| `date` | `{"type": "date", "date": {"start": "YYYY-MM-DD", "end": null}}` |
| `url` | `{"type": "url", "url": "https://..."}` |
| `number` | `{"type": "number", "number": 1.49}` |
| `formula` | ⚠️ `{"type": "formula", "formula": {"type": "string", "string": "..."}}` (структура из отдельной страницы docs) |
| `relation` | ⚠️ `{"type": "relation", "relation": [{"id": "<page-uuid>"}]}` (структура из отдельной страницы docs) |

---

## Операция: обновить url-поле карточки

### PATCH /v1/pages/{page_id}

⚠️ Страница `/reference/update-page` вернула 404 при fetching. Структура восстановлена из смежных страниц.

**Обновление url-поля:**
```json
PATCH https://api.notion.com/v1/pages/{page_id}

{
  "properties": {
    "General Interview recording": {
      "url": "https://synology.company.com/sharing/AbcXyz123"
    }
  }
}
```

**Ответ:** обновлённый Page object (полный).

**Python + httpx:**
```python
async def update_recording_url(
    token: str,
    page_id: str,
    synology_url: str,
    recording_field: str = "General Interview recording",
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_headers(token),
            json={"properties": {recording_field: {"url": synology_url}}},
        )
        resp.raise_for_status()
        return resp.json()
```

---

## Pagination

| Параметр | Где | Описание |
|----------|-----|----------|
| `page_size` | тело (POST) / query string (GET) | Default 100, max 100 |
| `start_cursor` | тело (POST) / query string (GET) | Передать `next_cursor` из ответа |
| `has_more` | ответ | `true` если есть ещё |
| `next_cursor` | ответ | `null` если это последняя страница |

---

## Rate limits и стратегия retry

| Параметр | Значение |
|----------|----------|
| HTTP 429 | `rate_limited` |
| При 503/504 | Service overload — использовать `Retry-After` header |

⚠️ Точное значение req/s не задокументировано на fetched страницах. Общеизвестное значение — 3 req/s на integration, но не верифицировано из официальных docs.

```python
import asyncio

async def notion_request_with_retry(client: httpx.AsyncClient, *args, **kwargs) -> httpx.Response:
    for attempt in range(5):
        resp = await client.request(*args, **kwargs)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
            await asyncio.sleep(retry_after)
            continue
        if resp.status_code in (503, 504, 529):
            retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
            await asyncio.sleep(retry_after)
            continue
        return resp
    resp.raise_for_status()
    return resp
```

---

## Обработка ошибок

Все ошибки возвращают:
```json
{"code": "machine_readable_code", "message": "Human-readable detail"}
```

| HTTP | code | Причина | Действие |
|------|------|---------|----------|
| 400 | `validation_error` | Схема тела не совпадает | Проверить поля |
| 400 | `missing_version` | Нет заголовка `Notion-Version` | Добавить header |
| 401 | `unauthorized` | Невалидный токен | Проверить NOTION_TOKEN |
| 403 | `restricted_resource` | Интеграция не добавлена к БД | Добавить Connection в Notion UI |
| 404 | `object_not_found` | Ресурс не найден / не расшарен | Проверить database_id |
| 409 | `conflict_error` | Конфликт транзакций | Повторить запрос |
| 429 | `rate_limited` | Лимит запросов | Exponential backoff |

---

## Notion topology (из decisions.md)

- Один `NOTION_TOKEN` (Internal Integration) на всех рекрутеров
- Per-recruiter `database_id` mapping в config:
  ```python
  RECRUITER_NOTION_DB_IDS = {
      "anton@company.com": "abc123-...",
      "lili@company.com": "def456-...",   # TBD
  }
  ```

---

## Связи

- [[auth-flow]] → Notion token setup
- [[status-machine]] → `candidate_matched`, `notion_updated`
- [[data-model]] → поля `notion_database_id`, `notion_page_id`, `notion_page_url`
- open-questions: Q5 (database IDs + property IDs), Q8 (Lili's DB schema)
