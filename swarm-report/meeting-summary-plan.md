# Plan: конспект встречи в карточку Notion (meeting-summary)   (slug: meeting-summary)

## TL;DR

Два новых tool-эндпоинта (`GET /tools/recordings/{id}/summary-source`, `POST /tools/recordings/{id}/summary`)
дают Миле сырой текст найденного письма и принимают обратно готовый toggle-list + оценку кандидата.
Бэкенд находит письмо через новый per-recruiter IMAP-поиск (новый сервис `summary_email.py`, не
`InterviewMatcher`), пишет toggle-list в Notion сразу, а comment с оценкой — только после подтверждения
рекрутёра через существующий `ManualReview`/`QuestionQueueService` (как в digest-toggle). LLM-суммаризация
письма — в skill-файле Милы, вне этого репозитория (пользователь настраивает параллельно).

## Acceptance criteria

1. `GET /tools/recordings/{id}/summary-source` отдаёт subject/sender/date/body найденного письма;
   `404` — неизвестный `id`; `409` — письмо ещё не найдено. Требует `recruiter_user_id` и проверяет
   `recording.disk_owner_email == recruiter.email` (как `enforce_recruiter_scope`/`get_bound_review` у
   соседних эндпоинтов) — НЕ только общий `verify_openclaw_secret`.
2. `POST /tools/recordings/{id}/summary` (узкая Pydantic-схема, `extra="forbid"`, по образцу
   `QuestionBatchRequest`) принимает `recruiter_user_id`, `expected_version`, `idempotency_key`,
   toggle-контент и текст оценки. Пишет toggle-list в Notion сразу; вместо прямого comment создаёт один
   `ManualReview` (`question_type="summary_assessment_approval"`). Отклоняет: неизвестный `recruiter_user_id`/
   чужая запись (403/404), несовпадающий `expected_version` (409, оптимистическая конкурентность — как у
   остальных мутирующих tool-эндпоинтов), архивную Notion-страницу или `FAILED` запись (409 с внятным
   сообщением, не тихий сбой).
3. Подтверждение/отклонение оценки — через существующий `/tools/questions/answer` (`QuestionActionRequest`,
   choice 1/2). Approve → `notion.create_comment` с сохранённым текстом; reject/ignore → оценка отбрасывается.
   Toggle-list не зависит от исхода.
4. Поиск письма — best-effort, не блокирует `COMPLETED`. При неоднозначном совпадении (несколько писем
   кандидата в окне) — не тихий пропуск, а эскалация в `ManualReview` (тот же паттерн, что и
   confidence-эскалация в `InterviewMatcher`), а не молчаливый `NOT_FOUND`.
5. Поля поиска письма (`summary_email_search_attempts`, `..._deadline_at`, `..._message_id/subject/
   received_at`, `..._toggle_written_at`) живут на `Recording` НЕЗАВИСИМО от `RecordingStatus` —
   `GET`/`POST` читают/пишут эти поля напрямую, не через `transition_to`/`advance()`. Это обходит то, что
   `RecordingStatus.TRANSITIONS[COMPLETED]` — пустое множество: письмо, пришедшее после `COMPLETED`,
   по дефолту НЕ переоткрывает запись (см. Assumptions) — `GET summary-source` на `COMPLETED` без
   найденного письма отдаёт `409`, не ошибку.
6. `Settings.yandex_mail_app_passwords: dict[str, SecretStr]` (тот же `AliasChoices`-паттерн, что
   `yandex_caldav_passwords`, `app/config.py:47-50`) — отсутствующий/невалидный пароль валит только шаг
   поиска письма этого рекрутёра, не саму запись.
7. Письмо/конспект/оценка НИКОГДА не попадают в `pipeline_trace.trace()` без redaction — либо вовсе не
   передаются в `trace()`, либо ключи добавлены в redaction-deny-list (`pipeline_trace.py:12`).
