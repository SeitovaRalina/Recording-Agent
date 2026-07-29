from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models.cleanup_preview import CleanupFileResult
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.storage_destination import StorageDestination
from app.scheduler.cron import _resume_committed_transfer_steps
from app.services.cleanup import CleanupRejectedError, CleanupService
from app.services.destinations import DestinationService
from app.services.non_interview import NonInterviewRejectedError, NonInterviewService
from app.services.status import StatusService
from app.services.transfer import TransferResult
from app.tools.synology import SynologyFolder, SynologyPreflight

TEST_INTERVIEW_ROOTS = (
    "/home/Recruiting-NE/2. Interviews",
    "/home/Recruiting-E/2. Interviews external",
    "/home/Recruiting-E/3. Interviews internal",
)


def recruiter() -> RecruiterConfig:
    return RecruiterConfig(
        id=uuid.uuid4(),
        email="mila@example.com",
        notion_database_id="notion",
        synology_base_folder="/recruiters/mila",
        mattermost_user_id="mila-user",
        mattermost_dm_channel="mila-dm",
    )


def recording(*, status: RecordingStatus = RecordingStatus.COMPLETED) -> Recording:
    return Recording(
        disk_file_id=f"disk-{uuid.uuid4()}",
        disk_path="disk:/Записи Телемоста/video.webm",
        disk_filename="video.webm",
        disk_owner_email="mila@example.com",
        status=status,
        version=4,
        synology_share_url="https://nas.test/share/opaque",
        storage_is_durable=True,
        completed_at=datetime.now(UTC),
    )


@pytest.mark.anyio
async def test_destination_discovery_persists_only_writable_real_folders() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    backend = AsyncMock()
    backend.preflight.return_value = SynologyPreflight(True, True, True, True)
    backend.discover_folders.side_effect = [
        [
            SynologyFolder(
                "/home/Recruiting-NE/2. Interviews/Backend", "Backend", True, False
            ),
            SynologyFolder(
                "/home/Recruiting-NE/2. Interviews/link", "link", True, True
            ),
        ],
        [
            SynologyFolder(
                "/home/Recruiting-E/2. Interviews external/Frontend",
                "Frontend",
                True,
                False,
            )
        ],
        [
            SynologyFolder(
                "/home/Recruiting-E/3. Interviews internal/read-only",
                "read-only",
                False,
                False,
            )
        ],
    ]
    settings = Settings(
        synology_interview_roots=TEST_INTERVIEW_ROOTS,
        synology_discovery_max_depth=2,
        synology_discovery_max_pages=4,
        synology_discovery_max_results=25,
    )
    service = DestinationService(backend, settings)
    async with factory() as session:
        session.add(owner)
        await session.commit()
        rows = await service.discover(session, owner)
    await engine.dispose()

    assert [row.display_name for row in rows] == [
        "2. Interviews",
        "Backend",
        "2. Interviews external",
        "Frontend",
        "3. Interviews internal",
    ]
    assert [call.kwargs for call in backend.discover_folders.await_args_list] == [
        {"max_depth": 2, "max_pages": 4, "max_results": 8},
        {"max_depth": 2, "max_pages": 4, "max_results": 8},
        {"max_depth": 2, "max_pages": 4, "max_results": 8},
    ]
    assert [call.args[0] for call in backend.discover_folders.await_args_list] == list(
        TEST_INTERVIEW_ROOTS
    )


