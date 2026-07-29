from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.notion_reassignment_proposal import (
    NotionReassignmentProposal,
    NotionReassignmentStatus,
)
from app.db.models.recording import Recording
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.notion import NotionClient, NotionPage


class NotionReassignmentRejectedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReassignmentProposalResult:
    proposal_id: uuid.UUID
    target: NotionPage
    capability: str
    expires_at: datetime


class NotionReassignmentService:
    def __init__(self, notion: NotionClient, settings: Settings) -> None:
        self._notion = notion
        self._settings = settings

    async def resolve_targets(self, recruiter: RecruiterConfig, hint: str) -> list[NotionPage]:
        return await self._notion.resolve_reassignment_targets(
            recruiter.notion_database_id,
            hint,
            name_prop=self._settings.notion_name_prop,
            date_prop=self._settings.notion_date_prop,
            recording_prop=self._settings.notion_recording_prop,
            contacts_prop=self._settings.notion_contacts_prop,
            project_prop=self._settings.notion_project_prop,
            project_prop_type=self._settings.notion_project_prop_type,
        )

    async def propose(
        self,
        session: AsyncSession,
        *,
        recording: Recording,
        recruiter_user_id: str,
        dm_channel_id: str,
        target: NotionPage,
    ) -> ReassignmentProposalResult:
        if not recording.notion_page_id or not recording.synology_share_url:
            raise NotionReassignmentRejectedError("Recording lacks an active Notion link")
        source = await self._notion.get_recording_field(
            recording.notion_page_id, self._settings.notion_recording_prop
        )
        target_snapshot = await self._notion.get_recording_field(
            target.id, self._settings.notion_recording_prop
        )
        capability = secrets.token_urlsafe(32)
        expiry = datetime.now(UTC) + timedelta(seconds=self._settings.review_token_ttl_seconds)
        proposal = NotionReassignmentProposal(
            recording_id=recording.id,
            recruiter_user_id=recruiter_user_id,
            dm_channel_id=dm_channel_id,
            source_page_id=recording.notion_page_id,
            target_page_id=target.id,
            recording_version=recording.version,
            source_snapshot=source,
            target_snapshot=target_snapshot,
            capability_hash=_hash(capability),
            expires_at=expiry,
        )
        session.add(proposal)
        await session.commit()
        return ReassignmentProposalResult(proposal.id, target, capability, expiry)

    async def confirm(
        self,
        session: AsyncSession,
        *,
        proposal_id: uuid.UUID,
        recruiter_user_id: str,
        dm_channel_id: str,
        capability: str,
        idempotency_key: str,
    ) -> Recording:
        proposal = await session.scalar(
            select(NotionReassignmentProposal)
            .where(NotionReassignmentProposal.id == proposal_id)
            .with_for_update()
        )
        if proposal is None:
            raise NotionReassignmentRejectedError("Reassignment proposal not found")
        if (
            proposal.recruiter_user_id != recruiter_user_id
            or proposal.dm_channel_id != dm_channel_id
            or not secrets.compare_digest(proposal.capability_hash, _hash(capability))
        ):
            raise NotionReassignmentRejectedError("Reassignment confirmation is invalid")
        if proposal.status == NotionReassignmentStatus.COMPLETED:
            if proposal.result is None or proposal.result.get("idempotency_key") != idempotency_key:
                raise NotionReassignmentRejectedError("Reassignment idempotency key is invalid")
            recording = await session.get(Recording, proposal.recording_id)
            if recording is None:
                raise NotionReassignmentRejectedError("Recording not found")
            return recording
        if (
            proposal.status != NotionReassignmentStatus.PENDING
            or proposal.expires_at <= datetime.now(UTC)
        ):
            proposal.status = NotionReassignmentStatus.EXPIRED
            await session.commit()
            raise NotionReassignmentRejectedError("Reassignment confirmation is expired")
        recording = await session.get(Recording, proposal.recording_id, with_for_update=True)
        if recording is None or recording.version != proposal.recording_version:
            raise NotionReassignmentRejectedError(
                "Recording changed; create a new reassignment proposal"
            )
        target_written = (
            proposal.result is not None and proposal.result.get("phase") == "target_written"
        )
        source = await self._notion.get_recording_field(
            proposal.source_page_id, self._settings.notion_recording_prop
        )
        target = await self._notion.get_recording_field(
            proposal.target_page_id, self._settings.notion_recording_prop
        )
        if not target_written and (
            source != proposal.source_snapshot or target != proposal.target_snapshot
        ):
            raise NotionReassignmentRejectedError(
                "Notion card changed; create a new reassignment proposal"
            )
        if target_written:
            if source != proposal.source_snapshot:
                raise NotionReassignmentRejectedError(
                    "Source Notion card changed; it was not cleared"
                )
            if not _has_url(target, recording.synology_share_url or ""):
                raise NotionReassignmentRejectedError(
                    "Target Notion card drifted; source was not cleared"
                )
        filename = recording.generated_filename or recording.disk_filename
        # Target write+verify precedes source clear. Source stays untouched on any failure.
        if not target_written:
            await self._notion.replace_recording_link(
                proposal.target_page_id,
                recording_prop=self._settings.notion_recording_prop,
                filename=filename,
                url=recording.synology_share_url or "",
            )
            verified = await self._notion.get_recording_field(
                proposal.target_page_id, self._settings.notion_recording_prop
            )
            if not _has_url(verified, recording.synology_share_url or ""):
                raise NotionReassignmentRejectedError(
                    "Notion target did not persist the recording link"
                )
            proposal.result = {"phase": "target_written", "target_page_id": proposal.target_page_id}
            await session.commit()
        await self._notion.clear_recording_link(
            proposal.source_page_id, recording_prop=self._settings.notion_recording_prop
        )
        recording.notion_page_id = proposal.target_page_id
        recording.version += 1
        proposal.status = NotionReassignmentStatus.COMPLETED
        proposal.consumed_at = datetime.now(UTC)
        proposal.result = {
            "idempotency_key": idempotency_key,
            "target_page_id": proposal.target_page_id,
        }
        await session.commit()
        return recording


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _has_url(snapshot: dict[str, object], url: str) -> bool:
    files = snapshot.get("files")
    return isinstance(files, list) and any(
        isinstance(item, dict)
        and isinstance(item.get("external"), dict)
        and item["external"].get("url") == url
        for item in files
    )
