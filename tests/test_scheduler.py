import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.models.manual_review import ManualReview
from app.db.models.question_digest import QuestionDigest, QuestionDigestStatus
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.main import app
from app.scheduler.cron import (
    ScanSummary,
    _claim_daily_digest,
    _due_recruiter_local_date,
    _persist_found_recording,
    _resume_found_recording,
    _resume_transfer_recording,
    _send_recruiter_notifications,
    local_today_start_utc,
    register_jobs,
    run_due_recruiter_summaries,
    scan_all_recruiters,
    scan_recruiter,
)
from app.services.canary import notion_schema_hash, notion_token_hash
from app.services.candidate import CandidateMatchResult
from app.services.matching import InterviewMatcher
from app.services.reviews import (
    InteractionBinding,
    InteractionBindingConflict,
    ReviewRejectedError,
    ReviewService,
)
from app.services.status import StatusService
from app.services.storage import StorageCollisionError
from app.services.transfer import TransferError, TransferResult
from app.tools.calendar import CalDAVAuthError, ParsedVEVENT
from app.tools.mattermost import MattermostError, MattermostPost
from app.tools.notion import NotionPage, NotionRelationChoice


def found(file_id: str) -> Recording:
    return Recording(
        disk_file_id=file_id,
        disk_path=f"disk:/{file_id}.webm",
        disk_filename="2026-07-14_100000_Team sync.webm",
        disk_owner_email="recruiter@example.com",
        disk_created_at=datetime(2026, 7, 14, 10, tzinfo=UTC),
    )


def disk_metadata(file_id: str, created_at: datetime) -> dict[str, object]:
    return {
        "disk_file_id": file_id,
        "disk_path": f"disk:/{file_id}.webm",
        "disk_filename": f"{created_at:%Y-%m-%d_%H%M%S}_Team sync.webm",
        "disk_created_at": created_at,
    }


def recruiter() -> RecruiterConfig:
    return RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )


@pytest.mark.anyio
async def test_discovery_skips_only_new_files_before_local_today() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(scan_local_timezone="Asia/Omsk")
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    cutoff = local_today_start_utc(settings, now)
    disk = AsyncMock()
    disk.get_metadata.side_effect = [
        disk_metadata("legacy", cutoff - timedelta(seconds=1)),
        disk_metadata("current", cutoff),
    ]

    legacy, legacy_id = await _persist_found_recording(
        recruiter(), {"path": "disk:/legacy.webm"}, factory, disk, settings, now
    )
    current, current_id = await _persist_found_recording(
        recruiter(), {"path": "disk:/current.webm"}, factory, disk, settings, now
    )
    async with factory() as session:
        recordings = list((await session.scalars(select(Recording))).all())
    await engine.dispose()

    assert legacy == "skipped_legacy"
    assert legacy_id is None
    assert current == "inserted"
    assert current_id is not None
    assert [item.disk_file_id for item in recordings] == ["current"]


@pytest.mark.anyio
async def test_successful_scan_logs_insert_match_and_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    created = datetime(2026, 7, 15, 10, tzinfo=UTC)
    disk = AsyncMock()
    disk.list_new.return_value = [{"path": "disk:/current.webm"}]
    disk.get_metadata.return_value = disk_metadata("current", created)
    calendar = AsyncMock()
    calendar.find_events.return_value = []

    with caplog.at_level("INFO"):
        summary = await scan_recruiter(
            recruiter(),
            factory,
            disk,
            calendar,
            InterviewMatcher(Settings(recording_filename_timezone="UTC")),
            Settings(scan_local_timezone="UTC"),
            datetime(2026, 7, 15, 12, tzinfo=UTC),
        )
    await engine.dispose()

    assert "recording inserted:" in caplog.text
    assert "recording match decision:" in caplog.text
    assert "recruiter scan summary:" in caplog.text
    assert summary.recording_ids == summary.inserted_recording_ids
    assert len(summary.recording_ids) == 1


@pytest.mark.anyio
async def test_scan_refreshes_calendar_once_before_disk_listing() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    order: list[str] = []

    async def refresh_snapshot(_email: str) -> None:
        order.append("calendar")

    async def list_new(_email: str) -> list[object]:
        order.append("disk")
        return []

    calendar = AsyncMock()
    calendar.refresh_snapshot.side_effect = refresh_snapshot
    disk = AsyncMock()
    disk.list_new.side_effect = list_new

    summary = await scan_recruiter(
        recruiter(), factory, disk, calendar, InterviewMatcher(Settings())
    )
    await engine.dispose()

    assert summary.aborted is False
    assert order == ["calendar", "disk"]
    calendar.refresh_snapshot.assert_awaited_once_with("recruiter@example.com")


@pytest.mark.anyio
async def test_calendar_refresh_failure_aborts_without_downstream_or_row_mutation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        row = found("retryable")
        session.add(row)
        await session.commit()
        version = row.version
    calendar = AsyncMock()
    calendar.refresh_snapshot.side_effect = httpx.ConnectError("secret upstream URL")
    disk = AsyncMock()
    review = AsyncMock()

    summary = await scan_recruiter(
        recruiter(),
        factory,
        disk,
        calendar,
        InterviewMatcher(Settings()),
        review_service=review,
    )
    async with factory() as session:
        persisted = await session.get(Recording, row.id)
    await engine.dispose()

    assert summary.aborted is True
    assert summary.failed == 1
    assert summary.errors[0].stage == "calendar_discovery"
    assert summary.errors[0].code == "calendar_discovery_failed"
    assert persisted is not None
    assert persisted.status == RecordingStatus.FOUND
    assert persisted.version == version
    disk.list_new.assert_not_awaited()
    calendar.find_events.assert_not_awaited()
    review.enqueue_review.assert_not_awaited()


@pytest.mark.anyio
async def test_concurrent_recruiter_scans_are_serialized() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    entered = 0
    maximum = 0
    release = asyncio.Event()

    async def refresh(_email: str) -> None:
        nonlocal entered, maximum
        entered += 1
        maximum = max(maximum, entered)
        await release.wait()
        entered -= 1

    calendar = AsyncMock()
    calendar.refresh_snapshot.side_effect = refresh
    disk = AsyncMock()
    disk.list_new.return_value = []
    first = asyncio.create_task(
        scan_recruiter(recruiter(), factory, disk, calendar, InterviewMatcher(Settings()))
    )
    second = asyncio.create_task(
        scan_recruiter(recruiter(), factory, disk, calendar, InterviewMatcher(Settings()))
    )
    await asyncio.sleep(0)
    assert calendar.refresh_snapshot.await_count == 1
    release.set()
    await asyncio.gather(first, second)
    await engine.dispose()

    assert maximum == 1
    assert calendar.refresh_snapshot.await_count == 2


