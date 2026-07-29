from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.services.pipeline_trace import safe_url, trace

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"
DEFAULT_RECORDING_PROP = "General Interview recording"
DEFAULT_CACHE_SIZE = 128
MAX_SPOT_CHOICES = 10
_TRACE_BODY_LIMIT = 500
_EMAIL_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+)"
    r"(?![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
)


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
class NotionRelationChoice:
    id: str
    title: str
    url: str


@dataclass(frozen=True)
class NotionPage:
    id: str
    url: str
    title: str
    date_str: str | None
    email: str | None = None
    project_or_spot: str | None = "unspecified"
    emails: tuple[str, ...] = ()
    spots: tuple[NotionRelationChoice, ...] = ()
    recording_present: bool = False


@dataclass(frozen=True)
class NotionDataSource:
    id: str


@dataclass(frozen=True)
class NotionDataSourceSchema:
    id: str
    property_types: dict[str, str]

    def is_compatible(
        self,
        name_prop: str,
        date_prop: str,
        recording_prop: str,
        contacts_prop: str,
        project_prop: str = "",
        project_prop_type: str = "",
    ) -> bool:
        return (
            self.property_types.get(name_prop) == "title"
            and self.property_types.get(date_prop) == "date"
            and self.property_types.get(recording_prop) == "files"
            and self.property_types.get(contacts_prop) == "formula"
            and (
                not project_prop
                or (
                    project_prop_type == "relation"
                    and self.property_types.get(project_prop) == "relation"
                )
            )
        )


@dataclass(frozen=True)
class NotionDatabaseInspection:
    database_id: str
    title: str
    schema: NotionDataSourceSchema


SourceCacheKey = tuple[str, str, str, str, str, str, str]


