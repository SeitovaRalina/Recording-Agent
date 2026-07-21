from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ManualReviewStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class ManualReview(Base):
    __tablename__ = "manual_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved', 'expired')", name="ck_manual_reviews_status"
        ),
        Index("idx_manual_reviews_recording_id", "recording_id"),
        Index(
            "idx_manual_reviews_status",
            "status",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    question_context: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    raw_reply: Mapped[str | None] = mapped_column(Text)
    parsed_action: Mapped[str | None] = mapped_column(Text)
    resolved_notion_page_id: Mapped[str | None] = mapped_column(Text)
    mattermost_post_id: Mapped[str | None] = mapped_column(Text)
    mattermost_reply_id: Mapped[str | None] = mapped_column(Text)
    mattermost_channel_id: Mapped[str | None] = mapped_column(Text)
    mattermost_thread_id: Mapped[str | None] = mapped_column(Text)
    recruiter_user_id: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_claim: Mapped[str | None] = mapped_column(Text)
    delivery_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    status: Mapped[ManualReviewStatus] = mapped_column(
        Text,
        nullable=False,
        default=ManualReviewStatus.PENDING,
        server_default=ManualReviewStatus.PENDING.value,
    )

    recording: Mapped[Recording] = relationship(back_populates="manual_reviews")


from app.db.models.recording import Recording  # noqa: E402
