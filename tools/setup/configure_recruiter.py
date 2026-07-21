from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import create_engine, create_session_factory
from app.db.models.recruiter_config import RecruiterConfig
from app.tools.notion import NotionClient


@dataclass(frozen=True)
class DatabaseInspection:
    database_id: str
    title: str
    property_types: dict[str, str]


class DatabaseInspector(Protocol):
    async def inspect(self, database_id: str) -> DatabaseInspection: ...


class NotionInspector:
    def __init__(self, notion: NotionClient, settings: Settings) -> None:
        self._notion = notion
        self._settings = settings

    async def inspect(self, database_id: str) -> DatabaseInspection:
        source_id, _ = await self._notion._resolve_source(  # noqa: SLF001
            (
                database_id,
                self._settings.notion_name_prop,
                self._settings.notion_date_prop,
                self._settings.notion_recording_prop,
                self._settings.notion_project_prop,
            )
        )
        schema = await self._notion._retrieve_schema(source_id)  # noqa: SLF001
        return DatabaseInspection(
            database_id=database_id,
            title="explicit Notion database",
            property_types=schema.property_types,
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
    inspection = await inspector.inspect(database_id)
    print(f"Database: {inspection.title} ({inspection.database_id})")
    print(
        "Schema: " + ", ".join(f"{name}:{kind}" for name, kind in inspection.property_types.items())
    )
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


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with httpx.AsyncClient(timeout=30) as client:
        inspector = NotionInspector(
            NotionClient(settings.notion_token, client, settings=settings), settings
        )
        try:
            async with factory() as session:
                database_id = parse_notion_database_id(args.notion)
                inspection = await inspector.inspect(database_id)
                print(f"Database: {inspection.title} ({inspection.database_id})")
                print(
                    "Schema: "
                    + ", ".join(
                        f"{name}:{kind}" for name, kind in inspection.property_types.items()
                    )
                )
                confirmed = input("Create inactive recruiter config? [yes/no] ").strip() == "yes"
                await configure_recruiter(
                    session,
                    inspector,
                    settings,
                    email=args.email,
                    notion_target=args.notion,
                    mattermost_user_id=args.mattermost_user_id,
                    storage_prefix=args.storage_prefix,
                    confirmed=confirmed,
                )
        finally:
            await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create inactive recruiter configuration")
    parser.add_argument("--email", required=True)
    parser.add_argument("--notion", required=True, help="Explicit Notion database URL or ID")
    parser.add_argument("--mattermost-user-id", required=True)
    parser.add_argument("--storage-prefix", required=True)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
