# Wiki Agent — Prompt

Используй этот prompt для запуска агента, который исследует реальные API и пишет точную техническую документацию проекта Recording Agent.

**Важно:** агент сначала ИССЛЕДУЕТ официальные документации через WebFetch/WebSearch, потом ПИШЕТ файлы. Не из головы.

---

## Prompt для агента

```
Ты — технический исследователь и автор документации для проекта Recording Agent.

Твоя задача в двух шагах:
1. RESEARCH — исследуй реальные официальные документации через WebFetch/WebSearch
2. WRITE — напиши точные технические документы на основе того, что нашёл

## Контекст проекта (читай сначала)

- `TOR.md` — оригинальные требования
- `.memory-bank/index.md` — обзор проекта, стек, интеграции
- `.memory-bank/architecture.md` — компоненты и потоки данных
- `.memory-bank/auth-flow.md` — авторизация
- `.memory-bank/decisions.md` — принятые решения

## Шаг 1: Параллельный Research

Запусти следующих субагентов ОДНОВРЕМЕННО (в одном tool-call message).
Каждый субагент возвращает structured digest — не пишет файлы.

---

### SubAgent 1: Яндекс.Диск API

Исследуй: https://yandex.ru/dev/disk/rest/

Найди и верни digest с:
- Точный base URL (`cloud-api.yandex.net/v1/disk` — подтверди)
- Как передавать OAuth token (header name, format)
- GET /disk/resources — параметры для получения metadata файла
- GET /disk/resources/files — flat file list, параметры пагинации, фильтрации по типу/дате
- GET /disk/resources/download — как получить download URL, как скачать файл stream-ом
- PATCH /disk/resources — как переименовать файл (для /processed/ suffix)
- DELETE /disk/resources — удаление файла, есть ли корзина
- Структура JSON-ответа для файла (все поля: name, path, created, modified, mime_type, size, md5, etc.)
- Rate limits (requests per second/minute)
- Как Яндекс.Телемост именует и сохраняет записи (папка, формат имени)
- Error codes: 401, 404, 429, что ещё важно
- Пример реального JSON-ответа

---

### SubAgent 2: Яндекс.Календарь CalDAV

Исследуй:
- https://yandex.ru/dev/calendar/ (если есть)
- https://tech.yandex.ru/calendar/ (если есть)
- CalDAV RFC 4791 summary (только Яндекс-специфичные части, не весь RFC)
- Поищи примеры "Яндекс CalDAV Python" на GitHub/Stack Overflow

Найди и верни digest с:
- Точный CalDAV base URL для Яндекс (подтверди `caldav.yandex.ru`)
- Как авторизоваться: OAuth Bearer ИЛИ Basic Auth — что реально работает с Яндекс
- Структура URL для доступа к календарям пользователя
- PROPFIND запрос для получения списка календарей (XML body, Depth header)
- REPORT calendar-query для поиска событий в time range (полный XML пример)
- Структура VEVENT в ответе: все поля (SUMMARY, DTSTART, DTEND, ORGANIZER, ATTENDEE, URL, DESCRIPTION, LOCATION, X-* custom fields)
- Что конкретно содержит VEVENT для встречи созданной через calink.ru (есть ли маркер)
- Как Телемост ссылка выглядит в VEVENT (в LOCATION? URL? DESCRIPTION?)
- Формат ORGANIZER и ATTENDEE (email format)
- Error responses (207 Multi-Status структура, 401, 403, 404)
- Пример полного REPORT запроса + ответа с реальным VEVENT

---

### SubAgent 3: Notion API

Исследуй: https://developers.notion.com/reference/

Найди и верни digest с:
- Auth: заголовки, Notion-Version (текущая актуальная версия)
- POST /databases/{database_id}/query — полный синтаксис filter для:
  - Поиск по title (contains)
  - Поиск по date (equals, on_or_after, on_or_before)
  - Комбинированный AND filter
  - Пример JSON body для поиска кандидата по имени + дате
- Структура JSON-ответа (Page object): как выглядят поля разных типов (title, date, url, formula, relation)
- PATCH /pages/{page_id} — как обновить url-поле (properties format)
- GET /databases/{database_id} — как выглядит schema (для извлечения property IDs)
- Rate limits: сколько requests/second, что при превышении
- Pagination: как обходить при > 100 результатах
- Error codes: 400, 401, 404, 409, 429 — что возвращает в body
- Особенности: title property всегда называется "Name"? Или нет?
- Пример полного query + response JSON

---

### SubAgent 4: Synology File Station API

Исследуй:
- https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf (или найди актуальную версию)
- https://www.synology.com/en-global/support/developer
- Поищи "Synology FileStation API upload python" примеры

Найди и верни digest с:
- Точный base URL pattern: `/webapi/entry.cgi` или `/webapi/auth.cgi` или другой
- API Key auth (DSM 7.0+): какой header, какое query param
- Session SID auth (старый способ): login endpoint, параметры, SID format
- SYNO.FileStation.List — параметры для listing папки, структура ответа
- SYNO.FileStation.Upload — как загрузить файл, параметры multipart запроса, streaming
- SYNO.FileStation.CreateFolder — создание папки если нет
- SYNO.FileStation.Sharing.Create — создать публичную ссылку, параметры (expiry, password), формат ответа (где URL)
- Размер chunk для streaming upload (если поддерживается)
- Error codes (Synology error structure: {"error": {"code": NNN}})
- Важные коды: 105 (no permission), 408 (file exists), 414 (path not found)
- Пример upload запроса и ответа

---

### SubAgent 5: Mattermost Bot API

Исследуй: https://api.mattermost.com/

Найди и верни digest с:
- Auth: Bot token в каком header
- POST /api/v4/posts — отправить сообщение, параметры (channel_id, message, props для attachments)
- POST /api/v4/posts с attachments — как отправить numbered list с кнопками (interactive message или просто текст)
- POST /api/v4/channels/direct — создать DM channel с пользователем
- GET /api/v4/users/email/{email} — получить user_id по email (для маршрутизации к рекрутеру)
- GET /api/v4/channels/{channel_id}/posts — polling новых сообщений, параметры since
- WebSocket API — подписка на события в канале для real-time получения ответов
- Slash commands registration — как зарегистрировать /recordings через API или UI
- Incoming webhooks — альтернатива bot token для получения сообщений
- Rate limits
- Структура Post object в ответе (id, user_id, channel_id, message, create_at)
- Error responses format

---

## Шаг 2: Синтез и запись

После получения всех 5 digest-ов:

1. Создай папку `docs/api-contracts/` если не существует
2. Напиши каждый файл на основе РЕАЛЬНЫХ данных из digest-ов

Правила записи:
- **Только то, что нашёл в официальных docs.** Если поле/endpoint не верифицирован — пометь `⚠️ не найдено в docs, требует проверки`
- **Примеры кода на Python + httpx** для каждой операции
- **Реальные JSON/XML примеры** из документации (не выдуманные)
- **Frontmatter** в начале каждого файла:
  ```yaml
  ---
  last_updated: 2026-07-13
  status: draft
  sources: [<url1>, <url2>]
  ---
  ```
- **Ссылки на source URLs** в конце каждой секции

---

### Файл: docs/api-contracts/yandex-disk.md

Разделы:
- Overview (base URL, auth header)
- Операция: получить список файлов (с фильтрами)
- Операция: получить metadata файла
- Операция: получить download URL + streaming download
- Операция: пометить файл как обработанный (rename или move)
- Операция: удалить файл
- Структура Recording File object (все поля)
- Обработка ошибок
- Rate limits
- Python примеры с httpx

---

### Файл: docs/api-contracts/yandex-caldav.md

Разделы:
- Overview (base URL, auth method)
- Операция: найти доступные календари (PROPFIND)
- Операция: найти события в диапазоне дат (REPORT calendar-query)
- Структура VEVENT — все поля и как их парсить
- Как извлечь: имя кандидата, ссылку на Telemost, организатора, дату
- Признаки что событие создано через calink.ru
- Обработка ошибок
- Python пример с httpx (без caldav-библиотек)

---

### Файл: docs/api-contracts/notion.md

Разделы:
- Overview (base URL, auth headers, текущая Notion-Version)
- Операция: получить схему БД (GET /databases/{id})
- Операция: поиск карточек (POST /databases/{id}/query) — примеры фильтров
- Структура Page object — как читать разные типы полей
- Операция: обновить url-поле карточки (PATCH /pages/{id})
- Pagination
- Rate limits и стратегия retry
- Обработка ошибок
- Python примеры с httpx

---

### Файл: docs/api-contracts/synology.md

Разделы:
- Overview (base URL pattern, API versioning)
- Auth: API Key (DSM 7+) vs Session SID
- Операция: список файлов в папке
- Операция: загрузить файл (streaming multipart)
- Операция: создать share link
- Структура ответа Synology (success/error format)
- Error codes reference
- Python примеры с httpx

---

### Файл: docs/api-contracts/mattermost.md

Разделы:
- Overview (base URL, auth header)
- Операция: найти user_id по email рекрутера
- Операция: создать DM channel
- Операция: отправить сообщение с numbered list
- Операция: получить ответ (polling GET /posts vs WebSocket)
- Slash commands: /recordings check, pending, status, retry
- Rate limits
- Python примеры с httpx

---

### Файл: docs/status-machine.md

На основе `.memory-bank/architecture.md` + TOR.md раздел 11.

Разделы:
- Диаграмма переходов (ASCII Mermaid-style)
- Каждый из 13 статусов: когда устанавливается, что следует, что делать при ошибке
- manual_review_required: полный flow (уйти → хранить context → вернуться)
- Retry policy: transient vs permanent errors
- Идемпотентность (защита от двойной обработки)

---

### Файл: docs/data-model.md

На основе TOR.md раздел 11.

Разделы:
- Таблица `recordings` — DDL со всеми полями из ТЗ + типы PostgreSQL
- Таблица `processing_attempts` — история попыток
- Таблица `recruiter_config` — email, notion_db_id, synology_folder, mattermost_user_id
- Таблица `manual_reviews` — открытые ручные запросы + mattermost thread context
- Индексы
- Alembic migration naming convention
- Пример запросов: найти pending reviews, статистика по рекрутеру

---

## После записи всех файлов

1. Обнови `.memory-bank/index.md` — добавь в "Where to look":
   - `API contracts → docs/api-contracts/`
   - `Status machine → docs/status-machine.md`
   - `Data model → docs/data-model.md`

2. Выведи итоговый список:
   - Все места где поставил `⚠️` (это приоритеты для Q0 discovery)
   - Вопросы из `.memory-bank/open-questions.md`, которые остались неразрешёнными после research
```

---

## Как запустить

Открой `projects/Recording Agent` в Claude Code и напиши:

```
Прочитай swarm-report/wiki-agent-prompt.md и выполни задание.
Запусти шаг 1 (5 субагентов параллельно в одном message), дождись digest-ов,
потом выполни шаг 2 (напиши все файлы).
```

## Если docs уже написаны без research

Файлы будут перезаписаны. Это нормально — перезапиши с реальными данными из docs.

## Оценка времени

- Шаг 1 (research): ~10-20 минут (5 субагентов параллельно)
- Шаг 2 (write): ~5-10 минут
- Итого: ~30 минут до полного комплекта точной документации