@pytest.mark.anyio
async def test_resume_persists_unique_calendar_provenance_and_exact_title_gate() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    title = "Meeting (Ivan Ivanov)"
    item = Recording(
        disk_file_id="positive",
        disk_path="disk:/positive.webm",
        disk_filename=f"{start:%Y-%m-%d_%H%M%S}_{title}.webm",
        disk_owner_email="recruiter@example.com",
        disk_created_at=start,
    )
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    calendar_id = uuid.uuid4()
    calendar = AsyncMock()
    calendar.find_events.return_value = [
        ParsedVEVENT(
            uid="event-1",
            summary=title,
            dtstart_utc=start,
            dtend_utc=start + timedelta(hours=1),
            description="https://calink.ru/recruiter/interview/123",
            organizer_email="recruiter@example.com",
            attendees=["candidate@example.com"],
            raw_ics="raw",
            calendar_id=calendar_id,
            calendar_url="https://caldav.test/interviews/",
            calendar_display_name="Interviews",
        )
    ]

    await _resume_found_recording(
        recording_id,
        factory,
        calendar,
        InterviewMatcher(Settings(recording_filename_timezone="UTC")),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.CALENDAR_EVENT_FOUND
    assert loaded.matched_calendar_id == calendar_id
    assert loaded.matched_calendar_url == "https://caldav.test/interviews/"
    assert loaded.candidate_email == "candidate@example.com"
    assert loaded.manual_review_reason is None
    assert loaded.last_attempted_at is not None


@pytest.mark.anyio
async def test_resume_regression_title_mismatch_persists_bounded_reason_only() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    item = Recording(
        disk_file_id="regression",
        disk_path="disk:/regression.webm",
        disk_filename=f"{start:%Y-%m-%d_%H%M%S}_Не рекрутинг встреча.webm",
        disk_owner_email="recruiter@example.com",
        disk_created_at=start,
    )
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    calendar = AsyncMock()
    calendar.find_events.return_value = [
        ParsedVEVENT(
            uid="wrong-event",
            summary="Встреча на 30 минут (Иван Иванов)",
            dtstart_utc=start,
            dtend_utc=start + timedelta(hours=1),
            description="https://calink.ru/recruiter/interview/123",
            organizer_email="recruiter@example.com",
            attendees=[],
            raw_ics="must-not-persist",
        )
    ]

    await _resume_found_recording(
        recording_id,
        factory,
        calendar,
        InterviewMatcher(Settings(recording_filename_timezone="UTC")),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.MANUAL_REVIEW_REQUIRED
    assert loaded.manual_review_reason == "no_compatible_event"
    assert loaded.calendar_event_uid is None
    assert loaded.calendar_raw_ics is None
    assert loaded.matched_calendar_url is None
    assert loaded.last_attempted_at is not None


@pytest.mark.anyio
async def test_persistence_failure_is_counted_in_recruiter_summary() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    disk = AsyncMock()
    disk.list_new.return_value = [{"path": "disk:/broken.webm"}]
    disk.get_metadata.side_effect = RuntimeError("metadata unavailable")

    summary = await scan_recruiter(
        recruiter(), factory, disk, AsyncMock(), InterviewMatcher(Settings())
    )
    await engine.dispose()

    assert summary.failed == 1


@pytest.mark.anyio
async def test_scan_resumes_found_and_one_failure_does_not_abort_others() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    async with factory() as session:
        session.add_all([found("first"), found("second")])
        await session.commit()

    disk = AsyncMock()
    disk.list_new.return_value = []
    calendar = AsyncMock()
    calendar.find_events.side_effect = [
        httpx.ConnectError(
            "temporary CalDAV failure",
            request=httpx.Request("REPORT", "https://caldav.test/calendar/"),
        ),
        [],
    ]
    matcher = InterviewMatcher(Settings())

    await scan_recruiter(recruiter, factory, disk, calendar, matcher)
    async with factory() as session:
        statuses = list((await session.scalars(select(Recording.status))).all())
    assert statuses.count(RecordingStatus.FOUND) == 1
    assert statuses.count(RecordingStatus.MANUAL_REVIEW_REQUIRED) == 1

    calendar.find_events.side_effect = None
    calendar.find_events.return_value = []
    await scan_recruiter(recruiter, factory, disk, calendar, matcher)
    async with factory() as session:
        statuses = list((await session.scalars(select(Recording.status))).all())
    await engine.dispose()
    assert statuses.count(RecordingStatus.FOUND) == 0
    assert statuses.count(RecordingStatus.MANUAL_REVIEW_REQUIRED) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "message_fragment"),
    [
        (CalDAVAuthError("invalid app password"), "invalid app password"),
        (KeyError("missing calendar config"), "missing calendar config"),
        (ValueError("invalid calendar payload"), "invalid calendar payload"),
    ],
)
async def test_permanent_calendar_failure_marks_recording_failed(
    error: Exception, message_fragment: str
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    async with factory() as session:
        session.add(found("auth-failure"))
        await session.commit()
    disk = AsyncMock()
    disk.list_new.return_value = []
    calendar = AsyncMock()
    calendar.find_events.side_effect = error

    await scan_recruiter(recruiter, factory, disk, calendar, InterviewMatcher(Settings()))
    async with factory() as session:
        item = await session.scalar(select(Recording))
    await engine.dispose()

    assert item is not None
    assert item.status == RecordingStatus.FAILED
    assert item.error_step == "calendar_matching"
    assert item.error_message is not None
    assert message_fragment in item.error_message
    assert item.last_attempted_at is not None


@pytest.mark.anyio
async def test_scan_all_recruiters_isolates_recruiter_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                RecruiterConfig(
                    email="first@example.com",
                    notion_database_id="one",
                    synology_base_folder="/one",
                ),
                RecruiterConfig(
                    email="second@example.com",
                    notion_database_id="two",
                    synology_base_folder="/two",
                ),
            ]
        )
        await session.commit()
    called: list[str] = []

    async def fake_scan(recruiter: RecruiterConfig, *_args: object, **_kwargs: object) -> None:
        called.append(recruiter.email)
        if recruiter.email == "first@example.com":
            raise RuntimeError("first failed")

    monkeypatch.setattr("app.scheduler.cron.scan_recruiter", fake_scan)
    await scan_all_recruiters(factory, MagicMock(), MagicMock(), MagicMock())
    await engine.dispose()
    assert set(called) == {"first@example.com", "second@example.com"}


