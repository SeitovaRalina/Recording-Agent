import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from urllib.parse import urljoin

import httpx
from charset_normalizer import from_bytes
from defusedxml import ElementTree  # type: ignore[import-untyped]
from icalendar import Calendar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig

CALDAV_NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}


class CalDAVAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedVEVENT:
    uid: str
    summary: str
    dtstart_utc: datetime
    dtend_utc: datetime
    description: str
    organizer_email: str
    attendees: list[str]
    raw_ics: str


class CalDAVClient:
    def __init__(
        self,
        settings: Settings,
        session_provider: AsyncSession | async_sessionmaker[AsyncSession] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._session_provider = session_provider
        self._http_client = http_client

    @asynccontextmanager
    async def _session_scope(self) -> AsyncIterator[AsyncSession]:
        if self._session_provider is None:
            raise RuntimeError("CalDAV calendar lookup requires a database session")
        if isinstance(self._session_provider, AsyncSession):
            yield self._session_provider
            return
        async with self._session_provider() as session:
            yield session

    async def _request(
        self,
        method: str,
        url: str,
        recruiter_email: str,
        **kwargs: Any,
    ) -> httpx.Response:
        password_secret = self._settings.yandex_caldav_passwords.get(recruiter_email)
        if password_secret is None:
            raise KeyError(f"No CalDAV password configured for {recruiter_email}")
        auth = httpx.BasicAuth(recruiter_email, password_secret.get_secret_value())
        if self._http_client is None:
            async with httpx.AsyncClient(auth=auth) as client:
                response = await client.request(method, url, **kwargs)
        else:
            response = await self._http_client.request(method, url, auth=auth, **kwargs)
        if response.status_code == 401:
            raise CalDAVAuthError(f"CalDAV authentication failed for {recruiter_email}")
        response.raise_for_status()
        return response

    async def find_events(
        self,
        recruiter_email: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ParsedVEVENT]:
        window_start = self._as_utc(window_start)
        window_end = self._as_utc(window_end)
        calendar_url = await self._calendar_url(recruiter_email)
        buffered_start = window_start - timedelta(minutes=15)
        buffered_end = window_end + timedelta(minutes=15)
        body = f"""<?xml version="1.0" encoding="utf-8" ?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:calendar-data /></d:prop>
  <c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">
    <c:time-range start="{buffered_start:%Y%m%dT%H%M%SZ}" end="{buffered_end:%Y%m%dT%H%M%SZ}" />
  </c:comp-filter></c:comp-filter></c:filter>
</c:calendar-query>"""
        response = await self._request(
            "REPORT",
            calendar_url,
            recruiter_email,
            content=body.encode(),
            headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
        )
        root = ElementTree.fromstring(self._xml_bytes(response.content))
        events: list[ParsedVEVENT] = []
        for element in root.findall(".//c:calendar-data", CALDAV_NS):
            raw_ics = element.text or ""
            for event in self.parse_vevents(raw_ics):
                if window_start <= event.dtstart_utc <= window_end:
                    events.append(event)
        return events

    async def _calendar_url(self, recruiter_email: str) -> str:
        async with self._session_scope() as session:
            recruiter = await session.scalar(
                select(RecruiterConfig).where(RecruiterConfig.email == recruiter_email)
            )
            if recruiter is None:
                raise KeyError(f"Unknown recruiter {recruiter_email}")
            if recruiter.caldav_calendar_url:
                return recruiter.caldav_calendar_url

            principal_response = await self._request(
                "PROPFIND",
                self._settings.caldav_base_url,
                recruiter_email,
                content=(
                    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    "<d:prop><d:current-user-principal/></d:prop></d:propfind>"
                ),
                headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "0"},
            )
            principal_root = ElementTree.fromstring(self._xml_bytes(principal_response.content))
            principal_href = principal_root.findtext(
                ".//d:current-user-principal/d:href", namespaces=CALDAV_NS
            )
            if not principal_href:
                raise ValueError("CalDAV discovery returned no current-user-principal")
            principal_url = urljoin(self._settings.caldav_base_url, cast(str, principal_href))

            home_response = await self._request(
                "PROPFIND",
                principal_url,
                recruiter_email,
                content=(
                    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    "<d:prop><c:calendar-home-set/></d:prop></d:propfind>"
                ),
                headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "0"},
            )
            home_root = ElementTree.fromstring(self._xml_bytes(home_response.content))
            home_href = home_root.findtext(".//c:calendar-home-set/d:href", namespaces=CALDAV_NS)
            if not home_href:
                raise ValueError("CalDAV discovery returned no calendar-home-set")
            home_url = urljoin(self._settings.caldav_base_url, cast(str, home_href))

            collections_response = await self._request(
                "PROPFIND",
                home_url,
                recruiter_email,
                content=(
                    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    "<d:prop><d:resourcetype/></d:prop></d:propfind>"
                ),
                headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
            )
            collections_root = ElementTree.fromstring(self._xml_bytes(collections_response.content))
            calendar_href: str | None = None
            for response_element in collections_root.findall(".//d:response", CALDAV_NS):
                if response_element.find(".//d:resourcetype/c:calendar", CALDAV_NS) is None:
                    continue
                calendar_href = response_element.findtext("d:href", namespaces=CALDAV_NS)
                if calendar_href:
                    break
            if not calendar_href:
                raise ValueError("CalDAV discovery returned no calendar collection")
            calendar_url = urljoin(home_url, calendar_href)
            recruiter.caldav_calendar_url = calendar_url
            await session.commit()
            return calendar_url

    @classmethod
    def parse_vevents(cls, raw_ics: str) -> list[ParsedVEVENT]:
        calendar = Calendar.from_ical(raw_ics)
        events: list[ParsedVEVENT] = []
        for component in calendar.walk("VEVENT"):
            # TODO Phase 3: expand RRULE via recurring-ical-events.
            dtstart = cls._decoded_datetime(component.decoded("DTSTART"))
            dtend_value = component.decoded("DTEND") if component.get("DTEND") else dtstart
            dtend = cls._decoded_datetime(dtend_value)
            attendee_value = component.get("ATTENDEE")
            attendee_items = (
                attendee_value
                if isinstance(attendee_value, list)
                else ([attendee_value] if attendee_value else [])
            )
            events.append(
                ParsedVEVENT(
                    uid=str(component.get("UID", "")),
                    summary=str(component.get("SUMMARY", "")),
                    dtstart_utc=dtstart,
                    dtend_utc=dtend,
                    description=str(component.get("DESCRIPTION", "")),
                    organizer_email=cls._email(str(component.get("ORGANIZER", ""))),
                    attendees=[cls._email(str(value)) for value in attendee_items],
                    raw_ics=raw_ics,
                )
            )
        return events

    @classmethod
    def parse_vevent(cls, raw_ics: str) -> ParsedVEVENT:
        events = cls.parse_vevents(raw_ics)
        if not events:
            raise ValueError("iCalendar data contains no VEVENT")
        return events[0]

    @staticmethod
    def _decode_bytes(value: bytes) -> str:
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as error:
            match = from_bytes(value).best()
            if match is None:
                raise ValueError("Unable to detect CalDAV response encoding") from error
            if match.encoding and match.encoding.lower().replace("_", "-") in {
                "cp1251",
                "windows-1251",
            }:
                return str(match)
            return value.decode("windows-1251")

    @classmethod
    def _xml_bytes(cls, value: bytes) -> bytes:
        text = cls._decode_bytes(value)
        text = re.sub(
            r'(<\?xml[^>]*encoding=["\'])[^"\']+',
            r"\1utf-8",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        return text.encode("utf-8")

    @staticmethod
    def _email(value: str) -> str:
        return value.removeprefix("mailto:").removeprefix("MAILTO:")

    @classmethod
    def _decoded_datetime(cls, value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return cls._as_utc(value)
        return datetime.combine(value, time.min, tzinfo=UTC)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
