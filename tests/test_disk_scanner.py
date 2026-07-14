from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording
from app.tools.disk import (
    DISK_API_BASE,
    PROCESSED_AT_PROPERTY,
    PROCESSED_PROPERTY,
    DiskScanner,
    PermanentDeleteApproval,
)

ROOT = "disk:/Записи Телемоста/"
EMAIL = "recruiter@example.com"


def recording(file_id: str) -> Recording:
    return Recording(
        disk_file_id=file_id,
        disk_path=f"{ROOT}{file_id}.webm",
        disk_filename=f"{file_id}.webm",
        disk_owner_email=EMAIL,
    )


@pytest.mark.anyio
async def test_list_new_checks_properties_only_after_database_filter(
    session: AsyncSession,
) -> None:
    session.add_all(recording(f"id-{index}") for index in range(100))
    await session.commit()
    first = [{"resource_id": f"id-{index}", "path": f"{ROOT}{index}.webm"} for index in range(100)]
    second = [
        {"resource_id": "new", "path": f"{ROOT}new.webm"},
        {"resource_id": "photo", "path": "disk:/Photos/photo.webm"},
    ]
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            list_route = respx.get(f"{DISK_API_BASE}/resources/files").mock(
                side_effect=[
                    httpx.Response(200, json={"items": first}),
                    httpx.Response(200, json={"items": second}),
                ]
            )
            metadata_route = respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(200, json={"custom_properties": {}})
            )
            result = await DiskScanner(token_manager, session, client).list_new(EMAIL)

    assert [item["resource_id"] for item in result] == ["new"]
    assert list_route.call_count == 2
    assert metadata_route.call_count == 1


@pytest.mark.anyio
async def test_list_new_excludes_processed_custom_property(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    items = [
        {"resource_id": "processed", "path": f"{ROOT}processed.webm"},
        {"resource_id": "incomplete", "path": f"{ROOT}incomplete.webm"},
        {"resource_id": "new", "path": f"{ROOT}new.webm"},
    ]
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get(f"{DISK_API_BASE}/resources/files").mock(
                return_value=httpx.Response(200, json={"items": items})
            )
            respx.get(f"{DISK_API_BASE}/resources").mock(
                side_effect=[
                    httpx.Response(
                        200,
                        json={
                            "custom_properties": {
                                PROCESSED_PROPERTY: "true",
                                PROCESSED_AT_PROPERTY: "2026-07-14T10:00:00Z",
                            }
                        },
                    ),
                    httpx.Response(
                        200,
                        json={
                            "custom_properties": {
                                PROCESSED_PROPERTY: "true",
                                PROCESSED_AT_PROPERTY: "invalid",
                            }
                        },
                    ),
                    httpx.Response(200, json={"custom_properties": {}}),
                ]
            )
            repair = respx.patch(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(200)
            )
            delete_route = respx.delete(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(204)
            )
            result = await DiskScanner(token_manager, session, client).list_new(EMAIL)
    assert [item["resource_id"] for item in result] == ["new"]
    assert repair.call_count == 1
    assert PROCESSED_AT_PROPERTY.encode() in repair.calls[0].request.content
    assert delete_route.call_count == 0


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
                "GET", "https://disk.test/item", EMAIL
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
        "path": f"{ROOT}a.webm",
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
                str(payload["path"]), EMAIL
            )
    assert result == {
        "disk_file_id": "disk-id",
        "disk_path": payload["path"],
        "disk_filename": "a.webm",
        "disk_owner_email": EMAIL,
        "disk_created_at": "2026-07-14T10:00:00+00:00",
        "disk_modified_at": "2026-07-14T10:05:00+00:00",
        "disk_size_bytes": 123,
        "disk_mime_type": "video/webm",
        "disk_md5": "abc",
    }


