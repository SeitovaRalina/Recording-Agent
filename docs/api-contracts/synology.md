---
type: reference
status: draft
last_updated: 2026-07-13
sources:
  - https://github.com/N4S4/synology-api
  - https://global.download.synology.com/download/Document/Software/DeveloperGuide/Os/DSM/All/enu/DSM_Login_Web_API_Guide_enu.pdf
  - https://www.synology.com/en-global/support/developer
---

# Synology File Station API

## Overview

**Base URL pattern:**
```
http://{host}:{port}/webapi/
```

Порты:
- HTTP: `5000`
- HTTPS: `5001` (рекомендуется)

**Главный endpoint для всех FileStation операций:**
```
/webapi/entry.cgi
```

**Auth endpoint (для SID-метода):**
```
/webapi/auth.cgi
```

**API Discovery** — узнать актуальные версии и пути:
```
GET /webapi/query.cgi?api=SYNO.API.Info&version=1&method=query&query=all
```
Возвращает карту `api_name → {path, minVersion, maxVersion}`.

---

## API Versioning

Все запросы передают `api`, `version`, `method` как параметры.

- Для большинства API использовать `version=<maxVersion>`
- Для `SYNO.FileStation.Upload` использовать `version=<minVersion>` (обычно `1`)
- `maxVersion` и `minVersion` получать из SYNO.API.Info discovery

---

## Auth: Session SID (подтверждено)

**Login request:**
```
GET /webapi/auth.cgi
```

**Параметры:**

| Параметр | Значение |
|----------|----------|
| `api` | `SYNO.API.Auth` |
| `version` | `7` (для DSM 7) |
| `method` | `login` |
| `account` | username |
| `passwd` | password |
| `enable_syno_token` | `yes` |
| `session` | `webui` |
| `format` | `cookie` (или `sid` для явного возврата SID) |
| `otp_code` | (опционально, для 2FA) |

**Ответ (успех):**
```json
{
  "success": true,
  "data": {
    "sid": "AbCdEf123456...",
    "synotoken": "XyZ789..."
  }
}
```

**Использование SID в запросах:**
- Query param: `&_sid=<sid>`
- Cookie: `id=<sid>` (если `format=cookie`)

**CSRF token (synotoken):** передавать в header `X-SYNO-TOKEN: <synotoken>` для всех upload-запросов.

**Logout:**
```
GET /webapi/entry.cgi?api=SYNO.API.Auth&version=6&method=logout&_sid=<sid>
```

**Re-auth при истечении SID:** ловить error code `106` (session timeout) или `119` (invalid session).

---

## Auth: API Key / PAT (DSM 7.0+)

⚠️ **Не верифицировано из официальных docs** — KB страница недоступна при fetching.

Предположительно (из косвенных источников):
- PAT создаётся в DSM → Personal → Account → Access Token
- Передаётся как: `Authorization: Bearer <token>` или query param `_sid=<token>`
- Точное имя параметра/header не подтверждено

Решение: использовать Session SID как основной метод (ADR-005). Если DSM ≥ 7.0 — Q2 из open-questions.md.

---

## Python + httpx: инициализация клиента

```python
import httpx

class SynologyClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/webapi/"
        self._sid: str | None = None
        self._synotoken: str | None = None

    async def login(self, account: str, passwd: str) -> None:
        async with httpx.AsyncClient(verify=False) as client:
            resp = await client.get(
                self.base_url + "auth.cgi",
                params={
                    "api": "SYNO.API.Auth",
                    "version": "7",
                    "method": "login",
                    "account": account,
                    "passwd": passwd,
                    "enable_syno_token": "yes",
                    "session": "webui",
                    "format": "cookie",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(f"Synology login failed: {data}")
            self._sid = data["data"]["sid"]
            self._synotoken = data["data"]["synotoken"]

    def _params(self, **kwargs) -> dict:
        return {"_sid": self._sid, **kwargs}
```

---

## Операция: список файлов в папке

### SYNO.FileStation.List — method=list

**HTTP:** GET `/webapi/entry.cgi`

