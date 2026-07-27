from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.cleanup_preview import CleanupFileResult, CleanupPreview
from app.db.models.intent_replay import IntentReplay
from app.db.models.manual_review import ManualReview
from app.db.models.notification_outbox import NotificationOutbox
from app.db.models.processing_attempt import ProcessingAttempt
from app.db.models.question_digest import QuestionDigest
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.storage_destination import StorageDestination
from tools.setup.reset_recording_state import (
    CONFIRMATION,
    inspect_recording_state,
    require_safe_reset_settings,
    reset_recording_state,
)


def _test_settings(*, scheduler_enabled: bool = False) -> Settings:
    return Settings(
        app_environment="test",
        test_mode_enabled=True,
        scheduler_enabled=scheduler_enabled,
        yandex_source_mutation_enabled=False,
    )


def test_reset_requires_test_mode_and_disabled_scheduler() -> None:
    with pytest.raises(RuntimeError, match="test mode"):
        require_safe_reset_settings(Settings(app_environment="production"))

    with pytest.raises(RuntimeError, match="scheduler"):
        require_safe_reset_settings(_test_settings(scheduler_enabled=True))


@pytest.mark.anyio
async def test_reset_deletes_only_recording_workflow_state(session: AsyncSession) -> None:
    recording = Recording(
        disk_file_id="disk-file",
        disk_path="/Записи Телемоста/interview.webm",
        disk_filename="interview.webm",
        disk_owner_email="recruiter@example.com",
    )
    session.add(recording)
    await session.flush()
    session.add_all(
        [
            ManualReview(
                recording_id=recording.id,
                question_type="multiple_candidates",
                question_context={},
            ),
            ProcessingAttempt(
                recording_id=recording.id,
                status_before="found",
                status_after="manual_review_required",
                step="candidate_match",
                success=True,
            ),
            IntentReplay(
                actor="codex-test-operator",
                operation="scan",
                idempotency_key="same-scan",
                request_fingerprint="fingerprint",
            ),
        ]
    )
    await session.commit()

    before = await inspect_recording_state(session)
    assert before.recordings == 1
    assert before.manual_reviews == 1
    assert before.processing_attempts == 1
    assert before.intent_replays == 1

    deleted = await reset_recording_state(
        session,
        _test_settings(),
        CONFIRMATION,
    )

    assert deleted == before
    assert await session.scalar(select(Recording)) is None
    assert await session.scalar(select(ManualReview)) is None
    assert await session.scalar(select(ProcessingAttempt)) is None
    assert await session.scalar(select(IntentReplay)) is None


@pytest.mark.anyio
async def test_reset_rejects_wrong_confirmation_without_mutation(session: AsyncSession) -> None:
    recording = Recording(
        disk_file_id="disk-file",
        disk_path="/Записи Телемоста/interview.webm",
        disk_filename="interview.webm",
        disk_owner_email="recruiter@example.com",
    )
    session.add(recording)
    await session.commit()

    with pytest.raises(ValueError, match=CONFIRMATION):
        await reset_recording_state(
            session,
            _test_settings(),
            "wrong",
        )

    assert await session.scalar(select(Recording)) is not None


@pytest.mark.anyio
async def test_reset_clears_new_question_destination_and_cleanup_state(
    session: AsyncSession,
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
    )
    recording = Recording(
        disk_file_id="disk-new-state",
        disk_path="disk:/new-state.webm",
        disk_filename="new-state.webm",
        disk_owner_email=recruiter.email,
    )
    session.add_all([recruiter, recording])
    await session.flush()
    destination = StorageDestination(
        recruiter_id=recruiter.id,
        canonical_path="/root/folder",
        display_name="folder",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    digest = QuestionDigest(
        recruiter_user_id="user",
        mattermost_channel_id="dm",
        local_date=datetime.now(UTC).date(),
    )
    preview = CleanupPreview(
        recruiter_id=recruiter.id,
        recruiter_user_id="user",
        mattermost_dm_channel_id="dm",
        snapshot=[],
        snapshot_hash="snapshot",
        capability_hash="capability",
        capability_expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    session.add_all([destination, digest, preview])
    await session.flush()
    session.add_all(
        [
            NotificationOutbox(
                dedupe_key="digest:test",
                kind="summary",
                recruiter_user_id="user",
                mattermost_channel_id="dm",
                payload={"message": "test"},
            ),
            CleanupFileResult(
                preview_id=preview.id,
                recording_id=recording.id,
                disk_file_id=recording.disk_file_id,
                source_version=recording.version,
                state="eligible",
            ),
        ]
    )
    await session.commit()

    counts = await reset_recording_state(session, _test_settings(), CONFIRMATION)

    assert counts.question_digests == 1
    assert counts.notification_outbox == 1
    assert counts.storage_destinations == 1
    assert counts.cleanup_previews == 1
    assert counts.cleanup_file_results == 1
    assert await session.scalar(select(QuestionDigest)) is None
    assert await session.scalar(select(NotificationOutbox)) is None
    assert await session.scalar(select(StorageDestination)) is None
    assert await session.scalar(select(CleanupPreview)) is None
    assert await session.scalar(select(CleanupFileResult)) is None
