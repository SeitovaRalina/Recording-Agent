---
type: reference
status: draft
last_updated: 2026-07-14
sources:
  - https://yandex.ru/dev/disk-api/doc/ru/concepts/quickstart
  - https://yandex.ru/dev/disk-api/doc/ru/reference/meta
  - https://yandex.ru/dev/disk-api/doc/ru/reference/all-files
  - https://yandex.ru/dev/disk-api/doc/ru/reference/content
  - https://yandex.ru/dev/disk-api/doc/ru/reference/move
  - https://yandex.ru/dev/disk-api/doc/ru/reference/delete
---

# Яндекс.Диск API

## Overview

**Base URL:** `https://cloud-api.yandex.net/v1/disk`

**Auth header** (подтверждено из docs):
```
Authorization: OAuth <access_token>
```
Важно: используется именно `OAuth`, не `Bearer`.

**Получение токена:** oauth.yandex.ru → создать приложение → получить `authorization_code` → обменять на `access_token` + `refresh_token`.

**Refresh (из auth-flow.md):**
```python
# POST https://oauth.yandex.ru/token
# Body: grant_type=refresh_token&refresh_token=...&client_id=...&client_secret=...
# Returns: {"access_token": "...", "expires_in": 3600}
```
⚠️ Страницы с описанием refresh-flow в fetched docs не обнаружены. Описание из `.memory-bank/auth-flow.md`.

---

## Операция: получить список файлов

### GET /disk/resources/files

Плоский список всех файлов диска (без иерархии).

**Параметры:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `limit` | int | 20 | Кол-во файлов |
| `offset` | int | 0 | Смещение для пагинации |
| `media_type` | string | — | Фильтр по типу: `audio,video,image,document,…` |
| `fields` | string | — | Список полей через запятую |
| `preview_size` | string | — | S/M/L/XL/XXL/XXXL или WxH |
| `preview_crop` | bool | false | Кропить превью |

⚠️ Параметр `sort` не документирован для этого endpoint. Список возвращается в алфавитном порядке.

**Пример ответа:**
```json
{
  "items": [
    {
      "name": "recording.mp4",
      "preview": "<url>",
      "created": "2026-07-13T15:30:00+03:00",
      "modified": "2026-07-13T15:31:00+03:00",
      "path": "disk:/Телемост/recording.mp4",
      "md5": "<file-md5>",
      "type": "file",
      "mime_type": "video/mp4",
      "size": 524288000
    }
  ],
  "limit": 20,
  "offset": 0
}
```

**Пагинация:** увеличивать `offset` на `limit` пока `len(items) < limit`.

**Python + httpx:**
```python
import httpx

async def list_video_files(token: str, offset: int = 0, limit: int = 20) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources/files",
            headers={"Authorization": f"OAuth {token}"},
            params={
                "media_type": "video",
                "limit": limit,
                "offset": offset,
            },
        )
        resp.raise_for_status()
        return resp.json()
```

---

## Операция: получить metadata файла

### GET /disk/resources

**Обязательный параметр:** `path` (URL-encoded путь, напр. `disk:/Телемост/recording.mp4`).

**Необязательные параметры:** `fields`, `limit`, `offset`, `sort`, `preview_size`, `preview_crop`.

**Пример ответа:**
```json
{
  "public_key": "<public-key>",
  "public_url": "https://yadi.sk/d/AaaBbb1122Ccc",
  "name": "recording.mp4",
  "path": "disk:/Телемост/recording.mp4",
  "type": "file",
  "created": "2026-07-13T15:30:00+04:00",
  "modified": "2026-07-13T15:31:00+04:00",
  "md5": "<file-md5>",
  "mime_type": "video/mp4",
  "size": 524288000,
  "preview": "<thumbnail_url>",
  "custom_properties": {}
}
```

