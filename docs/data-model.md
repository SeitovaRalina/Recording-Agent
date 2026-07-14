---
type: reference
status: draft
last_updated: 2026-07-13
sources:
  - TOR.md (раздел 11)
  - .memory-bank/architecture.md
  - .memory-bank/decisions.md
---

# Data Model — Recording Agent

> PostgreSQL — источник истины по состоянию обработки записей. Храним статусы, связи, идентификаторы, метаданные. Видеофайлы — никогда.

## Таблицы

### recordings

Основная таблица. Одна строка = одна запись Телемоста найденная агентом.

```sql
CREATE TABLE recordings (
    -- Identity
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Яндекс.Диск
    disk_file_id            TEXT NOT NULL,          -- уникальный id файла на Диске (из path или etag)
    disk_path               TEXT NOT NULL,          -- "disk:/Телемост/meeting-2026-07-13.webm"
    disk_filename           TEXT NOT NULL,          -- "meeting-2026-07-13.webm"
    disk_owner_email        TEXT NOT NULL,          -- email рекрутера = организатора Диска
    disk_created_at         TIMESTAMPTZ,            -- из поля created в Disk API
    disk_modified_at        TIMESTAMPTZ,            -- из поля modified
    disk_size_bytes         BIGINT,
    disk_mime_type          TEXT,                   -- "video/webm", "video/mp4"
    disk_md5                TEXT,

    -- Яндекс.Календарь
    calendar_event_uid      TEXT,                   -- UID из VEVENT
    calendar_event_summary  TEXT,                   -- SUMMARY (название события)
    calendar_dtstart        TIMESTAMPTZ,            -- DTSTART нормализованный в UTC
    calendar_dtend          TIMESTAMPTZ,            -- DTEND
    calendar_organizer      TEXT,                   -- ORGANIZER mailto:
    calendar_telemost_url   TEXT,                   -- LOCATION / URL / X-TELEMOST-CONFERENCE-URL
    calendar_raw_ics        TEXT,                   -- полный VEVENT текст (для отладки)

    -- Кандидат (извлечён из SUMMARY события)
    candidate_name          TEXT,                   -- "Иван Иванов" (из SUMMARY)
    candidate_email         TEXT,                   -- если был в ATTENDEE (не гарантировано)

    -- Notion
    notion_database_id      TEXT,                   -- id базы рекрутера
    notion_page_id          TEXT,                   -- id карточки (после матчинга)
    notion_page_url         TEXT,                   -- https://notion.so/...

    -- Synology
    synology_folder_path    TEXT,                   -- /volume1/interviews/Anton/2026-07-13/
    synology_file_path      TEXT,                   -- /volume1/interviews/.../filename.webm
    synology_share_url      TEXT,                   -- публичная ссылка из Sharing.Create

    -- Статус (state machine)
    status                  TEXT NOT NULL DEFAULT 'found'
                            CHECK (status IN (
                                'found',
                                'calendar_event_found',
                                'candidate_matched',
                                'manual_review_required',
                                'transfer_started',
                                'uploaded_to_synology',
                                'synology_link_created',
                                'notion_updated',
                                'source_marked_processed',
                                'source_deleted',
                                'completed',
                                'ignored',
                                'failed'
                            )),

    -- Ошибка
    error_message           TEXT,
    error_step              TEXT,                   -- на каком шаге упало

    -- Mattermost (для manual_review_required)
    mattermost_channel_id   TEXT,                   -- id DM-канала с рекрутером
    mattermost_post_id      TEXT,                   -- id сообщения с вопросом

    -- Временные метки
    found_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempted_at       TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    deleted_from_disk_at    TIMESTAMPTZ,

    -- Retention
    disk_deletable_after    TIMESTAMPTZ,            -- когда можно удалять с Диска (если задана политика)
    source_processed        BOOLEAN NOT NULL DEFAULT false, -- помечен ли файл на Диске

    -- Uniqueness: не обрабатывать один и тот же файл дважды
    UNIQUE (disk_file_id)
);
```

### processing_attempts

История попыток — append-only. Не обновлять, только вставлять.

```sql
CREATE TABLE processing_attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id    UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_before   TEXT NOT NULL,
    status_after    TEXT NOT NULL,
    step            TEXT NOT NULL,              -- 'calendar_lookup', 'notion_search', 'transfer', etc.
    success         BOOLEAN NOT NULL,
    error_message   TEXT,
    duration_ms     INTEGER,
    metadata        JSONB                       -- доп. данные конкретного шага
);

CREATE INDEX idx_processing_attempts_recording_id ON processing_attempts(recording_id);
CREATE INDEX idx_processing_attempts_attempted_at ON processing_attempts(attempted_at);
```

### recruiter_config

Конфигурация на рекрутера. Заполняется оператором при onboarding.

