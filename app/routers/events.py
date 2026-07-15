import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings

OPENCLAW_SECRET_HEADER = "X-OpenClaw-Secret"

router = APIRouter(prefix="/events", tags=["events"])


class OpenClawEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventAccepted(BaseModel):
    accepted: bool


async def verify_openclaw_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_openclaw_secret: Annotated[str | None, Header(alias=OPENCLAW_SECRET_HEADER)] = None,
) -> None:
    expected = settings.openclaw_secret.get_secret_value()
    supplied = x_openclaw_secret or ""
    if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OpenClaw secret"
        )


@router.post(
    "",
    response_model=EventAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_openclaw_secret)],
)
async def receive_event(event: OpenClawEvent) -> EventAccepted:
    del event
    return EventAccepted(accepted=True)
