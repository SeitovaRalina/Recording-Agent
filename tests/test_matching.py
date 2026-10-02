import json
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.matching import (
    DEFAULT_MATCHING_SIGNALS,
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
    # No booking marker in the description: pure time-window overlap with a mismatched
    # title must NOT be enough to enter the pool (the safety hole the booking-marker
    # path must not reopen). `description=""` makes explicit what the default fixture
    # value would otherwise obscure (it defaults to a calink.ru URL for convenience in
    # other tests).
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    result = InterviewMatcher(Settings(recording_filename_timezone="UTC")).score(
        recording("Не рекрутинг встреча", start),
        [event(start=start, summary="Встреча на 30 минут (Иван Иванов)", description="")],
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


def test_calink_booking_marker_pool_entry_matches_despite_mismatched_title() -> None:
    """Real case: Четова Дарья, 2026-09-21. The calink-generated event summary and the
    independently-generated Telemost recording filename never coincide by construction
    (neither the generic default Telemost title nor the manually-renamed one equals the
    event summary) — the booking-marker path (calink.ru in the description) lets the
    event enter the pool anyway, bypassing the title check.
    """
    start = datetime(2026, 9, 21, 14, 44, 43, tzinfo=UTC)
    summary = "Собеседование в Effective c Лилией Акентьевой (Четова Дарья)"
    description = (
        "Участник: Четова Дарья (dashachetova@gmail.com)\n"
        "https://telemost.360.yandex.ru/j/2973463676\n"
        "Детали встречи, отмена и перенос: "
        "https://calink.ru/liliya-akenteva/45min/45409?code=FAtvM1"
    )
    calendar_event = event(start=start, summary=summary, description=description)
    matcher = InterviewMatcher(Settings(recording_filename_timezone="UTC"))

    for filename_title in (
        "Ссылка для собеседования с Лилией Акентьевой",  # generic Telemost default name
        "Чегова Дарья DM Junior с Лилией Акентьевой",  # manually renamed
    ):
        result = matcher.score(recording(filename_title, start), [calendar_event])

        assert result.manual_review_required is False
        assert result.best_event is calendar_event
        assert result.confidence == 1.0
        assert "booking_source_marker" in result.signals


def test_consultation_exact_title_without_booking_marker_stays_low_confidence() -> None:
    """Real case: Денис Васильев technical consultation. Title matches exactly (pool
    entry via path 1) but there is no calink/calendly link and no '(Name)' suffix, so
    the score stays below threshold. This must stay LOW_CONFIDENCE, not auto-match and
    not NO_COMPATIBLE_EVENT. Signal weights are intentionally NOT widened for this case
    (no recruiter confirmation it is even a candidate interview) — out of scope.
    """
    start = datetime(2026, 9, 30, 11, 3, 10, tzinfo=UTC)
    title = "Консультация по инфраструктуре с Денисом Васильевым"
    description = "https://telemost.360.yandex.ru/j/1234567890"
    result = InterviewMatcher(Settings(recording_filename_timezone="UTC")).score(
        recording(title, start),
        [event(start=start, summary=title, description=description)],
    )

    assert result.reason == ManualReviewReason.LOW_CONFIDENCE
    assert result.manual_review_required is True
    assert round(result.confidence, 2) == 0.40


def test_bare_calink_link_title_matches_but_no_booking_marker_stays_low_confidence() -> None:
    """Real case: 'Ссылка для собеседования с Лилией Акентьевой', 2026-09-07T19:00. This
    calink link template puts no calink.ru URL or candidate identity in the
    description, so BOOKING_PATTERN never fires — but the title matches exactly (path
    1), and after the INTERVIEW_PATTERN stem fix the genitive 'собеседования' now
    matches. Still below threshold: 0.35 (time_overlap) + 0.05 (has_telemost_url) +
    0.05 (interview_keywords) = 0.45 < 0.7. Not a bug: this calink template carries no
    machine-readable candidate data at all; widening NAME_PATTERN to compensate is out
    of scope.
    """
    start = datetime(2026, 9, 7, 19, 0, 0, tzinfo=UTC)
    title = "Ссылка для собеседования с Лилией Акентьевой"
    description = "https://telemost.360.yandex.ru/j/9999999999"
    result = InterviewMatcher(Settings(recording_filename_timezone="UTC")).score(
        recording(title, start),
        [event(start=start, summary=title, description=description)],
    )

    assert result.reason == ManualReviewReason.LOW_CONFIDENCE
    assert round(result.confidence, 2) == 0.45
    assert "interview_keywords" in result.signals


def test_explicit_signals_argument_actually_changes_the_calink_outcome() -> None:
    """Proves `score()` consults the passed `signals`, not just the module defaults: the real
    calink fixture auto-matches via the booking-marker pool-entry path under
    `DEFAULT_MATCHING_SIGNALS`, but swapping in a `booking_pattern` that never matches the same
    description drops the event out of the compatible pool entirely (title still mismatches).
    """
    start = datetime(2026, 9, 21, 14, 44, 43, tzinfo=UTC)
    summary = "Собеседование в Effective c Лилией Акентьевой (Четова Дарья)"
    description = (
        "Участник: Четова Дарья (dashachetova@gmail.com)\n"
        "https://telemost.360.yandex.ru/j/2973463676\n"
        "Детали встречи, отмена и перенос: "
        "https://calink.ru/liliya-akenteva/45min/45409?code=FAtvM1"
    )
    calendar_event = event(start=start, summary=summary, description=description)
    filename_title = "Ссылка для собеседования с Лилией Акентьевой"
    matcher = InterviewMatcher(Settings(recording_filename_timezone="UTC"))

    default_result = matcher.score(recording(filename_title, start), [calendar_event])
    custom_signals = replace(
        DEFAULT_MATCHING_SIGNALS,
        booking_pattern=re.compile(r"https://never-matches\.example/"),
    )
    custom_result = matcher.score(
        recording(filename_title, start), [calendar_event], custom_signals
    )

    assert default_result.manual_review_required is False
    assert default_result.confidence == 1.0
    assert custom_result.manual_review_required is True
    assert custom_result.reason == ManualReviewReason.NO_COMPATIBLE_EVENT


def test_all_day_event_in_pool_window_does_not_cause_spurious_collision() -> None:
    """A same-day all-day block (span >= 20 hours) must never enter the compatible pool
    via either path, even when it would otherwise qualify on title — otherwise a
    recruiter's all-day OOO/placeholder entry would cause a spurious
    MULTIPLE_ELIGIBLE/UNMONITORED_COLLISION next to every real meeting that day.
    """
    start = datetime(2026, 7, 15, 8, 54, 11, tzinfo=UTC)
    title = "Meeting (Ivan Ivanov)"
    real_event = event(start=start, summary=title, calendar_id=uuid.uuid4())
    all_day = replace(
        real_event,
        uid="all-day-1",
        dtstart_utc=start.replace(hour=0, minute=0, second=0, microsecond=0),
        dtend_utc=start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=24),
    )
    matcher = InterviewMatcher(Settings(recording_filename_timezone="UTC"))

    result = matcher.score(recording(title, start), [real_event, all_day])

    assert result.manual_review_required is False
    assert result.best_event is real_event
