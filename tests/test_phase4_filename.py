from datetime import date

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.filename import FilenameError, build_storage_identity


def test_filename_and_key_are_deterministic() -> None:
    identity = build_storage_identity(
        event_date=date(2026, 7, 21),
        candidate_name="  Иван / Иванов ",
        project_or_spot="Spot: A",
        interview_type="general_interview",
        original_filename="CALL.WEBM",
        recruiter_prefix="recruiter@example.com",
    )
    assert identity.filename == "2026-07-21_Иван___Иванов_Spot__A_general_interview.webm"
    assert identity.key.endswith("/Иван___Иванов/" + identity.filename)


def test_filename_rejects_empty_component_and_extension() -> None:
    with pytest.raises(FilenameError):
        build_storage_identity(
            event_date=date(2026, 7, 21),
            candidate_name="...",
            project_or_spot="Spot",
            interview_type="general_interview",
            original_filename="call.exe",
            recruiter_prefix="recruiter",
        )


def test_test_mode_fails_closed() -> None:
    with pytest.raises(ValidationError, match="Yandex source mutation"):
        Settings(test_mode_enabled=True)
    settings = Settings(
        test_mode_enabled=True,
        scheduler_enabled=False,
        yandex_source_mutation_enabled=False,
        notion_writes_enabled=False,
        test_recruiter_allowlist={"r@example.com"},
        test_notion_database_allowlist={"db"},
        test_mattermost_user_allowlist={"user"},
    )
    assert settings.storage_provider == "minio"
