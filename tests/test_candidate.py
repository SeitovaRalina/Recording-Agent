from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.services.candidate import CandidateService
from app.tools.notion import NotionPage, NotionRelationChoice


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
            {
                "name": "Ivan",
                "url": "url1",
                "general_interview_date": "2026-07-16",
                "project_or_spot": "unspecified",
                "candidate_email": "",
                "candidate_emails": [],
            },
            {
                "name": "Ivan",
                "url": "url2",
                "general_interview_date": "2026-07-16",
                "project_or_spot": "unspecified",
                "candidate_email": "",
                "candidate_emails": [],
            },
        ]
        assert [choice["url"] for choice in result.choices or []] == ["url1", "url2"]


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

    await CandidateService(
        notion,
        Settings(
            scan_local_timezone="Asia/Omsk",
            notion_project_prop="📍 Spots",
            notion_project_prop_type="relation",
        ),
    ).find_and_match(
        item,
        recruiter(),
        session,  # type: ignore[arg-type]
    )

    assert notion.search_pages.await_args.args[0] == "db"
    assert notion.search_pages.await_args.args[2] == date(2026, 7, 16)
    assert notion.search_pages.await_args.args[6:] == ("📍 Spots", "relation", "TBD")


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


@pytest.mark.anyio
async def test_unique_candidate_with_multiple_spots_requires_explicit_choice(
    session: object,
) -> None:
    page = NotionPage(
        "candidate",
        "https://notion/candidate",
        "Ivan",
        None,
        emails=("first@example.com", "second@example.com"),
        project_or_spot=None,
        spots=(
            NotionRelationChoice("spot-1", "Backend", "https://notion/spot-1"),
            NotionRelationChoice("spot-2", "Mobile", "https://notion/spot-2"),
        ),
    )
    notion = AsyncMock()
    notion.search_pages.return_value = [page]

    result = await CandidateService(notion, Settings()).find_and_match(
        recording("Interview (Ivan)"),
        recruiter(),
        session,  # type: ignore[arg-type]
    )

    assert result.page is None
    assert result.reason == "multiple_spots"
    assert result.choices == [
        {
            "id": "candidate",
            "name": "Ivan",
            "url": "https://notion/candidate",
            "project_or_spot": "Backend",
            "spot_id": "spot-1",
            "spot_url": "https://notion/spot-1",
            "general_interview_date": "",
            "candidate_email": "",
            "candidate_emails": ["first@example.com", "second@example.com"],
        },
        {
            "id": "candidate",
            "name": "Ivan",
            "url": "https://notion/candidate",
            "project_or_spot": "Mobile",
            "spot_id": "spot-2",
            "spot_url": "https://notion/spot-2",
            "general_interview_date": "",
            "candidate_email": "",
            "candidate_emails": ["first@example.com", "second@example.com"],
        },
    ]


@pytest.mark.anyio
async def test_multiple_formula_emails_do_not_block_unique_name_match(session: object) -> None:
    page = NotionPage(
        "1",
        "url",
        "Ivan",
        None,
        emails=("first@example.com", "second@example.com"),
    )
    notion = AsyncMock()
    notion.search_pages.return_value = [page]

    result = await CandidateService(notion, Settings()).find_and_match(
        recording("Interview (Ivan)"),
        recruiter(),
        session,  # type: ignore[arg-type]
    )

    assert result.page == page


@pytest.mark.anyio
async def test_attendee_email_is_only_a_supporting_duplicate_signal(session: object) -> None:
    item = recording("Interview (Ivan)")
    item.candidate_email = "second@example.com"
    expected = NotionPage(
        "2",
        "url2",
        "Ivan",
        None,
        emails=("second@example.com",),
    )
    notion = AsyncMock()
    notion.search_pages.return_value = [
        NotionPage("1", "url1", "Ivan", None, emails=("first@example.com",)),
        expected,
    ]

    result = await CandidateService(notion, Settings()).find_and_match(
        item,
        recruiter(),
        session,  # type: ignore[arg-type]
    )

    assert result.page == expected


@pytest.mark.anyio
async def test_attendee_email_mismatch_keeps_name_matches(session: object) -> None:
    item = recording("Interview (Ivan)")
    item.candidate_email = "unknown@example.com"
    notion = AsyncMock()
    notion.search_pages.return_value = [
        NotionPage("1", "url1", "Ivan", None, emails=("first@example.com",)),
        NotionPage("2", "url2", "Ivan", None, emails=("second@example.com",)),
    ]

    result = await CandidateService(notion, Settings()).find_and_match(
        item,
        recruiter(),
        session,  # type: ignore[arg-type]
    )

    assert result.page is None
    assert result.reason == "multiple_candidates"
    assert len(result.choices or []) == 2
