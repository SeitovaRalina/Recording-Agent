from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import Settings
from app.db.models.intent_replay import IntentReplay
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import enforce_recruiter_scope
from app.services.destinations import DestinationRejectedError, DestinationService
from app.tools.mattermost import MattermostClient

AUTONOMOUS_ROUTING_QUESTION_TYPES = frozenset(
    {
        "autonomous_routing_ambiguous",
        "autonomous_routing_no_match",
        "autonomous_routing_model_error",
    }
)


class ReviewRejectedError(ValueError):
    pass


class InteractionBindingConflict(ReviewRejectedError):
    pass


@dataclass(frozen=True)
class InteractionBinding:
    recruiter_user_id: str
    dm_channel_id: str


@dataclass(frozen=True)
class ReviewMutation:
    review_id: uuid.UUID
    recording_id: uuid.UUID
    status: str
    version: int
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "review_id": str(self.review_id),
            "recording_id": str(self.recording_id),
            "status": self.status,
            "version": self.version,
            "replayed": self.replayed,
        }


class ReviewService:
    def __init__(
        self,
        mattermost: MattermostClient,
        settings: Settings,
        destination_service: DestinationService | None = None,
    ) -> None:
        self._mattermost = mattermost
        self._settings = settings
        self._destinations = destination_service

    def capability_token(self, review: ManualReview) -> str:
        if not review.delivery_nonce:
            raise ReviewRejectedError("Question capability is not initialized")
        return self._derive_review_token(review.id, review.delivery_nonce, review.recording_version)

    def rotate_digest_capability(self, review: ManualReview, *, issued_at: datetime) -> str:
        """Issue a digest-bound capability that remains valid through the next daily digest."""
        review.delivery_nonce = secrets.token_urlsafe(16)
        review.question_set_id = uuid.uuid4()
        review.token_consumed_at = None
        token = self.capability_token(review)
        review.token_hash = self._hash_token(token)
        review.token_expires_at = issued_at + timedelta(
            seconds=self._settings.question_capability_ttl_seconds
        )
        return token

    async def enqueue_review(
        self,
        session: AsyncSession,
        recording: Recording,
        recruiter: RecruiterConfig,
        interaction_binding: InteractionBinding | None = None,
    ) -> ManualReview:
        """Create a durable DM-bound question without sending an individual post."""
        existing = await session.scalar(
            select(ManualReview).where(
                ManualReview.recording_id == recording.id,
                ManualReview.status == ManualReviewStatus.PENDING,
            )
        )
        if existing is not None:
            if interaction_binding is not None and (
                existing.recruiter_user_id != interaction_binding.recruiter_user_id
                or existing.mattermost_channel_id != interaction_binding.dm_channel_id
            ):
                raise ReviewRejectedError("Pending question belongs to another interaction")
            return existing
        if interaction_binding is not None:
            if not self._offline_test_mode:
                raise ReviewRejectedError("Offline interaction binding is unavailable")
            if recruiter.mattermost_user_id != interaction_binding.recruiter_user_id:
                raise ReviewRejectedError(
                    "Interaction requester does not match recruiter configuration"
                )
            self._enforce_user(interaction_binding.recruiter_user_id)
            try:
                enforce_recruiter_scope(self._settings, recruiter)
            except PermissionError as error:
                raise ReviewRejectedError(str(error)) from error
            user_id = interaction_binding.recruiter_user_id
            channel_id = interaction_binding.dm_channel_id
            conflicting = await session.scalar(
                select(ManualReview.id)
                .join(ManualReview.recording)
                .where(
                    Recording.disk_owner_email == recruiter.email,
                    ManualReview.status == ManualReviewStatus.PENDING,
                    or_(
                        ManualReview.recruiter_user_id.is_distinct_from(user_id),
                        ManualReview.mattermost_channel_id.is_distinct_from(channel_id),
                    ),
                )
            )
            if conflicting is not None:
                raise ReviewRejectedError("Pending question belongs to another interaction")
        else:
            if not recruiter.mattermost_user_id or not recruiter.mattermost_dm_channel:
                raise ReviewRejectedError("Recruiter has no exact Mattermost DM mapping")
            self._enforce_user(recruiter.mattermost_user_id)
            await self._mattermost.validate_direct_channel(
                recruiter.mattermost_user_id, recruiter.mattermost_dm_channel
            )
            user_id = recruiter.mattermost_user_id
            channel_id = recruiter.mattermost_dm_channel
        review = ManualReview(
            id=uuid.uuid4(),
            recording_id=recording.id,
            question_type=recording.manual_review_reason or "manual_review",
            question_context={"choices": (recording.manual_review_candidates or [])[:10]},
            recruiter_user_id=user_id,
            mattermost_channel_id=channel_id,
            recording_version=recording.version,
            delivery_nonce=secrets.token_urlsafe(16),
        )
        token = self.capability_token(review)
        review.token_hash = self._hash_token(token)
        review.token_expires_at = datetime.now(UTC) + timedelta(
            seconds=self._settings.review_token_ttl_seconds
        )
        session.add(review)
        await session.flush()
        return review

    @property
    def _offline_test_mode(self) -> bool:
        return self._settings.test_mode_enabled and not self._settings.mattermost_delivery_enabled

    async def issue_review(
        self,
        session: AsyncSession,
        recording: Recording,
        recruiter: RecruiterConfig,
    ) -> ManualReview:
        existing = await session.scalar(
            select(ManualReview).where(
                ManualReview.recording_id == recording.id,
                ManualReview.status == ManualReviewStatus.PENDING,
            )
        )
        if existing is not None and existing.delivery_sent_at is not None:
            return existing
        if not recruiter.mattermost_user_id:
            raise ReviewRejectedError("Recruiter has no Mattermost DM mapping")
        self._enforce_user(recruiter.mattermost_user_id)
        self._review_token_secret()
        claim = str(uuid.uuid4())
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self._settings.intent_claim_ttl_seconds)
        claimed = await session.scalar(
            update(Recording)
            .where(
                Recording.id == recording.id,
                or_(
                    Recording.review_notification_claim.is_(None),
                    Recording.review_notification_claimed_at <= stale_before,
                ),
            )
            .values(
                review_notification_claim=claim,
                review_notification_claimed_at=now,
            )
            .returning(Recording.id)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        if claimed is None:
            if existing is not None:
                return existing
            raise ReviewRejectedError("Review notification is already claimed")
        review_id = existing.id if existing is not None else uuid.uuid4()
        delivery_nonce = existing.delivery_nonce if existing is not None else None
        delivery_nonce = delivery_nonce or secrets.token_urlsafe(16)
        token = self._derive_review_token(review_id, delivery_nonce, recording.version)
        choices = (recording.manual_review_candidates or [])[:10]
        rendered_choices: list[str] = []
        for index, choice in enumerate(choices, start=1):
            details = [str(choice.get("name") or choice.get("event_summary") or "option")[:160]]
            if choice.get("project_or_spot"):
                details.append(f"📍 Spots: {str(choice['project_or_spot'])[:160]}")
            if choice.get("spot_url"):
                details.append(f"Spot: {str(choice['spot_url'])[:500]}")
            if choice.get("general_interview_date"):
                details.append(f"Date: {str(choice['general_interview_date'])[:32]}")
            emails = choice.get("candidate_emails")
            if isinstance(emails, list):
                safe_emails = [str(email)[:320] for email in emails[:3] if isinstance(email, str)]
                if safe_emails:
                    details.append(f"Contacts: {', '.join(safe_emails)}")
            if choice.get("url"):
                details.append(str(choice["url"])[:500])
            rendered_choices.append(f"{index}. " + " — ".join(details))
        rendered = "\n".join(rendered_choices)
        message = (
            f"Recording {recording.disk_filename} needs review.\n{rendered}\n"
            f"Reply with a choice or skip. Token: {token}"
        )
        review = existing or ManualReview(
            id=review_id,
            recording_id=recording.id,
            question_type=recording.manual_review_reason or "manual_review",
            question_context={"choices": choices},
            recruiter_user_id=recruiter.mattermost_user_id,
            recording_version=recording.version,
        )
        review.token_hash = self._hash_token(token)
        review.token_expires_at = datetime.now(UTC) + timedelta(
            seconds=self._settings.review_token_ttl_seconds
        )
        review.delivery_claim = claim
        review.delivery_nonce = delivery_nonce
        review.delivery_claimed_at = datetime.now(UTC)
        if existing is None:
            session.add(review)
        await session.commit()
        post = await self._mattermost.send_dm(
            recruiter.mattermost_user_id,
            message,
            pending_post_id=self._pending_post_id("review", review.id),
        )
        review.mattermost_post_id = post.post_id
        review.mattermost_channel_id = post.channel_id
        review.mattermost_thread_id = post.thread_id
        review.delivery_sent_at = datetime.now(UTC)
        await session.execute(
            update(Recording)
            .where(
                Recording.id == recording.id,
                Recording.review_notification_claim == claim,
            )
            .values(review_notification_claim=None, review_notification_claimed_at=None)
        )
        await session.commit()
        return review

    async def get_bound_review(
        self,
        session: AsyncSession,
        *,
        review_id: uuid.UUID,
        recruiter_user_id: str,
        thread_id: str,
        token: str,
    ) -> ManualReview:
        review = await session.scalar(
            select(ManualReview)
            .where(ManualReview.id == review_id)
            .options(joinedload(ManualReview.recording))
        )
        if review is None:
            raise ReviewRejectedError("Review not found")
        await self._enforce_authoritative_scope(session, review, recruiter_user_id)
        self._validate_binding(
            review,
            recruiter_user_id,
            thread_id,
            token,
            review.recording_version,
        )
        return review

    async def notify_terminal(
        self,
        recording: Recording,
        recruiter: RecruiterConfig,
    ) -> None:
        if not recruiter.mattermost_user_id:
            raise ReviewRejectedError("Recruiter has no Mattermost DM mapping")
        self._enforce_user(recruiter.mattermost_user_id)
        filename = recording.generated_filename or recording.disk_filename
        if recording.status == RecordingStatus.COMPLETED:
            link = recording.synology_share_url or "temporary link unavailable"
            message = (
                f"Recording completed: {recording.candidate_name or 'unknown candidate'}; "
                f"{filename}; {link} (temporary/test-only)."
            )
        else:
            message = (
                f"Recording failed: {recording.candidate_name or 'unknown candidate'}; "
                f"{filename}; step={recording.error_step or 'unknown'}; "
                f"error={(recording.error_message or 'unknown')[:300]}"
            )
        await self._mattermost.send_dm(
            recruiter.mattermost_user_id,
            message,
            pending_post_id=self._pending_post_id("terminal", recording.id, recording.version),
        )

    async def deliver_terminal(
        self,
        session: AsyncSession,
        recording: Recording,
        recruiter: RecruiterConfig,
    ) -> bool:
        claim = str(uuid.uuid4())
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self._settings.intent_claim_ttl_seconds)
        claimed = await session.scalar(
            update(Recording)
            .where(
                Recording.id == recording.id,
                Recording.terminal_notified_at.is_(None),
                or_(
                    Recording.terminal_notification_claim.is_(None),
                    Recording.terminal_notification_claimed_at <= stale_before,
                ),
            )
            .values(
                terminal_notification_claim=claim,
                terminal_notification_claimed_at=now,
            )
            .returning(Recording.id)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        if claimed is None:
            return False
        await self.notify_terminal(recording, recruiter)
        completed = await session.scalar(
            update(Recording)
            .where(
                Recording.id == recording.id,
                Recording.terminal_notification_claim == claim,
            )
            .values(
                terminal_notified_at=datetime.now(UTC),
                terminal_notification_claim=None,
                terminal_notification_claimed_at=None,
            )
            .returning(Recording.id)
        )
        await session.commit()
        return completed is not None

    async def mutate(
        self,
        session: AsyncSession,
        *,
        review_id: uuid.UUID,
        action: Literal["resolve", "ignore"],
        recruiter_user_id: str,
        thread_id: str,
        token: str,
        expected_version: int,
        idempotency_key: str,
        choice: int | None = None,
        bind_dm: bool = False,
    ) -> ReviewMutation:
        operation = f"review:{review_id}:{action}"
        fingerprint = self._request_fingerprint(
            review_id=review_id,
            action=action,
            recruiter_user_id=recruiter_user_id,
            thread_id=thread_id,
            token=token,
            expected_version=expected_version,
            choice=choice,
            bind_dm=bind_dm,
        )
        review = await session.scalar(
            select(ManualReview)
            .where(ManualReview.id == review_id)
            .options(joinedload(ManualReview.recording))
        )
        if review is None:
            raise ReviewRejectedError("Review not found")
        await self._enforce_authoritative_scope(session, review, recruiter_user_id)
        replay = await self._find_replay(session, recruiter_user_id, operation, idempotency_key)
        if replay is not None:
            return self._mutation_from_replay(replay, fingerprint)
        review = await session.scalar(
            select(ManualReview)
            .where(ManualReview.id == review_id)
            .options(joinedload(ManualReview.recording))
            .with_for_update()
        )
        if review is None:
            raise ReviewRejectedError("Review not found")
        await self._enforce_authoritative_scope(session, review, recruiter_user_id)
        replay = await self._find_replay(session, recruiter_user_id, operation, idempotency_key)
        if replay is not None:
            return self._mutation_from_replay(replay, fingerprint)
        self._validate_binding(
            review,
            recruiter_user_id,
            thread_id,
            token,
            expected_version,
            bind_dm=bind_dm,
        )
        recording = review.recording
        now = datetime.now(UTC)
        if action == "ignore":
            recording.transition_to(RecordingStatus.IGNORED)
            review.parsed_action = "ignore"
        else:
            choices = review.question_context.get("choices")
            if (
                not isinstance(choices, list)
                or choice is None
                or choice < 1
                or choice > len(choices)
            ):
                raise ReviewRejectedError("Choice is outside the allowed review options")
            selected = choices[choice - 1]
            if not isinstance(selected, dict):
                raise ReviewRejectedError("Selected review option cannot resume the pipeline")
            if isinstance(selected.get("id"), str):
                spot_id, spot_url = self._selected_spot_identity(
                    selected,
                    required=review.question_type == "multiple_spots",
                )
                recording.notion_page_id = selected["id"]
                recording.notion_page_url = str(selected.get("url") or "")
                recording.candidate_name = str(selected.get("name") or "")
                recording.project_or_spot = str(selected.get("project_or_spot") or "")
                recording.notion_spot_id = spot_id
                recording.notion_spot_url = spot_url
                recording.transition_to(RecordingStatus.CANDIDATE_MATCHED)
                review.parsed_action = "select_card"
                review.resolved_notion_page_id = recording.notion_page_id
                review.result = {"selected_choice": dict(selected)}
            elif isinstance(selected.get("event_uid"), str):
                start = selected.get("event_start_utc")
                if not isinstance(start, str):
                    raise ReviewRejectedError("Calendar choice has no event start")
                recording.calendar_event_uid = selected["event_uid"]
                recording.calendar_event_summary = str(selected.get("event_summary") or "")
                recording.calendar_dtstart = datetime.fromisoformat(start)
                calendar_id = selected.get("calendar_id")
                recording.matched_calendar_id = (
                    uuid.UUID(calendar_id) if isinstance(calendar_id, str) and calendar_id else None
                )
                recording.matched_calendar_display_name = str(
                    selected.get("calendar_display_name") or ""
                )
                recording.manual_review_reason = None
                recording.transition_to(RecordingStatus.CALENDAR_EVENT_FOUND)
                review.parsed_action = "select_calendar_event"
            elif review.question_type in AUTONOMOUS_ROUTING_QUESTION_TYPES:
                destination_id = self._selected_destination_id(selected)
                if self._destinations is None:
                    raise ReviewRejectedError("Synology destination routing is unavailable")
                recruiter = await session.scalar(
                    select(RecruiterConfig).where(
                        RecruiterConfig.email == recording.disk_owner_email
                    )
                )
                if recruiter is None:
                    raise ReviewRejectedError("Recording recruiter configuration is unavailable")
                try:
                    destination = await self._destinations.resolve(
                        session, recruiter, destination_id
                    )
                except (DestinationRejectedError, PermissionError, ValueError) as error:
                    raise ReviewRejectedError(str(error)) from error
                recording.storage_destination_id = destination.id
                recording.storage_key = None
                recording.content_identity = (
                    recording.content_identity or recording.disk_md5 or recording.disk_file_id
                )
                recording.transition_to(RecordingStatus.TRANSFER_STARTED)
                review.parsed_action = "select_synology_destination"
                review.result = {"selected_destination_id": str(destination.id)}
            else:
                raise ReviewRejectedError("Selected review option cannot resume the pipeline")
        recording.version += 1
        review.status = ManualReviewStatus.PROCESSING
        review.answered_at = now
        review.processing_at = now
        review.resolved_at = now
        review.token_consumed_at = now
        result = ReviewMutation(review.id, recording.id, recording.status.value, recording.version)
        session.add(
            IntentReplay(
                actor=recruiter_user_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                state="completed",
                response=result.as_dict(),
            )
        )
        await session.flush()
        return result

    @staticmethod
    def _selected_destination_id(selected: dict[str, Any]) -> uuid.UUID:
        raw_destination_id = selected.get("destination_id")
        if not isinstance(raw_destination_id, str):
            raise ReviewRejectedError("Selected review option has no destination identity")
        try:
            return uuid.UUID(raw_destination_id)
        except ValueError as error:
            raise ReviewRejectedError("Selected destination identity is invalid") from error

    @staticmethod
    def _selected_spot_identity(
        selected: dict[str, Any], *, required: bool
    ) -> tuple[str | None, str | None]:
        title = selected.get("project_or_spot")
        spot_id = selected.get("spot_id")
        spot_url = selected.get("spot_url")
        has_any_identity = bool(spot_id or spot_url)
        if required or has_any_identity:
            if not isinstance(title, str) or not title.strip():
                raise ReviewRejectedError("Selected Spot has no title")
            if not isinstance(spot_id, str) or not spot_id.strip():
                raise ReviewRejectedError("Selected Spot has no opaque identity")
            if not isinstance(spot_url, str):
                raise ReviewRejectedError("Selected Spot has no safe URL")
            parsed = urlsplit(spot_url)
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise ReviewRejectedError("Selected Spot has no safe URL")
            return spot_id, spot_url
        return None, None

    @staticmethod
    async def _find_replay(
        session: AsyncSession, actor: str, operation: str, idempotency_key: str
    ) -> IntentReplay | None:
        return cast(
            IntentReplay | None,
            await session.scalar(
                select(IntentReplay).where(
                    IntentReplay.actor == actor,
                    IntentReplay.operation == operation,
                    IntentReplay.idempotency_key == idempotency_key,
                )
            ),
        )

    @staticmethod
    def _mutation_from_replay(replay: IntentReplay, fingerprint: str) -> ReviewMutation:
        if replay.request_fingerprint != fingerprint:
            raise ReviewRejectedError("Review idempotency key was reused for another request")
        data = replay.response
        if data is None:
            raise ReviewRejectedError("Review request is still in progress")
        return ReviewMutation(
            review_id=uuid.UUID(str(data["review_id"])),
            recording_id=uuid.UUID(str(data["recording_id"])),
            status=str(data["status"]),
            version=int(data["version"]),
            replayed=True,
        )

    def _validate_binding(
        self,
        review: ManualReview,
        recruiter_user_id: str,
        thread_id: str,
        token: str,
        expected_version: int,
        *,
        bind_dm: bool = False,
    ) -> None:
        self._enforce_user(recruiter_user_id)
        if review.status != ManualReviewStatus.PENDING or review.token_consumed_at is not None:
            raise ReviewRejectedError("Review token is already consumed")
        if review.recruiter_user_id != recruiter_user_id:
            raise ReviewRejectedError("Review belongs to another recruiter")
        if bind_dm:
            if review.mattermost_channel_id != thread_id:
                raise ReviewRejectedError("Question belongs to another Mattermost DM")
        elif review.mattermost_thread_id != thread_id:
            raise ReviewRejectedError("Review belongs to another Mattermost thread")
        expires = review.token_expires_at
        if expires is None:
            raise ReviewRejectedError("Review token has no expiry")
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= datetime.now(UTC):
            review.status = ManualReviewStatus.SUPPRESSED
            review.suppressed_at = datetime.now(UTC)
            raise ReviewRejectedError("Review token has expired")
        if (
            review.recording.version != expected_version
            or review.recording_version != expected_version
        ):
            raise ReviewRejectedError("Recording version is stale")
        expected_hash = review.token_hash or ""
        if not hmac.compare_digest(self._hash_token(token), expected_hash):
            raise ReviewRejectedError("Review token is invalid")

    def _enforce_user(self, user_id: str) -> None:
        if (
            self._settings.test_mode_enabled
            and user_id not in self._settings.test_mattermost_user_allowlist
        ):
            raise ReviewRejectedError("Mattermost user is outside the test-mode allowlist")

    async def _enforce_authoritative_scope(
        self, session: AsyncSession, review: ManualReview, requester_user_id: str
    ) -> None:
        recruiter = await session.scalar(
            select(RecruiterConfig).where(
                RecruiterConfig.email == review.recording.disk_owner_email,
                RecruiterConfig.active.is_(True),
            )
        )
        if recruiter is None:
            raise ReviewRejectedError("Active recruiter not found")
        if recruiter.mattermost_user_id != requester_user_id:
            raise ReviewRejectedError("Review requester does not match recruiter configuration")
        try:
            enforce_recruiter_scope(self._settings, recruiter)
        except PermissionError as error:
            raise ReviewRejectedError(str(error)) from error

    @classmethod
    def _request_fingerprint(cls, **payload: object) -> str:
        token = str(payload.pop("token"))
        payload["token_hash"] = cls._hash_token(token)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _review_token_secret(self) -> bytes:
        secret = self._settings.openclaw_secret.get_secret_value()
        if not secret:
            raise ReviewRejectedError("OpenClaw secret is required for review token delivery")
        return secret.encode()

    def _derive_review_token(
        self, review_id: uuid.UUID, delivery_nonce: str, recording_version: int
    ) -> str:
        payload = f"{review_id}:{delivery_nonce}:{recording_version}".encode()
        return hmac.new(self._review_token_secret(), payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _pending_post_id(kind: str, entity_id: uuid.UUID, version: int | None = None) -> str:
        payload = f"recording-agent:{kind}:{entity_id}:{version or 0}"
        return f"{hashlib.sha256(payload.encode()).hexdigest()[:26]}:0"
