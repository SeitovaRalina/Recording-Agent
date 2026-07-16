from datetime import date

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.tools.notion import (
    NotionAPIError,
    NotionAuthError,
    NotionClient,
    NotionDatabaseNotFoundError,
)


def page(page_id: str = "page-1") -> dict[str, object]:
    return {
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "properties": {
            "Name": {"title": [{"plain_text": "Ivan Ivanov"}]},
            "General Interview Date": {"date": {"start": "2026-07-16"}},
            "Email": {"email": "ivan@example.com"},
        },
    }


@pytest.mark.anyio
@pytest.mark.parametrize("results_count", [0, 1, 3])
async def test_search_pages_is_bounded_and_sends_date_filter(results_count: int) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            route = router.post("https://api.notion.com/v1/databases/db/query").mock(
                return_value=httpx.Response(
                    200, json={"results": [page(str(index)) for index in range(results_count)]}
                )
            )
            result = await client.search_pages(
                "db", "Ivan", date(2026, 7, 16), "Name", "General Interview Date"
            )
        request = route.calls.last.request
        assert len(result) == results_count
        assert request.headers["Authorization"] == "Bearer token"
        assert b'"property":"Name","title":{"contains":"Ivan"}' in request.content
        assert b'"rich_text"' not in request.content
        assert b'"equals":"2026-07-16"' in request.content
        assert b'"page_size":10' in request.content


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, NotionAuthError), (404, NotionDatabaseNotFoundError), (500, NotionAPIError)],
)
async def test_search_errors(status: int, error_type: type[Exception]) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock:
            respx.post("https://api.notion.com/v1/databases/db/query").mock(
                return_value=httpx.Response(status)
            )
            with pytest.raises(error_type):
                await client.search_pages("db", "Ivan", date.today(), "Name", "Date")


@pytest.mark.anyio
async def test_update_page_url_success_and_error() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock:
            route = respx.patch("https://api.notion.com/v1/pages/page").mock(
                return_value=httpx.Response(200, json={})
            )
            await client.update_page_url("page", "Recording", "https://share")
            assert b'"url":"https://share"' in route.calls.last.request.content
        with respx.mock:
            respx.patch("https://api.notion.com/v1/pages/page").mock(
                return_value=httpx.Response(500)
            )
            with pytest.raises(NotionAPIError):
                await client.update_page_url("page", "Recording", "https://share")
