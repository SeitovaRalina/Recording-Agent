import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.db.models.recruiter_calendar import RecruiterCalendar
from app.services.canary import notion_schema_hash, notion_token_hash
from app.tools.notion import NotionClient, NotionDatabaseInspection, NotionDataSourceSchema
from tools.setup.configure_recruiter import (
    DatabaseInspection,
    NotionInspector,
    activate_recruiter,
    configure_recruiter,
    parse_notion_database_id,
    preflight_recruiter,
    preflight_recruiter_notion,
)


@pytest.mark.anyio
@respx.mock
async def test_notion_inspector_returns_real_title_with_single_probe() -> None:
    database_id = "fe5fe300-f311-821b-96fe-01233947e4c2"
    source_id = "0788967f-04fe-43c3-a78b-d2572e031031"
    database_route = respx.get(f"https://api.notion.com/v1/databases/{database_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": [{"plain_text": "Test Interviews"}],
                "data_sources": [{"id": source_id}],
            },
        )
    )
    schema_route = respx.get(f"https://api.notion.com/v1/data_sources/{source_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": source_id,
                "properties": {
                    "Name": {"type": "title"},
                    "General Interview Date": {"type": "date"},
                    "General Interview recording": {"type": "files"},
                    "📍 Spots": {"type": "relation"},
                },
            },
        )
    )
    settings = Settings(notion_token=SecretStr("notion-token"))

    async with httpx.AsyncClient() as client:
        inspection = await NotionInspector(
            notion=NotionClient(settings.notion_token, client, settings=settings),
            settings=settings,
        ).inspect(database_id)

    assert inspection.title == "Test Interviews"
    assert inspection.property_types["Name"] == "title"
    assert database_route.call_count == 1
    assert schema_route.call_count == 1


def test_parse_explicit_notion_target() -> None:
    assert parse_notion_database_id("fe5fe300f311821b96fe01233947e4c2") == (
        "fe5fe300-f311-821b-96fe-01233947e4c2"
    )
    assert (
        parse_notion_database_id(
            "https://app.notion.com/p/effectiveland/Test-Interviews-Page-"
            "397c8889e4c8814c8acfd7da92915220"
        )
        == "397c8889-e4c8-814c-8acf-d7da92915220"
    )
    with pytest.raises(ValueError):
        parse_notion_database_id("https://notion.so/workspace-search")


@pytest.mark.anyio
async def test_bootstrap_creates_inactive_explicit_recruiter(session: object) -> None:
    inspector = AsyncMock()
    inspector.inspect.return_value = DatabaseInspection(
        "fe5fe300-f311-821b-96fe-01233947e4c2",
        "Test Interviews",
        {"Name": "title", "📍 Spots": "relation"},
    )
    settings = Settings(
        yandex_refresh_tokens={"r@example.com": SecretStr("refresh")},
        yandex_caldav_passwords={"r@example.com": SecretStr("password")},
    )
    recruiter = await configure_recruiter(
        session,  # type: ignore[arg-type]
        inspector,
        settings,
        email="R@example.com",
        notion_target="fe5fe300f311821b96fe01233947e4c2",
        mattermost_user_id="mm-user",
        storage_prefix="test-prefix",
        confirmed=True,
    )
    assert recruiter.active is False
    assert recruiter.notion_database_id == "fe5fe300-f311-821b-96fe-01233947e4c2"
    inspector.inspect.assert_awaited_once()


@pytest.mark.anyio
async def test_bootstrap_reuses_confirmed_database_inspection(session: object) -> None:
    database_id = "fe5fe300-f311-821b-96fe-01233947e4c2"
    inspector = AsyncMock()
    inspection = DatabaseInspection(database_id, "Test Interviews", {"Name": "title"})
    settings = Settings(
        yandex_refresh_tokens={"r@example.com": SecretStr("refresh")},
        yandex_caldav_passwords={"r@example.com": SecretStr("password")},
    )

    await configure_recruiter(
        session,  # type: ignore[arg-type]
        inspector,
        settings,
        email="R@example.com",
        notion_target=database_id,
        mattermost_user_id="mm-user",
        storage_prefix="test-prefix",
        confirmed=True,
        inspection=inspection,
    )

    inspector.inspect.assert_not_awaited()


@pytest.mark.anyio
async def test_operator_preflight_persists_backend_token_and_synthetic_row_proof(
    session: object,
) -> None:
    database_id = "fe5fe300-f311-821b-96fe-01233947e4c2"
    settings = Settings(notion_token=SecretStr("backend-token"))
    recruiter = await configure_recruiter(
        session,  # type: ignore[arg-type]
        AsyncMock(),
        Settings(
            yandex_refresh_tokens={"r@example.com": SecretStr("refresh")},
            yandex_caldav_passwords={"r@example.com": SecretStr("password")},
        ),
        email="r@example.com",
        notion_target=database_id,
        mattermost_user_id="mm-user",
        storage_prefix="test-prefix",
        confirmed=True,
        inspection=DatabaseInspection(database_id, "Test Interviews", {}),
    )
    notion = AsyncMock(spec=NotionClient)
    notion.preflight_database.return_value = NotionDatabaseInspection(
        database_id, "Test Interviews", NotionDataSourceSchema("runtime-only", {})
    )

    await preflight_recruiter_notion(
        session,  # type: ignore[arg-type]
        notion,
        settings,
        recruiter_email=recruiter.email,
        synthetic_page_id="synthetic-page",
    )

    assert recruiter.notion_preflight_token_hash
    assert recruiter.notion_preflight_database_id == database_id
    assert recruiter.notion_preflight_synthetic_page_id == "synthetic-page"
    assert recruiter.notion_preflight_completed_at is not None


