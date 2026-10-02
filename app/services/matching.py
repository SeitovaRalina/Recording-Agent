import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from app.config import Settings
from app.tools.calendar import ParsedVEVENT

TELEMOST_PATTERN = re.compile(r"https://telemost\.360\.yandex\.ru/")
NAME_PATTERN = re.compile(r"\(([^)]+)\)$")
INTERVIEW_PATTERN = re.compile(r"собеседован|интервью|interview|candidate", re.IGNORECASE)
BOOKING_PATTERN = re.compile(r"https://(?:calink\.ru|calendly\.com|cal\.com)/", re.IGNORECASE)
MAX_DIAGNOSTIC_CANDIDATES = 5
MAX_DIAGNOSTIC_PAYLOAD_CHARS = 4096
MAX_DIAGNOSTIC_TEXT_CHARS = 160
MAX_CALENDAR_DISPLAY_NAME_CHARS = 100
FILENAME_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{6})_(?P<body>.+)\.webm$")
# Events spanning this long or more (all-day/multi-day calendar blocks) never enter the
# compatible pool via either path below — a widened pool is more exposed to them.
MAX_EVENT_SPAN_FOR_POOL = timedelta(hours=20)


@dataclass(frozen=True)
class MatchingSignals:
    """The three regex signals `InterviewMatcher` consults; per-recruiter overridable.

    `NULL` on `recruiter_config.matching_signals` resolves to `DEFAULT_MATCHING_SIGNALS`, built
    from the module-level `NAME_PATTERN`/`INTERVIEW_PATTERN`/`BOOKING_PATTERN` constants below,
    which stay the single source of truth for global behavior. See
    `app/services/recruiter_schema.py` for the override/merge/resolve machinery.
    """

    name_pattern: re.Pattern[str]
    interview_pattern: re.Pattern[str]
    booking_pattern: re.Pattern[str]


DEFAULT_MATCHING_SIGNALS = MatchingSignals(
    name_pattern=NAME_PATTERN,
    interview_pattern=INTERVIEW_PATTERN,
    booking_pattern=BOOKING_PATTERN,
)


class RecordingLike(Protocol):
    disk_filename: str
    disk_created_at: datetime | None


class ManualReviewReason(StrEnum):
    FILENAME_INVALID = "filename_invalid"
    FILENAME_TIMESTAMP_INCONSISTENT = "filename_timestamp_inconsistent"
    CALENDAR_CONFIGURATION_INCOMPLETE = "calendar_configuration_incomplete"
    NO_COMPATIBLE_EVENT = "no_compatible_event"
    UNMONITORED_ONLY = "unmonitored_only"
    MULTIPLE_ELIGIBLE = "multiple_eligible_events"
    UNMONITORED_COLLISION = "unmonitored_collision"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True)
class ParsedRecordingFilename:
    start_utc: datetime
    title: str
    normalized_title: str
    audio_only: bool


@dataclass(frozen=True)
class MatchCandidate:
    calendar_id: str | None
    calendar_display_name: str | None
    event_uid: str
    event_summary: str
    event_start_utc: str
    eligible: bool

    @classmethod
    def from_event(cls, event: ParsedVEVENT) -> "MatchCandidate":
        return cls(
            calendar_id=str(event.calendar_id) if event.calendar_id else None,
            calendar_display_name=(event.calendar_display_name or "")[
                :MAX_CALENDAR_DISPLAY_NAME_CHARS
            ]
            or None,
            event_uid=event.uid[:MAX_DIAGNOSTIC_TEXT_CHARS],
            event_summary=event.summary[:MAX_DIAGNOSTIC_TEXT_CHARS],
            event_start_utc=event.dtstart_utc.isoformat(),
            eligible=event.eligible,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "calendar_id": self.calendar_id,
            "calendar_display_name": self.calendar_display_name,
            "event_uid": self.event_uid,
            "event_summary": self.event_summary,
            "event_start_utc": self.event_start_utc,
            "eligible": self.eligible,
        }


@dataclass(frozen=True)
class MatchResult:
    best_event: ParsedVEVENT | None
    confidence: float
    signals: list[str]
    manual_review_required: bool
    reason: ManualReviewReason | None = None
    candidates: tuple[MatchCandidate, ...] = ()


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def parse_recording_filename(filename: str, timezone_name: str) -> ParsedRecordingFilename:
    match = FILENAME_PATTERN.fullmatch(filename)
    if match is None:
        raise ValueError("Unsupported Telemost recording filename")
    body = match.group("body")
    audio_only = body.endswith("_audio_only")
    title = body.removesuffix("_audio_only") if audio_only else body
    normalized_title = normalize_title(title)
    if not normalized_title:
        raise ValueError("Recording filename contains no meeting title")
    local_start = datetime.strptime(
        f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H%M%S"
    ).replace(tzinfo=ZoneInfo(timezone_name))
    return ParsedRecordingFilename(
        start_utc=local_start.astimezone(UTC),
        title=title,
        normalized_title=normalized_title,
        audio_only=audio_only,
    )


class InterviewMatcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def parse_filename(self, filename: str) -> ParsedRecordingFilename:
        return parse_recording_filename(filename, self._settings.recording_filename_timezone)

    def _score_event(
        self, recording_start: datetime, event: ParsedVEVENT, active_signals: MatchingSignals
    ) -> tuple[float, list[str]]:
        score = 0.0
        signals: list[str] = []
        if TELEMOST_PATTERN.search(event.description):
            score += 0.05
            signals.append("has_telemost_url")
        if (
            event.dtstart_utc - timedelta(minutes=15)
            <= recording_start
            <= event.dtend_utc + timedelta(minutes=15)
        ):
            score += 0.35
            signals.append("time_overlap")
        if active_signals.name_pattern.search(event.summary):
            score += 0.25
            signals.append("name_in_summary")
        if active_signals.interview_pattern.search(event.summary):
            score += 0.05
            signals.append("interview_keywords")
        if active_signals.booking_pattern.search(event.description):
            score += 0.30
            signals.append("booking_source_marker")
        return min(round(score, 2), 1.0), signals

    def score(
        self,
        recording: RecordingLike,
        events: list[ParsedVEVENT],
        signals: MatchingSignals | None = None,
    ) -> MatchResult:
        active_signals = signals or DEFAULT_MATCHING_SIGNALS
        try:
            parsed = parse_recording_filename(
                recording.disk_filename, self._settings.recording_filename_timezone
            )
        except (ValueError, KeyError):
            return self._manual(ManualReviewReason.FILENAME_INVALID)
        if recording.disk_created_at is not None:
            disk_created_at = self._utc(recording.disk_created_at)
            if abs((disk_created_at - parsed.start_utc).total_seconds()) > 6 * 60 * 60:
                return self._manual(ManualReviewReason.FILENAME_TIMESTAMP_INCONSISTENT)

        compatible_by_key: dict[tuple[object, str, str | None], ParsedVEVENT] = {}
        for event in events:
            # All-day/multi-day blocks never enter the pool via either path.
            if event.dtend_utc - event.dtstart_utc >= MAX_EVENT_SPAN_FOR_POOL:
                continue
            if not (
                event.dtstart_utc - timedelta(minutes=15)
                <= parsed.start_utc
                <= event.dtend_utc + timedelta(minutes=15)
            ):
                continue
            # Path 1 (default): exact normalized-title match within the time window.
            title_matches = normalize_title(event.summary) == parsed.normalized_title
            # Path 2 (narrow): a booking-link marker in the description independently
            # corroborates a genuine external booking (calink/calendly/cal.com), which
            # justifies bypassing the title check for calink-generated event summaries
            # that never match the Telemost recording filename by construction.
            has_booking_marker = bool(active_signals.booking_pattern.search(event.description))
            if not title_matches and not has_booking_marker:
                continue
            key = (event.calendar_id, event.uid, event.recurrence_id)
            compatible_by_key.setdefault(key, event)
        compatible = list(compatible_by_key.values())
        candidates = self._bounded_candidates(compatible)
        eligible = [item for item in compatible if item.eligible]
        unmonitored = [item for item in compatible if not item.eligible]
        if not compatible:
            return self._manual(ManualReviewReason.NO_COMPATIBLE_EVENT)
        if not eligible:
            return self._manual(ManualReviewReason.UNMONITORED_ONLY, candidates=candidates)
        if len(eligible) > 1:
            return self._manual(ManualReviewReason.MULTIPLE_ELIGIBLE, candidates=candidates)
        if unmonitored:
            return self._manual(ManualReviewReason.UNMONITORED_COLLISION, candidates=candidates)
        event = eligible[0]
        confidence, matched_signals = self._score_event(parsed.start_utc, event, active_signals)
        if confidence < self._settings.confidence_threshold:
            return self._manual(
                ManualReviewReason.LOW_CONFIDENCE,
                confidence=confidence,
                signals=matched_signals,
                candidates=candidates,
            )
        return MatchResult(
            best_event=event,
            confidence=confidence,
            signals=matched_signals,
            manual_review_required=False,
        )

    @staticmethod
    def _bounded_candidates(events: list[ParsedVEVENT]) -> tuple[MatchCandidate, ...]:
        candidates: list[MatchCandidate] = []
        for event in events[:MAX_DIAGNOSTIC_CANDIDATES]:
            candidate = MatchCandidate.from_event(event)
            trial = [*candidates, candidate]
            payload_chars = len(json.dumps([item.as_dict() for item in trial], ensure_ascii=False))
            if payload_chars > MAX_DIAGNOSTIC_PAYLOAD_CHARS:
                break
            candidates.append(candidate)
        return tuple(candidates)

    @staticmethod
    def _manual(
        reason: ManualReviewReason,
        *,
        confidence: float = 0.0,
        signals: list[str] | None = None,
        candidates: tuple[MatchCandidate, ...] = (),
    ) -> MatchResult:
        return MatchResult(
            best_event=None,
            confidence=confidence,
            signals=signals or [],
            manual_review_required=True,
            reason=reason,
            candidates=candidates,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
