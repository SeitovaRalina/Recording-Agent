"""Create Phase 1 baseline tables.

Revision ID: 20260714_0001
Revises:
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260714_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORDING_STATUSES = (
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


def upgrade() -> None:
    op.create_table(
        "recordings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("disk_file_id", sa.Text(), nullable=False),
        sa.Column("disk_path", sa.Text(), nullable=False),
        sa.Column("disk_filename", sa.Text(), nullable=False),
        sa.Column("disk_owner_email", sa.Text(), nullable=False),
        sa.Column("disk_created_at", sa.DateTime(timezone=True)),
        sa.Column("disk_modified_at", sa.DateTime(timezone=True)),
        sa.Column("disk_size_bytes", sa.BigInteger()),
        sa.Column("disk_mime_type", sa.Text()),
        sa.Column("disk_md5", sa.Text()),
        sa.Column("calendar_event_uid", sa.Text()),
        sa.Column("calendar_event_summary", sa.Text()),
        sa.Column("calendar_dtstart", sa.DateTime(timezone=True)),
        sa.Column("calendar_dtend", sa.DateTime(timezone=True)),
        sa.Column("calendar_organizer", sa.Text()),
        sa.Column("calendar_telemost_url", sa.Text()),
        sa.Column("calendar_raw_ics", sa.Text()),
        sa.Column("candidate_name", sa.Text()),
        sa.Column("candidate_email", sa.Text()),
        sa.Column("notion_database_id", sa.Text()),
        sa.Column("notion_page_id", sa.Text()),
        sa.Column("notion_page_url", sa.Text()),
        sa.Column("synology_folder_path", sa.Text()),
        sa.Column("synology_file_path", sa.Text()),
        sa.Column("synology_share_url", sa.Text()),
        sa.Column("status", sa.Text(), server_default="found", nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_step", sa.Text()),
        sa.Column("mattermost_channel_id", sa.Text()),
        sa.Column("mattermost_post_id", sa.Text()),
        sa.Column(
            "found_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_from_disk_at", sa.DateTime(timezone=True)),
        sa.Column("disk_deletable_after", sa.DateTime(timezone=True)),
        sa.Column("source_processed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in RECORDING_STATUSES) + ")",
            name="ck_recordings_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("disk_file_id"),
    )
    op.create_index("idx_recordings_status", "recordings", ["status"])
    op.create_index("idx_recordings_disk_owner", "recordings", ["disk_owner_email"])
    op.create_index(
        "idx_recordings_status_found_at",
        "recordings",
        ["status", "found_at"],
        postgresql_where=sa.text("status NOT IN ('completed', 'ignored', 'failed')"),
    )
    op.create_index("idx_recordings_disk_file_id", "recordings", ["disk_file_id"])

    op.create_table(
        "processing_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column(
            "attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("status_before", sa.Text(), nullable=False),
        sa.Column("status_after", sa.Text(), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text())),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_processing_attempts_recording_id", "processing_attempts", ["recording_id"])
    op.create_index("idx_processing_attempts_attempted_at", "processing_attempts", ["attempted_at"])

    op.create_table(
        "recruiter_config",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column("notion_database_id", sa.Text(), nullable=False),
        sa.Column("synology_base_folder", sa.Text(), nullable=False),
        sa.Column("mattermost_user_id", sa.Text()),
        sa.Column("mattermost_dm_channel", sa.Text()),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "manual_reviews",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("question_type", sa.Text(), nullable=False),
        sa.Column("question_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_reply", sa.Text()),
        sa.Column("parsed_action", sa.Text()),
        sa.Column("resolved_notion_page_id", sa.Text()),
        sa.Column("mattermost_post_id", sa.Text()),
        sa.Column("mattermost_reply_id", sa.Text()),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'expired')", name="ck_manual_reviews_status"
        ),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_manual_reviews_recording_id", "manual_reviews", ["recording_id"])
    op.create_index(
        "idx_manual_reviews_status",
        "manual_reviews",
        ["status"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "yandex_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("recruiter_email", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text()),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recruiter_email"),
    )


def downgrade() -> None:
    op.drop_table("yandex_tokens")
    op.drop_index("idx_manual_reviews_status", table_name="manual_reviews")
    op.drop_index("idx_manual_reviews_recording_id", table_name="manual_reviews")
    op.drop_table("manual_reviews")
    op.drop_table("recruiter_config")
    op.drop_index("idx_processing_attempts_attempted_at", table_name="processing_attempts")
    op.drop_index("idx_processing_attempts_recording_id", table_name="processing_attempts")
    op.drop_table("processing_attempts")
    op.drop_index("idx_recordings_disk_file_id", table_name="recordings")
    op.drop_index("idx_recordings_status_found_at", table_name="recordings")
    op.drop_index("idx_recordings_disk_owner", table_name="recordings")
    op.drop_index("idx_recordings_status", table_name="recordings")
    op.drop_table("recordings")
