import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.routing_job import RoutingJob, RoutingJobStatus
from app.db.models.storage_destination import StorageDestination
from app.routers.routing_jobs import DeferRequest, _require_autonomous_routing, defer_job
from app.services.routing_jobs import RoutingJobRejectedError, RoutingJobService


def test_autonomous_routing_execution_requires_explicit_opt_in() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=Settings())))

    with pytest.raises(HTTPException, match="Autonomous routing is disabled") as error:
        _require_autonomous_routing(request)

    assert error.value.status_code == 409
    _require_autonomous_routing(
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(settings=Settings(autonomous_routing_enabled=True))
            )
        )
    )


async def _ready_job(session: AsyncSession) -> tuple[RoutingJobService, RoutingJob, str, uuid.UUID]:
    recruiter = RecruiterConfig(
        email="recruiter@example.com",
        notion_database_id="database",
        synology_base_folder="/home/Recruiting-E",
    )
    recording = Recording(
        disk_file_id="routing-job-file",
        disk_path="disk:/routing-job-file.webm",
        disk_filename="routing-job-file.webm",
        disk_owner_email=recruiter.email,
        candidate_name="Ivan Ivanov",
        calendar_dtstart=datetime(2026, 7, 29, tzinfo=UTC),
        status=RecordingStatus.CANDIDATE_MATCHED,
        version=4,
    )
    session.add_all([recruiter, recording])
    await session.flush()
    destination = StorageDestination(
        recruiter_id=recruiter.id,
        canonical_path="/home/Recruiting-E/Android",
        display_name="Android",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    session.add(destination)
    await session.flush()
    service = RoutingJobService()
    job = await service.create_or_reuse(session, recording, recruiter, [destination])
    lease = await service.dispatch_next(session)
    assert lease is not None
    await session.commit()
    return service, job, lease.dispatch_nonce, destination.id


@pytest.mark.anyio
async def test_dispatch_is_idempotent_and_worker_payload_is_bounded(session: AsyncSession) -> None:
    service, job, nonce, destination_id = await _ready_job(session)

    assert await service.dispatch_next(session) is None
    payload = await service.activate(
        session, job_id=job.id, worker_id="recordings-saver", dispatch_nonce=nonce
    )

    assert payload.job_id == job.id
    assert payload.recording_version == 4
    assert payload.destinations == ((destination_id, "Android"),)
    assert "canonical_path" not in str(payload)
    stored = await session.get(RoutingJob, job.id)
    assert stored is not None
    assert stored.status == RoutingJobStatus.ACTIVE
    assert stored.dispatch_nonce_hash != nonce


@pytest.mark.anyio
async def test_worker_rejects_wrong_nonce_and_non_snapshot_destination(
    session: AsyncSession,
) -> None:
    service, job, nonce, _ = await _ready_job(session)
    with pytest.raises(RoutingJobRejectedError, match="lease is invalid"):
        await service.activate(
            session, job_id=job.id, worker_id="recordings-saver", dispatch_nonce="wrong"
        )
    payload = await service.activate(
        session, job_id=job.id, worker_id="recordings-saver", dispatch_nonce=nonce
    )
    with pytest.raises(RoutingJobRejectedError, match="not in the job snapshot"):
        await service.resolve(
            session,
            job_id=job.id,
            worker_id="recordings-saver",
            dispatch_nonce=nonce,
            snapshot_hash=payload.snapshot_hash,
            destination_id=uuid.uuid4(),
            destination_service=AsyncMock(),
        )


@pytest.mark.anyio
async def test_resolve_revalidates_destination_and_claims_transfer(session: AsyncSession) -> None:
    service, job, nonce, destination_id = await _ready_job(session)
    payload = await service.activate(
        session, job_id=job.id, worker_id="recordings-saver", dispatch_nonce=nonce
    )
    destination_service = AsyncMock()
    recording, recruiter = await service.resolve(
        session,
        job_id=job.id,
        worker_id="recordings-saver",
        dispatch_nonce=nonce,
        snapshot_hash=payload.snapshot_hash,
        destination_id=destination_id,
        destination_service=destination_service,
    )

    assert recruiter.email == "recruiter@example.com"
    assert recording.storage_destination_id == destination_id
    assert recording.status == RecordingStatus.TRANSFER_STARTED
    assert recording.version == 5
    destination_service.resolve.assert_awaited_once_with(session, recruiter, destination_id)
    stored = await session.scalar(select(RoutingJob).where(RoutingJob.id == job.id))
    assert stored is not None
    assert stored.status == RoutingJobStatus.RESOLVED


@pytest.mark.anyio
async def test_defer_creates_single_recruiter_review_state(session: AsyncSession) -> None:
    service, job, nonce, _ = await _ready_job(session)
    payload = await service.activate(
        session, job_id=job.id, worker_id="recordings-saver", dispatch_nonce=nonce
    )
    recording, recruiter = await service.defer(
        session,
        job_id=job.id,
        worker_id="recordings-saver",
        dispatch_nonce=nonce,
        snapshot_hash=payload.snapshot_hash,
        reason="ambiguous",
    )

    assert recording.status == RecordingStatus.MANUAL_REVIEW_REQUIRED
    assert recruiter.email == "recruiter@example.com"
    assert recording.manual_review_reason == "autonomous_routing_ambiguous"
    assert recording.manual_review_candidates == [
        {"destination_id": str(payload.destinations[0][0]), "name": "Android"}
    ]


@pytest.mark.anyio
async def test_defer_enqueues_one_backend_owned_question_and_outbox() -> None:
    recording = SimpleNamespace(id=uuid.uuid4(), version=5)
    recruiter = SimpleNamespace()
    review = SimpleNamespace(
        id=uuid.uuid4(), recruiter_user_id="recruiter", mattermost_channel_id="dm"
    )
    routing = SimpleNamespace(defer=AsyncMock(return_value=(recording, recruiter)))
    reviews = SimpleNamespace(enqueue_review=AsyncMock(return_value=review))
    queue = SimpleNamespace(queue_routing_defer_notification=AsyncMock())
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(autonomous_routing_enabled=True),
                routing_job_service=routing,
                review_service=reviews,
                question_queue_service=queue,
            )
        )
    )
    session = AsyncMock()
    job_id = uuid.uuid4()
    response = await defer_job(
        job_id,
        DeferRequest(
            worker_id="recordings-saver",
            dispatch_nonce="nonce_value_123456",
            snapshot_hash="a" * 64,
            reason="ambiguous",
        ),
        session,
        request,
    )

    assert response.status == "awaiting_recruiter"
    reviews.enqueue_review.assert_awaited_once_with(session, recording, recruiter)
    queue.queue_routing_defer_notification.assert_awaited_once_with(
        session, job_id=job_id, recording=recording, review=review
    )
