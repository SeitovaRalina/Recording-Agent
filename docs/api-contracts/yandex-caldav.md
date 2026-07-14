---
type: reference
status: draft
last_updated: 2026-07-13
sources:
  - https://yandex.com/support/calendar/en/sync/sync-desktop.html
  - https://yandex.com/support/calendar/en/sync/sync-mobile.html
  - https://github.com/ArtemIsmagilov/mm-yc-notify
  - https://github.com/Istom1n/fix-yandex-caldav
  - https://github.com/python-caldav/caldav
  - https://www.rfc-editor.org/rfc/rfc4791
---

# Яндекс.Календарь CalDAV

## Overview

**Base URL:** `https://caldav.yandex.ru`
**Port:** 443 (SSL обязателен). Fallback: 8443.

**Auth метод:** Basic Auth с **app-specific password** (подтверждено из официальных Яндекс docs).

⚠️ **OAuth Bearer token** — не упоминается ни в одном официальном doc по CalDAV Яндекса. Яндекс OAuth API для CalDAV не задокументирован. Использовать Basic Auth.

**Создание app password:**
1. Открыть id.yandex.com → Безопасность → Пароли приложений
2. Выбрать тип «CalDAV-клиент для Яндекс Календаря»
3. Скопировать пароль (показывается только один раз)

⚠️ App password может начать работать с задержкой до нескольких часов после создания.

**Формат Basic Auth:**
```
Authorization: Basic base64(login@yandex.ru:app_password)
```

---

## Известные проблемы Яндекс.Календаря (подтверждено из GitHub)

| Проблема | Источник |
|----------|----------|
| Сервер может возвращать данные в кодировке Windows-1251 вместо UTF-8 | `fix-yandex-caldav` |
| Freebusy REPORT → 504 Gateway Timeout | `mm-yc-notify` |
| События возвращаются вне запрошенного time-range из-за timezone bug | `caldav#351` |
| Несоответствие RFC 5545 — требуется нормализация .ics | `fix-yandex-caldav` |
| Серверные изменения событий без действий клиента | `mm-yc-notify` |

---

## Операция: найти доступные календари (PROPFIND)

**Request:**
```
PROPFIND /calendars/<username>/ HTTP/1.1
Host: caldav.yandex.ru
Authorization: Basic <base64(login:app_password)>
Depth: 1
Content-Type: application/xml; charset=utf-8
```

**XML body:**
```xml
<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:"
            xmlns:C="urn:ietf:params:xml:ns:caldav"
            xmlns:CS="http://calendarserver.org/ns/">
  <D:prop>
    <D:displayname/>
    <D:resourcetype/>
    <C:calendar-description/>
    <C:supported-calendar-component-set/>
    <CS:getctag/>
    <D:sync-token/>
  </D:prop>
</D:propfind>
```

**Ответ 207 Multi-Status:**
```xml
<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/calendars/user@yandex.ru/default/</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>Мой календарь</D:displayname>
        <D:resourcetype>
          <D:collection/>
          <C:calendar/>
        </D:resourcetype>
        <CS:getctag>"ctag-value"</CS:getctag>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>
```

**Как извлечь список календарей:**
- Парсить все `<D:response>`
- Оставить только те, чей `<D:resourcetype>` содержит `<C:calendar/>`
- Извлечь `<D:href>` как URL календаря
- Извлечь `<D:displayname>` как метку

**Python + httpx:**
```python
import httpx
import base64
from xml.etree import ElementTree as ET

NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
    "cs": "http://calendarserver.org/ns/",
}

def _auth_header(login: str, app_password: str) -> str:
    creds = base64.b64encode(f"{login}:{app_password}".encode()).decode()
    return f"Basic {creds}"

async def list_calendars(login: str, app_password: str) -> list[dict]:
    headers = {
        "Authorization": _auth_header(login, app_password),
        "Content-Type": "application/xml; charset=utf-8",
        "Depth": "1",
    }
    body = """<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"
            xmlns:CS="http://calendarserver.org/ns/">
  <D:prop>
    <D:displayname/><D:resourcetype/><CS:getctag/>
  </D:prop>
</D:propfind>"""

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            "PROPFIND",
            f"https://caldav.yandex.ru/calendars/{login}/",
            headers=headers,
            content=body.encode("utf-8"),
        )
        resp.raise_for_status()

    # Handle potential Windows-1251 encoding from Yandex
    text = resp.content.decode("utf-8", errors="replace")
    root = ET.fromstring(text)

    calendars = []
    for response in root.findall("d:response", NS):
        resourcetype = response.find(".//d:resourcetype", NS)
        if resourcetype is None or resourcetype.find("c:calendar", NS) is None:
            continue
        href = response.findtext("d:href", namespaces=NS)
        name = response.findtext(".//d:displayname", namespaces=NS)
        calendars.append({"href": href, "name": name})
    return calendars
```