@pytest.mark.anyio
@pytest.mark.parametrize("mattermost_delivery_enabled", [True, False])
async def test_preflight_selects_explicit_default_and_keeps_recruiter_inactive(
    session: object, mattermost_delivery_enabled: bool
) -> None:
    database_id = "fe5fe300-f311-821b-96fe-01233947e4c2"
    settings = Settings(
        notion_token=SecretStr("backend-token"),
        yandex_refresh_tokens={"r@example.com": SecretStr("refresh")},
        yandex_caldav_passwords={"r@example.com": SecretStr("password")},
        test_mode_enabled=not mattermost_delivery_enabled,
        yandex_source_mutation_enabled=mattermost_delivery_enabled,
        mattermost_delivery_enabled=mattermost_delivery_enabled,
    )
    recruiter = await configure_recruiter(
        session,  # type: ignore[arg-type]
        AsyncMock(),
        settings,
        email="r@example.com",
        notion_target=database_id,
        mattermost_user_id="mm-user",
        storage_prefix="test-prefix",
        confirmed=True,
        inspection=DatabaseInspection(database_id, "Test Interviews", {}),
    )
    first = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.yandex.ru/first/",
        display_name="First",
        available=True,
        last_seen_at=datetime.now(UTC),
    )
    second = RecruiterCalendar(
        recruiter_id=recruiter.id,
        canonical_url="https://caldav.yandex.ru/second/",
        display_name="Second",
        available=True,
        last_seen_at=datetime.now(UTC),
    )
    session.add_all([first, second])  # type: ignore[attr-defined]
    await session.flush()  # type: ignore[attr-defined]
    calendar = AsyncMock()
    calendar.discover_calendars.return_value = [first, second]
    notion = AsyncMock(spec=NotionClient)
    notion.preflight_database.return_value = NotionDatabaseInspection(
        database_id, "Test Interviews", NotionDataSourceSchema("runtime-only", {})
    )
    yandex = AsyncMock()
    mattermost = AsyncMock()

    result = await preflight_recruiter(
        session,  # type: ignore[arg-type]
        settings,
        recruiter_email=recruiter.email,
        synthetic_page_id="synthetic-page",
        default_calendar_id=str(second.id),
        yandex_probe=yandex,
        calendar=calendar,
        notion=notion,
        mattermost=mattermost,
    )

    assert result.active is False
    assert second.is_default is True
    assert first.is_default is False
    yandex.probe.assert_awaited_once_with("r@example.com")
    if mattermost_delivery_enabled:
        mattermost.probe_user.assert_awaited_once_with("mm-user")
    else:
        mattermost.probe_user.assert_not_awaited()
        activated = await activate_recruiter(
            session,  # type: ignore[arg-type]
            settings,
            recruiter_email=recruiter.email,
            yandex_probe=yandex,
            mattermost=mattermost,
        )
        assert activated.active is True
        mattermost.probe_user.assert_not_awaited()


@pytest.mark.anyio
async def test_activation_fails_closed_then_activates_after_all_preflights(
    session: object,
) -> None:
    database_id = "fe5fe300-f311-821b-96fe-01233947e4c2"
    settings = Settings(
        notion_token=SecretStr("backend-token"),
        yandex_refresh_tokens={"r@example.com": SecretStr("refresh")},
        yandex_caldav_passwords={"r@example.com": SecretStr("password")},
    )
    recruiter = await configure_recruiter(
        session,  # type: ignore[arg-type]
        AsyncMock(),
        settings,
        email="r@example.com",
        notion_target=database_id,
        mattermost_user_id="mm-user",
        storage_prefix="test-prefix",
        confirmed=True,
        inspection=DatabaseInspection(database_id, "Test Interviews", {}),
    )
    yandex = AsyncMock()
    mattermost = AsyncMock()

    with pytest.raises(ValueError, match="Notion preflight"):
        await activate_recruiter(
            session,  # type: ignore[arg-type]
            settings,
            recruiter_email=recruiter.email,
            yandex_probe=yandex,
            mattermost=mattermost,
        )

    recruiter.notion_preflight_token_hash = notion_token_hash(settings)
    recruiter.notion_preflight_database_id = database_id
    recruiter.notion_preflight_schema_hash = notion_schema_hash(settings)
    recruiter.notion_preflight_synthetic_page_id = "synthetic-page"
    recruiter.notion_preflight_completed_at = datetime.now(UTC)
    session.add(  # type: ignore[attr-defined]
        RecruiterCalendar(
            id=uuid.uuid4(),
            recruiter_id=recruiter.id,
            canonical_url="https://caldav.yandex.ru/default/",
            display_name="Default",
            is_default=True,
            available=True,
            last_seen_at=datetime.now(UTC),
        )
    )
    await session.flush()  # type: ignore[attr-defined]

    activated = await activate_recruiter(
        session,  # type: ignore[arg-type]
        settings,
        recruiter_email=recruiter.email,
        yandex_probe=yandex,
        mattermost=mattermost,
    )

    assert activated.active is True
    yandex.probe.assert_awaited_once_with("r@example.com")
    mattermost.probe_user.assert_awaited_once_with("mm-user")
