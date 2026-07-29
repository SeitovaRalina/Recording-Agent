"""Backfill safe legacy calendar URLs as unavailable defaults.

The migration performs no network requests. Backfilled rows remain unavailable until runtime
CalDAV discovery confirms that the exact canonical URL is a recruiter-owned VEVENT collection on
the configured origin.

Revision ID: 20260715_1400
Revises: 2e68d69a2654
Create Date: 2026-07-15
"""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa

from alembic import op

revision: str = "20260715_1400"
down_revision: str | None = "2e68d69a2654"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_NAMESPACE = uuid.UUID("94f31bd0-7f21-4c4a-a3d8-b2a376a2f7ea")

recruiter_config = sa.table(
    "recruiter_config",
    sa.column("id", sa.Uuid()),
    sa.column("caldav_calendar_url", sa.Text()),
)
recruiter_calendar = sa.table(
    "recruiter_calendar",
    sa.column("id", sa.Uuid()),
    sa.column("recruiter_id", sa.Uuid()),
    sa.column("canonical_url", sa.Text()),
    sa.column("display_name", sa.Text()),
    sa.column("is_default", sa.Boolean()),
    sa.column("selected", sa.Boolean()),
    sa.column("available", sa.Boolean()),
    sa.column("last_seen_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def canonical_legacy_url(value: str) -> str | None:
    """Return a deterministic safe HTTPS URL without asserting calendar ownership."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunsplit(("https", parsed.netloc.lower(), path, parsed.query, ""))


def backfill_id(recruiter_id: uuid.UUID, canonical_url: str) -> uuid.UUID:
    return uuid.uuid5(BACKFILL_NAMESPACE, f"{recruiter_id}:{canonical_url}")


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(recruiter_config.c.id, recruiter_config.c.caldav_calendar_url).where(
            recruiter_config.c.caldav_calendar_url.is_not(None)
        )
    )
    now = datetime.now(UTC)
    for recruiter_id, legacy_url in rows:
        if not isinstance(recruiter_id, uuid.UUID) or not isinstance(legacy_url, str):
            continue
        canonical_url = canonical_legacy_url(legacy_url)
        if canonical_url is None:
            continue
        connection.execute(
            recruiter_calendar.insert().values(
                id=backfill_id(recruiter_id, canonical_url),
                recruiter_id=recruiter_id,
                canonical_url=canonical_url,
                display_name="Legacy default (pending discovery)",
                is_default=True,
                selected=False,
                available=False,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(recruiter_config.c.id, recruiter_config.c.caldav_calendar_url).where(
            recruiter_config.c.caldav_calendar_url.is_not(None)
        )
    )
    ids: list[uuid.UUID] = []
    for recruiter_id, legacy_url in rows:
        if not isinstance(recruiter_id, uuid.UUID) or not isinstance(legacy_url, str):
            continue
        canonical_url = canonical_legacy_url(legacy_url)
        if canonical_url is not None:
            ids.append(backfill_id(recruiter_id, canonical_url))
    if ids:
        connection.execute(recruiter_calendar.delete().where(recruiter_calendar.c.id.in_(ids)))