@pytest.mark.anyio
async def test_empty_recruiter_scan_emits_completion_totals(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    with caplog.at_level("INFO"):
        await scan_all_recruiters(factory, AsyncMock(), AsyncMock(), AsyncMock())
    await engine.dispose()

    assert "active_recruiters=0" in caplog.text
    assert "scan_all_recruiters completed:" in caplog.text
    assert "discovered=0 inserted=0 skipped_legacy=0" in caplog.text


@pytest.mark.anyio
async def test_internal_codex_scan_skips_mattermost_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    recruiter = RecruiterConfig(
        email="codex@example.com",
        notion_database_id="test-db",
        synology_base_folder="test-interviews",
        mattermost_user_id="codex-user",
        active=True,
    )
    disk = AsyncMock()
    disk.list_new.return_value = []
    delivery = AsyncMock()
    monkeypatch.setattr("app.scheduler.cron._send_recruiter_notifications", delivery)
    settings = Settings(
        openclaw_secret="secret",
        test_mode_enabled=True,
        yandex_source_mutation_enabled=False,
        mattermost_delivery_enabled=False,
        test_recruiter_allowlist={recruiter.email},
        test_notion_database_allowlist={recruiter.notion_database_id},
        test_mattermost_user_allowlist={recruiter.mattermost_user_id},
        minio_test_prefix=recruiter.synology_base_folder,
    )

    await scan_recruiter(
        recruiter,
        factory,
        disk,
        AsyncMock(),
        MagicMock(),
        settings,
        review_service=AsyncMock(),
    )
    await engine.dispose()

    delivery.assert_not_awaited()


def test_registered_cleanup_has_no_permanent_delete_authority() -> None:
    get_settings.cache_clear()
    scheduler = MagicMock()
    register_jobs(scheduler, MagicMock(), MagicMock(), MagicMock(), MagicMock())

    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args_list[0].kwargs["id"] == "cleanup_stale_transfer_files"
    assert all(
        call.kwargs["id"] != "cleanup_expired_recordings"
        for call in scheduler.add_job.call_args_list
    )
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_real_scheduler_is_disabled_by_default_but_temp_cleanup_remains(
    caplog: pytest.LogCaptureFixture,
) -> None:
    get_settings.cache_clear()
    scheduler = AsyncIOScheduler(timezone=UTC)

    with caplog.at_level("INFO"):
        register_jobs(scheduler, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        scheduler.start(paused=True)
    try:
        scan_job = scheduler.get_job("scan_due_recruiter_summaries")
        cleanup_job = scheduler.get_job("cleanup_expired_recordings")
        assert scan_job is None
        assert cleanup_job is None
        assert scheduler.get_job("cleanup_stale_transfer_files") is not None
        assert "Scheduled recording scan is disabled" in caplog.text
        assert "cleanup_expired_recordings registered:" not in caplog.text
        assert "next_run=None" not in caplog.text
    finally:
        scheduler.shutdown(wait=False)
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_app_lifespan_starts_scheduler_without_running_jobs() -> None:
    get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        assert app.state.scheduler.running is True
        assert app.state.scheduler.get_job("scan_due_recruiter_summaries") is None
        assert app.state.scheduler.get_job("cleanup_stale_transfer_files") is not None
        assert app.state.scheduler.get_job("cleanup_expired_recordings") is None
    get_settings.cache_clear()


def test_recruiter_local_due_time_handles_dst_offsets() -> None:
    owner = recruiter()
    owner.timezone = "Europe/Berlin"

    assert _due_recruiter_local_date(owner, datetime(2026, 7, 22, 15, 59, tzinfo=UTC)) is None
    assert _due_recruiter_local_date(owner, datetime(2026, 7, 22, 16, 0, tzinfo=UTC)) == date(
        2026, 7, 22
    )
    assert _due_recruiter_local_date(owner, datetime(2026, 12, 22, 16, 59, tzinfo=UTC)) is None
    assert _due_recruiter_local_date(owner, datetime(2026, 12, 22, 17, 0, tzinfo=UTC)) == date(
        2026, 12, 22
    )


@pytest.mark.anyio
async def test_daily_digest_claim_deduplicates_and_recovers_after_restart() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)

    assert await _claim_daily_digest(factory, "user", "dm", date(2026, 7, 22), now) is True
    assert (
        await _claim_daily_digest(
            factory, "user", "dm", date(2026, 7, 22), now + timedelta(minutes=1)
        )
        is False
    )
    assert (
        await _claim_daily_digest(
            factory, "user", "dm", date(2026, 7, 22), now + timedelta(minutes=16)
        )
        is True
    )
    async with factory() as session:
        assert len(list((await session.scalars(select(QuestionDigest))).all())) == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_scheduled_scan_abort_skips_digest_and_preserves_retryable_failed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "user"
    owner.mattermost_dm_channel = "dm"
    owner.timezone = "UTC"
    async with factory() as session:
        session.add(owner)
        await session.commit()
    scan = AsyncMock(return_value=ScanSummary(aborted=True, failed=1))
    monkeypatch.setattr("app.scheduler.cron.scan_recruiter", scan)
    questions = AsyncMock()
    now = datetime(2026, 7, 22, 18, tzinfo=UTC)

    await run_due_recruiter_summaries(
        factory,
        AsyncMock(),
        AsyncMock(),
        MagicMock(),
        Settings(),
        None,
        None,
        None,
        None,
        None,
        questions,
        now,
    )
    async with factory() as session:
        digest = await session.scalar(select(QuestionDigest))
    await engine.dispose()

    scan.assert_awaited_once()
    questions.build_digest.assert_not_awaited()
    assert digest is not None
    assert digest.status == QuestionDigestStatus.FAILED


def test_enabled_scheduler_registers_local_dispatcher_with_misfire_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    get_settings.cache_clear()
    scheduler = MagicMock()

    register_jobs(
        scheduler,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        question_queue_service=MagicMock(),
    )

    dispatcher = next(
        call
        for call in scheduler.add_job.call_args_list
        if call.kwargs["id"] == "scan_due_recruiter_summaries"
    )
    assert dispatcher.kwargs["coalesce"] is True
    assert dispatcher.kwargs["misfire_grace_time"] == 86400
    assert dispatcher.kwargs["max_instances"] == 1
    assert all(
        call.kwargs["id"] != "cleanup_expired_recordings"
        for call in scheduler.add_job.call_args_list
    )
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_unique_candidate_with_blank_spot_reaches_source_marked_processed() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    settings = Settings(notion_writes_enabled=True, yandex_source_mutation_enabled=True)
    owner.notion_preflight_token_hash = notion_token_hash(settings)
    owner.notion_preflight_database_id = owner.notion_database_id
    owner.notion_preflight_schema_hash = notion_schema_hash(settings)
    owner.notion_preflight_synthetic_page_id = "synthetic-page"
    owner.notion_preflight_completed_at = datetime.now(UTC)
    item = found("pipeline")
    item.status = RecordingStatus.CALENDAR_EVENT_FOUND
    item.calendar_event_summary = "Interview (Ivan Ivanov)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    page = NotionPage(
        "page",
        "https://notion/page",
        "Different Notion Title",
        "2026-07-16",
        project_or_spot=None,
    )
    candidate = AsyncMock()
    candidate.find_and_match.return_value = CandidateMatchResult(page=page, confidence=1.0)
    transfer = AsyncMock()
    transfer.transfer.return_value = TransferResult(
        "/recordings/2026-07-16/Ivan Ivanov",
        "/recordings/2026-07-16/Ivan Ivanov/video.webm",
    )
    transfer.create_share_link.return_value = "https://share/video"
    disk = AsyncMock()
    notion = AsyncMock()

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        disk,
        candidate,
        transfer,
        StatusService(),
        notion,
        settings,
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.SOURCE_MARKED_PROCESSED
    assert loaded.source_processed is True
    assert loaded.candidate_name == "Ivan Ivanov"
    assert loaded.notion_database_id == owner.notion_database_id
    assert loaded.project_or_spot is None
    assert loaded.generated_filename == (
        "2026-07-16_Ivan_Ivanov_unspecified_general_interview.webm"
    )
    assert loaded.synology_share_url == "https://share/video"
    notion.update_page_interview.assert_awaited_once_with(
        "page",
        date_prop=Settings().notion_date_prop,
        recording_prop=Settings().notion_recording_prop,
        event_date=date(2026, 7, 16),
        url="https://share/video",
        filename="2026-07-16_Ivan_Ivanov_unspecified_general_interview.webm",
    )
    disk.mark_processed.assert_awaited_once_with(item.disk_path, owner.email)


