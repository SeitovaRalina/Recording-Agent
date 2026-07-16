from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from pydantic import SecretStr

NOTION_API_BASE = "https://api.notion.com/v1"


class NotionAPIError(RuntimeError):
    pass


class NotionAuthError(NotionAPIError):
    pass


class NotionDatabaseNotFoundError(NotionAPIError):
    pass


@dataclass(frozen=True)
class NotionPage:
    id: str
    url: str
    title: str
    date_str: str | None
    email: str | None = None


class NotionClient:
    def __init__(self, token: SecretStr, client: httpx.AsyncClient) -> None:
        self._token = token
        self._client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token.get_secret_value()}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    async def search_pages(
        self,
        database_id: str,
        candidate_name: str,
        event_date: date,
        name_prop: str,
        date_prop: str,
    ) -> list[NotionPage]:
        response = await self._client.post(
            f"{NOTION_API_BASE}/databases/{database_id}/query",
            headers=self._headers,
            json={
                "filter": {
                    "and": [
                        {"property": name_prop, "title": {"contains": candidate_name}},
                        {"property": date_prop, "date": {"equals": event_date.isoformat()}},
                    ]
                },
                "page_size": 10,
            },
        )
        self._raise_for_status(response, database=True)
        payload = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [self._parse_page(item, name_prop, date_prop) for item in results[:10]]

    async def update_page_url(self, page_id: str, prop_name: str, url: str) -> None:
        response = await self._client.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=self._headers,
            json={"properties": {prop_name: {"url": url}}},
        )
        self._raise_for_status(response)

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, database: bool = False) -> None:
        if response.status_code == 401:
            raise NotionAuthError("Notion authentication failed")
        if database and response.status_code == 404:
            raise NotionDatabaseNotFoundError("Notion database was not found")
        if response.is_error:
            raise NotionAPIError(f"Notion API returned HTTP {response.status_code}")

    @staticmethod
    def _parse_page(item: Any, name_prop: str, date_prop: str) -> NotionPage:
        if not isinstance(item, dict):
            raise NotionAPIError("Notion page payload must be an object")
        properties = item.get("properties")
        props = properties if isinstance(properties, dict) else {}
        email = next(
            (
                str(value["email"])
                for value in props.values()
                if isinstance(value, dict) and isinstance(value.get("email"), str)
            ),
            None,
        )
        return NotionPage(
            id=str(item.get("id", "")),
            url=str(item.get("url", "")),
            title=NotionClient._plain_text(props.get(name_prop)),
            date_str=NotionClient._date_value(props.get(date_prop)),
            email=email,
        )

    @staticmethod
    def _plain_text(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        entries = value.get("title") or value.get("rich_text") or []
        if not isinstance(entries, list):
            return ""
        return "".join(
            str(entry.get("plain_text", "")) for entry in entries if isinstance(entry, dict)
        )

    @staticmethod
    def _date_value(value: Any) -> str | None:
        if not isinstance(value, dict) or not isinstance(value.get("date"), dict):
            return None
        start = value["date"].get("start")
        return str(start) if start is not None else None
