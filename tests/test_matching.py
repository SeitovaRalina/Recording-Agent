import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.matching import (
    InterviewMatcher,
    ManualReviewReason,
    normalize_title,
    parse_recording_filename,
)
from app.tools.calendar import ParsedVEVENT


def event(
    *,
    start: datetime,
    summary: str,
    description: str = "https://calink.ru/recruiter/interview/123?code=abc",
    eligible: bool = True,
    calendar_id: uuid.UUID | None = None,
    uid: str = "event-1",
    recurrence_id: str | None = None,
) -> ParsedVEVENT:
    return ParsedVEVENT(
        uid=uid,
        summary=summary,
        dtstart_utc=start,
        dtend_utc=start + timedelta(hours=1),
        description=description,
        organizer_email="recruiter@example.com",
        attendees=[],
        raw_ics="SECRET RAW ICS",
        calendar_id=calendar_id,
        calendar_url="https://caldav.test/calendar/",
        calendar_display_name="Interviews",
        eligible=eligible,
        recurrence_id=recurrence_id,
    )


def recording(title: str, start: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        disk_filename=f"{start:%Y-%m-%d_%H%M%S}_{title}.webm",
        disk_created_at=start,
    )


def test_filename_parser_video_audio_timezone_and_underscores() -> None:
    video = parse_recording_filename("2026-07-15_085411_Тест_A.webm", "Asia/Omsk")
    audio = parse_recording_filename("2026-07-15_085411_Тест_A_audio_only.webm", "Asia/Omsk")

    assert video.start_utc == datetime(2026, 7, 15, 2, 54, 11, tzinfo=UTC)
    assert video.title == "Тест_A"
    assert video.audio_only is False
    assert audio.title == "Тест_A"
    assert audio.audio_only is True


@pytest.mark.parametrize(
    "filename",
    [
        "renamed.webm",
        "2026-07-15_0854_Title.webm",
        "2026-07-15_085411_Title.mp4",
        "2026-07-15_085411__audio_only.webm",
        "copy_2026-07-15_085411_Title.webm",
    ],
)
def test_filename_parser_rejects_unsupported_shapes(filename: str) -> None:
    with pytest.raises(ValueError):
        parse_recording_filename(filename, "UTC")


def test_title_normalization_is_only_nfkc_casefold_and_whitespace() -> None:
    assert normalize_title("  Ａbc\t Иван  ") == "abc иван"
    assert normalize_title("Meeting-title") != normalize_title("Meeting title")
    assert normalize_title("Иван") != normalize_title("Ivan")


def test_unique_exact_title_time_and_calink_auto_match() -> None:
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    title = "Встреча на 30 минут (Дмитрий Aqa)"
    result = InterviewMatcher(Settings(recording_filename_timezone="UTC")).score(
        recording(title, start), [event(start=start, summary=title)]
    )

    assert result.confidence == 0.90
    assert result.manual_review_required is False


def test_reported_non_recruiting_title_cannot_match_other_event() -> None:
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    result = InterviewMatcher(Settings(recording_filename_timezone="UTC")).score(
        recording("Не рекрутинг встреча", start),
        [event(start=start, summary="Встреча на 30 минут (Иван Иванов)")],
    )

    assert result.reason == ManualReviewReason.NO_COMPATIBLE_EVENT
    assert result.best_event is None


def test_unmonitored_only_and_cross_calendar_collision_fail_closed() -> None:
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    title = "Meeting (Ivan Ivanov)"
    matcher = InterviewMatcher(Settings(recording_filename_timezone="UTC"))
    monitored = event(start=start, summary=title, calendar_id=uuid.uuid4())
    unmonitored = event(
        start=start,
        summary=title,
        eligible=False,
        calendar_id=uuid.uuid4(),
        uid="event-2",
    )

    assert matcher.score(recording(title, start), [unmonitored]).reason == (
        ManualReviewReason.UNMONITORED_ONLY
    )
    assert matcher.score(recording(title, start), [monitored, unmonitored]).reason == (
        ManualReviewReason.UNMONITORED_COLLISION
    )


def test_duplicate_occurrence_deduplicates_but_distinct_recurrence_is_ambiguous() -> None:
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    title = "Meeting (Ivan Ivanov)"
    calendar_id = uuid.uuid4()
    first = event(start=start, summary=title, calendar_id=calendar_id)
    duplicate = event(start=start, summary=title, calendar_id=calendar_id)
    other_occurrence = event(
        start=start,
        summary=title,
        calendar_id=calendar_id,
        recurrence_id="20260715T085411Z",
    )
    matcher = InterviewMatcher(Settings(recording_filename_timezone="UTC"))

    assert matcher.score(recording(title, start), [first, duplicate]).best_event is first
    assert matcher.score(recording(title, start), [first, other_occurrence]).reason == (
        ManualReviewReason.MULTIPLE_ELIGIBLE
    )


def test_timestamp_inconsistency_and_low_confidence_fail_closed() -> None:
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    title = "Team sync"
    inconsistent = recording(title, start)
    inconsistent.disk_created_at = start + timedelta(days=1)
    matcher = InterviewMatcher(Settings(recording_filename_timezone="UTC"))

    assert matcher.score(inconsistent, [event(start=start, summary=title)]).reason == (
        ManualReviewReason.FILENAME_TIMESTAMP_INCONSISTENT
    )
    assert (
        matcher.score(
            recording(title, start),
            [event(start=start, summary=title, description="")],
        ).reason
        == ManualReviewReason.LOW_CONFIDENCE
    )


def test_manual_review_candidate_payload_is_field_and_total_bounded() -> None:
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    title = "X" * 500
    events = [
        event(
            start=start,
            summary=title,
            calendar_id=uuid.uuid4(),
            uid=f"event-{index}-" + "u" * 500,
        )
        for index in range(20)
    ]
    events = [replace(item, calendar_display_name="Calendar " + "d" * 500) for item in events]

    result = InterviewMatcher(Settings(recording_filename_timezone="UTC")).score(
        recording(title, start), events
    )
    payload = [candidate.as_dict() for candidate in result.candidates]

    assert result.reason == ManualReviewReason.MULTIPLE_ELIGIBLE
    assert len(payload) <= 5
    assert len(json.dumps(payload, ensure_ascii=False)) <= 4096
    assert all(len(str(item["calendar_display_name"])) <= 100 for item in payload)
    assert all(len(str(item["event_uid"])) <= 160 for item in payload)
    assert all(len(str(item["event_summary"])) <= 160 for item in payload)


def test_telemost_filename_timezone_is_independent_from_recruiter_local_timezone() -> None:
    settings = Settings(
        scan_local_timezone="Asia/Omsk",
        recording_filename_timezone="Europe/Moscow",
    )
    item = SimpleNamespace(
        disk_filename=("2026-07-16_061826_Встреча на 30 минут (Максим Соболев).webm"),
        disk_created_at=datetime(2026, 7, 16, 3, 25, 38, tzinfo=UTC),
    )
    calendar_event = event(
        start=datetime(2026, 7, 16, 3, 0, tzinfo=UTC),
        summary="Встреча на 30 минут (Максим Соболев)",
    )

    result = InterviewMatcher(settings).score(item, [calendar_event])

    assert result.manual_review_required is False
    assert result.best_event is calendar_event
    assert "time_overlap" in result.signals
