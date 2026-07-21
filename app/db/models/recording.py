from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RecordingStatus(StrEnum):
    FOUND = "found"
    CALENDAR_EVENT_FOUND = "calendar_event_found"
    CANDIDATE_MATCHED = "candidate_matched"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    TRANSFER_STARTED = "transfer_started"
    UPLOADED_TO_SYNOLOGY = "uploaded_to_synology"
    SYNOLOGY_LINK_CREATED = "synology_link_created"
    NOTION_UPDATED = "notion_updated"
    SOURCE_MARKED_PROCESSED = "source_marked_processed"
    SOURCE_DELETED = "source_deleted"
    COMPLETED = "completed"
    IGNORED = "ignored"
    FAILED = "failed"


STATUS_VALUES = tuple(status.value for status in RecordingStatus)
STATUS_CHECK_SQL = "status IN (" + ", ".join(f"'{value}'" for value in STATUS_VALUES) + ")"


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (
        CheckConstraint(STATUS_CHECK_SQL, name="ck_recordings_status"),
        Index("idx_recordings_status", "status"),
        Index("idx_recordings_disk_owner", "disk_owner_email"),
        Index(
            "idx_recordings_status_found_at",
            "status",
            "found_at",
            postgresql_where=text("status NOT IN ('completed', 'ignored', 'failed')"),
        ),
        Index("idx_recordings_disk_file_id", "disk_file_id"),
    )

    TRANSITIONS: ClassVar[dict[RecordingStatus, set[RecordingStatus]]] = {
        RecordingStatus.FOUND: {
            RecordingStatus.CALENDAR_EVENT_FOUND,
            RecordingStatus.MANUAL_REVIEW_REQUIRED,
            RecordingStatus.IGNORED,
            RecordingStatus.FAILED,
        },
        RecordingStatus.CALENDAR_EVENT_FOUND: {
            RecordingStatus.CANDIDATE_MATCHED,
            RecordingStatus.MANUAL_REVIEW_REQUIRED,
            RecordingStatus.FAILED,
        },
        RecordingStatus.CANDIDATE_MATCHED: {
            RecordingStatus.TRANSFER_STARTED,
            RecordingStatus.FAILED,
        },
        RecordingStatus.MANUAL_REVIEW_REQUIRED: {
            RecordingStatus.CALENDAR_EVENT_FOUND,
            RecordingStatus.CANDIDATE_MATCHED,
            RecordingStatus.IGNORED,
            RecordingStatus.FAILED,
        },
        RecordingStatus.TRANSFER_STARTED: {
            RecordingStatus.UPLOADED_TO_SYNOLOGY,
            RecordingStatus.FAILED,
        },
        RecordingStatus.UPLOADED_TO_SYNOLOGY: {
            RecordingStatus.SYNOLOGY_LINK_CREATED,
            RecordingStatus.FAILED,
        },
        RecordingStatus.SYNOLOGY_LINK_CREATED: {
            RecordingStatus.NOTION_UPDATED,
            RecordingStatus.FAILED,
        },
        RecordingStatus.NOTION_UPDATED: {
            RecordingStatus.SOURCE_MARKED_PROCESSED,
            RecordingStatus.COMPLETED,
            RecordingStatus.FAILED,
        },
        RecordingStatus.SOURCE_MARKED_PROCESSED: {
            RecordingStatus.SOURCE_DELETED,
            RecordingStatus.COMPLETED,
        },
        RecordingStatus.SOURCE_DELETED: {RecordingStatus.COMPLETED},
        RecordingStatus.COMPLETED: set(),
        RecordingStatus.IGNORED: set(),
        RecordingStatus.FAILED: set(),
    }

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    disk_file_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    disk_path: Mapped[str] = mapped_column(Text, nullable=False)
    disk_filename: Mapped[str] = mapped_column(Text, nullable=False)
    disk_owner_email: Mapped[str] = mapped_column(Text, nullable=False)
    disk_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disk_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disk_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_mime_type: Mapped[str | None] = mapped_column(Text)
    disk_md5: Mapped[str | None] = mapped_column(Text)
    calendar_event_uid: Mapped[str | None] = mapped_column(Text)
    calendar_event_recurrence_id: Mapped[str | None] = mapped_column(Text)
    calendar_event_summary: Mapped[str | None] = mapped_column(Text)
    calendar_dtstart: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_dtend: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_organizer: Mapped[str | None] = mapped_column(Text)
    calendar_telemost_url: Mapped[str | None] = mapped_column(Text)
    calendar_raw_ics: Mapped[str | None] = mapped_column(Text)
    matched_calendar_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruiter_calendar.id", ondelete="SET NULL")
    )
    matched_calendar_url: Mapped[str | None] = mapped_column(Text)
    matched_calendar_display_name: Mapped[str | None] = mapped_column(Text)
    manual_review_reason: Mapped[str | None] = mapped_column(Text)
    manual_review_candidates: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    candidate_name: Mapped[str | None] = mapped_column(Text)
    candidate_email: Mapped[str | None] = mapped_column(Text)
    project_or_spot: Mapped[str | None] = mapped_column(Text)
    notion_database_id: Mapped[str | None] = mapped_column(Text)
    notion_page_id: Mapped[str | None] = mapped_column(Text)
    notion_page_url: Mapped[str | None] = mapped_column(Text)
    synology_folder_path: Mapped[str | None] = mapped_column(Text)
    synology_file_path: Mapped[str | None] = mapped_column(Text)
    synology_share_url: Mapped[str | None] = mapped_column(Text)
    generated_filename: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text, unique=True)
    content_identity: Mapped[str | None] = mapped_column(Text)
    terminal_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))
    status: Mapped[RecordingStatus] = mapped_column(
        Text,
        nullable=False,
        default=RecordingStatus.FOUND,
        server_default=RecordingStatus.FOUND.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    error_step: Mapped[str | None] = mapped_column(Text)
    mattermost_channel_id: Mapped[str | None] = mapped_column(Text)
    mattermost_post_id: Mapped[str | None] = mapped_column(Text)
    found_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_from_disk_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disk_deletable_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_processed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    processing_attempts: Mapped[list[ProcessingAttempt]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )
    manual_reviews: Mapped[list[ManualReview]] = relationship(
        back_populates="recording", cascade="all, delete-orphan"
    )
    matched_calendar: Mapped[RecruiterCalendar | None] = relationship(back_populates="recordings")

    def transition_to(self, new_status: RecordingStatus | str) -> None:
        try:
            current = RecordingStatus(self.status or RecordingStatus.FOUND)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid current recording status {self.status!r}") from error

        try:
            target = RecordingStatus(new_status)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid transition {current.value} → {new_status}") from error

        if target not in self.TRANSITIONS[current]:
            raise ValueError(f"Invalid transition {current.value} → {target.value}")
        self.status = target


from app.db.models.manual_review import ManualReview  # noqa: E402
from app.db.models.processing_attempt import ProcessingAttempt  # noqa: E402
from app.db.models.recruiter_calendar import RecruiterCalendar  # noqa: E402
