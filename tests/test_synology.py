from collections.abc import AsyncIterator
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.services.storage import StorageCollisionError
from app.tools.synology import SynologyAPIError, SynologyBackend, SynologyPathError

URL = "https://nas.test/webapi/entry.cgi"


async def chunks() -> AsyncIterator[bytes]:
    yield b"video-data"


@pytest.mark.anyio
async def test_ensure_folder_treats_already_exists_as_success() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(URL).mock(return_value=httpx.Response(200, json={"success": True}))
            create_route = router.post(URL).mock(
                return_value=httpx.Response(200, json={"success": False, "error": {"code": 409}})
            )
            await backend.ensure_folder("/base/date/name")
        assert len(create_route.calls) == 3
        forms = [parse_qs(call.request.content.decode()) for call in create_route.calls]
        assert forms == [
            {"folder_path": ["/"], "name": ["base"], "force_parent": ["true"]},
            {"folder_path": ["/base"], "name": ["date"], "force_parent": ["true"]},
            {
                "folder_path": ["/base/date"],
                "name": ["name"],
                "force_parent": ["true"],
            },
        ]
        assert all(
            call.request.url.params["api"] == "SYNO.FileStation.CreateFolder"
            and call.request.url.params["method"] == "create"
            and call.request.url.params["version"] == "2"
            for call in create_route.calls
        )


@pytest.mark.anyio
async def test_upload_streams_multipart_and_returns_path() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(URL).mock(return_value=httpx.Response(404, json={"success": False}))
            route = router.post(URL).mock(return_value=httpx.Response(200, json={"success": True}))
            path = await backend.upload(
                "/base",
                "video.webm",
                chunks(),
                10,
                recording_id="recording-1",
                content_identity="md5-1",
            )
        request = route.calls.last.request
        assert path == "/base/video.webm"
        assert len(route.calls) == 2
        assert request.headers["X-SYNO-Token"] == "key"
        assert b'name="path"' in request.content
        assert b'name="overwrite"' in request.content
        assert b"false" in request.content
        assert b"video-data" in request.content


@pytest.mark.anyio
async def test_create_share_link_and_error_propagation() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock as router:
            respx.post(URL).mock(
                return_value=httpx.Response(
                    200,
                    json={"success": True, "data": {"links": [{"url": "https://share"}]}},
                )
            )
            assert await backend.create_share_link("/base/video.webm") == "https://share"
            body = parse_qs((await router.calls.last.request.aread()).decode())
            assert body["date_expired"] == ["-1"]
            assert body["date_available"] == ["0"]
            assert "password" not in body
        with respx.mock:
            respx.post(URL).mock(
                return_value=httpx.Response(200, json={"success": False, "error": {"code": 999}})
            )
            with pytest.raises(SynologyAPIError):
                await backend.create_share_link("/base/video.webm")


@pytest.mark.anyio
async def test_find_public_share_link_recovers_exact_path_only() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            route = router.get(URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "links": [
                                {"path": "/base/other.webm", "url": "https://wrong"},
                                {"path": "/base/video.webm", "url": "https://right"},
                            ]
                        },
                    },
                )
            )
            assert await backend.find_public_share_link("/base/video.webm") == "https://right"
    assert route.calls.last.request.url.params["method"] == "list"


@pytest.mark.anyio
async def test_find_public_share_link_paginates_to_exact_path() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        first = [{"path": f"/base/{index}", "url": "https://other"} for index in range(100)]
        with respx.mock(assert_all_called=True) as router:
            route = router.get(URL).mock(
                side_effect=[
                    httpx.Response(200, json={"success": True, "data": {"links": first}}),
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {"links": [{"path": "/base/video.webm", "url": "https://right"}]},
                        },
                    ),
                ]
            )
            assert await backend.find_public_share_link("/base/video.webm") == "https://right"
    assert [call.request.url.params["offset"] for call in route.calls] == ["0", "100"]


@pytest.mark.anyio
async def test_sid_login_is_used_when_api_key_is_unavailable() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend(
            "https://nas.test",
            SecretStr(""),
            http,
            username="operator",
            password=SecretStr("password"),
            device_id=SecretStr("device-1"),
        )
        with respx.mock(assert_all_called=True) as router:
            auth = router.get(URL).mock(
                return_value=httpx.Response(200, json={"success": True, "data": {"sid": "sid-1"}})
            )
            share = router.post(URL).mock(
                return_value=httpx.Response(
                    200,
                    json={"success": True, "data": {"links": [{"url": "https://share"}]}},
                )
            )

            assert await backend.create_share_link("/base/video.webm") == "https://share"

    auth_query = parse_qs(str(auth.calls.last.request.url.query, encoding="utf-8"))
    share_query = parse_qs(str(share.calls.last.request.url.query, encoding="utf-8"))
    assert auth_query["api"] == ["SYNO.API.Auth"]
    assert auth_query["account"] == ["operator"]
    assert auth_query["device_id"] == ["device-1"]
    assert "X-SYNO-Token" not in share.calls.last.request.headers
    assert share_query["_sid"] == ["sid-1"]


