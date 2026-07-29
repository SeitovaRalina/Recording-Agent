from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.intent_replay import IntentReplay


class IntentRejectedError(ValueError):
    pass


@dataclass(frozen=True)
class IntentClaim:
    replay: IntentReplay
    owner: str | None

    @property
    def completed_response(self) -> dict[str, object] | None:
        return self.replay.response if self.replay.state == "completed" else None


def request_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


async def claim_intent(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: str,
    fingerprint: str,
    ttl_seconds: int,
) -> IntentClaim:
    now = datetime.now(UTC)
    owner = str(uuid.uuid4())
    replay = IntentReplay(
        actor=actor,
        operation=operation,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        state="pending",
        claim_owner=owner,
        claim_expires_at=now + timedelta(seconds=ttl_seconds),
        response=None,
    )
    session.add(replay)
    try:
        await session.commit()
        return IntentClaim(replay, owner)
    except IntegrityError:
        await session.rollback()
    existing = await session.scalar(
        select(IntentReplay)
        .where(
            IntentReplay.actor == actor,
            IntentReplay.operation == operation,
            IntentReplay.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    if existing is None:
        raise IntentRejectedError("Intent claim disappeared")
    replay = existing
    if replay.request_fingerprint != fingerprint:
        raise IntentRejectedError("Idempotency key was reused for another request")
    if replay.state == "completed":
        return IntentClaim(replay, None)
    expires = replay.claim_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires is not None and expires > now:
        raise IntentRejectedError("Intent request is still in progress")
    replay.claim_owner = owner
    replay.claim_expires_at = now + timedelta(seconds=ttl_seconds)
    await session.commit()
    return IntentClaim(replay, owner)


async def complete_intent(
    session: AsyncSession, claim: IntentClaim, response: dict[str, object]
) -> None:
    if claim.owner is None:
        raise IntentRejectedError("Intent claim ownership was lost")
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(IntentReplay)
            .where(
                IntentReplay.id == claim.replay.id,
                IntentReplay.state == "pending",
                IntentReplay.claim_owner == claim.owner,
            )
            .values(
                response=response,
                state="completed",
                claim_owner=None,
                claim_expires_at=None,
            )
        ),
    )
    if result.rowcount != 1:
        await session.rollback()
        raise IntentRejectedError("Intent claim ownership was lost")
    await session.commit()