8. `poetry run pytest -q` зелёный, включая новые тесты (см. Plan → tests).
9. Notion Connection получает comment-право вручную в Notion UI — внешний шаг оператора, не код-таск;
   проверяется перед первой прод-отправкой comment.

## Plan

**Модель данных** (`app/db/models/recording.py`):
- Новый `RecordingStatus.AWAITING_SUMMARY_EMAIL`; `TRANSITIONS`: `NOTION_UPDATED →
  AWAITING_SUMMARY_EMAIL → {self (retry), SOURCE_MARKED_PROCESSED, COMPLETED, FAILED}`.
- Новые nullable-колонки: `summary_email_search_attempts` (int, default 0),
  `summary_email_search_deadline_at`, `summary_email_message_id/subject/received_at`,
  `summary_toggle_written_at`. Все не участвуют в `transition_to` — читаются/пишутся напрямую.
- Alembic: `/migrate generate "add awaiting_summary_email status and summary tracking columns"`;
  вручную проверить перегенерированный `CHECK` constraint на новое значение enum; additive/nullable,
  `expand-contract` (как весь прошлый rollout в этой сессии).

**Конфиг** (`app/config.py`): `yandex_mail_app_passwords` (как п.6 acceptance), `summary_email_imap_host`
(default `imap.yandex.ru` — подтверждено живым IMAP-логином в этой сессии для обоих рекрутёров),
`summary_email_search_timeout_seconds` (bounded `Field`).

**IMAP-клиент** (`app/tools/mail_imap.py`, новый модуль с нуля — в проекте сегодня `imaplib` есть только
как одноразовая проверка в `tests/e2e/inspect_prod.py`, не как сервис): оборачивает синхронный `imaplib`
через `asyncio.to_thread` (без этого — блокирующий вызов в async-пути, нарушение правила AGENTS.md).
Типизированные исключения по образцу `NotionAPIError`-иерархии.

**Сервис матчинга письма** (`app/services/summary_email.py`, новый, НЕ `InterviewMatcher`): по теме/окну
времени/email кандидата (из `Recording.candidate_email`/calink-описания события) ищет письмо. Возвращает
`FOUND` / `NOT_FOUND` (до таймаута — retry) / `AMBIGUOUS` (несколько кандидатов → `ManualReview`, не тихий
best-effort). Инкапсулирует retry/timeout политику на новых колонках `Recording`.

**cron.py**: новый шаг между `NOTION_UPDATED` (~1114) и существующей проверкой
`COMPLETED`/`SOURCE_MARKED_PROCESSED` (~1117-1127). На `NOTION_UPDATED` → перевод в
`AWAITING_SUMMARY_EMAIL` + попытка `summary_email.find()`. На `AWAITING_SUMMARY_EMAIL` — retry до дедлайна.
Найдено → сохранить поля письма на `Recording` (Notion НЕ пишется здесь — только Мила пишет, через
`POST /summary`, после того как прочитает текст через `GET`). Таймаут/ошибка IMAP — проезд в существующую
`COMPLETED`-логику без изменений (best-effort, запись никогда не проваливается из-за письма). Явно
проверить: существующий concurrency-guard `scan_recruiter`-тика покрывает и этот новый шаг (один mailbox
не читается параллельно двумя тиками) — задача для `/build`, не предполагать.

