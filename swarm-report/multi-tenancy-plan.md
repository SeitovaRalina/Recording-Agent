# Plan: Мультипользовательность (per-recruiter Notion mapping + Synology roots)   (slug: multi-tenancy)

## TL;DR

Recruiter_config получает две новые nullable JSON-колонки (Notion property map, Synology
interview roots) + один resolver-модуль, через который переписываются ВСЕ 8+ мест, что сегодня
читают `settings.notion_*` / `settings.synology_interview_roots` напрямую. NULL-колонка =
поведение как сейчас (default = global). Schema preflight (`canary.py`) хэширует резолвленную
per-recruiter карту, а не глобальный `Settings`. Contacts — 3 режима: `none` (нет поля, как у
Lilia сегодня), `formula` (как у Antona — `TBD`), `relation` (как реально нужно Lilia — читать
email из `Contacts` (rich_text) карточки кандидата через relation Interviews→Candidates).
Relation-режим реализуется полностью в этом плане (решение пользователя 2026-09-30), не
откладывается. Роуты Антона (`/home/...` test copy) этим планом НЕ трогаются — подтверждено
пользователем, остаются как есть.

**Решено пользователем (2026-09-30):**
1. Contacts-через-relation — реализовать сейчас, не откладывать.
2. Роуты Антона (`/home/...`) — не трогать, остаются тестовыми.

## Acceptance criteria

- `recruiter_config` получает nullable `notion_property_map` (JSON) и `synology_interview_roots`
  (JSON list[str]) через одну Alembic-миграцию (down_revision = текущий head `20260729_1100`).
- Recruiter-строка с обеими колонками = NULL ведёт себя байт-в-байт как сегодня (резолвится в
  `Settings.notion_name_prop/date_prop/recording_prop/project_prop/project_prop_type/contacts_prop`
  и `Settings.synology_interview_roots`). Анton не ломается этой миграцией.
- `tools/setup/configure_recruiter.py configure` принимает опциональные флаги
  `--notion-name-prop/--notion-date-prop/--notion-recording-prop/--notion-project-prop/
  --notion-project-prop-type/--notion-contacts-mode/--notion-contacts-prop/
  --notion-contacts-relation-prop/--notion-contacts-target-prop/--synology-roots`; пропущенные
  флаги оставляют колонки NULL.
- Этими флагами можно создать неактивную строку Lilia: `notion_project_prop=Vacancy`,
  `notion_project_prop_type=relation`, `notion_contacts_mode=none`,
  `synology_interview_roots=["/Recruiting-NE/2. Interviews"]` — без правки `app/config.py`.
- `notion_schema_hash`/`require_notion_preflight` (`app/services/canary.py`) считают хэш от
  РЕЗОЛВЛЕННОЙ карты конкретного рекрутера, не от глобального `Settings`. Смена схемы у
  рекрутера A никогда не инвалидирует сохранённый preflight-хэш рекрутера B.
- `is_compatible` (`app/tools/notion.py`) проверяет contacts по `contacts_mode`: `none` — без
  проверки поля вообще; `formula` — текущая проверка (`contacts_prop` типа `formula`); `relation`
  — `contacts_relation_prop` типа `relation` на источнике (Interviews DB). Ни один режим не падает
  и не блокирует preflight, когда у рекрутера нет contacts вообще (`none`).
- Для `contacts_mode=relation`: ровно одна relation на `contacts_relation_prop` → бэкенд читает
  `contacts_target_prop` (rich_text) со связанной карточки (Candidates DB) и парсит email тем же
  regex, что и `_formula_emails` сегодня. Ноль или больше одной relation → contacts пусты
  (`emails=()`), матчинг не блокируется — email всегда лишь supplementary-сигнал (Q5).
- `CandidateService.find_and_match`, `NotionReassignmentService.resolve_targets/propose/confirm`,
  `DestinationService.preflight/discover/create/resolve/list_allowed_candidates`,
  `TransferService.transfer`, `app/scheduler/cron.py` (~634, 845, 861-862, 1065, 1091-1092),
  `app/services/reroute.py route()` резолвят Notion-поля / Synology roots per-recruiter, не читая
  `settings.notion_*` / `settings.synology_interview_roots` напрямую.
