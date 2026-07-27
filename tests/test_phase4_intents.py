from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.db.models.intent_replay import IntentReplay
from app.services.intents import IntentRejectedError, claim_intent, complete_intent


@pytest.mark.anyio
async def test_stale_intent_worker_cannot_complete_after_takeover(session: object) -> None:
    claim = await claim_intent(
        session,  # type: ignore[arg-type]
        actor="actor",
        operation="scan:test",
        idempotency_key="request-123",
        fingerprint="fingerprint",
        ttl_seconds=60,
    )
    await session.execute(  # type: ignore[attr-defined]
        update(IntentReplay)
        .where(IntentReplay.id == claim.replay.id)
        .values(
            claim_owner="new-worker",
            claim_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )
    await session.commit()  # type: ignore[attr-defined]

    with pytest.raises(IntentRejectedError, match="ownership was lost"):
        await complete_intent(session, claim, {"accepted": True})  # type: ignore[arg-type]