@pytest.mark.anyio
async def test_blank_spot_storage_key_collision_requires_manual_review() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = found("blank-spot-collision")
    item.status = RecordingStatus.CALENDAR_EVENT_FOUND
    item.calendar_event_summary = "Interview (Ivan Ivanov)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    expected_key = (
        "recruiter@example.com/2026-07-16/Ivan_Ivanov/"
        "2026-07-16_Ivan_Ivanov_unspecified_general_interview.webm"
    )
    conflicting = found("existing-key")
    conflicting.storage_key = expected_key
    async with factory() as session:
        session.add_all([item, conflicting])
        await session.commit()
        recording_id = item.id
    candidate = AsyncMock()
    candidate.find_and_match.return_value = CandidateMatchResult(
        page=NotionPage(
            "page",
            "https://notion/page",
            "Different Notion Title",
            "2026-07-16",
            project_or_spot=" ",
        ),
        confidence=1.0,
    )
    transfer = AsyncMock()

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        AsyncMock(),
        candidate,
        transfer,
        StatusService(),
        AsyncMock(),
        Settings(),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.MANUAL_REVIEW_REQUIRED
    assert loaded.manual_review_reason == "storage_key_collision"
    assert loaded.storage_key is None
    transfer.transfer.assert_not_awaited()


@pytest.mark.anyio
async def test_equal_spot_titles_collision_keeps_exact_spot_identities() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = found("equal-spot-title-collision")
    item.status = RecordingStatus.CALENDAR_EVENT_FOUND
    item.calendar_event_summary = "Interview (Ivan Ivanov)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    expected_key = (
        "recruiter@example.com/2026-07-16/Ivan_Ivanov/"
        "2026-07-16_Ivan_Ivanov_Backend_general_interview.webm"
    )
    conflicting = found("existing-equal-title-key")
    conflicting.storage_key = expected_key
    conflicting.project_or_spot = "Backend"
    conflicting.notion_spot_id = "different-backend-spot"
    async with factory() as session:
        session.add_all([item, conflicting])
        await session.commit()
        recording_id = item.id
    candidate = AsyncMock()
    candidate.find_and_match.return_value = CandidateMatchResult(
        page=NotionPage(
            "page",
            "https://notion.example/page",
            "Ivan Ivanov",
            None,
            project_or_spot="Backend",
            spots=(
                NotionRelationChoice(
                    "selected-backend-spot",
                    "Backend",
                    "https://notion.example/selected-backend-spot",
                ),
            ),
        ),
        confidence=1.0,
    )
    transfer = AsyncMock()

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        AsyncMock(),
        candidate,
        transfer,
        StatusService(),
        AsyncMock(),
        Settings(),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.MANUAL_REVIEW_REQUIRED
    assert loaded.manual_review_reason == "storage_key_collision"
    assert loaded.manual_review_candidates == [
        {
            "project_or_spot": "Backend",
            "spot_id": "selected-backend-spot",
            "spot_url": "https://notion.example/selected-backend-spot",
            "conflicting_recording_id": str(conflicting.id),
            "conflicting_spot_id": "different-backend-spot",
        }
    ]
    transfer.transfer.assert_not_awaited()


