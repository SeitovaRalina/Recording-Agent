import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.question_digest import QuestionDigest, QuestionDigestStatus
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import (
    enforce_recruiter_scope,
    enforce_storage_key_scope,
    require_notion_preflight,
)
from app.services.candidate import CandidateService
from app.services.filename import FilenameError, build_storage_identity
from app.services.matching import (
    InterviewMatcher,
    ManualReviewReason,
    MatchResult,
    normalize_title,
)
from app.services.pipeline_trace import safe_url, trace
from app.services.question_queue import QuestionQueueService
from app.services.reviews import InteractionBinding, InteractionBindingConflict, ReviewService
from app.services.status import StatusService
from app.services.storage import StorageCollisionError
from app.services.transfer import TransferError, TransferService, cleanup_stale_temp_files
from app.tools.calendar import CalDAVAuthError, CalDAVClient, CalendarConfigurationError
from app.tools.disk import DiskScanner
from app.tools.notion import NotionClient, NotionPage, NotionRelationChoice

logger = logging.getLogger(__name__)

SUMMARY_LOCAL_HOUR = 18
SUMMARY_LOCAL_MINUTE = 0
SUMMARY_CLAIM_TTL = timedelta(minutes=15)
_SCAN_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = WeakKeyDictionary()

TRANSFER_RESUMABLE_STATUSES = (
    RecordingStatus.CALENDAR_EVENT_FOUND,
    RecordingStatus.CANDIDATE_MATCHED,
    RecordingStatus.TRANSFER_STARTED,
    RecordingStatus.UPLOADED_TO_SYNOLOGY,
    RecordingStatus.SYNOLOGY_LINK_CREATED,
    RecordingStatus.NOTION_UPDATED,
)


@dataclass
class ScanError:
    stage: str
    code: str
    message: str
    retryable: bool


@dataclass
class ScanSummary:
    discovered: int = 0
    inserted: int = 0
    skipped_legacy: int = 0
    matched: int = 0
    manual_review: int = 0
    failed: int = 0
    recording_ids: list[uuid.UUID] = field(default_factory=list)
    inserted_recording_ids: list[uuid.UUID] = field(default_factory=list)
    aborted: bool = False
    errors: list[ScanError] = field(default_factory=list)


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
    review_service: ReviewService | None = None,
    question_queue_service: QuestionQueueService | None = None,
    interaction_binding: InteractionBinding | None = None,
) -> ScanSummary:
    loop = asyncio.get_running_loop()
    locks = _SCAN_LOCKS.setdefault(loop, {})
    lock = locks.setdefault(recruiter.email, asyncio.Lock())
    async with lock:
        return await _scan_recruiter_unlocked(
            recruiter,
            session_factory,
            disk,
            cal,
            matcher,
            settings,
            now,
            candidate_service,
            transfer_service,
            status_service,
            notion,
            review_service,
            question_queue_service,
            interaction_binding,
        )


