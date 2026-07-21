from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