@pytest.mark.anyio
async def test_multiple_spot_resume_rejects_stale_storage_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = found("stale-selected-spot")
    item.status = RecordingStatus.CANDIDATE_MATCHED
    item.calendar_event_summary = "Interview (Ivan Ivanov)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    item.candidate_name = "Ivan Ivanov"
    item.notion_page_id = "candidate-page"
    item.notion_page_url = "https://notion.example/candidate-page"
    item.manual_review_reason = "multiple_spots"
    item.project_or_spot = "Backend"
    item.notion_spot_id = "backend-spot"
    item.notion_spot_url = "https://notion.example/backend-spot"
    item.generated_filename = "2026-07-16_Ivan_Ivanov_Mobile_general_interview.webm"
    item.storage_key = (
        "recruiter@example.com/2026-07-16/Ivan_Ivanov/"
        "2026-07-16_Ivan_Ivanov_Mobile_general_interview.webm"
    )
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    transfer = AsyncMock()

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        AsyncMock(),
        AsyncMock(),
        transfer,
        StatusService(),
        AsyncMock(),
        Settings(),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.MANUAL_REVIEW_REQUIRED
    assert loaded.manual_review_reason == "stale_storage_identity"
    assert loaded.notion_spot_id == "backend-spot"
    transfer.transfer.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("initial_status", "transfer_calls", "share_calls", "notion_calls"),
    [
        (RecordingStatus.TRANSFER_STARTED, 1, 1, 1),
        (RecordingStatus.UPLOADED_TO_SYNOLOGY, 0, 1, 1),
        (RecordingStatus.SYNOLOGY_LINK_CREATED, 0, 0, 1),
        (RecordingStatus.NOTION_UPDATED, 0, 0, 0),
    ],
)
async def test_transfer_pipeline_resumes_from_committed_restart_checkpoint(
    initial_status: RecordingStatus,
    transfer_calls: int,
    share_calls: int,
    notion_calls: int,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    settings = Settings(notion_writes_enabled=True, yandex_source_mutation_enabled=False)
    owner.notion_preflight_token_hash = notion_token_hash(settings)
    owner.notion_preflight_database_id = owner.notion_database_id
    owner.notion_preflight_schema_hash = notion_schema_hash(settings)
    owner.notion_preflight_synthetic_page_id = "synthetic-page"
    owner.notion_preflight_completed_at = datetime.now(UTC)
    item = found(f"restart-{initial_status.value}")
    item.status = initial_status
    item.calendar_event_summary = "Interview (Ivan Ivanov)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    item.candidate_name = "Ivan Ivanov"
    item.project_or_spot = "Project"
    item.notion_page_id = "page"
    item.notion_page_url = "https://notion/page"
    item.generated_filename = "2026-07-16_Ivan_Ivanov_Project_general_interview.webm"
    item.storage_key = f"recruiter/2026-07-16/Ivan_Ivanov/{item.generated_filename}"
    item.content_identity = item.disk_file_id
    if initial_status != RecordingStatus.TRANSFER_STARTED:
        item.synology_folder_path = "/folder"
        item.synology_file_path = f"/{item.storage_key}"
    if initial_status in {
        RecordingStatus.SYNOLOGY_LINK_CREATED,
        RecordingStatus.NOTION_UPDATED,
    }:
        item.synology_share_url = "https://share/video"
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    candidate = AsyncMock()
    transfer = AsyncMock()
    transfer.transfer.return_value = TransferResult("/folder", f"/{item.storage_key}")
    transfer.create_share_link.return_value = "https://share/video"
    notion = AsyncMock()

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        AsyncMock(),
        candidate,
        transfer,
        StatusService(),
        notion,
        settings,
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.COMPLETED
    assert transfer.transfer.await_count == transfer_calls
    assert transfer.create_share_link.await_count == share_calls
    assert notion.update_page_interview.await_count == notion_calls
    candidate.find_and_match.assert_not_awaited()


@pytest.mark.anyio
async def test_concurrent_transfer_resume_has_single_side_effect_owner() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    settings = Settings(notion_writes_enabled=True, yandex_source_mutation_enabled=False)
    owner.notion_preflight_token_hash = notion_token_hash(settings)
    owner.notion_preflight_database_id = owner.notion_database_id
    owner.notion_preflight_schema_hash = notion_schema_hash(settings)
    owner.notion_preflight_synthetic_page_id = "synthetic-page"
    owner.notion_preflight_completed_at = datetime.now(UTC)
    item = found("concurrent-resume")
    item.status = RecordingStatus.UPLOADED_TO_SYNOLOGY
    item.candidate_name = "Candidate"
    item.notion_page_id = "page"
    item.generated_filename = "recording.webm"
    item.storage_key = "recruiter/date/candidate/recording.webm"
    item.content_identity = item.disk_file_id
    item.synology_file_path = "/recording.webm"
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    entered = asyncio.Event()
    release = asyncio.Event()
    transfer = AsyncMock()

    async def create_share_link(_path: str) -> str:
        entered.set()
        await release.wait()
        return "https://share/video"

    transfer.create_share_link.side_effect = create_share_link
    args = (
        recording_id,
        owner,
        factory,
        AsyncMock(),
        AsyncMock(),
        transfer,
        StatusService(),
        AsyncMock(),
        settings,
    )
    first = asyncio.create_task(_resume_transfer_recording(*args))
    await entered.wait()
    second = asyncio.create_task(_resume_transfer_recording(*args))
    await asyncio.sleep(0.05)
    release.set()
    first_owned, second_owned = await asyncio.gather(first, second)
    third_owned = await _resume_transfer_recording(*args)
    await engine.dispose()

    assert transfer.create_share_link.await_count == 1
    assert first_owned is True
    assert second_owned is False
    assert third_owned is False


@pytest.mark.anyio
async def test_concurrent_found_resume_has_single_claim() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    item = found("concurrent-found")
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    entered = asyncio.Event()
    release = asyncio.Event()
    calendar = AsyncMock()

    async def find_events(*_args: object) -> list[object]:
        entered.set()
        await release.wait()
        return []

    calendar.find_events.side_effect = find_events
    matcher = InterviewMatcher(Settings(recording_filename_timezone="UTC"))
    first = asyncio.create_task(_resume_found_recording(recording_id, factory, calendar, matcher))
    await entered.wait()
    second_result = await _resume_found_recording(recording_id, factory, calendar, matcher)
    release.set()
    first_result = await first
    await engine.dispose()

    assert first_result is not None
    assert second_result is None
    assert calendar.find_events.await_count == 1


@pytest.mark.anyio
async def test_concurrent_terminal_notification_has_single_claim() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "mm-user"
    item = found("concurrent-terminal")
    item.status = RecordingStatus.COMPLETED
    async with factory() as session:
        session.add(item)
        await session.commit()
    entered = asyncio.Event()
    release = asyncio.Event()
    mattermost = AsyncMock()
    durable_claim_seen = False

    async def send_dm(_user_id: str, _message: str, **_kwargs: object) -> object:
        nonlocal durable_claim_seen
        async with factory() as check_session:
            claimed = await check_session.get(Recording, item.id)
            durable_claim_seen = (
                claimed is not None and claimed.terminal_notification_claim is not None
            )
        entered.set()
        await release.wait()
        return object()

    mattermost.send_dm.side_effect = send_dm
    service = ReviewService(mattermost, Settings(openclaw_secret="test-secret"))
    first = asyncio.create_task(_send_recruiter_notifications(owner, factory, service))
    await entered.wait()
    second = asyncio.create_task(_send_recruiter_notifications(owner, factory, service))
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(first, second)
    await engine.dispose()

    assert mattermost.send_dm.await_count == 1
    assert durable_claim_seen is True


@pytest.mark.anyio
async def test_concurrent_review_notification_has_single_claim() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "mm-user"
    item = found("concurrent-review")
    item.status = RecordingStatus.MANUAL_REVIEW_REQUIRED
    item.manual_review_reason = "multiple_candidates"
    item.manual_review_candidates = [
        {
            "name": "Candidate",
            "project_or_spot": "Backend Spot",
            "spot_url": "https://notion.example/spot",
            "general_interview_date": "2026-07-16",
            "candidate_emails": ["candidate@example.com"],
            "url": "https://notion.example/card",
        }
    ]
    async with factory() as session:
        session.add(item)
        await session.commit()
    entered = asyncio.Event()
    release = asyncio.Event()
    mattermost = AsyncMock()
    post = MagicMock(post_id="post", channel_id="channel", thread_id="thread")
    durable_claim_seen = False

    async def send_dm(_user_id: str, _message: str, **_kwargs: object) -> object:
        nonlocal durable_claim_seen
        assert "📍 Spots: Backend Spot" in _message
        assert "Spot: https://notion.example/spot" in _message
        assert "Date: 2026-07-16" in _message
        assert "Contacts: candidate@example.com" in _message
        assert "https://notion.example/card" in _message
        async with factory() as check_session:
            claimed = await check_session.get(Recording, item.id)
            durable_claim_seen = (
                claimed is not None and claimed.review_notification_claim is not None
            )
        entered.set()
        await release.wait()
        return post

    mattermost.send_dm.side_effect = send_dm
    service = ReviewService(mattermost, Settings(openclaw_secret="test-secret"))
    first = asyncio.create_task(_send_recruiter_notifications(owner, factory, service))
    await entered.wait()
    second = asyncio.create_task(_send_recruiter_notifications(owner, factory, service))
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(first, second)
    await engine.dispose()

    assert mattermost.send_dm.await_count == 1
    assert durable_claim_seen is True


@pytest.mark.anyio
async def test_stale_terminal_notification_reclaims_with_same_pending_post_id() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "mm-user"
    item = found("stale-terminal")
    item.status = RecordingStatus.COMPLETED
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    mattermost = AsyncMock()
    mattermost.send_dm.side_effect = [
        MattermostError("timeout after acceptance"),
        MattermostPost(channel_id="dm", post_id="post", thread_id="post"),
    ]
    service = ReviewService(mattermost, Settings(intent_claim_ttl_seconds=60))
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
        assert loaded is not None
        with pytest.raises(MattermostError, match="timeout after acceptance"):
            await service.deliver_terminal(session, loaded, owner)
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
        assert loaded is not None
        loaded.terminal_notification_claimed_at = datetime.now(UTC) - timedelta(seconds=61)
        await session.commit()
        delivered = await service.deliver_terminal(session, loaded, owner)
    await engine.dispose()

    assert delivered is True
    assert mattermost.send_dm.await_count == 2
    assert (
        mattermost.send_dm.await_args_list[0].kwargs["pending_post_id"]
        == mattermost.send_dm.await_args_list[1].kwargs["pending_post_id"]
    )


@pytest.mark.anyio
async def test_stale_review_notification_reclaims_same_token_and_pending_post_id() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "mm-user"
    item = found("stale-review")
    item.status = RecordingStatus.MANUAL_REVIEW_REQUIRED
    item.manual_review_reason = "multiple_candidates"
    item.manual_review_candidates = [{"name": "Candidate"}]
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    mattermost = AsyncMock()
    mattermost.send_dm.side_effect = [
        MattermostError("timeout after acceptance"),
        MattermostPost(channel_id="dm", post_id="post", thread_id="post"),
    ]
    settings = Settings(openclaw_secret="test-secret", intent_claim_ttl_seconds=60)
    service = ReviewService(mattermost, settings)
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
        assert loaded is not None
        with pytest.raises(MattermostError, match="timeout after acceptance"):
            await service.issue_review(session, loaded, owner)
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
        review = await session.scalar(
            select(ManualReview).where(ManualReview.recording_id == recording_id)
        )
        assert loaded is not None
        assert review is not None
        loaded.review_notification_claimed_at = datetime.now(UTC) - timedelta(seconds=61)
        await session.commit()
        await service.issue_review(session, loaded, owner)
    await engine.dispose()

    assert mattermost.send_dm.await_count == 2
    assert (
        mattermost.send_dm.await_args_list[0].args[1]
        == mattermost.send_dm.await_args_list[1].args[1]
    )
    assert (
        mattermost.send_dm.await_args_list[0].kwargs["pending_post_id"]
        == mattermost.send_dm.await_args_list[1].kwargs["pending_post_id"]
    )


@pytest.mark.anyio
async def test_scan_selects_every_committed_restart_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    statuses = [
        RecordingStatus.TRANSFER_STARTED,
        RecordingStatus.UPLOADED_TO_SYNOLOGY,
        RecordingStatus.SYNOLOGY_LINK_CREATED,
        RecordingStatus.NOTION_UPDATED,
    ]
    items = [found(f"scan-restart-{status.value}") for status in statuses]
    for item, item_status in zip(items, statuses, strict=True):
        item.status = item_status
    async with factory() as session:
        session.add_all(items)
        await session.commit()
        expected_ids = {item.id for item in items}
    resumed: list[uuid.UUID] = []

    async def capture(recording_id: uuid.UUID, *_args: object, **_kwargs: object) -> None:
        resumed.append(recording_id)

    monkeypatch.setattr("app.scheduler.cron._resume_transfer_recording", capture)
    disk = AsyncMock()
    disk.list_new.return_value = []
    await scan_recruiter(
        owner,
        factory,
        disk,
        AsyncMock(),
        InterviewMatcher(Settings()),
        Settings(),
        candidate_service=AsyncMock(),
        transfer_service=AsyncMock(),
        status_service=StatusService(),
        notion=AsyncMock(),
    )
    await engine.dispose()

    assert set(resumed) == expected_ids


@pytest.mark.anyio
async def test_restart_storage_collision_routes_to_manual_review() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = found("restart-collision")
    item.status = RecordingStatus.TRANSFER_STARTED
    item.candidate_name = "Ivan Ivanov"
    item.notion_page_id = "page"
    item.generated_filename = "recording.webm"
    item.storage_key = "recruiter/date/candidate/recording.webm"
    item.content_identity = "md5"
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    transfer = AsyncMock()
    transfer.transfer.side_effect = TransferError(
        "upload", StorageCollisionError("Storage key already exists")
    )

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        AsyncMock(),
        AsyncMock(),
        transfer,
        StatusService(),
        AsyncMock(),
        Settings(),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.MANUAL_REVIEW_REQUIRED
    assert loaded.manual_review_reason == "storage_key_collision"


@pytest.mark.anyio
async def test_scan_resumes_calendar_match_and_routes_missing_candidate_to_review() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = found("candidate-missing")
    item.status = RecordingStatus.CALENDAR_EVENT_FOUND
    item.calendar_event_summary = "Interview (Ivan Ivanov)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    disk = AsyncMock()
    disk.list_new.return_value = []
    candidate = AsyncMock()
    candidate.find_and_match.return_value = CandidateMatchResult(
        reason="no_candidate_found", candidates=[]
    )
    transfer = AsyncMock()

    await scan_recruiter(
        owner,
        factory,
        disk,
        AsyncMock(),
        InterviewMatcher(Settings()),
        Settings(),
        candidate_service=candidate,
        transfer_service=transfer,
        status_service=StatusService(),
        notion=AsyncMock(),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.MANUAL_REVIEW_REQUIRED
    assert loaded.manual_review_reason == "no_candidate_found"
    assert loaded.manual_review_candidates == []
    candidate.find_and_match.assert_awaited_once()
    transfer.transfer.assert_not_awaited()


@pytest.mark.anyio
async def test_scan_enqueues_manual_review_question_for_daily_digest() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "recruiter"
    owner.mattermost_dm_channel = "dm"
    item = found("digest-review")
    item.status = RecordingStatus.MANUAL_REVIEW_REQUIRED
    item.manual_review_reason = "multiple_candidates"
    async with factory() as session:
        session.add(item)
        await session.commit()
    disk = AsyncMock()
    disk.list_new.return_value = []
    reviews = AsyncMock()

    await scan_recruiter(
        owner,
        factory,
        disk,
        AsyncMock(),
        InterviewMatcher(Settings()),
        Settings(mattermost_delivery_enabled=True),
        review_service=reviews,
    )
    await engine.dispose()

    reviews.enqueue_review.assert_awaited_once()


@pytest.mark.anyio
async def test_test_mode_scan_skips_dm_review_enqueue_when_delivery_disabled() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "codex-user"
    owner.active = True
    item = found("review-without-dm")
    item.status = RecordingStatus.MANUAL_REVIEW_REQUIRED
    async with factory() as session:
        session.add(item)
        await session.commit()
    disk = AsyncMock()
    disk.list_new.return_value = []
    reviews = AsyncMock()
    reviews.enqueue_review.side_effect = ReviewRejectedError(
        "Recruiter has no exact Mattermost DM mapping"
    )

    summary = await scan_recruiter(
        owner,
        factory,
        disk,
        AsyncMock(),
        InterviewMatcher(Settings()),
        Settings(
            test_mode_enabled=True,
            mattermost_delivery_enabled=False,
            test_recruiter_allowlist={owner.email},
            test_notion_database_allowlist={owner.notion_database_id},
            test_mattermost_user_allowlist={"codex-user"},
            minio_test_prefix=owner.synology_base_folder,
        ),
        review_service=reviews,
    )
    await engine.dispose()

    assert summary.failed == 0
    assert summary.errors == []
    reviews.enqueue_review.assert_not_awaited()


@pytest.mark.anyio
async def test_offline_manual_scan_creates_exact_bound_question_without_mattermost() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "trusted-user"
    recording = found("offline-review")
    recording.status = RecordingStatus.MANUAL_REVIEW_REQUIRED
    recording.manual_review_reason = "multiple_candidates"
    async with factory() as session:
        session.add_all([owner, recording])
        await session.commit()
    mattermost = AsyncMock()
    settings = Settings(
        openclaw_secret="secret",
        test_mode_enabled=True,
        mattermost_delivery_enabled=False,
        test_recruiter_allowlist={owner.email},
        test_notion_database_allowlist={owner.notion_database_id},
        test_mattermost_user_allowlist={"trusted-user"},
        minio_test_prefix=owner.synology_base_folder,
    )
    reviews = ReviewService(mattermost, settings)
    calendar = AsyncMock()
    disk = AsyncMock()
    disk.list_new.return_value = []

    await scan_recruiter(
        owner,
        factory,
        disk,
        calendar,
        InterviewMatcher(settings),
        settings,
        review_service=reviews,
        interaction_binding=InteractionBinding("trusted-user", "trusted-dm"),
    )
    async with factory() as session:
        question = await session.scalar(select(ManualReview))
        persisted_owner = await session.get(RecruiterConfig, owner.id)
    await engine.dispose()

    assert question is not None
    assert question.recruiter_user_id == "trusted-user"
    assert question.mattermost_channel_id == "trusted-dm"
    assert persisted_owner is not None
    assert persisted_owner.mattermost_dm_channel is None
    mattermost.validate_direct_channel.assert_not_awaited()
    mattermost.send_dm.assert_not_awaited()


@pytest.mark.anyio
async def test_concurrent_offline_channels_bind_once_and_reject_before_second_scan_effects(
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    owner.mattermost_user_id = "trusted-user"
    recording = found("concurrent-offline-review")
    recording.status = RecordingStatus.MANUAL_REVIEW_REQUIRED
    recording.manual_review_reason = "multiple_candidates"
    async with factory() as session:
        session.add_all([owner, recording])
        await session.commit()
    mattermost = AsyncMock()
    settings = Settings(
        openclaw_secret="secret",
        test_mode_enabled=True,
        mattermost_delivery_enabled=False,
        test_recruiter_allowlist={owner.email},
        test_notion_database_allowlist={owner.notion_database_id},
        test_mattermost_user_allowlist={"trusted-user"},
        minio_test_prefix=owner.synology_base_folder,
    )
    reviews = ReviewService(mattermost, settings)
    calendar = AsyncMock()
    disk = AsyncMock()
    disk.list_new.return_value = []

    results = await asyncio.gather(
        scan_recruiter(
            owner,
            factory,
            disk,
            calendar,
            InterviewMatcher(settings),
            settings,
            review_service=reviews,
            interaction_binding=InteractionBinding("trusted-user", "dm-a"),
        ),
        scan_recruiter(
            owner,
            factory,
            disk,
            calendar,
            InterviewMatcher(settings),
            settings,
            review_service=reviews,
            interaction_binding=InteractionBinding("trusted-user", "dm-b"),
        ),
        return_exceptions=True,
    )
    async with factory() as session:
        questions = list((await session.scalars(select(ManualReview))).all())
    await engine.dispose()

    assert len([item for item in results if isinstance(item, ScanSummary)]) == 1
    assert len([item for item in results if isinstance(item, InteractionBindingConflict)]) == 1
    assert len(questions) == 1
    assert questions[0].mattermost_channel_id in {"dm-a", "dm-b"}
    assert calendar.refresh_snapshot.await_count == 1
    assert disk.list_new.await_count == 1
    mattermost.validate_direct_channel.assert_not_awaited()


@pytest.mark.anyio
async def test_transfer_failure_persists_failed_step() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = found("transfer-failed")
    item.status = RecordingStatus.CALENDAR_EVENT_FOUND
    item.calendar_event_summary = "Interview (Calendar Name)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    candidate = AsyncMock()
    candidate.find_and_match.return_value = CandidateMatchResult(
        page=NotionPage("page", "https://notion/page", "Notion Name", "2026-07-16")
    )
    transfer = AsyncMock()
    transfer.transfer.side_effect = TransferError("upload", RuntimeError("storage down"))

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        AsyncMock(),
        candidate,
        transfer,
        StatusService(),
        AsyncMock(),
        Settings(),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.FAILED
    assert loaded.error_step == "upload"
    assert loaded.error_message == "storage down"
    assert loaded.candidate_name == "Calendar Name"
    assert loaded.synology_file_path is None


@pytest.mark.anyio
async def test_share_failure_keeps_committed_upload_paths() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = found("share-failed")
    item.status = RecordingStatus.CALENDAR_EVENT_FOUND
    item.calendar_event_summary = "Interview (Calendar Name)"
    item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
    async with factory() as session:
        session.add(item)
        await session.commit()
        recording_id = item.id
    candidate = AsyncMock()
    candidate.find_and_match.return_value = CandidateMatchResult(
        page=NotionPage("page", "https://notion/page", "Notion Name", "2026-07-16")
    )
    transfer = AsyncMock()
    transfer.transfer.return_value = TransferResult("/folder", "/folder/video.webm")
    transfer.create_share_link.side_effect = TransferError(
        "share_link", RuntimeError("share unavailable")
    )

    await _resume_transfer_recording(
        recording_id,
        owner,
        factory,
        AsyncMock(),
        candidate,
        transfer,
        StatusService(),
        AsyncMock(),
        Settings(),
    )
    async with factory() as session:
        loaded = await session.get(Recording, recording_id)
    await engine.dispose()

    assert loaded is not None
    assert loaded.status == RecordingStatus.FAILED
    assert loaded.error_step == "share_link"
    assert loaded.synology_folder_path == "/folder"
    assert loaded.synology_file_path == "/folder/video.webm"


@pytest.mark.anyio
async def test_transfer_failure_is_isolated_between_recruiters() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owners = [
        RecruiterConfig(
            email="first@example.com", notion_database_id="one", synology_base_folder="/one"
        ),
        RecruiterConfig(
            email="second@example.com", notion_database_id="two", synology_base_folder="/two"
        ),
    ]
    settings = Settings(notion_writes_enabled=True, yandex_source_mutation_enabled=True)
    for owner in owners:
        owner.notion_preflight_token_hash = notion_token_hash(settings)
        owner.notion_preflight_database_id = owner.notion_database_id
        owner.notion_preflight_schema_hash = notion_schema_hash(settings)
        owner.notion_preflight_synthetic_page_id = "synthetic-page"
        owner.notion_preflight_completed_at = datetime.now(UTC)
    items: list[Recording] = []
    for index, owner in enumerate(owners):
        item = found(f"isolation-{index}")
        item.disk_owner_email = owner.email
        item.status = RecordingStatus.CALENDAR_EVENT_FOUND
        item.calendar_event_summary = f"Interview (Candidate {index})"
        item.calendar_dtstart = datetime(2026, 7, 16, 10, tzinfo=UTC)
        items.append(item)
    async with factory() as session:
        session.add_all([*owners, *items])
        await session.commit()
    disk = AsyncMock()
    disk.list_new.return_value = []
    candidate = AsyncMock()
    candidate.find_and_match.return_value = CandidateMatchResult(
        page=NotionPage("page", "https://notion/page", "Notion Name", "2026-07-16")
    )
    transfer = AsyncMock()

    async def transfer_effect(
        _recording: Recording, owner: RecruiterConfig, *_args: object
    ) -> TransferResult:
        if owner.email == "first@example.com":
            raise TransferError("upload", RuntimeError("first storage failed"))
        return TransferResult("/two/folder", "/two/folder/video.webm")

    transfer.transfer.side_effect = transfer_effect
    transfer.create_share_link.return_value = "https://share/video"

    await scan_all_recruiters(
        factory,
        disk,
        AsyncMock(),
        InterviewMatcher(settings),
        settings,
        candidate,
        transfer,
        StatusService(),
        AsyncMock(),
    )
    async with factory() as session:
        statuses = {
            row.disk_owner_email: row.status
            for row in (await session.scalars(select(Recording))).all()
        }
    await engine.dispose()

    assert statuses == {
        "first@example.com": RecordingStatus.FAILED,
        "second@example.com": RecordingStatus.SOURCE_MARKED_PROCESSED,
    }
