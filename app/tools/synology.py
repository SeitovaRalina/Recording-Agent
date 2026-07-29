from __future__ import annotations

import asyncio
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

QueryValue = str | int


def _copy_move_task_id(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    for key in ("taskid", "task_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


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
    directory: bool = True


@dataclass(frozen=True)
class SynologyPreflight:
    api_available: bool
    root_exists: bool
    root_writable: bool
    share_links_available: bool


@dataclass(frozen=True)
class SynologyMoveResult:
    task_id: str | None
    target_path: str


class SynologyBackend:
    def __init__(
        self,
        base_url: str = "",
        api_key: SecretStr | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        username: str = "",
        password: SecretStr | None = None,
        device_id: SecretStr | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or SecretStr("")
        self._client = client or httpx.AsyncClient()
        self._username = username
        self._password = password or SecretStr("")
        self._device_id = device_id or SecretStr("")
        self._sid: str | None = None

    @property
    def durable_for_source_cleanup(self) -> bool:
        return True

    @property
    def _headers(self) -> dict[str, str]:
        if not self._api_key.get_secret_value():
            return {}
        return {"X-SYNO-Token": self._api_key.get_secret_value()}

    async def _auth_params(self) -> dict[str, str]:
        if self._api_key.get_secret_value():
            return {}
        return {"_sid": await self._login_sid()}

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, QueryValue],
    ) -> httpx.Response:
        return await self._client.get(
            f"{self._base_url}{path}",
            params={**params, **await self._auth_params()},
            headers=self._headers,
        )

    async def _post(
        self,
        path: str,
        *,
        params: dict[str, QueryValue],
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        content: AsyncIterator[bytes] | None = None,
    ) -> httpx.Response:
        return await self._client.post(
            f"{self._base_url}{path}",
            params={**params, **await self._auth_params()},
            data=data,
            headers={**self._headers, **(headers or {})},
            content=content,
        )

    async def _login_sid(self) -> str:
        if self._sid:
            return self._sid
        username = self._username.strip()
        password = self._password.get_secret_value()
        if not username or not password:
            raise SynologyAPIError(0, {"error": "Synology SID login credentials are missing"})
        params: dict[str, QueryValue] = {
            "api": "SYNO.API.Auth",
            "method": "login",
            "version": "6",
            "account": username,
            "passwd": password,
            "session": "FileStation",
            "format": "sid",
        }
        device_id = self._device_id.get_secret_value()
        if device_id:
            params["device_id"] = device_id
        response = await self._client.get(f"{self._base_url}/webapi/entry.cgi", params=params)
        payload = self._validate(response)
        data = payload.get("data")
        sid = data.get("sid") if isinstance(data, dict) else None
        if not isinstance(sid, str) or not sid:
            raise SynologyAPIError(response.status_code, {"error": "Synology SID login failed"})
        self._sid = sid
        return sid

    async def preflight(self, root: str) -> SynologyPreflight:
        canonical_root = self.canonical_under_root(root, root)
        info = await self._get(
            "/webapi/query.cgi",
            params={
                "api": "SYNO.API.Info",
                "method": "query",
                "version": "1",
                "query": "SYNO.FileStation.Info,SYNO.FileStation.List,SYNO.FileStation.Sharing",
            },
        )
        info_payload = self._validate(info)
        apis = info_payload.get("data")
        api_names = set(apis) if isinstance(apis, dict) else set()
        root_info = await self._get_info(canonical_root)
        return SynologyPreflight(
            api_available={"SYNO.FileStation.Info", "SYNO.FileStation.List"}.issubset(api_names),
            root_exists=True,
            root_writable=root_info.directory and root_info.writable and not root_info.symlink,
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
                response = await self._get(
                    "/webapi/entry.cgi",
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
        response = await self._post(
            "/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.CreateFolder", "method": "create", "version": "2"},
            data={"folder_path": canonical_parent, "name": name, "force_parent": "false"},
        )
        self._validate(response)
        created = await self._get_info(target)
        if not created.directory or created.symlink or not created.writable:
            raise PermissionError("Created destination is not a writable real folder")
        return created

    async def validate_existing_directory_under_root(self, root: str, path: str) -> SynologyFolder:
        canonical_root = self.canonical_under_root(root, root)
        canonical_path = self.canonical_under_root(canonical_root, path)
        preflight = await self.preflight(canonical_root)
        if not all(
            (
                preflight.api_available,
                preflight.root_exists,
                preflight.root_writable,
                preflight.share_links_available,
            )
        ):
            raise PermissionError("Synology preflight requirements are not satisfied")
        directory = await self._get_info(canonical_path)
        if directory.path != canonical_path:
            raise SynologyPathError("Synology returned a different destination path")
        if not directory.directory or directory.symlink or not directory.writable:
            raise PermissionError("Selected destination is not a writable real folder")
        return directory

    async def ensure_folder(self, path: str) -> None:
        info = await self._get(
            "/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.Info", "method": "get", "version": "2"},
        )
        self._validate(info)
        components = [component for component in path.split("/") if component]
        parent = "/"
        for component in components:
            response = await self._post(
                "/webapi/entry.cgi",
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
        target = f"{folder.rstrip('/')}/{filename}"
        expected_owner: dict[str, object] = {
            "content_identity": content_identity,
            "recording_id": recording_id,
            "size": size,
            "v": 1,
        }
        owner = await self._read_owner_marker(folder, filename)
        existing_size = await self._file_size(target)
        if owner is not None:
            self._require_same_owner(target, owner, expected_owner)
            if existing_size is not None:
                self._require_complete_size(target, existing_size, size)
                return target
        elif existing_size is not None:
            raise StorageCollisionError(
                "Synology destination already exists; overwrite is forbidden"
            )

        if owner is None:
            await self._claim_owner(folder, filename, expected_owner)
            existing_size = await self._file_size(target)
            if existing_size is not None:
                self._require_complete_size(target, existing_size, size)
                return target

        try:
            await self._upload_file(folder, filename, stream)
        except Exception:
            recovered_owner = await self._read_owner_marker(folder, filename)
            recovered_size = await self._file_size(target)
            if recovered_owner is None or recovered_size is None:
                raise
            self._require_same_owner(target, recovered_owner, expected_owner)
            self._require_complete_size(target, recovered_size, size)
        return target

    async def _claim_owner(
        self, folder: str, filename: str, expected_owner: dict[str, object]
    ) -> None:
        marker_name = self._owner_marker_name(filename)
        body = json.dumps(expected_owner, sort_keys=True, separators=(",", ":")).encode()
        try:
            await self._upload_file(folder, marker_name, self._bytes(body))
        except Exception:
            owner = await self._read_owner_marker(folder, filename)
            if owner is None:
                raise
            self._require_same_owner(f"{folder.rstrip('/')}/{filename}", owner, expected_owner)

    async def _upload_file(self, folder: str, filename: str, stream: AsyncIterator[bytes]) -> None:
        boundary = f"recording-agent-{uuid.uuid4().hex}"
        response = await self._post(
            "/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.Upload", "method": "upload", "version": "2"},
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            content=self._multipart(boundary, folder, filename, stream),
        )
        self._validate(response)

    async def _file_size(self, path: str) -> int | None:
        response = await self._get(
            "/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.List",
                "method": "getinfo",
                "version": "2",
                "path": json.dumps([path]),
                "additional": '["size"]',
            },
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if response.status_code == 404 or code == 408:
            return None
        validated = self._validate(response)
        data = validated.get("data")
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list) or not files:
            return None
        item = files[0]
        if not isinstance(item, dict) or not isinstance(item.get("size"), int):
            raise StorageCollisionError(
                f"Synology destination exists but its size cannot be verified: {path}"
            )
        return int(item["size"])

    async def _read_owner_marker(self, folder: str, filename: str) -> dict[str, object] | None:
        marker_path = f"{folder.rstrip('/')}/{self._owner_marker_name(filename)}"
        response = await self._get(
            "/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.Download",
                "method": "download",
                "version": "2",
                "path": marker_path,
                "mode": "open",
            },
        )
        if response.status_code == 404:
            return None
        try:
            payload = response.json()
        except ValueError as error:
            raise StorageCollisionError("Synology ownership marker is malformed") from error
        if isinstance(payload, dict) and payload.get("success") is False:
            marker_error = payload.get("error")
            code = marker_error.get("code") if isinstance(marker_error, dict) else None
            if code == 408:
                return None
            self._validate(response)
        if not isinstance(payload, dict):
            raise StorageCollisionError("Synology ownership marker is malformed")
        return payload

    @staticmethod
    def _owner_marker_name(filename: str) -> str:
        return f".{filename}.recording-agent-owner.json"

    @staticmethod
    async def _bytes(value: bytes) -> AsyncIterator[bytes]:
        yield value

    @staticmethod
    def _require_same_owner(
        target: str, actual: dict[str, object], expected: dict[str, object]
    ) -> None:
        if actual == expected:
            return
        raise StorageCollisionError(
            f"Synology destination already exists with different ownership: {target}"
        )

    @staticmethod
    def _require_complete_size(target: str, actual: int, expected: int | None) -> None:
        if expected is not None and actual == expected:
            return
        raise StorageCollisionError(
            f"Synology destination cannot be proven complete for safe reuse: {target}"
        )

    async def _get_info(self, path: str) -> SynologyFolder:
        response = await self._get(
            "/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.List",
                "method": "getinfo",
                "version": "2",
                "path": json.dumps([path]),
                "additional": '["perm","real_path"]',
            },
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
            directory=item.get("isdir") is True,
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
        response = await self._post(
            "/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.Sharing",
                "method": "create",
                "version": "3",
            },
            data={"path": json.dumps([path]), "date_expired": "-1", "date_available": "0"},
        )
        payload = self._validate(response)
        try:
            return str(payload["data"]["links"][0]["url"])
        except (KeyError, IndexError, TypeError) as error:
            raise SynologyAPIError(response.status_code, payload) from error

    async def find_public_share_link(self, path: str) -> str | None:
        """Recover an existing permanent File Station link by exact stored path."""
        for offset in range(0, 1000, 100):
            response = await self._get(
                "/webapi/entry.cgi",
                params={
                    "api": "SYNO.FileStation.Sharing",
                    "method": "list",
                    "version": "3",
                    "offset": str(offset),
                    "limit": "100",
                },
            )
            payload = self._validate(response)
            data = payload.get("data")
            links = data.get("links") if isinstance(data, dict) else None
            if not isinstance(links, list):
                raise SynologyAPIError(response.status_code, payload)
            for item in links:
                if isinstance(item, dict) and item.get("path") == path:
                    url = item.get("url")
                    if isinstance(url, str) and url:
                        return url
            total = data.get("total") if isinstance(data, dict) else None
            if not links or len(links) < 100 or (isinstance(total, int) and offset + 100 >= total):
                return None
        raise SynologyAPIError(0, {"error": "Synology share-link scan exceeded safe bound"})

    async def copy_move_verified(
        self,
        *,
        source_path: str,
        target_folder: str,
        filename: str,
        root: str,
        expected_size: int | None,
        expected_owner: dict[str, object],
    ) -> SynologyMoveResult:
        """Move a proven owned file without overwrite and prove the result before returning."""
        source = self.canonical_under_root(root, source_path)
        folder = self.canonical_under_root(root, target_folder)
        target = self.canonical_under_root(root, f"{folder.rstrip('/')}/{filename}")
        if await self._file_size(target) is not None:
            raise StorageCollisionError(
                "Synology reroute target already exists; overwrite is forbidden"
            )
        source_size = await self._file_size(source)
        if source_size is None:
            raise StorageCollisionError("Synology reroute source does not exist")
        self._require_complete_size(source, source_size, expected_size)
        source_owner = await self._read_owner_marker(
            str(PurePosixPath(source).parent), PurePosixPath(source).name
        )
        if source_owner is None:
            raise StorageCollisionError("Synology reroute source has no ownership marker")
        self._require_same_owner(source, source_owner, expected_owner)
        task_id = await self._start_copy_move(source, folder)
        target_size = await self._file_size(target)
        if target_size is None:
            raise StorageCollisionError("Synology CopyMove target is absent after task completion")
        self._require_complete_size(target, target_size, expected_size)
        marker_name = self._owner_marker_name(filename)
        source_marker = self.canonical_under_root(
            root, f"{PurePosixPath(source).parent}/{marker_name}"
        )
        target_marker = self.canonical_under_root(root, f"{folder.rstrip('/')}/{marker_name}")
        if await self._file_size(target_marker) is not None:
            raise StorageCollisionError("Synology reroute owner-marker target already exists")
        await self._start_copy_move(source_marker, folder)
        target_owner = await self._read_owner_marker(folder, filename)
        if target_owner is None:
            raise StorageCollisionError("Synology CopyMove did not preserve ownership marker")
        self._require_same_owner(target, target_owner, expected_owner)
        if await self._file_size(source) is not None:
            raise StorageCollisionError("Synology CopyMove did not remove the physical source")
        if await self._file_size(source_marker) is not None:
            raise StorageCollisionError("Synology CopyMove did not remove the source owner marker")
        return SynologyMoveResult(task_id=task_id, target_path=target)

    async def verify_moved_target(
        self,
        *,
        target_path: str,
        filename: str,
        root: str,
        expected_size: int | None,
        expected_owner: dict[str, object],
    ) -> None:
        target = self.canonical_under_root(root, target_path)
        size = await self._file_size(target)
        if size is None:
            raise StorageCollisionError("Synology reroute target is absent")
        self._require_complete_size(target, size, expected_size)
        owner = await self._read_owner_marker(str(PurePosixPath(target).parent), filename)
        if owner is None:
            raise StorageCollisionError("Synology reroute target has no owner marker")
        self._require_same_owner(target, owner, expected_owner)

    async def _start_copy_move(self, source: str, target_folder: str) -> str | None:
        response = await self._post(
            "/webapi/entry.cgi",
            params={"api": "SYNO.FileStation.CopyMove", "method": "start", "version": "3"},
            data={
                "path": json.dumps([source]),
                "dest_folder_path": target_folder,
                "remove_src": "true",
                "overwrite": "false",
            },
        )
        payload = self._validate(response)
        task_id = _copy_move_task_id(payload)
        if task_id:
            await self._wait_background_task(task_id)
        return task_id

    async def _wait_background_task(self, task_id: str) -> None:
        # File Station reports CopyMove asynchronously. Bounded polling avoids declaring an
        # ambiguous NAS mutation successful before the task is terminal.
        for _ in range(30):
            response = await self._get(
                "/webapi/entry.cgi",
                params={
                    "api": "SYNO.FileStation.CopyMove",
                    "method": "status",
                    "version": "3",
                    "taskid": task_id,
                },
            )
            try:
                payload = self._validate(response)
            except SynologyAPIError as error:
                code = (
                    error.payload.get("error", {}).get("code")
                    if isinstance(error.payload, dict)
                    else None
                )
                if code == 599:  # DSM removes a completed CopyMove task from status.
                    return
                raise
            data = payload.get("data")
            if not isinstance(data, dict):
                raise SynologyAPIError(response.status_code, payload)
            status = data.get("status")
            if status in {"finished", True}:
                return
            if data.get("has_fail") is True or status in {"failed", "error", "cancelled"}:
                raise SynologyAPIError(response.status_code, payload)
            await asyncio.sleep(min(0.25 * (2**_), 2.0))
        raise SynologyAPIError(0, {"error": "Synology CopyMove task did not complete"})

    @staticmethod
    async def _multipart(
        boundary: str,
        folder: str,
        filename: str,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        fields = {"path": folder, "create_parents": "true", "overwrite": "false"}
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
