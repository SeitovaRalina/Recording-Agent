from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.engine import get_session
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.main import app
from app.routers.tools import QuestionItem, _scan_response
from app.scheduler.cron import ScanSummary


@pytest.mark.anyio
async def test_tools_reject_missing_auth(async_client: AsyncClient) -> None:
    response = await async_client.get(
        "/tools/recordings/status", params={"recruiter_user_id": "user"}
    )
    assert response.status_code == 401


def test_question_item_exposes_capability_required_by_answer_contract() -> None:
    assert "capability" in QuestionItem.model_fields


def test_scan_response_reports_final_per_recording_outcomes() -> None:
    review = Recording(
        id=uuid4(),
        disk_file_id="review",
        disk_path="disk:/review.webm",
        disk_filename="review.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        manual_review_reason="no_candidate_found",
    )
    completed = Recording(
        id=uuid4(),
        disk_file_id="completed",
        disk_path="disk:/completed.webm",
        disk_filename="completed.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.COMPLETED,
        candidate_name="Иван Иванов",
    )

    response = _scan_response(
        "r@example.com",
        ScanSummary(
            discovered=9,
            inserted=2,
            skipped_legacy=7,
            matched=1,
            inserted_recording_ids=[review.id, completed.id],
        ),
        [review, completed],
    )

    assert response.skipped_legacy == 7
    assert response.manual_review == 1
    assert response.without_review == 1
    assert [item.filename for item in response.items] == ["review.webm", "completed.webm"]
    assert response.items[0].requires_review is True
    assert response.items[0].is_new is True
    assert response.items[0].review_reason == "no_candidate_found"


def test_scan_response_exposes_full_totals_when_items_are_truncated() -> None:
    item = Recording(
        id=uuid4(),
        disk_file_id="review",
        disk_path="disk:/review.webm",
        disk_filename="review.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
    )

    response = _scan_response(
        "r@example.com",
        ScanSummary(recording_ids=[item.id]),
        [item],
        {
            RecordingStatus.MANUAL_REVIEW_REQUIRED: 50,
            RecordingStatus.COMPLETED: 1,
        },
    )

    assert response.processed == 51
    assert response.manual_review == 50
    assert response.without_review == 1
    assert response.items_truncated is True
    assert len(response.items) == 1


@pytest.mark.anyio
async def test_tools_authenticate_docker_bridge_peer_by_secret(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    recruiter = RecruiterConfig(
        email="bridge@example.com",
        notion_database_id="db",
        synology_base_folder="test",
        mattermost_user_id="bridge-user",
    )
    session.add(recruiter)
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setenv("OPENCLAW_SECRET", "test-secret")
    monkeypatch.setenv("TEST_MODE_ENABLED", "false")
    get_settings.cache_clear()
    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app, client=("172.21.0.1", 52236))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            rejected = await client.get(
                "/tools/recordings/status",
                params={"recruiter_user_id": "bridge-user"},
                headers={"Authorization": "Bearer wrong-secret"},
            )
            accepted = await client.get(
                "/tools/recordings/status",
                params={"recruiter_user_id": "bridge-user"},
                headers={"Authorization": "Bearer test-secret"},
            )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()

    assert rejected.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.anyio
async def test_status_query_is_recruiter_scoped(
    async_client: AsyncClient, session: AsyncSession
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="test",
        mattermost_user_id="mm-user",
    )
    session.add_all(
        [
            recruiter,
            Recording(
                disk_file_id="one",
                disk_path="disk:/one.webm",
                disk_filename="one.webm",
                disk_owner_email="r@example.com",
            ),
            Recording(
                disk_file_id="other",
                disk_path="disk:/other.webm",
                disk_filename="other.webm",
                disk_owner_email="other@example.com",
            ),
        ]
    )
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    response = await async_client.get(
        "/tools/recordings/status",
        params={"recruiter_user_id": "mm-user"},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["filename"] == "one.webm"
    assert payload["items"][0]["requires_review"] is False
    assert payload["items"][0]["review_reason"] is None


@pytest.mark.anyio
async def test_status_rejects_authoritative_recruiter_outside_test_scope(
    async_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="production-db",
        synology_base_folder="production-prefix",
        mattermost_user_id="mm-user",
        active=True,
    )
    session.add(recruiter)
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setenv("TEST_MODE_ENABLED", "true")
    monkeypatch.setenv("YANDEX_SOURCE_MUTATION_ENABLED", "false")
    monkeypatch.setenv("TEST_MATTERMOST_USER_ALLOWLIST", '["mm-user"]')
    monkeypatch.setenv("TEST_RECRUITER_ALLOWLIST", '["r@example.com"]')
    monkeypatch.setenv("TEST_NOTION_DATABASE_ALLOWLIST", '["test-db"]')
    get_settings.cache_clear()
    response = await async_client.get(
        "/tools/recordings/status",
        params={"recruiter_user_id": "mm-user"},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Notion database is outside the test-mode allowlist"
