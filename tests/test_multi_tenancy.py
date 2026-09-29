"""Per-recruiter Notion map and Synology roots at the service call sites."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.storage_destination import StorageDestination
from app.services.candidate import CandidateService
from app.services.destinations import DestinationRejectedError, DestinationService
from app.services.transfer import TransferError, TransferService
from app.tools.notion import NotionClient
from app.tools.synology import SynologyFolder, SynologyPreflight
from tests.test_transfer import CapturingSynologyBackend, download_client

BASE = "https://api.notion.com/v1"
GLOBAL_ROOT = "/home/Recruiting-E/2. Interviews external"
LILIA_ROOT = "/Recruiting-NE/2. Interviews"
LILIA_MAP: dict[str, object] = {
    "project_prop": "Vacancy",
    "project_prop_type": "relation",
    "contacts_mode": "relation",
    "contacts_relation_prop": "Candidate",
    "contacts_target_prop": "Contacts",
}


def lilia(**overrides: object) -> RecruiterConfig:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "email": "lilia@example.com",
        "notion_database_id": "lilia-db",
        "synology_base_folder": "/base",
        "notion_property_map": LILIA_MAP,
        "synology_interview_roots": [LILIA_ROOT],
    }
    values.update(overrides)
    return RecruiterConfig(**values)


def interview_recording() -> Recording:
    return Recording(
        disk_file_id="file",
        disk_path="disk:/video.webm",
        disk_filename="video.webm",
        disk_owner_email="lilia@example.com",
        calendar_event_summary="Interview (Ivan)",
        calendar_dtstart=datetime(2026, 9, 30, 10, tzinfo=UTC),
    )


def _page(page_id: str, title: str, props: dict[str, object]) -> dict[str, object]:
    return {"id": page_id, "url": f"https://notion.so/{page_id}", "properties": props}


def _mock_lilia_notion(router: respx.MockRouter, *, candidate_links: list[str]) -> None:
    router.get(f"{BASE}/databases/lilia-db").mock(
        return_value=httpx.Response(200, json={"data_sources": [{"id": "lilia-src"}]})
    )
    router.get(f"{BASE}/data_sources/lilia-src").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "lilia-src",
                "properties": {
                    "Name": {"type": "title"},
                    "General Interview Date": {"type": "date"},
                    "General Interview recording": {"type": "files"},
                    "Vacancy": {"type": "relation"},
                    "Candidate": {"type": "relation"},
                },
            },
        )
    )
    interview = _page(
        "interview-1",
        "Ivan",
        {
            "Name": {"title": [{"plain_text": "Ivan Ivanov"}]},
            "General Interview Date": {"date": None},
            "General Interview recording": {"type": "files", "files": []},
            "Vacancy": {"relation": [{"id": "vacancy-1"}]},
            "Candidate": {"relation": [{"id": value} for value in candidate_links]},
        },
    )
    router.post(f"{BASE}/data_sources/lilia-src/query").mock(
        return_value=httpx.Response(200, json={"results": [interview]})
    )
    router.get(f"{BASE}/pages/vacancy-1").mock(
        return_value=httpx.Response(
            200,
            json=_page("vacancy-1", "", {"Name": {"title": [{"plain_text": "Backend Go"}]}}),
        )
    )
    router.get(f"{BASE}/pages/cand-1").mock(
        return_value=httpx.Response(
            200,
            json=_page(
                "cand-1",
                "",
                {
                    "Name": {"title": [{"plain_text": "Ivan Ivanov"}]},
                    "Contacts": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "tg @ivan, Ivan@Example.com"}],
                    },
                },
            ),
        )
    )


@pytest.mark.anyio
async def test_candidate_match_uses_lilia_map_for_project_and_relation_contacts() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_lilia_notion(router, candidate_links=["cand-1"])
        async with httpx.AsyncClient() as http:
            service = CandidateService(NotionClient(SecretStr("token"), http), Settings())
            result = await service.find_and_match(
                interview_recording(),
                lilia(),
                AsyncMock(spec=AsyncSession),
            )

    assert result.page is not None
    assert result.page.project_or_spot == "Backend Go"
    assert result.page.emails == ("ivan@example.com",)
    assert result.page.email == "ivan@example.com"


@pytest.mark.anyio
async def test_candidate_match_with_contacts_none_has_no_emails() -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_lilia_notion(router, candidate_links=["cand-1"])
        async with httpx.AsyncClient() as http:
            service = CandidateService(NotionClient(SecretStr("token"), http), Settings())
            result = await service.find_and_match(
                interview_recording(),
                lilia(notion_property_map={**LILIA_MAP, "contacts_mode": "none"}),
                AsyncMock(spec=AsyncSession),
            )
        assert not router.routes[-1].called  # candidate card never fetched

    assert result.page is not None
    assert result.page.project_or_spot == "Backend Go"
    assert result.page.emails == ()


@pytest.mark.anyio
async def test_destination_service_uses_recruiter_roots_not_global(
    session: AsyncSession,
) -> None:
    owner = lilia()
    backend = AsyncMock()
    backend.preflight.return_value = SynologyPreflight(True, True, True, True)
    backend.discover_folders.return_value = [
        SynologyFolder(f"{LILIA_ROOT}/Backend", "Backend", True, False)
    ]
    service = DestinationService(backend, Settings(synology_interview_roots=(GLOBAL_ROOT,)))
    outside = StorageDestination(
        recruiter_id=owner.id,
        canonical_path=f"{GLOBAL_ROOT}/Frontend",
        display_name="Global Frontend",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    session.add_all([owner, outside])
    await session.flush()

    rows = await service.discover(session, owner)
    candidates = await service.list_allowed_candidates(session, owner)

    assert [call.args[0] for call in backend.preflight.await_args_list] == [LILIA_ROOT]
    assert [call.args[0] for call in backend.discover_folders.await_args_list] == [LILIA_ROOT]
    assert [row.canonical_path for row in rows] == [LILIA_ROOT, f"{LILIA_ROOT}/Backend"]
    assert [row.canonical_path for row in candidates] == [LILIA_ROOT, f"{LILIA_ROOT}/Backend"]
    with pytest.raises(DestinationRejectedError, match="outside allowed interview roots"):
        await service.resolve(session, owner, outside.id)


@pytest.mark.anyio
async def test_destination_service_null_roots_fall_back_to_global(
    session: AsyncSession,
) -> None:
    owner = lilia(synology_interview_roots=None)
    backend = AsyncMock()
    backend.preflight.return_value = SynologyPreflight(True, True, True, True)
    backend.discover_folders.return_value = []
    service = DestinationService(backend, Settings(synology_interview_roots=(GLOBAL_ROOT,)))
    session.add(owner)
    await session.flush()

    await service.discover(session, owner)

    assert [call.args[0] for call in backend.discover_folders.await_args_list] == [GLOBAL_ROOT]


async def _transfer_to(session: AsyncSession, canonical_path: str) -> str:
    owner = lilia()
    item = interview_recording()
    item.generated_filename = "video.webm"
    destination = StorageDestination(
        recruiter_id=owner.id,
        canonical_path=canonical_path,
        display_name="Backend",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    session.add_all([owner, destination])
    await session.flush()
    item.storage_destination_id = destination.id
    disk = AsyncMock()
    disk._request.return_value = httpx.Response(200, json={"href": "https://download"})
    storage = CapturingSynologyBackend()
    async with download_client() as http:
        result = await TransferService(
            disk, storage, http, Settings(synology_interview_roots=(GLOBAL_ROOT,))
        ).transfer(item, owner, "Ivan", session)
    return result.folder_path


@pytest.mark.anyio
async def test_transfer_accepts_destination_under_recruiter_root(session: AsyncSession) -> None:
    assert await _transfer_to(session, f"{LILIA_ROOT}/Backend") == f"{LILIA_ROOT}/Backend"


@pytest.mark.anyio
async def test_transfer_rejects_global_root_for_recruiter_with_own_roots(
    session: AsyncSession,
) -> None:
    with pytest.raises(TransferError, match="outside allowed interview roots"):
        await _transfer_to(session, f"{GLOBAL_ROOT}/Backend")
