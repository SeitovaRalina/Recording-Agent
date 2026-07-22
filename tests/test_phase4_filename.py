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


def test_canary_key_keeps_logical_suffix_under_test_prefix() -> None:
    identity = build_storage_identity(
        event_date=date(2026, 7, 21),
        candidate_name="Candidate",
        project_or_spot="Spot",
        interview_type="general_interview",
        original_filename="call.webm",
        recruiter_prefix="r@example.com",
        key_prefix="test-interviews",
    )
    assert identity.key == (
        "test-interviews/r@example.com/2026-07-21/Candidate/"
        "2026-07-21_Candidate_Spot_general_interview.webm"
    )


@pytest.mark.parametrize("project_or_spot", [None, "", " \t\n\u2003"])
def test_blank_project_uses_unspecified(project_or_spot: str | None) -> None:
    identity = build_storage_identity(
        event_date=date(2026, 7, 21),
        candidate_name="Candidate",
        project_or_spot=project_or_spot,
        interview_type="general_interview",
        original_filename="call.webm",
        recruiter_prefix="r@example.com",
        key_prefix="test-interviews",
    )

    assert identity.filename == ("2026-07-21_Candidate_unspecified_general_interview.webm")
    assert identity.key == (
        "test-interviews/r@example.com/2026-07-21/Candidate/"
        "2026-07-21_Candidate_unspecified_general_interview.webm"
    )


def test_nonblank_project_behavior_is_unchanged() -> None:
    identity = build_storage_identity(
        event_date=date(2026, 7, 21),
        candidate_name="Candidate",
        project_or_spot=" Spot: A ",
        interview_type="general_interview",
        original_filename="call.webm",
        recruiter_prefix="r@example.com",
    )

    assert identity.filename == "2026-07-21_Candidate_Spot__A_general_interview.webm"


@pytest.mark.parametrize("project_or_spot", ["...", "|<>?"])
def test_nonblank_project_that_sanitizes_empty_is_rejected(project_or_spot: str) -> None:
    with pytest.raises(FilenameError, match="empty after sanitization"):
        build_storage_identity(
            event_date=date(2026, 7, 21),
            candidate_name="Candidate",
            project_or_spot=project_or_spot,
            interview_type="general_interview",
            original_filename="call.webm",
            recruiter_prefix="r@example.com",
        )


def test_literal_unspecified_project_keeps_marker_text() -> None:
    identity = build_storage_identity(
        event_date=date(2026, 7, 21),
        candidate_name="Candidate",
        project_or_spot="unspecified",
        interview_type="general_interview",
        original_filename="call.webm",
        recruiter_prefix="r@example.com",
    )

    assert identity.filename == "2026-07-21_Candidate_unspecified_general_interview.webm"


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
