from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording
from app.tools.disk import DISK_API_BASE, DiskScanner


@pytest.mark.anyio
async def test_list_new_paginates_filters_and_skips_existing(session: AsyncSession) -> None:
    existing = Recording(
        disk_file_id="id-0",
        disk_path="disk:/Записи Телемоста/0.webm",
        disk_filename="0.webm",
        disk_owner_email="recruiter@example.com",
    )
    session.add(existing)
    await session.commit()
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    first = [
        {
            "resource_id": f"id-{index}",
            "path": f"disk:/Записи Телемоста/{index}.webm",
        }
        for index in range(100)
    ]
    second = [
        {"resource_id": "new", "path": "disk:/Записи Телемоста/new.webm"},
        {"resource_id": "photo", "path": "disk:/Photos/photo.webm"},
    ]
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.get(f"{DISK_API_BASE}/resources/files").mock(
                side_effect=[
                    httpx.Response(200, json={"items": first}),
                    httpx.Response(200, json={"items": second}),
                ]
            )
            result = await DiskScanner(token_manager, session, client).list_new(
                "recruiter@example.com"
            )
    assert len(result) == 100
    assert all(item["resource_id"] != "id-0" for item in result)
    assert route.call_count == 2


@pytest.mark.anyio
async def test_request_retries_401_once(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "old"
    token_manager.refresh_token.return_value = "new"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.get("https://disk.test/item").mock(
                side_effect=[httpx.Response(401), httpx.Response(200)]
            )
            response = await DiskScanner(token_manager, session, client)._request(
                "GET", "https://disk.test/item", "recruiter@example.com"
            )
    assert response.status_code == 200
    assert route.call_count == 2
    token_manager.refresh_token.assert_awaited_once()


@pytest.mark.anyio
async def test_get_metadata_returns_all_recording_disk_fields(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    payload = {
        "resource_id": "disk-id",
        "path": "disk:/Записи Телемоста/a.webm",
        "name": "a.webm",
        "created": "2026-07-14T10:00:00+00:00",
        "modified": "2026-07-14T10:05:00+00:00",
        "size": 123,
        "mime_type": "video/webm",
        "md5": "abc",
    }
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(200, json=payload)
            )
            result = await DiskScanner(token_manager, session, client).get_metadata(
                str(payload["path"]), "recruiter@example.com"
            )
    assert result == {
        "disk_file_id": "disk-id",
        "disk_path": payload["path"],
        "disk_filename": "a.webm",
        "disk_owner_email": "recruiter@example.com",
        "disk_created_at": "2026-07-14T10:00:00+00:00",
        "disk_modified_at": "2026-07-14T10:05:00+00:00",
        "disk_size_bytes": 123,
        "disk_mime_type": "video/webm",
        "disk_md5": "abc",
    }


@pytest.mark.anyio
async def test_mark_processed_sync(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.post(f"{DISK_API_BASE}/resources/move").mock(
                return_value=httpx.Response(201)
            )
            await DiskScanner(token_manager, session, client).mark_processed(
                "disk:/Записи Телемоста/a.webm", "a.webm", "recruiter@example.com"
            )
    assert route.called


@pytest.mark.anyio
async def test_mark_processed_polls_async_operation(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    monkeypatch.setattr("app.tools.disk.asyncio.sleep", AsyncMock())
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.post(f"{DISK_API_BASE}/resources/move").mock(
                return_value=httpx.Response(202, json={"href": f"{DISK_API_BASE}/operations/op-1"})
            )
            operation = respx.get(f"{DISK_API_BASE}/operations/op-1").mock(
                side_effect=[
                    httpx.Response(200, json={"status": "in-progress"}),
                    httpx.Response(200, json={"status": "success"}),
                ]
            )
            await DiskScanner(token_manager, session, client).mark_processed(
                "disk:/Записи Телемоста/a.webm", "a.webm", "recruiter@example.com"
            )
    assert operation.call_count == 2


@pytest.mark.anyio
async def test_mark_processed_times_out(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    sleep = AsyncMock()
    monkeypatch.setattr("app.tools.disk.asyncio.sleep", sleep)
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.post(f"{DISK_API_BASE}/resources/move").mock(
                return_value=httpx.Response(
                    202, json={"href": f"{DISK_API_BASE}/operations/op-timeout"}
                )
            )
            respx.get(f"{DISK_API_BASE}/operations/op-timeout").mock(
                return_value=httpx.Response(200, json={"status": "in-progress"})
            )
            with pytest.raises(TimeoutError):
                await DiskScanner(token_manager, session, client).mark_processed(
                    "disk:/Записи Телемоста/a.webm", "a.webm", "recruiter@example.com"
                )
    assert sleep.await_count == 60