**Notion** (`app/tools/notion.py`, методы с нуля — сегодня нет ни children-blocks, ни comments API):
`append_toggle_block(page_id, title, paragraphs)` (`PATCH /v1/blocks/{page_id}/children`),
`create_comment(page_id, text)` (`POST /v1/comments`). Узкие типизированные исключения, включая отдельную
обработку "страница архивирована" (конкретный Notion error code → понятная ошибка наружу, не молчаливый
drop) и "нет comment-права на Connection" (тоже понятная ошибка, не silent fail — см. acceptance #9).

**Tools router** (`app/routers/tools.py`): два новых эндпоинта под существующим `/tools`
(`verify_openclaw_secret` остаётся, ПЛЮС recruiter-scope проверка — см. acceptance #1/#2).
`SummarySourceResponse`, `SummarySubmitRequest`/`SummarySubmitResponse` — bounded `Field`, `extra="forbid"`.
`idempotency_key` на `POST /summary` — переиспользовать existing intent-replay паттерн (`app/services/
intents.py`), не изобретать новый.

**Approve-flow**: `ReviewService.mutate` (~`:397`) получает ветку `question_type ==
"summary_assessment_approval"` — approve → `notion.create_comment`, reject/ignore → discard. Это тот же
механизм реюза, что в digest-toggle.

**Tests**: unit (`summary_email.py` против реальных fixture-примеров подписей/окон времени, включая
timeout-исчерпание и `AMBIGUOUS`-ветку), unit (`mail_imap.py` против мокнутого `imaplib` — никогда реальное
IMAP-соединение в тестах), unit (новые переходы `RecordingStatus`), integration (оба новых эндпоинта —
200/404/409/403, recruiter-scope отказ), integration (`POST /summary` — toggle через мок-`NotionClient`,
`ManualReview`-строка, idempotency-replay), integration (approve создаёт comment ровно 1 раз;
reject/ignore — ни разу), regression (полный pipeline `NOTION_UPDATED → COMPLETED` без найденного письма
не ломается), full suite `poetry run pytest -q` с цитированием результата.

**Commits**: по логическому чекпоинту — миграция/модель, конфиг, IMAP+сервис, cron-встройка,
Notion-методы, tools-эндпоинты, approve-dispatch — каждый через `/commit`.

## Blockers

- **Оценка времени.** Черновая оценка пользователя (9ч) занижена: это 2 новых auth-корректных
  tool-эндпоинта + сервисный слой, новый IMAP-клиент с нуля (своя конфигурация и тесты), новый
  `RecordingStatus` (миграция + `CHECK` + `TRANSITIONS`), Notion children-blocks/comments с нуля — ни
  одна из трёх поверхностей (IMAP, новый статус, Notion comments) не имеет кода для расширения, всё
  пишется заново. Реалистичная оценка — **16-24ч / 2+ сессии `/build`**. Нужно решение: делать полный
  скоуп сразу, или резать на v1 (например: только toggle-list без comment-approval флоу — переносится в
  отдельную фичу)?

## Out of scope

- Skill-файл/конфиг Милы в OpenClaw (сама суммаризация её моделью) — параллельная работа пользователя
  вне этого репозитория.
- Полный E2E с живой Милой — зависит от готовности её skill-конфига; `/build` в этом репо проверяет оба
  эндпоинта только мок-вызовами/curl.
- Per-recruiter Notion token override (один глобальный токен на всех — не нужен сейчас).
- Изменение `InterviewMatcher`/calink-сопоставления календаря (используется только как источник
  `candidate_email`/времени, read-only контекст).
- Переоткрытие `POST /events`/`OPENCLAW_EVENTS_URL` как push-канала — протокол остаётся
  Мила-тянет-только.
- Backfill/переобработка уже `COMPLETED` записей, чьё письмо пришло после таймаута (см. Assumptions).

## Assumptions

- IMAP-хост — стандартный Yandex 360 (`imap.yandex.ru:993`), тот же домен, что Диск/Календарь —
  подтверждено живым логином в этой сессии для Ральи и Лили, не предположение.
- Письмо, пришедшее после того как запись уже `COMPLETED` (таймаут исчерпан раньше) — НЕ переоткрывает
  запись по умолчанию; `GET summary-source` на такой записи отдаёт `409`. Если нужен другой UX
  (бэкофилл поздних писем) — отдельное решение, не в этом скоупе.
- Toggle-list — плоский список параграфов (`list[str]`), без вложенных/форматированных блоков.
- "Comment только после подтверждения" закрывается одним `ManualReview`-вопросом на запись (не
  многошаговый review).
- Один IMAP host/port на всех рекрутёров — различается только пароль (как у `YANDEX_CALDAV_PASSWORDS`).
