"""Read-only Notion schema preflight for the isolated canary."""

import argparse
import asyncio
from collections.abc import Sequence

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.tools.notion import NotionClient, NotionDatabaseInspection, build_notion_http_client


def _require_canary_boundary(settings: Settings, database_id: str) -> None:
    """Reject an invocation that could inspect a non-canary database or enable effects."""
    if not settings.test_mode_enabled:
        raise ValueError("Notion schema preflight requires TEST_MODE_ENABLED=true")
    if database_id not in settings.test_notion_database_allowlist:
        raise ValueError("Notion database is not in TEST_NOTION_DATABASE_ALLOWLIST")
    if any(
        (
            settings.scheduler_enabled,
            settings.autonomous_routing_enabled,
            settings.notion_writes_enabled,
            settings.mattermost_delivery_enabled,
            settings.yandex_source_mutation_enabled,
        )
    ):
        raise ValueError("Notion schema preflight requires all side-effect flags to be disabled")


async def inspect_canary_notion_schema(
    settings: Settings, database_id: str
) -> NotionDatabaseInspection:
    """Inspect exactly one allowlisted Notion schema using the dedicated proxy client."""
    _require_canary_boundary(settings, database_id)
    async with build_notion_http_client(
        settings, httpx.Timeout(connect=10, read=30, write=30, pool=10)
    ) as http_client:
        notion = NotionClient(settings.notion_token, http_client, settings=settings)
        return await notion.inspect_database(
            database_id,
            settings.notion_name_prop,
            settings.notion_date_prop,
            settings.notion_recording_prop,
            settings.notion_project_prop,
            settings.notion_project_prop_type,
            settings.notion_contacts_prop,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only canary Notion schema preflight")
    parser.add_argument("--database-id", required=True)
    return parser


async def _run(database_id: str) -> NotionDatabaseInspection:
    return await inspect_canary_notion_schema(get_settings(), database_id)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        inspection = asyncio.run(_run(args.database_id))
    except (ValidationError, ValueError, httpx.HTTPError, RuntimeError) as error:
        raise SystemExit(f"Notion schema preflight failed: {error}") from None
    print(f"Notion schema verified for database {inspection.database_id}")


if __name__ == "__main__":
    main()
