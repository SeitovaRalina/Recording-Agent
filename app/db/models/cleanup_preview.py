from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CleanupPreview(Base):
    __tablename__ = "cleanup_previews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'expired')",
            name="ck_cleanup_previews_status",
        ),
        Index("idx_cleanup_previews_recruiter", "recruiter_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruiter_config.id", ondelete="CASCADE"), nullable=False
    )
    recruiter_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    mattermost_dm_channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    snapshot_hash: Mapped[str] = mapped_column(Text, nullable=False)
    capability_hash: Mapped[str] = mapped_column(Text, nullable=False)
    capability_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capability_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_fingerprint: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CleanupFileResult(Base):
    __tablename__ = "cleanup_file_results"
    __table_args__ = (
        UniqueConstraint(
            "preview_id",
            "recording_id",
            name="uq_cleanup_file_results_preview_recording",
        ),
        Index("idx_cleanup_file_results_preview", "preview_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    preview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cleanup_previews.id", ondelete="CASCADE"), nullable=False
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    disk_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    safe_error: Mapped[str | None] = mapped_column(Text)
    moved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
