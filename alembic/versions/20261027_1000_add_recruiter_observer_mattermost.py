"""add recruiter observer mattermost columns

Revision ID: 20261027_1000
Revises: 20261006_1000
Create Date: 2026-10-27

Additive, nullable, no backfill: `recruiter_config.observer_mattermost_user_id` and
`recruiter_config.observer_mattermost_dm_channel` let an observed recruiter's row point at a
*different* person's already-provisioned Mattermost DM, which receives a read-only mirror of
every digest/question/confirmation text Backend already sends the recruiter (see
swarm-report/shared-mattermost-observer-plan.md). These columns are never read by
`_bound_recruiter`/`_scan_recruiter`/`_question_recruiter` or any `ManualReview` binding check —
they are a one-way notification destination, not a recruiter identity. NULL means "no observer
configured", which is the previous application version's entire behavior, so it runs unchanged
against the new schema (expand-contract).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_1000"
down_revision: str | None = "20261006_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recruiter_config", sa.Column("observer_mattermost_user_id", sa.Text()))
    op.add_column("recruiter_config", sa.Column("observer_mattermost_dm_channel", sa.Text()))


def downgrade() -> None:
    op.drop_column("recruiter_config", "observer_mattermost_dm_channel")
    op.drop_column("recruiter_config", "observer_mattermost_user_id")
