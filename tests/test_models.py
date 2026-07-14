from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording, RecordingStatus
from app.services.yandex_token_manager import YandexTokenManager


def recording(file_id: str = "file-1") -> Recording:
    return Recording(
        disk_file_id=file_id,
        disk_path=f"disk:/Записи Телемоста/{file_id}.webm",
        disk_filename=f"{file_id}.webm",
        disk_owner_email="recruiter@effective.band",
    )


@pytest.mark.anyio
async def test_recording_round_trip(session: AsyncSession) -> None:
    item = recording()
    session.add(item)
    await session.commit()

    loaded = await session.scalar(select(Recording).where(Recording.disk_file_id == "file-1"))

    assert loaded is not None
    assert loaded.status == RecordingStatus.FOUND
    assert loaded.source_processed is False


@pytest.mark.anyio
async def test_duplicate_disk_file_id_rejected(session: AsyncSession) -> None:
    session.add_all([recording(), recording()])
    with pytest.raises(IntegrityError):
        await session.commit()


def test_all_thirteen_statuses_present() -> None:
    assert len(RecordingStatus) == 13


def test_transition_guard() -> None:
    item = recording()
    item.transition_to(RecordingStatus.CALENDAR_EVENT_FOUND)
    assert item.status == RecordingStatus.CALENDAR_EVENT_FOUND

    with pytest.raises(ValueError, match="Invalid transition"):
        item.transition_to("invalid_target")


@pytest.mark.anyio
async def test_yandex_token_upsert(session: AsyncSession) -> None:
    manager = YandexTokenManager(session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    created = await manager.upsert_token(
        "recruiter@effective.band", "access-1", "refresh-1", expires_at
    )
    updated = await manager.upsert_token(
        "recruiter@effective.band", "access-2", "refresh-2", expires_at
    )

    assert created.id == updated.id
    assert updated.access_token == "access-2"
    assert await manager.is_expired("recruiter@effective.band") is False


@pytest.mark.anyio
async def test_yandex_token_missing(session: AsyncSession) -> None:
    with pytest.raises(KeyError):
        await YandexTokenManager(session).get_token("missing@effective.band")
