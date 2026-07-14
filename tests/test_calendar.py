from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.calendar import CalDAVAuthError, CalDAVClient

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


@pytest.mark.anyio
async def test_calendar_discovery_caches_exact_collection(session: AsyncSession) -> None:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.commit()
    principal_xml = """<d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop>
<d:current-user-principal><d:href>/principals/recruiter/</d:href></d:current-user-principal>
</d:prop></d:propstat></d:response></d:multistatus>"""
    home_xml = """<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:response><d:propstat><d:prop><c:calendar-home-set><d:href>/calendars/recruiter/</d:href>
</c:calendar-home-set></d:prop></d:propstat></d:response></d:multistatus>"""
    collections_xml = """<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:response><d:href>/calendars/recruiter/</d:href><d:propstat><d:prop>
<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
<d:response><d:href>/calendars/recruiter/interviews/</d:href><d:propstat><d:prop>
<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
</d:prop></d:propstat></d:response></d:multistatus>"""
    settings = Settings(YANDEX_CALDAV_PASSWORDS='{"recruiter@example.com":"password"}')
    async with httpx.AsyncClient() as client:
        with respx.mock:
            discovery = respx.request("PROPFIND").mock(
                side_effect=[
                    httpx.Response(207, content=principal_xml.encode()),
                    httpx.Response(207, content=home_xml.encode()),
                    httpx.Response(207, content=collections_xml.encode()),
                ]
            )
            calendar_url = await CalDAVClient(settings, session, client)._calendar_url(
                "recruiter@example.com"
            )
    await session.refresh(recruiter)
    assert calendar_url == "https://caldav.yandex.ru/calendars/recruiter/interviews/"
    assert recruiter.caldav_calendar_url == calendar_url
    assert [str(call.request.url) for call in discovery.calls] == [
        "https://caldav.yandex.ru/",
        "https://caldav.yandex.ru/principals/recruiter/",
        "https://caldav.yandex.ru/calendars/recruiter/",
    ]


@pytest.mark.anyio
async def test_caldav_401_propagates_without_retry() -> None:
    settings = Settings(YANDEX_CALDAV_PASSWORDS='{"recruiter@example.com":"password"}')
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.request("REPORT", "https://caldav.test/calendar/").mock(
                return_value=httpx.Response(401)
            )
            with pytest.raises(CalDAVAuthError):
                await CalDAVClient(settings, http_client=client)._request(
                    "REPORT", "https://caldav.test/calendar/", "recruiter@example.com"
                )
    assert route.call_count == 1
