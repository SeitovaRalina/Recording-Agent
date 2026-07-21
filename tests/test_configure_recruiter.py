from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.config import Settings
from tools.setup.configure_recruiter import (
    DatabaseInspection,
    configure_recruiter,
    parse_notion_database_id,
)


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
        {"Name": "title", "Spot Client": "rich_text"},
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
