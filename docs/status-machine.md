---
type: reference
status: draft
last_updated: 2026-07-13
sources:
  - TOR.md (раздел 11)
  - .memory-bank/architecture.md
---

# Status Machine — Машина состояний обработки записей

## Диаграмма переходов

```
[START: новый файл обнаружен на Диске]
          │
          ▼
        found
          │
          ├─── события не найдены / неоднозначность ──► manual_review_required
          │                                                      │
          ▼                                                      │ рекрутер подтвердил
  calendar_event_found                                           │
          │                                                      │
          ├─── карточка не найдена / несколько совпадений ──►──┘
          │
          ▼
  candidate_matched
          │
          ▼
  transfer_started
          │
          ├─── ошибка при передаче ──► failed
          │
          ▼
  uploaded_to_synology
          │
          ▼
  synology_link_created
          │
          ├─── ошибка Notion ──► failed
          │
          ▼
  notion_updated
          │
          ▼
  source_marked_processed
          │
          ▼
  source_deleted (опционально, по retention policy)
          │
          ▼
       completed
          
Отдельные ветки:
  ignored  — рекрутер явно отказался обрабатывать запись
  failed   — необратимая ошибка (после retry)
```

---

## Все 13 статусов

### 1. `found`

**Когда устанавливается:** файл обнаружен в списке Яндекс.Диска, ещё не обрабатывался.

**Что следует:** поиск события в Яндекс.Календаре в ±2h окне от времени записи.

**При ошибке:** если диск недоступен — ждать следующего цикла, не менять статус.

---

### 2. `calendar_event_found`

**Когда устанавливается:** найдено подходящее событие CalDAV с confidence ≥ threshold.

**Что следует:** поиск карточки кандидата в Notion.

**При ошибке / неоднозначности:** → `manual_review_required` (никогда не `ignored` автоматически).

---

### 3. `candidate_matched`

**Когда устанавливается:** найдена ровно одна карточка Notion с достаточной уверенностью.

**Что следует:** начать передачу файла в Synology.

**При ошибке:** если несколько карточек → `manual_review_required`. Если 0 → `manual_review_required`.

---

### 4. `manual_review_required`

**Когда устанавливается:**
- Событие календаря не найдено или неоднозначно
- Карточка Notion не найдена или найдено несколько
- Рекрутер не уверен / низкий confidence score

**Flow:**
```
1. db.set_status("manual_review_required")
2. mattermost.send_dm(recruiter, disambiguation_message)
3. context сохранён в recordings.manual_review_context (JSON)
4. Ожидание ответа рекрутера (WebSocket / polling)
5. OpenClaw NLU парсит свободный текст ответа
6. Определяем action: прикрепить к карточке N / ignore / URL
7. db.set_status("candidate_matched") → resume pipeline
```

**Хранить контекст:** `manual_review_context` в PostgreSQL — это всё что нужно для возобновления:
- ID записи
- ID кандидатов-претендентов
- ID Mattermost thread/channel

**При timeout рекрутера:** запись остаётся в `manual_review_required`. Reminder через 24h.

**Только явный `"ignore"` от рекрутера** переводит запись в `ignored`.

---

### 5. `transfer_started`

**Когда устанавливается:** перед началом streaming-передачи Диск → Synology.

**Что следует:** chunk-by-chunk streaming upload.

**Идемпотентность:** если агент перезапустился — проверить что файл не загружен уже в Synology. Если загружен — перейти в `uploaded_to_synology` без повторной загрузки.

**При ошибке:** → `failed` (transient: retry; permanent: alert)

---

### 6. `uploaded_to_synology`

**Когда устанавливается:** Synology подтвердил upload (200 OK).

**Что следует:** создать share link.

**Временный файл:** если использовался fallback (temp file) — удалить немедленно.

---

### 7. `synology_link_created`

**Когда устанавливается:** получен share URL от Synology.

