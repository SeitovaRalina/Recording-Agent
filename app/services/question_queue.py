from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import Select, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import Settings
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.notification_outbox import NotificationOutbox, OutboxStatus
from app.db.models.question_digest import QuestionDigest, QuestionDigestStatus
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import enforce_recruiter_scope
from app.services.reviews import (
    InteractionBinding,
    ReviewMutation,
    ReviewRejectedError,
    ReviewService,
)
from app.tools.mattermost import MattermostClient, MattermostError

QuestionAction = Literal["resolve", "ignore"]
# A question about a recording in one of these states can no longer change its outcome.
SETTLED_RECORDING_STATUSES = (RecordingStatus.COMPLETED, RecordingStatus.IGNORED)


_QUESTION_LABELS = {
    "low_confidence": "подтвердите событие календаря",
    "no_compatible_event": "событие календаря не найдено — это собеседование?",
    "multiple_compatible_events": "выберите событие календаря",
    "multiple_eligible_events": "выберите событие календаря",
    "unmonitored_only": "событие найдено только в неотслеживаемом календаре",
    "unmonitored_collision": "похожее событие есть в неотслеживаемом календаре",
    "no_candidate_name_in_event": "в названии события нет имени кандидата",
    "no_candidate_found": "кандидат не найден в Notion",
    "multiple_candidates": "выберите карточку кандидата",
    "candidate_choices_exceed_limit": "слишком много похожих карточек в Notion",
    "multiple_spots": "выберите проект (📍 Spots)",
    "storage_destination_required": "выберите папку в Synology",
    "storage_key_collision": "в папке уже есть файл с таким именем",
    "autonomous_routing_ambiguous": "подходят несколько папок в Synology",
    "autonomous_routing_no_match": "подходящая папка в Synology не найдена",
}

_FAILED_STEP_LABELS = {
    "calendar_matching": "сопоставление с календарём",
    "candidate_matching": "поиск карточки в Notion",
    "destination": "выбор папки в Synology",
    "download": "скачивание с Яндекс.Диска",
    "ensure_folder": "подготовка папки в Synology",
    "upload": "загрузка в Synology",
    "share_link": "создание ссылки в Synology",
    "notion_preflight": "проверка базы Notion",
    "notion_update": "запись ссылки в Notion",
    "mark_processed": "отметка файла на Яндекс.Диске",
}


def _folder_label(path: str | None) -> str:
    parts = [part for part in (path or "").split("/") if part]
    if parts and parts[0] == "home":
        parts = parts[1:]
    return " / ".join(parts)


