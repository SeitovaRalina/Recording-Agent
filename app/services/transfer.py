from __future__ import annotations

import re
import shutil
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.storage_destination import StorageDestination
from app.services.storage import StorageBackend, StreamingUnsupportedError
from app.tools.disk import DISK_API_BASE, DiskScanner
from app.tools.synology import SynologyAPIError, SynologyBackend

TEMP_ROOT = Path("/tmp/recording-agent")
TEMP_TTL = timedelta(hours=4)


class TransferError(RuntimeError):
    def __init__(self, step: str, cause: Exception) -> None:
        super().__init__(f"Transfer failed at {step}: {cause}")
        self.step = step
        self.cause = cause


@dataclass(frozen=True)
class TransferResult:
    folder_path: str
    file_path: str
    storage_is_durable: bool = False


class TransferService:
    def __init__(
        self,
        disk: DiskScanner,
        storage: StorageBackend,
        client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self._disk = disk
        self._storage = storage
        self._client = client
        self._synology_interview_roots = (
            settings.synology_interview_roots if settings is not None else ()
        )

    async def transfer(
        self,
        recording: Recording,
        recruiter: RecruiterConfig,
        candidate_name: str,
        session: AsyncSession,
    ) -> TransferResult:
        if recording.storage_destination_id and isinstance(self._storage, SynologyBackend):
            if not recording.generated_filename:
                raise TransferError("destination", ValueError("generated filename is missing"))
            destination = await session.scalar(
                select(StorageDestination).where(
                    StorageDestination.id == recording.storage_destination_id,
                    StorageDestination.recruiter_id == recruiter.id,
                    StorageDestination.writable.is_(True),
                    StorageDestination.symlink_safe.is_(True),
                )
            )
            if destination is None:
                raise TransferError("destination", ValueError("storage destination is unavailable"))
            try:
                folder, root = _canonical_allowed_destination(
                    destination.canonical_path, self._synology_interview_roots
                )
                await self._storage.validate_existing_directory_under_root(root, folder)
            except (SynologyAPIError, ValueError) as error:
                raise TransferError("destination", error) from error
            except PermissionError as error:
                raise TransferError("destination", error) from error
            filename = recording.generated_filename
        elif recording.storage_key and recording.generated_filename:
            folder, _, filename = recording.storage_key.rpartition("/")
            if not folder or filename != recording.generated_filename:
                raise TransferError("destination", ValueError("persisted storage key is invalid"))
            if isinstance(self._storage, SynologyBackend):
                try:
                    folder = SynologyBackend.canonical_under_root(
                        recruiter.synology_base_folder,
                        f"{recruiter.synology_base_folder.rstrip('/')}/{folder}",
                    )
                except ValueError as error:
                    raise TransferError("destination", error) from error
        else:
            if recording.calendar_dtstart is None:
                raise TransferError("destination", ValueError("calendar start is missing"))
            safe_name = re.sub(r'[/\\:*?"<>|]', "_", candidate_name)
            folder = (
                f"{recruiter.synology_base_folder.rstrip('/')}/"
                f"{recording.calendar_dtstart:%Y-%m-%d}/{safe_name}"
            )
            filename = recording.disk_filename
        if not (recording.storage_destination_id and isinstance(self._storage, SynologyBackend)):
            try:
                await self._storage.ensure_folder(folder)
            except Exception as error:
                raise TransferError("ensure_folder", error) from error
        try:
            download = await self._disk._request(  # noqa: SLF001
                "GET",
                f"{DISK_API_BASE}/resources/download",
                recruiter.email,
                params={"path": recording.disk_path},
            )
            href = download.json().get("href")
            if not isinstance(href, str) or not href:
                raise ValueError("Yandex Disk download response has no href")
        except Exception as error:
            raise TransferError("download", error) from error
        try:
            path = await self._stream_upload(href, folder, filename, recording)
        except StreamingUnsupportedError:
            try:
                path = await self._temp_upload(href, folder, filename, recording)
            except Exception as error:
                raise TransferError("upload", error) from error
        except Exception as error:
            raise TransferError("upload", error) from error
        return TransferResult(
            folder_path=folder,
            file_path=path,
            storage_is_durable=(
                getattr(self._storage, "durable_for_source_cleanup", False) is True
            ),
        )

    async def create_share_link(self, path: str) -> str:
        try:
            if isinstance(self._storage, SynologyBackend):
                return await self._storage.create_share_link(path)
            return await self._storage.create_share_link(path)
        except Exception as error:
            raise TransferError("share_link", error) from error

    async def _stream_upload(
        self, href: str, folder: str, filename: str, recording: Recording
    ) -> str:
        async with self._client.stream("GET", href, follow_redirects=True) as response:
            response.raise_for_status()
            size_value = response.headers.get("Content-Length")
            size = int(size_value) if size_value and int(size_value) > 0 else None
            return await self._storage.upload(
                folder,
                filename,
                response.aiter_bytes(1024 * 1024),
                size,
                recording_id=str(recording.id),
                content_identity=recording.content_identity
                or recording.disk_md5
                or recording.disk_file_id,
            )

    async def _temp_upload(
        self, href: str, folder: str, filename: str, recording: Recording
    ) -> str:
        temp_dir = TEMP_ROOT / str(uuid.uuid4())
        temp_path = temp_dir / filename
        await anyio.to_thread.run_sync(temp_dir.mkdir, 0o700, True, True)
        try:
            async with self._client.stream("GET", href, follow_redirects=True) as response:
                response.raise_for_status()
                async with await anyio.open_file(temp_path, "wb") as target:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        await target.write(chunk)
            size = (await anyio.to_thread.run_sync(temp_path.stat)).st_size
            return await self._storage.upload(
                folder,
                filename,
                _file_chunks(temp_path),
                size,
                recording_id=str(recording.id),
                content_identity=recording.content_identity
                or recording.disk_md5
                or recording.disk_file_id,
            )
        finally:
            await anyio.to_thread.run_sync(shutil.rmtree, temp_dir, True)


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    async with await anyio.open_file(path, "rb") as source:
        while chunk := await source.read(1024 * 1024):
            yield chunk


def _canonical_allowed_destination(path: str, roots: tuple[str, ...]) -> tuple[str, str]:
    for root in roots:
        try:
            return SynologyBackend.canonical_under_root(root, path), root
        except ValueError:
            continue
    raise ValueError("storage destination is outside allowed interview roots")


async def cleanup_stale_temp_files(root: Path = TEMP_ROOT, now: datetime | None = None) -> int:
    if not await anyio.to_thread.run_sync(root.exists):
        return 0
    cutoff = (now or datetime.now(UTC)).timestamp() - TEMP_TTL.total_seconds()
    removed = 0
    for path in await anyio.to_thread.run_sync(lambda: list(root.iterdir())):
        stat = await anyio.to_thread.run_sync(path.stat)
        if stat.st_mtime >= cutoff:
            continue
        if await anyio.to_thread.run_sync(path.is_dir):
            await anyio.to_thread.run_sync(shutil.rmtree, path, True)
        else:
            await anyio.to_thread.run_sync(path.unlink, True)
        removed += 1
    return removed