async def _scan_recruiter_unlocked(
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
    review_service: ReviewService | None = None,
    question_queue_service: QuestionQueueService | None = None,
    interaction_binding: InteractionBinding | None = None,
) -> ScanSummary:
    active_settings = settings or get_settings()
    _enforce_recruiter_scope(active_settings, recruiter)
    if interaction_binding is not None:
        await _validate_offline_interaction_binding(
            recruiter,
            session_factory,
            interaction_binding,
        )
    active_status = status_service or StatusService()
    summary = ScanSummary()
    try:
        await cal.refresh_snapshot(recruiter.email)
    except Exception as error:
        logger.warning(
            "Calendar discovery preflight failed for %s: %s",
            recruiter.email,
            type(error).__name__,
        )
        summary.aborted = True
        summary.failed = 1
        summary.errors.append(
            ScanError(
                stage="calendar_discovery",
                code="calendar_discovery_failed",
                message="Calendar discovery could not be refreshed; retry the scan.",
                retryable=True,
            )
        )
        return summary
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
            outcome, persisted_id = await _persist_found_recording(
                recruiter, file_item, session_factory, disk, active_settings, now
            )
            if outcome == "inserted":
                summary.inserted += 1
                if persisted_id is not None:
                    summary.inserted_recording_ids.append(persisted_id)
                    summary.recording_ids.append(persisted_id)
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
                recording_id, session_factory, cal, matcher, active_status, active_settings
            )
            if result is not None:
                if recording_id not in summary.recording_ids:
                    summary.recording_ids.append(recording_id)
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
                            Recording.status.in_(TRANSFER_RESUMABLE_STATUSES),
                        )
                    )
                ).all()
            )
        for recording_id in transfer_ids:
            try:
                owned = await _resume_transfer_recording(
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
                if owned and recording_id not in summary.recording_ids:
                    summary.recording_ids.append(recording_id)
            except Exception:
                summary.failed += 1
                logger.exception("Recording %s transfer pipeline failed", recording_id)
    if question_queue_service is not None:
        async with session_factory() as session:
            await question_queue_service.reconcile_processing(
                session,
                recruiter=recruiter,
                interaction_binding=interaction_binding,
            )
            await session.commit()
    if review_service is not None and (
        active_settings.mattermost_delivery_enabled or interaction_binding is not None
    ):
        async with session_factory() as session:
            pending = list(
                (
                    await session.scalars(
                        select(Recording).where(
                            Recording.disk_owner_email == recruiter.email,
                            Recording.status == RecordingStatus.MANUAL_REVIEW_REQUIRED,
                        )
                    )
                ).all()
            )
            for recording in pending:
                await review_service.enqueue_review(
                    session,
                    recording,
                    recruiter,
                    interaction_binding=interaction_binding,
                )
            await session.commit()
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


async def _validate_offline_interaction_binding(
    recruiter: RecruiterConfig,
    session_factory: async_sessionmaker[AsyncSession],
    binding: InteractionBinding,
) -> None:
    async with session_factory() as session:
        conflicting = await session.scalar(
            select(ManualReview.id)
            .join(ManualReview.recording)
            .where(
                Recording.disk_owner_email == recruiter.email,
                ManualReview.status == ManualReviewStatus.PENDING,
                or_(
                    ManualReview.recruiter_user_id.is_distinct_from(
                        binding.recruiter_user_id
                    ),
                    ManualReview.mattermost_channel_id.is_distinct_from(
                        binding.dm_channel_id
                    ),
                ),
            )
        )
    if conflicting is not None:
        raise InteractionBindingConflict(
            "Pending question belongs to another interaction"
        )


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
) -> bool:
    lease_token = str(uuid.uuid4())
    now = datetime.now(UTC)
    async with session_factory() as session:
        claimed = await session.scalar(
            update(Recording)
            .where(
                Recording.id == recording_id,
                Recording.status.in_(TRANSFER_RESUMABLE_STATUSES),
                or_(
                    Recording.processing_lease_token.is_(None),
                    Recording.processing_lease_expires_at <= now,
                ),
            )
            .values(
                processing_lease_token=lease_token,
                processing_lease_expires_at=now + timedelta(hours=6),
            )
            .returning(Recording.id)
        )
        await session.commit()
    if claimed is None:
        return False
    try:
        await _run_transfer_recording(
            recording_id,
            recruiter,
            session_factory,
            disk,
            candidate_service,
            transfer_service,
            status,
            notion,
            settings,
        )
    finally:
        async with session_factory() as session:
            await session.execute(
                update(Recording)
                .where(
                    Recording.id == recording_id,
                    Recording.processing_lease_token == lease_token,
                )
                .values(processing_lease_token=None, processing_lease_expires_at=None)
            )
            await session.commit()
    return True


def _persisted_spot(recording: Recording) -> NotionRelationChoice | None:
    required = recording.manual_review_reason == "multiple_spots"
    has_any_identity = bool(recording.notion_spot_id or recording.notion_spot_url)
    if not required and not has_any_identity:
        return None
    if not recording.project_or_spot or not recording.project_or_spot.strip():
        raise ValueError("Resolved Spot title is missing")
    if not recording.notion_spot_id or not recording.notion_spot_id.strip():
        raise ValueError("Resolved Spot opaque identity is missing")
    if not recording.notion_spot_url:
        raise ValueError("Resolved Spot URL is missing")
    return _validated_spot(
        NotionRelationChoice(
            recording.notion_spot_id,
            recording.project_or_spot,
            recording.notion_spot_url,
        )
    )


def _single_page_spot(page: NotionPage) -> NotionRelationChoice | None:
    if len(page.spots) > 1:
        raise ValueError("Candidate page has multiple unresolved Spots")
    return _validated_spot(page.spots[0]) if page.spots else None


