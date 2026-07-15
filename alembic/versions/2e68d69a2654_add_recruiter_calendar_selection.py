"""Add recruiter calendar selection schema.

Revision ID: 2e68d69a2654
Revises: 20260714_1000
Create Date: 2026-07-15 07:13:23.862136
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2e68d69a2654"
down_revision: str | None = "20260714_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruiter_calendar",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruiter_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recruiter_id"],
            ["recruiter_config.id"],
            name="fk_recruiter_calendar_recruiter_id_recruiter_config",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recruiter_calendar"),
        sa.UniqueConstraint("recruiter_id", "canonical_url", name="uq_recruiter_calendar_url"),
    )
    op.create_index(
        "ix_recruiter_calendar_recruiter_id",
        "recruiter_calendar",
        ["recruiter_id"],
    )
    op.create_index(
        "uq_recruiter_calendar_default",
        "recruiter_calendar",
        ["recruiter_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = 1"),
    )
    op.add_column("recordings", sa.Column("calendar_event_recurrence_id", sa.Text()))
    op.add_column("recordings", sa.Column("matched_calendar_id", sa.Uuid()))
    op.add_column("recordings", sa.Column("matched_calendar_url", sa.Text()))
    op.add_column("recordings", sa.Column("matched_calendar_display_name", sa.Text()))
    op.add_column("recordings", sa.Column("manual_review_reason", sa.Text()))
    op.add_column("recordings", sa.Column("manual_review_candidates", sa.JSON()))
    op.create_foreign_key(
        "fk_recordings_matched_calendar_id_recruiter_calendar",
        "recordings",
        "recruiter_calendar",
        ["matched_calendar_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "recruiter_config",
        sa.Column(
            "calendar_selection_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "recruiter_config", sa.Column("calendar_selection_updated_at", sa.DateTime(timezone=True))
    )
    op.add_column("recruiter_config", sa.Column("calendar_selection_updated_by", sa.Text()))
    op.add_column("recruiter_config", sa.Column("calendar_selection_before", sa.JSON()))
    op.add_column("recruiter_config", sa.Column("calendar_selection_after", sa.JSON()))


def downgrade() -> None:
    op.drop_column("recruiter_config", "calendar_selection_after")
    op.drop_column("recruiter_config", "calendar_selection_before")
    op.drop_column("recruiter_config", "calendar_selection_updated_by")
    op.drop_column("recruiter_config", "calendar_selection_updated_at")
    op.drop_column("recruiter_config", "calendar_selection_version")
    op.drop_constraint(
        "fk_recordings_matched_calendar_id_recruiter_calendar",
        "recordings",
        type_="foreignkey",
    )
    op.drop_column("recordings", "manual_review_candidates")
    op.drop_column("recordings", "manual_review_reason")
    op.drop_column("recordings", "matched_calendar_display_name")
    op.drop_column("recordings", "matched_calendar_url")
    op.drop_column("recordings", "matched_calendar_id")
    op.drop_column("recordings", "calendar_event_recurrence_id")
    op.drop_index("uq_recruiter_calendar_default", table_name="recruiter_calendar")
    op.drop_index("ix_recruiter_calendar_recruiter_id", table_name="recruiter_calendar")
    op.drop_table("recruiter_calendar")
