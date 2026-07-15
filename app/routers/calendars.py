import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.recruiter_calendar import RecruiterCalendar
from app.db.models.recruiter_config import RecruiterConfig
from app.routers.events import verify_openclaw_secret
from app.tools.calendar import CalDAVClient

router = APIRouter(
    prefix="/internal/recruiters/{recruiter_email}/calendars",
    tags=["internal-calendars"],
    dependencies=[Depends(verify_openclaw_secret)],
)


class CalendarItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    available: bool
    selected: bool
    is_default: bool


class CalendarState(BaseModel):
    recruiter_email: str
    version: int
    default_id: uuid.UUID | None
    effective_ids: list[uuid.UUID]
    calendars: list[CalendarItem]


class ReplaceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    calendar_ids: list[uuid.UUID] = Field(max_length=100)


class SetDefault(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    calendar_id: uuid.UUID


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    async with factory() as session:
        yield session


async def verify_internal_request(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Internal endpoint")


InternalRequest = Annotated[None, Depends(verify_internal_request)]
Session = Annotated[AsyncSession, Depends(get_session)]
Actor = Annotated[str, Header(alias="X-Operator-Identity", min_length=1, max_length=200)]


@router.get("", response_model=CalendarState)
async def get_calendar_state(
    recruiter_email: str, session: Session, _internal: InternalRequest
) -> CalendarState:
    return await _state(session, recruiter_email)


@router.post("/discover", response_model=CalendarState)
async def discover_calendars(
    recruiter_email: str,
    request: Request,
    session: Session,
    _internal: InternalRequest,
    _actor: Actor,
) -> CalendarState:
    client = cast(CalDAVClient, request.app.state.calendar_client)
    await client.discover_calendars(recruiter_email)
    return await _state(session, recruiter_email)


@router.put("/selection", response_model=CalendarState)
async def replace_calendar_selection(
    recruiter_email: str,
    body: ReplaceSelection,
    session: Session,
    _internal: InternalRequest,
    actor: Actor,
) -> CalendarState:
    recruiter = await _locked_recruiter(session, recruiter_email)
    _check_version(recruiter, body.version)
    rows = await _calendar_rows(session, recruiter.id)
    requested = set(body.calendar_ids)
    if len(requested) != len(body.calendar_ids):
        raise HTTPException(status_code=422, detail="calendar_ids must be unique")
    owned = {row.id: row for row in rows}
    invalid = [item for item in requested if item not in owned or not owned[item].available]
    if invalid:
        raise HTTPException(status_code=422, detail="Unknown or unavailable calendar ID")
    before = _audit_state(rows)
    for row in rows:
        row.selected = row.id in requested
        row.updated_at = datetime.now(UTC)
    _audit(recruiter, actor, before, _audit_state(rows))
    await session.commit()
    return await _state(session, recruiter_email)


@router.put("/default", response_model=CalendarState)
async def set_default_calendar(
    recruiter_email: str,
    body: SetDefault,
    session: Session,
    _internal: InternalRequest,
    actor: Actor,
) -> CalendarState:
    recruiter = await _locked_recruiter(session, recruiter_email)
    _check_version(recruiter, body.version)
    rows = await _calendar_rows(session, recruiter.id)
    target = next((row for row in rows if row.id == body.calendar_id and row.available), None)
    if target is None:
        raise HTTPException(status_code=422, detail="Unknown or unavailable calendar ID")
    before = _audit_state(rows)
    now = datetime.now(UTC)
    for row in rows:
        if row.is_default and row.id != target.id:
            row.is_default = False
        row.updated_at = now
    await session.flush()
    target.is_default = True
    recruiter.caldav_calendar_url = target.canonical_url
    _audit(recruiter, actor, before, _audit_state(rows))
    await session.commit()
    return await _state(session, recruiter_email)


async def _locked_recruiter(session: AsyncSession, email: str) -> RecruiterConfig:
    recruiter = await session.scalar(
        select(RecruiterConfig).where(RecruiterConfig.email == email).with_for_update()
    )
    if recruiter is None:
        raise HTTPException(status_code=404, detail="Recruiter not found")
    return recruiter


async def _calendar_rows(session: AsyncSession, recruiter_id: uuid.UUID) -> list[RecruiterCalendar]:
    return list(
        (
            await session.scalars(
                select(RecruiterCalendar)
                .where(RecruiterCalendar.recruiter_id == recruiter_id)
                .order_by(RecruiterCalendar.display_name, RecruiterCalendar.id)
            )
        ).all()
    )


async def _state(session: AsyncSession, email: str) -> CalendarState:
    recruiter = await session.scalar(select(RecruiterConfig).where(RecruiterConfig.email == email))
    if recruiter is None:
        raise HTTPException(status_code=404, detail="Recruiter not found")
    rows = await _calendar_rows(session, recruiter.id)
    defaults = [row.id for row in rows if row.is_default and row.available]
    return CalendarState(
        recruiter_email=email,
        version=recruiter.calendar_selection_version,
        default_id=defaults[0] if len(defaults) == 1 else None,
        effective_ids=_effective_ids(rows),
        calendars=[CalendarItem.model_validate(row) for row in rows],
    )


def _effective_ids(rows: list[RecruiterCalendar]) -> list[uuid.UUID]:
    selected = [row.id for row in rows if row.selected and row.available]
    if selected:
        return sorted(selected, key=str)
    return sorted([row.id for row in rows if row.is_default and row.available], key=str)


def _check_version(recruiter: RecruiterConfig, expected: int) -> None:
    if recruiter.calendar_selection_version != expected:
        raise HTTPException(status_code=409, detail="Calendar selection version conflict")


def _audit_state(rows: list[RecruiterCalendar]) -> dict[str, object]:
    defaults = [str(row.id) for row in rows if row.is_default]
    return {
        "effective_ids": [str(item) for item in _effective_ids(rows)],
        "default_id": defaults[0] if len(defaults) == 1 else None,
    }


def _audit(
    recruiter: RecruiterConfig,
    actor: str,
    before: dict[str, object],
    after: dict[str, object],
) -> None:
    recruiter.calendar_selection_before = before
    recruiter.calendar_selection_after = after
    recruiter.calendar_selection_updated_by = actor
    recruiter.calendar_selection_updated_at = datetime.now(UTC)
    recruiter.calendar_selection_version += 1
