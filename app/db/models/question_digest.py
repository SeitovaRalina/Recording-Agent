from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class QuestionDigestStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class QuestionDigest(Base):
    __tablename__ = "question_digests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name="ck_question_digest_status"
        ),
        UniqueConstraint(
            "recruiter_user_id",
            "mattermost_channel_id",
            "local_date",
            name="uq_question_digest_day",
        ),
        Index("idx_question_digest_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruiter_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    mattermost_channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[QuestionDigestStatus] = mapped_column(
        Text, nullable=False, default=QuestionDigestStatus.PENDING, server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list[ManualReview]] = relationship(back_populates="digest")


from app.db.models.manual_review import ManualReview  # noqa: E402
