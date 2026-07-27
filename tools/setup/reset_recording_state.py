import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import create_engine, create_session_factory
from app.db.models.cleanup_preview import CleanupFileResult, CleanupPreview
from app.db.models.intent_replay import IntentReplay
from app.db.models.manual_review import ManualReview
from app.db.models.notification_outbox import NotificationOutbox
from app.db.models.processing_attempt import ProcessingAttempt
from app.db.models.question_digest import QuestionDigest
from app.db.models.recording import Recording
from app.db.models.storage_destination import StorageDestination

CONFIRMATION = "RESET-TEST-RECORDING-STATE"


@dataclass(frozen=True)
class RecordingStateCounts:
    recordings: int
    manual_reviews: int
    processing_attempts: int
    intent_replays: int
    question_digests: int
    notification_outbox: int
    storage_destinations: int
    cleanup_previews: int
    cleanup_file_results: int


def require_safe_reset_settings(settings: Settings) -> None:
    if settings.app_environment != "test" or not settings.test_mode_enabled:
        raise RuntimeError("Recording-state reset is allowed only in explicit test mode")
    if settings.scheduler_enabled:
        raise RuntimeError("Disable the scheduler before resetting recording state")


async def inspect_recording_state(session: AsyncSession) -> RecordingStateCounts:
    async def count(model: type[Any]) -> int:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)

    return RecordingStateCounts(
        recordings=await count(Recording),
        manual_reviews=await count(ManualReview),
        processing_attempts=await count(ProcessingAttempt),
        intent_replays=await count(IntentReplay),
        question_digests=await count(QuestionDigest),
        notification_outbox=await count(NotificationOutbox),
        storage_destinations=await count(StorageDestination),
        cleanup_previews=await count(CleanupPreview),
        cleanup_file_results=await count(CleanupFileResult),
    )


async def reset_recording_state(
    session: AsyncSession,
    settings: Settings,
    confirmation: str,
) -> RecordingStateCounts:
    require_safe_reset_settings(settings)
    if confirmation != CONFIRMATION:
        raise ValueError(f"Confirmation must be exactly {CONFIRMATION}")

    counts = await inspect_recording_state(session)
    await session.execute(delete(CleanupFileResult))
    await session.execute(delete(CleanupPreview))
    await session.execute(delete(NotificationOutbox))
    await session.execute(delete(ManualReview))
    await session.execute(delete(QuestionDigest))
    await session.execute(delete(ProcessingAttempt))
    await session.execute(delete(Recording))
    await session.execute(delete(StorageDestination))
    await session.execute(delete(IntentReplay))
    await session.commit()
    return counts


async def _run(apply: bool, confirmation: str | None) -> None:
    settings = get_settings()
    require_safe_reset_settings(settings)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            if apply:
                deleted = await reset_recording_state(
                    session,
                    settings,
                    confirmation or "",
                )
                output = {"mode": "applied", "deleted": asdict(deleted)}
            else:
                counts = await inspect_recording_state(session)
                output = {
                    "mode": "preview",
                    "would_delete": asdict(counts),
                    "confirmation": CONFIRMATION,
                }
            print(json.dumps(output, ensure_ascii=False))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or clear test recording workflow rows while preserving recruiter setup"
        )
    )
    parser.add_argument("--apply", action="store_true", help="Apply the previewed database reset")
    parser.add_argument(
        "--confirm",
        help=f"Required with --apply; exact value: {CONFIRMATION}",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.apply, args.confirm))


if __name__ == "__main__":
    main()
