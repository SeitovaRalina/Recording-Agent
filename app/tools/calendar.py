import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from charset_normalizer import from_bytes
from defusedxml import ElementTree  # type: ignore[import-untyped]
from icalendar import Calendar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models.recruiter_calendar import RecruiterCalendar
from app.db.models.recruiter_config import RecruiterConfig

CALDAV_NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
DISCOVERY_MAX_AGE = timedelta(hours=24)


class CalDAVAuthError(RuntimeError):
    pass


class CalendarOriginError(ValueError):
    pass


class CalendarConfigurationError(ValueError):
    pass


class CalendarSnapshotIncomplete(RuntimeError):
    pass


@dataclass(frozen=True)
class CalendarRef:
    id: uuid.UUID | None
    canonical_url: str
    display_name: str
    eligible: bool


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
    recurrence_id: str | None = None
    calendar_id: uuid.UUID | None = None
    calendar_url: str | None = None
    calendar_display_name: str | None = None
    eligible: bool = True


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
        self._origin = self._validated_origin(settings.caldav_base_url)

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
        safe_url = self._canonical_url(url)
        password_secret = self._settings.yandex_caldav_passwords.get(recruiter_email)
        if password_secret is None:
            raise KeyError(f"No CalDAV password configured for {recruiter_email}")
        auth = httpx.BasicAuth(recruiter_email, password_secret.get_secret_value())
        request_kwargs = {**kwargs, "follow_redirects": False}
        if self._http_client is None:
            async with httpx.AsyncClient(auth=auth) as client:
                response = await client.request(method, safe_url, **request_kwargs)
        else:
            response = await self._http_client.request(
                method, safe_url, auth=auth, **request_kwargs
            )
        if response.is_redirect:
            raise CalendarOriginError(
                "CalDAV redirects are not followed with recruiter credentials"
            )
        if response.status_code == 401:
            raise CalDAVAuthError(f"CalDAV authentication failed for {recruiter_email}")
        response.raise_for_status()
        return response

    async def discover_calendars(self, recruiter_email: str) -> list[RecruiterCalendar]:
        discovered = await self._fetch_calendar_collections(recruiter_email)
        return await self._persist_discovery(recruiter_email, discovered, validate_selection=False)

    async def refresh_snapshot(self, recruiter_email: str) -> list[RecruiterCalendar]:
        """Refresh a recruiter's complete collection snapshot before a scan."""
        discovered = await self._fetch_calendar_collections(recruiter_email)
        if not discovered:
            raise CalendarSnapshotIncomplete("CalDAV discovery returned no VEVENT calendars")
        return await self._persist_discovery(recruiter_email, discovered, validate_selection=True)

    async def _fetch_calendar_collections(
        self, recruiter_email: str
    ) -> list[tuple[str, str]]:
        principal_url, home_url = await self._discover_home(recruiter_email)
        del principal_url
        response = await self._request(
            "PROPFIND",
            home_url,
            recruiter_email,
            content=(
                '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                "<d:prop><d:displayname/><d:resourcetype/>"
                "<c:supported-calendar-component-set/></d:prop></d:propfind>"
            ),
            headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
        )
        discovered = self._parse_collection_discovery(response.content, home_url)
        by_url: dict[str, str] = {}
        for canonical_url, display_name in discovered:
            previous_name = by_url.setdefault(canonical_url, display_name)
            if previous_name != display_name:
                raise CalendarSnapshotIncomplete(
                    "CalDAV discovery returned conflicting calendar collections"
                )
        return sorted(by_url.items())

    async def _persist_discovery(
        self,
        recruiter_email: str,
        discovered: list[tuple[str, str]],
        *,
        validate_selection: bool,
    ) -> list[RecruiterCalendar]:
        now = datetime.now(UTC)
        async with self._session_scope() as session:
            try:
                recruiter = await session.scalar(
                    select(RecruiterConfig).where(RecruiterConfig.email == recruiter_email)
                )
                if recruiter is None:
                    raise KeyError(f"Unknown recruiter {recruiter_email}")
                rows = list(
                    (
                        await session.scalars(
                            select(RecruiterCalendar).where(
                                RecruiterCalendar.recruiter_id == recruiter.id
                            )
                        )
                    ).all()
                )
                discovered_urls = {item[0] for item in discovered}
                selected = [row for row in rows if row.selected]
                if validate_selection:
                    if selected:
                        if any(row.canonical_url not in discovered_urls for row in selected):
                            raise CalendarSnapshotIncomplete(
                                "A selected calendar is missing from CalDAV discovery"
                            )
                    else:
                        available_defaults = [
                            row
                            for row in rows
                            if row.is_default and row.canonical_url in discovered_urls
                        ]
                        if len(available_defaults) != 1:
                            raise CalendarConfigurationError(
                                "Exactly one available default calendar is required"
                            )
                by_url = {row.canonical_url: row for row in rows}
                for canonical_url, display_name in discovered:
                    row = by_url.get(canonical_url)
                    if row is None:
                        row = RecruiterCalendar(
                            recruiter_id=recruiter.id,
                            canonical_url=canonical_url,
                            display_name=display_name,
                            last_seen_at=now,
                        )
                        session.add(row)
                        rows.append(row)
                    else:
                        row.display_name = display_name
                        row.available = True
                        row.last_seen_at = now
                        row.updated_at = now
                for row in rows:
                    if row.canonical_url not in discovered_urls:
                        row.available = False
                        row.updated_at = now
                default_rows = [row for row in rows if row.is_default]
                if not validate_selection and not default_rows and recruiter.caldav_calendar_url:
                    try:
                        legacy_url = self._canonical_url(recruiter.caldav_calendar_url)
                    except CalendarOriginError:
                        legacy_url = None
                    if legacy_url is not None:
                        legacy_row = next(
                            (
                                row
                                for row in rows
                                if row.canonical_url == legacy_url and row.available
                            ),
                            None,
                        )
                        if legacy_row is not None:
                            legacy_row.is_default = True
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return sorted(rows, key=lambda item: (item.display_name.casefold(), item.canonical_url))

    async def find_events(
        self,
        recruiter_email: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ParsedVEVENT]:
        start = self._as_utc(window_start)
        end = self._as_utc(window_end)
        calendars = await self._calendar_snapshot(recruiter_email)
        events: list[ParsedVEVENT] = []
        for calendar in calendars:
            try:
                calendar_events = await self._report_calendar(recruiter_email, calendar, start, end)
            except (CalDAVAuthError, httpx.HTTPError, ValueError, KeyError) as error:
                raise CalendarSnapshotIncomplete(
                    f"Calendar snapshot incomplete for {recruiter_email}"
                ) from error
            events.extend(calendar_events)
        return events

    async def _calendar_snapshot(self, recruiter_email: str) -> tuple[CalendarRef, ...]:
        async with self._session_scope() as session:
            recruiter = await session.scalar(
                select(RecruiterConfig).where(RecruiterConfig.email == recruiter_email)
            )
            if recruiter is None:
                raise KeyError(f"Unknown recruiter {recruiter_email}")
            rows = list(
                (
                    await session.scalars(
                        select(RecruiterCalendar).where(
                            RecruiterCalendar.recruiter_id == recruiter.id
                        )
                    )
                ).all()
            )
            if not rows:
                raise CalendarConfigurationError(
                    f"No discovered calendar configured for {recruiter_email}"
                )
            selected = [row for row in rows if row.selected]
            if selected and any(not row.available for row in selected):
                raise CalendarSnapshotIncomplete(
                    f"Selected calendar is unavailable for {recruiter_email}"
                )
            if selected and any(self._calendar_is_stale(row) for row in selected):
                raise CalendarSnapshotIncomplete(
                    f"Selected calendar discovery is stale for {recruiter_email}"
                )
            available_rows = [row for row in rows if row.available]
            if not available_rows:
                raise CalendarSnapshotIncomplete(
                    f"No available calendar snapshot for {recruiter_email}"
                )
            if any(self._calendar_is_stale(row) for row in available_rows):
                raise CalendarSnapshotIncomplete(
                    f"Calendar discovery is stale for {recruiter_email}"
                )
            selected_ids = {row.id for row in selected}
            if selected_ids:
                eligible_ids = selected_ids
            else:
                defaults = [row for row in rows if row.is_default]
                if len(defaults) != 1:
                    raise CalendarConfigurationError(
                        f"Exactly one default calendar is required for {recruiter_email}"
                    )
                if not defaults[0].available or self._calendar_is_stale(defaults[0]):
                    raise CalendarSnapshotIncomplete(
                        f"Default calendar snapshot is incomplete for {recruiter_email}"
                    )
                eligible_ids = {defaults[0].id}
            return tuple(
                CalendarRef(
                    id=row.id,
                    canonical_url=row.canonical_url,
                    display_name=row.display_name,
                    eligible=row.id in eligible_ids,
                )
                for row in sorted(available_rows, key=lambda item: str(item.id))
            )

    @classmethod
    def _calendar_is_stale(cls, row: RecruiterCalendar) -> bool:
        return cls._as_utc(row.last_seen_at) < datetime.now(UTC) - DISCOVERY_MAX_AGE

    async def _report_calendar(
        self,
        recruiter_email: str,
        calendar: CalendarRef,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ParsedVEVENT]:
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
            calendar.canonical_url,
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
                    events.append(
                        replace(
                            event,
                            calendar_id=calendar.id,
                            calendar_url=calendar.canonical_url,
                            calendar_display_name=calendar.display_name,
                            eligible=calendar.eligible,
                        )
                    )
        return events

    async def _discover_home(self, recruiter_email: str) -> tuple[str, str]:
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
        principal_url = self._canonical_url(urljoin(self._settings.caldav_base_url, principal_href))
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
        home_url = self._canonical_url(urljoin(principal_url, home_href))
        return principal_url, home_url

    def _parse_collection_discovery(self, xml_bytes: bytes, home_url: str) -> list[tuple[str, str]]:
        root = ElementTree.fromstring(self._xml_bytes(xml_bytes))
        calendars: list[tuple[str, str]] = []
        for response in root.findall(".//d:response", CALDAV_NS):
            href = response.findtext("d:href", namespaces=CALDAV_NS)
            if not href:
                continue
            for propstat in response.findall("d:propstat", CALDAV_NS):
                status = propstat.findtext("d:status", namespaces=CALDAV_NS) or ""
                prop = propstat.find("d:prop", CALDAV_NS)
                if " 200 " not in status or prop is None:
                    continue
                if prop.find("d:resourcetype/c:calendar", CALDAV_NS) is None:
                    continue
                components = prop.findall("c:supported-calendar-component-set/c:comp", CALDAV_NS)
                if not any(item.attrib.get("name", "").upper() == "VEVENT" for item in components):
                    continue
                canonical_url = self._canonical_url(urljoin(home_url, href))
                display_name = prop.findtext("d:displayname", namespaces=CALDAV_NS)
                calendars.append((canonical_url, (display_name or canonical_url).strip()))
        return sorted(calendars, key=lambda item: item[0])

    @classmethod
    def parse_vevents(cls, raw_ics: str) -> list[ParsedVEVENT]:
        calendar = Calendar.from_ical(raw_ics)
        events: list[ParsedVEVENT] = []
        for component in calendar.walk("VEVENT"):
            dtstart = cls._decoded_datetime(component.decoded("DTSTART"))
            dtend_value = component.decoded("DTEND") if component.get("DTEND") else dtstart
            attendee_value = component.get("ATTENDEE")
            attendee_items = (
                attendee_value
                if isinstance(attendee_value, list)
                else ([attendee_value] if attendee_value else [])
            )
            recurrence = component.get("RECURRENCE-ID")
            events.append(
                ParsedVEVENT(
                    uid=str(component.get("UID", "")),
                    summary=str(component.get("SUMMARY", "")),
                    dtstart_utc=dtstart,
                    dtend_utc=cls._decoded_datetime(dtend_value),
                    description=str(component.get("DESCRIPTION", "")),
                    organizer_email=cls._email(str(component.get("ORGANIZER", ""))),
                    attendees=[cls._email(str(value)) for value in attendee_items],
                    raw_ics=raw_ics,
                    recurrence_id=str(recurrence) if recurrence is not None else None,
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
    def _validated_origin(base_url: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(base_url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise CalendarOriginError("CalDAV base URL must use HTTPS with a valid host")
        return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port

    def _canonical_url(self, value: str) -> str:
        parsed = urlsplit(value)
        origin = (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)
        if origin != self._origin or parsed.username or parsed.password:
            raise CalendarOriginError("CalDAV URL must remain on the configured HTTPS origin")
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        return urlunsplit(("https", parsed.netloc.lower(), path, parsed.query, ""))

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
        decoded = cls._decode_bytes(value)
        decoded = re.sub(
            r'(<\?xml[^>]*encoding=["\'])[^"\']+',
            r"\1utf-8",
            decoded,
            count=1,
            flags=re.IGNORECASE,
        )
        return decoded.encode("utf-8")

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