def _validated_spot(spot: NotionRelationChoice) -> NotionRelationChoice:
    if not spot.id.strip() or not spot.title.strip():
        raise ValueError("Resolved Spot identity is incomplete")
    parsed = urlsplit(spot.url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Resolved Spot URL is unsafe")
    return spot


def _selected_spot_context(
    recording: Recording, selected_spot: NotionRelationChoice | None = None
) -> dict[str, object]:
    return {
        "project_or_spot": selected_spot.title
        if selected_spot is not None
        else recording.project_or_spot or "",
        "spot_id": selected_spot.id
        if selected_spot is not None
        else recording.notion_spot_id or "",
        "spot_url": selected_spot.url
        if selected_spot is not None
        else recording.notion_spot_url or "",
    }


async def _run_transfer_recording(
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
        recording = await session.scalar(
            select(Recording).where(Recording.id == recording_id).with_for_update()
        )
        if recording is not None and recording.status in {
            RecordingStatus.TRANSFER_STARTED,
            RecordingStatus.UPLOADED_TO_SYNOLOGY,
            RecordingStatus.SYNOLOGY_LINK_CREATED,
            RecordingStatus.NOTION_UPDATED,
        }:
            await _resume_committed_transfer_steps(
                session, recording, recruiter, disk, transfer_service, status, notion, settings
            )
            return
        if recording is None or recording.status not in {
            RecordingStatus.CALENDAR_EVENT_FOUND,
            RecordingStatus.CANDIDATE_MATCHED,
        }:
            return
        already_matched = recording.status == RecordingStatus.CANDIDATE_MATCHED
        match_confidence = 1.0
        selected_spot: NotionRelationChoice | None = None
        if already_matched:
            if not recording.notion_page_id or not recording.candidate_name:
                await status.advance(
                    session,
                    recording,
                    RecordingStatus.FAILED,
                    error_step="review_resolution",
                    error_message="Resolved candidate state is incomplete",
                )
                await session.commit()
                return
            try:
                selected_spot = _persisted_spot(recording)
            except ValueError as error:
                await status.advance(
                    session,
                    recording,
                    RecordingStatus.MANUAL_REVIEW_REQUIRED,
                    manual_review_reason="invalid_selected_spot_identity",
                    manual_review_candidates=[],
                    error_step="review_resolution",
                    error_message=str(error),
                )
                await session.commit()
                return
            page = NotionPage(
                id=recording.notion_page_id,
                url=recording.notion_page_url or "",
                title=recording.candidate_name,
                date_str=None,
                email=recording.candidate_email,
                project_or_spot=recording.project_or_spot,
                spots=(selected_spot,) if selected_spot is not None else (),
            )
            candidate_name = recording.candidate_name
        else:
            trace(
                settings,
                "pipeline.candidate_match.start",
                recording_id=recording.id,
                calendar_summary=recording.calendar_event_summary,
                calendar_start=recording.calendar_dtstart,
                recruiter_database_id=recruiter.notion_database_id,
            )
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
                trace(
                    settings,
                    "pipeline.candidate_match.manual_review",
                    recording_id=recording.id,
                    reason=match.reason,
                    confidence=match.confidence,
                    candidates=match.choices or match.candidates or [],
                )
                await status.advance(
                    session,
                    recording,
                    RecordingStatus.MANUAL_REVIEW_REQUIRED,
                    manual_review_reason=match.reason,
                    manual_review_candidates=match.choices or match.candidates or [],
                )
                await session.commit()
                return
            page = match.page
            match_confidence = match.confidence
            candidate_name = _candidate_name(recording.calendar_event_summary)
            try:
                selected_spot = _single_page_spot(page)
            except ValueError as error:
                await status.advance(
                    session,
                    recording,
                    RecordingStatus.MANUAL_REVIEW_REQUIRED,
                    manual_review_reason="invalid_selected_spot_identity",
                    manual_review_candidates=[],
                    error_step="candidate_matching",
                    error_message=str(error),
                )
                await session.commit()
                return
        try:
            identity = build_storage_identity(
                event_date=recording.calendar_dtstart.astimezone(
                    ZoneInfo(settings.scan_local_timezone)
                ).date()
                if recording.calendar_dtstart
                else datetime.now(UTC).date(),
                candidate_name=candidate_name,
                project_or_spot=page.project_or_spot,
                interview_type=settings.notion_interview_type,
                original_filename=recording.disk_filename,
                recruiter_prefix=recruiter.email,
                key_prefix=recruiter.synology_base_folder if settings.test_mode_enabled else None,
            )
            enforce_storage_key_scope(settings, recruiter, identity.key)
        except FilenameError as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.MANUAL_REVIEW_REQUIRED,
                manual_review_reason="invalid_storage_identity",
                manual_review_candidates=[],
                error_message=str(error),
            )
            await session.commit()
            return
        if (
            recording.generated_filename is not None
            and recording.generated_filename != identity.filename
        ) or (recording.storage_key is not None and recording.storage_key != identity.key):
            await status.advance(
                session,
                recording,
                RecordingStatus.MANUAL_REVIEW_REQUIRED,
                manual_review_reason="stale_storage_identity",
                manual_review_candidates=[_selected_spot_context(recording, selected_spot)],
                error_step="destination",
                error_message="Persisted storage identity does not match the selected Spot",
            )
            await session.commit()
            return
        collision = await session.scalar(
            select(Recording).where(
                Recording.storage_key == identity.key,
                Recording.id != recording.id,
            )
        )
        if collision is not None:
            await status.advance(
                session,
                recording,
                RecordingStatus.MANUAL_REVIEW_REQUIRED,
                manual_review_reason="storage_key_collision",
                manual_review_candidates=[
                    {
                        **_selected_spot_context(recording, selected_spot),
                        "conflicting_recording_id": str(collision.id),
                        "conflicting_spot_id": collision.notion_spot_id or "",
                    }
                ],
            )
            await session.commit()
            return
        trace(
            settings,
            "pipeline.candidate_match.success",
            recording_id=recording.id,
            confidence=match_confidence,
            candidate_name=candidate_name,
            notion_page_id=page.id,
            notion_page_title=page.title,
            notion_page_url=page.url,
            project_or_spot=page.project_or_spot,
            generated_filename=identity.filename,
            storage_key=identity.key,
            content_identity=recording.disk_md5 or recording.disk_file_id,
            version=recording.version + 1,
        )
        candidate_updates: dict[str, Any] = {
            "candidate_name": candidate_name,
            "candidate_email": page.email,
            "notion_database_id": recruiter.notion_database_id,
            "notion_page_id": page.id,
            "notion_page_url": page.url,
            "project_or_spot": page.project_or_spot,
            "notion_spot_id": selected_spot.id if selected_spot is not None else None,
            "notion_spot_url": selected_spot.url if selected_spot is not None else None,
            "generated_filename": identity.filename,
            "storage_key": None if settings.storage_provider == "synology" else identity.key,
            "content_identity": recording.disk_md5 or recording.disk_file_id,
        }
        if already_matched:
            for field, value in candidate_updates.items():
                setattr(recording, field, value)
        else:
            candidate_updates["version"] = recording.version + 1
            await status.advance(
                session,
                recording,
                RecordingStatus.CANDIDATE_MATCHED,
                **candidate_updates,
            )
        await session.commit()
        if settings.storage_provider == "synology" and recording.storage_destination_id is None:
            await status.advance(
                session,
                recording,
                RecordingStatus.MANUAL_REVIEW_REQUIRED,
                manual_review_reason="storage_destination_required",
                manual_review_candidates=[],
                error_step="destination",
                error_message=(
                    "Interview destination must be selected from allowed Synology inventory"
                ),
            )
            await session.commit()
            return
        await status.advance(session, recording, RecordingStatus.TRANSFER_STARTED)
        await session.commit()
        trace(
            settings,
            "pipeline.transfer.start",
            recording_id=recording.id,
            filename=recording.disk_filename,
            candidate_name=candidate_name,
        )
        try:
            result = await transfer_service.transfer(recording, recruiter, candidate_name, session)
        except TransferError as error:
            if isinstance(error.cause, StorageCollisionError):
                await status.advance(
                    session,
                    recording,
                    RecordingStatus.MANUAL_REVIEW_REQUIRED,
                    manual_review_reason="storage_key_collision",
                    manual_review_candidates=[],
                    error_message=str(error.cause),
                )
                await session.commit()
                return
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
        trace(
            settings,
            "pipeline.transfer.uploaded",
            recording_id=recording.id,
            storage_folder=result.folder_path,
            storage_path=result.file_path,
        )
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
            storage_is_durable=settings.storage_provider == "synology",
        )
        await session.commit()
        trace(
            settings,
            "pipeline.transfer.share_link",
            recording_id=recording.id,
            storage_path=result.file_path,
            share_url=safe_url(share_url),
        )
        try:
            require_notion_preflight(settings, recruiter)
        except PermissionError as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step="notion_preflight",
                error_message=str(error),
            )
            await session.commit()
            return
        try:
            if recording.calendar_dtstart is None:
                raise ValueError("Matched calendar date is missing")
            await notion.update_page_interview(
                page.id,
                date_prop=settings.notion_date_prop,
                recording_prop=settings.notion_recording_prop,
                event_date=recording.calendar_dtstart.astimezone(
                    ZoneInfo(settings.scan_local_timezone)
                ).date(),
                url=share_url,
                filename=recording.generated_filename or recording.disk_filename,
            )
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
        trace(
            settings,
            "pipeline.notion_update.success",
            recording_id=recording.id,
            notion_page_id=page.id,
            notion_page_url=page.url,
        )
        if not settings.yandex_source_mutation_enabled:
            await status.advance(
                session,
                recording,
                RecordingStatus.COMPLETED,
                completed_at=datetime.now(UTC),
            )
            await session.commit()
            return
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
        trace(
            settings,
            "pipeline.completed_source_marked",
            recording_id=recording.id,
            disk_path=recording.disk_path,
            deletable_after=recording.disk_deletable_after,
        )