---

## Операция: найти события в диапазоне дат (REPORT calendar-query)

**Request:**
```
REPORT /calendars/<username>/<calendar-id>/ HTTP/1.1
Host: caldav.yandex.ru
Authorization: Basic <base64(login:app_password)>
Depth: 1
Content-Type: application/xml; charset=utf-8
```

**XML body:**
```xml
<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:"
                  xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="20260713T000000Z"
                      end="20260713T235959Z"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>
```

Формат time-range: UTC `YYYYMMDDTHHmmssZ`.

⚠️ Сервер может вернуть события вне запрошенного диапазона (известный Яндекс timezone bug) — фильтровать в коде.

**Python + httpx:**
```python
from datetime import datetime, timezone, timedelta

async def find_events_in_range(
    login: str,
    app_password: str,
    calendar_href: str,
    dt_from: datetime,
    dt_to: datetime,
) -> list[str]:
    """Returns list of raw VEVENT ical strings."""
    start = dt_from.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end = dt_to.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    body = f"""<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start}" end="{end}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""

    url = f"https://caldav.yandex.ru{calendar_href}"
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            "REPORT",
            url,
            headers={
                "Authorization": _auth_header(login, app_password),
                "Content-Type": "application/xml; charset=utf-8",
                "Depth": "1",
            },
            content=body.encode("utf-8"),
        )
        resp.raise_for_status()

    text = resp.content.decode("utf-8", errors="replace")
    root = ET.fromstring(text)

    events = []
    for response in root.findall("d:response", NS):
        cal_data = response.findtext(
            ".//c:calendar-data", namespaces=NS
        )
        if cal_data:
            events.append(cal_data)
    return events
```

---

## Структура VEVENT

Подтверждённые поля из RFC 5545 + Яндекс-паттерны из GitHub-репозиториев:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Yandex//Yandex Calendar//RU
BEGIN:VEVENT
UID:unique-event-id@yandex.ru
DTSTAMP:20260713T120000Z
DTSTART;TZID=Europe/Moscow:20260714T100000
DTEND;TZID=Europe/Moscow:20260714T110000
SUMMARY:Название встречи / Имя кандидата
DESCRIPTION:Описание встречи
LOCATION:https://telemost.yandex.ru/j/<meeting-id>
URL:https://telemost.yandex.ru/j/<meeting-id>
ORGANIZER;CN="Иван Иванов":mailto:ivan@yandex.ru
ATTENDEE;CN="Пётр Петров";PARTSTAT=ACCEPTED;ROLE=REQ-PARTICIPANT:mailto:petr@example.com
X-TELEMOST-REQUIRED:TRUE
X-TELEMOST-CONFERENCE-URL:https://telemost.yandex.ru/j/<meeting-id>
STATUS:CONFIRMED
CLASS:PUBLIC
TRANSP:OPAQUE
CREATED:20260710T080000Z
LAST-MODIFIED:20260710T080000Z
END:VEVENT
END:VCALENDAR
```

**Разбор полей:**

| Поле | Формат | Примечание |
|------|--------|------------|
| `SUMMARY` | plain text | Содержит имя кандидата (гарантировано из TOR) |
| `DTSTART` | `TZID=Europe/Moscow:YYYYMMDDTHHmmss` | ⚠️ timezone в параметре, не UTC suffix |
| `DTEND` | аналогично DTSTART | |
| `ORGANIZER` | `CN="Имя":mailto:email` | email организатора/рекрутера |
| `ATTENDEE` | `CN="Имя";PARTSTAT=ACCEPTED:mailto:email` | список участников |
| `LOCATION` | URL | Ссылка на Телемост (скорее всего здесь) |
| `URL` | URL | Дублирует ссылку на встречу |
| `X-TELEMOST-CONFERENCE-URL` | URL | Яндекс-специфичный X-field с Telemost ссылкой |
| `X-TELEMOST-REQUIRED` | `TRUE/FALSE` | Флаг, что встреча через Телемост |
| `PRODID` | string | `-//Yandex//Yandex Calendar//RU` |

