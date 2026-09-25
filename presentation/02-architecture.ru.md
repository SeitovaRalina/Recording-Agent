# Архитектура Recording Agent

Главная мысль: модель общается, бэкенд исполняет. У Милы нет ключей от внешних сервисов, есть только узкие команды навыка. Каждое её действие бэкенд проверяет заново.

## Схема компонентов

```mermaid
flowchart LR
    R["👤 Рекрутер<br/>личка в Mattermost"]

    subgraph OC["OpenClaw · сервер"]
        M["Мила<br/>навык recording-agent<br/>понимает просьбу, задаёт вопросы"]
        D["Cron-диспетчер<br/>раз в 2 минуты<br/>автовыбор папки"]
    end

    subgraph BE["Backend · FastAPI"]
        API["Tools API<br/>scan · status · answer · route-interview · cleanup …"]
        SCH["Планировщик<br/>скан Диска · сводка в 18:00"]
        CORE["Сопоставление · перенос файлов<br/>очередь вопросов · уведомления"]
        DB[("PostgreSQL<br/>статусы записей<br/>вопросы · идемпотентность")]
    end

    DISK["Яндекс.Диск<br/>записи Телемоста"]
    CAL["Яндекс.Календарь<br/>CalDAV"]
    NOTION["Notion<br/>карточки и Spot"]
    SYN["Synology<br/>файлы и ссылки"]
    MMB["Mattermost Bot<br/>сообщения бэкенда"]
    PROXY{{"прокси"}}

    R <-->|сообщения| M
    M -->|"CLI → HTTP, только loopback"| API
    D -->|"одноразовый ключ задания"| M
    API --> CORE
    SCH --> CORE
    CORE <--> DB
    CORE --> DISK
    CORE --> CAL
    CORE --> PROXY --> NOTION
    CORE --> SYN
    CORE --> MMB --> R
```

## Та же схема без Mermaid (для слайда или печати)

```text
 Рекрутер ◄──────────────── сообщения «готово», вопросы, сводка 18:00 ───────────┐
    │ личка                                                                     │
    ▼                                                                           │
┌──────────────────────┐   CLI → HTTP    ┌───────────────────────────────────┐   │
│ Мила · OpenClaw      │ ──────────────► │ Backend · FastAPI                 │   │
│ навык recording-agent│   (loopback)    │  • планировщик: скан, сводка      │   │
│ нет ключей сервисов  │                 │  • сопоставление записи           │   │
└──────────────────────┘                 │  • перенос файлов, ссылки         │   │
          ▲                              │  • очередь вопросов и уведомлений │   │
          │ одноразовый ключ задания     │  • все ключи сервисов — здесь     │   │
┌──────────────────────┐                 └──────┬──────────┬─────────────────┘   │
│ Cron-диспетчер       │                        │          │                     │
│ раз в 2 мин          │                 ┌──────▼──────┐   ├──► Яндекс.Диск       │
└──────────────────────┘                 │ PostgreSQL  │   ├──► Яндекс.Календарь  │
                                         │ статусы,    │   ├──► прокси ──► Notion │
                                         │ вопросы     │   ├──► Synology          │
                                         └─────────────┘   └──► Mattermost Bot ───┘
```

## Что показать на схеме словами

| Элемент | Роль | Чего у него нет |
|---|---|---|
| Мила | понимает свободный текст рекрутера, вызывает команды навыка, задаёт вопросы | ключей от Диска, Notion, Synology; доступа к путям на сервере; команд удаления |
| Cron-диспетчер | раз в две минуты спрашивает бэкенд, есть ли задание; если есть — запускает Милу в отдельной сессии | модели: пустой опрос обходится без LLM |
| Backend | делает всю работу с сервисами, хранит состояние, отправляет сообщения | собственных решений о папке: выбор папки — только из разрешённого списка |
| PostgreSQL | статус каждой записи по шагам, вопросы, защита от повторов | — |
| Прокси | единственный путь от сервера к Notion | стабильности: главный источник сбоев |

## Статусы одной записи

```mermaid
stateDiagram-v2
    direction LR
    [*] --> found
    found --> calendar_event_found
    calendar_event_found --> candidate_matched
    candidate_matched --> transfer_started
    transfer_started --> uploaded_to_synology
    uploaded_to_synology --> synology_link_created
    synology_link_created --> notion_updated
    notion_updated --> completed
    found --> manual_review_required: неясно
    calendar_event_found --> manual_review_required
    candidate_matched --> manual_review_required
    manual_review_required --> candidate_matched: ответ рекрутера
    manual_review_required --> ignored: «пропусти»
    transfer_started --> failed
    failed --> transfer_started: повтор
```

Каждый шаг сохраняется. После сбоя запись продолжает с последнего сохранённого шага, и файл второй раз не загружается.
