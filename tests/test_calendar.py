from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recruiter_calendar import RecruiterCalendar
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.calendar import (
    CalDAVAuthError,
    CalDAVClient,
    CalendarConfigurationError,
    CalendarSnapshotIncomplete,
)

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
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.flush()
    session.add(
        RecruiterCalendar(
            recruiter_id=recruiter.id,
            canonical_url="https://caldav.test/calendar/",
            display_name="Interviews",
            is_default=True,
            last_seen_at=datetime.now(UTC),
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
    settings = Settings(
        CALDAV_BASE_URL="https://caldav.test",
        YANDEX_CALDAV_PASSWORDS='{"recruiter@example.com":"password"}',
    )
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
async def test_calendar_discovery_persists_all_vevent_collections_without_guessing_default(
    session: AsyncSession,
) -> None:
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
<d:resourcetype><d:collection/></d:resourcetype></d:prop>
<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
<d:response><d:href>/calendars/recruiter/interviews/</d:href><d:propstat><d:prop>
<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
<d:displayname>Interviews</d:displayname><c:supported-calendar-component-set>
<c:comp name="VEVENT"/></c:supported-calendar-component-set>
</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"""
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
            rows = await CalDAVClient(settings, session, client).discover_calendars(
                "recruiter@example.com"
            )
    await session.refresh(recruiter)
    persisted = await session.scalar(select(RecruiterCalendar))
    assert len(rows) == 1
    assert persisted is not None
    assert persisted.canonical_url == "https://caldav.yandex.ru/calendars/recruiter/interviews/"
    assert persisted.display_name == "Interviews"
    assert persisted.is_default is False
    assert recruiter.caldav_calendar_url is None
    assert [str(call.request.url) for call in discovery.calls] == [
        "https://caldav.yandex.ru/",
        "https://caldav.yandex.ru/principals/recruiter/",
        "https://caldav.yandex.ru/calendars/recruiter/",
    ]


@pytest.mark.anyio
async def test_caldav_401_propagates_without_retry() -> None:
    settings = Settings(
        CALDAV_BASE_URL="https://caldav.test",
        YANDEX_CALDAV_PASSWORDS='{"recruiter@example.com":"password"}',
    )
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


@pytest.mark.anyio
async def test_unavailable_legacy_default_is_never_requested_before_discovery(
    session: AsyncSession,
) -> None:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
        caldav_calendar_url="https://attacker.example/calendar/",
    )
    session.add(recruiter)
    await session.flush()
    session.add(
        RecruiterCalendar(
            recruiter_id=recruiter.id,
            canonical_url="https://attacker.example/calendar/",
            display_name="Legacy default (pending discovery)",
            is_default=True,
            available=False,
            last_seen_at=datetime.now(UTC),
        )
    )
    await session.commit()
    settings = Settings(
        CALDAV_BASE_URL="https://caldav.test",
        YANDEX_CALDAV_PASSWORDS='{"recruiter@example.com":"password"}',
    )
    client = httpx.AsyncClient()
    try:
        with pytest.raises(CalendarSnapshotIncomplete):
            await CalDAVClient(settings, session, client).find_events(
                recruiter.email,
                datetime(2026, 7, 15, tzinfo=UTC),
                datetime(2026, 7, 16, tzinfo=UTC),
            )
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_selected_unavailable_or_stale_calendar_never_falls_back_to_default(
    session: AsyncSession,
) -> None:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.flush()
    default = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/default/",
        display_name="Default",
        is_default=True,
        last_seen_at=datetime.now(UTC),
    )
    selected = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/selected/",
        display_name="Selected",
        selected=True,
        available=False,
        last_seen_at=datetime.now(UTC),
    )
    session.add_all([default, selected])
    await session.commit()
    client = CalDAVClient(Settings(CALDAV_BASE_URL="https://caldav.test"), session)

    with pytest.raises(CalendarSnapshotIncomplete, match="unavailable"):
        await client._calendar_snapshot(recruiter.email)

    selected.available = True
    selected.last_seen_at = datetime.now(UTC) - timedelta(days=2)
    await session.commit()
    with pytest.raises(CalendarSnapshotIncomplete, match="stale"):
        await client._calendar_snapshot(recruiter.email)


@pytest.mark.anyio
async def test_refresh_snapshot_atomically_preserves_flags_and_updates_availability(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.flush()
    selected = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/selected/",
        display_name="Old selected",
        selected=True,
        available=False,
        last_seen_at=datetime.now(UTC) - timedelta(days=2),
    )
    missing = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/missing/",
        display_name="Missing",
        available=True,
        last_seen_at=datetime.now(UTC),
    )
    session.add_all([selected, missing])
    await session.commit()
    client = CalDAVClient(Settings(CALDAV_BASE_URL="https://caldav.test"), session)

    async def staged(_email: str) -> list[tuple[str, str]]:
        return [
            ("https://caldav.test/selected/", "Selected"),
            ("https://caldav.test/new/", "New"),
        ]

    monkeypatch.setattr(client, "_fetch_calendar_collections", staged)
    rows = await client.refresh_snapshot(recruiter.email)

    assert {row.canonical_url for row in rows if row.available} == {
        "https://caldav.test/selected/",
        "https://caldav.test/new/",
    }
    assert selected.selected is True
    assert selected.display_name == "Selected"
    assert missing.available is False


@pytest.mark.anyio
async def test_refresh_snapshot_empty_discovery_preserves_previous_snapshot(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.flush()
    existing = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/default/",
        display_name="Default",
        is_default=True,
        last_seen_at=datetime.now(UTC),
    )
    session.add(existing)
    await session.commit()
    before = existing.last_seen_at
    client = CalDAVClient(Settings(CALDAV_BASE_URL="https://caldav.test"), session)

    async def staged(_email: str) -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr(client, "_fetch_calendar_collections", staged)
    with pytest.raises(CalendarSnapshotIncomplete, match="no VEVENT"):
        await client.refresh_snapshot(recruiter.email)
    await session.refresh(existing)

    assert existing.available is True
    assert existing.display_name == "Default"
    assert existing.last_seen_at == before.replace(tzinfo=None)


@pytest.mark.anyio
async def test_refresh_snapshot_rejects_missing_selected_and_missing_default_without_mutation(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.flush()
    selected = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/selected/",
        display_name="Selected",
        selected=True,
        last_seen_at=datetime.now(UTC),
    )
    session.add(selected)
    await session.commit()
    recruiter_email = recruiter.email
    client = CalDAVClient(Settings(CALDAV_BASE_URL="https://caldav.test"), session)

    async def staged(_email: str) -> list[tuple[str, str]]:
        return [("https://caldav.test/other/", "Other")]

    monkeypatch.setattr(client, "_fetch_calendar_collections", staged)
    with pytest.raises(CalendarSnapshotIncomplete, match="selected"):
        await client.refresh_snapshot(recruiter_email)
    selected_row = await session.scalar(
        select(RecruiterCalendar).where(RecruiterCalendar.selected)
    )
    assert selected_row is selected

    selected.selected = False
    await session.commit()
    with pytest.raises(CalendarConfigurationError, match="default"):
        await client.refresh_snapshot(recruiter_email)
    other = await session.scalar(
        select(RecruiterCalendar).where(
            RecruiterCalendar.canonical_url == "https://caldav.test/other/"
        )
    )
    assert other is None
