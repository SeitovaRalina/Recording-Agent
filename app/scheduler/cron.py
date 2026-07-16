import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.candidate import CandidateService
from app.services.matching import (
    InterviewMatcher,
    ManualReviewReason,
    MatchResult,
)
from app.services.status import StatusService
from app.services.transfer import TransferError, TransferService, cleanup_stale_temp_files
from app.tools.calendar import CalDAVAuthError, CalDAVClient, CalendarConfigurationError
from app.tools.disk import DiskScanner
from app.tools.notion import NotionClient

logger = logging.getLogger(__name__)


@dataclass
class ScanSummary:
    discovered: int = 0
    inserted: int = 0
    skipped_legacy: int = 0
    matched: int = 0
    manual_review: int = 0
    failed: int = 0


def local_today_start_utc(settings: Settings, now: datetime | None = None) -> datetime:
    current = _utc(now or datetime.now(UTC))
    local_zone = ZoneInfo(settings.scan_local_timezone)
    return datetime.combine(current.astimezone(local_zone).date(), time.min, local_zone).astimezone(
        UTC
    )


async def scan_recruiter(
    recruiter: RecruiterConfig,
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    cal: CalDAVClient,
    matcher: InterviewMatcher,
    settings: Settings | None = None,
    now: datetime | None = None,
    candidate_service: CandidateService | None = None,
    transfer_service: TransferService | None = None,
    status_service: StatusService | None = None,
    notion: NotionClient | None = None,
) -> ScanSummary:
    active_settings = settings or get_settings()
    active_status = status_service or StatusService()
    summary = ScanSummary()
    try:
        files = await disk.list_new(recruiter.email)
    except Exception:
        logger.exception(
            "Disk listing failed for %s; resuming persisted recordings", recruiter.email
        )
        files = []
    summary.discovered = len(files)
    for file_item in files:
        try:
            outcome = await _persist_found_recording(
                recruiter, file_item, session_factory, disk, active_settings, now
            )
            if outcome == "inserted":
                summary.inserted += 1
            elif outcome == "skipped_legacy":
                summary.skipped_legacy += 1
        except Exception:
            summary.failed += 1
            logger.exception("Failed to persist Disk recording for %s", recruiter.email)

    async with session_factory() as session:
        recording_ids = list(
            (
                await session.scalars(
                    select(Recording.id).where(
                        Recording.disk_owner_email == recruiter.email,
                        Recording.status == RecordingStatus.FOUND,
                    )
                )
            ).all()
        )
    for recording_id in recording_ids:
        try:
            result = await _resume_found_recording(
                recording_id, session_factory, cal, matcher, active_status
            )
            if result is not None:
                if result.manual_review_required:
                    summary.manual_review += 1
                    status = RecordingStatus.MANUAL_REVIEW_REQUIRED
                else:
                    summary.matched += 1
                    status = RecordingStatus.CALENDAR_EVENT_FOUND
                logger.info(
                    "recording match decision: id=%s status=%s confidence=%.2f signals=%s "
                    "event_summary=%s",
                    recording_id,
                    status,
                    result.confidence,
                    result.signals,
                    result.best_event.summary if result.best_event is not None else None,
                )
        except (CalDAVAuthError, KeyError, ValueError) as error:
            await _fail_recording(recording_id, session_factory, error, active_status)
            summary.failed += 1
            logger.error("Recording %s failed permanently: %s", recording_id, error)
        except Exception:
            summary.failed += 1
            logger.exception("Recording %s remains resumable after scan failure", recording_id)
    if all(
        service is not None
        for service in (candidate_service, transfer_service, status_service, notion)
    ):
        async with session_factory() as session:
            transfer_ids = list(
                (
                    await session.scalars(
                        select(Recording.id).where(
                            Recording.disk_owner_email == recruiter.email,
                            Recording.status == RecordingStatus.CALENDAR_EVENT_FOUND,
                        )
                    )
                ).all()
            )
        for recording_id in transfer_ids:
            try:
                await _resume_transfer_recording(
                    recording_id,
                    recruiter,
                    session_factory,
                    disk,
                    cast(CandidateService, candidate_service),
                    cast(TransferService, transfer_service),
                    cast(StatusService, status_service),
                    cast(NotionClient, notion),
                    active_settings,
                )
            except Exception:
                summary.failed += 1
                logger.exception("Recording %s transfer pipeline failed", recording_id)
    logger.info(
        "recruiter scan summary: recruiter=%s discovered=%d inserted=%d skipped_legacy=%d "
        "matched=%d manual_review=%d failed=%d",
        recruiter.email,
        summary.discovered,
        summary.inserted,
        summary.skipped_legacy,
        summary.matched,
        summary.manual_review,
        summary.failed,
    )
    return summary


