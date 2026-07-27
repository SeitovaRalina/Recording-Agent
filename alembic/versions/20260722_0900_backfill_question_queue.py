"""Backfill durable question queue state.

Revision ID: 20260722_0900
Revises: f8376c382e77
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0900"
down_revision: str | None = "f8376c382e77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE manual_reviews "
            "SET question_set_id = gen_random_uuid() "
            "WHERE question_set_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE manual_reviews "
            "SET status = 'completed', "
            "completed_at = COALESCE(resolved_at, CURRENT_TIMESTAMP) "
            "WHERE status = 'resolved'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE manual_reviews "
            "SET status = 'suppressed', "
            "suppressed_at = COALESCE(resolved_at, CURRENT_TIMESTAMP) "
            "WHERE status = 'expired'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE manual_reviews "
            "SET status = 'resolved', resolved_at = COALESCE(resolved_at, completed_at) "
            "WHERE status IN ('answered', 'processing', 'completed', 'failed')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE manual_reviews "
            "SET status = 'expired', resolved_at = COALESCE(resolved_at, suppressed_at) "
            "WHERE status = 'suppressed'"
        )
    )
