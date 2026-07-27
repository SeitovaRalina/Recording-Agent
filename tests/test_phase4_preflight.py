from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import (
    enforce_recruiter_scope,
    notion_schema_hash,
    notion_token_hash,
    require_notion_preflight,
)


def test_notion_write_flag_does_not_bypass_durable_preflight() -> None:
    settings = Settings(notion_writes_enabled=True, notion_token=SecretStr("backend-token"))
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="db",
        synology_base_folder="test",
    )
    with pytest.raises(PermissionError, match="Backend-token"):
        require_notion_preflight(settings, recruiter)

    recruiter.notion_preflight_token_hash = notion_token_hash(settings)
    recruiter.notion_preflight_database_id = "db"
    recruiter.notion_preflight_schema_hash = notion_schema_hash(settings)
    recruiter.notion_preflight_synthetic_page_id = "page"
    recruiter.notion_preflight_completed_at = datetime.now(UTC)
    require_notion_preflight(settings, recruiter)

    changed_token = Settings(notion_writes_enabled=True, notion_token=SecretStr("other-token"))
    with pytest.raises(PermissionError, match="Backend-token"):
        require_notion_preflight(changed_token, recruiter)


def test_canary_scope_normalizes_notion_database_uuid() -> None:
    recruiter = RecruiterConfig(
        email="r@example.com",
        notion_database_id="00000000-0000-0000-0000-000000000001",
        synology_base_folder="test-interviews",
        mattermost_user_id="codex-user",
        active=True,
    )
    settings = Settings(
        test_mode_enabled=True,
        yandex_source_mutation_enabled=False,
        mattermost_delivery_enabled=False,
        test_recruiter_allowlist={recruiter.email},
        test_notion_database_allowlist={"00000000000000000000000000000001"},
        test_mattermost_user_allowlist={recruiter.mattermost_user_id},
        minio_test_prefix=recruiter.synology_base_folder,
    )

    enforce_recruiter_scope(settings, recruiter)
