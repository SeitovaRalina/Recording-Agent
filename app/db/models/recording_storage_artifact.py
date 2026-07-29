from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecordingStorageArtifact(Base):
    """Immutable evidence for each durable Synology placement."""

    __tablename__ = "recording_storage_artifacts"
    __table_args__ = (
        Index("idx_storage_artifacts_recording", "recording_id"),
        Index(
            "uq_storage_artifacts_active_recording",
            "recording_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    destination_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storage_destinations.id", ondelete="SET NULL")
    )
    folder_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    share_url: Mapped[str] = mapped_column(Text, nullable=False)
    owner_marker_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