async def _resume_committed_transfer_steps(
    session: AsyncSession,
    recording: Recording,
    recruiter: RecruiterConfig,
    disk: DiskScanner,
    transfer_service: TransferService,
    status: StatusService,
    notion: NotionClient,
    settings: Settings,
) -> None:
    required = {
        "generated_filename": recording.generated_filename,
        "content_identity": recording.content_identity,
    }
    if not recording.storage_key and not recording.storage_destination_id:
        required["storage_destination_id_or_storage_key"] = None
    if recording.route_type == "interview":
        required |= {
            "candidate_name": recording.candidate_name,
            "notion_page_id": recording.notion_page_id,
        }
    missing = [name for name, value in required.items() if not value]
    if missing:
        await status.advance(
            session,
            recording,
            RecordingStatus.FAILED,
            error_step="restart_recovery",
            error_message=f"Committed transfer state is incomplete: {', '.join(missing)}",
        )
        await session.commit()
        return

    if recording.status == RecordingStatus.TRANSFER_STARTED:
        try:
            result = await transfer_service.transfer(
                recording, recruiter, cast(str, recording.candidate_name), session
            )
        except TransferError as error:
            if isinstance(error.cause, StorageCollisionError):
                await status.advance(
                    session,
                    recording,
                    RecordingStatus.MANUAL_REVIEW_REQUIRED,
                    manual_review_reason="storage_key_collision",
                    manual_review_candidates=[],
                    error_message=str(error.cause),
                )
            else:
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

    if recording.status == RecordingStatus.UPLOADED_TO_SYNOLOGY:
        if not recording.synology_file_path:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step="restart_recovery",
                error_message="Committed upload has no storage path",
            )
            await session.commit()
            return
        try:
            share_url = await transfer_service.create_share_link(recording.synology_file_path)
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

    if recording.status == RecordingStatus.SYNOLOGY_LINK_CREATED:
        if recording.route_type == "non_interview":
            await status.advance(
                session,
                recording,
                RecordingStatus.COMPLETED,
                storage_is_durable=True,
                completed_at=datetime.now(UTC),
            )
            await session.commit()
            return
        try:
            require_notion_preflight(settings, recruiter)
        except PermissionError as error:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step="notion_preflight",
                error_message=str(error),
            )
            await session.commit()
            return
        if not recording.synology_share_url:
            await status.advance(
                session,
                recording,
                RecordingStatus.FAILED,
                error_step="restart_recovery",
                error_message="Committed share-link state has no URL",
            )
            await session.commit()
            return
        try:
            if recording.calendar_dtstart is None:
                raise ValueError("Matched calendar date is missing")
            await notion.update_page_interview(
                cast(str, recording.notion_page_id),
                date_prop=settings.notion_date_prop,
                recording_prop=settings.notion_recording_prop,
                event_date=recording.calendar_dtstart.astimezone(
                    ZoneInfo(settings.scan_local_timezone)
                ).date(),
                url=recording.synology_share_url,
                filename=cast(str, recording.generated_filename),
            )
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
        await status.advance(session, recording, RecordingStatus.NOTION_UPDATED)
        await session.commit()

    if recording.status != RecordingStatus.NOTION_UPDATED:
        return
    if not settings.yandex_source_mutation_enabled:
        await status.advance(
            session,
            recording,
            RecordingStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
        await session.commit()
        return
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
) -> tuple[Literal["existing", "inserted", "skipped_legacy"], uuid.UUID | None]:
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
        return "skipped_legacy", None
    async with session_factory() as session:
        existing = await session.scalar(
            select(Recording.id).where(Recording.disk_file_id == str(metadata["disk_file_id"]))
        )
        if existing is not None:
            return "existing", existing
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
        return "inserted", recording.id