- `pytest` зелёный, включая новые тесты: NULL-карта = текущие global defaults; non-NULL карта
  переопределяет только заданные поля; изоляция preflight двух рекрутеров; `DestinationService`/
  `TransferService` уважают recruiter-specific roots, отличные от global.

## Plan

### Шаги (порядок исполнения)

1. `/migrate generate "add per-recruiter notion property map and synology interview roots"` —
   `down_revision` = текущий head `20260729_1100`. Новые колонки: `notion_property_map` JSON
   NULL, `synology_interview_roots` JSON NULL. Без backfill — NULL значит "inherit global".
2. `app/db/models/recruiter_config.py` — добавить оба поля в `RecruiterConfig`.
3. Новый файл `app/services/recruiter_schema.py`:
   - `NotionPropertyMap` — frozen dataclass/Pydantic-модель: `name_prop`, `date_prop`,
     `recording_prop`, `project_prop`, `project_prop_type` (обязательные, наследуют текущий
     `Literal["rich_text", "relation"]`), `contacts_mode: Literal["none", "formula", "relation"]`,
     `contacts_prop`, `contacts_relation_prop`, `contacts_target_prop` (опциональные). Валидация
     через Pydantic — как сегодня `app/config.py` валидирует `notion_project_prop_type` — чтобы
     кривой JSON (опечатка в типе/режиме) падал сразу при записи в `configure_recruiter.py`, а не
     всплывал `NotionMalformedResponseError`-ом глубоко в проде.
   - `resolve_notion_property_map(settings, recruiter) -> NotionPropertyMap`: мёрджит
     `recruiter.notion_property_map` (любое подмножество ключей) поверх `settings.notion_*`
     дефолтов — **per-field fallback**, не all-or-nothing.
   - `resolve_synology_roots(settings, recruiter) -> tuple[str, ...]`:
     `recruiter.synology_interview_roots`, если не пусто, иначе `settings.synology_interview_roots`.
     Переиспользовать текущую нормализацию путей из `app/config.py` (абсолютный путь, rstrip('/'),
     dedupe).
   - Юнит-тест мёрдж/fallback-логики в изоляции первым — дешевле всего отловить ошибки здесь.
