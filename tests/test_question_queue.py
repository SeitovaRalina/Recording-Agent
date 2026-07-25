import hashlib
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.notification_outbox import NotificationOutbox, OutboxStatus
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.question_queue import QuestionAnswer, QuestionQueueService
from app.services.reviews import InteractionBinding, ReviewRejectedError, ReviewService


def _question(file_id: str, token: str) -> ManualReview:
    recording = Recording(
        disk_file_id=file_id,
        disk_path=f"disk:/{file_id}.webm",
        disk_filename=f"{file_id}.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        version=3,
    )
    return ManualReview(
        recording=recording,
        question_type="classification",
        question_context={"choices": []},
        recruiter_user_id="recruiter",
        mattermost_channel_id="dm",
        delivery_nonce="nonce",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        recording_version=3,
    )


@pytest.mark.anyio
async def test_partial_answer_accepts_exact_item_and_leaves_other_pending(
    session: AsyncSession,
) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret")
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    accepted = _question("accepted", "valid-token")
    pending = _question("pending", "other-token")
    session.add_all(
        [
            RecruiterConfig(
                email="r@example.com",
                notion_database_id="db",
                synology_base_folder="root",
                mattermost_user_id="recruiter",
                mattermost_dm_channel="dm",
            ),
            accepted,
            pending,
        ]
    )
    await session.commit()

    result = await service.apply_partial(
        session,
        recruiter_user_id="recruiter",
        dm_channel_id="dm",
        answers=(
            QuestionAnswer(
                question_id=accepted.id,
                question_set_id=accepted.question_set_id,
                action="ignore",
                token="valid-token",
                expected_version=3,
                idempotency_key="accepted-1",
            ),
            QuestionAnswer(
                question_id=pending.id,
                question_set_id=pending.question_set_id,
                action="ignore",
                token="wrong-token",
                expected_version=3,
                idempotency_key="rejected-1",
            ),
        ),
    )

    assert [item.review_id for item in result.accepted] == [accepted.id]
    assert result.rejected[0][0] == pending.id
    assert result.pending == (pending.id,)
    assert accepted.status == ManualReviewStatus.PROCESSING
    assert pending.status == ManualReviewStatus.PENDING
    assert await session.scalar(
        select(NotificationOutbox).where(NotificationOutbox.kind == "processing_started")
    )


@pytest.mark.anyio
async def test_digest_rotates_digest_bound_capability_with_next_day_ttl(
    session: AsyncSession,
) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret")
    reviews = ReviewService(mattermost, settings)
    service = QuestionQueueService(reviews, mattermost, settings)
    question = _question("rotated", "expired-before-digest")
    question.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    old_nonce = question.delivery_nonce
    session.add_all(
        [
            RecruiterConfig(
                email="r@example.com",
                notion_database_id="db",
                synology_base_folder="root",
                mattermost_user_id="recruiter",
                mattermost_dm_channel="dm",
                active=True,
            ),
            question,
        ]
    )
    await session.commit()

    before = datetime.now(UTC)
    await service.build_digest(
        session, recruiter_user_id="recruiter", dm_channel_id="dm", local_date=date(2026, 7, 22)
    )

    assert question.delivery_nonce != old_nonce
    assert question.token_expires_at is not None
    assert question.token_expires_at >= before + timedelta(hours=24)
    capability = reviews.capability_token(question)
    assert question.token_hash == hashlib.sha256(capability.encode()).hexdigest()


@pytest.mark.anyio
async def test_digest_renders_bounded_notion_differentiators(session: AsyncSession) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret")
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    question = _question("duplicates", "unused")
    question.question_context = {
        "choices": [
            {
                "name": "Same Name",
                "url": "https://notion.example/interview-1",
                "project_or_spot": "Backend",
                "spot_url": "https://notion.example/spot-1",
                "candidate_emails": ["candidate@example.com"],
            }
        ]
    }
    session.add_all(
        [
            RecruiterConfig(
                email="r@example.com",
                notion_database_id="db",
                synology_base_folder="root",
                mattermost_user_id="recruiter",
                mattermost_dm_channel="dm",
                active=True,
            ),
            question,
        ]
    )
    await session.commit()

    await service.build_digest(
        session, recruiter_user_id="recruiter", dm_channel_id="dm", local_date=date(2026, 7, 22)
    )
    message = await session.scalar(
        select(NotificationOutbox).where(NotificationOutbox.kind == "summary")
    )

    assert message is not None
    rendered = str(message.payload["message"])
    assert "https://notion.example/interview-1" in rendered
    assert "Spots: Backend" in rendered
    assert "https://notion.example/spot-1" in rendered
    assert "candidate@example.com" in rendered


