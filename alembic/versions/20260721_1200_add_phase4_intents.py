"""Add Phase 4 deterministic intents and review bindings.

Revision ID: 20260721_1200
Revises: 20260715_1400
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260721_1200"
down_revision: str | None = "20260715_1400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recordings", sa.Column("generated_filename", sa.Text()))
    op.add_column("recordings", sa.Column("storage_key", sa.Text()))
    op.add_column("recordings", sa.Column("content_identity", sa.Text()))
    op.add_column("recordings", sa.Column("project_or_spot", sa.Text()))
    op.add_column("recordings", sa.Column("terminal_notified_at", sa.DateTime(timezone=True)))
    op.add_column(
        "recordings", sa.Column("version", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_unique_constraint("uq_recordings_storage_key", "recordings", ["storage_key"])
    op.add_column("manual_reviews", sa.Column("mattermost_channel_id", sa.Text()))
    op.add_column("manual_reviews", sa.Column("mattermost_thread_id", sa.Text()))
    op.add_column("manual_reviews", sa.Column("recruiter_user_id", sa.Text()))
    op.add_column("manual_reviews", sa.Column("token_hash", sa.Text()))
    op.add_column("manual_reviews", sa.Column("token_expires_at", sa.DateTime(timezone=True)))
    op.add_column("manual_reviews", sa.Column("token_consumed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "manual_reviews",
        sa.Column("recording_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "intent_replays",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor", "operation", "idempotency_key", name="uq_intent_replay"),
    )
    op.create_index("idx_intent_replays_created_at", "intent_replays", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_intent_replays_created_at", table_name="intent_replays")
    op.drop_table("intent_replays")
    for column in (
        "recording_version",
        "token_consumed_at",
        "token_expires_at",
        "token_hash",
        "recruiter_user_id",
        "mattermost_thread_id",
        "mattermost_channel_id",
    ):
        op.drop_column("manual_reviews", column)
    op.drop_constraint("uq_recordings_storage_key", "recordings", type_="unique")
    for column in (
        "version",
        "terminal_notified_at",
        "project_or_spot",
        "content_identity",
        "storage_key",
        "generated_filename",
    ):
        op.drop_column("recordings", column)
