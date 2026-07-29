import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.engine import get_session
from app.db.models.intent_replay import IntentReplay
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.notification_outbox import NotificationOutbox
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.db.models.storage_destination import StorageDestination
from app.main import app
from app.routers.tools import (
    DestinationItem,
    QuestionItem,
    ScanRequest,
    _question_recruiter,
    _scan_interaction_binding,
    _scan_response,
)
from app.scheduler.cron import ScanError, ScanSummary
from app.services.destinations import DestinationService
from app.services.question_queue import QuestionQueueService
from app.services.reviews import (
    InteractionBindingConflict,
    ReviewRejectedError,
    ReviewService,
)

TEST_INTERVIEW_ROOTS = (
    "/home/Recruiting-NE/2. Interviews",
    "/home/Recruiting-E/2. Interviews external",
    "/home/Recruiting-E/3. Interviews internal",
)


@pytest.mark.anyio
async def test_tools_reject_missing_auth(async_client: AsyncClient) -> None:
    response = await async_client.get(
        "/tools/recordings/status", params={"recruiter_user_id": "user"}
    )
    assert response.status_code == 401


def test_question_item_exposes_capability_required_by_answer_contract() -> None:
    assert "capability" in QuestionItem.model_fields


def test_destination_item_exposes_path_label_for_llm_disambiguation() -> None:
    assert "path_label" in DestinationItem.model_fields


def test_scan_response_reports_final_per_recording_outcomes() -> None:
    review = Recording(
        id=uuid4(),
        disk_file_id="review",
        disk_path="disk:/review.webm",
        disk_filename="review.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        manual_review_reason="no_candidate_found",
    )
    completed = Recording(
        id=uuid4(),
        disk_file_id="completed",
        disk_path="disk:/completed.webm",
        disk_filename="completed.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.COMPLETED,
        candidate_name="Иван Иванов",
    )

    response = _scan_response(
        "r@example.com",
        ScanSummary(
            discovered=9,
            inserted=2,
            skipped_legacy=7,
            matched=1,
            inserted_recording_ids=[review.id, completed.id],
        ),
        [review, completed],
    )

    assert response.skipped_legacy == 7
    assert response.manual_review == 1
    assert response.without_review == 1
    assert [item.filename for item in response.items] == ["review.webm", "completed.webm"]
    assert response.items[0].requires_review is True
    assert response.items[0].is_new is True
    assert response.items[0].review_reason == "no_candidate_found"


def test_scan_response_exposes_full_totals_when_items_are_truncated() -> None:
    item = Recording(
        id=uuid4(),
        disk_file_id="review",
        disk_path="disk:/review.webm",
        disk_filename="review.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
    )

    response = _scan_response(
        "r@example.com",
        ScanSummary(recording_ids=[item.id]),
        [item],
        {
            RecordingStatus.MANUAL_REVIEW_REQUIRED: 50,
            RecordingStatus.COMPLETED: 1,
        },
    )

    assert response.processed == 51
    assert response.manual_review == 50
    assert response.without_review == 1
    assert response.items_truncated is True
    assert len(response.items) == 1


def test_scan_response_reports_abort_and_found_as_pending_not_without_review() -> None:
    found_item = Recording(
        id=uuid4(),
        disk_file_id="found",
        disk_path="disk:/found.webm",
        disk_filename="found.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.FOUND,
    )
    response = _scan_response(
        "r@example.com",
        ScanSummary(
            aborted=True,
            failed=1,
            errors=[
                ScanError(
                    stage="calendar_discovery",
                    code="calendar_discovery_failed",
                    message="Calendar discovery could not be refreshed; retry the scan.",
                    retryable=True,
                )
            ],
        ),
        [found_item],
    )

    assert response.aborted is True
    assert response.pending == 1
    assert response.without_review == 0
    assert response.failed_recordings == 0
    assert response.errors[0].code == "calendar_discovery_failed"
    assert "caldav.test" not in response.model_dump_json().casefold()


