from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import Settings
from app.db.models.intent_replay import IntentReplay
from app.db.models.manual_review import ManualReview, ManualReviewStatus
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import enforce_recruiter_scope
from app.tools.mattermost import MattermostClient


class ReviewRejectedError(ValueError):
    pass


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
    def __init__(self, mattermost: MattermostClient, settings: Settings) -> None:
        self._mattermost = mattermost
        self._settings = settings

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
        if existing is not None:
            return existing
        if not recruiter.mattermost_user_id:
            raise ReviewRejectedError("Recruiter has no Mattermost DM mapping")
        self._enforce_user(recruiter.mattermost_user_id)
        token = secrets.token_urlsafe(32)
        choices = (recording.manual_review_candidates or [])[:10]
        rendered = "\n".join(
            f"{index}. {str(choice.get('name') or choice.get('event_summary') or 'option')[:160]}"
            for index, choice in enumerate(choices, start=1)
        )
        message = (
            f"Recording {recording.disk_filename} needs review.\n{rendered}\n"
            f"Reply with a choice or skip. Token: {token}"
        )
        post = await self._mattermost.send_dm(recruiter.mattermost_user_id, message)
        review = ManualReview(
            recording_id=recording.id,
            question_type=recording.manual_review_reason or "manual_review",
            question_context={"choices": choices},
            mattermost_post_id=post.post_id,
            mattermost_channel_id=post.channel_id,
            mattermost_thread_id=post.thread_id,
            recruiter_user_id=recruiter.mattermost_user_id,
            token_hash=self._hash_token(token),
            token_expires_at=datetime.now(UTC)
            + timedelta(seconds=self._settings.review_token_ttl_seconds),
            recording_version=recording.version,
        )
        session.add(review)
        await session.flush()
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
        await self._mattermost.send_dm(recruiter.mattermost_user_id, message)

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
        self._validate_binding(review, recruiter_user_id, thread_id, token, expected_version)
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
                recording.notion_page_id = selected["id"]
                recording.notion_page_url = str(selected.get("url") or "")
                recording.candidate_name = str(selected.get("name") or "")
                recording.project_or_spot = str(selected.get("project_or_spot") or "")
                recording.transition_to(RecordingStatus.CANDIDATE_MATCHED)
                review.parsed_action = "select_card"
                review.resolved_notion_page_id = recording.notion_page_id
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
            else:
                raise ReviewRejectedError("Selected review option cannot resume the pipeline")
        recording.version += 1
        review.status = ManualReviewStatus.RESOLVED
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
    ) -> None:
        self._enforce_user(recruiter_user_id)
        if review.status != ManualReviewStatus.PENDING or review.token_consumed_at is not None:
            raise ReviewRejectedError("Review token is already consumed")
        if review.recruiter_user_id != recruiter_user_id:
            raise ReviewRejectedError("Review belongs to another recruiter")
        if review.mattermost_thread_id != thread_id:
            raise ReviewRejectedError("Review belongs to another Mattermost thread")
        expires = review.token_expires_at
        if expires is None:
            raise ReviewRejectedError("Review token has no expiry")
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= datetime.now(UTC):
            review.status = ManualReviewStatus.EXPIRED
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