@pytest.mark.anyio
async def test_reconcile_processing_marks_terminal_and_queues_completion(
    session: AsyncSession,
) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret")
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    question = _question("completed-answer", "unused")
    question.status = ManualReviewStatus.PROCESSING
    question.recording.status = RecordingStatus.COMPLETED
    question.recording.synology_share_url = "https://storage.example/file"
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
        mattermost_user_id="recruiter",
        mattermost_dm_channel="dm",
        active=True,
    )
    session.add_all([recruiter, question])
    await session.commit()

    await service.reconcile_processing(session, recruiter=recruiter)

    assert question.status == ManualReviewStatus.COMPLETED
    completion = await session.scalar(
        select(NotificationOutbox).where(NotificationOutbox.kind == "completion")
    )
    assert completion is not None
    assert "https://storage.example/file" in str(completion.payload["message"])


@pytest.mark.anyio
async def test_reconcile_processing_recovers_failed_work_with_actionable_error(
    session: AsyncSession,
) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret")
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    question = _question("failed-answer", "unused")
    question.status = ManualReviewStatus.PROCESSING
    question.recording.status = RecordingStatus.FAILED
    question.recording.error_step = "notion_update"
    question.recording.error_message = "schema changed"
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
        mattermost_user_id="recruiter",
        mattermost_dm_channel="dm",
        active=True,
    )
    session.add_all([recruiter, question])
    await session.commit()

    await service.reconcile_processing(session, recruiter=recruiter)

    assert question.status == ManualReviewStatus.FAILED
    failure = await session.scalar(
        select(NotificationOutbox).where(NotificationOutbox.kind == "error")
    )
    assert failure is not None
    rendered = str(failure.payload["message"])
    assert "notion_update" in rendered
    assert "retry" in rendered.casefold()


@pytest.mark.anyio
async def test_digest_reminds_once_then_suppresses(session: AsyncSession) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret")
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    question = _question("reminder", "unused")
    session.add_all(
        [
            RecruiterConfig(
                email="r@example.com",
                notion_database_id="db",
                synology_base_folder="root",
                mattermost_user_id="recruiter",
                mattermost_dm_channel="dm",
            ),
            question,
        ]
    )
    await session.commit()

    assert await service.build_digest(
        session, recruiter_user_id="recruiter", dm_channel_id="dm", local_date=date(2026, 7, 22)
    )
    first_message = await session.scalar(
        select(NotificationOutbox).where(NotificationOutbox.kind == "summary")
    )
    assert first_message is not None
    rendered = first_message.payload["message"]
    assert isinstance(rendered, str)
    assert "capability=" not in rendered
    assert "question=" not in rendered
    assert "set=" not in rendered
    first_message.status = OutboxStatus.SENDING
    first_message.claim_owner = "worker-1"
    await service.deliver_claimed(session, first_message, worker_id="worker-1")
    await session.commit()
    assert await service.build_digest(
        session, recruiter_user_id="recruiter", dm_channel_id="dm", local_date=date(2026, 7, 23)
    )
    second_message = await session.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.dedupe_key == "digest:recruiter:dm:2026-07-23"
        )
    )
    assert second_message is not None
    second_message.status = OutboxStatus.SENDING
    second_message.claim_owner = "worker-2"
    await service.deliver_claimed(session, second_message, worker_id="worker-2")
    await session.commit()
    assert (
        await service.build_digest(
            session,
            recruiter_user_id="recruiter",
            dm_channel_id="dm",
            local_date=date(2026, 7, 24),
        )
        is None
    )
    assert question.automatic_delivery_count == 2
    assert question.status == ManualReviewStatus.SUPPRESSED


@pytest.mark.anyio
async def test_undelivered_summary_does_not_consume_reminder(session: AsyncSession) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret")
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    question = _question("delivery-failed", "unused")
    session.add_all(
        [
            RecruiterConfig(
                email="r@example.com",
                notion_database_id="db",
                synology_base_folder="root",
                mattermost_user_id="recruiter",
                mattermost_dm_channel="dm",
            ),
            question,
        ]
    )
    await session.commit()

    assert await service.build_digest(
        session, recruiter_user_id="recruiter", dm_channel_id="dm", local_date=date(2026, 7, 22)
    )
    assert (
        await service.build_digest(
            session,
            recruiter_user_id="recruiter",
            dm_channel_id="dm",
            local_date=date(2026, 7, 23),
        )
        is None
    )
    assert question.automatic_delivery_count == 0
    assert question.status == ManualReviewStatus.PENDING


