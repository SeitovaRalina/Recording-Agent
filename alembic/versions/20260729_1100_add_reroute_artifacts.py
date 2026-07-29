"""add Synology artifact history and reroute state

Revision ID: 20260729_1100
Revises: 20260729_1000
Create Date: 2026-07-29
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260729_1100"
down_revision: str | None = "20260729_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recording_storage_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=True),
        sa.Column("folder_path", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("share_url", sa.Text(), nullable=False),
        sa.Column("owner_marker_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["destination_id"], ["storage_destinations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_path"),
    )
    op.create_index(
        "idx_storage_artifacts_recording", "recording_storage_artifacts", ["recording_id"]
    )
    op.create_index(
        "uq_storage_artifacts_active_recording",
        "recording_storage_artifacts",
        ["recording_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "recording_reroutes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("target_file_path", sa.Text(), nullable=True),
        sa.Column("target_share_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'moved', 'linked', 'notion_updated', 'completed', 'failed')",
            name="ck_recording_reroutes_status",
        ),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["recording_storage_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"], ["storage_destinations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recording_id", "idempotency_key", name="uq_recording_reroutes_idempotency"
        ),
    )
    op.create_table(
        "notion_reassignment_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("recruiter_user_id", sa.Text(), nullable=False),
        sa.Column("dm_channel_id", sa.Text(), nullable=False),
        sa.Column("source_page_id", sa.Text(), nullable=False),
        sa.Column("target_page_id", sa.Text(), nullable=False),
        sa.Column("recording_version", sa.Integer(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("target_snapshot", sa.JSON(), nullable=False),
        sa.Column("capability_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'expired', 'failed')",
            name="ck_notion_reassignment_proposals_status",
        ),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_notion_reassignment_recording", "notion_reassignment_proposals", ["recording_id"]
    )
    # Only complete, durable rows with all path/link identities are safe historical artifacts.
    op.execute("""
        INSERT INTO recording_storage_artifacts
            (id, recording_id, destination_id, folder_path, file_path, share_url, owner_marker_path,
             size_bytes, is_active)
        SELECT gen_random_uuid(), id, storage_destination_id, synology_folder_path, synology_file_path,
               synology_share_url,
               synology_folder_path || '/.' || generated_filename || '.recording-agent-owner.json',
               disk_size_bytes, true
        FROM recordings
        WHERE storage_is_durable = true
          AND synology_folder_path IS NOT NULL
          AND synology_file_path IS NOT NULL
          AND synology_share_url IS NOT NULL
          AND generated_filename IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("idx_notion_reassignment_recording", table_name="notion_reassignment_proposals")
    op.drop_table("notion_reassignment_proposals")
    op.drop_table("recording_reroutes")
    op.drop_index("uq_storage_artifacts_active_recording", table_name="recording_storage_artifacts")
    op.drop_index("idx_storage_artifacts_recording", table_name="recording_storage_artifacts")
    op.drop_table("recording_storage_artifacts")
