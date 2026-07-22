from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import get_session
from app.db.models.intent_replay import IntentReplay
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.routers.events import verify_openclaw_secret
from app.scheduler.cron import ScanSummary, _resume_transfer_recording, scan_recruiter
from app.services.canary import enforce_recruiter_scope
from app.services.intents import (
    IntentRejectedError,
    claim_intent,
    complete_intent,
    request_fingerprint,
)
from app.services.question_queue import QuestionAnswer, QuestionQueueService
from app.services.reviews import ReviewRejectedError, ReviewService

router = APIRouter(
    prefix="/tools",
    tags=["openclaw-tools"],
    dependencies=[Depends(verify_openclaw_secret)],
)
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recruiter_email: str = Field(min_length=3, max_length=320)
    scope: Literal["test", "production"] = "test"
    idempotency_key: str = Field(min_length=8, max_length=200)


class ScanItem(BaseModel):
    id: uuid.UUID
    filename: str
    candidate_name: str | None
    status: RecordingStatus
    is_new: bool
    requires_review: bool
    review_reason: str | None
    generated_filename: str | None
    safe_link: str | None
    error: str | None


class ScanResponse(BaseModel):
    accepted: bool
    recruiter_email: str
    discovered: int
    inserted: int
    skipped_legacy: int = 0
    matched: int
    manual_review: int
    without_review: int = 0
    failed: int
    failed_recordings: int = 0
    processed: int = 0
    items_truncated: bool = False
    items: list[ScanItem] = Field(default_factory=list)


class RecordingStatusItem(BaseModel):
    id: uuid.UUID
    filename: str
    generated_filename: str | None
    candidate_name: str | None
    status: RecordingStatus
    requires_review: bool
    review_reason: str | None
    version: int
    found_at: str
    safe_link: str | None
    error: str | None


class RecordingStatusResponse(BaseModel):
    items: list[RecordingStatusItem]
    count: int


class ReviewContext(BaseModel):
    review_id: uuid.UUID
    recording_id: uuid.UUID
    recording_version: int
    filename: str
    reason: str
    choices: list[dict[str, object]]
    expires_at: str


class ReviewMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recruiter_user_id: str = Field(min_length=1, max_length=200)
    mattermost_thread_id: str = Field(min_length=1, max_length=200)
    token: SecretStr
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=200)


class ReviewResolveRequest(ReviewMutationRequest):
    choice: int = Field(ge=1, le=10)


class ReviewMutationResponse(BaseModel):
    review_id: uuid.UUID
    recording_id: uuid.UUID
    status: str
    version: int
    replayed: bool


class QuestionItem(BaseModel):
    question_id: uuid.UUID
    question_set_id: uuid.UUID
    recording_id: uuid.UUID
    recording_version: int
    filename: str
    reason: str
    choices: list[dict[str, object]]
    expires_at: str


class QuestionListResponse(BaseModel):
    items: list[QuestionItem]
    count: int


class QuestionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    question_set_id: uuid.UUID
    action: Literal["resolve", "ignore"]
    capability: SecretStr
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=200)
    choice: int | None = Field(default=None, ge=1, le=10)


class QuestionBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recruiter_user_id: str = Field(min_length=1, max_length=200)
    mattermost_dm_channel_id: str = Field(min_length=1, max_length=200)
    actions: list[QuestionActionRequest] = Field(min_length=1, max_length=50)


class QuestionAccepted(BaseModel):
    question_id: uuid.UUID
    recording_id: uuid.UUID
    status: str
    version: int
    replayed: bool


class QuestionRejected(BaseModel):
    question_id: uuid.UUID
    reason: str


class QuestionBatchResponse(BaseModel):
    accepted: list[QuestionAccepted]
    rejected: list[QuestionRejected]
    pending: list[uuid.UUID]


