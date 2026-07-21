from collections.abc import AsyncIterator
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.tools.synology import SynologyAPIError, SynologyBackend

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
        assert request.headers["X-SYNO-Token"] == "key"
        assert b'name="path"' in request.content
        assert b"video-data" in request.content


@pytest.mark.anyio
async def test_create_share_link_and_error_propagation() -> None:
    async with httpx.AsyncClient() as http:
        backend = SynologyBackend("https://nas.test", SecretStr("key"), http)
        with respx.mock:
            respx.post(URL).mock(
                return_value=httpx.Response(
                    200,
                    json={"success": True, "data": {"links": [{"url": "https://share"}]}},
                )
            )
            assert await backend.create_share_link("/base/video.webm") == "https://share"
        with respx.mock:
            respx.post(URL).mock(
                return_value=httpx.Response(200, json={"success": False, "error": {"code": 999}})
            )
            with pytest.raises(SynologyAPIError):
                await backend.create_share_link("/base/video.webm")