async def _resume_transfer_recording(
    recording_id: uuid.UUID,
    recruiter: RecruiterConfig,
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    candidate_service: CandidateService,
    transfer_service: TransferService,
    status: StatusService,
    notion: NotionClient,
    settings: Settings,
) -> None:
    async with session_factory() as session:
        recording = await session.get(Recording, recording_id)
        if recording is None or recording.status != RecordingStatus.CALENDAR_EVENT_FOUND:
            return
        try:
            match = await candidate_service.find_and_match(recording, recruiter, session)
        except Exception as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step="candidate_matching",
                error_message=str(error),
            )
            await session.commit()
            return
        if match.page is None:
            await status.advance(
                session,
                recording,
                RecordingStatus.MANUAL_REVIEW_REQUIRED,
                manual_review_reason=match.reason,
                manual_review_candidates=match.candidates or [],
            )
            await session.commit()
            return
        page = match.page
        candidate_name = _candidate_name(recording.calendar_event_summary)
        await status.advance(
            session,
            recording,
            RecordingStatus.CANDIDATE_MATCHED,
            candidate_name=candidate_name,
            candidate_email=page.email,
            notion_database_id=recruiter.notion_database_id,
            notion_page_id=page.id,
            notion_page_url=page.url,
        )
        await session.commit()
        await status.advance(session, recording, RecordingStatus.TRANSFER_STARTED)
        await session.commit()
        try:
            result = await transfer_service.transfer(recording, recruiter, candidate_name, session)
        except TransferError as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step=error.step,
                error_message=str(error.cause),
            )
            await session.commit()
            return
        await status.advance(
            session,
            recording,
            RecordingStatus.UPLOADED_TO_SYNOLOGY,
            synology_folder_path=result.folder_path,
            synology_file_path=result.file_path,
        )
        await session.commit()
        try:
            share_url = await transfer_service.create_share_link(result.file_path)
        except TransferError as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step=error.step,
                error_message=str(error.cause),
            )
            await session.commit()
            return
        await status.advance(
            session,
            recording,
            RecordingStatus.SYNOLOGY_LINK_CREATED,
            synology_share_url=share_url,
        )
        await session.commit()
        try:
            await notion.update_page_url(page.id, settings.notion_recording_prop, share_url)
        except Exception as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step="notion_update",
                error_message=str(error),
            )
            await session.commit()
            return
        await status.advance(
            session, recording, RecordingStatus.NOTION_UPDATED, notion_page_url=page.url
        )
        await session.commit()
        try:
            await disk.mark_processed(recording.disk_path, recruiter.email)
        except Exception as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step="mark_processed",
                error_message=str(error),
            )
            await session.commit()
            return
        await status.advance(
            session,
            recording,
            RecordingStatus.SOURCE_MARKED_PROCESSED,
            source_processed=True,
            disk_deletable_after=datetime.now(UTC) + timedelta(days=7),
        )
        await session.commit()


def _candidate_name(summary: str | None) -> str:
    match = re.search(r"\(([^)]+)\)$", summary or "")
    if match is None:
        raise ValueError("Calendar event has no candidate name")
    return match.group(1).strip()


