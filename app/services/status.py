from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recording import Recording, RecordingStatus


class StatusService:
    async def advance(
        self,
        session: AsyncSession,
        recording: Recording,
        new_status: RecordingStatus,
        *,
        error_step: str | None = None,
        error_message: str | None = None,
        **field_updates: object,
    ) -> None:
        invalid_fields = [name for name in field_updates if not hasattr(recording, name)]
        if invalid_fields:
            raise AttributeError(f"Recording has no field {invalid_fields[0]!r}")
        recording.transition_to(new_status)
        recording.last_attempted_at = datetime.now(UTC)
        recording.error_step = error_step
        recording.error_message = error_message
        for field_name, value in field_updates.items():
            setattr(recording, field_name, value)
        await session.flush()
