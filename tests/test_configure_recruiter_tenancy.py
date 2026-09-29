"""configure_recruiter CLI: per-recruiter Notion map and Synology roots round-trip."""

from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import notion_schema_hash
from app.services.recruiter_schema import resolve_notion_property_map
from app.tools.notion import NotionClient, NotionDatabaseInspection, NotionDataSourceSchema
from tools.setup.configure_recruiter import (
    DatabaseInspection,
    build_parser,
    configure_recruiter,
    notion_overrides_from_args,
    preflight_recruiter_notion,
    synology_roots_from_args,
)

DATABASE_ID = "00000000-0000-0000-0000-000000000001"
BASE_ARGS = [
    "configure",
    "--email",
    "Lilia@example.com",
    "--notion",
    DATABASE_ID,
    "--mattermost-user-id",
    "mm-user",
    "--mattermost-dm-channel",
    "dm-channel",
    "--timezone",
    "Asia/Omsk",
    "--storage-prefix",
    "test-prefix",
]
LILIA_FLAGS = [
    "--notion-project-prop",
    "Vacancy",
    "--notion-project-prop-type",
    "relation",
    "--notion-contacts-mode",
    "none",
    "--synology-roots",
    "/Recruiting-NE/2. Interviews/",
]


def _settings() -> Settings:
    return Settings(
        notion_token=SecretStr("backend-token"),
        yandex_refresh_tokens={"lilia@example.com": SecretStr("refresh")},
        yandex_caldav_passwords={"lilia@example.com": SecretStr("password")},
    )


async def _configure(session: AsyncSession, argv: list[str]) -> tuple[RecruiterConfig, AsyncMock]:
    args = build_parser().parse_args(argv)
    inspector = AsyncMock()
    inspector.inspect.return_value = DatabaseInspection(DATABASE_ID, "Interviews", {})
    recruiter = await configure_recruiter(
        session,
        inspector,
        _settings(),
        email=args.email,
        notion_target=args.notion,
        mattermost_user_id=args.mattermost_user_id,
        mattermost_dm_channel=args.mattermost_dm_channel,
        storage_prefix=args.storage_prefix,
        timezone_name=args.timezone,
        confirmed=True,
        notion_property_map=notion_overrides_from_args(args),
        synology_interview_roots=synology_roots_from_args(args),
    )
    return recruiter, inspector


@pytest.mark.anyio
async def test_cli_flags_round_trip_into_inactive_recruiter_columns(
    session: AsyncSession,
) -> None:
    recruiter, inspector = await _configure(session, BASE_ARGS + LILIA_FLAGS)

    assert recruiter.active is False
    assert recruiter.notion_property_map == {
        "project_prop": "Vacancy",
        "project_prop_type": "relation",
        "contacts_mode": "none",
    }
    assert recruiter.synology_interview_roots == ["/Recruiting-NE/2. Interviews"]
    inspected_map = inspector.inspect.await_args.args[1]
    assert inspected_map.project_prop == "Vacancy"
    assert inspected_map.contacts_mode == "none"
    assert inspected_map.name_prop == Settings().notion_name_prop


@pytest.mark.anyio
async def test_cli_without_flags_leaves_columns_null(session: AsyncSession) -> None:
    recruiter, _ = await _configure(session, BASE_ARGS)

    assert recruiter.notion_property_map is None
    assert recruiter.synology_interview_roots is None


def test_cli_rejects_unknown_contacts_mode() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([*BASE_ARGS, "--notion-contacts-mode", "rollup"])


@pytest.mark.anyio
async def test_cli_rejects_incomplete_relation_contacts_before_inspection(
    session: AsyncSession,
) -> None:
    with pytest.raises(ValidationError):
        await _configure(
            session,
            [
                *BASE_ARGS,
                "--notion-contacts-mode",
                "relation",
                "--notion-contacts-relation-prop",
                "C",
            ],
        )


@pytest.mark.anyio
async def test_cli_rejects_relative_synology_root(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="absolute"):
        await _configure(session, [*BASE_ARGS, "--synology-roots", "Recruiting-NE"])


@pytest.mark.anyio
async def test_notion_preflight_uses_and_hashes_recruiter_map(session: AsyncSession) -> None:
    recruiter, _ = await _configure(session, BASE_ARGS + LILIA_FLAGS)
    notion = AsyncMock(spec=NotionClient)
    notion.preflight_database.return_value = NotionDatabaseInspection(
        DATABASE_ID, "Interviews", NotionDataSourceSchema("source", {})
    )
    settings = _settings()

    await preflight_recruiter_notion(
        session,
        notion,
        settings,
        recruiter_email=recruiter.email,
        synthetic_page_id="synthetic-page",
    )

    args = notion.preflight_database.await_args.args
    assert args[5:7] == ("Vacancy", "relation")
    assert args[8] == "none"
    resolved = resolve_notion_property_map(settings, recruiter)
    assert recruiter.notion_preflight_schema_hash == notion_schema_hash(resolved)