async def _persist_found_recording(
    recruiter: RecruiterConfig,
    file_item: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> Literal["existing", "inserted", "skipped_legacy"]:
    path = str(file_item["path"])
    metadata = await disk.get_metadata(path, recruiter.email)
    created_at = _datetime(metadata.get("disk_created_at"))
    active_settings = settings or get_settings()
    if (
        active_settings.scan_ignore_before_today
        and created_at is not None
        and created_at < local_today_start_utc(active_settings, now)
    ):
        logger.info(
            "legacy Disk recording skipped: recruiter=%s filename=%s created_at=%s",
            recruiter.email,
            metadata.get("disk_filename"),
            created_at.isoformat(),
        )
        return "skipped_legacy"
    async with session_factory() as session:
        existing = await session.scalar(
            select(Recording.id).where(Recording.disk_file_id == str(metadata["disk_file_id"]))
        )
        if existing is not None:
            return "existing"
        recording = Recording(
            disk_file_id=str(metadata["disk_file_id"]),
            disk_path=str(metadata["disk_path"]),
            disk_filename=str(metadata["disk_filename"]),
            disk_owner_email=recruiter.email,
            disk_created_at=created_at,
            disk_modified_at=_datetime(metadata.get("disk_modified_at")),
            disk_size_bytes=_integer(metadata.get("disk_size_bytes")),
            disk_mime_type=_optional_string(metadata.get("disk_mime_type")),
            disk_md5=_optional_string(metadata.get("disk_md5")),
        )
        session.add(recording)
        await session.commit()
        logger.info(
            "recording inserted: id=%s recruiter=%s filename=%s created_at=%s status=%s",
            recording.id,
            recruiter.email,
            recording.disk_filename,
            recording.disk_created_at.isoformat() if recording.disk_created_at else None,
            recording.status,
        )
        return "inserted"


async def _resume_found_recording(
    recording_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    cal: CalDAVClient,
    matcher: InterviewMatcher,
    status: StatusService | None = None,
) -> MatchResult | None:
    active_status = status or StatusService()
    async with session_factory() as session:
        recording = await session.get(Recording, recording_id)
        if recording is None or recording.status != RecordingStatus.FOUND:
            return None
        try:
            recording_time = matcher.parse_filename(recording.disk_filename).start_utc
        except (ValueError, KeyError):
            result = matcher.score(recording, [])
            await _apply_match_result(session, recording, result, active_status)
            await session.commit()
            return result
        try:
            events = await cal.find_events(
                recording.disk_owner_email,
                recording_time - timedelta(hours=2),
                recording_time + timedelta(hours=2),
            )
        except CalendarConfigurationError:
            result = MatchResult(
                best_event=None,
                confidence=0.0,
                signals=[],
                manual_review_required=True,
                reason=ManualReviewReason.CALENDAR_CONFIGURATION_INCOMPLETE,
            )
            await _apply_match_result(session, recording, result, active_status)
            await session.commit()
            return result
        result = matcher.score(recording, events)
        await _apply_match_result(session, recording, result, active_status)
        await session.commit()
        return result


async def _apply_match_result(
    session: AsyncSession,
    recording: Recording,
    result: MatchResult,
    status: StatusService,
) -> None:
    new_status = (
        RecordingStatus.MANUAL_REVIEW_REQUIRED
        if result.manual_review_required
        else RecordingStatus.CALENDAR_EVENT_FOUND
    )
    updates: dict[str, Any] = {
        "manual_review_reason": result.reason.value if result.reason else None,
        "manual_review_candidates": (
            [candidate.as_dict() for candidate in result.candidates] if result.candidates else None
        ),
    }
    event = result.best_event
    if result.manual_review_required or event is None:
        updates.update(
            calendar_event_uid=None,
            calendar_event_recurrence_id=None,
            calendar_event_summary=None,
            calendar_dtstart=None,
            calendar_dtend=None,
            calendar_organizer=None,
            calendar_telemost_url=None,
            calendar_raw_ics=None,
            matched_calendar_id=None,
            matched_calendar_url=None,
            matched_calendar_display_name=None,
        )
    else:
        telemost = re.search(r"https://telemost\.360\.yandex\.ru/\S+", event.description)
        updates.update(
            calendar_event_uid=event.uid,
            calendar_event_recurrence_id=event.recurrence_id,
            calendar_event_summary=event.summary,
            calendar_dtstart=event.dtstart_utc,
            calendar_dtend=event.dtend_utc,
            calendar_organizer=event.organizer_email,
            calendar_telemost_url=telemost.group(0) if telemost else None,
            calendar_raw_ics=event.raw_ics,
            matched_calendar_id=event.calendar_id,
            matched_calendar_url=event.calendar_url,
            matched_calendar_display_name=event.calendar_display_name,
        )
    await status.advance(session, recording, new_status, **updates)


async def scan_all_recruiters(
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    cal: CalDAVClient,
    matcher: InterviewMatcher,
    settings: Settings | None = None,
    candidate_service: CandidateService | None = None,
    transfer_service: TransferService | None = None,
    status_service: StatusService | None = None,
    notion: NotionClient | None = None,
) -> None:
    started_at = datetime.now(UTC)
    recruiters = await _active_recruiters(session_factory)
    logger.info("scan_all_recruiters started: active_recruiters=%d", len(recruiters))
    if not recruiters:
        logger.warning("No active recruiters configured; disk scan skipped")
    results = await asyncio.gather(
        *(
            scan_recruiter(
                item,
                session_factory,
                disk,
                cal,
                matcher,
                settings,
                candidate_service=candidate_service,
                transfer_service=transfer_service,
                status_service=status_service,
                notion=notion,
            )
            for item in recruiters
        ),
        return_exceptions=True,
    )
    for recruiter, result in zip(recruiters, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("Recruiter scan failed for %s: %s", recruiter.email, result)
    summaries = [result for result in results if isinstance(result, ScanSummary)]
    totals = ScanSummary(
        discovered=sum(item.discovered for item in summaries),
        inserted=sum(item.inserted for item in summaries),
        skipped_legacy=sum(item.skipped_legacy for item in summaries),
        matched=sum(item.matched for item in summaries),
        manual_review=sum(item.manual_review for item in summaries),
        failed=sum(item.failed for item in summaries),
    )
    logger.info(
        "scan_all_recruiters completed: duration_seconds=%.3f discovered=%d inserted=%d "
        "skipped_legacy=%d matched=%d manual_review=%d failed=%d",
        (datetime.now(UTC) - started_at).total_seconds(),
        totals.discovered,
        totals.inserted,
        totals.skipped_legacy,
        totals.matched,
        totals.manual_review,
        totals.failed,
    )


async def cleanup_expired_recordings(
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
) -> None:
    recruiters = await _active_recruiters(session_factory)
    results = await asyncio.gather(
        *(disk.delete_expired(recruiter.email) for recruiter in recruiters),
        return_exceptions=True,
    )
    for recruiter, result in zip(recruiters, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("Disk cleanup failed for %s: %s", recruiter.email, result)


async def _fail_recording(
    recording_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    error: Exception,
    status: StatusService | None = None,
) -> None:
    active_status = status or StatusService()
    async with session_factory() as session:
        recording = await session.get(Recording, recording_id)
        if recording is None or recording.status != RecordingStatus.FOUND:
            return
        await active_status.advance(
            session,
            recording,
            RecordingStatus.FAILED,
            error_step="calendar_matching",
            error_message=str(error),
        )
        await session.commit()


async def _active_recruiters(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[RecruiterConfig]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(RecruiterConfig).where(RecruiterConfig.active.is_(True))
                )
            ).all()
        )


def register_jobs(
    scheduler: AsyncIOScheduler,
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    cal: CalDAVClient,
    matcher: InterviewMatcher,
    candidate_service: CandidateService | None = None,
    transfer_service: TransferService | None = None,
    status_service: StatusService | None = None,
    notion: NotionClient | None = None,
) -> None:
    settings = get_settings()
    scan_trigger = CronTrigger(
        hour=settings.scan_hour,
        minute=settings.scan_minute,
        timezone=UTC,
    )
    scheduler.add_job(
        scan_all_recruiters,
        scan_trigger,
        args=[
            session_factory,
            disk,
            cal,
            matcher,
            settings,
            candidate_service,
            transfer_service,
            status_service,
            notion,
        ],
        max_instances=1,
        misfire_grace_time=3600,
        id="scan_all_recruiters",
        replace_existing=True,
    )
    logger.info(
        "scan_all_recruiters registered: hour=%d minute=%d next_run=%s",
        settings.scan_hour,
        settings.scan_minute,
        _next_run_time(scan_trigger).isoformat(),
    )
    cleanup_trigger = CronTrigger(
        hour=settings.disk_cleanup_hour,
        minute=settings.disk_cleanup_minute,
        timezone=UTC,
    )
    scheduler.add_job(
        cleanup_expired_recordings,
        cleanup_trigger,
        args=[session_factory, disk],
        max_instances=1,
        misfire_grace_time=3600,
        id="cleanup_expired_recordings",
        replace_existing=True,
    )
    logger.info(
        "cleanup_expired_recordings registered: hour=%d minute=%d next_run=%s",
        settings.disk_cleanup_hour,
        settings.disk_cleanup_minute,
        _next_run_time(cleanup_trigger).isoformat(),
    )
    scheduler.add_job(
        cleanup_stale_temp_files,
        "interval",
        hours=1,
        max_instances=1,
        id="cleanup_stale_transfer_files",
        replace_existing=True,
    )


def _next_run_time(trigger: CronTrigger, now: datetime | None = None) -> datetime:
    next_run = trigger.get_next_fire_time(None, now or datetime.now(UTC))
    if next_run is None:
        raise RuntimeError("Cron trigger has no next run time")
    return cast(datetime, next_run).astimezone(UTC)


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
