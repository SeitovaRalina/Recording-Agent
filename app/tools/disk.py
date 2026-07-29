import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.recording import Recording
from app.services.yandex_token_manager import YandexTokenManager

DISK_API_BASE = "https://cloud-api.yandex.net/v1/disk"
TELEMOST_ROOT = "disk:/Записи Телемоста/"
PROCESSED_PROPERTY = "processed"
PROCESSED_AT_PROPERTY = "processed_at"
APPROVAL_MAX_AGE = timedelta(minutes=5)


@dataclass(frozen=True)
class PermanentDeleteApproval:
    approved_by: str
    approved_at: datetime
    nonce: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DiskScanner:
    def __init__(
        self,
        token_manager: YandexTokenManager,
        session_provider: AsyncSession | async_sessionmaker[AsyncSession],
        http_client: httpx.AsyncClient | None = None,
        retention_days: int = 7,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._token_manager = token_manager
        self._session_provider = session_provider
        self._http_client = http_client
        self._retention_days = retention_days
        self._clock = clock or _utc_now
        self._consumed_approval_nonces: set[str] = set()

    @asynccontextmanager
    async def _session_scope(self) -> AsyncIterator[AsyncSession]:
        if isinstance(self._session_provider, AsyncSession):
            yield self._session_provider
            return
        async with self._session_provider() as session:
            yield session

    async def _request(
        self,
        method: str,
        url: str,
        recruiter_email: str,
        **kwargs: Any,
    ) -> httpx.Response:
        token = await self._token_manager.get_access_token(recruiter_email)
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"OAuth {token}"

        async def send() -> httpx.Response:
            if self._http_client is not None:
                return await self._http_client.request(method, url, headers=headers, **kwargs)
            async with httpx.AsyncClient() as client:
                return await client.request(method, url, headers=headers, **kwargs)

        response = await send()
        if response.status_code == 401:
            token = await self._token_manager.refresh_token(
                recruiter_email, stale_access_token=token
            )
            headers["Authorization"] = f"OAuth {token}"
            response = await send()
        response.raise_for_status()
        return response

    async def _list_video_files(self, recruiter_email: str) -> list[dict[str, Any]]:
        offset = 0
        candidates: list[dict[str, Any]] = []
        while True:
            response = await self._request(
                "GET",
                f"{DISK_API_BASE}/resources/files",
                recruiter_email,
                params={"media_type": "video", "limit": 100, "offset": offset},
            )
            payload = response.json()
            items = payload.get("items")
            if items is None:
                items = payload.get("_embedded", {}).get("items", [])
            page = [item for item in items if isinstance(item, dict)]
            candidates.extend(
                item for item in page if str(item.get("path", "")).startswith(TELEMOST_ROOT)
            )
            if len(page) < 100:
                return candidates
            offset += len(page)

    async def list_new(self, recruiter_email: str) -> list[dict[str, Any]]:
        candidates = await self._list_video_files(recruiter_email)
        file_ids = [self._file_id(item) for item in candidates]
        if not file_ids:
            return []
        async with self._session_scope() as session:
            existing = set(
                (
                    await session.scalars(
                        select(Recording.disk_file_id).where(Recording.disk_file_id.in_(file_ids))
                    )
                ).all()
            )
        database_new = [item for item in candidates if self._file_id(item) not in existing]

        unprocessed: list[dict[str, Any]] = []
        for item in database_new:
            path = str(item["path"])
            resource = await self._get_resource(path, recruiter_email)
            properties = self._custom_properties(resource)
            if str(properties.get(PROCESSED_PROPERTY, "")).lower() == "true":
                if not self._has_valid_processed_marker(properties):
                    repaired_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                    await self._patch_processed_properties(path, recruiter_email, repaired_at)
                continue
            unprocessed.append(item)
        return unprocessed

    async def _get_resource(self, path: str, recruiter_email: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"{DISK_API_BASE}/resources",
            recruiter_email,
            params={"path": path},
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Yandex Disk resource response must be an object")
        return payload

    async def get_metadata(self, path: str, recruiter_email: str) -> dict[str, Any]:
        item = await self._get_resource(path, recruiter_email)
        return {
            "disk_file_id": self._file_id(item),
            "disk_path": item.get("path", path),
            "disk_filename": item.get("name") or path.rsplit("/", 1)[-1],
            "disk_owner_email": recruiter_email,
            "disk_created_at": item.get("created"),
            "disk_modified_at": item.get("modified"),
            "disk_size_bytes": item.get("size"),
            "disk_mime_type": item.get("mime_type"),
            "disk_md5": item.get("md5"),
        }

    async def mark_processed(self, path: str, recruiter_email: str) -> None:
        resource = await self._get_resource(path, recruiter_email)
        properties = self._custom_properties(resource)
        if self._has_valid_processed_marker(properties):
            return
        processed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        await self._patch_processed_properties(path, recruiter_email, processed_at)

    async def move_to_trash(self, path: str, recruiter_email: str) -> None:
        """Move one explicit source to Yandex Trash; permanent deletion is impossible here."""
        if not path.startswith(TELEMOST_ROOT):
            raise PermissionError("Cleanup source is outside the Telemost root")
        response = await self._request(
            "DELETE",
            f"{DISK_API_BASE}/resources",
            recruiter_email,
            params={"path": path, "permanently": "false"},
        )
        await self._await_operation(response, recruiter_email)

    async def _patch_processed_properties(
        self, path: str, recruiter_email: str, processed_at: str
    ) -> None:
        await self._request(
            "PATCH",
            f"{DISK_API_BASE}/resources",
            recruiter_email,
            params={"path": path},
            json={
                "custom_properties": {
                    PROCESSED_PROPERTY: "true",
                    PROCESSED_AT_PROPERTY: processed_at,
                }
            },
        )

    async def delete_expired(
        self,
        recruiter_email: str,
        *,
        now: datetime | None = None,
    ) -> list[str]:
        current_time = now or datetime.now(UTC)
        current_time = (
            current_time.replace(tzinfo=UTC)
            if current_time.tzinfo is None
            else current_time.astimezone(UTC)
        )
        cutoff = current_time - timedelta(days=self._retention_days)
        deleted_paths: list[str] = []
        for item in await self._list_video_files(recruiter_email):
            path = str(item["path"])
            resource = await self._get_resource(path, recruiter_email)
            properties = self._custom_properties(resource)
            if str(properties.get(PROCESSED_PROPERTY, "")).lower() != "true":
                continue
            processed_at = self._parse_datetime(properties.get(PROCESSED_AT_PROPERTY))
            if processed_at is None:
                repaired_at = current_time.isoformat().replace("+00:00", "Z")
                await self._patch_processed_properties(path, recruiter_email, repaired_at)
                continue
            if processed_at > cutoff:
                continue
            soft_delete = await self._request(
                "DELETE",
                f"{DISK_API_BASE}/resources",
                recruiter_email,
                params={"path": path, "permanently": "false"},
            )
            await self._await_operation(soft_delete, recruiter_email)
            deleted_paths.append(path)
        return deleted_paths

    async def purge_expired_from_trash(
        self,
        recruiter_email: str,
        approval: PermanentDeleteApproval,
    ) -> list[str]:
        current_time = self._trusted_utc_now()
        self._consume_approval(approval, current_time)
        cutoff = current_time - timedelta(days=self._retention_days)
        purged_paths: list[str] = []
        for item in await self._list_trash_resources(recruiter_email):
            trash_path = str(item.get("path", ""))
            if not trash_path:
                continue
            resource = item
            if not item.get("origin_path") or not self._custom_properties(item):
                resource = await self._get_trash_resource(trash_path, recruiter_email)
            origin_path = str(resource.get("origin_path", ""))
            if not origin_path.startswith(TELEMOST_ROOT):
                continue
            properties = self._custom_properties(resource)
            if str(properties.get(PROCESSED_PROPERTY, "")).lower() != "true":
                continue
            processed_at = self._parse_datetime(properties.get(PROCESSED_AT_PROPERTY))
            if processed_at is None or processed_at > cutoff:
                continue
            response = await self._request(
                "DELETE",
                f"{DISK_API_BASE}/trash/resources",
                recruiter_email,
                params={"path": trash_path},
            )
            await self._await_operation(response, recruiter_email)
            purged_paths.append(trash_path)
        return purged_paths

    async def _list_trash_resources(self, recruiter_email: str) -> list[dict[str, Any]]:
        offset = 0
        resources: list[dict[str, Any]] = []
        while True:
            response = await self._request(
                "GET",
                f"{DISK_API_BASE}/trash/resources",
                recruiter_email,
                params={"limit": 100, "offset": offset},
            )
            payload = response.json()
            embedded = payload.get("_embedded", {}) if isinstance(payload, dict) else {}
            items = embedded.get("items", []) if isinstance(embedded, dict) else []
            page = [item for item in items if isinstance(item, dict)]
            resources.extend(page)
            if len(page) < 100:
                return resources
            offset += len(page)

    async def _get_trash_resource(self, path: str, recruiter_email: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"{DISK_API_BASE}/trash/resources",
            recruiter_email,
            params={"path": path},
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Yandex Disk trash resource response must be an object")
        return payload

    def _consume_approval(self, approval: PermanentDeleteApproval, current_time: datetime) -> None:
        if not isinstance(approval, PermanentDeleteApproval):
            raise PermissionError("Permanent deletion requires explicit per-run approval")
        if not approval.nonce.strip():
            raise PermissionError("Permanent deletion approval requires a nonce")
        if approval.nonce in self._consumed_approval_nonces:
            raise PermissionError("Permanent deletion approval was already consumed")
        approved_at = approval.approved_at
        if approved_at.tzinfo is None:
            raise PermissionError("Permanent deletion approval must be timezone-aware")
        approved_at = approved_at.astimezone(UTC)
        current_time = (
            current_time.replace(tzinfo=UTC)
            if current_time.tzinfo is None
            else current_time.astimezone(UTC)
        )
        if not approval.approved_by.strip():
            raise PermissionError("Permanent deletion approval requires an operator identity")
        if approved_at > current_time or current_time - approved_at > APPROVAL_MAX_AGE:
            raise PermissionError("Permanent deletion approval is not fresh")
        self._consumed_approval_nonces.add(approval.nonce)

    def _trusted_utc_now(self) -> datetime:
        current_time = self._clock()
        if current_time.tzinfo is None:
            raise RuntimeError("DiskScanner trusted clock must be timezone-aware")
        return current_time.astimezone(UTC)

    async def _await_operation(self, response: httpx.Response, recruiter_email: str) -> None:
        if response.status_code != 202:
            return
        operation_url = str(response.json().get("href", ""))
        if not operation_url:
            raise ValueError("Yandex Disk async delete returned no operation URL")
        for _ in range(60):
            operation = await self._request("GET", operation_url, recruiter_email)
            status = operation.json().get("status")
            if status == "success":
                return
            if status == "failed":
                raise RuntimeError("Yandex Disk delete operation failed")
            await asyncio.sleep(2)
        raise TimeoutError("Yandex Disk delete did not complete within 120 seconds")

    @staticmethod
    def _custom_properties(item: dict[str, Any]) -> dict[str, Any]:
        value = item.get("custom_properties")
        return value if isinstance(value, dict) else {}

    @classmethod
    def _has_valid_processed_marker(cls, properties: dict[str, Any]) -> bool:
        return (
            str(properties.get(PROCESSED_PROPERTY, "")).lower() == "true"
            and cls._parse_datetime(properties.get(PROCESSED_AT_PROPERTY)) is not None
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @staticmethod
    def _file_id(item: dict[str, Any]) -> str:
        value = item.get("resource_id") or item.get("file_id") or item.get("md5")
        if not value:
            raise ValueError("Yandex Disk resource has no stable file id")
        return str(value)