@pytest.mark.anyio
async def test_mark_processed_patches_properties(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            metadata = respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(200, json={"custom_properties": {}})
            )
            route = respx.patch(f"{DISK_API_BASE}/resources").mock(return_value=httpx.Response(200))
            await DiskScanner(token_manager, session, client).mark_processed(f"{ROOT}a.webm", EMAIL)
    payload = route.calls[0].request.content.decode()
    assert PROCESSED_PROPERTY in payload
    assert PROCESSED_AT_PROPERTY in payload
    assert '"true"' in payload
    assert metadata.call_count == 1


@pytest.mark.anyio
async def test_mark_processed_is_idempotent(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "custom_properties": {
                            PROCESSED_PROPERTY: "true",
                            PROCESSED_AT_PROPERTY: "2026-07-14T10:00:00Z",
                        }
                    },
                )
            )
            patch_route = respx.patch(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(200)
            )
            await DiskScanner(token_manager, session, client).mark_processed(f"{ROOT}a.webm", EMAIL)
    assert patch_route.call_count == 0


@pytest.mark.anyio
async def test_mark_processed_repairs_invalid_timestamp(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "custom_properties": {
                            PROCESSED_PROPERTY: "true",
                            PROCESSED_AT_PROPERTY: "invalid",
                        }
                    },
                )
            )
            patch_route = respx.patch(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(200)
            )
            await DiskScanner(token_manager, session, client).mark_processed(f"{ROOT}a.webm", EMAIL)
    assert patch_route.call_count == 1


@pytest.mark.anyio
async def test_cleanup_soft_deletes_but_gate_blocks_permanent_delete(
    session: AsyncSession,
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    old = datetime(2026, 7, 1, tzinfo=UTC)
    item = {"resource_id": "old", "path": f"{ROOT}old.webm"}
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get(f"{DISK_API_BASE}/resources/files").mock(
                return_value=httpx.Response(200, json={"items": [item]})
            )
            respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "custom_properties": {
                            PROCESSED_PROPERTY: "true",
                            PROCESSED_AT_PROPERTY: old.isoformat(),
                        }
                    },
                )
            )
            soft_delete = respx.delete(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(204)
            )
            permanent_delete = respx.delete(f"{DISK_API_BASE}/trash/resources").mock(
                return_value=httpx.Response(204)
            )
            deleted = await DiskScanner(token_manager, session, client).delete_expired(
                EMAIL,
                now=old + timedelta(days=8),
            )
    assert deleted == [item["path"]]
    assert soft_delete.call_count == 1
    assert soft_delete.calls[0].request.url.params["permanently"] == "false"
    assert permanent_delete.call_count == 0


@pytest.mark.anyio
async def test_soft_delete_then_approved_purge_uses_actual_trash_path(
    session: AsyncSession,
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    old = datetime(2026, 7, 1, tzinfo=UTC)
    item = {"resource_id": "old", "path": f"{ROOT}old.webm"}
    async with httpx.AsyncClient() as client:
        with respx.mock:
            live_list = respx.get(f"{DISK_API_BASE}/resources/files").mock(
                return_value=httpx.Response(200, json={"items": [item]})
            )
            respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "custom_properties": {
                            PROCESSED_PROPERTY: "true",
                            PROCESSED_AT_PROPERTY: old.isoformat(),
                        }
                    },
                )
            )
            soft_delete = respx.delete(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(204)
            )
            trash_list = respx.get(f"{DISK_API_BASE}/trash/resources").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "_embedded": {
                            "items": [
                                {
                                    "path": "trash:/actual-trash-id.webm",
                                    "origin_path": item["path"],
                                    "custom_properties": {
                                        PROCESSED_PROPERTY: "true",
                                        PROCESSED_AT_PROPERTY: old.isoformat(),
                                    },
                                }
                            ]
                        }
                    },
                )
            )
            permanent_delete = respx.delete(f"{DISK_API_BASE}/trash/resources").mock(
                return_value=httpx.Response(204)
            )
            purge_time = old + timedelta(days=8)
            scanner = DiskScanner(token_manager, session, client, clock=lambda: purge_time)
            await scanner.delete_expired(
                EMAIL,
                now=old + timedelta(days=8),
            )
            await scanner.purge_expired_from_trash(
                EMAIL,
                PermanentDeleteApproval(
                    approved_by="operator@example.com",
                    approved_at=purge_time,
                    nonce="approval-success",
                ),
            )
            with pytest.raises(PermissionError, match="already consumed"):
                await scanner.purge_expired_from_trash(
                    EMAIL,
                    PermanentDeleteApproval(
                        approved_by="operator@example.com",
                        approved_at=purge_time,
                        nonce="approval-success",
                    ),
                )
            delete_order = [
                call.request.url.path for call in respx.calls if call.request.method == "DELETE"
            ]
    assert live_list.call_count == soft_delete.call_count == trash_list.call_count == 1
    assert permanent_delete.call_count == 1
    assert permanent_delete.calls[0].request.url.params["path"] == "trash:/actual-trash-id.webm"
    assert delete_order == ["/v1/disk/resources", "/v1/disk/trash/resources"]


