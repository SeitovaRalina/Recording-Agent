"""Scope cleanup results to one preview.

Revision ID: 20260722_1010
Revises: 20260722_1000
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_1010"
down_revision: str | None = "20260722_1000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'uq_cleanup_file_results_recording' "
            "AND conrelid = 'cleanup_file_results'::regclass) THEN "
            "ALTER TABLE cleanup_file_results "
            "DROP CONSTRAINT uq_cleanup_file_results_recording; "
            "END IF; "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'uq_cleanup_file_results_preview_recording' "
            "AND conrelid = 'cleanup_file_results'::regclass) THEN "
            "ALTER TABLE cleanup_file_results "
            "ADD CONSTRAINT uq_cleanup_file_results_preview_recording "
            "UNIQUE (preview_id, recording_id); "
            "END IF; END $$"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE cleanup_file_results "
            "DROP CONSTRAINT uq_cleanup_file_results_preview_recording; "
            "ALTER TABLE cleanup_file_results "
            "ADD CONSTRAINT uq_cleanup_file_results_recording UNIQUE (recording_id)"
        )
    )
