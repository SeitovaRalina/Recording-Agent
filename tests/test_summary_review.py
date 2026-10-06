"""ReviewService.mutate branches for the new summary-email/assessment question types."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.reviews import ReviewRejectedError, ReviewService


def _recording(*, status: RecordingStatus = RecordingStatus.COMPLETED) -> Recording:
    return Recording(
        disk_file_id="disk-id",
        disk_path="disk:/call.webm",
        disk_filename="call.webm",
        disk_owner_email="r@example.com",
        status=status,
        version=5,
        notion_page_id="page-1",
    )


def _recruiter() -> RecruiterConfig:
    return RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="prefix",
        mattermost_user_id="mm-user",
        mattermost_dm_channel="dm-channel",
    )


def _review(
    recording: Recording, *, question_type: str, context: dict[str, object]
) -> ManualReview:
    token = "opaque-token"
    return ManualReview(
        recording=recording,
        recording_id=recording.id,
        question_type=question_type,
        question_context=context,
        recruiter_user_id="mm-user",
        mattermost_channel_id="dm-channel",
        delivery_nonce="nonce",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        recording_version=recording.version,
    )


_TOKEN = "opaque-token"


@pytest.mark.anyio
async def test_approve_summary_assessment_posts_comment_exactly_once(session: object) -> None:
    recording = _recording()
    review = _review(
        recording,
        question_type="summary_assessment_approval",
        context={
            "choices": [{"approve": True, "name": "approve"}, {"approve": False, "name": "reject"}],
            "assessment_text": "Strengths: X. Weaknesses: Y. Recommendation: move forward.",
        },
    )
    session.add_all([_recruiter(), review])  # type: ignore[attr-defined]
    await session.commit()  # type: ignore[attr-defined]
    notion = AsyncMock()
    service = ReviewService(AsyncMock(), Settings(), notion=notion)

    mutation = await service.mutate(
        session,  # type: ignore[arg-type]
        review_id=review.id,
        action="resolve",
        recruiter_user_id="mm-user",
        thread_id="dm-channel",
        token=_TOKEN,
        expected_version=5,
        idempotency_key="approve-1",
        choice=1,
        bind_dm=True,
    )

    notion.create_comment.assert_awaited_once_with(
        "page-1", "Strengths: X. Weaknesses: Y. Recommendation: move forward."
    )
    assert review.parsed_action == "approve"
    # The recording's main-pipeline status is untouched by this approval.
    assert mutation.status == RecordingStatus.COMPLETED.value
    assert recording.status == RecordingStatus.COMPLETED


@pytest.mark.anyio
async def test_reject_summary_assessment_never_posts_a_comment(session: object) -> None:
    recording = _recording()
    review = _review(
        recording,
        question_type="summary_assessment_approval",
        context={
            "choices": [{"approve": True, "name": "approve"}, {"approve": False, "name": "reject"}],
            "assessment_text": "text",
        },
    )
    session.add_all([_recruiter(), review])  # type: ignore[attr-defined]
    await session.commit()  # type: ignore[attr-defined]
    notion = AsyncMock()
    service = ReviewService(AsyncMock(), Settings(), notion=notion)

    await service.mutate(
        session,  # type: ignore[arg-type]
        review_id=review.id,
        action="resolve",
        recruiter_user_id="mm-user",
        thread_id="dm-channel",
        token=_TOKEN,
        expected_version=5,
        idempotency_key="reject-1",
        choice=2,
        bind_dm=True,
    )

    notion.create_comment.assert_not_awaited()
    assert review.parsed_action == "reject"
    assert recording.status == RecordingStatus.COMPLETED


@pytest.mark.anyio
async def test_ignore_summary_assessment_never_posts_a_comment_or_reopens_recording(
    session: object,
) -> None:
    recording = _recording()
    review = _review(
        recording,
        question_type="summary_assessment_approval",
        context={"choices": [], "assessment_text": "text"},
    )
    session.add_all([_recruiter(), review])  # type: ignore[attr-defined]
    await session.commit()  # type: ignore[attr-defined]
    notion = AsyncMock()
    service = ReviewService(AsyncMock(), Settings(), notion=notion)

    mutation = await service.mutate(
        session,  # type: ignore[arg-type]
        review_id=review.id,
        action="ignore",
        recruiter_user_id="mm-user",
        thread_id="dm-channel",
        token=_TOKEN,
        expected_version=5,
        idempotency_key="ignore-1",
        bind_dm=True,
    )

    notion.create_comment.assert_not_awaited()
    assert review.parsed_action == "ignore"
    assert recording.status == RecordingStatus.COMPLETED
    assert mutation.status == RecordingStatus.COMPLETED.value


@pytest.mark.anyio
async def test_approve_summary_assessment_without_notion_client_is_rejected(
    session: object,
) -> None:
    recording = _recording()
    review = _review(
        recording,
        question_type="summary_assessment_approval",
        context={
            "choices": [{"approve": True, "name": "approve"}],
            "assessment_text": "text",
        },
    )
    session.add_all([_recruiter(), review])  # type: ignore[attr-defined]
    await session.commit()  # type: ignore[attr-defined]
    service = ReviewService(AsyncMock(), Settings())  # no notion client wired

    with pytest.raises(ReviewRejectedError, match="Notion comment delivery"):
        await service.mutate(
            session,  # type: ignore[arg-type]
            review_id=review.id,
            action="resolve",
            recruiter_user_id="mm-user",
            thread_id="dm-channel",
            token=_TOKEN,
            expected_version=5,
            idempotency_key="approve-no-notion",
            choice=1,
            bind_dm=True,
        )


@pytest.mark.anyio
async def test_resolve_ambiguous_summary_email_choice_sets_recording_fields(
    session: object,
) -> None:
    recording = _recording()
    review = _review(
        recording,
        question_type="summary_email_ambiguous",
        context={
            "choices": [
                {
                    "message_id": "<a@mail>",
                    "name": "Interview summary — hr@example.com",
                    "subject": "Interview summary",
                    "sender": "hr@example.com",
                    "received_at": "2026-10-02T10:00:00+00:00",
                }
            ]
        },
    )
    session.add_all([_recruiter(), review])  # type: ignore[attr-defined]
    await session.commit()  # type: ignore[attr-defined]
    service = ReviewService(AsyncMock(), Settings())

    await service.mutate(
        session,  # type: ignore[arg-type]
        review_id=review.id,
        action="resolve",
        recruiter_user_id="mm-user",
        thread_id="dm-channel",
        token=_TOKEN,
        expected_version=5,
        idempotency_key="pick-email",
        choice=1,
        bind_dm=True,
    )

    assert recording.summary_email_message_id == "<a@mail>"
    assert recording.summary_email_subject == "Interview summary"
    assert recording.summary_email_received_at == datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
    assert recording.status == RecordingStatus.COMPLETED
    assert review.status == ManualReviewStatus.PROCESSING
