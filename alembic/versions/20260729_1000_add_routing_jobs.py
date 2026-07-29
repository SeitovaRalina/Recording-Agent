"""add durable autonomous routing jobs

Revision ID: 20260729_1000
Revises: b9b12bbd4cb0
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260729_1000"
down_revision: str | None = "b9b12bbd4cb0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "routing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("recruiter_id", sa.Uuid(), nullable=False),
        sa.Column("recording_version", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("snapshot_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("dispatch_nonce_hash", sa.Text(), nullable=True),
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_destination_id", sa.Uuid(), nullable=True),
        sa.Column("defer_reason", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
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
            "status IN ('queued', 'dispatched', 'active', 'resolved', 'deferred', 'failed')",
            name="ck_routing_jobs_status",
        ),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recruiter_id"], ["recruiter_config.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resolved_destination_id"], ["storage_destinations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_routing_jobs_ready", "routing_jobs", ["status", "dispatch_lease_expires_at"]
    )
    op.create_index("idx_routing_jobs_recording", "routing_jobs", ["recording_id"])
    op.create_index(
        "uq_routing_jobs_active_recording",
        "routing_jobs",
        ["recording_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'dispatched', 'active')"),
    )


def downgrade() -> None:
    op.drop_index("uq_routing_jobs_active_recording", table_name="routing_jobs")
    op.drop_index("idx_routing_jobs_recording", table_name="routing_jobs")
    op.drop_index("idx_routing_jobs_ready", table_name="routing_jobs")
    op.drop_table("routing_jobs")
