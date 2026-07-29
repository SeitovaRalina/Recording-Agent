from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.engine import get_session
from app.routers.events import verify_openclaw_secret
from app.scheduler.cron import _resume_transfer_recording
from app.services.reviews import ReviewRejectedError
from app.services.routing_jobs import (
    DispatchLease,
    RoutingJobRejectedError,
    RoutingJobService,
    WorkerRoutingPayload,
)

dispatcher_router = APIRouter(
    prefix="/internal/routing-jobs",
    tags=["routing-dispatcher"],
    dependencies=[Depends(verify_openclaw_secret)],
)
worker_router = APIRouter(prefix="/internal/routing-jobs", tags=["routing-worker"])
Session = Annotated[AsyncSession, Depends(get_session)]


class DispatchResponse(BaseModel):
    job_id: uuid.UUID
    dispatch_nonce: str = Field(min_length=32, max_length=256, repr=False)


class WorkerLeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: Literal["recordings-saver"]
    dispatch_nonce: SecretStr


class RoutingDestination(BaseModel):
    id: uuid.UUID
    label: str


class ActivateResponse(BaseModel):
    job_id: uuid.UUID
    recording_id: uuid.UUID
    recording_version: int
    snapshot_hash: str
    candidate_name: str
    interview_date: str
    destinations: list[RoutingDestination]


class ResolveRequest(WorkerLeaseRequest):
    snapshot_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    destination_id: uuid.UUID


class DeferRequest(WorkerLeaseRequest):
    snapshot_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    reason: Literal["ambiguous", "no_match", "model_error"]


class WorkerActionResponse(BaseModel):
    job_id: uuid.UUID
    recording_id: uuid.UUID
    status: str


def _routing_service(request: Request) -> RoutingJobService:
    return cast(RoutingJobService, request.app.state.routing_job_service)


def _require_autonomous_routing(request: Request) -> None:
    settings = cast(Settings, request.app.state.settings)
    if not settings.autonomous_routing_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Autonomous routing is disabled",
        )


@dispatcher_router.post("/dispatch", response_model=DispatchResponse | None)
async def dispatch_next(session: Session, request: Request) -> DispatchResponse | None:
    _require_autonomous_routing(request)
    lease = await _routing_service(request).dispatch_next(session)
    await session.commit()
    if lease is None:
        return None
    return _dispatch_response(lease)


@worker_router.post("/{job_id}/activate", response_model=ActivateResponse)
async def activate_job(
    job_id: uuid.UUID, body: WorkerLeaseRequest, session: Session, request: Request
) -> ActivateResponse:
    _require_autonomous_routing(request)
    try:
        payload = await _routing_service(request).activate(
            session,
            job_id=job_id,
            worker_id=body.worker_id,
            dispatch_nonce=body.dispatch_nonce.get_secret_value(),
        )
        await session.commit()
    except RoutingJobRejectedError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _activate_response(payload)


@worker_router.post("/{job_id}/resolve", response_model=WorkerActionResponse)
async def resolve_job(
    job_id: uuid.UUID, body: ResolveRequest, session: Session, request: Request
) -> WorkerActionResponse:
    _require_autonomous_routing(request)
    destination_service = request.app.state.destination_service
    if destination_service is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Synology routing is disabled"
        )
    try:
        recording, recruiter = await _routing_service(request).resolve(
            session,
            job_id=job_id,
            worker_id=body.worker_id,
            dispatch_nonce=body.dispatch_nonce.get_secret_value(),
            snapshot_hash=body.snapshot_hash,
            destination_id=body.destination_id,
            destination_service=destination_service,
        )
        recording_id = recording.id
        await session.commit()
    except (RoutingJobRejectedError, PermissionError, ValueError) as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    resumed = await _resume_transfer_recording(
        recording_id,
        recruiter,
        request.app.state.session_factory,
        request.app.state.disk_scanner,
        request.app.state.candidate_service,
        request.app.state.transfer_service,
        request.app.state.status_service,
        request.app.state.notion_client,
        request.app.state.settings,
    )
    if not resumed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Transfer is already owned"
        )
    return WorkerActionResponse(
        job_id=job_id, recording_id=recording_id, status="transfer_started"
    )


@worker_router.post("/{job_id}/defer", response_model=WorkerActionResponse)
async def defer_job(
    job_id: uuid.UUID, body: DeferRequest, session: Session, request: Request
) -> WorkerActionResponse:
    _require_autonomous_routing(request)
    try:
        recording, recruiter = await _routing_service(request).defer(
            session,
            job_id=job_id,
            worker_id=body.worker_id,
            dispatch_nonce=body.dispatch_nonce.get_secret_value(),
            snapshot_hash=body.snapshot_hash,
            reason=body.reason,
        )
        review = await request.app.state.review_service.enqueue_review(
            session, recording, recruiter
        )
        await request.app.state.question_queue_service.queue_routing_defer_notification(
            session, job_id=job_id, recording=recording, review=review
        )
        await session.commit()
    except (RoutingJobRejectedError, ReviewRejectedError) as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return WorkerActionResponse(
        job_id=job_id, recording_id=recording.id, status="awaiting_recruiter"
    )


def _dispatch_response(lease: DispatchLease) -> DispatchResponse:
    return DispatchResponse(job_id=lease.job_id, dispatch_nonce=lease.dispatch_nonce)


def _activate_response(payload: WorkerRoutingPayload) -> ActivateResponse:
    return ActivateResponse(
        job_id=payload.job_id,
        recording_id=payload.recording_id,
        recording_version=payload.recording_version,
        snapshot_hash=payload.snapshot_hash,
        candidate_name=payload.candidate_name,
        interview_date=payload.interview_date,
        destinations=[
            RoutingDestination(id=item[0], label=item[1]) for item in payload.destinations
        ],
    )