---

## Как извлечь данные из VEVENT

**Python-парсер (без caldav-библиотек):**
```python
import re
from datetime import datetime
import pytz

def parse_vevent(ical_text: str) -> dict:
    """Parse raw VEVENT from calendar-data into dict."""
    # Extract VEVENT block
    match = re.search(r"BEGIN:VEVENT(.+?)END:VEVENT", ical_text, re.DOTALL)
    if not match:
        return {}
    vevent = match.group(1)

    def get_field(name: str) -> str | None:
        pattern = rf"^{name}(?:;[^\n]*)?:(.+)$"
        m = re.search(pattern, vevent, re.MULTILINE)
        return m.group(1).strip() if m else None

    def parse_dt(field_name: str) -> datetime | None:
        # Handle both TZID and Z formats
        pattern = rf"^{field_name}(?:;TZID=([\w/]+))?:(\d{{8}}T\d{{6}})(Z?)$"
        m = re.search(pattern, vevent, re.MULTILINE)
        if not m:
            return None
        tzid, dt_str, is_utc = m.group(1), m.group(2), m.group(3)
        dt = datetime.strptime(dt_str, "%Y%m%dT%H%M%S")
        if is_utc:
            return dt.replace(tzinfo=pytz.utc)
        if tzid:
            return pytz.timezone(tzid).localize(dt)
        return dt

    # Extract Telemost URL from multiple possible fields
    telemost_url = None
    for field in ("X-TELEMOST-CONFERENCE-URL", "LOCATION", "URL"):
        val = get_field(field)
        if val and "telemost.yandex.ru" in val:
            telemost_url = val
            break

    # Extract organizer email
    org_raw = get_field("ORGANIZER")
    organizer_email = None
    if org_raw and "mailto:" in org_raw:
        organizer_email = org_raw.split("mailto:")[-1].strip()

    return {
        "uid": get_field("UID"),
        "summary": get_field("SUMMARY"),
        "dtstart": parse_dt("DTSTART"),
        "dtend": parse_dt("DTEND"),
        "organizer_email": organizer_email,
        "telemost_url": telemost_url,
        "description": get_field("DESCRIPTION"),
        "location": get_field("LOCATION"),
        "prodid": get_field("PRODID"),
    }
```

---

## Как извлечь имя кандидата

Имя кандидата гарантировано есть в `SUMMARY` (из TOR.md раздел 5).

Стратегия извлечения:
1. Взять `SUMMARY`
2. Убрать служебные слова: `Интервью`, `Interview`, `Собеседование`, `Backend`, `Frontend` и т.д.
3. Оставшийся текст — предположительное имя кандидата
4. Если имя не извлечь однозначно → `manual_review_required`

---

## Признаки события из calink.ru

⚠️ **Не подтверждено** — ни один источник не содержит реального примера VEVENT из calink.ru.

Гипотезы (требуют проверки через Q6 из open-questions.md):
- `PRODID` может ссылаться на calink или сторонний генератор
- `ORGANIZER` domain может быть нестандартным
- В `URL` или `LOCATION` может присутствовать calink.ru

**Обходное решение:** полагаться на другие сигналы из ADR-007 (scoring multi-signal), не только на calink.

---

## Обработка ошибок

| HTTP | Описание | Действие |
|------|----------|---------|
| 207 | Multi-Status — успех | Парсить ответ |
| 401 | Неверный логин или app-password | Проверить credentials, app-password ещё не активировался |
| 403 | Доступ запрещён | Проверить права |
| 404 | Путь не существует | Проверить URL calendara |
| 504 | Gateway Timeout | Известный Яндекс баг для freebusy — не использовать freebusy |

---

## CalDAV Namespaces

```python
NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
    "cs": "http://calendarserver.org/ns/",
    "i": "http://apple.com/ns/ical/",
}
```

---

## Связи

- [[auth-flow]] → app password setup, OAuth scope
- [[yandex-disk]] → matching по дате/времени
- [[status-machine]] → `calendar_event_found`, `manual_review_required`
- [[data-model]] → поля `calendar_event_id`, `candidate_name_from_calendar`, `telemost_url`
- open-questions: Q4 (Telemost folder), Q6 (calink.ru markers), Q7 (multi-account)
