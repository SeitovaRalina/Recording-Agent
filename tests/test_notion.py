import asyncio
from datetime import date

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.tools.notion import (
    NOTION_API_VERSION,
    NotionAPIError,
    NotionAuthError,
    NotionClient,
    NotionDatabaseNotFoundError,
    NotionDatabaseUnavailableError,
    NotionDataSourceNotFoundError,
    NotionDataSourceUnavailableError,
    NotionForbiddenError,
    NotionMalformedResponseError,
    NotionQueryError,
    NotionRelationChoice,
    NotionSchemaError,
    NotionSourceAmbiguityError,
    NotionUpdateError,
)

BASE = "https://api.notion.com/v1"
NAME = "Name"
DATE = "General Interview Date"
RECORDING = "General Interview recording"
SPOTS = "📍 Spots"
CONTACTS = "TBD"


def page(page_id: str = "page-1") -> dict[str, object]:
    return {
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "properties": {
            NAME: {"title": [{"plain_text": "Ivan Ivanov"}]},
            DATE: {"date": {"start": "2026-07-16"}},
            CONTACTS: {
                "type": "formula",
                "formula": {
                    "type": "string",
                    "string": "+7 999 000 00 00\nIvan@Example.com\n@ivan",
                },
            },
        },
    }


def database(*source_ids: str) -> dict[str, object]:
    return {"object": "database", "data_sources": [{"id": value} for value in source_ids]}


def schema(
    source_id: str,
    *,
    name_type: str = "title",
    date_type: str = "date",
    recording_type: str = "files",
    contacts_type: str = "formula",
    project_type: str | None = None,
    omit: str | None = None,
) -> dict[str, object]:
    properties: dict[str, object] = {
        NAME: {"type": name_type},
        DATE: {"type": date_type},
        RECORDING: {"type": recording_type},
        CONTACTS: {"type": contacts_type},
    }
    if project_type is not None:
        properties[SPOTS] = {"type": project_type}
    if omit is not None:
        del properties[omit]
    return {"object": "data_source", "id": source_id, "properties": properties}


@pytest.mark.parametrize(
    ("rendered", "expected"),
    [
        (
            "+7 999 000 00 00\nFirst.Last+tag@Example.COM\n@telegram",
            ("first.last+tag@example.com",),
        ),
        ("bad@@example.com\nname@localhost\n.name@example.com", ()),
        (None, ()),
    ],
)
def test_extracts_only_valid_normalized_emails_from_contacts_formula(
    rendered: str | None, expected: tuple[str, ...]
) -> None:
    candidate = page()
    properties = candidate["properties"]
    assert isinstance(properties, dict)
    properties[CONTACTS] = {
        "type": "formula",
        "formula": {"type": "string", "string": rendered},
    }

    parsed = NotionClient._parse_page(candidate, NAME, DATE, CONTACTS, SPOTS)  # noqa: SLF001

    assert parsed.emails == expected
    assert parsed.email == (expected[0] if len(expected) == 1 else None)


@pytest.mark.parametrize(
    "value",
    [
        {"type": "formula", "formula": {"type": "number", "number": 1}},
        {"type": "rich_text", "rich_text": []},
        {"type": "formula", "formula": {"type": "string", "string": []}},
    ],
)
def test_unknown_contacts_formula_shapes_fail_closed(value: dict[str, object]) -> None:
    candidate = page()
    properties = candidate["properties"]
    assert isinstance(properties, dict)
    properties[CONTACTS] = value

    with pytest.raises(NotionMalformedResponseError):
        NotionClient._parse_page(candidate, NAME, DATE, CONTACTS, SPOTS)  # noqa: SLF001


