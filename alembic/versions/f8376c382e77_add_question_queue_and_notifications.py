"""Prepare question queue and notification storage.

Revision ID: f8376c382e77
Revises: 20260721_1400
Create Date: 2026-07-22 08:36:43.164110
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f8376c382e77"
down_revision: str | None = "20260721_1400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSITIONAL_REVIEW_STATUSES = (
    "pending",
    "resolved",
    "expired",
    "answered",
    "processing",
    "completed",
    "failed",
    "suppressed",
)


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("recruiter_user_id", sa.Text(), nullable=False),
        sa.Column("mattermost_channel_id", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("claim_owner", sa.Text()),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed')",
            name="ck_notification_outbox_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_notification_outbox_dedupe_key"),
    )
    op.create_index(
        "idx_notification_outbox_delivery",
        "notification_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_table(
        "question_digests",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("recruiter_user_id", sa.Text(), nullable=False),
        sa.Column("mattermost_channel_id", sa.Text(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name="ck_question_digest_status"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recruiter_user_id",
            "mattermost_channel_id",
            "local_date",
            name="uq_question_digest_day",
        ),
    )
    op.create_index("idx_question_digest_status", "question_digests", ["status"])

    op.drop_constraint("ck_manual_reviews_status", "manual_reviews", type_="check")
    op.create_check_constraint(
        "ck_manual_reviews_status",
        "manual_reviews",
        "status IN (" + ", ".join(f"'{value}'" for value in TRANSITIONAL_REVIEW_STATUSES) + ")",
    )
    op.add_column("manual_reviews", sa.Column("question_set_id", sa.Uuid(), nullable=True))
    op.add_column("manual_reviews", sa.Column("digest_id", sa.Uuid()))
    op.add_column(
        "manual_reviews",
        sa.Column(
            "automatic_delivery_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column("manual_reviews", sa.Column("answered_at", sa.DateTime(timezone=True)))
    op.add_column("manual_reviews", sa.Column("processing_at", sa.DateTime(timezone=True)))
    op.add_column("manual_reviews", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.add_column("manual_reviews", sa.Column("failed_at", sa.DateTime(timezone=True)))
    op.add_column("manual_reviews", sa.Column("suppressed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "manual_reviews",
        sa.Column(
            "result",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
        ),
    )
    op.create_foreign_key(
        "fk_manual_reviews_digest_id_question_digests",
        "manual_reviews",
        "question_digests",
        ["digest_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "recruiter_config",
        sa.Column("timezone", sa.Text(), server_default="UTC", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("recruiter_config", "timezone")
    op.drop_constraint(
        "fk_manual_reviews_digest_id_question_digests",
        "manual_reviews",
        type_="foreignkey",
    )
    for column in (
        "result",
        "suppressed_at",
        "failed_at",
        "completed_at",
        "processing_at",
        "answered_at",
        "automatic_delivery_count",
        "digest_id",
        "question_set_id",
    ):
        op.drop_column("manual_reviews", column)
    op.drop_constraint("ck_manual_reviews_status", "manual_reviews", type_="check")
    op.create_check_constraint(
        "ck_manual_reviews_status",
        "manual_reviews",
        "status IN ('pending', 'resolved', 'expired')",
    )
    op.drop_index("idx_question_digest_status", table_name="question_digests")
    op.drop_table("question_digests")
    op.drop_index("idx_notification_outbox_delivery", table_name="notification_outbox")
    op.drop_table("notification_outbox")