4. `app/tools/notion.py` — самая существенная правка, contacts_mode: `none | formula | relation`:
   - `NotionDataSourceSchema.is_compatible` (~172-193): добавить параметры
     `contacts_mode: str = "formula"`, `contacts_relation_prop: str = ""`. Ветвление:
     `contacts_mode == "none"` → без проверки; `"formula"` → текущая проверка
     `property_types.get(contacts_prop) == "formula"`; `"relation"` →
     `property_types.get(contacts_relation_prop) == "relation"`.
   - Переименовать `_project_relation_ids(item, project_prop)` (~935-961) в общий
     `_relation_ids(item, prop_name)` — сегодня уже делает ровно то, что нужно для
     contacts-relation (парсит `properties[prop_name]["relation"]`, bounded, raises on
     malformed). Project-код продолжает звать его с `project_prop`.
   - Новый `_retrieve_related_property(page_id: str, target_prop: str) -> Any` — аналог
     `_retrieve_related_page` (~755-786), но вместо title достаёт `properties.get(target_prop)`
     сырым (для последующего парсинга).
   - Обобщить `_formula_emails` (~964-980) в `_extract_emails(text: str) -> tuple[str, ...]`
     (сам regex/валидация email не меняются) + два тонких адаптера:
     `_formula_emails(value)` (текущая формула-логика, дергает `_extract_emails` на
     `formula.string`) и новый `_rich_text_emails(value)` (тот же `_plain_text`-хелпер, что уже
     используется для title/project, затем `_extract_emails` на результат). Пустой/отсутствующий
     `contacts_prop`/`contacts_relation_prop` (`contacts_mode="none"`) → возвращать `()` без
     обращения к этим функциям вообще.
   - `_parse_page` (~904-933) и цикл в `search_pages` (~278-302), а также
     `resolve_reassignment_targets`/`_retrieve_reassignment_page`: добавить параметры
     `contacts_mode`, `contacts_relation_prop`, `contacts_target_prop` везде рядом с
     `contacts_prop`. Диспетчеризация после построения `page`:
     - `mode == "formula"` — как сегодня, синхронно внутри `_parse_page`.
     - `mode == "relation"` — `_parse_page` НЕ резолвит email (нет I/O в staticmethod); вызывающий
       async-код (`search_pages`/`resolve_reassignment_targets`) берёт `relation_ids =
       self._relation_ids(item, contacts_relation_prop)`, при `len == 1` — кэширует и вызывает
       `_retrieve_related_property` + `_rich_text_emails`, затем `replace(page, email=...,
       emails=...)`. Отдельный кэш от `relation_cache` (спотов) — ключ `relation_id`, значение
       `tuple[str, ...]` email.
     - `mode == "none"` — `emails=()`, без обращений.
   - `preflight_database`/`inspect_database` (~580-661): пробрасывают новые параметры в
     `is_compatible`. Синтетическая пре-флайт-проверка (`preflight_database` ~660,
     `self._formula_emails(...)`) вызывается только при `contacts_mode == "formula"`; при
     `"relation"` — НЕ проверяет `contacts_target_prop` на связанной БД (id связанной базы не
     конфигурируется отдельно, синтетическая тестовая строка вряд ли имеет реальную relation) —
     это осознанный soft-fail-at-runtime дизайн, см. Assumptions; при `"none"` — пропускается.
5. `app/services/canary.py`: `notion_schema_hash(map: NotionPropertyMap)` вместо
   `notion_schema_hash(settings: Settings)` — хэшировать и `project_prop_type`, и новые
   `contacts_mode`/`contacts_relation_prop`/`contacts_target_prop` (сегодня хэшируются только 5 из
   6 полей — расширить, чтобы смена схемы инвалидировала старый preflight). Сигнатура
   `require_notion_preflight(settings, recruiter)` не меняется для вызывающих — резолвит карту
   внутри перед хэшированием.
6. Sweep вызывающих мест в порядке (каждый тестируем независимо). Везде, где раньше передавался
   один `contacts_prop`, теперь передаются 3 поля из `NotionPropertyMap`: `contacts_mode`,
   `contacts_prop`, `contacts_relation_prop`, `contacts_target_prop`:
   `candidate.py` → `notion_reassignment.py` (+ `routers/tools.py` — `confirm_notion_reassignment`
   сейчас вообще не делает recruiter lookup, добавить его через тот же паттерн
   `_bound_recruiter(...)`, что уже есть в `propose_notion_reassignment`) → `destinations.py`
   (убрать constructor-time `self._roots`, резолвить `roots = resolve_synology_roots(...)` в
   каждом методе: `preflight`, `discover`, `create`, `resolve`, `list_allowed_candidates`,
   `_is_allowed_interview_path`/`_require_allowed_interview_path`) → `transfer.py` (аналогично,
   `transfer()` уже принимает `recruiter`) → `cron.py` (~634, 845, 861-862, 1065, 1091-1092 —
   `recruiter` уже в скоупе в этих местах) → `reroute.py` (`route()` уже принимает `recruiter`).
7. `tools/setup/configure_recruiter.py`:
   - `NotionInspector.inspect(database_id, property_map: NotionPropertyMap)` вместо чтения
     `self._settings.notion_*` — карта на момент `configure` берётся из CLI-аргументов (строки
     рекрутера ещё не существует).
   - `configure_recruiter()` получает kwargs `notion_property_map`/`synology_interview_roots`,
     пишет их в новую (неактивную) строку `RecruiterConfig`.
   - `preflight_recruiter_notion` резолвит карту из уже сохранённой строки через
     `resolve_notion_property_map` и передаёт в `notion.preflight_database`.
   - `main()`/argparse: 9 новых `--notion-*` флагов + `--synology-roots` (переиспользовать
     JSON-or-CSV парсинг из `app/config.py`) в подпарсер `configure`, все опциональные.
