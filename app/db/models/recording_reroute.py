from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RerouteStatus(StrEnum):
    PENDING = "pending"
    MOVED = "moved"
    LINKED = "linked"
    NOTION_UPDATED = "notion_updated"
    COMPLETED = "completed"
    FAILED = "failed"


class RecordingReroute(Base):
    __tablename__ = "recording_reroutes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'moved', 'linked', 'notion_updated', 'completed', 'failed')",
            name="ck_recording_reroutes_status",
        ),
        Index("uq_recording_reroutes_idempotency", "recording_id", "idempotency_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    source_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recording_storage_artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_destinations.id", ondelete="RESTRICT"), nullable=False
    )
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RerouteStatus] = mapped_column(
        Text,
        nullable=False,
        default=RerouteStatus.PENDING,
        server_default=RerouteStatus.PENDING.value,
    )
    target_file_path: Mapped[str | None] = mapped_column(Text)
    target_share_url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
