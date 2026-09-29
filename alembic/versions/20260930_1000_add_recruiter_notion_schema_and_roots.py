"""add per-recruiter notion property map and synology interview roots

Revision ID: 20260930_1000
Revises: 20260729_1100
Create Date: 2026-09-30

NULL in either column means "inherit the global Settings value"; no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260930_1000"
down_revision: str | None = "20260729_1100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recruiter_config", sa.Column("notion_property_map", sa.JSON(), nullable=True))
    op.add_column(
        "recruiter_config", sa.Column("synology_interview_roots", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("recruiter_config", "synology_interview_roots")
    op.drop_column("recruiter_config", "notion_property_map")
