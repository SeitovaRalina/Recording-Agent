from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording, RecordingStatus
from tools.setup.rematch_calendar_events import apply_requeue, find_false_calendar_matches


def matched(file_id: str, disk_filename: str, event_title: str | None) -> Recording:
    return Recording(
        disk_file_id=file_id,
        disk_path=f"disk:/{file_id}.webm",
        disk_filename=disk_filename,
        disk_owner_email="recruiter@example.com",
        disk_created_at=datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC),
        status=RecordingStatus.CALENDAR_EVENT_FOUND,
        calendar_event_uid=f"event-{file_id}",
        calendar_event_summary=event_title,
        calendar_raw_ics="raw",
        matched_calendar_url="https://caldav.test/calendar/",
    )


@pytest.mark.anyio
async def test_remediation_ignores_title_mismatch_and_only_finds_unparseable_filenames(
    session: AsyncSession,
) -> None:
    # A real calink match: the filename and the calink-generated event summary are
    # independently generated strings that never coincide by construction. Since
    # InterviewMatcher.score() now matches these via the booking-marker pool-entry
    # path, title mismatch here is the NORMAL shape of a correct match, not a bug.
    calink_match = matched(
        "calink",
        "2026-09-21_144443_Чегова Дарья DM Junior с Лилией Акентьевой.webm",
        "Собеседование в Effective c Лилией Акентьевой (Четова Дарья)",
    )
    # An exact-title direct match (Anton/Lilia direct-meeting style) — also not a finding.
    exact_match = matched(
        "exact",
        "2026-07-15_085411_Interview (Ivan).webm",
        " interview   (ivan) ",
    )
    # A genuinely unparseable filename slipped into CALENDAR_EVENT_FOUND — the only
    # thing this tool should still flag.
    invalid_filename = matched("invalid", "renamed.webm", "Some event")
    terminal = matched("terminal", "2026-07-15_085411_Wrong.webm", "Other")
    terminal.status = RecordingStatus.COMPLETED
    session.add_all([calink_match, exact_match, invalid_filename, terminal])
    await session.commit()

    findings = await find_false_calendar_matches(session, "UTC")

    assert [item.recording_id for item in findings] == [invalid_filename.id]
    assert findings[0].reason == "filename_invalid"
    assert invalid_filename.status == RecordingStatus.CALENDAR_EVENT_FOUND

    audit = await apply_requeue(session, findings, "operator@example.com")

    await session.refresh(calink_match)
    await session.refresh(exact_match)
    await session.refresh(invalid_filename)
    await session.refresh(terminal)
    assert calink_match.status == RecordingStatus.CALENDAR_EVENT_FOUND
    assert exact_match.status == RecordingStatus.CALENDAR_EVENT_FOUND
    assert str(invalid_filename.status) == RecordingStatus.FOUND.value
    assert invalid_filename.calendar_event_uid is None
    assert invalid_filename.calendar_raw_ics is None
    assert invalid_filename.matched_calendar_url is None
    assert terminal.status == RecordingStatus.COMPLETED
    assert audit == [
        {
            "recording_id": str(invalid_filename.id),
            "operator": "operator@example.com",
            "action": "requeued_to_found",
        }
    ]


@pytest.mark.anyio
async def test_remediation_apply_requires_operator(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Operator identity"):
        await apply_requeue(session, [], "")