@pytest.mark.anyio
async def test_live_destination_validation_rejects_symlink() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get("https://nas.test/webapi/query.cgi").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "SYNO.FileStation.Info": {},
                            "SYNO.FileStation.List": {},
                            "SYNO.FileStation.Sharing": {},
                        },
                    },
                )
            )
            route = router.get(URL).mock(
                side_effect=[
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {
                                "files": [
                                    {
                                        "path": "/root",
                                        "name": "root",
                                        "isdir": True,
                                        "additional": {
                                            "perm": {"write": True},
                                            "real_path": "/root",
                                        },
                                    }
                                ]
                            },
                        },
                    ),
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {
                                "files": [
                                    {
                                        "path": "/root/team",
                                        "name": "team",
                                        "isdir": True,
                                        "additional": {
                                            "perm": {"write": True},
                                            "real_path": "/elsewhere",
                                        },
                                    }
                                ]
                            },
                        },
                    ),
                ]
            )
            with pytest.raises(PermissionError, match="writable real"):
                await backend.validate_existing_directory_under_root("/root", "/root/team")

    assert len(route.calls) == 2


def test_canonical_path_rejects_escape_traversal_and_backslash() -> None:
    assert SynologyBackend.canonical_under_root("/recruiters/mila", "/recruiters/mila/team") == (
        "/recruiters/mila/team"
    )
    with pytest.raises(SynologyPathError):
        SynologyBackend.canonical_under_root("/recruiters/mila", "/recruiters/other")
    with pytest.raises(SynologyPathError):
        SynologyBackend.canonical_under_root("/recruiters/mila", "/recruiters/mila/../other")
    with pytest.raises(SynologyPathError):
        SynologyBackend.canonical_under_root("/recruiters/mila", "/recruiters/mila\\other")


@pytest.mark.anyio
async def test_upload_refuses_existing_destination() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(URL).mock(
                side_effect=[
                    httpx.Response(404),
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {"files": [{"path": "/base/video.webm", "size": 10}]},
                        },
                    ),
                ]
            )
            with pytest.raises(StorageCollisionError, match="overwrite is forbidden"):
                await backend.upload(
                    "/base",
                    "video.webm",
                    chunks(),
                    10,
                    recording_id="recording-2",
                    content_identity="md5-2",
                )


@pytest.mark.anyio
async def test_upload_reuses_existing_destination_only_for_exact_persisted_owner() -> None:
    marker = b'{"content_identity":"md5-1","recording_id":"recording-1","size":10,"v":1}'
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(URL).mock(
                side_effect=[
                    httpx.Response(200, content=marker),
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {"files": [{"path": "/base/video.webm", "size": 10}]},
                        },
                    ),
                ]
            )
            path = await backend.upload(
                "/base",
                "video.webm",
                chunks(),
                10,
                recording_id="recording-1",
                content_identity="md5-1",
            )

    assert path == "/base/video.webm"


@pytest.mark.anyio
async def test_upload_rejects_existing_destination_owned_by_another_recording() -> None:
    marker = b'{"content_identity":"md5-1","recording_id":"recording-1","size":10,"v":1}'
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(URL).mock(return_value=httpx.Response(200, content=marker))

            with pytest.raises(StorageCollisionError, match="different ownership"):
                await backend.upload(
                    "/base",
                    "video.webm",
                    chunks(),
                    10,
                    recording_id="recording-2",
                    content_identity="md5-1",
                )


@pytest.mark.anyio
async def test_upload_recovers_timeout_after_synology_accepted_exact_owned_file() -> None:
    marker = b'{"content_identity":"md5-1","recording_id":"recording-1","size":10,"v":1}'
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            router.get(URL).mock(
                side_effect=[
                    httpx.Response(200, content=marker),
                    httpx.Response(404),
                    httpx.Response(200, content=marker),
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {"files": [{"path": "/base/video.webm", "size": 10}]},
                        },
                    ),
                ]
            )
            router.post(URL).mock(return_value=httpx.Response(504))

            path = await backend.upload(
                "/base",
                "video.webm",
                chunks(),
                10,
                recording_id="recording-1",
                content_identity="md5-1",
            )

    assert path == "/base/video.webm"


@pytest.mark.anyio
async def test_folder_discovery_is_paginated_bounded_and_omits_symlinks() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock(assert_all_called=True) as router:
            route = router.get(URL).mock(
                side_effect=[
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {
                                "total": 2,
                                "files": [
                                    {
                                        "path": "/root/real",
                                        "name": "real",
                                        "additional": {
                                            "perm": {"write": True},
                                            "real_path": "/root/real",
                                        },
                                    }
                                ],
                            },
                        },
                    ),
                    httpx.Response(
                        200,
                        json={
                            "success": True,
                            "data": {
                                "total": 2,
                                "files": [
                                    {
                                        "path": "/root/link",
                                        "name": "link",
                                        "additional": {
                                            "perm": {"write": True},
                                            "real_path": "/elsewhere",
                                        },
                                    }
                                ],
                            },
                        },
                    ),
                ]
            )
            folders = await backend.discover_folders(
                "/root", max_depth=0, max_pages=2, max_results=10, page_size=1
            )

    assert [folder.path for folder in folders] == ["/root/real"]
    assert len(route.calls) == 2
