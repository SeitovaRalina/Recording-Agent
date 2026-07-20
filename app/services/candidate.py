import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.notion import NotionClient, NotionPage


@dataclass(frozen=True)
class CandidateMatchResult:
    page: NotionPage | None = None
    reason: str | None = None
    candidates: list[dict[str, object]] | None = None
    confidence: float = 0.0


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
        )
        if not pages:
            return CandidateMatchResult(reason="no_candidate_found", candidates=[])
        if len(pages) == 1:
            return CandidateMatchResult(page=pages[0], confidence=1.0)
        return CandidateMatchResult(
            reason="multiple_candidates",
            candidates=[{"name": page.title, "url": page.url} for page in pages[:10]],
        )
