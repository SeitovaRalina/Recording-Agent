import argparse
import asyncio
import json
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.engine import create_engine, create_session_factory
from app.db.models.recording import Recording, RecordingStatus
from app.services.matching import normalize_title, parse_recording_filename


@dataclass(frozen=True)
class RemediationFinding:
    recording_id: uuid.UUID
    disk_filename: str
    stored_summary: str | None
    reason: str


async def find_false_calendar_matches(
    session: AsyncSession, timezone_name: str
) -> list[RemediationFinding]:
    rows = list(
        (
            await session.scalars(
                select(Recording).where(Recording.status == RecordingStatus.CALENDAR_EVENT_FOUND)
            )
        ).all()
    )
    findings: list[RemediationFinding] = []
    for recording in rows:
        try:
            parsed = parse_recording_filename(recording.disk_filename, timezone_name)
        except ValueError:
            reason = "filename_invalid"
        else:
            if (
                recording.calendar_event_summary is not None
                and normalize_title(recording.calendar_event_summary) == parsed.normalized_title
            ):
                continue
            reason = "title_mismatch"
        findings.append(
            RemediationFinding(
                recording_id=recording.id,
                disk_filename=recording.disk_filename,
                stored_summary=recording.calendar_event_summary,
                reason=reason,
            )
        )
    return findings


async def apply_requeue(
    session: AsyncSession,
    findings: list[RemediationFinding],
    operator: str,
) -> list[dict[str, str]]:
    if not operator.strip():
        raise ValueError("Operator identity is required")
    ids = {item.recording_id for item in findings}
    if not ids:
        return []
    rows = list(
        (
            await session.scalars(
                select(Recording)
                .where(
                    Recording.id.in_(ids),
                    Recording.status == RecordingStatus.CALENDAR_EVENT_FOUND,
                )
                .with_for_update()
            )
        ).all()
    )
    audit: list[dict[str, str]] = []
    for recording in rows:
        recording.status = RecordingStatus.FOUND
        recording.calendar_event_uid = None
        recording.calendar_event_recurrence_id = None
        recording.calendar_event_summary = None
        recording.calendar_dtstart = None
        recording.calendar_dtend = None
        recording.calendar_organizer = None
        recording.calendar_telemost_url = None
        recording.calendar_raw_ics = None
        recording.matched_calendar_id = None
        recording.matched_calendar_url = None
        recording.matched_calendar_display_name = None
        recording.manual_review_reason = None
        recording.manual_review_candidates = None
        audit.append(
            {
                "recording_id": str(recording.id),
                "operator": operator,
                "action": "requeued_to_found",
            }
        )
    await session.commit()
    return audit


async def _run(apply: bool, operator: str | None) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            findings = await find_false_calendar_matches(session, settings.scan_local_timezone)
            output: object = [asdict(item) for item in findings]
            if apply:
                if operator is None:
                    raise ValueError("--operator is required with --apply")
                output = await apply_requeue(session, findings, operator)
            print(json.dumps(output, ensure_ascii=False, default=str))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Find false calendar-event matches")
    parser.add_argument("--apply", action="store_true", help="Explicitly requeue listed rows")
    parser.add_argument("--operator", help="Operator identity recorded in audit output")
    args = parser.parse_args()
    asyncio.run(_run(args.apply, args.operator))


if __name__ == "__main__":
    main()
