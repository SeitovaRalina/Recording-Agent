import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models.intent_replay import IntentReplay
from app.db.models.manual_review import ManualReview
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
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


@pytest.mark.parametrize(
    "selected",
    [
        {
            "project_or_spot": "Backend",
            "spot_url": "https://notion.test/spot",
        },
        {
            "project_or_spot": "Backend",
            "spot_id": "spot-id",
            "spot_url": "http://notion.test/spot",
        },
    ],
)
def test_multiple_spot_choice_requires_exact_safe_identity(selected: dict[str, str]) -> None:
    with pytest.raises(ReviewRejectedError, match="Selected Spot"):
        ReviewService._selected_spot_identity(selected, required=True)  # noqa: SLF001


@pytest.mark.anyio
async def test_review_resolution_is_bound_and_idempotent(session: object) -> None:
    token = "opaque-review-token-value"
    recording = _recording()
    review = ManualReview(
        recording=recording,
        recording_id=recording.id,
        question_type="multiple_spots",
        question_context={
            "choices": [
                {
                    "id": "page-id",
                    "name": "Candidate",
                    "url": "https://notion.test/page",
                    "project_or_spot": "Backend",
                    "spot_id": "spot-id",
                    "spot_url": "https://notion.test/spot",
                }
            ]
        },
        recruiter_user_id="mm-user",
        mattermost_thread_id="thread",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        recording_version=3,
    )
    session.add_all(  # type: ignore[attr-defined]
        [
            RecruiterConfig(
                email="r@example.com",
                notion_database_id="db",
                synology_base_folder="prefix",
                mattermost_user_id="mm-user",
            ),
            review,
        ]
    )
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
    assert recording.project_or_spot == "Backend"
    assert recording.notion_spot_id == "spot-id"
    assert recording.notion_spot_url == "https://notion.test/spot"
    assert review.result == {
        "selected_choice": {
            "id": "page-id",
            "name": "Candidate",
            "url": "https://notion.test/page",
            "project_or_spot": "Backend",
            "spot_id": "spot-id",
            "spot_url": "https://notion.test/spot",
        }
    }
    assert replay.replayed is True
    assert replay.version == 4

    persisted = await session.scalar(select(IntentReplay))  # type: ignore[attr-defined]
    race_service = ReviewService(AsyncMock(), Settings())
    race_service._find_replay = AsyncMock(  # type: ignore[method-assign]
        side_effect=[None, persisted]
    )
    post_lock_replay = await race_service.mutate(
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
    assert post_lock_replay.replayed is True

    with pytest.raises(ReviewRejectedError, match="idempotency key was reused"):
        await service.mutate(
            session,  # type: ignore[arg-type]
            review_id=review.id,
            action="resolve",
            recruiter_user_id="mm-user",
            thread_id="different-thread",
            token="different-token",
            expected_version=99,
            idempotency_key="request-123",
            choice=1,
        )


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
    session.add_all(  # type: ignore[attr-defined]
        [
            RecruiterConfig(
                email="r@example.com",
                notion_database_id="db",
                synology_base_folder="prefix",
                mattermost_user_id="mm-user",
            ),
            review,
        ]
    )
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
