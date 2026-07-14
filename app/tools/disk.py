import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.recording import Recording
from app.services.yandex_token_manager import YandexTokenManager

DISK_API_BASE = "https://cloud-api.yandex.net/v1/disk"
TELEMOST_ROOT = "disk:/Записи Телемоста/"
PROCESSED_ROOT = f"{TELEMOST_ROOT}processed/"


class DiskScanner:
    def __init__(
        self,
        token_manager: YandexTokenManager,
        session_provider: AsyncSession | async_sessionmaker[AsyncSession],
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token_manager = token_manager
        self._session_provider = session_provider
        self._http_client = http_client

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

    async def list_new(self, recruiter_email: str) -> list[dict[str, Any]]:
        offset = 0
        candidates: list[dict[str, Any]] = []
        while True:
            response = await self._request(
                "GET",
                f"{DISK_API_BASE}/resources/files",
                recruiter_email,
                params={"media_type": "video", "limit": 100, "offset": offset},
            )
            items = response.json().get("items")
            if items is None:
                items = response.json().get("_embedded", {}).get("items", [])
            page = [item for item in items if isinstance(item, dict)]
            candidates.extend(
                item
                for item in page
                if str(item.get("path", "")).startswith(TELEMOST_ROOT)
                and not str(item.get("path", "")).startswith(PROCESSED_ROOT)
            )
            if len(page) < 100:
                break
            offset += len(page)

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
        return [item for item in candidates if self._file_id(item) not in existing]

    async def get_metadata(self, path: str, recruiter_email: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"{DISK_API_BASE}/resources",
            recruiter_email,
            params={"path": path},
        )
        item = response.json()
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

    async def mark_processed(self, path: str, filename: str, recruiter_email: str) -> None:
        destination = f"{PROCESSED_ROOT}{filename}"
        response = await self._request(
            "POST",
            f"{DISK_API_BASE}/resources/move",
            recruiter_email,
            params={"from": path, "path": destination},
        )
        if response.status_code == 201:
            return
        operation_url = str(response.json().get("href", ""))
        operation_id = operation_url.rstrip("/").rsplit("/", 1)[-1]
        if not operation_id:
            raise ValueError("Yandex Disk move returned no operation id")
        for _ in range(60):
            operation = await self._request(
                "GET",
                f"{DISK_API_BASE}/operations/{quote(operation_id, safe='')}",
                recruiter_email,
            )
            status = operation.json().get("status")
            if status == "success":
                return
            if status == "failed":
                raise RuntimeError("Yandex Disk move operation failed")
            await asyncio.sleep(2)
        raise TimeoutError("Yandex Disk move did not complete within 120 seconds")

    @staticmethod
    def _file_id(item: dict[str, Any]) -> str:
        value = item.get("resource_id") or item.get("file_id") or item.get("md5")
        if not value:
            raise ValueError("Yandex Disk resource has no stable file id")
        return str(value)
