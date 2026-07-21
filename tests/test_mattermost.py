import httpx
import pytest
import respx
from pydantic import SecretStr

from app.tools.mattermost import MattermostClient, MattermostError


@pytest.mark.anyio
@respx.mock
async def test_mattermost_sender_creates_dm_and_thread() -> None:
    direct = respx.post("https://mm.test/api/v4/channels/direct").mock(
        return_value=httpx.Response(201, json={"id": "dm"})
    )
    post = respx.post("https://mm.test/api/v4/posts").mock(
        return_value=httpx.Response(201, json={"id": "post", "root_id": "root"})
    )
    async with httpx.AsyncClient() as http:
        result = await MattermostClient(
            "https://mm.test", SecretStr("secret"), "bot", http
        ).send_dm("recruiter", "message", "root")
    assert result.thread_id == "root"
    assert direct.calls[0].request.content == b'["bot","recruiter"]'
    assert b'"root_id":"root"' in post.calls[0].request.content
    assert b"secret" not in post.calls[0].request.content


@pytest.mark.anyio
@respx.mock
async def test_mattermost_error_is_sanitized() -> None:
    respx.post("https://mm.test/api/v4/channels/direct").mock(
        return_value=httpx.Response(401, text="raw secret payload")
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(MattermostError, match="HTTP 401") as caught:
            await MattermostClient("https://mm.test", SecretStr("secret"), "bot", http).send_dm(
                "recruiter", "message"
            )
    assert "raw secret" not in str(caught.value)