@pytest.mark.anyio
async def test_resolves_project_name_from_spots_relation() -> None:
    related_page_id = "df3fe300-f311-82b4-98f5-013eb4ca475d"
    candidate = page()
    properties = candidate["properties"]
    assert isinstance(properties, dict)
    properties[SPOTS] = {"relation": [{"id": related_page_id}]}

    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(200, json=database("source"))
            )
            router.get(f"{BASE}/data_sources/source").mock(
                return_value=httpx.Response(200, json=schema("source", project_type="relation"))
            )
            router.post(f"{BASE}/data_sources/source/query").mock(
                return_value=httpx.Response(200, json={"results": [candidate]})
            )
            router.get(f"{BASE}/pages/{related_page_id}").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": related_page_id,
                        "url": f"https://notion.so/{related_page_id}",
                        "properties": {"Name": {"title": [{"plain_text": "Backend Spot"}]}},
                    },
                )
            )

            result = await client.search_pages(
                "db",
                "Ivan",
                date(2026, 7, 16),
                NAME,
                DATE,
                RECORDING,
                SPOTS,
                "relation",
            )

    assert result[0].project_or_spot == "Backend Spot"


@pytest.mark.anyio
async def test_returns_every_bounded_spot_for_explicit_choice() -> None:
    candidate = page()
    properties = candidate["properties"]
    assert isinstance(properties, dict)
    properties[SPOTS] = {
        "relation": [
            {"id": "first-spot"},
            {"id": "second-spot"},
        ]
    }

    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(200, json=database("source"))
            )
            router.get(f"{BASE}/data_sources/source").mock(
                return_value=httpx.Response(200, json=schema("source", project_type="relation"))
            )
            router.post(f"{BASE}/data_sources/source/query").mock(
                return_value=httpx.Response(200, json={"results": [candidate]})
            )

            for spot_id, title in (("first-spot", "First"), ("second-spot", "Second")):
                router.get(f"{BASE}/pages/{spot_id}").mock(
                    return_value=httpx.Response(
                        200,
                        json={
                            "id": spot_id,
                            "url": f"https://notion.so/{spot_id}",
                            "properties": {"Name": {"title": [{"plain_text": title}]}},
                        },
                    )
                )
            result = await client.search_pages(
                "db",
                "Ivan",
                date(2026, 7, 16),
                NAME,
                DATE,
                RECORDING,
                SPOTS,
                "relation",
            )

    assert result[0].project_or_spot is None
    assert result[0].spots == (
        NotionRelationChoice("first-spot", "First", "https://notion.so/first-spot"),
        NotionRelationChoice("second-spot", "Second", "https://notion.so/second-spot"),
    )


@pytest.mark.anyio
async def test_rejects_configured_project_property_type_mismatch() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(200, json=database("source"))
            )
            router.get(f"{BASE}/data_sources/source").mock(
                return_value=httpx.Response(200, json=schema("source", project_type="relation"))
            )

            with pytest.raises(NotionSchemaError):
                await client.search_pages(
                    "db",
                    "Ivan",
                    date(2026, 7, 16),
                    NAME,
                    DATE,
                    RECORDING,
                    SPOTS,
                    "rich_text",
                )


def register_chain(
    router: respx.MockRouter,
    *,
    database_id: str = "db",
    source_id: str = "source",
    results: list[dict[str, object]] | None = None,
) -> tuple[respx.Route, respx.Route, respx.Route]:
    discovery = router.get(f"{BASE}/databases/{database_id}").mock(
        return_value=httpx.Response(200, json=database(source_id))
    )
    source = router.get(f"{BASE}/data_sources/{source_id}").mock(
        return_value=httpx.Response(200, json=schema(source_id))
    )
    query = router.post(f"{BASE}/data_sources/{source_id}/query").mock(
        return_value=httpx.Response(200, json={"results": results or []})
    )
    return discovery, source, query


@pytest.mark.anyio
async def test_discovers_validates_and_queries_current_data_source() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            discovery, source, query = register_chain(router, results=[page()])
            result = await client.search_pages(
                "db", "Ivan", date(2026, 7, 16), NAME, DATE, RECORDING
            )

        assert [item.id for item in result] == ["page-1"]
        assert query.calls.last.request.url.path == "/v1/data_sources/source/query"
        assert b'"title":{"contains":"Ivan"}' in query.calls.last.request.content
        assert b"General Interview Date" not in query.calls.last.request.content
        assert b'"page_size":10' in query.calls.last.request.content
        for route in (discovery, source, query):
            assert route.calls.last.request.headers["Notion-Version"] == NOTION_API_VERSION
            assert route.calls.last.request.headers["Authorization"] == "Bearer token"