async def _resume_found_recording(
    recording_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    cal: CalDAVClient,
    matcher: InterviewMatcher,
    status: StatusService | None = None,
    settings: Settings | None = None,
) -> MatchResult | None:
    lease_token = str(uuid.uuid4())
    now = datetime.now(UTC)
    async with session_factory() as session:
        claimed = await session.scalar(
            update(Recording)
            .where(
                Recording.id == recording_id,
                Recording.status == RecordingStatus.FOUND,
                or_(
                    Recording.processing_lease_token.is_(None),
                    Recording.processing_lease_expires_at <= now,
                ),
            )
            .values(
                processing_lease_token=lease_token,
                processing_lease_expires_at=now + timedelta(hours=6),
            )
            .returning(Recording.id)
        )
        await session.commit()
    if claimed is None:
        return None
    try:
        return await _run_found_recording(
            recording_id, session_factory, cal, matcher, status, settings
        )
    finally:
        async with session_factory() as session:
            await session.execute(
                update(Recording)
                .where(
                    Recording.id == recording_id,
                    Recording.processing_lease_token == lease_token,
                )
                .values(processing_lease_token=None, processing_lease_expires_at=None)
            )
            await session.commit()


async def _run_found_recording(
    recording_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    cal: CalDAVClient,
    matcher: InterviewMatcher,
    status: StatusService | None = None,
    settings: Settings | None = None,
) -> MatchResult | None:
    active_status = status or StatusService()
    active_settings = settings or get_settings()
    async with session_factory() as session:
        recording = await session.get(Recording, recording_id)
        if recording is None or recording.status != RecordingStatus.FOUND:
            return None
        try:
            parsed = matcher.parse_filename(recording.disk_filename)
            recording_time = parsed.start_utc
            trace(
                active_settings,
                "pipeline.calendar_match.parsed_filename",
                recording_id=recording.id,
                filename=recording.disk_filename,
                filename_title=parsed.title,
                filename_start_utc=recording_time,
                filename_timezone=active_settings.recording_filename_timezone,
                calendar_window_start=recording_time - timedelta(hours=2),
                calendar_window_end=recording_time + timedelta(hours=2),
            )
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
            trace(
                active_settings,
                "pipeline.calendar_match.events",
                recording_id=recording.id,
                event_count=len(events),
                events=[
                    {
                        "summary": event.summary,
                        "start": event.dtstart_utc,
                        "end": event.dtend_utc,
                        "calendar": event.calendar_display_name,
                        "eligible": event.eligible,
                        "title_exact": normalize_title(event.summary) == parsed.normalized_title,
                        "time_compatible": (
                            event.dtstart_utc - timedelta(minutes=15)
                            <= recording_time
                            <= event.dtend_utc + timedelta(minutes=15)
                        ),
                    }
                    for event in events
                ],
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
        trace(
            active_settings,
            "pipeline.calendar_match.decision",
            recording_id=recording.id,
            manual_review_required=result.manual_review_required,
            reason=result.reason,
            confidence=result.confidence,
            signals=result.signals,
            best_event_summary=result.best_event.summary if result.best_event else None,
            best_event_start=result.best_event.dtstart_utc if result.best_event else None,
            candidates=[candidate.as_dict() for candidate in result.candidates],
        )
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
        excluded_emails = {
            recording.disk_owner_email.casefold(),
            event.organizer_email.casefold(),
        }
        candidate_attendees = sorted(
            {
                attendee.strip().casefold()
                for attendee in event.attendees
                if attendee.strip() and attendee.strip().casefold() not in excluded_emails
            }
        )
        updates.update(
            calendar_event_uid=event.uid,
            calendar_event_recurrence_id=event.recurrence_id,
            calendar_event_summary=event.summary,
            calendar_dtstart=event.dtstart_utc,
            calendar_dtend=event.dtend_utc,
            calendar_organizer=event.organizer_email,
            candidate_email=(candidate_attendees[0] if len(candidate_attendees) == 1 else None),
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
    review_service: ReviewService | None = None,
    question_queue_service: QuestionQueueService | None = None,
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
                review_service=review_service,
                question_queue_service=question_queue_service,
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
    review_service: ReviewService | None = None,
    question_queue_service: QuestionQueueService | None = None,
) -> None:
    settings = get_settings()
    scheduler.add_job(
        cleanup_stale_temp_files,
        "interval",
        hours=1,
        max_instances=1,
        id="cleanup_stale_transfer_files",
        replace_existing=True,
    )
    if settings.mattermost_delivery_enabled and question_queue_service is not None:
        scheduler.add_job(
            drain_notification_outbox,
            "interval",
            seconds=10,
            args=[session_factory, question_queue_service],
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
            id="deliver_notification_outbox",
            replace_existing=True,
        )
    if not settings.scheduler_enabled:
        logger.info("Scheduled recording scan is disabled")
        return
    if question_queue_service is None:
        raise RuntimeError("Question queue service is required when scheduler is enabled")
    scheduler.add_job(
        run_due_recruiter_summaries,
        "interval",
        minutes=1,
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
            review_service,
            question_queue_service,
        ],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=86400,
        id="scan_due_recruiter_summaries",
        replace_existing=True,
    )
    logger.info(
        "recruiter-local scan/summary dispatcher registered: local_time=%02d:%02d",
        SUMMARY_LOCAL_HOUR,
        SUMMARY_LOCAL_MINUTE,
    )


