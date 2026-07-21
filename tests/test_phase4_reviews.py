import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.db.models.manual_review import ManualReview
from app.db.models.recording import Recording, RecordingStatus
from app.services.reviews import ReviewRejectedError, ReviewService


def _recording() -> Recording:
    return Recording(
        disk_file_id="disk-id",
        disk_path="disk:/call.webm",
        disk_filename="call.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        version=3,
    )


@pytest.mark.anyio
async def test_review_resolution_is_bound_and_idempotent(session: object) -> None:
    token = "opaque-review-token-value"
    recording = _recording()
    review = ManualReview(
        recording=recording,
        recording_id=recording.id,
        question_type="multiple_candidates",
        question_context={
            "choices": [
                {
                    "id": "page-id",
                    "name": "Candidate",
                    "url": "https://notion.test/page",
                    "project_or_spot": "Spot A",
                }
            ]
        },
        recruiter_user_id="mm-user",
        mattermost_thread_id="thread",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        recording_version=3,
    )
    session.add(review)  # type: ignore[attr-defined]
    await session.commit()  # type: ignore[attr-defined]
    service = ReviewService(AsyncMock(), Settings())
    first = await service.mutate(
        session,  # type: ignore[arg-type]
        review_id=review.id,
        action="resolve",
        recruiter_user_id="mm-user",
        thread_id="thread",
        token=token,
        expected_version=3,
        idempotency_key="request-123",
        choice=1,
    )
    await session.commit()  # type: ignore[attr-defined]
    replay = await service.mutate(
        session,  # type: ignore[arg-type]
        review_id=review.id,
        action="resolve",
        recruiter_user_id="mm-user",
        thread_id="thread",
        token=token,
        expected_version=3,
        idempotency_key="request-123",
        choice=1,
    )
    assert first.status == RecordingStatus.CANDIDATE_MATCHED
    assert recording.notion_page_id == "page-id"
    assert replay.replayed is True
    assert replay.version == 4


@pytest.mark.anyio
async def test_review_rejects_wrong_thread_before_consuming(session: object) -> None:
    token = "opaque-review-token-value"
    recording = _recording()
    review = ManualReview(
        recording=recording,
        recording_id=recording.id,
        question_type="multiple_candidates",
        question_context={"choices": []},
        recruiter_user_id="mm-user",
        mattermost_thread_id="thread",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        recording_version=3,
    )
    session.add(review)  # type: ignore[attr-defined]
    await session.commit()  # type: ignore[attr-defined]
    with pytest.raises(ReviewRejectedError, match="another Mattermost thread"):
        await ReviewService(AsyncMock(), Settings()).mutate(
            session,  # type: ignore[arg-type]
            review_id=review.id,
            action="ignore",
            recruiter_user_id="mm-user",
            thread_id="wrong",
            token=token,
            expected_version=3,
            idempotency_key="request-456",
        )
    assert review.token_consumed_at is None
