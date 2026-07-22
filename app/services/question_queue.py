from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import Settings
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.notification_outbox import NotificationOutbox, OutboxStatus
from app.db.models.question_digest import QuestionDigest, QuestionDigestStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.reviews import ReviewMutation, ReviewRejectedError, ReviewService
from app.tools.mattermost import MattermostClient, MattermostError

QuestionAction = Literal["resolve", "ignore"]


@dataclass(frozen=True)
class QuestionAnswer:
    question_id: uuid.UUID
    question_set_id: uuid.UUID
    action: QuestionAction
    token: str
    expected_version: int
    idempotency_key: str
    choice: int | None = None


@dataclass(frozen=True)
class QuestionBatchResult:
    accepted: tuple[ReviewMutation, ...]
    rejected: tuple[tuple[uuid.UUID, str], ...]
    pending: tuple[uuid.UUID, ...]


class QuestionQueueService:
    def __init__(
        self, review_service: ReviewService, mattermost: MattermostClient, settings: Settings
    ) -> None:
        self._reviews = review_service
        self._mattermost = mattermost
        self._settings = settings

    async def list_active(
        self,
        session: AsyncSession,
        *,
        recruiter_user_id: str,
        dm_channel_id: str,
        question_set_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[ManualReview]:
        await self._validate_dm(session, recruiter_user_id, dm_channel_id)
        statement = (
            select(ManualReview)
            .where(
                ManualReview.recruiter_user_id == recruiter_user_id,
                ManualReview.mattermost_channel_id == dm_channel_id,
                ManualReview.status == ManualReviewStatus.PENDING,
            )
            .options(joinedload(ManualReview.recording))
            .order_by(ManualReview.created_at.asc(), ManualReview.id.asc())
            .limit(min(limit, 50))
        )
        if question_set_id is not None:
            statement = statement.where(ManualReview.question_set_id == question_set_id)
        return list((await session.scalars(statement)).unique().all())

    async def apply_partial(
        self,
        session: AsyncSession,
        *,
        recruiter_user_id: str,
        dm_channel_id: str,
        answers: tuple[QuestionAnswer, ...],
    ) -> QuestionBatchResult:
        if not answers or len(answers) > 50:
            raise ReviewRejectedError("Question answer batch must contain 1..50 items")
        if len({answer.question_id for answer in answers}) != len(answers):
            raise ReviewRejectedError("Question answer batch contains duplicate questions")
        await self._validate_dm(session, recruiter_user_id, dm_channel_id)
        accepted: list[ReviewMutation] = []
        rejected: list[tuple[uuid.UUID, str]] = []
        for answer in answers:
            try:
                if answer.action == "resolve" and answer.choice is None:
                    raise ReviewRejectedError("Resolve action requires an exact choice")
                if answer.action == "ignore" and answer.choice is not None:
                    raise ReviewRejectedError("Ignore action does not accept a choice")
                question = await session.get(ManualReview, answer.question_id)
                if question is None or question.question_set_id != answer.question_set_id:
                    raise ReviewRejectedError("Question set does not match")
                mutation = await self._reviews.mutate(
                    session,
                    review_id=answer.question_id,
                    action=answer.action,
                    recruiter_user_id=recruiter_user_id,
                    thread_id=dm_channel_id,
                    token=answer.token,
                    expected_version=answer.expected_version,
                    idempotency_key=answer.idempotency_key,
                    choice=answer.choice,
                    bind_dm=True,
                )
                accepted.append(mutation)
                await self.queue_notification(
                    session,
                    dedupe_key=f"question:{answer.question_id}:start:{mutation.version}",
                    kind="processing_started",
                    recruiter_user_id=recruiter_user_id,
                    dm_channel_id=dm_channel_id,
                    message=f"Recording {mutation.recording_id}: processing started.",
                )
            except ReviewRejectedError as error:
                rejected.append((answer.question_id, str(error)))
        await session.flush()
        pending = tuple(
            row.id
            for row in await self.list_active(
                session,
                recruiter_user_id=recruiter_user_id,
                dm_channel_id=dm_channel_id,
            )
        )
        return QuestionBatchResult(tuple(accepted), tuple(rejected), pending)

    async def build_digest(
        self,
        session: AsyncSession,
        *,
        recruiter_user_id: str,
        dm_channel_id: str,
        local_date: date,
    ) -> QuestionDigest | None:
        await self._validate_dm(session, recruiter_user_id, dm_channel_id)
        existing = await session.scalar(
            select(QuestionDigest).where(
                QuestionDigest.recruiter_user_id == recruiter_user_id,
                QuestionDigest.mattermost_channel_id == dm_channel_id,
                QuestionDigest.local_date == local_date,
            )
        )
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        await session.execute(
            update(ManualReview)
            .where(
                ManualReview.recruiter_user_id == recruiter_user_id,
                ManualReview.mattermost_channel_id == dm_channel_id,
                ManualReview.status == ManualReviewStatus.PENDING,
                ManualReview.automatic_delivery_count >= 2,
            )
            .values(status=ManualReviewStatus.SUPPRESSED, suppressed_at=now)
        )
        questions = list(
            (
                await session.scalars(
                    select(ManualReview)
                    .where(
                        ManualReview.recruiter_user_id == recruiter_user_id,
                        ManualReview.mattermost_channel_id == dm_channel_id,
                        ManualReview.status == ManualReviewStatus.PENDING,
                        ManualReview.automatic_delivery_count < 2,
                    )
                    .options(joinedload(ManualReview.recording))
                    .order_by(ManualReview.created_at.asc(), ManualReview.id.asc())
                    .limit(50)
                )
            )
            .unique()
            .all()
        )
        if not questions:
            return None
        digest = QuestionDigest(
            recruiter_user_id=recruiter_user_id,
            mattermost_channel_id=dm_channel_id,
            local_date=local_date,
        )
        session.add(digest)
        await session.flush()
        lines = ["Recording Agent questions:"]
        for number, question in enumerate(questions, start=1):
            question.digest_id = digest.id
            question.automatic_delivery_count += 1
            lines.append(
                f"{number}. {question.recording.disk_filename}: {question.question_type} "
                f"[question={question.id}; set={question.question_set_id}; "
                f"capability={self._reviews.capability_token(question)}; "
                f"version={question.recording_version}]"
            )
        await self.queue_notification(
            session,
            dedupe_key=f"digest:{recruiter_user_id}:{dm_channel_id}:{local_date.isoformat()}",
            kind="summary",
            recruiter_user_id=recruiter_user_id,
            dm_channel_id=dm_channel_id,
            message="\n".join(lines),
            entity_id=digest.id,
        )
        return digest

    async def queue_notification(
        self,
        session: AsyncSession,
        *,
        dedupe_key: str,
        kind: str,
        recruiter_user_id: str,
        dm_channel_id: str,
        message: str,
        entity_id: uuid.UUID | None = None,
    ) -> NotificationOutbox:
        existing = await session.scalar(
            select(NotificationOutbox).where(NotificationOutbox.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return existing
        item = NotificationOutbox(
            dedupe_key=dedupe_key,
            kind=kind,
            recruiter_user_id=recruiter_user_id,
            mattermost_channel_id=dm_channel_id,
            payload={
                "message": message[:4000],
                **({"entity_id": str(entity_id)} if entity_id is not None else {}),
            },
        )
        session.add(item)
        await session.flush()
        return item

    async def mark_terminal(
        self,
        session: AsyncSession,
        *,
        question_id: uuid.UUID,
        succeeded: bool,
        safe_message: str,
    ) -> NotificationOutbox:
        question = await session.get(ManualReview, question_id)
        if question is None:
            raise ReviewRejectedError("Question not found")
        if question.status not in {
            ManualReviewStatus.ANSWERED,
            ManualReviewStatus.PROCESSING,
            ManualReviewStatus.FAILED,
            ManualReviewStatus.COMPLETED,
        }:
            raise ReviewRejectedError("Question is not processing")
        now = datetime.now(UTC)
        if succeeded:
            question.status = ManualReviewStatus.COMPLETED
            question.completed_at = now
            kind = "completion"
        else:
            question.status = ManualReviewStatus.FAILED
            question.failed_at = now
            kind = "error"
        question.result = {"succeeded": succeeded, "message": safe_message[:300]}
        return await self.queue_notification(
            session,
            dedupe_key=f"question:{question.id}:{kind}:{question.recording_version}",
            kind=kind,
            recruiter_user_id=question.recruiter_user_id or "",
            dm_channel_id=question.mattermost_channel_id or "",
            message=safe_message[:4000],
        )

    async def claim_outbox(
        self, session: AsyncSession, *, worker_id: str, limit: int = 20
    ) -> list[NotificationOutbox]:
        now = datetime.now(UTC)
        stale = now - timedelta(seconds=self._settings.intent_claim_ttl_seconds)
        ids = list(
            await session.scalars(
                select(NotificationOutbox.id)
                .where(
                    NotificationOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.SENDING]),
                    or_(
                        NotificationOutbox.status == OutboxStatus.PENDING,
                        NotificationOutbox.claim_expires_at.is_(None),
                        NotificationOutbox.claim_expires_at <= now,
                    ),
                    or_(
                        NotificationOutbox.next_attempt_at.is_(None),
                        NotificationOutbox.next_attempt_at <= now,
                    ),
                )
                .order_by(NotificationOutbox.created_at.asc())
                .limit(min(limit, 50))
            )
        )
        if not ids:
            return []
        await session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id.in_(ids),
                or_(
                    NotificationOutbox.status == OutboxStatus.PENDING,
                    NotificationOutbox.claim_expires_at.is_(None),
                    NotificationOutbox.claim_expires_at <= now,
                ),
            )
            .values(
                status=OutboxStatus.SENDING,
                claim_owner=worker_id,
                claim_expires_at=now + (now - stale),
            )
        )
        await session.flush()
        return list(
            await session.scalars(
                select(NotificationOutbox).where(
                    NotificationOutbox.id.in_(ids), NotificationOutbox.claim_owner == worker_id
                )
            )
        )

    async def deliver_claimed(
        self, session: AsyncSession, item: NotificationOutbox, *, worker_id: str
    ) -> None:
        if item.claim_owner != worker_id or item.status != OutboxStatus.SENDING:
            raise ReviewRejectedError("Outbox item is not owned by this worker")
        message = item.payload.get("message")
        if not isinstance(message, str):
            raise ReviewRejectedError("Outbox payload is malformed")
        try:
            await self._mattermost.validate_direct_channel(
                item.recruiter_user_id, item.mattermost_channel_id
            )
            await self._mattermost.send_dm(
                item.recruiter_user_id,
                message,
                pending_post_id=self._pending_post_id(item.dedupe_key),
                expected_channel_id=item.mattermost_channel_id,
            )
        except MattermostError as error:
            item.attempts += 1
            item.status = OutboxStatus.FAILED if item.attempts >= 5 else OutboxStatus.PENDING
            item.claim_owner = None
            item.claim_expires_at = None
            item.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 2 ** min(item.attempts, 10))
            )
            item.last_error = str(error)[:300]
            await session.flush()
            raise
        item.status = OutboxStatus.SENT
        item.attempts += 1
        item.sent_at = datetime.now(UTC)
        item.claim_owner = None
        item.claim_expires_at = None
        item.last_error = None
        if item.kind == "summary":
            entity_id = item.payload.get("entity_id")
            if isinstance(entity_id, str):
                digest = await session.get(QuestionDigest, uuid.UUID(entity_id))
                if digest is not None:
                    digest.status = QuestionDigestStatus.SENT
                    digest.sent_at = item.sent_at
        await session.flush()

    async def _validate_dm(
        self, session: AsyncSession, recruiter_user_id: str, dm_channel_id: str
    ) -> RecruiterConfig:
        recruiter = await session.scalar(
            select(RecruiterConfig).where(
                RecruiterConfig.mattermost_user_id == recruiter_user_id,
                RecruiterConfig.mattermost_dm_channel == dm_channel_id,
                RecruiterConfig.active.is_(True),
            )
        )
        if recruiter is None:
            raise ReviewRejectedError("Recruiter or exact Mattermost DM binding is invalid")
        await self._mattermost.validate_direct_channel(recruiter_user_id, dm_channel_id)
        return recruiter

    @staticmethod
    def _pending_post_id(dedupe_key: str) -> str:
        return f"{hashlib.sha256(dedupe_key.encode()).hexdigest()[:26]}:0"