**Что следует:** обновить карточку Notion.

**При ошибке создания ссылки:** → `failed`, файл на Synology уже есть — не удалять.

---

### 8. `notion_updated`

**Когда устанавливается:** PATCH `/pages/{id}` вернул 200, поле `General Interview recording` обновлено.

**Что следует:** пометить исходный файл на Диске как обработанный.

---

### 9. `source_marked_processed`

**Когда устанавливается:** файл перемещён в `/processed/` на Яндекс.Диске (POST /disk/resources/move).

**Что следует:** опционально — удалить файл с Диска (зависит от retention policy — Q9 из open-questions.md).

---

### 10. `source_deleted`

**Когда устанавливается:** исходный файл удалён с Яндекс.Диска (`permanently=true`).

**Условие:** только если все шаги 1-9 завершились успешно.

**Что следует:** → `completed`.

---

### 11. `completed`

**Когда устанавливается:** все шаги пройдены, запись полностью обработана.

**Финальный статус.** Запись в PostgreSQL остаётся для аудита.

---

### 12. `ignored`

**Когда устанавливается:** рекрутер явно ответил `"ignore"` / `"не моё"` / `"пропусти"` в Mattermost.

**Финальный статус.** Файл на Диске не трогать. Агент его больше не обрабатывает.

---

### 13. `failed`

**Когда устанавливается:** необратимая ошибка или исчерпан лимит retry.

**Действия:**
1. `db.set_status("failed", error_message=...)`
2. `db.increment_attempts()`
3. Уведомить рекрутера через Mattermost
4. Источник на Диске не трогать

**Retry:** агент не повторяет `failed` автоматически. Только по команде `/recordings retry <id>`.

---

## Retry Policy

### Transient ошибки (retry допустим)

| Ошибка | Стратегия |
|--------|-----------|
| Network timeout | Exponential backoff, max 5 попыток |
| HTTP 429 (rate limit) | Backoff по Retry-After |
| HTTP 503/504 (overload) | Backoff 30s, 60s, 120s |
| Synology 106 (session timeout) | Re-login, retry |
| Диск 423 (maintenance) | Ждать 30 мин, retry |

### Permanent ошибки (не retry)

| Ошибка | Действие |
|--------|----------|
| 404 файл не найден на Диске | → `failed` + alert |
| Notion 404 database_id | → `failed` + alert (нужен Q5) |
| Synology 415 quota exceeded | → `failed` + alert |
| Неверный OAuth token | → `failed` + alert (нужна ротация) |
| CalDAV 401 (app password) | → `failed` + alert |

---

## Идемпотентность (защита от двойной обработки)

Каждый шаг должен быть идемпотентным:

1. **`found`** — перед добавлением записи проверить `disk_file_id` в PostgreSQL. Если уже есть — пропустить.
2. **`transfer_started`** — перед upload проверить что файл не существует в Synology по имени/пути.
3. **`notion_updated`** — перед PATCH проверить текущее значение поля. Если уже заполнено нашим URL — пропустить.
4. **`source_deleted`** — проверить что `source_marked_processed` завершён. Если файл уже удалён (404) — считать успехом.

---

## Confidence Scoring (из architecture.md)

| Сигнал | Вес |
|--------|-----|
| Owner = known recruiter | high |
| CalDAV event has Telemost link | high |
| CalDAV event created via calink.ru | high |
| Event title contains interview keywords | medium |
| Candidate name in event title | medium |
| Recording in designated Disk folder | medium |

Если `total_confidence < threshold` → `manual_review_required` (не `ignored`).

Threshold определяется при настройке. Начать с 0.7.

---

## Связи

- [[data-model]] → таблица `recordings` + поле `status`
- [[architecture]] → data flow happy path
- [[mattermost]] → disambiguation flow
- [[yandex-disk]] → операции mark_processed, delete
- open-questions: Q9 (retention policy — нужно ли `source_deleted`)
