from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.config import Settings
from app.services.matching import InterviewMatcher
from app.tools.calendar import ParsedVEVENT


def event(*, start: datetime, summary: str, description: str) -> ParsedVEVENT:
    return ParsedVEVENT(
        uid=summary,
        summary=summary,
        dtstart_utc=start,
        dtend_utc=start + timedelta(hours=1),
        description=description,
        organizer_email="recruiter@example.com",
        attendees=[],
        raw_ics="",
    )


def test_calink_time_and_candidate_name_auto_match() -> None:
    created = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    recording = SimpleNamespace(disk_created_at=created)
    item = event(
        start=created - timedelta(minutes=30),
        summary="Meeting for 30 minutes (Dmitry Aqa)",
        description="https://calink.ru/recruiter/interview/123?code=abc",
    )

    result = InterviewMatcher(Settings()).score(recording, [item])

    assert result.confidence == 0.90
    assert result.manual_review_required is False


def test_matcher_empty_and_tie_break() -> None:
    created = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    recording = SimpleNamespace(disk_created_at=created)
    matcher = InterviewMatcher(Settings())
    farther = event(start=created - timedelta(hours=1), summary="Team", description="")
    closer = event(start=created - timedelta(minutes=5), summary="Sync", description="")

    assert matcher.score(recording, []).best_event is None
    assert matcher.score(recording, [farther, closer]).best_event is closer


def test_telemost_and_time_requires_manual_review() -> None:
    created = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    recording = SimpleNamespace(disk_created_at=created)
    item = event(
        start=created - timedelta(minutes=30),
        summary="Team sync",
        description="https://telemost.360.yandex.ru/j/123",
    )

    result = InterviewMatcher(Settings()).score(recording, [item])

    assert result.confidence == 0.40
    assert result.manual_review_required is True


def test_telemost_time_and_candidate_name_requires_manual_review() -> None:
    created = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    item = event(
        start=created - timedelta(minutes=30),
        summary="Meeting (Ivan Ivanov)",
        description="https://telemost.360.yandex.ru/j/123",
    )

    result = InterviewMatcher(Settings()).score(SimpleNamespace(disk_created_at=created), [item])

    assert result.confidence == 0.65
    assert result.manual_review_required is True


def test_calink_time_and_name_match_without_telemost() -> None:
    created = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    item = event(
        start=created - timedelta(minutes=30),
        summary="Meeting (Ivan Ivanov)",
        description="https://calink.ru/recruiter/interview/123?code=abc",
    )

    result = InterviewMatcher(Settings()).score(SimpleNamespace(disk_created_at=created), [item])

    assert result.confidence == 0.90
    assert result.manual_review_required is False


def test_zero_signal_event_requires_manual_review() -> None:
    created = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    result = InterviewMatcher(Settings()).score(
        SimpleNamespace(disk_created_at=created),
        [event(start=created + timedelta(days=1), summary="Team sync", description="")],
    )

    assert result.confidence == 0.0
    assert result.signals == []
    assert result.manual_review_required is True
