from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.storage_destination import StorageDestination
from app.tools.synology import SynologyBackend, SynologyFolder, SynologyPreflight


class DestinationRejectedError(ValueError):
    pass


class DestinationService:
    def __init__(self, synology: SynologyBackend, settings: Settings) -> None:
        self._synology = synology
        self._settings = settings

    async def preflight(self, recruiter: RecruiterConfig) -> SynologyPreflight:
        result = await self._synology.preflight(recruiter.synology_base_folder)
        if not all(
            (
                result.api_available,
                result.root_exists,
                result.root_writable,
                result.share_links_available,
            )
        ):
            raise DestinationRejectedError("Synology preflight requirements are not satisfied")
        return result

    async def discover(
        self, session: AsyncSession, recruiter: RecruiterConfig
    ) -> list[StorageDestination]:
        await self.preflight(recruiter)
        folders = await self._synology.discover_folders(
            recruiter.synology_base_folder,
            max_depth=self._settings.synology_discovery_max_depth,
            max_pages=self._settings.synology_discovery_max_pages,
            max_results=self._settings.synology_discovery_max_results,
        )
        destinations: list[StorageDestination] = []
        for folder in folders:
            if folder.symlink or not folder.writable:
                continue
            destinations.append(await self._persist(session, recruiter, folder))
        await session.commit()
        return destinations

    async def create(
        self,
        session: AsyncSession,
        recruiter: RecruiterConfig,
        *,
        parent_id: uuid.UUID,
        name: str,
    ) -> StorageDestination:
        parent = await self.resolve(session, recruiter, parent_id)
        folder = await self._synology.create_folder_under_root(
            recruiter.synology_base_folder, parent.canonical_path, name
        )
        destination = await self._persist(session, recruiter, folder)
        await session.commit()
        return destination

    async def resolve(
        self,
        session: AsyncSession,
        recruiter: RecruiterConfig,
        destination_id: uuid.UUID,
    ) -> StorageDestination:
        destination = await session.scalar(
            select(StorageDestination).where(
                StorageDestination.id == destination_id,
                StorageDestination.recruiter_id == recruiter.id,
                StorageDestination.writable.is_(True),
                StorageDestination.symlink_safe.is_(True),
            )
        )
        if destination is None:
            raise DestinationRejectedError("Storage destination is unavailable")
        try:
            self._synology.canonical_under_root(
                recruiter.synology_base_folder, destination.canonical_path
            )
        except ValueError as error:
            raise DestinationRejectedError(
                "Storage destination is outside recruiter root"
            ) from error
        return destination

    async def _persist(
        self, session: AsyncSession, recruiter: RecruiterConfig, folder: SynologyFolder
    ) -> StorageDestination:
        existing = await session.scalar(
            select(StorageDestination).where(
                StorageDestination.recruiter_id == recruiter.id,
                StorageDestination.canonical_path == folder.path,
            )
        )
        destination = existing or StorageDestination(
            recruiter_id=recruiter.id,
            canonical_path=folder.path,
            display_name=folder.name,
            validated_at=datetime.now(UTC),
        )
        destination.display_name = folder.name
        destination.writable = folder.writable
        destination.symlink_safe = not folder.symlink
        destination.validated_at = datetime.now(UTC)
        session.add(destination)
        await session.flush()
        return destination
