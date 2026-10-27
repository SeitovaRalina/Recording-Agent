"""add awaiting_summary_email status and summary tracking columns

Revision ID: 20261006_1000
Revises: 20261002_1000
Create Date: 2026-10-06

All new `recordings` columns are nullable/defaulted and independent of `status`/
`transition_to`; the previous application version selects none of them, so it runs
unchanged against the new schema (expand-contract). Only `ck_recordings_status` is
recreated to admit the new enum value `awaiting_summary_email`.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261006_1000"
down_revision: str | None = "20261002_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = (
    "found",
    "calendar_event_found",
    "candidate_matched",
    "manual_review_required",
    "transfer_started",
    "uploaded_to_synology",
    "synology_link_created",
    "notion_updated",
    "source_marked_processed",
    "source_deleted",
    "completed",
    "ignored",
    "failed",
)
_NEW_STATUSES = (
    "found",
    "calendar_event_found",
    "candidate_matched",
    "manual_review_required",
    "transfer_started",
    "uploaded_to_synology",
    "synology_link_created",
    "notion_updated",
    "awaiting_summary_email",
    "source_marked_processed",
    "source_deleted",
    "completed",
    "ignored",
    "failed",
)


def _check_sql(statuses: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{value}'" for value in statuses) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_recordings_status", "recordings", type_="check")
    op.create_check_constraint("ck_recordings_status", "recordings", _check_sql(_NEW_STATUSES))
    op.add_column(
        "recordings",
        sa.Column(
            "summary_email_search_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "recordings", sa.Column("summary_email_search_deadline_at", sa.DateTime(timezone=True))
    )
    op.add_column("recordings", sa.Column("summary_email_message_id", sa.Text()))
    op.add_column("recordings", sa.Column("summary_email_subject", sa.Text()))
    op.add_column("recordings", sa.Column("summary_email_received_at", sa.DateTime(timezone=True)))
    op.add_column("recordings", sa.Column("summary_toggle_written_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("recordings", "summary_toggle_written_at")
    op.drop_column("recordings", "summary_email_received_at")
    op.drop_column("recordings", "summary_email_subject")
    op.drop_column("recordings", "summary_email_message_id")
    op.drop_column("recordings", "summary_email_search_deadline_at")
    op.drop_column("recordings", "summary_email_search_attempts")
    op.drop_constraint("ck_recordings_status", "recordings", type_="check")
    op.create_check_constraint("ck_recordings_status", "recordings", _check_sql(_OLD_STATUSES))
