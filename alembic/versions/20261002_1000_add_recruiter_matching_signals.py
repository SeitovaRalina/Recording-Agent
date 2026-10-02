"""add per-recruiter matching signals override column

Revision ID: 20261002_1000
Revises: 20261001_0900
Create Date: 2026-10-02

NULL means "inherit app.services.matching's compiled NAME_PATTERN/INTERVIEW_PATTERN/
BOOKING_PATTERN defaults"; no backfill needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261002_1000"
down_revision: str | None = "20261001_0900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recruiter_config", sa.Column("matching_signals", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("recruiter_config", "matching_signals")