@pytest.mark.anyio
async def test_permanent_purge_rejects_stale_approval(session: AsyncSession) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    scanner = DiskScanner(AsyncMock(), session, clock=lambda: now)
    with pytest.raises(PermissionError, match="not fresh"):
        await scanner.purge_expired_from_trash(
            EMAIL,
            PermanentDeleteApproval("operator@example.com", now - timedelta(minutes=6), "stale"),
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("approval", "message"),
    [
        (
            PermanentDeleteApproval("", datetime(2026, 7, 14, tzinfo=UTC), "empty-operator"),
            "operator identity",
        ),
        (
            PermanentDeleteApproval("operator@example.com", datetime(2026, 7, 14), "naive"),
            "timezone-aware",
        ),
        (
            PermanentDeleteApproval(
                "operator@example.com",
                datetime(2026, 7, 14, 0, 0, 1, tzinfo=UTC),
                "future",
            ),
            "not fresh",
        ),
    ],
)
async def test_permanent_purge_rejects_invalid_approval_before_requests(
    session: AsyncSession,
    approval: PermanentDeleteApproval,
    message: str,
) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    token_manager = AsyncMock()
    scanner = DiskScanner(token_manager, session, clock=lambda: now)
    with pytest.raises(PermissionError, match=message):
        await scanner.purge_expired_from_trash(EMAIL, approval)
    token_manager.get_access_token.assert_not_awaited()


@pytest.mark.anyio
async def test_cleanup_includes_exact_boundary_and_excludes_younger(
    session: AsyncSession,
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    now = datetime(2026, 7, 14, tzinfo=UTC)
    items = [
        {"resource_id": "boundary", "path": f"{ROOT}boundary.webm"},
        {"resource_id": "younger", "path": f"{ROOT}younger.webm"},
    ]
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get(f"{DISK_API_BASE}/resources/files").mock(
                return_value=httpx.Response(200, json={"items": items})
            )
            respx.get(f"{DISK_API_BASE}/resources").mock(
                side_effect=[
                    httpx.Response(
                        200,
                        json={
                            "custom_properties": {
                                PROCESSED_PROPERTY: "true",
                                PROCESSED_AT_PROPERTY: (now - timedelta(days=7)).isoformat(),
                            }
                        },
                    ),
                    httpx.Response(
                        200,
                        json={
                            "custom_properties": {
                                PROCESSED_PROPERTY: "true",
                                PROCESSED_AT_PROPERTY: (
                                    now - timedelta(days=7) + timedelta(seconds=1)
                                ).isoformat(),
                            }
                        },
                    ),
                ]
            )
            delete_route = respx.delete(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(204)
            )
            deleted = await DiskScanner(token_manager, session, client).delete_expired(
                EMAIL, now=now
            )
    assert deleted == [items[0]["path"]]
    assert delete_route.call_count == 1


@pytest.mark.anyio
async def test_cleanup_repairs_incomplete_marker_without_deleting(
    session: AsyncSession,
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    item = {"resource_id": "incomplete", "path": f"{ROOT}incomplete.webm"}
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get(f"{DISK_API_BASE}/resources/files").mock(
                return_value=httpx.Response(200, json={"items": [item]})
            )
            respx.get(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "custom_properties": {
                            PROCESSED_PROPERTY: "true",
                            PROCESSED_AT_PROPERTY: "not-a-date",
                        }
                    },
                )
            )
            repair = respx.patch(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(200)
            )
            delete_route = respx.delete(f"{DISK_API_BASE}/resources").mock(
                return_value=httpx.Response(204)
            )
            deleted = await DiskScanner(token_manager, session, client).delete_expired(
                EMAIL, now=now
            )
    assert deleted == []
    assert delete_route.call_count == 0
    assert repair.call_count == 1
    assert b"2026-07-14T12:00:00Z" in repair.calls[0].request.content


