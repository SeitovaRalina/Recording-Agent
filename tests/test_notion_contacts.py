"""contacts_mode none|formula|relation in the Notion client."""

from datetime import date

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.tools.notion import (
    NotionAuthError,
    NotionClient,
    NotionDataSourceSchema,
    NotionPage,
    NotionQueryError,
    NotionSchemaError,
)
from tests.test_notion import BASE, CONTACTS, DATE, NAME, RECORDING, SPOTS, database, page

CANDIDATE_REL = "Candidate"
TARGET = "Contacts"


def schema_without_contacts(source_id: str, *, candidate_relation: bool) -> dict[str, object]:
    properties: dict[str, object] = {
        NAME: {"type": "title"},
        DATE: {"type": "date"},
        RECORDING: {"type": "files"},
        SPOTS: {"type": "relation"},
    }
    if candidate_relation:
        properties[CANDIDATE_REL] = {"type": "relation"}
    return {"object": "data_source", "id": source_id, "properties": properties}


def interview_page(relation_ids: list[str]) -> dict[str, object]:
    candidate = page()
    properties = candidate["properties"]
    assert isinstance(properties, dict)
    del properties[CONTACTS]
    properties[CANDIDATE_REL] = {"relation": [{"id": value} for value in relation_ids]}
    return candidate


def candidate_card(page_id: str, text: str | None) -> dict[str, object]:
    properties: dict[str, object] = {"Name": {"title": [{"plain_text": "Ivan Ivanov"}]}}
    if text is not None:
        properties[TARGET] = {"type": "rich_text", "rich_text": [{"plain_text": text}]}
    return {"id": page_id, "url": f"https://notion.so/{page_id}", "properties": properties}


def test_is_compatible_by_contacts_mode() -> None:
    no_contacts = NotionDataSourceSchema(
        "s", {NAME: "title", DATE: "date", RECORDING: "files", CANDIDATE_REL: "relation"}
    )
    with_formula = NotionDataSourceSchema(
        "s", {NAME: "title", DATE: "date", RECORDING: "files", CONTACTS: "formula"}
    )

    assert no_contacts.is_compatible(NAME, DATE, RECORDING, CONTACTS, contacts_mode="none")
    assert not no_contacts.is_compatible(NAME, DATE, RECORDING, CONTACTS)
    assert no_contacts.is_compatible(
        NAME,
        DATE,
        RECORDING,
        CONTACTS,
        contacts_mode="relation",
        contacts_relation_prop=CANDIDATE_REL,
    )
    assert not with_formula.is_compatible(
        NAME,
        DATE,
        RECORDING,
        CONTACTS,
        contacts_mode="relation",
        contacts_relation_prop=CANDIDATE_REL,
    )
    assert with_formula.is_compatible(NAME, DATE, RECORDING, CONTACTS)
    assert not with_formula.is_compatible(NAME, DATE, RECORDING, CONTACTS, contacts_mode="bogus")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "+7 999 000 00 00\nFirst.Last+tag@Example.COM\n@telegram",
            ("first.last+tag@example.com",),
        ),
        ("a@example.com, B@Example.com a@example.com", ("a@example.com", "b@example.com")),
        ("bad@@example.com\nname@localhost\n.name@example.com", ()),
    ],
)
def test_rich_text_emails_match_formula_parsing(text: str, expected: tuple[str, ...]) -> None:
    rich = {"type": "rich_text", "rich_text": [{"plain_text": text}]}
    formula = {"type": "formula", "formula": {"type": "string", "string": text}}

    assert NotionClient._rich_text_emails(rich) == expected  # noqa: SLF001
    assert NotionClient._formula_emails(formula) == expected  # noqa: SLF001
    assert NotionClient._extract_emails(text) == expected  # noqa: SLF001


@pytest.mark.parametrize(
    "value", [None, {"type": "email", "email": "a@example.com"}, {"type": "title", "title": []}]
)
def test_rich_text_emails_soft_fail_on_missing_or_wrong_type(value: object) -> None:
    assert NotionClient._rich_text_emails(value) == ()  # noqa: SLF001


def test_parse_page_none_and_relation_modes_skip_formula() -> None:
    candidate = interview_page([])

    for mode in ("none", "relation"):
        parsed = NotionClient._parse_page(  # noqa: SLF001
            candidate, NAME, DATE, CONTACTS, SPOTS, contacts_mode=mode
        )
        assert parsed.emails == ()
        assert parsed.email is None


