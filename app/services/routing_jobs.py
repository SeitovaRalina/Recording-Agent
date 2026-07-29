from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.routing_job import RoutingJob, RoutingJobStatus
from app.db.models.storage_destination import StorageDestination
from app.services.destinations import DestinationService

WORKER_ID = "recordings-saver"
DISPATCH_LEASE = timedelta(minutes=5)


class RoutingJobRejectedError(ValueError):
    pass


@dataclass(frozen=True)
class DispatchLease:
    job_id: uuid.UUID
    dispatch_nonce: str


@dataclass(frozen=True)
class WorkerRoutingPayload:
    job_id: uuid.UUID
    recording_id: uuid.UUID
    recording_version: int
    snapshot_hash: str
    candidate_name: str
    interview_date: str
    destinations: tuple[tuple[uuid.UUID, str], ...]


class RoutingJobService:
    """Owns durable routing leases; the worker never receives a recruiter credential."""

    async def create_or_reuse(
        self,
        session: AsyncSession,
        recording: Recording,
        recruiter: RecruiterConfig,
        destinations: list[StorageDestination],
    ) -> RoutingJob:
        if recording.status != RecordingStatus.CANDIDATE_MATCHED:
            raise RoutingJobRejectedError("Recording is not ready for autonomous routing")
        if not recording.candidate_name or recording.calendar_dtstart is None:
            raise RoutingJobRejectedError("Recording routing context is incomplete")
        snapshot: dict[str, Any] = {
            "candidate_name": recording.candidate_name[:160],
            "interview_date": recording.calendar_dtstart.date().isoformat(),
            "destinations": [
                {"id": str(destination.id), "label": destination.display_name[:160]}
                for destination in destinations[:100]
            ],
        }
        if not snapshot["destinations"]:
            raise RoutingJobRejectedError("No allowed Synology destinations are available")
        existing = await session.scalar(
            select(RoutingJob)
            .where(
                RoutingJob.recording_id == recording.id,
                RoutingJob.status.in_(
                    [RoutingJobStatus.QUEUED, RoutingJobStatus.DISPATCHED, RoutingJobStatus.ACTIVE]
                ),
            )
            .with_for_update()
        )
        if existing is not None:
            return existing
        job = RoutingJob(
            recording_id=recording.id,
            recruiter_id=recruiter.id,
            recording_version=recording.version,
            snapshot=snapshot,
            snapshot_hash=_snapshot_hash(snapshot),
        )
        session.add(job)
        await session.flush()
        return job

    async def dispatch_next(self, session: AsyncSession) -> DispatchLease | None:
        now = datetime.now(UTC)
        job = await session.scalar(
            select(RoutingJob)
            .where(
                or_(
                    RoutingJob.status == RoutingJobStatus.QUEUED,
                    (
                        RoutingJob.status.in_(
                            [RoutingJobStatus.DISPATCHED, RoutingJobStatus.ACTIVE]
                        )
                        & (RoutingJob.dispatch_lease_expires_at <= now)
                    ),
                )
            )
            .order_by(RoutingJob.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        nonce = secrets.token_urlsafe(32)
        job.status = RoutingJobStatus.DISPATCHED
        job.worker_id = WORKER_ID
        job.dispatch_nonce_hash = _nonce_hash(nonce)
        job.dispatch_lease_expires_at = now + DISPATCH_LEASE
        job.attempts += 1
        job.updated_at = now
        await session.flush()
        return DispatchLease(job_id=job.id, dispatch_nonce=nonce)

    async def activate(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        dispatch_nonce: str,
    ) -> WorkerRoutingPayload:
        job, recording = await self._lease_owned_job(
            session, job_id=job_id, worker_id=worker_id, dispatch_nonce=dispatch_nonce
        )
        if job.status == RoutingJobStatus.DISPATCHED:
            job.status = RoutingJobStatus.ACTIVE
            job.activated_at = datetime.now(UTC)
            job.updated_at = job.activated_at
        snapshot = _validated_snapshot(job)
        if (
            recording.version != job.recording_version
            or recording.status != RecordingStatus.CANDIDATE_MATCHED
        ):
            raise RoutingJobRejectedError("Recording changed after routing job creation")
        destinations = tuple(
            (uuid.UUID(str(item["id"])), str(item["label"]))
            for item in cast(list[dict[str, object]], snapshot["destinations"])
        )
        return WorkerRoutingPayload(
            job_id=job.id,
            recording_id=recording.id,
            recording_version=job.recording_version,
            snapshot_hash=job.snapshot_hash,
            candidate_name=str(snapshot["candidate_name"]),
            interview_date=str(snapshot["interview_date"]),
            destinations=destinations,
        )

    async def resolve(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        dispatch_nonce: str,
        snapshot_hash: str,
        destination_id: uuid.UUID,
        destination_service: DestinationService,
    ) -> tuple[Recording, RecruiterConfig]:
        job, recording = await self._lease_owned_job(
            session, job_id=job_id, worker_id=worker_id, dispatch_nonce=dispatch_nonce
        )
        if job.status == RoutingJobStatus.RESOLVED:
            return await self._resolved_recording(session, job)
        self._require_active_snapshot(job, recording, snapshot_hash)
        snapshot = _validated_snapshot(job)
        allowed = {
            uuid.UUID(str(item["id"]))
            for item in cast(list[dict[str, object]], snapshot["destinations"])
        }
        if destination_id not in allowed:
            raise RoutingJobRejectedError("Destination is not in the job snapshot")
        destination = await session.scalar(
            select(StorageDestination).where(
                StorageDestination.id == destination_id,
                StorageDestination.recruiter_id == job.recruiter_id,
                StorageDestination.writable.is_(True),
                StorageDestination.symlink_safe.is_(True),
            )
        )
        if destination is None:
            raise RoutingJobRejectedError("Destination is unavailable")
        recruiter = await session.get(RecruiterConfig, job.recruiter_id)
        if recruiter is None or recording.disk_owner_email != recruiter.email:
            raise RoutingJobRejectedError("Routing job ownership is invalid")
        await destination_service.resolve(session, recruiter, destination_id)
        recording.storage_destination_id = destination.id
        recording.storage_key = None
        recording.content_identity = (
            recording.content_identity or recording.disk_md5 or recording.disk_file_id
        )
        recording.transition_to(RecordingStatus.TRANSFER_STARTED)
        recording.version += 1
        job.status = RoutingJobStatus.RESOLVED
        job.resolved_destination_id = destination.id
        job.updated_at = datetime.now(UTC)
        return recording, recruiter

    async def defer(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        dispatch_nonce: str,
        snapshot_hash: str,
        reason: Literal["ambiguous", "no_match", "model_error"],
    ) -> tuple[Recording, RecruiterConfig]:
        job, recording = await self._lease_owned_job(
            session, job_id=job_id, worker_id=worker_id, dispatch_nonce=dispatch_nonce
        )
        self._require_active_snapshot(job, recording, snapshot_hash)
        recruiter = await session.get(RecruiterConfig, job.recruiter_id)
        if recruiter is None or recording.disk_owner_email != recruiter.email:
            raise RoutingJobRejectedError("Routing job ownership is invalid")
        snapshot = _validated_snapshot(job)
        recording.transition_to(RecordingStatus.MANUAL_REVIEW_REQUIRED)
        recording.manual_review_reason = f"autonomous_routing_{reason}"
        recording.manual_review_candidates = [
            {"destination_id": item["id"], "name": item["label"]}
            for item in cast(list[dict[str, object]], snapshot["destinations"])
        ]
        recording.version += 1
        job.status = RoutingJobStatus.DEFERRED
        job.defer_reason = reason
        job.updated_at = datetime.now(UTC)
        return recording, recruiter

    async def _lease_owned_job(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        dispatch_nonce: str,
    ) -> tuple[RoutingJob, Recording]:
        if worker_id != WORKER_ID:
            raise RoutingJobRejectedError("Worker is not authorized")
        job = await session.scalar(
            select(RoutingJob).where(RoutingJob.id == job_id).with_for_update()
        )
        if job is None or job.dispatch_lease_expires_at is None:
            raise RoutingJobRejectedError("Routing job is unavailable")
        if job.dispatch_lease_expires_at <= datetime.now(UTC):
            raise RoutingJobRejectedError("Routing lease has expired")
        if not job.dispatch_nonce_hash or not hmac.compare_digest(
            job.dispatch_nonce_hash, _nonce_hash(dispatch_nonce)
        ):
            raise RoutingJobRejectedError("Routing lease is invalid")
        if job.worker_id != worker_id:
            raise RoutingJobRejectedError("Routing worker does not own this job")
        recording = await session.get(Recording, job.recording_id)
        if recording is None:
            raise RoutingJobRejectedError("Recording is unavailable")
        return job, recording

    @staticmethod
    def _require_active_snapshot(job: RoutingJob, recording: Recording, snapshot_hash: str) -> None:
        if job.status != RoutingJobStatus.ACTIVE:
            raise RoutingJobRejectedError("Routing job is not active")
        if not hmac.compare_digest(job.snapshot_hash, snapshot_hash):
            raise RoutingJobRejectedError("Routing snapshot is stale")
        if (
            recording.version != job.recording_version
            or recording.status != RecordingStatus.CANDIDATE_MATCHED
        ):
            raise RoutingJobRejectedError("Recording changed after routing job creation")

    @staticmethod
    async def _resolved_recording(
        session: AsyncSession, job: RoutingJob
    ) -> tuple[Recording, RecruiterConfig]:
        recording = await session.get(Recording, job.recording_id)
        recruiter = await session.get(RecruiterConfig, job.recruiter_id)
        if recording is None or recruiter is None:
            raise RoutingJobRejectedError("Resolved routing job is unavailable")
        return recording, recruiter


def _snapshot_hash(snapshot: Mapping[str, object]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _nonce_hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def _validated_snapshot(job: RoutingJob) -> dict[str, Any]:
    snapshot = job.snapshot
    destinations = snapshot.get("destinations") if isinstance(snapshot, dict) else None
    if (
        not isinstance(snapshot, dict)
        or not isinstance(snapshot.get("candidate_name"), str)
        or not isinstance(snapshot.get("interview_date"), str)
        or not isinstance(destinations, list)
        or not destinations
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("label"), str)
            for item in destinations
        )
    ):
        raise RoutingJobRejectedError("Routing snapshot is malformed")
    return snapshot
