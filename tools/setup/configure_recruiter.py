from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import create_engine, create_session_factory
from app.db.models.recruiter_calendar import RecruiterCalendar
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import notion_schema_hash, notion_token_hash, require_notion_preflight
from app.services.yandex_token_manager import YandexTokenManager
from app.tools.calendar import DISCOVERY_MAX_AGE, CalDAVClient
from app.tools.mattermost import MattermostClient
from app.tools.notion import NotionClient


@dataclass(frozen=True)
class DatabaseInspection:
    database_id: str
    title: str
    property_types: dict[str, str]


class DatabaseInspector(Protocol):
    async def inspect(self, database_id: str) -> DatabaseInspection: ...


class YandexCredentialProbe(Protocol):
    async def probe(self, recruiter_email: str) -> None: ...


class CalendarProvisioner(Protocol):
    async def discover_calendars(self, recruiter_email: str) -> list[RecruiterCalendar]: ...


class MattermostUserProbe(Protocol):
    async def probe_user(self, recruiter_user_id: str) -> None: ...


class YandexProbe:
    def __init__(self, token_manager: YandexTokenManager) -> None:
        self._token_manager = token_manager

    async def probe(self, recruiter_email: str) -> None:
        await self._token_manager.get_access_token(recruiter_email)


class NotionInspector:
    def __init__(self, notion: NotionClient, settings: Settings) -> None:
        self._notion = notion
        self._settings = settings

    async def inspect(self, database_id: str) -> DatabaseInspection:
        inspection = await self._notion.inspect_database(
            database_id,
            self._settings.notion_name_prop,
            self._settings.notion_date_prop,
            self._settings.notion_recording_prop,
            self._settings.notion_project_prop,
        )
        return DatabaseInspection(
            database_id=database_id,
            title=inspection.title,
            property_types=inspection.schema.property_types,
        )


def parse_notion_database_id(value: str) -> str:
    raw = value.strip()
    compact = raw.replace("-", "")
    if re.fullmatch(r"[0-9a-fA-F]{32}", compact):
        return str(uuid.UUID(compact))
    path_tail = raw.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
    match = re.search(r"([0-9a-fA-F]{32})$", path_tail)
    if match is None:
        raise ValueError("Explicit Notion URL/ID has no database UUID")
    return str(uuid.UUID(match.group(1)))


async def configure_recruiter(
    session: AsyncSession,
    inspector: DatabaseInspector,
    settings: Settings,
    *,
    email: str,
    notion_target: str,
    mattermost_user_id: str,
    storage_prefix: str,
    confirmed: bool,
    inspection: DatabaseInspection | None = None,
) -> RecruiterConfig:
    normalized_email = email.strip().casefold()
    if normalized_email not in settings.yandex_refresh_tokens:
        raise ValueError("Yandex refresh token is not provisioned for recruiter")
    if normalized_email not in settings.yandex_caldav_passwords:
        raise ValueError("CalDAV app password is not provisioned for recruiter")
    if await session.scalar(
        select(RecruiterConfig.id).where(RecruiterConfig.email == normalized_email)
    ):
        raise ValueError("Recruiter already exists")
    database_id = parse_notion_database_id(notion_target)
    if inspection is None:
        inspection = await inspector.inspect(database_id)
        _display_inspection(inspection)
    elif inspection.database_id != database_id:
        raise ValueError("Database inspection does not match explicit Notion target")
    if not confirmed:
        raise ValueError("Operator confirmation is required")
    recruiter = RecruiterConfig(
        email=normalized_email,
        notion_database_id=database_id,
        mattermost_user_id=mattermost_user_id.strip(),
        synology_base_folder=storage_prefix.strip(" /"),
        active=False,
    )
    session.add(recruiter)
    await session.commit()
    return recruiter


async def preflight_recruiter_notion(
    session: AsyncSession,
    notion: NotionClient,
    settings: Settings,
    *,
    recruiter_email: str,
    synthetic_page_id: str,
) -> RecruiterConfig:
    recruiter = await session.scalar(
        select(RecruiterConfig).where(
            RecruiterConfig.email == recruiter_email.strip().casefold(),
            RecruiterConfig.active.is_(False),
        )
    )
    if recruiter is None:
        raise ValueError("Inactive recruiter config not found")
    inspection = await notion.preflight_database(
        recruiter.notion_database_id,
        synthetic_page_id,
        settings.notion_name_prop,
        settings.notion_date_prop,
        settings.notion_recording_prop,
        settings.notion_project_prop,
    )
    if inspection.database_id != recruiter.notion_database_id:
        raise ValueError("Notion preflight returned another database")
    recruiter.notion_preflight_token_hash = notion_token_hash(settings)
    recruiter.notion_preflight_database_id = recruiter.notion_database_id
    recruiter.notion_preflight_schema_hash = notion_schema_hash(settings)
    recruiter.notion_preflight_synthetic_page_id = synthetic_page_id
    recruiter.notion_preflight_completed_at = datetime.now(UTC)
    await session.commit()
    return recruiter