async def run_due_recruiter_summaries(
    session_factory: async_sessionmaker[AsyncSession],
    disk: DiskScanner,
    cal: CalDAVClient,
    matcher: InterviewMatcher,
    settings: Settings,
    candidate_service: CandidateService | None,
    transfer_service: TransferService | None,
    status_service: StatusService | None,
    notion: NotionClient | None,
    review_service: ReviewService | None,
    question_queue_service: QuestionQueueService,
    now: datetime | None = None,
) -> None:
    current = _utc(now or datetime.now(UTC))
    for recruiter in await _active_recruiters(session_factory):
        local_date = _due_recruiter_local_date(recruiter, current)
        if (
            local_date is None
            or not recruiter.mattermost_user_id
            or not recruiter.mattermost_dm_channel
        ):
            continue
        claimed = await _claim_daily_digest(
            session_factory,
            recruiter.mattermost_user_id,
            recruiter.mattermost_dm_channel,
            local_date,
            current,
        )
        if not claimed:
            continue
        try:
            summary = await scan_recruiter(
                recruiter,
                session_factory,
                disk,
                cal,
                matcher,
                settings,
                now=current,
                candidate_service=candidate_service,
                transfer_service=transfer_service,
                status_service=status_service,
                notion=notion,
                review_service=review_service,
                question_queue_service=question_queue_service,
            )
            if summary.aborted:
                logger.warning(
                    "Scheduled recruiter scan aborted before digest for %s", recruiter.email
                )
                await _mark_daily_digest_failed(
                    session_factory,
                    recruiter.mattermost_user_id,
                    recruiter.mattermost_dm_channel,
                    local_date,
                )
                continue
            async with session_factory() as session:
                await question_queue_service.build_digest(
                    session,
                    recruiter_user_id=recruiter.mattermost_user_id,
                    dm_channel_id=recruiter.mattermost_dm_channel,
                    local_date=local_date,
                )
                await session.commit()
        except Exception:
            logger.exception("Scheduled recruiter scan/summary failed for %s", recruiter.email)
            await _mark_daily_digest_failed(
                session_factory,
                recruiter.mattermost_user_id,
                recruiter.mattermost_dm_channel,
                local_date,
            )