def test_offline_scan_binding_is_exact_and_in_request_payload() -> None:
    settings = get_settings().model_copy(
        update={"test_mode_enabled": True, "mattermost_delivery_enabled": False}
    )
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="test",
        mattermost_user_id="trusted-user",
    )
    body = ScanRequest(
        recruiter_email=recruiter.email,
        recruiter_user_id="trusted-user",
        mattermost_dm_channel_id="trusted-dm",
        idempotency_key="scan-0001",
    )

    binding = _scan_interaction_binding(settings, recruiter, body)

    assert binding is not None
    assert binding.recruiter_user_id == "trusted-user"
    assert binding.dm_channel_id == "trusted-dm"
    assert body.model_dump()["mattermost_dm_channel_id"] == "trusted-dm"


@pytest.mark.anyio
async def test_offline_question_recruiter_rejects_non_allowlisted_user(
    session: AsyncSession,
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="test",
        mattermost_user_id="blocked-user",
    )
    session.add(recruiter)
    await session.commit()
    settings = get_settings().model_copy(
        update={
            "test_mode_enabled": True,
            "mattermost_delivery_enabled": False,
            "test_recruiter_allowlist": {"r@example.com"},
            "test_notion_database_allowlist": {"db"},
            "test_mattermost_user_allowlist": {"trusted-user"},
        }
    )

    with pytest.raises(ReviewRejectedError, match="allowlist"):
        await _question_recruiter(session, settings, "blocked-user", "trusted-dm")