8. Обновить `docs/api-contracts/notion.md` и `docs/data-model.md` — сейчас описывают единую
   глобальную схему; привести к per-recruiter (LOW-приоритет, но входит в diff).
9. Полный `pytest`; отдельно подтвердить, что Anton-shaped (NULL-колонки) тесты не изменились —
   это regression-gate на «global settings остаются default».
10. **НЕ трогать** текущее значение `synology_interview_roots`/роуты Антона и **не** создавать/
    активировать строку Lilia в рамках этого изменения — отдельный операционный шаг (онбординг
    Lilia, item 3), заблокированный открытым решением про `/home` vs prod пути.

### Затронутые файлы

- `alembic/versions/<new>_add_recruiter_notion_schema_and_roots.py` — новая миграция.
- `app/db/models/recruiter_config.py` — 2 новых поля.
- `app/services/recruiter_schema.py` — новый: `NotionPropertyMap`, `resolve_notion_property_map`,
  `resolve_synology_roots`.
- `app/tools/notion.py` — `is_compatible` (3 contacts_mode), `_relation_ids` (renamed/generalized
  `_project_relation_ids`), `_retrieve_related_property` (новый), `_extract_emails` +
  `_rich_text_emails` (новые/обобщённые из `_formula_emails`), `_parse_page`, `search_pages`,
  `resolve_reassignment_targets`, `_retrieve_reassignment_page`, `preflight_database`,
  `inspect_database`.
- `app/services/canary.py` — `notion_schema_hash(map)`, `require_notion_preflight`.
- `app/services/candidate.py` — `find_and_match` через resolver.
- `app/services/notion_reassignment.py` — `propose()`/`confirm()` получают `recruiter`.
- `app/routers/tools.py` — `confirm_notion_reassignment` (~647): добавить recruiter lookup.
- `app/services/destinations.py` — все методы резолвят roots локально, не через
  constructor-time `self._roots`.
- `app/services/transfer.py` — `transfer()` резолвит roots из recruiter+settings.
- `app/scheduler/cron.py` — ~634, 845, 861-862, 1065, 1091-1092.
- `app/services/reroute.py` — `route()`.
- `tools/setup/configure_recruiter.py` — `NotionInspector.inspect`, `configure_recruiter`,
  `preflight_recruiter_notion`, CLI-флаги.
- `docs/api-contracts/notion.md`, `docs/data-model.md` — обновить под per-recruiter.

### Тесты

- Юнит: `resolve_notion_property_map`/`resolve_synology_roots` — NULL-колонки == global
  defaults; частичный override мёрджит только заданные ключи; неизвестный `contacts_mode`
  отклоняется Pydantic-валидацией.
- Юнит: `notion_schema_hash(map)` различается при разном `project_prop_type`/`contacts_mode`;
  изоляция `require_notion_preflight` между двумя рекрутерами с разными картами и разными
  сохранёнными хэшами.
- Интеграционный: `CandidateService.find_and_match` на Lilia-shaped карте (`Vacancy`/relation
  для project, `contacts_mode=relation` для contacts) — `project_or_spot` резолвится через
  relation так же, как сегодня `📍 Spots`; email резолвится через
  `contacts_relation_prop`→связанная карточка→`contacts_target_prop` (rich_text), совпадает с
  regex-парсингом formula-режима. Отдельно: `contacts_mode=none` — без падений, `emails=()`.
- Юнит: `_rich_text_emails`/`_extract_emails` — тот же regex/нормализация email, что и у
  `_formula_emails` сегодня (несколько email в тексте, невалидные строки игнорируются). Ноль
  relation на `contacts_relation_prop` → `()`; больше одной → `()` (не блокирует, не выбирает
  произвольно).