**Python + httpx:**
```python
async def get_file_metadata(token: str, path: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources",
            headers={"Authorization": f"OAuth {token}"},
            params={"path": path},
        )
        resp.raise_for_status()
        return resp.json()
```

---

## Структура Recording File Object

Все поля, подтверждённые из официальных docs:

| Поле | Тип | Описание |
|------|-----|----------|
| `name` | string | Имя файла |
| `path` | string | Полный путь `disk:/...` |
| `type` | string | `"file"` или `"dir"` |
| `created` | string | ISO 8601 с timezone |
| `modified` | string | ISO 8601 с timezone |
| `md5` | string | MD5-хэш файла |
| `mime_type` | string | MIME-тип |
| `size` | int | Размер в байтах |
| `preview` | string | URL превью (миниатюра) |
| `public_key` | string | Ключ публичной ссылки (если опубликован) |
| `public_url` | string | Публичная ссылка (если опубликован) |
| `custom_properties` | object | Произвольные метаданные |
| `origin_path` | string | Путь до удаления (только для файлов в корзине) |

⚠️ Поля `sha256`, `revision`, `antivirus_status`, `media_type` существуют в API, но не показаны в fetched страницах docs.

---

## Операция: получить download URL + streaming download

### GET /disk/resources/download

**Обязательный параметр:** `path`.

**Ответ (200 OK):**
```json
{
  "href": "https://downloader.disk.yandex.ru/disk/...",
  "method": "GET",
  "templated": false
}
```

`href` — временный URL. Срок действия не задокументирован (описан как «ограниченный»).

**Streaming download через redirect:**
1. GET `/disk/resources/download?path=...` → получить `href`
2. GET `<href>` с `Authorization: OAuth <token>` → `200 OK` (файл) или `302 Found` → Location: `*.storage.yandex.net`
3. Если `302` — следовать редиректу к storage URL

**Python + httpx (streaming):**
```python
async def get_download_url(token: str, path: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://cloud-api.yandex.net/v1/disk/resources/download",
            headers={"Authorization": f"OAuth {token}"},
            params={"path": path},
        )
        resp.raise_for_status()
        return resp.json()["href"]


async def stream_file(token: str, download_url: str):
    """Yields chunks. Caller streams to Synology."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        async with client.stream(
            "GET",
            download_url,
            headers={"Authorization": f"OAuth {token}"},
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                yield chunk
```

---

## Mark a source as processed

### PATCH /disk/resources

The Recording Agent does not move or rename processed sources. It updates the resource at its
original path with these custom properties:

```json
{
  "custom_properties": {
    "processed": "true",
    "processed_at": "2026-07-14T09:00:00Z"
  }
}
```

`processed_at` is a UTC ISO 8601 timestamp. Discovery first filters folder-listing items by
path and media type, then requests metadata for candidates because folder listings do not
include custom properties reliably. A candidate with `processed == "true"` is skipped. If its
`processed_at` is missing or invalid, discovery PATCHes it to current UTC and still excludes the
candidate; malformed metadata must never re-enable duplicate processing.

The PATCH occurs only after the Synology upload and required downstream updates succeed. A
retry reads current metadata first; an existing valid marker is idempotent success. If only one
of `processed` or `processed_at` exists, `mark_processed()` repairs the incomplete pair rather
than skipping the resource.

---

## Seven-day retention cleanup

### DELETE /disk/resources

The daily cron selects only resources with `processed == "true"` and a parseable
`processed_at` at least seven days old. Missing, malformed, or future timestamps are not
eligible. If `processed == "true"` but `processed_at` is missing or invalid, cleanup repairs the
timestamp to current UTC and does not delete that resource during the repair run. This scheduled
operation is soft-delete-only and has no permanent-delete authority.

### Stage 1: move the source to Trash

**Parameters:**

| Parameter | Type | Default | Description |
|----------|-----|---------|----------|
| `path` | string | — | Source resource path |
| `permanently` | bool | false | Must remain `false` for the Trash stage |
| `md5` | string | — | Optional pre-delete hash check |
| `force_async` | bool | false | Request asynchronous execution |

