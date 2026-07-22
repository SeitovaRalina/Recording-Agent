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

    async def probe_user(self, recruiter_user_id: str) -> None:
        """Validate the configured DM endpoints without creating a channel or post."""
        if not self._base_url or not self._bot_user_id or not recruiter_user_id:
            raise MattermostError("Mattermost DM configuration is incomplete")
        payload = await self._json_request("GET", f"/api/v4/users/{recruiter_user_id}")
        if payload.get("id") != recruiter_user_id:
            raise MattermostError("Mattermost recruiter mapping response is malformed")

    async def validate_direct_channel(self, recruiter_user_id: str, channel_id: str) -> None:
        """Fail closed unless a channel is a DM containing exactly bot and recruiter."""
        if not self._base_url or not self._bot_user_id or not recruiter_user_id or not channel_id:
            raise MattermostError("Mattermost DM configuration is incomplete")
        channel = await self._json_request("GET", f"/api/v4/channels/{channel_id}")
        if channel.get("id") != channel_id or channel.get("type") != "D":
            raise MattermostError("Mattermost channel is not a direct channel")
        members = await self._list_request(
            "GET", f"/api/v4/channels/{channel_id}/members?page=0&per_page=3"
        )
        member_ids = {member.get("user_id") for member in members if isinstance(member, dict)}
        if member_ids != {self._bot_user_id, recruiter_user_id} or len(members) != 2:
            raise MattermostError("Mattermost direct-channel membership is not exact")

    async def send_dm(
        self,
        recruiter_user_id: str,
        message: str,
        root_id: str = "",
        pending_post_id: str = "",
        expected_channel_id: str = "",
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
        if expected_channel_id and channel_id != expected_channel_id:
            raise MattermostError("Mattermost direct-channel binding changed")
        if pending_post_id:
            existing = await self._find_pending_post(channel_id, pending_post_id)
            if existing is not None:
                return existing
        body: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if root_id:
            body["root_id"] = root_id
        if pending_post_id:
            body["pending_post_id"] = pending_post_id
        post_payload = await self._json_request("POST", "/api/v4/posts", json=body)
        post_id = post_payload.get("id")
        returned_root = post_payload.get("root_id")
        if not isinstance(post_id, str) or not post_id:
            raise MattermostError("Mattermost post response is malformed")
        thread_id = returned_root if isinstance(returned_root, str) and returned_root else post_id
        return MattermostPost(channel_id=channel_id, post_id=post_id, thread_id=thread_id)

    async def _find_pending_post(
        self, channel_id: str, pending_post_id: str
    ) -> MattermostPost | None:
        payload = await self._json_request(
            "GET", f"/api/v4/channels/{channel_id}/posts?page=0&per_page=200"
        )
        posts = payload.get("posts")
        if not isinstance(posts, dict):
            raise MattermostError("Mattermost channel-post response is malformed")
        for value in posts.values():
            if not isinstance(value, dict) or value.get("pending_post_id") != pending_post_id:
                continue
            post_id = value.get("id")
            root_id = value.get("root_id")
            if not isinstance(post_id, str) or not post_id:
                raise MattermostError("Mattermost existing post is malformed")
            thread_id = root_id if isinstance(root_id, str) and root_id else post_id
            return MattermostPost(channel_id=channel_id, post_id=post_id, thread_id=thread_id)
        return None

    async def _json_request(
        self, method: str, path: str, *, json: object | None = None
    ) -> dict[str, Any]:
        try:
            if json is None:
                response = await self._client.request(
                    method, f"{self._base_url}{path}", headers=self._headers
                )
            else:
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

    async def _list_request(self, method: str, path: str) -> list[Any]:
        try:
            response = await self._client.request(
                method, f"{self._base_url}{path}", headers=self._headers
            )
        except httpx.RequestError:
            raise MattermostError("Mattermost request transport failed") from None
        if response.is_error:
            raise MattermostError(f"Mattermost request failed with HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise MattermostError("Mattermost response is not valid JSON") from None
        if not isinstance(payload, list):
            raise MattermostError("Mattermost response is malformed")
        return payload
