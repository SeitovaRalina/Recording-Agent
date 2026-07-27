import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.notion import NotionClient, NotionPage, NotionRelationChoice

MAX_CANDIDATE_CHOICES = 10


@dataclass(frozen=True)
class CandidateMatchResult:
    page: NotionPage | None = None
    reason: str | None = None
    candidates: list[dict[str, object]] | None = None
    confidence: float = 0.0
    choices: list[dict[str, object]] | None = None


class CandidateService:
    def __init__(self, notion: NotionClient, settings: Settings) -> None:
        self._notion = notion
        self._settings = settings

    async def find_and_match(
        self,
        recording: Recording,
        recruiter: RecruiterConfig,
        session: AsyncSession,
    ) -> CandidateMatchResult:
        del session
        match = re.search(r"\(([^)]+)\)$", recording.calendar_event_summary or "")
        if match is None or not match.group(1).strip():
            return CandidateMatchResult(reason="no_candidate_name_in_event", candidates=[])
        if recording.calendar_dtstart is None:
            return CandidateMatchResult(reason="no_candidate_found", candidates=[])
        if (
            recording.calendar_dtstart.tzinfo is None
            or recording.calendar_dtstart.utcoffset() is None
        ):
            raise ValueError("calendar_dtstart must be timezone-aware")
        event_date = recording.calendar_dtstart.astimezone(
            ZoneInfo(self._settings.scan_local_timezone)
        ).date()
        pages = await self._notion.search_pages(
            recruiter.notion_database_id,
            match.group(1).strip(),
            event_date,
            self._settings.notion_name_prop,
            self._settings.notion_date_prop,
            self._settings.notion_recording_prop,
            self._settings.notion_project_prop,
            self._settings.notion_project_prop_type,
            self._settings.notion_contacts_prop,
        )
        if not pages:
            return CandidateMatchResult(reason="no_candidate_found", candidates=[])
        if len(pages) == 1 and len(pages[0].spots) <= 1:
            return CandidateMatchResult(page=pages[0], confidence=1.0)
        supporting_email = (recording.candidate_email or "").strip().casefold()
        email_matches = [
            page
            for page in pages
            if supporting_email and supporting_email in {email.casefold() for email in page.emails}
        ]
        if len(email_matches) == 1:
            pages = email_matches
            if len(pages[0].spots) <= 1:
                return CandidateMatchResult(page=pages[0], confidence=1.0)
        choices = [choice for page in pages for choice in self._choices_for_page(page)]
        if len(choices) > MAX_CANDIDATE_CHOICES:
            return CandidateMatchResult(
                reason="candidate_choices_exceed_limit",
                candidates=[
                    self._candidate_summary(page) for page in pages[:MAX_CANDIDATE_CHOICES]
                ],
                choices=[],
            )
        if len(pages) == 1 and len(pages[0].spots) > 1:
            reason = "multiple_spots"
        else:
            reason = "multiple_candidates"
        return CandidateMatchResult(
            reason=reason,
            candidates=[self._candidate_summary(page) for page in pages],
            choices=choices,
        )

    @staticmethod
    def _candidate_summary(page: NotionPage) -> dict[str, object]:
        return {
            "name": page.title,
            "url": page.url,
            "general_interview_date": page.date_str or "",
            "project_or_spot": page.project_or_spot or "multiple",
            "candidate_email": page.email or "",
            "candidate_emails": list(page.emails),
        }

    @classmethod
    def _choices_for_page(cls, page: NotionPage) -> list[dict[str, object]]:
        if len(page.spots) > 1:
            return [cls._choice(page, spot) for spot in page.spots]
        spot = page.spots[0] if page.spots else None
        return [cls._choice(page, spot)]

    @staticmethod
    def _choice(page: NotionPage, spot: NotionRelationChoice | None) -> dict[str, object]:
        return {
            "id": page.id,
            "name": page.title,
            "url": page.url,
            "project_or_spot": spot.title
            if spot is not None
            else page.project_or_spot or "unspecified",
            "spot_id": spot.id if spot is not None else "",
            "spot_url": spot.url if spot is not None else "",
            "general_interview_date": page.date_str or "",
            "candidate_email": page.email or "",
            "candidate_emails": list(page.emails),
        }