@pytest.mark.anyio
async def test_interview_destination_candidates_are_bounded_allowed_inventory() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    destinations = [
        StorageDestination(
            recruiter_id=owner.id,
            canonical_path="/home/Recruiting-E/2. Interviews external/Backend",
            display_name="Backend",
            writable=True,
            symlink_safe=True,
            validated_at=datetime.now(UTC),
        ),
        StorageDestination(
            recruiter_id=owner.id,
            canonical_path="/home/Recruiting-E/2. Interviews external/Frontend",
            display_name="Frontend",
            writable=True,
            symlink_safe=True,
            validated_at=datetime.now(UTC),
        ),
    ]
    blocked = StorageDestination(
        recruiter_id=owner.id,
        canonical_path="/home/Recruiting-E/2. Interviews external/Backend Link",
        display_name="Backend Link",
        writable=True,
        symlink_safe=False,
        validated_at=datetime.now(UTC),
    )
    outside = StorageDestination(
        recruiter_id=owner.id,
        canonical_path="/home/Recruiting-E/1. Other/Backend",
        display_name="Other Backend",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    service = DestinationService(
        AsyncMock(), Settings(synology_interview_roots=TEST_INTERVIEW_ROOTS)
    )
    async with factory() as session:
        session.add(owner)
        session.add_all([*destinations, blocked, outside])
        await session.commit()
        candidates = await service.list_allowed_candidates(session, owner, limit=10)
    await engine.dispose()

    assert [row.display_name for row in candidates] == ["Backend", "Frontend"]


@pytest.mark.anyio
async def test_interview_destination_candidates_respect_limit_without_matching_text() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    destinations = [
        StorageDestination(
            recruiter_id=owner.id,
            canonical_path=f"/home/Recruiting-E/2. Interviews external/{name}",
            display_name=name,
            writable=True,
            symlink_safe=True,
            validated_at=datetime.now(UTC),
        )
        for name in ("Backend", "Frontend", "QA")
    ]
    other_recruiter_destination = StorageDestination(
        recruiter_id=owner.id,
        canonical_path="/home/Recruiting-E/3. Interviews internal/Flutter",
        display_name="Flutter",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    other_recruiter_destination.recruiter_id = uuid.uuid4()
    service = DestinationService(
        AsyncMock(), Settings(synology_interview_roots=TEST_INTERVIEW_ROOTS)
    )
    async with factory() as session:
        session.add(owner)
        session.add_all([*destinations, other_recruiter_destination])
        await session.commit()
        candidates = await service.list_allowed_candidates(session, owner, limit=2)
    await engine.dispose()

    assert [row.display_name for row in candidates] == ["Backend", "Frontend"]


@pytest.mark.anyio
async def test_cleanup_preview_revalidates_then_moves_to_trash_exactly_once() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = recording()
    disk = AsyncMock()
    settings = Settings(yandex_source_mutation_enabled=True, cleanup_preview_ttl_seconds=600)
    service = CleanupService(disk, settings)
    async with factory() as session:
        session.add_all([owner, item])
        await session.commit()
        issued = await service.preview(
            session,
            owner,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            limit=50,
        )
        result = await service.confirm(
            session,
            owner,
            preview_id=issued.preview.id,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            capability=issued.capability,
            snapshot_hash=issued.preview.snapshot_hash,
            idempotency_key="cleanup-1",
        )
        replay = await service.confirm(
            session,
            owner,
            preview_id=issued.preview.id,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            capability=issued.capability,
            snapshot_hash=issued.preview.snapshot_hash,
            idempotency_key="cleanup-1",
        )
        persisted = await session.scalar(
            select(CleanupFileResult).where(CleanupFileResult.recording_id == item.id)
        )
    await engine.dispose()

    assert result == replay
    assert result["items"] == [{"recording_id": str(item.id), "state": "moved_to_trash"}]
    assert persisted is not None and persisted.state == "moved_to_trash"
    disk.move_to_trash.assert_awaited_once_with(item.disk_path, owner.email)


@pytest.mark.anyio
async def test_cleanup_refuses_disabled_mutation_and_snapshot_drift() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = recording()
    disk = AsyncMock()
    async with factory() as session:
        session.add_all([owner, item])
        await session.commit()
        disabled = CleanupService(disk, Settings(yandex_source_mutation_enabled=False))
        issued = await disabled.preview(
            session,
            owner,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            limit=10,
        )
        with pytest.raises(CleanupRejectedError, match="disabled"):
            await disabled.confirm(
                session,
                owner,
                preview_id=issued.preview.id,
                recruiter_user_id="mila-user",
                dm_channel_id="mila-dm",
                capability=issued.capability,
                snapshot_hash=issued.preview.snapshot_hash,
                idempotency_key="cleanup-disabled",
            )
        enabled = CleanupService(disk, Settings(yandex_source_mutation_enabled=True))
        drifted = await enabled.preview(
            session,
            owner,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            limit=10,
        )
        item.version += 1
        await session.commit()
        result = await enabled.confirm(
            session,
            owner,
            preview_id=drifted.preview.id,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            capability=drifted.capability,
            snapshot_hash=drifted.preview.snapshot_hash,
            idempotency_key="cleanup-drift",
        )
    await engine.dispose()
    assert result["items"][0]["state"] == "skipped_drift"
    disk.move_to_trash.assert_not_awaited()


@pytest.mark.anyio
async def test_cleanup_failed_item_can_retry_only_from_new_preview() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = recording()
    disk = AsyncMock()
    disk.move_to_trash.side_effect = [RuntimeError("outage"), None]
    service = CleanupService(disk, Settings(yandex_source_mutation_enabled=True))
    async with factory() as session:
        session.add_all([owner, item])
        await session.commit()
        first = await service.preview(
            session,
            owner,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            limit=10,
        )
        failed = await service.confirm(
            session,
            owner,
            preview_id=first.preview.id,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            capability=first.capability,
            snapshot_hash=first.preview.snapshot_hash,
            idempotency_key="cleanup-failed",
        )
        second = await service.preview(
            session,
            owner,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            limit=10,
        )
        moved = await service.confirm(
            session,
            owner,
            preview_id=second.preview.id,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            capability=second.capability,
            snapshot_hash=second.preview.snapshot_hash,
            idempotency_key="cleanup-retry",
        )
    await engine.dispose()

    assert failed["items"][0]["state"] == "failed"
    assert moved["items"][0]["state"] == "moved_to_trash"
    assert disk.move_to_trash.await_count == 2


@pytest.mark.anyio
async def test_cleanup_restart_never_reissues_an_ambiguous_trash_move() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = recording()
    disk = AsyncMock()
    service = CleanupService(disk, Settings(yandex_source_mutation_enabled=True))
    async with factory() as session:
        session.add_all([owner, item])
        await session.commit()
        issued = await service.preview(
            session,
            owner,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            limit=10,
        )
        fingerprint = service._json_hash(
            {
                "preview_id": str(issued.preview.id),
                "recruiter_user_id": "mila-user",
                "dm_channel_id": "mila-dm",
                "capability_hash": service._hash(issued.capability),
                "snapshot_hash": issued.preview.snapshot_hash,
                "idempotency_key": "cleanup-restart",
            }
        )
        issued.preview.status = "processing"
        issued.preview.capability_consumed_at = datetime.now(UTC)
        issued.preview.confirmation_fingerprint = fingerprint
        session.add(
            CleanupFileResult(
                preview_id=issued.preview.id,
                recording_id=item.id,
                disk_file_id=item.disk_file_id,
                source_version=item.version,
                state="processing",
            )
        )
        await session.commit()

        resumed = await service.confirm(
            session,
            owner,
            preview_id=issued.preview.id,
            recruiter_user_id="mila-user",
            dm_channel_id="mila-dm",
            capability=issued.capability,
            snapshot_hash=issued.preview.snapshot_hash,
            idempotency_key="cleanup-restart",
        )
    await engine.dispose()

    assert resumed["items"][0]["state"] == "processing"
    disk.move_to_trash.assert_not_awaited()


@pytest.mark.anyio
async def test_non_interview_route_uses_opaque_destination_and_skips_notion() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = recording(status=RecordingStatus.MANUAL_REVIEW_REQUIRED)
    item.synology_share_url = None
    item.storage_is_durable = False
    destination = StorageDestination(
        recruiter_id=owner.id,
        canonical_path="/recruiters/mila/team",
        display_name="team",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    destinations = AsyncMock()
    destinations.resolve.return_value = destination
    transfer = AsyncMock()
    transfer.transfer.return_value = TransferResult(
        "/recruiters/mila/team", "/recruiters/mila/team/video.webm"
    )
    transfer.create_share_link.return_value = "https://nas.test/share/final"
    async with factory() as session:
        session.add_all([owner, destination, item])
        await session.commit()
    service = NonInterviewService(factory, destinations, transfer)
    result = await service.route(
        recording_id=item.id,
        recruiter=owner,
        destination_id=destination.id,
        expected_version=4,
    )
    await engine.dispose()

    assert result.status == RecordingStatus.COMPLETED
    assert result.route_type == "non_interview"
    assert result.notion_page_id is None
    assert result.synology_share_url == "https://nas.test/share/final"
    assert result.storage_is_durable is False


@pytest.mark.anyio
async def test_non_interview_route_refuses_another_recordings_storage_key() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = recording(status=RecordingStatus.MANUAL_REVIEW_REQUIRED)
    item.synology_share_url = None
    item.storage_is_durable = False
    existing = recording()
    existing.storage_key = "/recruiters/mila/team/video.webm"
    destination = StorageDestination(
        recruiter_id=owner.id,
        canonical_path="/recruiters/mila/team",
        display_name="team",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    destinations = AsyncMock()
    destinations.resolve.return_value = destination
    transfer = AsyncMock()
    async with factory() as session:
        session.add_all([owner, destination, item, existing])
        await session.commit()
    service = NonInterviewService(factory, destinations, transfer)

    with pytest.raises(NonInterviewRejectedError, match="owned by another recording"):
        await service.route(
            recording_id=item.id,
            recruiter=owner,
            destination_id=destination.id,
            expected_version=4,
        )
    await engine.dispose()

    transfer.transfer.assert_not_awaited()


@pytest.mark.anyio
async def test_non_interview_restart_from_share_link_never_calls_notion() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = recruiter()
    item = recording(status=RecordingStatus.SYNOLOGY_LINK_CREATED)
    item.route_type = "non_interview"
    item.generated_filename = "video.webm"
    item.storage_key = "/recruiters/mila/team/video.webm"
    item.content_identity = item.disk_file_id
    async with factory() as session:
        session.add_all([owner, item])
        await session.commit()
        notion = AsyncMock()
        await _resume_committed_transfer_steps(
            session,
            item,
            owner,
            AsyncMock(),
            AsyncMock(),
            StatusService(),
            notion,
            Settings(),
        )
    await engine.dispose()

    assert item.status == RecordingStatus.COMPLETED
    assert item.storage_is_durable is True
    notion.update_page_interview.assert_not_awaited()
