from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from pydantic import SecretStr

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"
DEFAULT_RECORDING_PROP = "General Interview recording"
DEFAULT_CACHE_SIZE = 128


class NotionAPIError(RuntimeError):
    """Sanitized base error for Notion integration failures."""


class NotionAuthError(NotionAPIError):
    pass


class NotionForbiddenError(NotionAPIError):
    pass


class NotionDatabaseNotFoundError(NotionAPIError):
    pass


class NotionDatabaseUnavailableError(NotionAPIError):
    pass


class NotionDataSourceNotFoundError(NotionAPIError):
    pass


class NotionDataSourceUnavailableError(NotionAPIError):
    pass


class NotionSchemaError(NotionAPIError):
    pass


class NotionSourceAmbiguityError(NotionSchemaError):
    pass


class NotionMalformedResponseError(NotionAPIError):
    pass


class NotionQueryError(NotionAPIError):
    pass


class NotionUpdateError(NotionAPIError):
    pass


@dataclass(frozen=True)
class NotionPage:
    id: str
    url: str
    title: str
    date_str: str | None
    email: str | None = None


@dataclass(frozen=True)
class NotionDataSource:
    id: str


@dataclass(frozen=True)
class NotionDataSourceSchema:
    id: str
    property_types: dict[str, str]

    def is_compatible(self, name_prop: str, date_prop: str, recording_prop: str) -> bool:
        return (
            self.property_types.get(name_prop) == "title"
            and self.property_types.get(date_prop) == "date"
            and self.property_types.get(recording_prop) == "files"
        )


SourceCacheKey = tuple[str, str, str, str]