The Recording Agent uses the default non-permanent behavior. A successful request returns 204,
or 202 with an operation to poll.

### Stage 2: permanently delete the Trash resource

### DELETE /disk/trash/resources

Permanent deletion is a separate, never-scheduled destructive operation. Each invocation
requires a `PermanentDeleteApproval` with a non-empty `approved_by` identity and timezone-aware
`approved_at` timestamp no more than five minutes old, plus a non-empty unique `nonce`.
Freshness is evaluated with an injected/trusted timezone-aware UTC clock; callers cannot pass a
`now` value. The purge consumes the nonce before its first HTTP request. That approval cannot be
reused after either success or failure. Approval cannot be supplied by a standing
environment/configuration boolean. Age eligibility, a scheduled run, or successful Trash
movement does not constitute approval.

The purge first paginates `GET /disk/trash/resources`, retrieves metadata when listing fields
are incomplete, validates `origin_path`, processed markers, and retention age, then sends DELETE
using the actual returned `trash:/...` path. It never reconstructs a Trash path from the original
Disk path.

After a partial failure, a later invocation needs a newly issued approval with a new nonce and
re-enumerates Trash, making the purge resumable without standing authority. The implementation records each stage so retries
can distinguish an already-completed stage from an unexpected 404. Disk API 401 handling is
OAuth refresh followed by exactly one retry. CalDAV authentication is unrelated: its
app-password 401 is not retried.

---

## Асинхронные операции

Endpoint: `GET https://cloud-api.yandex.net/v1/disk/operations/{operation_id}`

**Ответ:**
```json
{"status": "success"}
```

Возможные значения `status`: `"success"`, `"failed"`, `"in-progress"`.

```python
import asyncio

async def poll_operation(token: str, operation_url: str, timeout_s: int = 300) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(timeout_s // 5):
            resp = await client.get(
                operation_url,
                headers={"Authorization": f"OAuth {token}"},
            )
            resp.raise_for_status()
            status = resp.json()["status"]
            if status == "success":
                return
            if status == "failed":
                raise RuntimeError(f"Yandex Disk async operation failed: {operation_url}")
            await asyncio.sleep(5)
        raise TimeoutError(f"Operation timed out: {operation_url}")
```

---

## Telemost recordings на Яндекс.Диске

⚠️ Точный путь, где Телемост сохраняет записи, **не подтверждён в официальных docs**.

Предположительный путь: `/Телемост/` (проверить вручную после тестового звонка — Q4 из open-questions.md).

⚠️ Конвенция именования файлов Телемоста не задокументирована. Требует тестирования.

---

## Обработка ошибок

| HTTP | Описание | Действие |
|------|----------|----------|
| 201 | Успешное перемещение/копирование (файл) | OK |
| 202 | Асинхронная операция запущена | poll_operation() |
| 204 | Успешное удаление | OK |
| 401 | Невалидный/истёкший токен | refresh → retry |
| 404 | Файл не найден | log, skip |
| 409 | Конфликт (файл уже существует в destination) | log, skip или rename |
| 423 | Сервис на обслуживании | retry с backoff |
| 507 | Недостаточно места | alert, abort |

⚠️ Формат JSON-тела ошибки не подтверждён из fetched docs. Ожидаемый паттерн Яндекса: `{"error": "DiskNotFoundError", "description": "...", "message": "..."}`.

⚠️ Rate limits не документированы в fetched страницах. Рекомендуется exponential backoff на 429.

---

## Связи

- [[auth-flow]] → Яндекс OAuth setup
- [[yandex-caldav]] → получение событий для матчинга
- [[status-machine]] → статусы `found`, `source_marked_processed`, `source_deleted`
- [[data-model]] → поля `disk_file_id`, `disk_file_path`, `disk_download_url`
