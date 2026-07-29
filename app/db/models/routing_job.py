from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RoutingJobStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    ACTIVE = "active"
    RESOLVED = "resolved"
    DEFERRED = "deferred"
    FAILED = "failed"


class RoutingJob(Base):
    """Durable, bounded hand-off from deterministic scan to the isolated worker."""

    __tablename__ = "routing_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'dispatched', 'active', 'resolved', 'deferred', 'failed')",
            name="ck_routing_jobs_status",
        ),
        Index("idx_routing_jobs_ready", "status", "dispatch_lease_expires_at"),
        Index("idx_routing_jobs_recording", "recording_id"),
        Index(
            "uq_routing_jobs_active_recording",
            "recording_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'dispatched', 'active')"),
            sqlite_where=text("status IN ('queued', 'dispatched', 'active')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruiter_config.id", ondelete="CASCADE"), nullable=False
    )
    recording_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RoutingJobStatus] = mapped_column(
        Text,
        nullable=False,
        default=RoutingJobStatus.QUEUED,
        server_default=RoutingJobStatus.QUEUED.value,
    )
    worker_id: Mapped[str | None] = mapped_column(Text)
    dispatch_nonce_hash: Mapped[str | None] = mapped_column(Text)
    dispatch_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_destination_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storage_destinations.id", ondelete="SET NULL")
    )
    defer_reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