@pytest.mark.anyio
async def test_outbox_recovers_stale_claim_and_terminal_is_deduplicated(
    session: AsyncSession,
) -> None:
    mattermost = AsyncMock()
    settings = Settings(openclaw_secret="secret", intent_claim_ttl_seconds=60)
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    item = await service.queue_notification(
        session,
        dedupe_key="stable",
        kind="summary",
        recruiter_user_id="recruiter",
        dm_channel_id="dm",
        message="hello",
    )
    await session.commit()
    first = await service.claim_outbox(session, worker_id="worker-1")
    assert [row.id for row in first] == [item.id]
    item.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    recovered = await service.claim_outbox(session, worker_id="worker-2")
    assert [row.id for row in recovered] == [item.id]
    await service.deliver_claimed(session, recovered[0], worker_id="worker-2")
    assert item.status == OutboxStatus.SENT
    assert mattermost.send_dm.await_count == 1


@pytest.mark.anyio
async def test_offline_questions_enforce_immutable_binding_and_create_no_outbox(
    session: AsyncSession,
) -> None:
    mattermost = AsyncMock()
    settings = Settings(
        openclaw_secret="secret",
        test_mode_enabled=True,
        mattermost_delivery_enabled=False,
        test_recruiter_allowlist={"r@example.com"},
        test_notion_database_allowlist={"db"},
        test_mattermost_user_allowlist={"recruiter"},
        minio_test_prefix="root",
    )
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    question = _question("offline-ignore", "valid-token")
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
        mattermost_user_id="recruiter",
    )
    session.add_all([recruiter, question])
    await session.commit()

    listed = await service.list_active(
        session, recruiter_user_id="recruiter", dm_channel_id="dm"
    )
    assert [item.id for item in listed] == [question.id]
    with pytest.raises(ReviewRejectedError, match="another Mattermost DM"):
        await service.list_active(
            session, recruiter_user_id="recruiter", dm_channel_id="attacker-dm"
        )

    result = await service.apply_partial(
        session,
        recruiter_user_id="recruiter",
        dm_channel_id="dm",
        answers=(
            QuestionAnswer(
                question_id=question.id,
                question_set_id=question.question_set_id,
                action="ignore",
                token="valid-token",
                expected_version=3,
                idempotency_key="offline-ignore-1",
            ),
        ),
    )
    await service.reconcile_processing(
        session,
        recruiter=recruiter,
        interaction_binding=InteractionBinding("recruiter", "dm"),
    )

    assert len(result.accepted) == 1
    assert question.recording.status == RecordingStatus.IGNORED
    assert question.status == ManualReviewStatus.COMPLETED
    assert await session.scalar(select(NotificationOutbox.id)) is None
    mattermost.validate_direct_channel.assert_not_awaited()
    mattermost.send_dm.assert_not_awaited()


@pytest.mark.anyio
async def test_offline_resolve_preserves_choice_version_and_idempotent_replay(
    session: AsyncSession,
) -> None:
    mattermost = AsyncMock()
    settings = Settings(
        openclaw_secret="secret",
        test_mode_enabled=True,
        mattermost_delivery_enabled=False,
        test_recruiter_allowlist={"r@example.com"},
        test_notion_database_allowlist={"db"},
        test_mattermost_user_allowlist={"recruiter"},
        minio_test_prefix="root",
    )
    service = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    question = _question("offline-resolve", "valid-token")
    question.question_context = {
        "choices": [
            {
                "id": "notion-page",
                "name": "Candidate",
                "url": "https://notion.example/candidate",
                "project_or_spot": "Backend",
            }
        ]
    }
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
        mattermost_user_id="recruiter",
    )
    session.add_all([recruiter, question])
    await session.commit()
    answer = QuestionAnswer(
        question_id=question.id,
        question_set_id=question.question_set_id,
        action="resolve",
        token="valid-token",
        expected_version=3,
        idempotency_key="offline-resolve-1",
        choice=1,
    )

    first = await service.apply_partial(
        session,
        recruiter_user_id="recruiter",
        dm_channel_id="dm",
        answers=(answer,),
    )
    replay = await service.apply_partial(
        session,
        recruiter_user_id="recruiter",
        dm_channel_id="dm",
        answers=(answer,),
    )

    assert first.accepted[0].status == RecordingStatus.CANDIDATE_MATCHED
    assert first.accepted[0].version == 4
    assert replay.accepted[0].replayed is True
    assert question.recording.notion_page_id == "notion-page"
    assert await session.scalar(select(NotificationOutbox.id)) is None
