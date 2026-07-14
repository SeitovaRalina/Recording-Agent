from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.calendar import CalDAVClient

ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-1
SUMMARY:Интервью (Иван Иванов)
DTSTART;TZID=Europe/Moscow:20260714T120000
DTEND;TZID=Europe/Moscow:20260714T130000
DESCRIPTION:https://telemost.360.yandex.ru/j/123
ORGANIZER:mailto:recruiter@example.com
ATTENDEE:mailto:candidate@example.com
END:VEVENT
END:VCALENDAR
"""


def test_parse_vevent_tzid_and_fields() -> None:
    event = CalDAVClient.parse_vevent(ICS)

    assert event.dtstart_utc == datetime(2026, 7, 14, 9, tzinfo=UTC)
    assert event.summary == "Интервью (Иван Иванов)"
    assert event.attendees == ["candidate@example.com"]


@pytest.mark.anyio
async def test_find_events_filters_server_out_of_range(session: AsyncSession) -> None:
    session.add(
        RecruiterConfig(
            email="recruiter@example.com",
            notion_database_id="notion",
            synology_base_folder="/recordings",
            caldav_calendar_url="https://caldav.test/calendar/",
        )
    )
    await session.commit()
    outside = ICS.replace("event-1", "event-2").replace("20260714T12", "20260715T12")
    xml = (
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        f"<d:response><d:propstat><d:prop><c:calendar-data>{ICS}</c:calendar-data>"
        f"</d:prop></d:propstat></d:response><d:response><d:propstat><d:prop>"
        f"<c:calendar-data>{outside}</c:calendar-data></d:prop></d:propstat></d:response>"
        "</d:multistatus>"
    )
    settings = Settings(YANDEX_CALDAV_PASSWORDS='{"recruiter@example.com":"password"}')
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.request("REPORT", "https://caldav.test/calendar/").mock(
                return_value=httpx.Response(207, content=xml.encode())
            )
            events = await CalDAVClient(settings, session, client).find_events(
                "recruiter@example.com",
                datetime(2026, 7, 14, 0, tzinfo=UTC),
                datetime(2026, 7, 14, 23, 59, tzinfo=UTC),
            )
    assert [item.uid for item in events] == ["event-1"]


def test_windows_1251_decode() -> None:
    assert "Интервью" in CalDAVClient._decode_bytes("Интервью".encode("cp1251"))
