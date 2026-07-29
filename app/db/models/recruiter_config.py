from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RecruiterConfig(Base):
    __tablename__ = "recruiter_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    notion_database_id: Mapped[str] = mapped_column(Text, nullable=False)
    synology_base_folder: Mapped[str] = mapped_column(Text, nullable=False)
    mattermost_user_id: Mapped[str | None] = mapped_column(Text)
    mattermost_dm_channel: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC", server_default="UTC")
    notion_preflight_token_hash: Mapped[str | None] = mapped_column(Text)
    notion_preflight_database_id: Mapped[str | None] = mapped_column(Text)
    notion_preflight_schema_hash: Mapped[str | None] = mapped_column(Text)
    notion_preflight_synthetic_page_id: Mapped[str | None] = mapped_column(Text)
    notion_preflight_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    caldav_calendar_url: Mapped[str | None] = mapped_column(Text)
    calendar_selection_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    calendar_selection_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_selection_updated_by: Mapped[str | None] = mapped_column(Text)
    calendar_selection_before: Mapped[dict[str, object] | None] = mapped_column(JSON)
    calendar_selection_after: Mapped[dict[str, object] | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    calendars: Mapped[list[RecruiterCalendar]] = relationship(
        back_populates="recruiter", cascade="all, delete-orphan"
    )


from app.db.models.recruiter_calendar import RecruiterCalendar  # noqa: E402
