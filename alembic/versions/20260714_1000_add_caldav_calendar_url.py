"""Add CalDAV calendar URL to recruiter configuration.

Revision ID: 20260714_1000
Revises: 20260714_0001
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260714_1000"
down_revision: str | None = "20260714_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recruiter_config", sa.Column("caldav_calendar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("recruiter_config", "caldav_calendar_url")