**Параметры:**

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| `api` | string | Да | `SYNO.FileStation.List` |
| `version` | int | Да | maxVersion |
| `method` | string | Да | `list` |
| `folder_path` | string | Да | Путь к папке, напр. `/volume1/recordings` |
| `offset` | int | Нет | Смещение |
| `limit` | int | Нет | Кол-во файлов |
| `sort_by` | string | Нет | `name`, `size`, `time`, `type` |
| `sort_direction` | string | Нет | `asc` / `desc` |
| `pattern` | string | Нет | Glob-фильтр |
| `filetype` | string | Нет | `file` / `dir` / `all` |
| `additional` | list | Нет | `["real_path","size","owner","time"]` |

**Структура ответа:**
```json
{
  "success": true,
  "data": {
    "total": 42,
    "offset": 0,
    "files": [
      {
        "name": "recording.mp4",
        "path": "/volume1/recordings/recording.mp4",
        "isdir": false,
        "additional": {
          "real_path": "/volume1/recordings/recording.mp4",
          "size": 524288000,
          "owner": {"user": "admin", "group": "users"},
          "time": {"atime": 1720000000, "mtime": 1720000000, "crtime": 1720000000}
        }
      }
    ]
  }
}
```

**Python + httpx:**
```python
async def list_folder(self, folder_path: str, limit: int = 100) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            self.base_url + "entry.cgi",
            params=self._params(
                api="SYNO.FileStation.List",
                version="2",
                method="list",
                folder_path=folder_path,
                filetype="file",
                limit=limit,
                additional='["size","time"]',
            ),
        )
        resp.raise_for_status()
        data = resp.json()
        if not data["success"]:
            raise RuntimeError(f"List failed: {data['error']}")
        return data["data"]["files"]
```

---

## Операция: создать папку

### SYNO.FileStation.CreateFolder — method=create

**HTTP:** GET `/webapi/entry.cgi`

**Параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `api` | string | `SYNO.FileStation.CreateFolder` |
| `version` | int | maxVersion |
| `method` | string | `create` |
| `folder_path` | string | Путь к родительской папке |
| `name` | string | Имя новой папки |
| `force_parent` | bool | Создать родителей если нет ⚠️ поведение не верифицировано |

**Ответ:**
```json
{
  "success": true,
  "data": {
    "folders": [
      {"name": "2026-07", "path": "/volume1/recordings/2026-07", "isdir": true}
    ]
  }
}
```

**Python + httpx:**
```python
async def create_folder(
    self, parent_path: str, folder_name: str, force_parent: bool = True
) -> str:
    """Returns path of created folder."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            self.base_url + "entry.cgi",
            params=self._params(
                api="SYNO.FileStation.CreateFolder",
                version="2",
                method="create",
                folder_path=parent_path,
                name=folder_name,
                force_parent=str(force_parent).lower(),
            ),
        )
        resp.raise_for_status()
        data = resp.json()
        if not data["success"]:
            raise RuntimeError(f"CreateFolder failed: {data['error']}")
        return data["data"]["folders"][0]["path"]
```

---

## Операция: загрузить файл (multipart upload)

### SYNO.FileStation.Upload — method=upload

**HTTP:** POST `/webapi/entry.cgi` (multipart/form-data)

⚠️ Версия: использовать `minVersion` (обычно `1`), не maxVersion.

**URL query string:**
```
/webapi/entry.cgi?api=SYNO.FileStation.Upload&version=1&method=upload&_sid=<sid>
```

**Multipart form fields:**

| Поле | Значение |
|------|----------|
| `path` | Путь назначения (папка) |
| `create_parents` | `"true"` / `"false"` |
| `overwrite` | `"true"` / `"false"` |
| `file` | Бинарные данные файла с именем в Content-Disposition |

**Header:** `X-SYNO-TOKEN: <synotoken>`

⚠️ Chunked/resumable upload не задокументирован. Весь файл передаётся в одном POST.

