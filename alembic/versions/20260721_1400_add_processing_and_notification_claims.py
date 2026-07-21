"""Add durable processing and notification claims.

Revision ID: 20260721_1400
Revises: 20260721_1300
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_1400"
down_revision: str | None = "20260721_1300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recordings", sa.Column("processing_lease_token", sa.Text()))
    op.add_column(
        "recordings", sa.Column("processing_lease_expires_at", sa.DateTime(timezone=True))
    )
    op.add_column("recordings", sa.Column("terminal_notification_claim", sa.Text()))
    op.add_column(
        "recordings", sa.Column("terminal_notification_claimed_at", sa.DateTime(timezone=True))
    )
    op.add_column("recordings", sa.Column("review_notification_claim", sa.Text()))
    op.add_column(
        "recordings", sa.Column("review_notification_claimed_at", sa.DateTime(timezone=True))
    )
    op.add_column("manual_reviews", sa.Column("delivery_claim", sa.Text()))
    op.add_column("manual_reviews", sa.Column("delivery_claimed_at", sa.DateTime(timezone=True)))
    op.add_column("manual_reviews", sa.Column("delivery_sent_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for column in (
        "delivery_sent_at",
        "delivery_claimed_at",
        "delivery_claim",
    ):
        op.drop_column("manual_reviews", column)
    for column in (
        "review_notification_claimed_at",
        "review_notification_claim",
        "terminal_notification_claimed_at",
        "terminal_notification_claim",
        "processing_lease_expires_at",
        "processing_lease_token",
    ):
        op.drop_column("recordings", column)
