from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.services.candidate import CandidateService
from app.tools.notion import NotionPage


def recording(summary: str) -> Recording:
    return Recording(
        disk_file_id="file",
        disk_path="disk:/file.webm",
        disk_filename="file.webm",
        disk_owner_email="recruiter@example.com",
        calendar_event_summary=summary,
        calendar_dtstart=datetime(2026, 7, 16, tzinfo=UTC),
    )


def recruiter() -> RecruiterConfig:
    return RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="db",
        synology_base_folder="/recordings",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("summary", "pages", "reason"),
    [
        ("Interview", [], "no_candidate_name_in_event"),
        ("Interview (Ivan)", [], "no_candidate_found"),
        (
            "Interview (Ivan)",
            [
                NotionPage("1", "url1", "Ivan", "2026-07-16"),
                NotionPage("2", "url2", "Ivan", "2026-07-16"),
            ],
            "multiple_candidates",
        ),
    ],
)
async def test_candidate_manual_review_reasons(
    summary: str,
    pages: list[NotionPage],
    reason: str,
    session: object,
) -> None:
    notion = AsyncMock()
    notion.search_pages.return_value = pages
    service = CandidateService(notion, Settings())
    result = await service.find_and_match(recording(summary), recruiter(), session)  # type: ignore[arg-type]
    assert result.reason == reason
    if reason == "multiple_candidates":
        assert result.candidates == [
            {"name": "Ivan", "url": "url1"},
            {"name": "Ivan", "url": "url2"},
        ]


@pytest.mark.anyio
async def test_candidate_unique_match(session: object) -> None:
    page = NotionPage("1", "url", "Ivan", "2026-07-16")
    notion = AsyncMock()
    notion.search_pages.return_value = [page]
    result = await CandidateService(notion, Settings()).find_and_match(
        recording("Interview (Ivan)"),
        recruiter(),
        session,  # type: ignore[arg-type]
    )
    assert result.page == page
    assert result.confidence == 1.0


@pytest.mark.anyio
async def test_candidate_search_uses_configured_local_date(session: object) -> None:
    item = recording("Interview (Ivan)")
    item.calendar_dtstart = datetime(2026, 7, 15, 20, 30, tzinfo=UTC)
    notion = AsyncMock()
    notion.search_pages.return_value = []

    await CandidateService(notion, Settings(scan_local_timezone="Asia/Omsk")).find_and_match(
        item,
        recruiter(),
        session,  # type: ignore[arg-type]
    )

    assert notion.search_pages.await_args.args[0] == "db"
    assert notion.search_pages.await_args.args[2] == date(2026, 7, 16)


@pytest.mark.anyio
async def test_candidate_search_rejects_naive_calendar_time(session: object) -> None:
    item = recording("Interview (Ivan)")
    item.calendar_dtstart = datetime(2026, 7, 16, 10)
    notion = AsyncMock()

    with pytest.raises(ValueError, match="timezone-aware"):
        await CandidateService(notion, Settings()).find_and_match(
            item,
            recruiter(),
            session,  # type: ignore[arg-type]
        )
    notion.search_pages.assert_not_awaited()