async def drain_notification_outbox(
    session_factory: async_sessionmaker[AsyncSession],
    service: QuestionQueueService,
) -> None:
    worker_id = str(uuid.uuid4())
    async with session_factory() as session:
        items = await service.claim_outbox(session, worker_id=worker_id)
        await session.commit()
        for item in items:
            try:
                await service.deliver_claimed(session, item, worker_id=worker_id)
                await session.commit()
            except Exception:
                await session.commit()
                logger.exception("Notification outbox delivery failed for item %s", item.id)


def _due_recruiter_local_date(recruiter: RecruiterConfig, now: datetime) -> date | None:
    try:
        local = _utc(now).astimezone(ZoneInfo(recruiter.timezone))
    except Exception:
        logger.error("Recruiter %s has invalid timezone", recruiter.email)
        return None
    due = time(SUMMARY_LOCAL_HOUR, SUMMARY_LOCAL_MINUTE)
    return local.date() if local.timetz().replace(tzinfo=None) >= due else None


async def _claim_daily_digest(
    session_factory: async_sessionmaker[AsyncSession],
    recruiter_user_id: str,
    dm_channel_id: str,
    local_date: date,
    now: datetime,
) -> bool:
    async with session_factory() as session:
        existing = await session.scalar(
            select(QuestionDigest)
            .where(
                QuestionDigest.recruiter_user_id == recruiter_user_id,
                QuestionDigest.mattermost_channel_id == dm_channel_id,
                QuestionDigest.local_date == local_date,
            )
            .with_for_update(skip_locked=True)
        )
        if existing is not None:
            created_at = _utc(existing.created_at)
            if existing.status == QuestionDigestStatus.SENT:
                return False
            if (
                existing.status == QuestionDigestStatus.PENDING
                and created_at > now - SUMMARY_CLAIM_TTL
            ):
                return False
            existing.status = QuestionDigestStatus.PENDING
            existing.created_at = now
            await session.commit()
            return True
        session.add(
            QuestionDigest(
                recruiter_user_id=recruiter_user_id,
                mattermost_channel_id=dm_channel_id,
                local_date=local_date,
                created_at=now,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
        return True


async def _mark_daily_digest_failed(
    session_factory: async_sessionmaker[AsyncSession],
    recruiter_user_id: str,
    dm_channel_id: str,
    local_date: date,
) -> None:
    async with session_factory() as session:
        digest = await session.scalar(
            select(QuestionDigest).where(
                QuestionDigest.recruiter_user_id == recruiter_user_id,
                QuestionDigest.mattermost_channel_id == dm_channel_id,
                QuestionDigest.local_date == local_date,
            )
        )
        if digest is not None:
            digest.status = QuestionDigestStatus.FAILED
            await session.commit()


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


async def _send_recruiter_notifications(
    recruiter: RecruiterConfig,
    session_factory: async_sessionmaker[AsyncSession],
    service: ReviewService,
) -> None:
    async with session_factory() as session:
        pending = list(
            (
                await session.scalars(
                    select(Recording).where(
                        Recording.disk_owner_email == recruiter.email,
                        Recording.status == RecordingStatus.MANUAL_REVIEW_REQUIRED,
                    )
                )
            ).all()
        )
        for recording in pending:
            try:
                await service.issue_review(session, recording, recruiter)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Failed to send review DM for recording %s", recording.id)
        terminal = list(
            (
                await session.scalars(
                    select(Recording).where(
                        Recording.disk_owner_email == recruiter.email,
                        Recording.status.in_([RecordingStatus.COMPLETED, RecordingStatus.FAILED]),
                        Recording.terminal_notified_at.is_(None),
                        Recording.terminal_notification_claim.is_(None),
                    )
                )
            ).all()
        )
        for recording in terminal:
            try:
                await service.deliver_terminal(session, recording, recruiter)
            except Exception:
                await session.rollback()
                logger.exception("Failed to send terminal DM for recording %s", recording.id)


def _enforce_recruiter_scope(settings: Settings, recruiter: RecruiterConfig) -> None:
    enforce_recruiter_scope(settings, recruiter)
