import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.matching import InterviewMatcher
from app.tools.calendar import CalDAVClient
from app.tools.disk import DiskScanner

logger = logging.getLogger(__name__)


async def scan_recruiter(
    recruiter: RecruiterConfig,
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    cal: CalDAVClient,
    matcher: InterviewMatcher,
) -> None:
    files = await disk.list_new(recruiter.email)
    for file_item in files:
        path = str(file_item["path"])
        metadata = await disk.get_metadata(path, recruiter.email)
        async with session_factory() as session:
            existing = await session.scalar(
                select(Recording).where(Recording.disk_file_id == str(metadata["disk_file_id"]))
            )
            if existing is not None:
                continue
            recording = Recording(
                disk_file_id=str(metadata["disk_file_id"]),
                disk_path=str(metadata["disk_path"]),
                disk_filename=str(metadata["disk_filename"]),
                disk_owner_email=recruiter.email,
                disk_created_at=_datetime(metadata.get("disk_created_at")),
                disk_modified_at=_datetime(metadata.get("disk_modified_at")),
                disk_size_bytes=_integer(metadata.get("disk_size_bytes")),
                disk_mime_type=_optional_string(metadata.get("disk_mime_type")),
                disk_md5=_optional_string(metadata.get("disk_md5")),
            )
            session.add(recording)
            await session.commit()
            await session.refresh(recording)

            if recording.disk_created_at is None:
                recording.status = RecordingStatus.MANUAL_REVIEW_REQUIRED
                await session.commit()
                continue
            recording_time = _utc(recording.disk_created_at)
            events = await cal.find_events(
                recruiter.email,
                recording_time - timedelta(hours=2),
                recording_time + timedelta(hours=2),
            )
            result = matcher.score(recording, events)
            recording.status = (
                RecordingStatus.MANUAL_REVIEW_REQUIRED
                if result.manual_review_required
                else RecordingStatus.CALENDAR_EVENT_FOUND
            )
            if result.best_event is not None:
                event = result.best_event
                recording.calendar_event_uid = event.uid
                recording.calendar_event_summary = event.summary
                recording.calendar_dtstart = event.dtstart_utc
                recording.calendar_dtend = event.dtend_utc
                recording.calendar_organizer = event.organizer_email
                recording.calendar_raw_ics = event.raw_ics
                telemost = re.search(r"https://telemost\.360\.yandex\.ru/\S+", event.description)
                recording.calendar_telemost_url = telemost.group(0) if telemost else None
            await session.commit()


async def scan_all_recruiters(
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    cal: CalDAVClient,
    matcher: InterviewMatcher,
) -> None:
    async with session_factory() as session:
        recruiters = list(
            (
                await session.scalars(
                    select(RecruiterConfig).where(RecruiterConfig.active.is_(True))
                )
            ).all()
        )
    if not recruiters:
        logger.warning("No active recruiters configured; disk scan skipped")
        return
    results = await asyncio.gather(
        *(scan_recruiter(item, session_factory, disk, cal, matcher) for item in recruiters),
        return_exceptions=True,
    )
    for recruiter, result in zip(recruiters, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("Recruiter scan failed for %s", recruiter.email, exc_info=result)


def register_jobs(
    scheduler: AsyncIOScheduler,
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    cal: CalDAVClient,
    matcher: InterviewMatcher,
) -> None:
    settings = get_settings()
    scheduler.add_job(
        scan_all_recruiters,
        CronTrigger(hour=settings.scan_hour, minute=settings.scan_minute, timezone=UTC),
        args=[session_factory, disk, cal, matcher],
        max_instances=1,
        misfire_grace_time=3600,
        id="scan_all_recruiters",
        replace_existing=True,
    )


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str) and value:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _integer(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