- Интеграционный: `DestinationService` + `TransferService` с `recruiter.synology_interview_roots`
  на один non-global root — discovery/preflight/transfer ограничены этим root, глобальный
  `settings.synology_interview_roots` не читается.
- Интеграционный: round-trip CLI `configure_recruiter configure` — флаги внутри → колонки
  снаружи; пропущенные флаги остаются NULL.
- Полный `pytest` зелёный (test-gate hook).

## Blockers

Нет открытых блокеров — оба пункта решены пользователем 2026-09-30:

1. **Contacts через relation (Lilia) — реализуется полностью в этом плане.** Interviews→
   Candidates relation-обход + чтение `Contacts` (rich_text) со связанной карточки, тот же
   email-regex, что и у Antona's formula. См. секцию Plan, шаг 4 (`app/tools/notion.py`).
   Остаётся открытым (операционный, не кодовый вопрос): имя back-relation свойства на Interviews
   DB, указывающего на Candidates DB (в памяти известно только прямое поле `Interviews` на
   стороне Candidates DB) — уточняется read-only schema-пробой при онбординге Lilia
   (`configure_recruiter.py inspect`/`preflight`), не блокирует код.
2. **Роуты Антона (`/home/...` test copy) — не трогаем.** Явное решение пользователя: остаются
   как есть, отдельным вопросом позже. `synology_interview_roots` для рекрутера Антона остаётся
   NULL (наследует текущий global `/home/...`).

## Out of scope

- Решение/смена реальных Synology-роутов Антона (явно отложено пользователем).
- Создание/активация строки Lilia — это онбординг (item 3), выполняется после этого плана через
  CLI, не его частью.
- calink matching (item 3 недели) и meeting summary (item 4) — не пересекаются, кроме случайного
  общего файла `recruiter_config`.
- Self-service онбординг UI — закрыто Q12, вне скоупа.
- Per-recruiter override `notion_interview_type` (`general_interview`), `notion_token`,
  `notion_proxy_url` — не упоминались как варьирующиеся, остаются глобальными.

## Assumptions

- «Global settings остаются default» = NULL-колонка рекрутера резолвится ровно в текущие
  `Settings.notion_*`/`Settings.synology_interview_roots` — без data backfill, NULL уже значит
  «use global».
- Одна JSON-колонка на концепцию (`notion_property_map`, `synology_interview_roots`) вместо 6-8
  типизированных колонок — по прецеденту `calendar_selection_before/after` в той же модели,
  меньше миграция, не требует второй миграции под contacts-via-relation позже.
- `synology_interview_roots` — список (не строка) на рекрутера, сохраняет текущую multi-root
  возможность (Анton потенциально Recruiting-E external+internal). Существующее поле
  `synology_base_folder` (primary upload target) не трогается — остаётся своим смыслом,
  `synology_interview_roots` — более широкий набор allowed destinations для discovery/reroute.
- `_parse_page`/`_project_relation_ids` (после переименования — `_relation_ids`) уже трактуют
  пустой `project_prop` как «поле отсутствует» — то же поведение переиспользуется для
  `contacts_mode=none`.
- Preflight для `contacts_mode=relation` проверяет только тип `contacts_relation_prop` (relation)
  на Interviews-источнике; тип `contacts_target_prop` на связанной Candidates-базе НЕ
  проверяется заранее (нет отдельно сконфигурированного id связанной базы, синтетическая
  тест-строка вряд ли имеет реальную relation) — сознательный soft-fail-at-runtime: если
  `contacts_target_prop` на связанной карточке отсутствует/не rich_text, `_rich_text_emails`
  возвращает `()`, не роняет запрос. Раскрыто пользователю как дизайн-решение, не скрытый гап.
- Имя back-relation свойства на Interviews DB (→ Candidates DB) для Lilia уточняется
  операционным read-only schema-пробом при онбординге (не известно заранее из памяти проекта).
