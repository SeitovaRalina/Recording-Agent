from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.cleanup_preview import CleanupFileResult, CleanupPreview
from app.db.models.recording import Recording, RecordingStatus
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.disk import DiskScanner


class CleanupRejectedError(ValueError):
    pass


@dataclass(frozen=True)
class CleanupPreviewIssued:
    preview: CleanupPreview
    capability: str


class CleanupService:
    def __init__(self, disk: DiskScanner, settings: Settings) -> None:
        self._disk = disk
        self._settings = settings

    async def preview(
        self,
        session: AsyncSession,
        recruiter: RecruiterConfig,
        *,
        recruiter_user_id: str,
        dm_channel_id: str,
        limit: int,
    ) -> CleanupPreviewIssued:
        self._validate_dm(recruiter, recruiter_user_id, dm_channel_id)
        bounded_limit = min(limit, self._settings.cleanup_preview_max_items)
        rows = list(
            (
                await session.scalars(
                    select(Recording)
                    .where(
                        Recording.disk_owner_email == recruiter.email,
                        Recording.status == RecordingStatus.COMPLETED,
                        Recording.synology_share_url.is_not(None),
                        Recording.storage_is_durable.is_(True),
                        Recording.deleted_from_disk_at.is_(None),
                    )
                    .order_by(Recording.completed_at.asc(), Recording.id.asc())
                    .limit(bounded_limit)
                )
            ).all()
        )
        snapshot = [
            {
                "recording_id": str(row.id),
                "disk_file_id": row.disk_file_id,
                "disk_path": row.disk_path,
                "filename": row.disk_filename,
                "version": row.version,
                "storage_link_hash": hashlib.sha256(
                    (row.synology_share_url or "").encode()
                ).hexdigest(),
            }
            for row in rows
        ]
        snapshot_hash = self._json_hash(snapshot)
        token = secrets.token_urlsafe(32)
        preview = CleanupPreview(
            recruiter_id=recruiter.id,
            recruiter_user_id=recruiter_user_id,
            mattermost_dm_channel_id=dm_channel_id,
            snapshot=snapshot,
            snapshot_hash=snapshot_hash,
            capability_hash=self._hash(token),
            capability_expires_at=datetime.now(UTC)
            + timedelta(seconds=self._settings.cleanup_preview_ttl_seconds),
            status="pending",
        )
        session.add(preview)
        await session.commit()
        return CleanupPreviewIssued(preview, token)

    async def confirm(
        self,
        session: AsyncSession,
        recruiter: RecruiterConfig,
        *,
        preview_id: uuid.UUID,
        recruiter_user_id: str,
        dm_channel_id: str,
        capability: str,
        snapshot_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._validate_dm(recruiter, recruiter_user_id, dm_channel_id)
        preview = await session.scalar(
            select(CleanupPreview).where(CleanupPreview.id == preview_id).with_for_update()
        )
        if preview is None or preview.recruiter_id != recruiter.id:
            raise CleanupRejectedError("Cleanup preview not found")
        fingerprint = self._json_hash(
            {
                "preview_id": str(preview_id),
                "recruiter_user_id": recruiter_user_id,
                "dm_channel_id": dm_channel_id,
                "capability_hash": self._hash(capability),
                "snapshot_hash": snapshot_hash,
                "idempotency_key": idempotency_key,
            }
        )
        if preview.capability_consumed_at is not None:
            if preview.confirmation_fingerprint != fingerprint:
                raise CleanupRejectedError("Cleanup capability was already consumed")
            if preview.result is not None:
                return preview.result
            if preview.status != "processing":
                raise CleanupRejectedError("Cleanup confirmation cannot be resumed")
        elif preview.status != "pending":
            raise CleanupRejectedError("Cleanup preview is not pending")
        if preview.recruiter_user_id != recruiter_user_id:
            raise CleanupRejectedError("Cleanup preview belongs to another recruiter")
        if preview.mattermost_dm_channel_id != dm_channel_id:
            raise CleanupRejectedError("Cleanup preview belongs to another Mattermost DM")
        if not self._settings.yandex_source_mutation_enabled:
            raise CleanupRejectedError("Yandex source mutation is disabled")
        if preview.capability_consumed_at is None:
            expires = preview.capability_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= datetime.now(UTC):
                preview.status = "expired"
                await session.commit()
                raise CleanupRejectedError("Cleanup preview expired")
            if not hmac.compare_digest(preview.capability_hash, self._hash(capability)):
                raise CleanupRejectedError("Cleanup capability is invalid")
            if not hmac.compare_digest(preview.snapshot_hash, snapshot_hash):
                raise CleanupRejectedError("Cleanup snapshot hash changed")
            preview.status = "processing"
            preview.capability_consumed_at = datetime.now(UTC)
            preview.confirmation_fingerprint = fingerprint
            await session.commit()

        results: list[dict[str, str]] = []
        for item in preview.snapshot:
            result = await self._process_item(session, preview, recruiter, item)
            results.append(result)
        payload: dict[str, Any] = {"preview_id": str(preview.id), "items": results}
        preview.status = "completed"
        preview.completed_at = datetime.now(UTC)
        preview.result = payload
        await session.commit()
        return payload

    async def _process_item(
        self,
        session: AsyncSession,
        preview: CleanupPreview,
        recruiter: RecruiterConfig,
        item: dict[str, Any],
    ) -> dict[str, str]:
        try:
            recording_id = uuid.UUID(str(item["recording_id"]))
            expected_version = int(item["version"])
            expected_file_id = str(item["disk_file_id"])
            expected_path = str(item["disk_path"])
        except (KeyError, TypeError, ValueError) as error:
            raise CleanupRejectedError("Cleanup snapshot is invalid") from error
        previous = await session.scalar(
            select(CleanupFileResult).where(
                CleanupFileResult.preview_id == preview.id,
                CleanupFileResult.recording_id == recording_id,
            )
        )
        if previous is not None:
            return {"recording_id": str(recording_id), "state": previous.state}
        unresolved_previous = await session.scalar(
            select(CleanupFileResult).where(
                CleanupFileResult.recording_id == recording_id,
                CleanupFileResult.state.in_(["processing", "moved_to_trash"]),
            )
        )
        if unresolved_previous is not None:
            return {
                "recording_id": str(recording_id),
                "state": unresolved_previous.state,
            }
        recording = await session.get(Recording, recording_id)
        eligible = (
            recording is not None
            and recording.disk_owner_email == recruiter.email
            and recording.disk_file_id == expected_file_id
            and recording.disk_path == expected_path
            and recording.version == expected_version
            and recording.status == RecordingStatus.COMPLETED
            and bool(recording.synology_share_url)
            and recording.storage_is_durable
            and recording.deleted_from_disk_at is None
            and hmac.compare_digest(
                hashlib.sha256((recording.synology_share_url or "").encode()).hexdigest(),
                str(item.get("storage_link_hash") or ""),
            )
        )
        if not eligible or recording is None:
            result = CleanupFileResult(
                preview_id=preview.id,
                recording_id=recording_id,
                disk_file_id=expected_file_id,
                source_version=expected_version,
                state="skipped_drift",
                safe_error="Recording no longer matches the cleanup preview",
            )
            session.add(result)
            await session.commit()
            return {"recording_id": str(recording_id), "state": result.state}
        result = CleanupFileResult(
            preview_id=preview.id,
            recording_id=recording.id,
            disk_file_id=recording.disk_file_id,
            source_version=recording.version,
            state="processing",
        )
        session.add(result)
        await session.commit()
        try:
            await self._disk.move_to_trash(recording.disk_path, recruiter.email)
        except Exception:
            result.state = "failed"
            result.safe_error = "Yandex Trash move failed; retry requires a new preview"
        else:
            moved_at = datetime.now(UTC)
            recording.deleted_from_disk_at = moved_at
            result.state = "moved_to_trash"
            result.moved_at = moved_at
        await session.commit()
        return {"recording_id": str(recording_id), "state": result.state}

    @staticmethod
    def _validate_dm(
        recruiter: RecruiterConfig, recruiter_user_id: str, dm_channel_id: str
    ) -> None:
        if recruiter.mattermost_user_id != recruiter_user_id:
            raise CleanupRejectedError("Recruiter identity does not match configuration")
        if recruiter.mattermost_dm_channel != dm_channel_id:
            raise CleanupRejectedError("Mattermost DM does not match configuration")

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _json_hash(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()