```sql
CREATE TABLE recruiter_config (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                   TEXT NOT NULL UNIQUE,   -- disk_owner_email рекрутера
    display_name            TEXT,
    notion_database_id      TEXT NOT NULL,          -- id базы в Notion
    synology_base_folder    TEXT NOT NULL,          -- /volume1/interviews/Anton
    mattermost_user_id      TEXT,                   -- id пользователя в Mattermost
    mattermost_dm_channel   TEXT,                   -- кэш id DM-канала с ботом
    active                  BOOLEAN NOT NULL DEFAULT true,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Пример:
-- INSERT INTO recruiter_config (email, display_name, notion_database_id, synology_base_folder, mattermost_user_id)
-- VALUES ('anton@company.com', 'Антон', 'abc123-...', '/volume1/interviews/Anton', 'mm-user-id-xxx');
```

### manual_reviews

Открытые запросы на ручное уточнение. Закрывается после ответа рекрутера.

```sql
CREATE TABLE manual_reviews (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id            UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,

    -- Что спросили
    question_type           TEXT NOT NULL,          -- 'notion_card_ambiguous', 'calendar_not_found', 'ignore_confirm'
    question_context        JSONB NOT NULL,         -- кандидаты, варианты карточек, etc.

    -- Ответ рекрутера
    raw_reply               TEXT,                   -- свободный текст от рекрутера
    parsed_action           TEXT,                   -- 'select_card', 'ignore', 'use_url'
    resolved_notion_page_id TEXT,                   -- id карточки после резолюции

    -- Mattermost thread
    mattermost_post_id      TEXT,                   -- исходное сообщение бота
    mattermost_reply_id     TEXT,                   -- ответ рекрутера

    status                  TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'resolved', 'expired'))
);

CREATE INDEX idx_manual_reviews_recording_id ON manual_reviews(recording_id);
CREATE INDEX idx_manual_reviews_status ON manual_reviews(status) WHERE status = 'pending';
```

## Индексы

```sql
-- Поиск новых необработанных записей
CREATE INDEX idx_recordings_status ON recordings(status);

-- Поиск по рекрутеру
CREATE INDEX idx_recordings_disk_owner ON recordings(disk_owner_email);

-- Поиск незавершённых (для retry)
CREATE INDEX idx_recordings_status_found_at ON recordings(status, found_at)
    WHERE status NOT IN ('completed', 'ignored', 'failed');

-- Поиск по файлу Диска (для идемпотентности)
CREATE INDEX idx_recordings_disk_file_id ON recordings(disk_file_id);
```

## Alembic — соглашение по именованию миграций

```
# Формат:
{YYYYMMDD}_{HHMM}_{short_description}.py

# Примеры:
20260713_1000_create_recordings_table.py
20260713_1100_create_processing_attempts_table.py
20260713_1200_create_recruiter_config_table.py
20260713_1300_create_manual_reviews_table.py
20260714_0900_add_disk_md5_to_recordings.py
```

## Примеры запросов

### Найти все записи требующие ручной проверки

```sql
SELECT r.id, r.disk_filename, r.disk_owner_email,
       r.candidate_name, r.found_at,
       mr.question_type, mr.mattermost_post_id
FROM recordings r
JOIN manual_reviews mr ON mr.recording_id = r.id
WHERE r.status = 'manual_review_required'
  AND mr.status = 'pending'
ORDER BY r.found_at;
```

### Найти записи застрявшие в transfer (retry кандидаты)

```sql
SELECT id, disk_filename, disk_owner_email, status,
       last_attempted_at, error_message
FROM recordings
WHERE status IN ('transfer_started', 'uploaded_to_synology')
  AND last_attempted_at < now() - interval '2 hours'
ORDER BY last_attempted_at;
```

### Статистика по рекрутеру

```sql
SELECT disk_owner_email,
       count(*) FILTER (WHERE status = 'completed') AS completed,
       count(*) FILTER (WHERE status = 'failed') AS failed,
       count(*) FILTER (WHERE status = 'manual_review_required') AS pending_review,
       count(*) AS total
FROM recordings
GROUP BY disk_owner_email
ORDER BY disk_owner_email;
```

### Записи готовые к удалению с Диска

```sql
SELECT id, disk_path, disk_filename, completed_at
FROM recordings
WHERE status = 'completed'
  AND source_processed = true
  AND deleted_from_disk_at IS NULL
  AND (disk_deletable_after IS NULL OR disk_deletable_after <= now())
ORDER BY completed_at;
```

### Идемпотентность: проверить что файл ещё не обрабатывался

```sql
SELECT id, status FROM recordings
WHERE disk_file_id = $1
LIMIT 1;
-- Если строка есть → пропустить (уже в pipeline)
-- Если нет → INSERT + начать обработку
```

## Связи с другими компонентами

- [[api-contracts/yandex-disk]] → disk_file_id, disk_path, disk_created_at
- [[api-contracts/yandex-caldav]] → calendar_event_uid, calendar_telemost_url
- [[api-contracts/notion]] → notion_database_id, notion_page_id
- [[api-contracts/synology]] → synology_folder_path, synology_share_url
- [[api-contracts/mattermost]] → mattermost_channel_id, mattermost_post_id
- [[status-machine]] → status поле + переходы