class NotionClient:
    def __init__(
        self,
        token: SecretStr,
        client: httpx.AsyncClient,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
        settings: Settings | None = None,
    ) -> None:
        if cache_size < 1:
            raise ValueError("Notion source cache size must be positive")
        self._token = token
        self._client = client
        self._cache_size = cache_size
        self._settings = settings
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
        event_date: date | None,
        name_prop: str,
        date_prop: str,
        recording_prop: str = DEFAULT_RECORDING_PROP,
        project_prop: str = "",
        project_prop_type: str = "",
        contacts_prop: str = "TBD",
    ) -> list[NotionPage]:
        del event_date
        key = (
            database_id,
            name_prop,
            date_prop,
            recording_prop,
            contacts_prop,
            project_prop,
            project_prop_type,
        )
        source_id, was_cached = await self._resolve_source(key)
        self._trace(
            "notion.query.start",
            database_id=database_id,
            data_source_id=source_id,
            source_cache_hit=was_cached,
            candidate_name=candidate_name,
            name_property=name_prop,
            date_property=date_prop,
            recording_property=recording_prop,
        )
        response = await self._query_source(source_id, candidate_name, name_prop, recording_prop)
        if response.status_code == 404 and was_cached:
            self._invalidate(key, source_id)
            source_id, _ = await self._resolve_source(key)
            response = await self._query_source(
                source_id, candidate_name, name_prop, recording_prop
            )
        self._raise_query_error(response)
        payload = self._json_object(response, "query")
        results = payload.get("results")
        if not isinstance(results, list):
            raise NotionMalformedResponseError("Notion query response has invalid results")
        pages: list[NotionPage] = []
        relation_cache: dict[str, NotionRelationChoice] = {}
        for item in results[:10]:
            page = self._parse_page(
                item, name_prop, date_prop, contacts_prop, project_prop, recording_prop
            )
            if page.recording_present:
                continue
            relation_ids = self._project_relation_ids(item, project_prop)
            relations: list[NotionRelationChoice] = []
            for relation_id in relation_ids:
                relation = relation_cache.get(relation_id)
                if relation is None:
                    relation = await self._retrieve_related_page(relation_id)
                    relation_cache[relation_id] = relation
                relations.append(relation)
            if len(relations) == 1:
                page = replace(
                    page,
                    project_or_spot=relations[0].title,
                    spots=tuple(relations),
                )
            elif len(relations) > 1:
                page = replace(page, project_or_spot=None, spots=tuple(relations))
            pages.append(page)
        self._trace(
            "notion.query.result",
            database_id=database_id,
            data_source_id=source_id,
            result_count=len(pages),
            pages=[{"id": page.id, "title": page.title, "url": page.url} for page in pages],
        )
        return pages

    async def resolve_reassignment_targets(
        self,
        database_id: str,
        hint: str,
        *,
        name_prop: str,
        date_prop: str,
        recording_prop: str,
        contacts_prop: str,
        project_prop: str,
        project_prop_type: str,
    ) -> list[NotionPage]:
        """Resolve a URL/name hint only in a configured schema-verified database."""
        key = (
            database_id,
            name_prop,
            date_prop,
            recording_prop,
            contacts_prop,
            project_prop,
            project_prop_type,
        )
        source_id, _ = await self._resolve_source(key)
        canonical_id = _canonical_notion_page_id(hint)
        if canonical_id is not None:
            page = await self._retrieve_reassignment_page(
                canonical_id,
                source_id,
                database_id,
                name_prop,
                date_prop,
                contacts_prop,
                project_prop,
                recording_prop,
            )
            # Page URL is only a lookup hint; configured-source schema validation happens above.
            # The schema cache above still proves the configured source before this lookup.
            return [page]
        response = await self._query_source_any_recording(source_id, hint, name_prop)
        self._raise_query_error(response)
        payload = self._json_object(response, "reassignment query")
        items = payload.get("results")
        if not isinstance(items, list):
            raise NotionMalformedResponseError("Notion reassignment query has invalid results")
        pages = [
            self._parse_page(
                item, name_prop, date_prop, contacts_prop, project_prop, recording_prop
            )
            for item in items[:10]
        ]
        return [page for page in pages if _hint_matches_page(hint, page)]

    async def _retrieve_reassignment_page(
        self,
        page_id: str,
        source_id: str,
        database_id: str,
        name_prop: str,
        date_prop: str,
        contacts_prop: str,
        project_prop: str,
        recording_prop: str,
    ) -> NotionPage:
        try:
            response = await self._client.get(
                f"{NOTION_API_BASE}/pages/{page_id}", headers=self._headers
            )
        except httpx.RequestError:
            raise NotionQueryError("Notion page retrieval transport failed") from None
        self._raise_query_error(response)
        payload = self._json_object(response, "reassignment page")
        parent = payload.get("parent")
        parent_id = (
            parent.get("data_source_id") or parent.get("database_id")
            if isinstance(parent, dict)
            else None
        )
        if parent_id not in {source_id, database_id}:
            raise NotionForbiddenError("Notion reassignment page is outside configured database")
        return self._parse_page(
            payload,
            name_prop,
            date_prop,
            contacts_prop,
            project_prop,
            recording_prop,
        )

    async def update_page_interview(
        self,
        page_id: str,
        *,
        date_prop: str,
        recording_prop: str,
        event_date: date,
        url: str,
        filename: str,
    ) -> None:
        self._trace(
            "notion.page_update.start",
            page_id=page_id,
            date_property=date_prop,
            recording_property=recording_prop,
            filename=filename,
            external_url=safe_url(url),
        )
        try:
            response = await self._client.patch(
                f"{NOTION_API_BASE}/pages/{page_id}",
                headers=self._headers,
                json={
                    "properties": {
                        date_prop: {"date": {"start": event_date.isoformat()}},
                        recording_prop: {
                            "files": [
                                {
                                    "name": filename,
                                    "external": {"url": url},
                                }
                            ]
                        },
                    }
                },
            )
        except httpx.RequestError:
            self._trace(
                "notion.page_update.failure",
                page_id=page_id,
                date_property=date_prop,
                recording_property=recording_prop,
                error_type="transport",
            )
            raise NotionUpdateError("Notion page update transport failed") from None
        self._raise_common(response)
        if response.is_error:
            self._trace(
                "notion.page_update.failure",
                page_id=page_id,
                date_property=date_prop,
                recording_property=recording_prop,
                status_code=response.status_code,
                response_body=_response_excerpt(response.text),
            )
            raise NotionUpdateError(f"Notion page update failed with HTTP {response.status_code}")
        self._trace(
            "notion.page_update.success",
            page_id=page_id,
            date_property=date_prop,
            recording_property=recording_prop,
        )

    async def get_recording_field(self, page_id: str, recording_prop: str) -> dict[str, object]:
        """Return the exact configured files field after Notion page retrieval."""
        try:
            response = await self._client.get(
                f"{NOTION_API_BASE}/pages/{page_id}", headers=self._headers
            )
        except httpx.RequestError:
            raise NotionQueryError("Notion page retrieval transport failed") from None
        self._raise_common(response)
        if response.is_error:
            raise NotionQueryError(f"Notion page retrieval failed with HTTP {response.status_code}")
        payload = self._json_object(response, "page retrieval")
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            raise NotionMalformedResponseError("Notion page properties are malformed")
        field = properties.get(recording_prop)
        if not isinstance(field, dict) or field.get("type") != "files":
            raise NotionMalformedResponseError("Notion recording field is malformed")
        files = field.get("files")
        if not isinstance(files, list):
            raise NotionMalformedResponseError("Notion recording files field is malformed")
        return {"page_id": page_id, "files": files}

    async def replace_recording_link(
        self, page_id: str, *, recording_prop: str, filename: str, url: str
    ) -> None:
        await self._write_recording_files(
            page_id,
            recording_prop=recording_prop,
            files=[{"name": filename, "external": {"url": url}}],
        )

    async def clear_recording_link(self, page_id: str, *, recording_prop: str) -> None:
        await self._write_recording_files(page_id, recording_prop=recording_prop, files=[])

    async def _write_recording_files(
        self, page_id: str, *, recording_prop: str, files: list[dict[str, object]]
    ) -> None:
        try:
            response = await self._client.patch(
                f"{NOTION_API_BASE}/pages/{page_id}",
                headers=self._headers,
                json={"properties": {recording_prop: {"files": files}}},
            )
        except httpx.RequestError:
            raise NotionUpdateError("Notion recording update transport failed") from None
        self._raise_common(response)
        if response.is_error:
            raise NotionUpdateError(
                f"Notion recording update failed with HTTP {response.status_code}"
            )

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
        (
            database_id,
            name_prop,
            date_prop,
            recording_prop,
            contacts_prop,
            project_prop,
            project_prop_type,
        ) = key
        database = await self._retrieve_database(database_id)
        selected = await self._select_compatible_schema(
            database,
            name_prop,
            date_prop,
            recording_prop,
            contacts_prop,
            project_prop,
            project_prop_type,
        )
        self._trace_source_selection(database_id, database, selected.id)
        return selected.id

    async def inspect_database(
        self,
        database_id: str,
        name_prop: str,
        date_prop: str,
        recording_prop: str,
        project_prop: str = "",
        project_prop_type: str = "",
        contacts_prop: str = "TBD",
    ) -> NotionDatabaseInspection:
        database = await self._retrieve_database(database_id)
        selected = await self._select_compatible_schema(
            database,
            name_prop,
            date_prop,
            recording_prop,
            contacts_prop,
            project_prop,
            project_prop_type,
        )
        self._trace_source_selection(database_id, database, selected.id)
        return NotionDatabaseInspection(
            database_id=database_id,
            title=self._database_title(database),
            schema=selected,
        )

    async def preflight_database(
        self,
        database_id: str,
        synthetic_page_id: str,
        name_prop: str,
        date_prop: str,
        recording_prop: str,
        project_prop: str = "",
        project_prop_type: str = "",
        contacts_prop: str = "TBD",
    ) -> NotionDatabaseInspection:
        inspection = await self.inspect_database(
            database_id,
            name_prop,
            date_prop,
            recording_prop,
            project_prop,
            project_prop_type,
            contacts_prop,
        )
        try:
            response = await self._client.post(
                f"{NOTION_API_BASE}/data_sources/{inspection.schema.id}/query",
                headers=self._headers,
                json={"page_size": 100},
            )
        except httpx.RequestError:
            raise NotionQueryError("Notion synthetic-row query transport failed") from None
        self._raise_query_error(response)
        payload = self._json_object(response, "synthetic-row query")
        results = payload.get("results")
        if not isinstance(results, list):
            raise NotionMalformedResponseError("Notion synthetic-row query has invalid results")
        expected = synthetic_page_id.replace("-", "").casefold()
        selected = next(
            (
                item
                for item in results
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item["id"].replace("-", "").casefold() == expected
            ),
            None,
        )
        if selected is None:
            raise NotionQueryError("Selected synthetic Notion row was not returned by query")
        properties = selected.get("properties")
        if not isinstance(properties, dict):
            raise NotionMalformedResponseError(
                "Selected synthetic Notion row has malformed properties"
            )
        self._formula_emails(properties.get(contacts_prop))
        return inspection

    async def _retrieve_database(self, database_id: str) -> dict[str, Any]:
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
        return self._json_object(response, "database discovery")

    async def _select_compatible_schema(
        self,
        database: dict[str, Any],
        name_prop: str,
        date_prop: str,
        recording_prop: str,
        contacts_prop: str,
        project_prop: str,
        project_prop_type: str,
    ) -> NotionDataSourceSchema:
        sources = self._parse_sources(database)
        compatible: list[NotionDataSourceSchema] = []
        for source in sources:
            schema = await self._retrieve_schema(source.id)
            if schema.is_compatible(
                name_prop,
                date_prop,
                recording_prop,
                contacts_prop,
                project_prop,
                project_prop_type,
            ):
                compatible.append(schema)
        if not compatible:
            raise NotionSchemaError("No Notion data source has the required schema")
        if len(compatible) > 1:
            raise NotionSourceAmbiguityError(
                "Multiple Notion data sources have the required schema"
            )
        return compatible[0]

    def _trace_source_selection(
        self, database_id: str, database: dict[str, Any], source_id: str
    ) -> None:
        self._trace(
            "notion.source_selected",
            database_id=database_id,
            discovered_source_count=len(self._parse_sources(database)),
            compatible_source_count=1,
            data_source_id=source_id,
        )

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

    async def _retrieve_related_page(self, page_id: str) -> NotionRelationChoice:
        try:
            response = await self._client.get(
                f"{NOTION_API_BASE}/pages/{page_id}", headers=self._headers
            )
        except httpx.RequestError:
            raise NotionQueryError("Notion related page retrieval failed") from None
        self._raise_common(response)
        if response.is_error:
            raise NotionQueryError(
                f"Notion related page retrieval failed with HTTP {response.status_code}"
            )
        payload = self._json_object(response, "related page retrieval")
        properties = payload.get("properties")
        if not isinstance(properties, dict):
            raise NotionMalformedResponseError("Notion related page properties are malformed")
        title = next(
            (
                self._plain_text(value).strip()
                for value in properties.values()
                if isinstance(value, dict) and isinstance(value.get("title"), list)
            ),
            "",
        )
        if not title:
            raise NotionMalformedResponseError("Notion related page has no title")
        page_url = payload.get("url")
        if not isinstance(page_url, str) or not page_url:
            raise NotionMalformedResponseError("Notion related page has no URL")
        return NotionRelationChoice(id=page_id, title=title, url=page_url)

    async def _query_source(
        self,
        source_id: str,
        candidate_name: str,
        name_prop: str,
        recording_prop: str,
    ) -> httpx.Response:
        try:
            return await self._client.post(
                f"{NOTION_API_BASE}/data_sources/{source_id}/query",
                headers=self._headers,
                json={
                    "filter": {
                        "and": [
                            {"property": name_prop, "title": {"contains": candidate_name}},
                            {"property": recording_prop, "files": {"is_empty": True}},
                        ]
                    },
                    "page_size": 10,
                },
            )
        except httpx.RequestError:
            raise NotionQueryError("Notion query transport failed") from None

    async def _query_source_any_recording(
        self, source_id: str, candidate_name: str, name_prop: str
    ) -> httpx.Response:
        try:
            return await self._client.post(
                f"{NOTION_API_BASE}/data_sources/{source_id}/query",
                headers=self._headers,
                json={
                    "filter": {"property": name_prop, "title": {"contains": candidate_name}},
                    "page_size": 10,
                },
            )
        except httpx.RequestError:
            raise NotionQueryError("Notion reassignment query transport failed") from None

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

    @staticmethod
    def _database_title(payload: dict[str, Any]) -> str:
        entries = payload.get("title")
        if not isinstance(entries, list):
            raise NotionMalformedResponseError("Notion database response has invalid title")
        title = "".join(
            str(entry.get("plain_text", "")) for entry in entries if isinstance(entry, dict)
        ).strip()
        if not title:
            raise NotionMalformedResponseError("Notion database response has empty title")
        return title

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

    def _trace(self, event: str, **fields: object) -> None:
        if self._settings is not None:
            trace(self._settings, event, **fields)

    @staticmethod
    def _parse_page(
        item: Any,
        name_prop: str,
        date_prop: str,
        contacts_prop: str,
        project_prop: str = "",
        recording_prop: str = DEFAULT_RECORDING_PROP,
    ) -> NotionPage:
        if not isinstance(item, dict):
            raise NotionMalformedResponseError("Notion page payload must be an object")
        page_id = item.get("id")
        page_url = item.get("url")
        properties = item.get("properties")
        if not isinstance(page_id, str) or not isinstance(page_url, str):
            raise NotionMalformedResponseError("Notion page identity is malformed")
        if not isinstance(properties, dict):
            raise NotionMalformedResponseError("Notion page properties are malformed")
        emails = NotionClient._formula_emails(properties.get(contacts_prop))
        return NotionPage(
            id=page_id,
            url=page_url,
            title=NotionClient._plain_text(properties.get(name_prop)),
            date_str=NotionClient._date_value(properties.get(date_prop)),
            email=emails[0] if len(emails) == 1 else None,
            emails=emails,
            project_or_spot=(
                NotionClient._plain_text(properties.get(project_prop)) if project_prop else None
            ),
            recording_present=NotionClient._files_present(properties.get(recording_prop)),
        )

    @staticmethod
    def _project_relation_ids(item: Any, project_prop: str) -> list[str]:
        if not project_prop or not isinstance(item, dict):
            return []
        properties = item.get("properties")
        if not isinstance(properties, dict):
            return []
        value = properties.get(project_prop)
        if not isinstance(value, dict) or "relation" not in value:
            return []
        relations = value.get("relation")
        if not isinstance(relations, list):
            raise NotionMalformedResponseError("Notion project relation is malformed")
        if value.get("has_more") is True:
            raise NotionMalformedResponseError("Notion project relation is incomplete")
        if len(relations) > MAX_SPOT_CHOICES:
            raise NotionMalformedResponseError("Notion project relation exceeds bounded choices")
        relation_ids: list[str] = []
        for relation in relations:
            if (
                not isinstance(relation, dict)
                or not isinstance(relation.get("id"), str)
                or not relation["id"]
            ):
                raise NotionMalformedResponseError("Notion project relation is malformed")
            relation_ids.append(relation["id"])
        return relation_ids

    @staticmethod
    def _formula_emails(value: Any) -> tuple[str, ...]:
        if not isinstance(value, dict) or value.get("type") != "formula":
            raise NotionMalformedResponseError("Notion contacts formula is malformed")
        formula = value.get("formula")
        if not isinstance(formula, dict) or formula.get("type") != "string":
            raise NotionMalformedResponseError("Notion contacts formula shape is unsupported")
        rendered = formula.get("string")
        if rendered is None:
            return ()
        if not isinstance(rendered, str):
            raise NotionMalformedResponseError("Notion contacts formula string is malformed")
        emails: list[str] = []
        for candidate in _EMAIL_CANDIDATE.findall(rendered):
            local, domain = candidate.rsplit("@", 1)
            if (
                len(candidate) > 254
                or len(local) > 64
                or local.startswith(".")
                or local.endswith(".")
                or ".." in local
            ):
                continue
            normalized = f"{local}@{domain}".casefold()
            if normalized not in emails:
                emails.append(normalized)
        return tuple(emails)

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

    @staticmethod
    def _files_present(value: Any) -> bool:
        if not isinstance(value, dict) or value.get("type") != "files":
            raise NotionMalformedResponseError("Notion recording field is malformed")
        files = value.get("files")
        if not isinstance(files, list):
            raise NotionMalformedResponseError("Notion recording files field is malformed")
        return bool(files)


def _response_excerpt(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) > _TRACE_BODY_LIMIT:
        return normalized[:_TRACE_BODY_LIMIT]
    return normalized


def _hint_matches_page(hint: str, page: NotionPage) -> bool:
    normalized = " ".join(hint.casefold().split())
    if normalized == " ".join(page.title.casefold().split()):
        return True
    compact = re.sub(r"[^0-9a-f]", "", hint.casefold())
    return len(compact) == 32 and compact in {
        re.sub(r"[^0-9a-f]", "", page.id.casefold()),
        re.sub(r"[^0-9a-f]", "", page.url.casefold()),
    }


def _canonical_notion_page_id(value: str) -> str | None:
    compact = re.sub(r"[^0-9a-f]", "", value.casefold())
    if len(compact) != 32:
        return None
    return f"{compact[:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:]}"
