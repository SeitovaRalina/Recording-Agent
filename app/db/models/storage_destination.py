from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StorageDestination(Base):
    __tablename__ = "storage_destinations"
    __table_args__ = (
        UniqueConstraint(
            "recruiter_id", "canonical_path", name="uq_storage_destination_recruiter_path"
        ),
        Index("idx_storage_destinations_recruiter", "recruiter_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruiter_config.id", ondelete="CASCADE"), nullable=False
    )
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    writable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    symlink_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
