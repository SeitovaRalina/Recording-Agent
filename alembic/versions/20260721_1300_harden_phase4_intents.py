"""Harden Phase 4 intent replay and Notion preflight.

Revision ID: 20260721_1300
Revises: 20260721_1200
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_1300"
down_revision: str | None = "20260721_1200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "intent_replays",
        sa.Column("request_fingerprint", sa.Text(), server_default="legacy", nullable=False),
    )
    op.add_column(
        "intent_replays",
        sa.Column("state", sa.Text(), server_default="completed", nullable=False),
    )
    op.add_column("intent_replays", sa.Column("claim_owner", sa.Text()))
    op.add_column("intent_replays", sa.Column("claim_expires_at", sa.DateTime(timezone=True)))
    op.alter_column("intent_replays", "response", existing_type=sa.JSON(), nullable=True)
    op.add_column("recruiter_config", sa.Column("notion_preflight_token_hash", sa.Text()))
    op.add_column("recruiter_config", sa.Column("notion_preflight_database_id", sa.Text()))
    op.add_column("recruiter_config", sa.Column("notion_preflight_schema_hash", sa.Text()))
    op.add_column("recruiter_config", sa.Column("notion_preflight_synthetic_page_id", sa.Text()))
    op.add_column(
        "recruiter_config", sa.Column("notion_preflight_completed_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    for column in (
        "notion_preflight_completed_at",
        "notion_preflight_synthetic_page_id",
        "notion_preflight_schema_hash",
        "notion_preflight_database_id",
        "notion_preflight_token_hash",
    ):
        op.drop_column("recruiter_config", column)
    op.alter_column("intent_replays", "response", existing_type=sa.JSON(), nullable=False)
    for column in ("claim_expires_at", "claim_owner", "state", "request_fingerprint"):
        op.drop_column("intent_replays", column)