@pytest.mark.anyio
@pytest.mark.parametrize("source_ids", [("bad", "good"), ("good", "bad")])
async def test_source_order_does_not_override_unique_schema_match(
    source_ids: tuple[str, str],
) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(200, json=database(*source_ids))
            )
            router.get(f"{BASE}/data_sources/bad").mock(
                return_value=httpx.Response(200, json=schema("bad", date_type="rich_text"))
            )
            router.get(f"{BASE}/data_sources/good").mock(
                return_value=httpx.Response(200, json=schema("good"))
            )
            query = router.post(f"{BASE}/data_sources/good/query").mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            assert await client.search_pages("db", "Ivan", date.today(), NAME, DATE) == []
        assert len(query.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("schemas", "error_type"),
    [
        ([schema("one", name_type="rich_text")], NotionSchemaError),
        ([schema("one"), schema("two")], NotionSourceAmbiguityError),
    ],
)
async def test_fails_closed_when_schema_selection_is_not_unique(
    schemas: list[dict[str, object]], error_type: type[Exception]
) -> None:
    ids = [str(item["id"]) for item in schemas]
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(200, json=database(*ids))
            )
            for source_schema in schemas:
                router.get(f"{BASE}/data_sources/{source_schema['id']}").mock(
                    return_value=httpx.Response(200, json=source_schema)
                )
            with pytest.raises(error_type):
                await client.search_pages("db", "Ivan", date.today(), NAME, DATE)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source_schema",
    [
        schema("source", omit=NAME),
        schema("source", omit=DATE),
        schema("source", omit=RECORDING),
        schema("source", omit=CONTACTS),
        schema("source", name_type="rich_text"),
        schema("source", date_type="rich_text"),
        schema("source", recording_type="url"),
        schema("source", contacts_type="rich_text"),
    ],
)
async def test_rejects_missing_or_wrong_required_property_types(
    source_schema: dict[str, object],
) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(200, json=database("source"))
            )
            router.get(f"{BASE}/data_sources/source").mock(
                return_value=httpx.Response(200, json=source_schema)
            )
            with pytest.raises(NotionSchemaError):
                await client.search_pages("db", "Ivan", date.today(), NAME, DATE)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, NotionAuthError),
        (403, NotionForbiddenError),
        (404, NotionDatabaseNotFoundError),
        (500, NotionAPIError),
    ],
)
async def test_database_discovery_errors_are_typed_and_sanitized(
    status: int, error_type: type[Exception]
) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("secret-token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(status, json={"secret": "credential-payload"})
            )
            with pytest.raises(error_type) as raised:
                await client.search_pages("db", "Ivan", date.today(), NAME, DATE)
        assert "secret-token" not in str(raised.value)
        assert "credential-payload" not in str(raised.value)


@pytest.mark.anyio
async def test_missing_discovered_source_is_typed() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(f"{BASE}/databases/db").mock(
                return_value=httpx.Response(200, json=database("gone"))
            )
            router.get(f"{BASE}/data_sources/gone").mock(return_value=httpx.Response(404))
            with pytest.raises(NotionDataSourceNotFoundError):
                await client.search_pages("db", "Ivan", date.today(), NAME, DATE)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 429, 500])
