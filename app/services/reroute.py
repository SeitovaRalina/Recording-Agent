from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recording_reroute import RecordingReroute, RerouteStatus
from app.db.models.recording_storage_artifact import RecordingStorageArtifact
from app.db.models.recruiter_config import RecruiterConfig
from app.services.destinations import DestinationService
from app.services.storage import StorageCollisionError
from app.tools.notion import NotionClient
from app.tools.synology import SynologyBackend


class RerouteRejectedError(RuntimeError):
    pass


@dataclass(frozen=True)
class RerouteResult:
    recording_id: uuid.UUID
    version: int
    share_url: str
    replayed: bool = False


class RerouteService:
    def __init__(
        self,
        synology: SynologyBackend,
        destinations: DestinationService,
        notion: NotionClient,
        settings: Settings,
    ) -> None:
        self._synology = synology
        self._destinations = destinations
        self._notion = notion
        self._settings = settings

    async def reroute(
        self,
        session: AsyncSession,
        *,
        recording_id: uuid.UUID,
        recruiter: RecruiterConfig,
        destination_id: uuid.UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RerouteResult:
        recording = await session.scalar(
            select(Recording).where(Recording.id == recording_id).with_for_update()
        )
        if recording is None or recording.disk_owner_email != recruiter.email:
            raise RerouteRejectedError("Recording not found")
        existing = await session.scalar(
            select(RecordingReroute).where(
                RecordingReroute.recording_id == recording_id,
                RecordingReroute.idempotency_key == idempotency_key,
            )
        )
        if existing is not None and existing.status == RerouteStatus.COMPLETED:
            if not existing.target_share_url:
                raise RerouteRejectedError("Completed reroute has no link")
            return RerouteResult(recording_id, recording.version, existing.target_share_url, True)
        if existing is not None and (
            existing.destination_id != destination_id
            or existing.expected_version != expected_version
        ):
            raise RerouteRejectedError("Reroute idempotency key has different immutable inputs")
        now = datetime.now(UTC)
        if (
            recording.processing_lease_token
            and recording.processing_lease_expires_at
            and recording.processing_lease_expires_at > now
        ):
            raise RerouteRejectedError("Recording has an active operation lease")
        if recording.version != expected_version:
            raise RerouteRejectedError("Recording version is stale")
        if recording.status not in {RecordingStatus.COMPLETED, RecordingStatus.NOTION_UPDATED}:
            raise RerouteRejectedError("Recording is not in a reroutable terminal state")
        if not recording.storage_is_durable or not recording.notion_page_id:
            raise RerouteRejectedError("Recording is legacy or has no durable Notion identity")
        artifact = await session.scalar(
            select(RecordingStorageArtifact).where(
                RecordingStorageArtifact.recording_id == recording.id,
                RecordingStorageArtifact.is_active.is_(True),
            )
        )
        if artifact is None:
            raise RerouteRejectedError("Recording is legacy and cannot be safely rerouted")
        destination = await self._destinations.resolve(session, recruiter, destination_id)
        filename = recording.generated_filename or recording.disk_filename
        owner: dict[str, object] = {
            "content_identity": recording.content_identity
            or recording.disk_md5
            or recording.disk_file_id,
            "recording_id": str(recording.id),
            "size": recording.disk_size_bytes,
            "v": 1,
        }
        operation = existing or RecordingReroute(
            recording_id=recording.id,
            source_artifact_id=artifact.id,
            destination_id=destination.id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        lease_token = uuid.uuid4().hex
        recording.processing_lease_token = lease_token
        recording.processing_lease_expires_at = now + timedelta(minutes=10)
        session.add(operation)
        await session.commit()
        try:
            root = _shared_allowed_root(
                self._settings.synology_interview_roots,
                artifact.file_path,
                destination.canonical_path,
            )
            if operation.status == RerouteStatus.PENDING:
                intended_target = self._synology.canonical_under_root(
                    root, f"{destination.canonical_path.rstrip('/')}/{filename}"
                )
                # Intent is durable before NAS mutation. Retry may reconcile this exact target only.
                if operation.target_file_path is None:
                    operation.target_file_path = intended_target
                    await session.commit()
                elif operation.target_file_path != intended_target:
                    raise RerouteRejectedError(
                        "Reroute target checkpoint does not match destination"
                    )
                if await self._synology._file_size(intended_target) is not None:  # noqa: SLF001
                    if await self._synology._file_size(artifact.file_path) is None:  # noqa: SLF001
                        await self._synology.verify_moved_target(
                            target_path=intended_target,
                            filename=filename,
                            root=root,
                            expected_size=recording.disk_size_bytes,
                            expected_owner=owner,
                        )
                        operation.status = RerouteStatus.MOVED
                        await session.commit()
                    else:
                        raise RerouteRejectedError(
                            "Reroute target exists while source remains; NAS mutation is ambiguous"
                        )
            if operation.status == RerouteStatus.PENDING:
                moved = await self._synology.copy_move_verified(
                    source_path=artifact.file_path,
                    target_folder=destination.canonical_path,
                    filename=filename,
                    root=root,
                    expected_size=recording.disk_size_bytes,
                    expected_owner=owner,
                )
                operation.status = RerouteStatus.MOVED
                operation.target_file_path = moved.target_path
                await session.commit()
            if operation.status == RerouteStatus.MOVED:
                if not operation.target_file_path:
                    raise RerouteRejectedError("Moved reroute has no durable target checkpoint")
                # A retry first recovers an exact-path link. DSM link listing is the durable
                # identity source; no second link is created while a prior link is discoverable.
                url = await self._synology.find_public_share_link(operation.target_file_path)
                if url is None:
                    url = await self._synology.create_share_link(operation.target_file_path)
                operation.status = RerouteStatus.LINKED
                operation.target_share_url = url
                await session.commit()
            if not operation.target_file_path or not operation.target_share_url:
                raise RerouteRejectedError("Reroute has no durable target/link checkpoint")
            url = operation.target_share_url
            # The old card value remains until the new public link was proven and persisted.
            if operation.status == RerouteStatus.LINKED:
                await self._notion.replace_recording_link(
                    recording.notion_page_id,
                    recording_prop=self._settings.notion_recording_prop,
                    filename=filename,
                    url=url,
                )
                current = await self._notion.get_recording_field(
                    recording.notion_page_id, self._settings.notion_recording_prop
                )
                if not _field_has_exact_url(current, url):
                    raise RerouteRejectedError(
                        "Notion did not persist the replacement recording link"
                    )
                operation.status = RerouteStatus.NOTION_UPDATED
                await session.commit()
            new_artifact = RecordingStorageArtifact(
                recording_id=recording.id,
                destination_id=destination.id,
                folder_path=destination.canonical_path,
                file_path=operation.target_file_path,
                share_url=url,
                owner_marker_path=(
                    f"{destination.canonical_path.rstrip('/')}/.{filename}.recording-agent-owner.json"
                ),
                size_bytes=recording.disk_size_bytes,
                is_active=True,
            )
            await session.execute(
                update(RecordingStorageArtifact)
                .where(RecordingStorageArtifact.id == artifact.id)
                .values(is_active=False)
            )
            session.add(new_artifact)
            recording.synology_folder_path = destination.canonical_path
            recording.synology_file_path = operation.target_file_path
            recording.synology_share_url = url
            recording.storage_destination_id = destination.id
            recording.version += 1
            operation.status = RerouteStatus.COMPLETED
            recording.processing_lease_token = None
            recording.processing_lease_expires_at = None
            await session.commit()
            return RerouteResult(recording.id, recording.version, url)
        except (StorageCollisionError, RerouteRejectedError, ValueError, PermissionError) as error:
            operation.status = RerouteStatus.FAILED
            operation.error = str(error)[:500]
            recording.processing_lease_token = None
            recording.processing_lease_expires_at = None
            await session.commit()
            raise RerouteRejectedError(str(error)) from error
        except Exception as error:
            # Keep the durable phase checkpoint; retry does not repeat the NAS move.
            recording.processing_lease_token = None
            recording.processing_lease_expires_at = None
            await session.commit()
            raise RerouteRejectedError("Reroute external operation is retryable") from error


def _field_has_exact_url(field: dict[str, object], url: str) -> bool:
    files = field.get("files")
    if not isinstance(files, list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("external"), dict)
        and item["external"].get("url") == url
        for item in files
    )


def capability_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _shared_allowed_root(roots: tuple[str, ...], source: str, destination: str) -> str:
    for root in roots:
        try:
            SynologyBackend.canonical_under_root(root, source)
            SynologyBackend.canonical_under_root(root, destination)
            return root
        except ValueError:
            continue
    raise RerouteRejectedError("Source and target do not share an allowed Synology root")
