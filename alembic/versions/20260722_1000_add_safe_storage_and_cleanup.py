"""Add opaque storage destinations and manual cleanup snapshots.

Revision ID: 20260722_1000
Revises: 20260722_0910
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260722_1000"
down_revision: str | None = "20260722_0910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_destinations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruiter_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_path", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("writable", sa.Boolean(), nullable=False),
        sa.Column("symlink_safe", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recruiter_id"], ["recruiter_config.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recruiter_id", "canonical_path", name="uq_storage_destination_recruiter_path"
        ),
    )
    op.create_index("idx_storage_destinations_recruiter", "storage_destinations", ["recruiter_id"])
    op.add_column(
        "recordings",
        sa.Column("route_type", sa.Text(), server_default="interview", nullable=False),
    )
    op.add_column("recordings", sa.Column("storage_destination_id", sa.Uuid(), nullable=True))
    op.add_column(
        "recordings",
        sa.Column(
            "storage_is_durable", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.create_foreign_key(
        "fk_recordings_storage_destination",
        "recordings",
        "storage_destinations",
        ["storage_destination_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_recordings_route_type",
        "recordings",
        "route_type IN ('interview', 'non_interview')",
    )
    op.create_table(
        "cleanup_previews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruiter_id", sa.Uuid(), nullable=False),
        sa.Column("recruiter_user_id", sa.Text(), nullable=False),
        sa.Column("mattermost_dm_channel_id", sa.Text(), nullable=False),
        sa.Column(
            "snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("snapshot_hash", sa.Text(), nullable=False),
        sa.Column("capability_hash", sa.Text(), nullable=False),
        sa.Column("capability_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capability_consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_fingerprint", sa.Text(), nullable=True),
        sa.Column(
            "result",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'expired')",
            name="ck_cleanup_previews_status",
        ),
        sa.ForeignKeyConstraint(["recruiter_id"], ["recruiter_config.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_cleanup_previews_recruiter", "cleanup_previews", ["recruiter_id"])
    op.create_table(
        "cleanup_file_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("preview_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("disk_file_id", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("safe_error", sa.Text(), nullable=True),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["preview_id"], ["cleanup_previews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recording_id", name="uq_cleanup_file_results_recording"),
    )
    op.create_index("idx_cleanup_file_results_preview", "cleanup_file_results", ["preview_id"])


def downgrade() -> None:
    op.drop_index("idx_cleanup_file_results_preview", table_name="cleanup_file_results")
    op.drop_table("cleanup_file_results")
    op.drop_index("idx_cleanup_previews_recruiter", table_name="cleanup_previews")
    op.drop_table("cleanup_previews")
    op.drop_constraint("ck_recordings_route_type", "recordings", type_="check")
    op.drop_constraint("fk_recordings_storage_destination", "recordings", type_="foreignkey")
    op.drop_column("recordings", "storage_is_durable")
    op.drop_column("recordings", "storage_destination_id")
    op.drop_column("recordings", "route_type")
    op.drop_index("idx_storage_destinations_recruiter", table_name="storage_destinations")
    op.drop_table("storage_destinations")