@pytest.mark.anyio
async def test_async_operation_success(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.get("https://disk.test/operations/1").mock(
                side_effect=[
                    httpx.Response(200, json={"status": "in-progress"}),
                    httpx.Response(200, json={"status": "success"}),
                ]
            )
            scanner = DiskScanner(token_manager, session, client)
            with pytest.MonkeyPatch.context() as monkeypatch:
                monkeypatch.setattr("app.tools.disk.asyncio.sleep", AsyncMock())
                await scanner._await_operation(
                    httpx.Response(202, json={"href": "https://disk.test/operations/1"}),
                    EMAIL,
                )
    assert route.call_count == 2


@pytest.mark.anyio
async def test_async_operation_failed(session: AsyncSession) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://disk.test/operations/failed").mock(
                return_value=httpx.Response(200, json={"status": "failed"})
            )
            with pytest.raises(RuntimeError, match="delete operation failed"):
                await DiskScanner(token_manager, session, client)._await_operation(
                    httpx.Response(202, json={"href": "https://disk.test/operations/failed"}),
                    EMAIL,
                )


@pytest.mark.anyio
async def test_async_operation_timeout(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    sleep = AsyncMock()
    monkeypatch.setattr("app.tools.disk.asyncio.sleep", sleep)
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://disk.test/operations/timeout").mock(
                return_value=httpx.Response(200, json={"status": "in-progress"})
            )
            with pytest.raises(TimeoutError):
                await DiskScanner(token_manager, session, client)._await_operation(
                    httpx.Response(202, json={"href": "https://disk.test/operations/timeout"}),
                    EMAIL,
                )
    assert sleep.await_count == 60


@pytest.mark.anyio
async def test_permanent_failure_is_resumable_on_later_approved_run(
    session: AsyncSession,
) -> None:
    token_manager = AsyncMock()
    token_manager.get_access_token.return_value = "token"
    now = datetime(2026, 7, 14, tzinfo=UTC)
    trash_item = {
        "path": "trash:/retry.webm",
        "origin_path": f"{ROOT}retry.webm",
        "custom_properties": {
            PROCESSED_PROPERTY: "true",
            PROCESSED_AT_PROPERTY: (now - timedelta(days=8)).isoformat(),
        },
    }
    failed_approval = PermanentDeleteApproval("operator@example.com", now, "failed-run")
    async with httpx.AsyncClient() as client:
        with respx.mock:
            trash_list = respx.get(f"{DISK_API_BASE}/trash/resources").mock(
                return_value=httpx.Response(200, json={"_embedded": {"items": [trash_item]}})
            )
            delete_route = respx.delete(f"{DISK_API_BASE}/trash/resources").mock(
                side_effect=[httpx.Response(500), httpx.Response(204)]
            )
            scanner = DiskScanner(token_manager, session, client, clock=lambda: now)
            with pytest.raises(httpx.HTTPStatusError):
                await scanner.purge_expired_from_trash(EMAIL, failed_approval)
            with pytest.raises(PermissionError, match="already consumed"):
                await scanner.purge_expired_from_trash(EMAIL, failed_approval)
            purged = await scanner.purge_expired_from_trash(
                EMAIL,
                PermanentDeleteApproval("operator@example.com", now, "retry-run"),
            )
    assert purged == ["trash:/retry.webm"]
    assert trash_list.call_count == delete_route.call_count == 2
