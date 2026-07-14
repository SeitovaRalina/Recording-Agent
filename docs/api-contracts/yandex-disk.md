---
type: reference
status: draft
last_updated: 2026-07-13
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
      "md5": "4334dc6379c8f95ddf11b8508cfea271",
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
  "public_key": "HQsmHLoeyBlJf8Eu1jlmzuU+ZaLkjPkgcvmoktUCIo8=",
  "public_url": "https://yadi.sk/d/AaaBbb1122Ccc",
  "name": "recording.mp4",
  "path": "disk:/Телемост/recording.mp4",
  "type": "file",
  "created": "2026-07-13T15:30:00+04:00",
  "modified": "2026-07-13T15:31:00+04:00",
  "md5": "4334dc6379c8f95ddf11b8508cfea271",
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

## Операция: пометить файл как обработанный (move/rename)

### POST /disk/resources/move

⚠️ Метод для переименования/перемещения — `POST`, не `PATCH` (подтверждено).

**Параметры:**

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| `from` | string | Да | Исходный путь (URL-encoded) |
| `path` | string | Да | Путь назначения (URL-encoded, max 32 760 символов) |
| `overwrite` | bool | Нет (default: false) | Перезаписать если есть |
| `force_async` | bool | Нет (default: false) | Асинхронный режим |

**Ответ 201 Created** (файл или пустая папка, синхронно):
```json
{
  "href": "https://cloud-api.yandex.net/v1/disk/resources?path=disk%3A%2Fprocessed%2Frecording.mp4",
  "method": "GET",
  "templated": false
}
```

**Ответ 202 Accepted** (непустая папка, асинхронно):
```json
{
  "href": "https://cloud-api.yandex.net/v1/disk/operations?id=33ca7d03...",
  "method": "GET",
  "templated": false
}
```

**Стратегия «processed» suffix:** переместить в `/processed/filename.mp4`.

**Python + httpx:**
```python
async def mark_processed(token: str, original_path: str) -> None:
    """Move file to /processed/ folder."""
    filename = original_path.split("/")[-1]
    dest_path = f"disk:/processed/{filename}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://cloud-api.yandex.net/v1/disk/resources/move",
            headers={"Authorization": f"OAuth {token}"},
            params={"from": original_path, "path": dest_path, "overwrite": "false"},
        )
        if resp.status_code == 202:
            # async operation — poll until done
            await poll_operation(token, resp.json()["href"])
        elif resp.status_code != 201:
            resp.raise_for_status()
```

---

## Операция: удалить файл

### DELETE /disk/resources

**Параметры:**

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `path` | string | — | Путь к файлу |
| `permanently` | bool | false | Удалить навсегда (минуя корзину) |
| `md5` | string | — | Проверка хэша перед удалением |
| `force_async` | bool | false | Асинхронный режим |

⚠️ По умолчанию файл перемещается в **корзину** (не освобождает место). Для полного удаления нужен `permanently=true`.

**Ответ:** `204 No Content` (синхронно) или `202 Accepted` (асинхронно для непустых папок).

**Python + httpx:**
```python
async def delete_file(token: str, path: str, permanently: bool = True) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            "https://cloud-api.yandex.net/v1/disk/resources",
            headers={"Authorization": f"OAuth {token}"},
            params={"path": path, "permanently": str(permanently).lower()},
        )
        if resp.status_code == 202:
            await poll_operation(token, resp.json()["href"])
        elif resp.status_code != 204:
            resp.raise_for_status()
```

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
