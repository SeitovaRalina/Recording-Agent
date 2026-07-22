from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from app.services.storage import StorageCollisionError


class SynologyAPIError(RuntimeError):
    def __init__(self, status_code: int, payload: object) -> None:
        super().__init__(f"Synology API returned HTTP {status_code}")
        self.status_code = status_code
        self.payload = payload


class SynologyPathError(ValueError):
    """A requested path cannot be proven safe under the configured root."""


@dataclass(frozen=True)
class SynologyFolder:
    path: str
    name: str
    writable: bool
    symlink: bool


@dataclass(frozen=True)
class SynologyPreflight:
    api_available: bool
    root_exists: bool
    root_writable: bool
    share_links_available: bool


class SynologyBackend:
    def __init__(self, base_url: str, api_key: SecretStr, client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-SYNO-Token": self._api_key.get_secret_value()}

    async def preflight(self, root: str) -> SynologyPreflight:
        canonical_root = self.canonical_under_root(root, root)
        info = await self._client.get(
            f"{self._base_url}/webapi/query.cgi",
            params={
                "api": "SYNO.API.Info",
                "method": "query",
                "version": "1",
                "query": "SYNO.FileStation.Info,SYNO.FileStation.List,SYNO.FileStation.Sharing",
            },
            headers=self._headers,
        )
        info_payload = self._validate(info)
        apis = info_payload.get("data")
        api_names = set(apis) if isinstance(apis, dict) else set()
        root_info = await self._get_info(canonical_root)
        return SynologyPreflight(
            api_available={"SYNO.FileStation.Info", "SYNO.FileStation.List"}.issubset(api_names),
            root_exists=True,
            root_writable=root_info.writable and not root_info.symlink,
            share_links_available="SYNO.FileStation.Sharing" in api_names,
        )

    async def discover_folders(
        self,
        root: str,
        *,
        max_depth: int = 3,
        max_pages: int = 10,
        max_results: int = 100,
        page_size: int = 50,
    ) -> list[SynologyFolder]:
        if not 0 <= max_depth <= 8:
            raise ValueError("Folder discovery depth is outside the safe bound")
        if not 1 <= max_pages <= 50 or not 1 <= max_results <= 500:
            raise ValueError("Folder discovery bounds are invalid")
        if not 1 <= page_size <= 100:
            raise ValueError("Folder page size is invalid")
        canonical_root = self.canonical_under_root(root, root)
        queue: list[tuple[str, int]] = [(canonical_root, 0)]
        results: list[SynologyFolder] = []
        pages = 0
        while queue and pages < max_pages and len(results) < max_results:
            parent, depth = queue.pop(0)
            offset = 0
            while pages < max_pages and len(results) < max_results:
                response = await self._client.get(
                    f"{self._base_url}/webapi/entry.cgi",
                    params={
                        "api": "SYNO.FileStation.List",
                        "method": "list",
                        "version": "2",
                        "folder_path": parent,
                        "filetype": "dir",
                        "offset": offset,
                        "limit": page_size,
                        "additional": '["perm","real_path"]',
                    },
                    headers=self._headers,
                )
                payload = self._validate(response)
                data = payload.get("data")
                files = data.get("files", []) if isinstance(data, dict) else []
                page = [item for item in files if isinstance(item, dict)]
                pages += 1
                for item in page:
                    raw_path = item.get("path")
                    name = item.get("name")
                    if not isinstance(raw_path, str) or not isinstance(name, str):
                        continue
                    path = self.canonical_under_root(canonical_root, raw_path)
                    additional = item.get("additional")
                    extra = additional if isinstance(additional, dict) else {}
                    real_path = extra.get("real_path")
                    symlink = isinstance(real_path, str) and self._canonical(real_path) != path
                    folder = SynologyFolder(
                        path=path,
                        name=name[:200],
                        writable=self._is_writable(extra),
                        symlink=symlink,
                    )
                    if not symlink:
                        results.append(folder)
                        if depth < max_depth:
                            queue.append((path, depth + 1))
                    if len(results) >= max_results:
                        break
                total = data.get("total") if isinstance(data, dict) else None
                offset += len(page)
                if (
                    not page
                    or len(page) < page_size
                    or (isinstance(total, int) and offset >= total)
                ):
                    break
        return results

    async def create_folder_under_root(self, root: str, parent: str, name: str) -> SynologyFolder:
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise SynologyPathError("Folder name must be one safe path component")
        if any(ord(character) < 32 for character in name):
            raise SynologyPathError("Folder name contains control characters")
        canonical_root = self.canonical_under_root(root, root)
        canonical_parent = self.canonical_under_root(canonical_root, parent)
        parent_info = await self._get_info(canonical_parent)
        if parent_info.symlink or not parent_info.writable:
            raise PermissionError("Destination parent is not a writable real folder")
        target = self.canonical_under_root(canonical_root, f"{canonical_parent}/{name}")
        response = await self._client.post(
            f"{self._base_url}/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.CreateFolder", "method": "create", "version": "2"},
            data={"folder_path": canonical_parent, "name": name, "force_parent": "false"},
            headers=self._headers,
        )
        self._validate(response)
        created = await self._get_info(target)
        if created.symlink or not created.writable:
            raise PermissionError("Created destination is not a writable real folder")
        return created

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
        target = f"{folder.rstrip('/')}/{filename}"
        if await self._exists(target):
            raise StorageCollisionError(
                "Synology destination already exists; overwrite is forbidden"
            )
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

    async def _exists(self, path: str) -> bool:
        response = await self._client.get(
            f"{self._base_url}/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.List",
                "method": "getinfo",
                "version": "2",
                "path": json.dumps([path]),
                "additional": '["perm","real_path"]',
            },
            headers=self._headers,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if response.status_code == 404 or code == 408:
            return False
        validated = self._validate(response)
        data = validated.get("data")
        files = data.get("files") if isinstance(data, dict) else None
        return isinstance(files, list) and bool(files)

    async def _get_info(self, path: str) -> SynologyFolder:
        response = await self._client.get(
            f"{self._base_url}/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.List",
                "method": "getinfo",
                "version": "2",
                "path": json.dumps([path]),
                "additional": '["perm","real_path"]',
            },
            headers=self._headers,
        )
        payload = self._validate(response)
        data = payload.get("data")
        files = data.get("files", []) if isinstance(data, dict) else []
        if not isinstance(files, list) or not files or not isinstance(files[0], dict):
            raise SynologyAPIError(response.status_code, {})
        item = files[0]
        raw_path = item.get("path")
        if not isinstance(raw_path, str):
            raise SynologyAPIError(response.status_code, {})
        canonical = self._canonical(raw_path)
        additional = item.get("additional")
        extra = additional if isinstance(additional, dict) else {}
        real_path = extra.get("real_path")
        return SynologyFolder(
            path=canonical,
            name=str(item.get("name") or PurePosixPath(canonical).name)[:200],
            writable=self._is_writable(extra),
            symlink=isinstance(real_path, str) and self._canonical(real_path) != canonical,
        )

    @classmethod
    def canonical_under_root(cls, root: str, candidate: str) -> str:
        canonical_root = cls._canonical(root)
        canonical_candidate = cls._canonical(candidate)
        root_path = PurePosixPath(canonical_root)
        candidate_path = PurePosixPath(canonical_candidate)
        if candidate_path != root_path and not candidate_path.is_relative_to(root_path):
            raise SynologyPathError("Destination escapes the configured recruiter root")
        return canonical_candidate

    @staticmethod
    def _canonical(path: str) -> str:
        if not path.startswith("/") or "\\" in path or "\x00" in path:
            raise SynologyPathError("Synology path must be an absolute POSIX path")
        parts = path.split("/")
        if any(part in {".", ".."} for part in parts):
            raise SynologyPathError("Synology path traversal is forbidden")
        return "/" + "/".join(part for part in parts if part)

    @staticmethod
    def _is_writable(additional: dict[str, Any]) -> bool:
        perm = additional.get("perm")
        return isinstance(perm, dict) and perm.get("write") is True

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
        if response.status_code in (allowed_error_codes or set()) or code in (
            allowed_error_codes or set()
        ):
            return payload if isinstance(payload, dict) else {}
        if response.is_error or not isinstance(payload, dict) or payload.get("success") is False:
            raise SynologyAPIError(response.status_code, payload)
        return payload
