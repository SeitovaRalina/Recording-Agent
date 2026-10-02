"""add per-recruiter daily digest enabled flag

Revision ID: 20261001_0900
Revises: 20260930_1000
Create Date: 2026-10-01

NOT NULL DEFAULT true: every existing row keeps today's behaviour (the 18:00 digest message
stays on) with no backfill needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261001_0900"
down_revision: str | None = "20260930_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recruiter_config",
        sa.Column(
            "daily_digest_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("recruiter_config", "daily_digest_enabled")
