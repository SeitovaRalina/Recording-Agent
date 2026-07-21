from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.services.storage import StreamingUnsupportedError
from app.services.transfer import TransferError, TransferService


class FakeStorage:
    def __init__(
        self, *, fallback: bool = False, fail: bool = False, fail_share: bool = False
    ) -> None:
        self.fallback = fallback
        self.fail = fail
        self.fail_share = fail_share
        self.uploads = 0
        self.content = b""
        self.folder = ""

    async def ensure_folder(self, path: str) -> None:
        self.folder = path

    async def upload(
        self,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
        size: int | None,
        **identity: str,
    ) -> str:
        del size, identity
        self.uploads += 1
        if self.fail:
            raise RuntimeError("upload failed")
        if self.fallback and self.uploads == 1:
            raise StreamingUnsupportedError("chunked unsupported")
        self.content = b"".join([chunk async for chunk in stream])
        return f"{folder}/{filename}"

    async def create_share_link(self, path: str) -> str:
        if self.fail_share:
            raise RuntimeError("share failed")
        return f"https://share{path}"


def recording() -> Recording:
    return Recording(
        disk_file_id="file",
        disk_path="disk:/video.webm",
        disk_filename="video.webm",
        disk_owner_email="owner@example.com",
        calendar_dtstart=datetime(2026, 7, 16, tzinfo=UTC),
    )


def recruiter() -> RecruiterConfig:
    return RecruiterConfig(
        email="owner@example.com",
        notion_database_id="db",
        synology_base_folder="/base",
    )


def download_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "download":
            return httpx.Response(
                302,
                headers={"Location": "https://storage/video"},
                request=request,
            )
        if request.url.host == "storage":
            return httpx.Response(
                200,
                content=b"video",
                headers={"Content-Length": "5"},
                request=request,
            )
        return httpx.Response(404, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
@pytest.mark.parametrize("candidate", ["Ivan", 'Iv/an\\:*?"<>|'])
async def test_transfer_streams_and_sanitizes_path(candidate: str, session: AsyncSession) -> None:
    disk = AsyncMock()
    disk._request.return_value = httpx.Response(200, json={"href": "https://download"})
    storage = FakeStorage()
    async with download_client() as http:
        service = TransferService(disk, storage, http)
        result = await service.transfer(recording(), recruiter(), candidate, session)
    assert storage.content == b"video"
    assert (
        result.folder_path
        == f"/base/2026-07-16/{'Ivan' if candidate == 'Ivan' else 'Iv_an________'}"
    )
    assert await service.create_share_link(result.file_path) == f"https://share{result.file_path}"


@pytest.mark.anyio
async def test_temp_fallback_deletes_temp(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    temp_root = Path("virtual-temp")
    file_content = bytearray()
    removed: list[Path] = []

    class FakeAsyncFile:
        def __init__(self, mode: str) -> None:
            self.mode = mode
            self.read_complete = False

        async def __aenter__(self) -> FakeAsyncFile:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def write(self, chunk: bytes) -> int:
            file_content.extend(chunk)
            return len(chunk)

        async def read(self, size: int) -> bytes:
            del size
            if self.read_complete:
                return b""
            self.read_complete = True
            return bytes(file_content)

    async def fake_open_file(_path: object, mode: str) -> FakeAsyncFile:
        return FakeAsyncFile(mode)

    async def fake_run_sync(func: Callable[..., Any], *args: object, **_kwargs: object) -> object:
        if func.__name__ == "stat":
            return SimpleNamespace(st_size=len(file_content))
        if func.__name__ == "rmtree":
            removed.append(args[0])  # type: ignore[arg-type]
        return None

    monkeypatch.setattr("app.services.transfer.TEMP_ROOT", temp_root)
    monkeypatch.setattr("app.services.transfer.anyio.open_file", fake_open_file)
    monkeypatch.setattr("app.services.transfer.anyio.to_thread.run_sync", fake_run_sync)
    disk = AsyncMock()
    disk._request.return_value = httpx.Response(200, json={"href": "https://download"})
    storage = FakeStorage(fallback=True)
    async with download_client() as http:
        await TransferService(disk, storage, http).transfer(
            recording(), recruiter(), "Ivan", session
        )
    assert storage.uploads == 2
    assert storage.content == b"video"
    assert len(removed) == 1
    assert removed[0].parent == temp_root


@pytest.mark.anyio
async def test_upload_failure_reports_step(session: AsyncSession) -> None:
    disk = AsyncMock()
    disk._request.return_value = httpx.Response(200, json={"href": "https://download"})
    async with download_client() as http:
        with pytest.raises(TransferError, match="upload") as raised:
            await TransferService(disk, FakeStorage(fail=True), http).transfer(
                recording(), recruiter(), "Ivan", session
            )
    assert raised.value.step == "upload"


@pytest.mark.anyio
async def test_share_failure_reports_separate_step(session: AsyncSession) -> None:
    disk = AsyncMock()
    storage = FakeStorage(fail_share=True)
    async with download_client() as http:
        service = TransferService(disk, storage, http)
        with pytest.raises(TransferError, match="share_link") as raised:
            await service.create_share_link("/base/video.webm")
    assert raised.value.step == "share_link"
