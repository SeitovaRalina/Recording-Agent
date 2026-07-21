from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr


class SynologyAPIError(RuntimeError):
    def __init__(self, status_code: int, payload: object) -> None:
        super().__init__(f"Synology API returned HTTP {status_code}")
        self.status_code = status_code
        self.payload = payload


class SynologyBackend:
    def __init__(self, base_url: str, api_key: SecretStr, client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-SYNO-Token": self._api_key.get_secret_value()}

    async def ensure_folder(self, path: str) -> None:
        info = await self._client.get(
            f"{self._base_url}/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.Info", "method": "get", "version": "2"},
            headers=self._headers,
        )
        self._validate(info)
        components = [component for component in path.split("/") if component]
        parent = "/"
        for component in components:
            response = await self._client.post(
                f"{self._base_url}/webapi/entry.cgi",
                params={
                    "api": "SYNO.FileStation.CreateFolder",
                    "method": "create",
                    "version": "2",
                },
                data={
                    "folder_path": parent,
                    "name": component,
                    "force_parent": "true",
                },
                headers=self._headers,
            )
            self._validate(response, allowed_error_codes={409, 1101})
            parent = f"{parent.rstrip('/')}/{component}"

    async def upload(
        self,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
        size: int | None,
        *,
        recording_id: str,
        content_identity: str,
    ) -> str:
        del size, recording_id, content_identity
        boundary = f"recording-agent-{uuid.uuid4().hex}"
        response = await self._client.post(
            f"{self._base_url}/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.Upload", "method": "upload", "version": "2"},
            headers={
                **self._headers,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            content=self._multipart(boundary, folder, filename, stream),
        )
        self._validate(response, allowed_error_codes={408})
        return f"{folder.rstrip('/')}/{filename}"

    async def create_share_link(self, path: str) -> str:
        response = await self._client.post(
            f"{self._base_url}/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.Sharing",
                "method": "create",
                "version": "3",
            },
            data={"path": json.dumps([path]), "date_expired": "-1", "date_available": "0"},
            headers=self._headers,
        )
        payload = self._validate(response)
        try:
            return str(payload["data"]["links"][0]["url"])
        except (KeyError, IndexError, TypeError) as error:
            raise SynologyAPIError(response.status_code, payload) from error

    @staticmethod
    async def _multipart(
        boundary: str,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        fields = {"path": folder, "create_parents": "true"}
        for name, value in fields.items():
            yield (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            ).encode()
        encoded_name = quote(filename, safe="._- ")
        yield (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{encoded_name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        async for chunk in stream:
            yield chunk
        yield f"\r\n--{boundary}--\r\n".encode()

    @staticmethod
    def _validate(
        response: httpx.Response, *, allowed_error_codes: set[int] | None = None
    ) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        if response.status_code == 409 or code in (allowed_error_codes or set()):
            return payload if isinstance(payload, dict) else {}
        if response.is_error or not isinstance(payload, dict) or payload.get("success") is False:
            raise SynologyAPIError(response.status_code, payload)
        return payload