async def test_query_failures_are_typed_without_unbounded_retry(status: int) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            _, _, query = register_chain(router)
            query.mock(return_value=httpx.Response(status, json={"token": "must-not-leak"}))
            with pytest.raises(NotionQueryError) as raised:
                await client.search_pages("db", "Ivan", date.today(), NAME, DATE)
        assert len(query.calls) == 1
        assert "must-not-leak" not in str(raised.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("database", {"data_sources": "wrong"}),
        ("database", {"data_sources": [{}]}),
        ("source", {"id": "source", "properties": []}),
        ("query", {"results": {}}),
    ],
)
async def test_malformed_payloads_fail_closed(endpoint: str, payload: dict[str, object]) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            if endpoint == "database":
                router.get(f"{BASE}/databases/db").mock(
                    return_value=httpx.Response(200, json=payload)
                )
            elif endpoint == "source":
                router.get(f"{BASE}/databases/db").mock(
                    return_value=httpx.Response(200, json=database("source"))
                )
                router.get(f"{BASE}/data_sources/source").mock(
                    return_value=httpx.Response(200, json=payload)
                )
            else:
                _, _, query = register_chain(router)
                query.mock(return_value=httpx.Response(200, json=payload))
            with pytest.raises(NotionMalformedResponseError):
                await client.search_pages("db", "Ivan", date.today(), NAME, DATE)


@pytest.mark.anyio
async def test_cache_hit_skips_discovery_and_concurrent_first_lookup_is_single_flight() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            discovery, source, query = register_chain(router)
            await asyncio.gather(
                client.search_pages("db", "Ivan", date.today(), NAME, DATE),
                client.search_pages("db", "Ivan", date.today(), NAME, DATE),
            )
            await client.search_pages("db", "Ivan", date.today(), NAME, DATE)
        assert len(discovery.calls) == 1
        assert len(source.calls) == 1
        assert len(query.calls) == 3


@pytest.mark.anyio
async def test_cache_is_bounded_and_evicts_least_recent_database() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http, cache_size=1)
        with respx.mock(assert_all_called=True) as router:
            db_one = router.get(f"{BASE}/databases/one").mock(
                return_value=httpx.Response(200, json=database("source-one"))
            )
            db_two = router.get(f"{BASE}/databases/two").mock(
                return_value=httpx.Response(200, json=database("source-two"))
            )
            for source_id in ("source-one", "source-two"):
                router.get(f"{BASE}/data_sources/{source_id}").mock(
                    return_value=httpx.Response(200, json=schema(source_id))
                )
                router.post(f"{BASE}/data_sources/{source_id}/query").mock(
                    return_value=httpx.Response(200, json={"results": []})
                )
            await client.search_pages("one", "Ivan", date.today(), NAME, DATE)
            await client.search_pages("two", "Ivan", date.today(), NAME, DATE)
            await client.search_pages("one", "Ivan", date.today(), NAME, DATE)
        assert len(db_one.calls) == 2
        assert len(db_two.calls) == 1


@pytest.mark.anyio
async def test_cached_stale_source_is_invalidated_rediscovered_and_retried_once() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            discovery = router.get(f"{BASE}/databases/db").mock(
                side_effect=[
                    httpx.Response(200, json=database("old")),
                    httpx.Response(200, json=database("new")),
                ]
            )
            for source_id in ("old", "new"):
                router.get(f"{BASE}/data_sources/{source_id}").mock(
                    return_value=httpx.Response(200, json=schema(source_id))
                )
            old_query = router.post(f"{BASE}/data_sources/old/query").mock(
                side_effect=[
                    httpx.Response(200, json={"results": []}),
                    httpx.Response(404),
                ]
            )
            new_query = router.post(f"{BASE}/data_sources/new/query").mock(
                return_value=httpx.Response(200, json={"results": [page("new-page")]})
            )
            await client.search_pages("db", "Ivan", date.today(), NAME, DATE)
            result = await client.search_pages("db", "Ivan", date.today(), NAME, DATE)
        assert [item.id for item in result] == ["new-page"]
        assert len(discovery.calls) == 2
        assert len(old_query.calls) == 2
        assert len(new_query.calls) == 1


