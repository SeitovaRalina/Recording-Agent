"""Enforce durable question queue constraints.

Revision ID: 20260722_0910
Revises: 20260722_0900
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0910"
down_revision: str | None = "20260722_0900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "manual_reviews",
        "question_set_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_constraint("ck_manual_reviews_status", "manual_reviews", type_="check")
    op.create_check_constraint(
        "ck_manual_reviews_status",
        "manual_reviews",
        "status IN ('pending', 'answered', 'processing', 'completed', 'failed', 'suppressed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_manual_reviews_status", "manual_reviews", type_="check")
    op.create_check_constraint(
        "ck_manual_reviews_status",
        "manual_reviews",
        "status IN ("
        "'pending', 'resolved', 'expired', 'answered', 'processing', "
        "'completed', 'failed', 'suppressed'"
        ")",
    )
    op.alter_column(
        "manual_reviews",
        "question_set_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
