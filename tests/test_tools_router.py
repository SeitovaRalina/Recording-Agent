from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.engine import get_session
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.main import app


@pytest.mark.anyio
async def test_tools_reject_missing_auth(async_client: AsyncClient) -> None:
    response = await async_client.get(
        "/tools/recordings/status", params={"recruiter_user_id": "user"}
    )
    assert response.status_code == 401


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