async def preflight_recruiter(
    session: AsyncSession,
    settings: Settings,
    *,
    recruiter_email: str,
    synthetic_page_id: str,
    default_calendar_id: str,
    yandex_probe: YandexCredentialProbe,
    calendar: CalendarProvisioner,
    notion: NotionClient,
    mattermost: MattermostUserProbe,
) -> RecruiterConfig:
    recruiter = await _inactive_recruiter(session, recruiter_email)
    _require_configured_credentials(settings, recruiter)
    if not recruiter.mattermost_user_id:
        raise ValueError("Mattermost recruiter mapping is missing")

    await yandex_probe.probe(recruiter.email)
    await calendar.discover_calendars(recruiter.email)
    rows = list(
        (
            await session.scalars(
                select(RecruiterCalendar).where(RecruiterCalendar.recruiter_id == recruiter.id)
            )
        ).all()
    )
    target = next(
        (row for row in rows if str(row.id) == default_calendar_id and row.available), None
    )
    if target is None:
        raise ValueError("Explicit default calendar is unknown or unavailable")
    for row in rows:
        row.is_default = row is target
    recruiter.caldav_calendar_url = target.canonical_url
    await mattermost.probe_user(recruiter.mattermost_user_id)
    await session.commit()
    return await preflight_recruiter_notion(
        session,
        notion,
        settings,
        recruiter_email=recruiter.email,
        synthetic_page_id=synthetic_page_id,
    )


async def activate_recruiter(
    session: AsyncSession,
    settings: Settings,
    *,
    recruiter_email: str,
    yandex_probe: YandexCredentialProbe,
    mattermost: MattermostUserProbe,
) -> RecruiterConfig:
    recruiter = await _inactive_recruiter(session, recruiter_email)
    _require_configured_credentials(settings, recruiter)
    if not recruiter.mattermost_user_id:
        raise ValueError("Mattermost recruiter mapping is missing")
    try:
        require_notion_preflight(settings, recruiter)
    except PermissionError as error:
        raise ValueError("Notion preflight is missing or stale") from error

    rows = list(
        (
            await session.scalars(
                select(RecruiterCalendar).where(RecruiterCalendar.recruiter_id == recruiter.id)
            )
        ).all()
    )
    defaults = [row for row in rows if row.is_default and row.available]
    cutoff = datetime.now(UTC) - DISCOVERY_MAX_AGE
    if len(defaults) != 1 or _as_utc(defaults[0].last_seen_at) < cutoff:
        raise ValueError("Current calendar discovery and one explicit default are required")

    await yandex_probe.probe(recruiter.email)
    await mattermost.probe_user(recruiter.mattermost_user_id)
    recruiter.active = True
    await session.commit()
    return recruiter


async def _inactive_recruiter(session: AsyncSession, recruiter_email: str) -> RecruiterConfig:
    recruiter = await session.scalar(
        select(RecruiterConfig).where(
            RecruiterConfig.email == recruiter_email.strip().casefold(),
            RecruiterConfig.active.is_(False),
        )
    )
    if recruiter is None:
        raise ValueError("Inactive recruiter config not found")
    return recruiter


def _require_configured_credentials(settings: Settings, recruiter: RecruiterConfig) -> None:
    if recruiter.email not in settings.yandex_refresh_tokens:
        raise ValueError("Yandex refresh token is not provisioned for recruiter")
    if recruiter.email not in settings.yandex_caldav_passwords:
        raise ValueError("CalDAV app password is not provisioned for recruiter")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _display_inspection(inspection: DatabaseInspection) -> None:
    print(f"Database: {inspection.title} ({inspection.database_id})")
    print(
        "Schema: " + ", ".join(f"{name}:{kind}" for name, kind in inspection.property_types.items())
    )


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with httpx.AsyncClient(timeout=30) as client:
        notion = NotionClient(settings.notion_token, client, settings=settings)
        inspector = NotionInspector(notion, settings)
        try:
            async with factory() as session:
                if args.command == "configure":
                    database_id = parse_notion_database_id(args.notion)
                    inspection = await inspector.inspect(database_id)
                    _display_inspection(inspection)
                    confirmed = (
                        input("Create inactive recruiter config? [yes/no] ").strip() == "yes"
                    )
                    await configure_recruiter(
                        session,
                        inspector,
                        settings,
                        email=args.email,
                        notion_target=args.notion,
                        mattermost_user_id=args.mattermost_user_id,
                        storage_prefix=args.storage_prefix,
                        confirmed=confirmed,
                        inspection=inspection,
                    )
                else:
                    yandex = YandexProbe(YandexTokenManager(factory, settings, client))
                    mattermost = MattermostClient(
                        settings.mattermost_url,
                        settings.mattermost_bot_token,
                        settings.mattermost_bot_user_id,
                        client,
                    )
                    if args.command == "preflight":
                        await preflight_recruiter(
                            session,
                            settings,
                            recruiter_email=args.email,
                            synthetic_page_id=args.synthetic_page_id,
                            default_calendar_id=args.default_calendar_id,
                            yandex_probe=yandex,
                            calendar=CalDAVClient(settings, factory, client),
                            notion=notion,
                            mattermost=mattermost,
                        )
                    elif input("Activate recruiter? [yes/no] ").strip() == "yes":
                        await activate_recruiter(
                            session,
                            settings,
                            recruiter_email=args.email,
                            yandex_probe=yandex,
                            mattermost=mattermost,
                        )
                    else:
                        raise ValueError("Operator confirmation is required")
        finally:
            await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Operator-only recruiter onboarding")
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure", help="Create an inactive recruiter")
    configure.add_argument("--email", required=True)
    configure.add_argument("--notion", required=True, help="Explicit Notion database URL or ID")
    configure.add_argument("--mattermost-user-id", required=True)
    configure.add_argument("--storage-prefix", required=True)
    preflight = commands.add_parser("preflight", help="Run all inactive recruiter preflights")
    preflight.add_argument("--email", required=True)
    preflight.add_argument("--synthetic-page-id", required=True)
    preflight.add_argument("--default-calendar-id", required=True)
    activate = commands.add_parser("activate", help="Revalidate preflights and activate")
    activate.add_argument("--email", required=True)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
