from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recruiter_calendar import RecruiterCalendar
from app.db.models.recruiter_config import RecruiterConfig
from app.main import app
from app.routers.calendars import get_session


@pytest.mark.anyio
async def test_calendar_state_requires_secret_and_is_recruiter_scoped(
    async_client: AsyncClient, session: AsyncSession
) -> None:
    recruiter = RecruiterConfig(
        email="first@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.flush()
    calendar = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/first/",
        display_name="First",
        is_default=True,
        last_seen_at=datetime.now(UTC),
    )
    session.add(calendar)
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session

    unauthorized = await async_client.get("/internal/recruiters/first@example.com/calendars")
    response = await async_client.get(
        "/internal/recruiters/first@example.com/calendars",
        headers={"X-OpenClaw-Secret": "test-secret"},
    )
    missing = await async_client.get(
        "/internal/recruiters/other@example.com/calendars",
        headers={"X-OpenClaw-Secret": "test-secret"},
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["effective_ids"] == [str(calendar.id)]
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_selection_replacement_version_clear_and_default_audit(
    async_client: AsyncClient, session: AsyncSession
) -> None:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="notion",
        synology_base_folder="/recordings",
    )
    session.add(recruiter)
    await session.flush()
    first = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/first/",
        display_name="First",
        is_default=True,
        last_seen_at=datetime.now(UTC),
    )
    second = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.test/second/",
        display_name="Second",
        last_seen_at=datetime.now(UTC),
    )
    session.add_all([first, second])
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    headers = {
        "X-OpenClaw-Secret": "test-secret",
        "X-Operator-Identity": "operator@example.com",
    }

    selected = await async_client.put(
        "/internal/recruiters/recruiter@example.com/calendars/selection",
        headers=headers,
        json={"version": 0, "calendar_ids": [str(second.id)]},
    )
    conflict = await async_client.put(
        "/internal/recruiters/recruiter@example.com/calendars/selection",
        headers=headers,
        json={"version": 0, "calendar_ids": []},
    )
    cleared = await async_client.put(
        "/internal/recruiters/recruiter@example.com/calendars/selection",
        headers=headers,
        json={"version": 1, "calendar_ids": []},
    )
    changed_default = await async_client.put(
        "/internal/recruiters/recruiter@example.com/calendars/default",
        headers=headers,
        json={"version": 2, "calendar_id": str(second.id)},
    )

    assert selected.status_code == 200
    assert selected.json()["effective_ids"] == [str(second.id)]
    assert conflict.status_code == 409
    assert cleared.json()["effective_ids"] == [str(first.id)]
    assert changed_default.json()["default_id"] == str(second.id)
    await session.refresh(recruiter)
    assert recruiter.calendar_selection_version == 3
    assert recruiter.calendar_selection_updated_by == "operator@example.com"
    assert recruiter.caldav_calendar_url == second.canonical_url