**Python + httpx (с streaming из Яндекс.Диска):**
```python
async def upload_file_stream(
    self,
    dest_folder: str,
    filename: str,
    file_stream,  # async generator yielding bytes
    overwrite: bool = False,
) -> None:
    """Upload from async generator (stream from Yandex Disk) to Synology."""
    # Collect chunks — Synology doesn't support streaming multipart
    # For large files, fallback to temp file (see ADR-004)
    chunks = []
    async for chunk in file_stream:
        chunks.append(chunk)
    file_bytes = b"".join(chunks)

    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(
            self.base_url + "entry.cgi",
            params={
                "api": "SYNO.FileStation.Upload",
                "version": "1",
                "method": "upload",
                "_sid": self._sid,
            },
            headers={"X-SYNO-TOKEN": self._synotoken},
            files={
                "path": (None, dest_folder),
                "create_parents": (None, "true"),
                "overwrite": (None, str(overwrite).lower()),
                "file": (filename, file_bytes, "application/octet-stream"),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Upload failed: {data.get('error')}")
```

---

## Операция: создать share link

### SYNO.FileStation.Sharing — method=create

**HTTP:** GET `/webapi/entry.cgi`

**Параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `api` | string | `SYNO.FileStation.Sharing` |
| `version` | int | maxVersion |
| `method` | string | `create` |
| `path` | string | Путь к файлу |
| `password` | string | Пароль (опционально) |
| `date_expired` | string | Дата истечения ⚠️ формат не верифицирован, предположительно `"YYYY-MM-DD"` |
| `expire_times` | int | Лимит обращений (0 = безлимит) |

**Ответ:**
```json
{
  "success": true,
  "data": {
    "links": [
      {
        "id": "AbcXyz123",
        "url": "https://nas.company.com/sharing/AbcXyz123",
        "link_owner": "admin",
        "path": "/volume1/recordings/recording.mp4",
        "isFolder": false,
        "has_password": false,
        "status": "valid"
      }
    ]
  }
}
```

⚠️ Структура ответа восстановлена из N4S4/synology-api — не из официальных docs.

**Получить URL:** `data["links"][0]["url"]`

**Python + httpx:**
```python
async def create_share_link(self, file_path: str) -> str:
    """Returns public share URL."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            self.base_url + "entry.cgi",
            params=self._params(
                api="SYNO.FileStation.Sharing",
                version="3",
                method="create",
                path=file_path,
            ),
        )
        resp.raise_for_status()
        data = resp.json()
        if not data["success"]:
            raise RuntimeError(f"Create share link failed: {data['error']}")
        return data["data"]["links"][0]["url"]
```

---

## Структура ответа Synology

**Успех:**
```json
{"success": true, "data": {...}}
```

**Ошибка:**
```json
{
  "success": false,
  "error": {
    "code": 408,
    "errors": [{"code": 414, "path": "/missing/path"}]
  }
}
```

Правило: проверять `response["success"] == True`.

---

## Error Codes

### Общие (все API)

| Код | Описание | Действие |
|-----|----------|----------|
| 100 | Unknown error | log, retry |
| 101 | Missing parameter | проверить params |
| 102 | API не существует | проверить api name |
| 103 | Method не существует | проверить method |
| 104 | Версия не поддерживает функциональность | снизить version |
| 105 | Нет прав для операции | проверить разрешения |
| 106 | Session timeout | re-login |
| 107 | Дублированный login | ok, использовать новый SID |
| 119 | Invalid session | re-login |

### SYNO.API.Auth

| Код | Описание |
|-----|----------|
| 400 | Нет аккаунта или неверный пароль |
| 401 | Аккаунт заблокирован |
| 402 | Permission denied |
| 403 | 2FA required |
| 404 | Неверный 2FA code |

### SYNO.FileStation

| Код | Описание |
|-----|----------|
| 400 | Invalid parameter |
| 408 | Недопустимое имя файла/папки (спецсимволы) |
| 414 | Файл уже существует / путь не найден |
| 415 | Превышена квота диска |
| 416 | Нет места |
| 418 | Недопустимое имя |
| 419 | Недопустимое имя файла |
| 1100 | Failed to create folder |

⚠️ Коды 408 и 414 имеют разные значения в SYNO.API.Auth и SYNO.FileStation. Официальные PDF были бинарными — точное разграничение не верифицировано.

---

## Связи

- [[auth-flow]] → Synology API key / SID setup
- [[status-machine]] → `transfer_started`, `uploaded_to_synology`, `synology_link_created`
- [[data-model]] → поля `synology_folder`, `synology_file_path`, `synology_share_url`
- open-questions: Q1 (folder structure), Q2 (DSM version)