@router.post("/scans/trigger", response_model=ScanResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_scan(
    body: ScanRequest, request: Request, session: Session, settings: AppSettings
) -> ScanResponse:
    if settings.test_mode_enabled and body.scope != "test":
        raise HTTPException(status_code=403, detail="Production scan is forbidden in test mode")
    operation = f"scan:{body.scope}"
    recruiter = await session.scalar(
        select(RecruiterConfig).where(
            RecruiterConfig.email == body.recruiter_email,
            RecruiterConfig.active.is_(True),
        )
    )
    if recruiter is None:
        raise HTTPException(status_code=404, detail="Active recruiter not found")
    try:
        enforce_recruiter_scope(settings, recruiter)
        claim = await claim_intent(
            session,
            actor=recruiter.email,
            operation=operation,
            idempotency_key=body.idempotency_key,
            fingerprint=request_fingerprint(body.model_dump(mode="json")),
            ttl_seconds=settings.intent_claim_ttl_seconds,
        )
    except (PermissionError, IntentRejectedError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if claim.completed_response is not None:
        return ScanResponse.model_validate(claim.completed_response)
    try:
        result = await scan_recruiter(
            recruiter,
            request.app.state.session_factory,
            request.app.state.disk_scanner,
            request.app.state.calendar_client,
            request.app.state.matcher,
            settings,
            candidate_service=request.app.state.candidate_service,
            transfer_service=request.app.state.transfer_service,
            status_service=request.app.state.status_service,
            notion=request.app.state.notion_client,
            review_service=request.app.state.review_service,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    scan_ids = list(dict.fromkeys(result.recording_ids))
    status_counts: dict[RecordingStatus, int] = {}
    rows: list[Recording] = []
    if scan_ids:
        status_counts = {
            recording_status: count
            for recording_status, count in (
                await session.execute(
                    select(Recording.status, func.count())
                    .where(
                        Recording.disk_owner_email == recruiter.email,
                        Recording.id.in_(scan_ids),
                    )
                    .group_by(Recording.status)
                )
            ).all()
        }
        rows = list(
            (
                await session.scalars(
                    select(Recording)
                    .where(
                        Recording.disk_owner_email == recruiter.email,
                        Recording.id.in_(scan_ids),
                    )
                    .order_by(Recording.found_at.asc())
                    .limit(50)
                )
            ).all()
        )
    response = _scan_response(recruiter.email, result, rows, status_counts)
    await complete_intent(session, claim, response.model_dump(mode="json"))
    return response


@router.get("/recordings/status", response_model=RecordingStatusResponse)
async def recording_status(
    session: Session,
    settings: AppSettings,
    recruiter_user_id: Annotated[str, Query(min_length=1, max_length=200)],
    on_date: date | None = None,
    candidate: Annotated[str | None, Query(max_length=200)] = None,
    recording_id: uuid.UUID | None = None,
    recording_status: Annotated[RecordingStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> RecordingStatusResponse:
    recruiter = await session.scalar(
        select(RecruiterConfig).where(
            RecruiterConfig.mattermost_user_id == recruiter_user_id,
            RecruiterConfig.active.is_(True),
        )
    )
    if recruiter is None:
        raise HTTPException(status_code=404, detail="Recruiter not found")
    try:
        enforce_recruiter_scope(settings, recruiter)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    statement: Select[tuple[Recording]] = select(Recording).where(
        Recording.disk_owner_email == recruiter.email
    )
    if on_date is not None:
        day_start = datetime.combine(on_date, time.min, UTC)
        statement = statement.where(
            Recording.found_at >= day_start,
            Recording.found_at < day_start + timedelta(days=1),
        )
    if candidate:
        statement = statement.where(Recording.candidate_name.ilike(f"%{candidate}%"))
    if recording_id:
        statement = statement.where(Recording.id == recording_id)
    if recording_status:
        statement = statement.where(Recording.status == recording_status)
    rows = list(
        (await session.scalars(statement.order_by(Recording.found_at.desc()).limit(limit))).all()
    )
    items = [
        RecordingStatusItem(
            id=row.id,
            filename=row.disk_filename,
            generated_filename=row.generated_filename,
            candidate_name=row.candidate_name,
            status=row.status,
            requires_review=row.status == RecordingStatus.MANUAL_REVIEW_REQUIRED,
            review_reason=row.manual_review_reason,
            version=row.version,
            found_at=row.found_at.isoformat(),
            safe_link=row.synology_share_url,
            error=row.error_message,
        )
        for row in rows
    ]
    return RecordingStatusResponse(items=items, count=len(items))


@router.get("/reviews/{review_id}", response_model=ReviewContext)
async def review_context(
    review_id: uuid.UUID,
    session: Session,
    request: Request,
    recruiter_user_id: Annotated[str, Query(min_length=1, max_length=200)],
    mattermost_thread_id: Annotated[str, Query(min_length=1, max_length=200)],
    token: Annotated[SecretStr, Header(alias="X-Review-Token")],
) -> ReviewContext:
    service = _review_service(request)
    try:
        review = await service.get_bound_review(
            session,
            review_id=review_id,
            recruiter_user_id=recruiter_user_id,
            thread_id=mattermost_thread_id,
            token=token.get_secret_value(),
        )
    except ReviewRejectedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    choices = review.question_context.get("choices", [])
    return ReviewContext(
        review_id=review.id,
        recording_id=review.recording_id,
        recording_version=review.recording_version,
        filename=review.recording.disk_filename,
        reason=review.question_type,
        choices=cast(list[dict[str, object]], choices),
        expires_at=review.token_expires_at.isoformat() if review.token_expires_at else "",
    )


@router.get("/questions", response_model=QuestionListResponse)
async def list_questions(
    session: Session,
    request: Request,
    recruiter_user_id: Annotated[str, Query(min_length=1, max_length=200)],
    mattermost_dm_channel_id: Annotated[str, Query(min_length=1, max_length=200)],
    question_set_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> QuestionListResponse:
    try:
        rows = await _question_queue_service(request).list_active(
            session,
            recruiter_user_id=recruiter_user_id,
            dm_channel_id=mattermost_dm_channel_id,
            question_set_id=question_set_id,
            limit=limit,
        )
    except ReviewRejectedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    items = [
        QuestionItem(
            question_id=row.id,
            question_set_id=row.question_set_id,
            recording_id=row.recording_id,
            recording_version=row.recording_version,
            filename=row.recording.disk_filename,
            reason=row.question_type,
            choices=cast(list[dict[str, object]], row.question_context.get("choices", [])),
            expires_at=row.token_expires_at.isoformat() if row.token_expires_at else "",
        )
        for row in rows
    ]
    return QuestionListResponse(items=items, count=len(items))


@router.post("/questions/answer", response_model=QuestionBatchResponse)
async def answer_questions(
    body: QuestionBatchRequest, session: Session, request: Request
) -> QuestionBatchResponse:
    answers = tuple(
        QuestionAnswer(
            question_id=item.question_id,
            question_set_id=item.question_set_id,
            action=item.action,
            token=item.capability.get_secret_value(),
            expected_version=item.expected_version,
            idempotency_key=item.idempotency_key,
            choice=item.choice,
        )
        for item in body.actions
    )
    try:
        result = await _question_queue_service(request).apply_partial(
            session,
            recruiter_user_id=body.recruiter_user_id,
            dm_channel_id=body.mattermost_dm_channel_id,
            answers=answers,
        )
        await session.commit()
    except ReviewRejectedError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return QuestionBatchResponse(
        accepted=[
            QuestionAccepted(
                question_id=item.review_id,
                recording_id=item.recording_id,
                status=item.status,
                version=item.version,
                replayed=item.replayed,
            )
            for item in result.accepted
        ],
        rejected=[
            QuestionRejected(question_id=item[0], reason=item[1]) for item in result.rejected
        ],
        pending=list(result.pending),
    )


@router.post("/reviews/{review_id}/resolve", response_model=ReviewMutationResponse)
async def resolve_review(
    review_id: uuid.UUID, body: ReviewResolveRequest, session: Session, request: Request
) -> ReviewMutationResponse:
    return await _mutate_review(review_id, body, session, request, "resolve", body.choice)


@router.post("/reviews/{review_id}/ignore", response_model=ReviewMutationResponse)
async def ignore_review(
    review_id: uuid.UUID, body: ReviewMutationRequest, session: Session, request: Request
) -> ReviewMutationResponse:
    return await _mutate_review(review_id, body, session, request, "ignore", None)


async def _mutate_review(
    review_id: uuid.UUID,
    body: ReviewMutationRequest,
    session: AsyncSession,
    request: Request,
    action: Literal["resolve", "ignore"],
    choice: int | None,
) -> ReviewMutationResponse:
    try:
        mutation = await _review_service(request).mutate(
            session,
            review_id=review_id,
            action=action,
            recruiter_user_id=body.recruiter_user_id,
            thread_id=body.mattermost_thread_id,
            token=body.token.get_secret_value(),
            expected_version=body.expected_version,
            idempotency_key=body.idempotency_key,
            choice=choice,
        )
        await session.commit()
    except ReviewRejectedError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    if action == "resolve":
        recording = await session.get(Recording, mutation.recording_id)
        if recording is not None:
            recruiter = await session.scalar(
                select(RecruiterConfig).where(RecruiterConfig.email == recording.disk_owner_email)
            )
            if recruiter is not None:
                await _resume_transfer_recording(
                    recording.id,
                    recruiter,
                    request.app.state.session_factory,
                    request.app.state.disk_scanner,
                    request.app.state.candidate_service,
                    request.app.state.transfer_service,
                    request.app.state.status_service,
                    request.app.state.notion_client,
                    get_settings(),
                )
                await session.refresh(recording)
                if recording.status in {RecordingStatus.COMPLETED, RecordingStatus.FAILED}:
                    await _review_service(request).deliver_terminal(session, recording, recruiter)
                mutation = type(mutation)(
                    review_id=mutation.review_id,
                    recording_id=mutation.recording_id,
                    status=recording.status.value,
                    version=recording.version,
                    replayed=mutation.replayed,
                )
                replay = await session.scalar(
                    select(IntentReplay).where(
                        IntentReplay.actor == body.recruiter_user_id,
                        IntentReplay.operation == f"review:{review_id}:{action}",
                        IntentReplay.idempotency_key == body.idempotency_key,
                    )
                )
                if replay is not None:
                    replay.response = mutation.as_dict()
                    await session.commit()
    return ReviewMutationResponse(**mutation.as_dict())


def _review_service(request: Request) -> ReviewService:
    return cast(ReviewService, request.app.state.review_service)


def _question_queue_service(request: Request) -> QuestionQueueService:
    return cast(QuestionQueueService, request.app.state.question_queue_service)


def _scan_response(
    email: str,
    summary: ScanSummary,
    rows: list[Recording] | None = None,
    status_counts: dict[RecordingStatus, int] | None = None,
) -> ScanResponse:
    new_ids = set(summary.inserted_recording_ids)
    items = [
        ScanItem(
            id=row.id,
            filename=row.disk_filename,
            candidate_name=row.candidate_name,
            status=row.status,
            is_new=row.id in new_ids,
            requires_review=row.status == RecordingStatus.MANUAL_REVIEW_REQUIRED,
            review_reason=row.manual_review_reason,
            generated_filename=row.generated_filename,
            safe_link=row.synology_share_url,
            error=row.error_message,
        )
        for row in (rows or [])
    ]
    counts = status_counts or {
        recording_status: sum(item.status == recording_status for item in items)
        for recording_status in RecordingStatus
    }
    processed = sum(counts.values())
    manual_review = counts.get(RecordingStatus.MANUAL_REVIEW_REQUIRED, 0)
    failed_recordings = counts.get(RecordingStatus.FAILED, 0)
    return ScanResponse(
        accepted=True,
        recruiter_email=email,
        discovered=summary.discovered,
        inserted=summary.inserted,
        skipped_legacy=summary.skipped_legacy,
        matched=summary.matched,
        manual_review=manual_review,
        without_review=max(0, processed - manual_review - failed_recordings),
        failed=summary.failed,
        failed_recordings=failed_recordings,
        processed=processed,
        items_truncated=processed > len(items),
        items=items,
    )
