from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotionReassignmentStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"


class NotionReassignmentProposal(Base):
    __tablename__ = "notion_reassignment_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'expired', 'failed')",
            name="ck_notion_reassignment_proposals_status",
        ),
        Index("idx_notion_reassignment_recording", "recording_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    recruiter_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    dm_channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_page_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_page_id: Mapped[str] = mapped_column(Text, nullable=False)
    recording_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    target_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    capability_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[NotionReassignmentStatus] = mapped_column(
        Text,
        nullable=False,
        default=NotionReassignmentStatus.PENDING,
        server_default=NotionReassignmentStatus.PENDING.value,
    )
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