async def _search(
    router: respx.MockRouter, results: list[dict[str, object]], mode: str
) -> list[NotionPage]:
    router.get(f"{BASE}/databases/db").mock(
        return_value=httpx.Response(200, json=database("source"))
    )
    router.get(f"{BASE}/data_sources/source").mock(
        return_value=httpx.Response(
            200, json=schema_without_contacts("source", candidate_relation=mode == "relation")
        )
    )
    router.post(f"{BASE}/data_sources/source/query").mock(
        return_value=httpx.Response(200, json={"results": results})
    )
    async with httpx.AsyncClient() as http:
        client = NotionClient(SecretStr("token"), http)
        return list(
            await client.search_pages(
                "db",
                "Ivan",
                date(2026, 7, 16),
                NAME,
                DATE,
                RECORDING,
                "",
                "",
                CONTACTS,
                contacts_mode=mode,
                contacts_relation_prop=CANDIDATE_REL if mode == "relation" else "",
                contacts_target_prop=TARGET if mode == "relation" else "",
            )
        )


@pytest.mark.anyio
async def test_relation_mode_reads_email_from_single_linked_card() -> None:
    with respx.mock(assert_all_called=True) as router:
        card = router.get(f"{BASE}/pages/cand-1").mock(
            return_value=httpx.Response(
                200, json=candidate_card("cand-1", "tg @ivan\nIvan@Example.com")
            )
        )
        pages = await _search(
            router, [interview_page(["cand-1"]), interview_page(["cand-1"])], "relation"
        )

    assert card.call_count == 1  # cached per relation id
    assert [p.emails for p in pages] == [("ivan@example.com",), ("ivan@example.com",)]
    assert pages[0].email == "ivan@example.com"


@pytest.mark.anyio
@pytest.mark.parametrize("relation_ids", [[], ["cand-1", "cand-2"]])
async def test_relation_mode_zero_or_many_links_yield_no_emails(relation_ids: list[str]) -> None:
    with respx.mock(assert_all_called=True) as router:
        pages = await _search(router, [interview_page(relation_ids)], "relation")

    assert len(pages) == 1
    assert pages[0].emails == ()
    assert pages[0].email is None


@pytest.mark.anyio
async def test_relation_mode_missing_target_property_soft_fails() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{BASE}/pages/cand-1").mock(
            return_value=httpx.Response(200, json=candidate_card("cand-1", None))
        )
        pages = await _search(router, [interview_page(["cand-1"])], "relation")

    assert pages[0].emails == ()


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 404])
async def test_relation_mode_unavailable_linked_card_yields_no_emails(status: int) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{BASE}/pages/cand-1").mock(
            return_value=httpx.Response(status, json={"object": "error"})
        )
        pages = await _search(router, [interview_page(["cand-1"])], "relation")

    assert len(pages) == 1
    assert pages[0].emails == ()
    assert pages[0].email is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (httpx.Response(500, json={"object": "error"}), NotionQueryError),
        (httpx.Response(429, json={"object": "error"}), NotionQueryError),
        (httpx.ConnectError("boom"), NotionQueryError),
        (httpx.Response(401, json={"object": "error"}), NotionAuthError),
    ],
)
async def test_relation_mode_transient_or_auth_linked_card_errors_propagate(
    response: httpx.Response | Exception, error_type: type[Exception]
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{BASE}/pages/cand-1")
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        with pytest.raises(error_type) as caught:
            await _search(router, [interview_page(["cand-1"])], "relation")

    if isinstance(caught.value, NotionQueryError):
        assert caught.value.transient


@pytest.mark.anyio
async def test_none_mode_needs_no_contacts_property() -> None:
    with respx.mock(assert_all_called=True) as router:
        pages = await _search(router, [interview_page([])], "none")

    assert pages[0].emails == ()


@pytest.mark.anyio
async def test_formula_mode_still_requires_formula_contacts() -> None:
    with respx.mock(assert_all_called=False) as router:
        with pytest.raises(NotionSchemaError):
            await _search(router, [interview_page([])], "formula")


@pytest.mark.anyio
async def test_preflight_skips_formula_probe_outside_formula_mode() -> None:
    synthetic = interview_page([])
    synthetic["id"] = "synthetic"
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{BASE}/databases/db").mock(
            return_value=httpx.Response(
                200, json={**database("source"), "title": [{"plain_text": "Interviews"}]}
            )
        )
        router.get(f"{BASE}/data_sources/source").mock(
            return_value=httpx.Response(
                200, json=schema_without_contacts("source", candidate_relation=True)
            )
        )
        router.post(f"{BASE}/data_sources/source/query").mock(
            return_value=httpx.Response(200, json={"results": [synthetic]})
        )
        async with httpx.AsyncClient() as http:
            client = NotionClient(SecretStr("token"), http)
            for mode in ("none", "relation"):
                inspection = await client.preflight_database(
                    "db",
                    "synthetic",
                    NAME,
                    DATE,
                    RECORDING,
                    SPOTS,
                    "relation",
                    CONTACTS,
                    mode,
                    CANDIDATE_REL,
                )
                assert inspection.schema.id == "source"