@pytest.mark.anyio
async def test_offline_scan_binding_race_returns_409_and_releases_intent(
    async_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
        mattermost_user_id="trusted-user",
    )
    session.add(recruiter)
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setenv("TEST_MODE_ENABLED", "true")
    monkeypatch.setenv("MATTERMOST_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("TEST_RECRUITER_ALLOWLIST", '["r@example.com"]')
    monkeypatch.setenv("TEST_NOTION_DATABASE_ALLOWLIST", '["db"]')
    monkeypatch.setenv("TEST_MATTERMOST_USER_ALLOWLIST", '["trusted-user"]')
    monkeypatch.setenv("MINIO_TEST_PREFIX", "root")
    get_settings.cache_clear()
    app.dependency_overrides[get_session] = override_session
    for name in (
        "session_factory",
        "disk_scanner",
        "calendar_client",
        "matcher",
        "candidate_service",
        "transfer_service",
        "status_service",
        "notion_client",
        "review_service",
        "question_queue_service",
        "destination_service",
        "routing_job_service",
    ):
        setattr(app.state, name, MagicMock())
    scan = AsyncMock(
        side_effect=InteractionBindingConflict(
            "Pending question belongs to another interaction"
        )
    )
    monkeypatch.setattr("app.routers.tools.scan_recruiter", scan)

    response = await async_client.post(
        "/tools/scans/trigger",
        headers={"Authorization": "Bearer test-secret"},
        json={
            "recruiter_email": "r@example.com",
            "recruiter_user_id": "trusted-user",
            "mattermost_dm_channel_id": "trusted-dm",
            "scope": "test",
            "idempotency_key": "scan-race-0001",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Pending question belongs to another interaction"
    assert await session.scalar(select(IntentReplay.id)) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "expected_status", "expects_resume"),
    [
        ("ignore", RecordingStatus.IGNORED, False),
        ("resolve", RecordingStatus.COMPLETED, True),
    ],
)
async def test_offline_answer_api_commits_reconciles_replays_and_reports_status(
    action: str,
    expected_status: RecordingStatus,
    expects_resume: bool,
    async_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = f"{action}-valid-token"
    recording = Recording(
        disk_file_id=f"api-{action}",
        disk_path=f"disk:/api-{action}.webm",
        disk_filename=f"api-{action}.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        version=3,
    )
    question = ManualReview(
        recording=recording,
        question_type="multiple_candidates",
        question_context={
            "choices": [
                {
                    "id": "notion-page",
                    "name": "Candidate",
                    "url": "https://notion.example/candidate",
                    "project_or_spot": "Backend",
                }
            ]
        },
        recruiter_user_id="trusted-user",
        mattermost_channel_id="trusted-dm",
        delivery_nonce="nonce",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        recording_version=3,
    )
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
        mattermost_user_id="trusted-user",
    )
    session.add_all([recruiter, question])
    await session.commit()
    recording_id = recording.id
    question_id = question.id
    question_set_id = question.question_set_id

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setenv("TEST_MODE_ENABLED", "true")
    monkeypatch.setenv("MATTERMOST_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("TEST_RECRUITER_ALLOWLIST", '["r@example.com"]')
    monkeypatch.setenv("TEST_NOTION_DATABASE_ALLOWLIST", '["db"]')
    monkeypatch.setenv("TEST_MATTERMOST_USER_ALLOWLIST", '["trusted-user"]')
    monkeypatch.setenv("MINIO_TEST_PREFIX", "root")
    monkeypatch.setenv("OPENCLAW_SECRET", "test-secret")
    get_settings.cache_clear()
    settings = get_settings()
    mattermost = AsyncMock()
    queue = QuestionQueueService(ReviewService(mattermost, settings), mattermost, settings)
    app.dependency_overrides[get_session] = override_session
    app.state.question_queue_service = queue
    for name in (
        "session_factory",
        "disk_scanner",
        "candidate_service",
        "transfer_service",
        "status_service",
        "notion_client",
    ):
        setattr(app.state, name, MagicMock())

    async def finish_pipeline(*_args: object, **_kwargs: object) -> bool:
        loaded = await session.get(Recording, recording_id)
        assert loaded is not None
        loaded.status = RecordingStatus.COMPLETED
        await session.commit()
        return True

    resume = AsyncMock(side_effect=finish_pipeline)
    monkeypatch.setattr("app.routers.tools._resume_transfer_recording", resume)
    action_payload = {
        "question_id": str(question_id),
        "question_set_id": str(question_set_id),
        "action": action,
        "capability": token,
        "expected_version": 3,
        "idempotency_key": f"answer-{action}-0001",
        **({"choice": 1} if action == "resolve" else {}),
    }
    request_payload = {
        "recruiter_user_id": "trusted-user",
        "mattermost_dm_channel_id": "trusted-dm",
        "actions": [action_payload],
    }

    first = await async_client.post(
        "/tools/questions/answer",
        headers={"Authorization": "Bearer test-secret"},
        json=request_payload,
    )
    replay = await async_client.post(
        "/tools/questions/answer",
        headers={"Authorization": "Bearer test-secret"},
        json=request_payload,
    )
    status_response = await async_client.get(
        "/tools/recordings/status",
        headers={"Authorization": "Bearer test-secret"},
        params={"recruiter_user_id": "trusted-user", "recording_id": str(recording_id)},
    )
    await session.refresh(question)
    await session.refresh(recording)

    assert first.status_code == 200
    assert first.json()["accepted"][0]["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["accepted"][0]["replayed"] is True
    assert recording.status == expected_status
    assert question.status == ManualReviewStatus.COMPLETED
    assert status_response.status_code == 200
    assert status_response.json()["items"][0]["status"] == expected_status.value
    assert resume.await_count == (1 if expects_resume else 0)
    assert await session.scalar(select(NotificationOutbox.id)) is None
    mattermost.validate_direct_channel.assert_not_awaited()
    mattermost.send_dm.assert_not_awaited()


@pytest.mark.anyio
async def test_autonomous_destination_answer_validates_then_resumes_once(
    async_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "autonomous-destination-token"
    destination_id = uuid4()
    recording = Recording(
        disk_file_id="autonomous-destination-api",
        disk_path="disk:/autonomous-destination-api.webm",
        disk_filename="autonomous-destination-api.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        version=3,
    )
    question = ManualReview(
        recording=recording,
        question_type="autonomous_routing_ambiguous",
        question_context={
            "choices": [{"destination_id": str(destination_id), "name": "Android"}]
        },
        recruiter_user_id="trusted-user",
        mattermost_channel_id="trusted-dm",
        delivery_nonce="nonce",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        recording_version=3,
    )
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="root",
        mattermost_user_id="trusted-user",
    )
    session.add_all([recruiter, question])
    await session.commit()
    recording_id = recording.id

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setenv("TEST_MODE_ENABLED", "true")
    monkeypatch.setenv("MATTERMOST_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("TEST_RECRUITER_ALLOWLIST", '["r@example.com"]')
    monkeypatch.setenv("TEST_NOTION_DATABASE_ALLOWLIST", '["db"]')
    monkeypatch.setenv("TEST_MATTERMOST_USER_ALLOWLIST", '["trusted-user"]')
    monkeypatch.setenv("MINIO_TEST_PREFIX", "root")
    monkeypatch.setenv("OPENCLAW_SECRET", "test-secret")
    get_settings.cache_clear()
    settings = get_settings()
    mattermost = AsyncMock()
    destinations = AsyncMock()
    destinations.resolve.return_value = MagicMock(id=destination_id)
    app.dependency_overrides[get_session] = override_session
    app.state.question_queue_service = QuestionQueueService(
        ReviewService(mattermost, settings, destinations), mattermost, settings
    )
    for name in (
        "session_factory",
        "disk_scanner",
        "candidate_service",
        "transfer_service",
        "status_service",
        "notion_client",
    ):
        setattr(app.state, name, MagicMock())

    async def finish_pipeline(*_args: object, **_kwargs: object) -> bool:
        loaded = await session.get(Recording, recording_id)
        assert loaded is not None
        loaded.status = RecordingStatus.COMPLETED
        await session.commit()
        return True

    resume = AsyncMock(side_effect=finish_pipeline)
    monkeypatch.setattr("app.routers.tools._resume_transfer_recording", resume)
    payload = {
        "recruiter_user_id": "trusted-user",
        "mattermost_dm_channel_id": "trusted-dm",
        "actions": [
            {
                "question_id": str(question.id),
                "question_set_id": str(question.question_set_id),
                "action": "resolve",
                "capability": token,
                "expected_version": 3,
                "idempotency_key": "autonomous-destination-answer-1",
                "choice": 1,
            }
        ],
    }

    first = await async_client.post(
        "/tools/questions/answer", headers={"Authorization": "Bearer test-secret"}, json=payload
    )
    replay = await async_client.post(
        "/tools/questions/answer", headers={"Authorization": "Bearer test-secret"}, json=payload
    )

    await session.refresh(recording)
    assert first.status_code == 200
    assert first.json()["accepted"][0]["status"] == RecordingStatus.TRANSFER_STARTED
    assert replay.json()["accepted"][0]["replayed"] is True
    assert recording.storage_destination_id == destination_id
    assert recording.status == RecordingStatus.COMPLETED
    destinations.resolve.assert_awaited_once_with(session, recruiter, destination_id)
    resume.assert_awaited_once()


@pytest.mark.anyio
async def test_route_interview_persists_destination_and_resumes_transfer(
    async_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="/home/Recruiting-E",
        mattermost_user_id="trusted-user",
        mattermost_dm_channel="trusted-dm",
    )
    recording = Recording(
        disk_file_id="route-interview",
        disk_path="disk:/route-interview.webm",
        disk_filename="route-interview.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        manual_review_reason="storage_destination_required",
        candidate_name="Candidate",
        notion_page_id="notion-page",
        generated_filename="Candidate - Backend.webm",
        version=5,
    )
    destination = StorageDestination(
        recruiter_id=recruiter.id,
        canonical_path="/home/Recruiting-E/2. Interviews external/Backend",
        display_name="Backend",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    session.add_all([recruiter, recording])
    await session.flush()
    destination.recruiter_id = recruiter.id
    session.add(destination)
    await session.commit()
    recording_id = recording.id
    destination_id = destination.id
    session_factory = async_sessionmaker(session.bind, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def finish_pipeline(*_args: object, **_kwargs: object) -> bool:
        async with session_factory() as resume_session:
            loaded = await resume_session.get(Recording, recording_id)
            assert loaded is not None
            loaded.status = RecordingStatus.COMPLETED
            loaded.synology_share_url = "https://nas.test/share/opaque"
            loaded.version += 1
            await resume_session.commit()
        return True

    app.dependency_overrides[get_session] = override_session
    app.state.destination_service = DestinationService(
        AsyncMock(),
        get_settings().model_copy(
            update={"synology_interview_roots": TEST_INTERVIEW_ROOTS}
        ),
    )
    app.state.session_factory = session_factory
    for name in (
        "disk_scanner",
        "candidate_service",
        "transfer_service",
        "status_service",
        "notion_client",
    ):
        setattr(app.state, name, MagicMock())
    resume = AsyncMock(side_effect=finish_pipeline)
    monkeypatch.setattr("app.routers.tools._resume_transfer_recording", resume)

    response = await async_client.post(
        f"/tools/recordings/{recording_id}/route-interview",
        headers={"Authorization": "Bearer test-secret"},
        json={
            "recruiter_user_id": "trusted-user",
            "mattermost_dm_channel_id": "trusted-dm",
            "destination_id": str(destination_id),
            "expected_version": 5,
            "idempotency_key": "route-interview-0001",
        },
    )
    replay = await async_client.post(
        f"/tools/recordings/{recording_id}/route-interview",
        headers={"Authorization": "Bearer test-secret"},
        json={
            "recruiter_user_id": "trusted-user",
            "mattermost_dm_channel_id": "trusted-dm",
            "destination_id": str(destination_id),
            "expected_version": 5,
            "idempotency_key": "route-interview-0001",
        },
    )
    await session.refresh(recording)

    assert response.status_code == 200
    assert response.json()["status"] == RecordingStatus.COMPLETED.value
    assert response.json()["safe_link"] == "https://nas.test/share/opaque"
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert recording.storage_destination_id == destination_id
    assert recording.storage_key is None
    assert resume.await_count == 1


@pytest.mark.anyio
async def test_route_interview_does_not_complete_intent_when_resume_is_busy(
    async_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="/home/Recruiting-E",
        mattermost_user_id="trusted-user",
        mattermost_dm_channel="trusted-dm",
    )
    recording = Recording(
        disk_file_id="route-interview-busy",
        disk_path="disk:/route-interview-busy.webm",
        disk_filename="route-interview-busy.webm",
        disk_owner_email="r@example.com",
        status=RecordingStatus.MANUAL_REVIEW_REQUIRED,
        manual_review_reason="storage_destination_required",
        candidate_name="Candidate",
        notion_page_id="notion-page",
        generated_filename="Candidate - Backend.webm",
        version=5,
    )
    destination = StorageDestination(
        recruiter_id=recruiter.id,
        canonical_path="/home/Recruiting-E/2. Interviews external/Backend",
        display_name="Backend",
        writable=True,
        symlink_safe=True,
        validated_at=datetime.now(UTC),
    )
    session.add_all([recruiter, recording])
    await session.flush()
    destination.recruiter_id = recruiter.id
    session.add(destination)
    await session.commit()
    recording_id = recording.id
    destination_id = destination.id
    session_factory = async_sessionmaker(session.bind, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.state.destination_service = DestinationService(
        AsyncMock(),
        get_settings().model_copy(
            update={"synology_interview_roots": TEST_INTERVIEW_ROOTS}
        ),
    )
    app.state.session_factory = session_factory
    for name in (
        "disk_scanner",
        "candidate_service",
        "transfer_service",
        "status_service",
        "notion_client",
    ):
        setattr(app.state, name, MagicMock())
    resume = AsyncMock(return_value=False)
    monkeypatch.setattr("app.routers.tools._resume_transfer_recording", resume)

    response = await async_client.post(
        f"/tools/recordings/{recording_id}/route-interview",
        headers={"Authorization": "Bearer test-secret"},
        json={
            "recruiter_user_id": "trusted-user",
            "mattermost_dm_channel_id": "trusted-dm",
            "destination_id": str(destination_id),
            "expected_version": 5,
            "idempotency_key": "route-interview-busy",
        },
    )
    intent = await session.scalar(
        select(IntentReplay).where(
            IntentReplay.operation == f"route-interview:{recording_id}"
        )
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == RecordingStatus.TRANSFER_STARTED.value
    assert intent is not None
    assert intent.state == "pending"
    assert intent.response is None
    assert resume.await_count == 1


@pytest.mark.anyio
async def test_tools_authenticate_docker_bridge_peer_by_secret(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    recruiter = RecruiterConfig(
        email="bridge@example.com",
        notion_database_id="db",
        synology_base_folder="test",
        mattermost_user_id="bridge-user",
    )
    session.add(recruiter)
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setenv("OPENCLAW_SECRET", "test-secret")
    monkeypatch.setenv("TEST_MODE_ENABLED", "false")
    get_settings.cache_clear()
    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app, client=("172.21.0.1", 52236))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            rejected = await client.get(
                "/tools/recordings/status",
                params={"recruiter_user_id": "bridge-user"},
                headers={"Authorization": "Bearer wrong-secret"},
            )
            accepted = await client.get(
                "/tools/recordings/status",
                params={"recruiter_user_id": "bridge-user"},
                headers={"Authorization": "Bearer test-secret"},
            )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()

    assert rejected.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.anyio
async def test_status_query_is_recruiter_scoped(
    async_client: AsyncClient, session: AsyncSession
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="test",
        mattermost_user_id="mm-user",
    )
    session.add_all(
        [
            recruiter,
            Recording(
                disk_file_id="one",
                disk_path="disk:/one.webm",
                disk_filename="one.webm",
                disk_owner_email="r@example.com",
            ),
            Recording(
                disk_file_id="other",
                disk_path="disk:/other.webm",
                disk_filename="other.webm",
                disk_owner_email="other@example.com",
            ),
        ]
    )
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    response = await async_client.get(
        "/tools/recordings/status",
        params={"recruiter_user_id": "mm-user"},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["filename"] == "one.webm"
    assert payload["items"][0]["requires_review"] is False
    assert payload["items"][0]["review_reason"] is None


@pytest.mark.anyio
async def test_status_rejects_authoritative_recruiter_outside_test_scope(
    async_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="production-db",
        synology_base_folder="production-prefix",
        mattermost_user_id="mm-user",
        active=True,
    )
    session.add(recruiter)
    await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setenv("TEST_MODE_ENABLED", "true")
    monkeypatch.setenv("YANDEX_SOURCE_MUTATION_ENABLED", "false")
    monkeypatch.setenv("TEST_MATTERMOST_USER_ALLOWLIST", '["mm-user"]')
    monkeypatch.setenv("TEST_RECRUITER_ALLOWLIST", '["r@example.com"]')
    monkeypatch.setenv("TEST_NOTION_DATABASE_ALLOWLIST", '["test-db"]')
    get_settings.cache_clear()
    response = await async_client.get(
        "/tools/recordings/status",
        params={"recruiter_user_id": "mm-user"},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Notion database is outside the test-mode allowlist"