@pytest.mark.anyio
async def test_stale_source_retry_happens_only_once() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            discovery = router.get(f"{BASE}/databases/db").mock(
                side_effect=[
                    httpx.Response(200, json=database("old")),
                    httpx.Response(200, json=database("new")),
                ]
            )
            for source_id in ("old", "new"):
                router.get(f"{BASE}/data_sources/{source_id}").mock(
                    return_value=httpx.Response(200, json=schema(source_id))
                )
            router.post(f"{BASE}/data_sources/old/query").mock(
                side_effect=[httpx.Response(200, json={"results": []}), httpx.Response(404)]
            )
            new_query = router.post(f"{BASE}/data_sources/new/query").mock(
                return_value=httpx.Response(404)
            )
            await client.search_pages("db", "Ivan", date.today(), NAME, DATE)
            with pytest.raises(NotionDataSourceNotFoundError):
                await client.search_pages("db", "Ivan", date.today(), NAME, DATE)
        assert len(discovery.calls) == 2
        assert len(new_query.calls) == 1


@pytest.mark.anyio
async def test_update_page_interview_uses_date_and_external_file_current_header() -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        with respx.mock(assert_all_called=True) as router:
            route = router.patch(f"{BASE}/pages/page").mock(
                return_value=httpx.Response(200, json={})
            )
            await client.update_page_interview(
                "page",
                date_prop=DATE,
                recording_prop=RECORDING,
                event_date=date(2026, 7, 16),
                url="https://share",
                filename="interview.webm",
            )
        assert route.calls.last.request.headers["Notion-Version"] == NOTION_API_VERSION
        assert route.calls.last.request.content == (
            b'{"properties":{"General Interview Date":{"date":{"start":"2026-07-16"}},'
            b'"General Interview recording":{"files":['
            b'{"name":"interview.webm","external":{"url":"https://share"}}]}}}'
        )

        with respx.mock(assert_all_called=True) as router:
            router.patch(f"{BASE}/pages/page").mock(return_value=httpx.Response(500))
            with pytest.raises(NotionUpdateError):
                await client.update_page_interview(
                    "page",
                    date_prop=DATE,
                    recording_prop=RECORDING,
                    event_date=date(2026, 7, 16),
                    url="https://share",
                    filename="interview.webm",
                )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("operation", "error_type"),
    [
        ("database", NotionDatabaseUnavailableError),
        ("source", NotionDataSourceUnavailableError),
        ("query", NotionQueryError),
        ("update", NotionUpdateError),
    ],
)
async def test_transport_failures_are_typed_and_sanitized(
    operation: str, error_type: type[Exception]
) -> None:
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("secret-token"), http)
        with respx.mock(assert_all_called=True) as router:
            if operation == "database":
                router.get(f"{BASE}/databases/secret-database-id").mock(
                    side_effect=httpx.ConnectError("credential-bearing transport failure")
                )
            elif operation == "update":
                router.patch(f"{BASE}/pages/secret-page-id").mock(
                    side_effect=httpx.ReadTimeout("credential-bearing transport failure")
                )
            else:
                router.get(f"{BASE}/databases/secret-database-id").mock(
                    return_value=httpx.Response(200, json=database("secret-source-id"))
                )
                if operation == "source":
                    router.get(f"{BASE}/data_sources/secret-source-id").mock(
                        side_effect=httpx.ConnectTimeout("credential-bearing transport failure")
                    )
                else:
                    router.get(f"{BASE}/data_sources/secret-source-id").mock(
                        return_value=httpx.Response(200, json=schema("secret-source-id"))
                    )
                    router.post(f"{BASE}/data_sources/secret-source-id/query").mock(
                        side_effect=httpx.WriteTimeout("credential-bearing transport failure")
                    )

            with pytest.raises(error_type) as raised:
                if operation == "update":
                    await client.update_page_interview(
                        "secret-page-id",
                        date_prop=DATE,
                        recording_prop=RECORDING,
                        event_date=date(2026, 7, 16),
                        url="https://secret-share-url",
                        filename="secret-recording-name.webm",
                    )
                else:
                    await client.search_pages(
                        "secret-database-id", "Ivan", date.today(), NAME, DATE
                    )

        message = str(raised.value)
        assert "secret-token" not in message
        assert "secret-database-id" not in message
        assert "secret-source-id" not in message
        assert "secret-share-url" not in message
        assert "secret-recording-name" not in message
        assert "credential-bearing" not in message
