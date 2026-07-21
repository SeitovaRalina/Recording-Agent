from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr


class MattermostError(RuntimeError):
    pass


@dataclass(frozen=True)
class MattermostPost:
    channel_id: str
    post_id: str
    thread_id: str


class MattermostClient:
    def __init__(
        self,
        base_url: str,
        bot_token: SecretStr,
        bot_user_id: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = bot_token
        self._bot_user_id = bot_user_id
        self._client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token.get_secret_value()}"}

    async def send_dm(
        self, recruiter_user_id: str, message: str, root_id: str = ""
    ) -> MattermostPost:
        if not self._base_url or not self._bot_user_id or not recruiter_user_id:
            raise MattermostError("Mattermost DM configuration is incomplete")
        channel_payload = await self._json_request(
            "POST",
            "/api/v4/channels/direct",
            json=[self._bot_user_id, recruiter_user_id],
        )
        channel_id = channel_payload.get("id")
        if not isinstance(channel_id, str) or not channel_id:
            raise MattermostError("Mattermost direct-channel response is malformed")
        body: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if root_id:
            body["root_id"] = root_id
        post_payload = await self._json_request("POST", "/api/v4/posts", json=body)
        post_id = post_payload.get("id")
        returned_root = post_payload.get("root_id")
        if not isinstance(post_id, str) or not post_id:
            raise MattermostError("Mattermost post response is malformed")
        thread_id = returned_root if isinstance(returned_root, str) and returned_root else post_id
        return MattermostPost(channel_id=channel_id, post_id=post_id, thread_id=thread_id)

    async def _json_request(self, method: str, path: str, *, json: object) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method, f"{self._base_url}{path}", headers=self._headers, json=json
            )
        except httpx.RequestError:
            raise MattermostError("Mattermost request transport failed") from None
        if response.is_error:
            raise MattermostError(f"Mattermost request failed with HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise MattermostError("Mattermost response is not valid JSON") from None
        if not isinstance(payload, dict):
            raise MattermostError("Mattermost response is malformed")
        return payload
