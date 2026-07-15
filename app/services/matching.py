import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.config import Settings
from app.tools.calendar import ParsedVEVENT

TELEMOST_PATTERN = re.compile(r"https://telemost\.360\.yandex\.ru/")
NAME_PATTERN = re.compile(r"\(([^)]+)\)$")
INTERVIEW_PATTERN = re.compile(r"собеседование|интервью|interview|candidate", re.IGNORECASE)
BOOKING_PATTERN = re.compile(r"https://(?:calink\.ru|calendly\.com|cal\.com)/", re.IGNORECASE)


class RecordingLike(Protocol):
    disk_created_at: datetime | None


@dataclass(frozen=True)
class MatchResult:
    best_event: ParsedVEVENT | None
    confidence: float
    signals: list[str]
    manual_review_required: bool


class InterviewMatcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _score_event(
        self, recording: RecordingLike, event: ParsedVEVENT
    ) -> tuple[float, list[str]]:
        score = 0.0
        signals: list[str] = []
        if TELEMOST_PATTERN.search(event.description):
            score += 0.05
            signals.append("has_telemost_url")
        recording_time = self._recording_time(recording)
        if recording_time is not None and event.dtstart_utc - timedelta(
            minutes=15
        ) <= recording_time <= event.dtend_utc + timedelta(minutes=15):
            score += 0.35
            signals.append("time_overlap")
        if NAME_PATTERN.search(event.summary):
            score += 0.25
            signals.append("name_in_summary")
        if INTERVIEW_PATTERN.search(event.summary):
            score += 0.05
            signals.append("interview_keywords")
        if BOOKING_PATTERN.search(event.description):
            score += 0.30
            signals.append("booking_source_marker")
        # TODO Phase 3: score attendee_email_match after Notion candidate lookup is wired.
        return min(round(score, 2), 1.0), signals

    def score(self, recording: RecordingLike, events: list[ParsedVEVENT]) -> MatchResult:
        if not events:
            return MatchResult(None, 0.0, [], manual_review_required=True)
        recording_time = self._recording_time(recording)

        def rank(event: ParsedVEVENT) -> tuple[float, float]:
            confidence, _ = self._score_event(recording, event)
            proximity = (
                abs((event.dtstart_utc - recording_time).total_seconds())
                if recording_time is not None
                else float("inf")
            )
            return confidence, -proximity

        best_event = max(events, key=rank)
        confidence, signals = self._score_event(recording, best_event)
        return MatchResult(
            best_event=best_event,
            confidence=confidence,
            signals=signals,
            manual_review_required=confidence < self._settings.confidence_threshold,
        )

    @staticmethod
    def _recording_time(recording: RecordingLike) -> datetime | None:
        value = recording.disk_created_at
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
