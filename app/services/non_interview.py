from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.destinations import DestinationService
from app.services.transfer import TransferService


class NonInterviewRejectedError(ValueError):
    pass


class NonInterviewService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        destinations: DestinationService,
        transfer: TransferService,
    ) -> None:
        self._session_factory = session_factory
        self._destinations = destinations
        self._transfer = transfer

    async def route(
        self,
        *,
        recording_id: uuid.UUID,
        recruiter: RecruiterConfig,
        destination_id: uuid.UUID,
        expected_version: int,
    ) -> Recording:
        async with self._session_factory() as session:
            recording = await session.scalar(
                select(Recording).where(Recording.id == recording_id).with_for_update()
            )
            if recording is None or recording.disk_owner_email != recruiter.email:
                raise NonInterviewRejectedError("Recording not found")
            if recording.version != expected_version:
                raise NonInterviewRejectedError("Recording version is stale")
            if recording.status != RecordingStatus.MANUAL_REVIEW_REQUIRED:
                raise NonInterviewRejectedError("Recording is not awaiting a route decision")
            destination = await self._destinations.resolve(session, recruiter, destination_id)
            filename = recording.generated_filename or recording.disk_filename
            recording.route_type = "non_interview"
            recording.storage_destination_id = destination.id
            recording.generated_filename = filename
            storage_key = f"{destination.canonical_path.rstrip('/')}/{filename}"
            collision = await session.scalar(
                select(Recording.id).where(
                    Recording.storage_key == storage_key,
                    Recording.id != recording.id,
                )
            )
            if collision is not None:
                raise NonInterviewRejectedError(
                    "Storage destination is already owned by another recording"
                )
            recording.storage_key = storage_key
            recording.content_identity = (
                recording.content_identity or recording.disk_md5 or recording.disk_file_id
            )
            recording.transition_to(RecordingStatus.TRANSFER_STARTED)
            recording.version += 1
            await session.commit()

        async with self._session_factory() as session:
            recording = await session.get(Recording, recording_id)
            if recording is None:
                raise NonInterviewRejectedError("Recording disappeared")
            result = await self._transfer.transfer(recording, recruiter, "non-interview", session)
            recording.synology_folder_path = result.folder_path
            recording.synology_file_path = result.file_path
            recording.transition_to(RecordingStatus.UPLOADED_TO_SYNOLOGY)
            await session.commit()
            link = await self._transfer.create_share_link(result.file_path)
            recording.synology_share_url = link
            recording.storage_is_durable = True
            recording.transition_to(RecordingStatus.SYNOLOGY_LINK_CREATED)
            recording.transition_to(RecordingStatus.COMPLETED)
            recording.completed_at = datetime.now(UTC)
            recording.version += 1
            await session.commit()
            return recording
