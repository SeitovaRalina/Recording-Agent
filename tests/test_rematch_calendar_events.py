from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording, RecordingStatus
from tools.setup.rematch_calendar_events import apply_requeue, find_false_calendar_matches


def matched(file_id: str, filename_title: str, event_title: str) -> Recording:
    return Recording(
        disk_file_id=file_id,
        disk_path=f"disk:/{file_id}.webm",
        disk_filename=f"2026-07-15_085411_{filename_title}.webm",
        disk_owner_email="recruiter@example.com",
        disk_created_at=datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC),
        status=RecordingStatus.CALENDAR_EVENT_FOUND,
        calendar_event_uid=f"event-{file_id}",
        calendar_event_summary=event_title,
        calendar_raw_ics="raw",
        matched_calendar_url="https://caldav.test/calendar/",
    )


@pytest.mark.anyio
async def test_remediation_dry_run_and_explicit_apply_scope(session: AsyncSession) -> None:
    bad = matched("bad", "Не рекрутинг встреча", "Interview (Ivan)")
    good = matched("good", "Interview (Ivan)", " interview   (ivan) ")
    terminal = matched("terminal", "Wrong", "Other")
    terminal.status = RecordingStatus.COMPLETED
    session.add_all([bad, good, terminal])
    await session.commit()

    findings = await find_false_calendar_matches(session, "UTC")

    assert [item.recording_id for item in findings] == [bad.id]
    assert bad.status == RecordingStatus.CALENDAR_EVENT_FOUND

    audit = await apply_requeue(session, findings, "operator@example.com")

    await session.refresh(bad)
    await session.refresh(good)
    await session.refresh(terminal)
    assert str(bad.status) == RecordingStatus.FOUND.value
    assert bad.calendar_event_uid is None
    assert bad.calendar_raw_ics is None
    assert bad.matched_calendar_url is None
    assert good.status == RecordingStatus.CALENDAR_EVENT_FOUND
    assert terminal.status == RecordingStatus.COMPLETED
    assert audit == [
        {
            "recording_id": str(bad.id),
            "operator": "operator@example.com",
            "action": "requeued_to_found",
        }
    ]


@pytest.mark.anyio
async def test_remediation_apply_requires_operator(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Operator identity"):
        await apply_requeue(session, [], "")