def render_terminal_message(recording: Recording) -> str:
    """Recruiter-facing result; contains links and a folder label, never tokens or errors."""
    if recording.status == RecordingStatus.COMPLETED:
        if recording.route_type == "non_interview":
            lines = ["✅ Запись рабочей встречи сохранена", f"Файл: {recording.disk_filename}"]
        else:
            lines = [
                "✅ Запись собеседования обработана",
                f"Кандидат: {recording.candidate_name or '—'}",
            ]
            if recording.notion_page_url:
                lines.append(f"Карточка в Notion: {recording.notion_page_url}")
        if recording.synology_share_url:
            lines.append(f"Запись: {recording.synology_share_url}")
        if folder := _folder_label(recording.synology_folder_path):
            lines.append(f"Папка: {folder}")
        return "\n".join(lines)
    step = _FAILED_STEP_LABELS.get(recording.error_step or "", "обработка записи")
    subject = recording.candidate_name or recording.disk_filename
    return "\n".join(
        [
            f"⚠️ Не удалось обработать запись «{recording.disk_filename}»",
            f"Этап: {step}",
            f"Исходный файл на Яндекс.Диске не тронут. Чтобы повторить, напишите Миле: "
            f"«Повтори обработку записи {subject}».",
        ]
    )


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

    @staticmethod
    def _settled_recording_ids() -> Select[tuple[uuid.UUID]]:
        return select(Recording.id).where(Recording.status.in_(SETTLED_RECORDING_STATUSES))

    def capability_token(self, question: ManualReview) -> str:
        return self._reviews.capability_token(question)

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
                ManualReview.recording_id.not_in(self._settled_recording_ids()),
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
                if not self._offline_test_mode:
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
        dedupe_key = f"digest:{recruiter_user_id}:{dm_channel_id}:{local_date.isoformat()}"
        outstanding_summary = await session.scalar(
            select(NotificationOutbox.id).where(
                NotificationOutbox.recruiter_user_id == recruiter_user_id,
                NotificationOutbox.mattermost_channel_id == dm_channel_id,
                NotificationOutbox.kind == "summary",
                NotificationOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.SENDING]),
                NotificationOutbox.dedupe_key != dedupe_key,
            )
        )
        if outstanding_summary is not None:
            return None
        existing = await session.scalar(
            select(QuestionDigest).where(
                QuestionDigest.recruiter_user_id == recruiter_user_id,
                QuestionDigest.mattermost_channel_id == dm_channel_id,
                QuestionDigest.local_date == local_date,
            )
        )
        if existing is not None and existing.status != QuestionDigestStatus.PENDING:
            return existing
        if existing is not None and await session.scalar(
            select(NotificationOutbox.id).where(NotificationOutbox.dedupe_key == dedupe_key)
        ):
            return existing
        now = datetime.now(UTC)
        await session.execute(
            update(ManualReview)
            .where(
                ManualReview.recruiter_user_id == recruiter_user_id,
                ManualReview.mattermost_channel_id == dm_channel_id,
                ManualReview.status == ManualReviewStatus.PENDING,
                ManualReview.recording_id.in_(self._settled_recording_ids()),
            )
            .values(
                status=ManualReviewStatus.COMPLETED,
                completed_at=now,
                result={"closed_by": "recording_settled"},
            )
            .execution_options(synchronize_session=False)
        )
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
            if existing is not None:
                existing.status = QuestionDigestStatus.SENT
                existing.sent_at = now
                await session.flush()
            return None
        digest = existing
        if digest is None:
            digest = QuestionDigest(
                recruiter_user_id=recruiter_user_id,
                mattermost_channel_id=dm_channel_id,
                local_date=local_date,
            )
            session.add(digest)
            await session.flush()
        lines = [
            f"Вопросы по записям собеседований: {len(questions)}. "
            "Ответьте Миле одним сообщением, например: «1 — 2, 2 — пропусти»."
        ]
        for number, question in enumerate(questions, start=1):
            question.digest_id = digest.id
            self._reviews.rotate_digest_capability(question, issued_at=now)
            lines.extend(self._render_question(number, question))
        await self.queue_notification(
            session,
            dedupe_key=dedupe_key,
            kind="summary",
            recruiter_user_id=recruiter_user_id,
            dm_channel_id=dm_channel_id,
            message="\n".join(lines),
            entity_id=digest.id,
        )
        return digest

    @staticmethod
    def _render_question(number: int, question: ManualReview) -> list[str]:
        label = _QUESTION_LABELS.get(question.question_type, question.question_type)
        lines = [f"{number}. {question.recording.disk_filename}: {label}"]
        choices = question.question_context.get("choices")
        if not isinstance(choices, list):
            return lines
        for choice_number, choice in enumerate(choices[:10], start=1):
            if not isinstance(choice, dict):
                continue
            label = choice.get("name") or choice.get("event_summary") or "вариант без названия"
            details = [str(label)[:160]]
            if choice.get("project_or_spot"):
                details.append(f"📍 Spots: {str(choice['project_or_spot'])[:160]}")
            if choice.get("spot_url"):
                details.append(f"Spot: {str(choice['spot_url'])[:500]}")
            emails = choice.get("candidate_emails")
            if isinstance(emails, list):
                safe_emails = [str(email)[:320] for email in emails[:3] if isinstance(email, str)]
                if safe_emails:
                    details.append(f"Contacts: {', '.join(safe_emails)}")
            if choice.get("url"):
                details.append(str(choice["url"])[:500])
            lines.append(f"   {choice_number}. " + " — ".join(details))
        return lines

    async def queue_terminal_notifications(self, session: AsyncSession, *, limit: int = 20) -> int:
        """Queue one completion/error DM per settled recording through the durable outbox.

        Every route (Mila, autonomous worker, scheduled scan, restart recovery) ends in
        `completed` or `failed`; sweeping those states keeps the recruiter notification
        independent of which path finished the work.
        """
        if self._offline_test_mode:
            return 0
        rows = (
            await session.execute(
                select(Recording, RecruiterConfig)
                .join(RecruiterConfig, RecruiterConfig.email == Recording.disk_owner_email)
                .where(
                    Recording.status.in_([RecordingStatus.COMPLETED, RecordingStatus.FAILED]),
                    Recording.terminal_notified_at.is_(None),
                    Recording.terminal_notification_claim.is_(None),
                    RecruiterConfig.active.is_(True),
                    RecruiterConfig.mattermost_user_id.is_not(None),
                    RecruiterConfig.mattermost_dm_channel.is_not(None),
                )
                .order_by(Recording.found_at.asc())
                .limit(limit)
                .with_for_update(of=Recording, skip_locked=True)
            )
        ).all()
        now = datetime.now(UTC)
        for recording, recruiter in rows:
            status = RecordingStatus(recording.status)
            succeeded = status == RecordingStatus.COMPLETED
            await self.queue_notification(
                session,
                dedupe_key=f"terminal:{recording.id}:{status.value}:{recording.version}",
                kind="completion" if succeeded else "error",
                recruiter_user_id=recruiter.mattermost_user_id or "",
                dm_channel_id=recruiter.mattermost_dm_channel or "",
                message=render_terminal_message(recording),
                entity_id=recording.id,
            )
            recording.terminal_notified_at = now
        await session.flush()
        return len(rows)

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

    async def queue_routing_defer_notification(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        recording: Recording,
        review: ManualReview,
    ) -> NotificationOutbox:
        """Queue one actionable ordinary-DM question for an autonomous routing defer."""
        if not review.recruiter_user_id or not review.mattermost_channel_id:
            raise ReviewRejectedError("Routing question has no exact Mattermost DM binding")
        choices = review.question_context.get("choices")
        if not isinstance(choices, list):
            raise ReviewRejectedError("Routing question choices are malformed")
        labels: list[str] = []
        for choice in choices[:10]:
            if not isinstance(choice, dict):
                raise ReviewRejectedError("Routing question choice is malformed")
            raw_id = choice.get("destination_id")
            raw_name = choice.get("name")
            if not isinstance(raw_id, str) or not isinstance(raw_name, str) or not raw_name.strip():
                raise ReviewRejectedError("Routing question choice is malformed")
            try:
                uuid.UUID(raw_id)
            except ValueError as error:
                raise ReviewRejectedError(
                    "Routing question destination identity is invalid"
                ) from error
            labels.append(" ".join(raw_name.split())[:160])
        subject = f"«{recording.disk_filename[:160]}»"
        if recording.candidate_name:
            subject += f", кандидат {recording.candidate_name[:160]}"
        if recording.project_or_spot:
            subject += f", 📍 {recording.project_or_spot[:160]}"
        if labels:
            lines = [
                f"Запись {subject}: подходят несколько папок в Synology.",
                *(f"{number}) {label}" for number, label in enumerate(labels, start=1)),
                "Ответьте Миле номером, например «1».",
            ]
        else:
            lines = [
                f"Запись {subject}: подходящей папки в Synology нет.",
                "Напишите Миле, куда её положить или какую папку создать, например: "
                "«создай папку Discovery во внешних».",
            ]
        message = "\n".join(lines)
        return await self.queue_notification(
            session,
            dedupe_key=f"routing-defer:{job_id}:{recording.version}",
            kind="routing_deferred",
            recruiter_user_id=review.recruiter_user_id,
            dm_channel_id=review.mattermost_channel_id,
            message=message,
            entity_id=review.id,
        )

    async def mark_terminal(
        self,
        session: AsyncSession,
        *,
        question_id: uuid.UUID,
        succeeded: bool,
        safe_message: str,
        notify: bool = True,
    ) -> NotificationOutbox | None:
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
        if self._offline_test_mode or not notify:
            await session.flush()
            return None
        return await self.queue_notification(
            session,
            dedupe_key=f"question:{question.id}:{kind}:{question.recording_version}",
            kind=kind,
            recruiter_user_id=question.recruiter_user_id or "",
            dm_channel_id=question.mattermost_channel_id or "",
            message=safe_message[:4000],
        )

    async def reconcile_processing(
        self,
        session: AsyncSession,
        *,
        recruiter: RecruiterConfig,
        interaction_binding: InteractionBinding | None = None,
    ) -> None:
        """Recover and finalize accepted answers from durable recording state."""
        if interaction_binding is not None:
            if not self._offline_test_mode:
                raise ReviewRejectedError("Offline interaction binding is unavailable")
            if recruiter.mattermost_user_id != interaction_binding.recruiter_user_id:
                raise ReviewRejectedError(
                    "Interaction requester does not match recruiter configuration"
                )
            user_id = interaction_binding.recruiter_user_id
            channel_id = interaction_binding.dm_channel_id
        else:
            if not recruiter.mattermost_user_id or not recruiter.mattermost_dm_channel:
                raise ReviewRejectedError("Recruiter Mattermost DM binding is incomplete")
            user_id = recruiter.mattermost_user_id
            channel_id = recruiter.mattermost_dm_channel
        questions = list(
            (
                await session.scalars(
                    select(ManualReview)
                    .join(ManualReview.recording)
                    .where(
                        ManualReview.status == ManualReviewStatus.PROCESSING,
                        ManualReview.recruiter_user_id == user_id,
                        ManualReview.mattermost_channel_id == channel_id,
                    )
                    .options(joinedload(ManualReview.recording))
                )
            )
            .unique()
            .all()
        )
        for question in questions:
            recording = question.recording
            filename = recording.generated_filename or recording.disk_filename
            if recording.status in {RecordingStatus.COMPLETED, RecordingStatus.FAILED}:
                # The recording-level terminal sweep sends the single recruiter result.
                await self.mark_terminal(
                    session,
                    question_id=question.id,
                    succeeded=recording.status == RecordingStatus.COMPLETED,
                    safe_message=f"recording {RecordingStatus(recording.status).value}",
                    notify=False,
                )
            elif recording.status == RecordingStatus.IGNORED:
                await self.mark_terminal(
                    session,
                    question_id=question.id,
                    succeeded=True,
                    safe_message=f"Запись «{filename}» пропущена по вашему ответу.",
                )
            elif recording.status == RecordingStatus.MANUAL_REVIEW_REQUIRED:
                await self.mark_terminal(
                    session,
                    question_id=question.id,
                    succeeded=True,
                    safe_message=(
                        f"Ответ по записи «{filename}» принят. Нужно ещё одно уточнение, "
                        "вопрос придёт следующим сообщением."
                    ),
                )
                await self._reviews.enqueue_review(
                    session,
                    recording,
                    recruiter,
                    interaction_binding=interaction_binding,
                )
        await session.flush()

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
                    await session.execute(
                        update(ManualReview)
                        .where(
                            ManualReview.digest_id == digest.id,
                            ManualReview.status == ManualReviewStatus.PENDING,
                        )
                        .values(automatic_delivery_count=ManualReview.automatic_delivery_count + 1)
                    )
                    digest.status = QuestionDigestStatus.SENT
                    digest.sent_at = item.sent_at
        await session.flush()

    async def _validate_dm(
        self, session: AsyncSession, recruiter_user_id: str, dm_channel_id: str
    ) -> RecruiterConfig:
        criteria = [
            RecruiterConfig.mattermost_user_id == recruiter_user_id,
            RecruiterConfig.active.is_(True),
        ]
        if not self._offline_test_mode:
            criteria.append(RecruiterConfig.mattermost_dm_channel == dm_channel_id)
        recruiter = await session.scalar(select(RecruiterConfig).where(*criteria))
        if recruiter is None:
            raise ReviewRejectedError("Recruiter or exact Mattermost DM binding is invalid")
        if self._offline_test_mode:
            try:
                enforce_recruiter_scope(self._settings, recruiter)
            except PermissionError as error:
                raise ReviewRejectedError(str(error)) from error
            conflicting = await session.scalar(
                select(ManualReview.id).where(
                    ManualReview.recruiter_user_id == recruiter_user_id,
                    ManualReview.status == ManualReviewStatus.PENDING,
                    ManualReview.mattermost_channel_id.is_distinct_from(dm_channel_id),
                )
            )
            if conflicting is not None:
                raise ReviewRejectedError("Pending question belongs to another Mattermost DM")
        else:
            await self._mattermost.validate_direct_channel(recruiter_user_id, dm_channel_id)
        return recruiter

    @property
    def _offline_test_mode(self) -> bool:
        return self._settings.test_mode_enabled and not self._settings.mattermost_delivery_enabled

    @staticmethod
    def _pending_post_id(dedupe_key: str) -> str:
        return f"{hashlib.sha256(dedupe_key.encode()).hexdigest()[:26]}:0"
