import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.tools.notion import NotionSchemaError
from tools.setup.preflight_notion import inspect_canary_notion_schema

DATABASE_ID = "00000000-0000-0000-0000-000000000001"
SOURCE_ID = "00000000-0000-0000-0000-000000000002"
BASE_URL = "https://api.notion.com/v1"


def canary_settings(**changes: object) -> Settings:
    return Settings(
        app_environment="production",
        notion_token=SecretStr("notion-token"),
        notion_proxy_url="http://notion-proxy:7890",
        test_mode_enabled=True,
        test_notion_database_allowlist={DATABASE_ID},
        notion_project_prop="📍 Spots",
        **changes,
    )


def database() -> dict[str, object]:
    return {
        "object": "database",
        "title": [{"plain_text": "Test Interviews"}],
        "data_sources": [{"id": SOURCE_ID}],
    }


def data_source(*, project_type: str = "relation") -> dict[str, object]:
    return {
        "object": "data_source",
        "id": SOURCE_ID,
        "properties": {
            "Name": {"type": "title"},
            "General Interview Date": {"type": "date"},
            "General Interview recording": {"type": "files"},
            "TBD": {"type": "formula"},
            "📍 Spots": {"type": project_type},
            "рџ“Ќ Spots": {"type": project_type},
        },
    }


@pytest.mark.anyio
@respx.mock
async def test_preflight_uses_only_database_and_data_source_gets() -> None:
    database_route = respx.get(f"{BASE_URL}/databases/{DATABASE_ID}").mock(
        return_value=httpx.Response(200, json=database())
    )
    source_route = respx.get(f"{BASE_URL}/data_sources/{SOURCE_ID}").mock(
        return_value=httpx.Response(200, json=data_source())
    )

    inspection = await inspect_canary_notion_schema(canary_settings(), DATABASE_ID)

    assert inspection.database_id == DATABASE_ID
    assert database_route.call_count == 1
    assert source_route.call_count == 1
    assert all(call.request.method == "GET" for call in respx.calls)
    assert all("/pages" not in str(call.request.url) for call in respx.calls)
    assert all("/query" not in str(call.request.url) for call in respx.calls)


@pytest.mark.anyio
@respx.mock
async def test_preflight_rejects_incompatible_schema_without_page_query() -> None:
    respx.get(f"{BASE_URL}/databases/{DATABASE_ID}").mock(
        return_value=httpx.Response(200, json=database())
    )
    respx.get(f"{BASE_URL}/data_sources/{SOURCE_ID}").mock(
        return_value=httpx.Response(200, json=data_source(project_type="rich_text"))
    )

    with pytest.raises(NotionSchemaError):
        await inspect_canary_notion_schema(canary_settings(), DATABASE_ID)

    assert all(call.request.method == "GET" for call in respx.calls)
    assert all("/pages" not in str(call.request.url) for call in respx.calls)
    assert all("/query" not in str(call.request.url) for call in respx.calls)


@pytest.mark.anyio
async def test_preflight_rejects_non_allowlisted_database_before_network() -> None:
    with pytest.raises(ValueError, match="ALLOWLIST"):
        await inspect_canary_notion_schema(
            canary_settings(), "00000000-0000-0000-0000-000000000003"
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "flag",
    [
        "scheduler_enabled",
        "autonomous_routing_enabled",
        "notion_writes_enabled",
        "mattermost_delivery_enabled",
        "yandex_source_mutation_enabled",
    ],
)
async def test_preflight_rejects_enabled_side_effects(flag: str) -> None:
    with pytest.raises(ValueError, match="side-effect|forbidden in test mode"):
        await inspect_canary_notion_schema(canary_settings(**{flag: True}), DATABASE_ID)
