from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.scheduler.cron import register_jobs, scan_all_recruiters, scan_recruiter
from app.services.matching import InterviewMatcher
from app.tools.calendar import CalDAVAuthError


def found(file_id: str) -> Recording:
    return Recording(
        disk_file_id=file_id,
        disk_path=f"disk:/Записи Телемоста/{file_id}.webm",
        disk_filename=f"{file_id}.webm",
        disk_owner_email="recruiter@example.com",
        disk_created_at=datetime(2026, 7, 14, 10, tzinfo=UTC),
    )


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

    async def fake_scan(recruiter: RecruiterConfig, *_args: object) -> None:
        called.append(recruiter.email)
        if recruiter.email == "first@example.com":
            raise RuntimeError("first failed")

    monkeypatch.setattr("app.scheduler.cron.scan_recruiter", fake_scan)
    await scan_all_recruiters(factory, MagicMock(), MagicMock(), MagicMock())
    await engine.dispose()
    assert set(called) == {"first@example.com", "second@example.com"}


def test_registered_cleanup_has_no_permanent_delete_authority() -> None:
    get_settings.cache_clear()
    scheduler = MagicMock()
    register_jobs(scheduler, MagicMock(), MagicMock(), MagicMock(), MagicMock())

    assert scheduler.add_job.call_count == 2
    cleanup_call = scheduler.add_job.call_args_list[1]
    assert cleanup_call.kwargs["id"] == "cleanup_expired_recordings"
    assert len(cleanup_call.kwargs["args"]) == 2
    get_settings.cache_clear()
