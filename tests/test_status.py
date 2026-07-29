from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording, RecordingStatus
from app.services.status import StatusService


def recording() -> Recording:
    return Recording(
        disk_file_id="file",
        disk_path="disk:/file",
        disk_filename="file.webm",
        disk_owner_email="owner@example.com",
    )


@pytest.mark.anyio
async def test_advance_sets_status_fields_and_attempt_time(session: AsyncSession) -> None:
    item = recording()
    session.add(item)
    await session.flush()
    before = datetime.now(UTC)
    await StatusService().advance(
        session,
        item,
        RecordingStatus.CALENDAR_EVENT_FOUND,
        calendar_event_summary="Interview (Ivan)",
        candidate_name="Ivan",
    )
    assert item.status == RecordingStatus.CALENDAR_EVENT_FOUND
    assert item.candidate_name == "Ivan"
    assert item.last_attempted_at is not None and item.last_attempted_at >= before


@pytest.mark.anyio
async def test_advance_rejects_invalid_transition(session: AsyncSession) -> None:
    item = recording()
    with pytest.raises(ValueError):
        await StatusService().advance(session, item, RecordingStatus.COMPLETED)
