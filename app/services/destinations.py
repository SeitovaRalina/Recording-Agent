from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.storage_destination import StorageDestination
from app.tools.synology import SynologyAPIError, SynologyBackend, SynologyFolder, SynologyPreflight


class DestinationRejectedError(ValueError):
    pass


class DestinationService:
    def __init__(self, synology: SynologyBackend, settings: Settings) -> None:
        self._synology = synology
        self._settings = settings
        self._roots = settings.synology_interview_roots

    async def preflight(self, recruiter: RecruiterConfig) -> SynologyPreflight:
        del recruiter
        if not self._roots:
            raise DestinationRejectedError("Synology interview roots are not configured")
        checks = [await self._synology.preflight(root) for root in self._roots]
        result = SynologyPreflight(
            api_available=all(item.api_available for item in checks),
            root_exists=all(item.root_exists for item in checks),
            root_writable=all(item.root_writable for item in checks),
            share_links_available=all(item.share_links_available for item in checks),
        )
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
        folders: list[SynologyFolder] = []
        per_root_results = max(1, self._settings.synology_discovery_max_results // len(self._roots))
        for root in self._roots:
            folders.append(
                SynologyFolder(
                    root,
                    root.rsplit("/", 1)[-1],
                    writable=True,
                    symlink=False,
                )
            )
            folders.extend(
                await self._synology.discover_folders(
                    root,
                    max_depth=self._settings.synology_discovery_max_depth,
                    max_pages=self._settings.synology_discovery_max_pages,
                    max_results=per_root_results,
                )
            )
        self._reject_duplicate_paths(folders)
        destinations: list[StorageDestination] = []
        for folder in folders:
            if (
                folder.symlink
                or not folder.writable
                or not self._is_allowed_interview_path(folder.path)
            ):
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
        if parent.canonical_path not in self._roots:
            raise DestinationRejectedError("New folders are allowed only under an allowed root")
        folder = await self._synology.create_folder_under_root(
            parent.canonical_path, parent.canonical_path, name
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
            root = self._require_allowed_interview_path(destination.canonical_path)
        except ValueError as error:
            raise DestinationRejectedError(
                "Storage destination is outside allowed interview roots"
            ) from error
        try:
            await self._synology.validate_existing_directory_under_root(
                root, destination.canonical_path
            )
        except (SynologyAPIError, PermissionError, ValueError) as error:
            raise DestinationRejectedError(
                "Storage destination failed live Synology validation"
            ) from error
        return destination

    async def list_allowed_candidates(
        self,
        session: AsyncSession,
        recruiter: RecruiterConfig,
        *,
        limit: int | None = None,
    ) -> list[StorageDestination]:
        max_results = limit or self._settings.synology_discovery_max_results
        if max_results < 1:
            raise DestinationRejectedError("Destination candidate limit must be positive")
        rows = await session.scalars(
            select(StorageDestination)
            .where(
                StorageDestination.recruiter_id == recruiter.id,
                StorageDestination.writable.is_(True),
                StorageDestination.symlink_safe.is_(True),
                _allowed_destination_clause(self._roots),
            )
            .order_by(StorageDestination.canonical_path.asc())
            .limit(max_results)
        )
        return list(rows.all())

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

    @staticmethod
    def _reject_duplicate_paths(folders: Iterable[SynologyFolder]) -> None:
        seen: set[str] = set()
        for folder in folders:
            if folder.path in seen:
                raise DestinationRejectedError("Synology inventory returned duplicate paths")
            seen.add(folder.path)

    def _is_allowed_interview_path(self, path: str) -> bool:
        try:
            self._require_allowed_interview_path(path)
        except ValueError:
            return False
        return True

    def _require_allowed_interview_path(self, path: str) -> str:
        for root in self._roots:
            try:
                SynologyBackend.canonical_under_root(root, path)
                return root
            except ValueError:
                continue
        raise DestinationRejectedError("Path is outside allowed interview roots")


def _allowed_destination_clause(roots: tuple[str, ...]) -> ColumnElement[bool]:
    if not roots:
        return false()
    return or_(
        *[
            predicate
            for root in roots
            for predicate in (
                StorageDestination.canonical_path == root,
                StorageDestination.canonical_path.like(f"{root}/%"),
            )
        ]
    )