class NotionClient:
    def __init__(
        self,
        token: SecretStr,
        client: httpx.AsyncClient,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        if cache_size < 1:
            raise ValueError("Notion source cache size must be positive")
        self._token = token
        self._client = client
        self._cache_size = cache_size
        self._source_cache: OrderedDict[SourceCacheKey, str] = OrderedDict()
        self._inflight: dict[SourceCacheKey, asyncio.Task[str]] = {}
        self._inflight_guard = asyncio.Lock()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token.get_secret_value()}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }

    async def search_pages(
        self,
        database_id: str,
        candidate_name: str,
        event_date: date,
        name_prop: str,
        date_prop: str,
        recording_prop: str = DEFAULT_RECORDING_PROP,
    ) -> list[NotionPage]:
        key = (database_id, name_prop, date_prop, recording_prop)
        source_id, was_cached = await self._resolve_source(key)
        response = await self._query_source(
            source_id, candidate_name, event_date, name_prop, date_prop
        )
        if response.status_code == 404 and was_cached:
            self._invalidate(key, source_id)
            source_id, _ = await self._resolve_source(key)
            response = await self._query_source(
                source_id, candidate_name, event_date, name_prop, date_prop
            )
        self._raise_query_error(response)
        payload = self._json_object(response, "query")
        results = payload.get("results")
        if not isinstance(results, list):
            raise NotionMalformedResponseError("Notion query response has invalid results")
        return [self._parse_page(item, name_prop, date_prop) for item in results[:10]]

    async def update_page_file(self, page_id: str, prop_name: str, url: str, filename: str) -> None:
        try:
            response = await self._client.patch(
                f"{NOTION_API_BASE}/pages/{page_id}",
                headers=self._headers,
                json={
                    "properties": {
                        prop_name: {
                            "files": [
                                {
                                    "name": filename,
                                    "external": {"url": url},
                                }
                            ]
                        }
                    }
                },
            )
        except httpx.RequestError:
            raise NotionUpdateError("Notion page update transport failed") from None
        self._raise_common(response)
        if response.is_error:
            raise NotionUpdateError(f"Notion page update failed with HTTP {response.status_code}")

    async def _resolve_source(self, key: SourceCacheKey) -> tuple[str, bool]:
        cached = self._cache_get(key)
        if cached is not None:
            return cached, True
        while True:
            capacity_waiter: asyncio.Task[str] | None = None
            async with self._inflight_guard:
                cached = self._cache_get(key)
                if cached is not None:
                    return cached, True
                task = self._inflight.get(key)
                if task is None and len(self._inflight) < self._cache_size:
                    task = asyncio.create_task(self._discover_source(key))
                    self._inflight[key] = task
                elif task is None:
                    capacity_waiter = next(iter(self._inflight.values()))
            if capacity_waiter is not None:
                try:
                    await asyncio.shield(capacity_waiter)
                except NotionAPIError:
                    pass
                continue
            assert task is not None
            try:
                source_id = await asyncio.shield(task)
                self._cache_put(key, source_id)
                return source_id, False
            finally:
                async with self._inflight_guard:
                    if self._inflight.get(key) is task and task.done():
                        del self._inflight[key]

    async def _discover_source(self, key: SourceCacheKey) -> str:
        database_id, name_prop, date_prop, recording_prop = key
        try:
            response = await self._client.get(
                f"{NOTION_API_BASE}/databases/{database_id}", headers=self._headers
            )
        except httpx.RequestError:
            raise NotionDatabaseUnavailableError(
                "Notion database discovery transport failed"
            ) from None
        self._raise_common(response)
        if response.status_code == 404:
            raise NotionDatabaseNotFoundError("Notion database is unavailable")
        if response.is_error:
            raise NotionAPIError(
                f"Notion database discovery failed with HTTP {response.status_code}"
            )
        database = self._json_object(response, "database discovery")
        sources = self._parse_sources(database)
        compatible: list[str] = []
        for source in sources:
            schema = await self._retrieve_schema(source.id)
            if schema.is_compatible(name_prop, date_prop, recording_prop):
                compatible.append(schema.id)
        if not compatible:
            raise NotionSchemaError("No Notion data source has the required schema")
        if len(compatible) > 1:
            raise NotionSourceAmbiguityError(
                "Multiple Notion data sources have the required schema"
            )
        return compatible[0]

    async def _retrieve_schema(self, source_id: str) -> NotionDataSourceSchema:
        try:
            response = await self._client.get(
                f"{NOTION_API_BASE}/data_sources/{source_id}", headers=self._headers
            )
        except httpx.RequestError:
            raise NotionDataSourceUnavailableError(
                "Notion data-source schema transport failed"
            ) from None
        self._raise_common(response)
        if response.status_code == 404:
            raise NotionDataSourceNotFoundError("Notion data source is unavailable")
        if response.is_error:
            raise NotionAPIError(
                f"Notion data-source schema retrieval failed with HTTP {response.status_code}"
            )
        payload = self._json_object(response, "data-source schema")
        payload_id = payload.get("id")
        properties = payload.get("properties")
        if not isinstance(payload_id, str) or not payload_id or not isinstance(properties, dict):
            raise NotionMalformedResponseError("Notion data-source schema is malformed")
        if payload_id != source_id:
            raise NotionMalformedResponseError("Notion data-source identity is malformed")
        property_types: dict[str, str] = {}
        for name, descriptor in properties.items():
            if not isinstance(name, str) or not isinstance(descriptor, dict):
                raise NotionMalformedResponseError("Notion data-source properties are malformed")
            prop_type = descriptor.get("type")
            if isinstance(prop_type, str):
                property_types[name] = prop_type
        return NotionDataSourceSchema(id=payload_id, property_types=property_types)

    async def _query_source(
        self,
        source_id: str,
        candidate_name: str,
        event_date: date,
        name_prop: str,
        date_prop: str,
    ) -> httpx.Response:
        try:
            return await self._client.post(
                f"{NOTION_API_BASE}/data_sources/{source_id}/query",
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
        except httpx.RequestError:
            raise NotionQueryError("Notion query transport failed") from None

    @staticmethod
    def _parse_sources(payload: dict[str, Any]) -> list[NotionDataSource]:
        raw_sources = payload.get("data_sources")
        if not isinstance(raw_sources, list):
            raise NotionMalformedResponseError("Notion database response has invalid data_sources")
        sources: list[NotionDataSource] = []
        for item in raw_sources:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise NotionMalformedResponseError("Notion data-source descriptor is malformed")
            sources.append(NotionDataSource(id=item["id"]))
        return sources

    @classmethod
    def _json_object(cls, response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise NotionMalformedResponseError(
                f"Notion {operation} response is not valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise NotionMalformedResponseError(f"Notion {operation} response is not an object")
        return payload

    @staticmethod
    def _raise_common(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise NotionAuthError("Notion authentication failed")
        if response.status_code == 403:
            raise NotionForbiddenError("Notion resource is forbidden or not shared")

    @classmethod
    def _raise_query_error(cls, response: httpx.Response) -> None:
        cls._raise_common(response)
        if response.status_code == 404:
            raise NotionDataSourceNotFoundError("Notion data source is unavailable")
        if response.is_error:
            raise NotionQueryError(f"Notion query failed with HTTP {response.status_code}")

    def _cache_get(self, key: SourceCacheKey) -> str | None:
        source_id = self._source_cache.get(key)
        if source_id is not None:
            self._source_cache.move_to_end(key)
        return source_id

    def _cache_put(self, key: SourceCacheKey, source_id: str) -> None:
        self._source_cache[key] = source_id
        self._source_cache.move_to_end(key)
        while len(self._source_cache) > self._cache_size:
            self._source_cache.popitem(last=False)

    def _invalidate(self, key: SourceCacheKey, source_id: str) -> None:
        if self._source_cache.get(key) == source_id:
            del self._source_cache[key]

    @staticmethod
    def _parse_page(item: Any, name_prop: str, date_prop: str) -> NotionPage:
        if not isinstance(item, dict):
            raise NotionMalformedResponseError("Notion page payload must be an object")
        page_id = item.get("id")
        page_url = item.get("url")
        properties = item.get("properties")
        if not isinstance(page_id, str) or not isinstance(page_url, str):
            raise NotionMalformedResponseError("Notion page identity is malformed")
        if not isinstance(properties, dict):
            raise NotionMalformedResponseError("Notion page properties are malformed")
        email = next(
            (
                str(value["email"])
                for value in properties.values()
                if isinstance(value, dict) and isinstance(value.get("email"), str)
            ),
            None,
        )
        return NotionPage(
            id=page_id,
            url=page_url,
            title=NotionClient._plain_text(properties.get(name_prop)),
            date_str=NotionClient._date_value(properties.get(date_prop)),
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
