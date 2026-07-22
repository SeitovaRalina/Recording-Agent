"""persist selected notion spot identity

Revision ID: b9b12bbd4cb0
Revises: 20260722_1010
Create Date: 2026-07-23 03:05:39.850387
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9b12bbd4cb0"
down_revision: str | None = "20260722_1010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recordings", sa.Column("notion_spot_id", sa.Text()))
    op.add_column("recordings", sa.Column("notion_spot_url", sa.Text()))


def downgrade() -> None:
    op.drop_column("recordings", "notion_spot_url")
    op.drop_column("recordings", "notion_spot_id")
