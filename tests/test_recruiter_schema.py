from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.services.canary import notion_schema_hash, notion_token_hash, require_notion_preflight
from app.services.destinations import DestinationRejectedError, DestinationService
from app.services.matching import (
    BOOKING_PATTERN,
    DEFAULT_MATCHING_SIGNALS,
    INTERVIEW_PATTERN,
    NAME_PATTERN,
)
from app.services.notion_reassignment import (
    NotionReassignmentRejectedError,
    NotionReassignmentService,
)
from app.services.recruiter_schema import (
    NotionPropertyMap,
    default_notion_property_map,
    merge_matching_signals,
    merge_notion_property_map,
    reject_dangerous_regex,
    resolve_matching_signals,
    resolve_notion_property_map,
    resolve_synology_roots,
)

LILIA_MAP: dict[str, object] = {
    "project_prop": "Vacancy",
    "project_prop_type": "relation",
    "contacts_mode": "none",
}


def _recruiter(
    email: str = "r@example.com",
    notion_property_map: dict[str, object] | None = None,
    synology_interview_roots: list[str] | None = None,
    matching_signals: dict[str, object] | None = None,
) -> RecruiterConfig:
    return RecruiterConfig(
        email=email,
        notion_database_id="db",
        synology_base_folder="test",
        notion_property_map=notion_property_map,
        synology_interview_roots=synology_interview_roots,
        matching_signals=matching_signals,
    )


def test_null_map_resolves_to_global_settings() -> None:
    settings = Settings()
    resolved = resolve_notion_property_map(settings, _recruiter())

    assert resolved == NotionPropertyMap(
        name_prop=settings.notion_name_prop,
        date_prop=settings.notion_date_prop,
        recording_prop=settings.notion_recording_prop,
        project_prop=settings.notion_project_prop,
        project_prop_type=settings.notion_project_prop_type,
        contacts_mode="formula",
        contacts_prop=settings.notion_contacts_prop,
    )
    assert resolve_notion_property_map(settings, None) == resolved
    assert resolve_notion_property_map(settings, _recruiter(notion_property_map={})) == resolved


def test_partial_map_overrides_only_given_keys() -> None:
    settings = Settings()
    resolved = resolve_notion_property_map(settings, _recruiter(notion_property_map=LILIA_MAP))

    assert resolved.project_prop == "Vacancy"
    assert resolved.project_prop_type == "relation"
    assert resolved.contacts_mode == "none"
    assert resolved.name_prop == settings.notion_name_prop
    assert resolved.date_prop == settings.notion_date_prop
    assert resolved.recording_prop == settings.notion_recording_prop
    assert resolved.contacts_prop == settings.notion_contacts_prop


@pytest.mark.parametrize(
    "overrides",
    [
        {"contacts_mode": "rollup"},
        {"project_prop_type": "select"},
        {"unknown_key": "x"},
        {"name_prop": ""},
        {"contacts_mode": "relation", "contacts_relation_prop": "Candidate"},
    ],
)
def test_invalid_map_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        merge_notion_property_map(Settings(), overrides)


def test_relation_contacts_map_is_valid() -> None:
    resolved = merge_notion_property_map(
        Settings(),
        {
            "contacts_mode": "relation",
            "contacts_relation_prop": "Candidate",
            "contacts_target_prop": "Contacts",
        },
    )
    assert resolved.contacts_relation_prop == "Candidate"
    assert resolved.contacts_target_prop == "Contacts"


def test_synology_roots_null_inherits_global_and_override_is_normalized() -> None:
    settings = Settings(synology_interview_roots=("/home/Recruiting-E/2. Interviews external",))

    assert resolve_synology_roots(settings, _recruiter()) == settings.synology_interview_roots
    assert resolve_synology_roots(settings, _recruiter(synology_interview_roots=[])) == (
        settings.synology_interview_roots
    )
    assert resolve_synology_roots(settings, None) == settings.synology_interview_roots
    assert resolve_synology_roots(
        settings,
        _recruiter(
            synology_interview_roots=[
                "/Recruiting-NE/2. Interviews/",
                "/Recruiting-NE/2. Interviews",
            ]
        ),
    ) == ("/Recruiting-NE/2. Interviews",)
    with pytest.raises(ValueError, match="absolute"):
        resolve_synology_roots(settings, _recruiter(synology_interview_roots=["relative"]))


def test_default_map_hash_matches_legacy_payload() -> None:
    import hashlib
    import json

    settings = Settings()
    # Equivalence holds only while the global project type is "relation" (legacy hardcoded it).
    assert settings.notion_project_prop_type == "relation"
    legacy = {
        settings.notion_name_prop: "title",
        settings.notion_date_prop: "date",
        settings.notion_recording_prop: "files",
        settings.notion_contacts_prop: "formula",
        settings.notion_project_prop: "relation",
    }
    expected = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert notion_schema_hash(default_notion_property_map(settings)) == expected


def test_schema_hash_differs_by_project_type_and_contacts_mode() -> None:
    settings = Settings()
    base = default_notion_property_map(settings)
    hashes = {
        notion_schema_hash(base),
        notion_schema_hash(merge_notion_property_map(settings, {"project_prop_type": "rich_text"})),
        notion_schema_hash(merge_notion_property_map(settings, {"contacts_mode": "none"})),
        notion_schema_hash(
            merge_notion_property_map(
                settings,
                {
                    "contacts_mode": "relation",
                    "contacts_relation_prop": "Candidate",
                    "contacts_target_prop": "Contacts",
                },
            )
        ),
        notion_schema_hash(
            merge_notion_property_map(
                settings,
                {
                    "contacts_mode": "relation",
                    "contacts_relation_prop": "Candidate",
                    "contacts_target_prop": "Email",
                },
            )
        ),
    }
    assert len(hashes) == 5


def _preflighted(settings: Settings, recruiter: RecruiterConfig) -> RecruiterConfig:
    recruiter.notion_preflight_token_hash = notion_token_hash(settings)
    recruiter.notion_preflight_database_id = recruiter.notion_database_id
    recruiter.notion_preflight_schema_hash = notion_schema_hash(
        resolve_notion_property_map(settings, recruiter)
    )
    recruiter.notion_preflight_synthetic_page_id = "page"
    recruiter.notion_preflight_completed_at = datetime.now(UTC)
    return recruiter


def test_preflight_hashes_are_isolated_between_recruiters() -> None:
    settings = Settings(notion_writes_enabled=True, notion_token=SecretStr("backend-token"))
    anton = _preflighted(settings, _recruiter("anton@example.com"))
    lilia = _preflighted(settings, _recruiter("lilia@example.com", notion_property_map=LILIA_MAP))

    require_notion_preflight(settings, anton)
    require_notion_preflight(settings, lilia)
    assert anton.notion_preflight_schema_hash != lilia.notion_preflight_schema_hash

    # Lilia's schema changes: only her preflight becomes stale.
    lilia.notion_property_map = {**LILIA_MAP, "project_prop": "Position"}
    with pytest.raises(PermissionError, match="Backend-token"):
        require_notion_preflight(settings, lilia)
    require_notion_preflight(settings, anton)


@pytest.mark.parametrize(
    "raw", ["/Recruiting-NE/2. Interviews", '["/Recruiting-NE/2. Interviews"]', {"a": "/x"}]
)
def test_non_list_synology_roots_are_rejected_not_split(raw: object) -> None:
    settings = Settings(synology_interview_roots=("/home/Recruiting-E/2. Interviews external",))
    recruiter = _recruiter()
    recruiter.synology_interview_roots = raw  # type: ignore[assignment]

    with pytest.raises(ValueError, match="must be a JSON array"):
        resolve_synology_roots(settings, recruiter)


@pytest.mark.anyio
@pytest.mark.parametrize("raw", ["/Recruiting-NE/2. Interviews", ["relative"]])
async def test_destination_service_maps_bad_recruiter_roots_to_rejection(raw: object) -> None:
    settings = Settings(synology_interview_roots=("/home/Recruiting-E/2. Interviews external",))
    recruiter = _recruiter()
    recruiter.synology_interview_roots = raw  # type: ignore[assignment]
    synology = AsyncMock()
    service = DestinationService(synology, settings)

    with pytest.raises(DestinationRejectedError, match="interview roots are invalid"):
        await service.preflight(recruiter)
    synology.preflight.assert_not_awaited()


@pytest.mark.parametrize(
    "raw",
    [{"contacts_mode": "rollup"}, {"unknown_key": "x"}, ["Vacancy"], "Vacancy"],
)
def test_malformed_stored_map_is_recruiter_misconfiguration(raw: object) -> None:
    settings = Settings(notion_writes_enabled=True, notion_token=SecretStr("backend-token"))
    recruiter = _preflighted(settings, _recruiter())
    recruiter.notion_property_map = raw  # type: ignore[assignment]

    with pytest.raises(PermissionError, match="notion_property_map"):
        resolve_notion_property_map(settings, recruiter)
    # Preflight callers already catch PermissionError (cron marks notion_preflight failed).
    with pytest.raises(PermissionError, match="notion_property_map"):
        require_notion_preflight(settings, recruiter)


@pytest.mark.anyio
async def test_reassignment_maps_malformed_map_to_typed_rejection() -> None:
    recruiter = _recruiter(notion_property_map={"contacts_mode": "rollup"})
    notion = AsyncMock()
    service = NotionReassignmentService(notion, Settings())

    with pytest.raises(NotionReassignmentRejectedError, match="notion_property_map is invalid"):
        await service.resolve_targets(recruiter, "hint")
    notion.resolve_reassignment_targets.assert_not_awaited()


def test_null_matching_signals_resolves_to_todays_compiled_defaults() -> None:
    resolved = resolve_matching_signals(_recruiter())

    assert resolved is DEFAULT_MATCHING_SIGNALS
    assert resolved.name_pattern.pattern == NAME_PATTERN.pattern
    assert resolved.interview_pattern.pattern == INTERVIEW_PATTERN.pattern
    assert resolved.interview_pattern.flags == INTERVIEW_PATTERN.flags
    assert resolved.booking_pattern.pattern == BOOKING_PATTERN.pattern
    assert resolved.booking_pattern.flags == BOOKING_PATTERN.flags
    assert resolve_matching_signals(None) is resolved
    assert resolve_matching_signals(_recruiter(matching_signals={})) is resolved


def test_partial_matching_signals_overrides_only_given_field() -> None:
    resolved = resolve_matching_signals(
        _recruiter(matching_signals={"booking_pattern": r"https://custom-booking\.example/"})
    )

    assert resolved.booking_pattern.pattern == r"https://custom-booking\.example/"
    assert resolved.name_pattern.pattern == NAME_PATTERN.pattern
    assert resolved.interview_pattern.pattern == INTERVIEW_PATTERN.pattern


@pytest.mark.parametrize(
    "pattern", ["(a+)+", "(a*)*", "([a-zA-Z]+)*", "(a|a)*", "(a|aa)*", "(a|a)+"]
)
def test_reject_dangerous_regex_rejects_classic_catastrophic_backtracking_shapes(
    pattern: str,
) -> None:
    with pytest.raises(ValueError, match="catastrophic backtracking"):
        reject_dangerous_regex(pattern)


@pytest.mark.parametrize(
    "pattern", [r"собеседован|интервью", r"(?i)calink\.ru", r"(abc)+", r"[a-z]+", r"(ab)+c"]
)
def test_reject_dangerous_regex_accepts_benign_patterns(pattern: str) -> None:
    assert reject_dangerous_regex(pattern) == pattern


@pytest.mark.parametrize(
    "overrides",
    [
        {"name_pattern": "("},
        {"booking_pattern": "(a+)+"},
        {"interview_pattern": "(a*)*"},
        {"name_pattern": "([a-zA-Z]+)*"},
        {"unknown_key": "x"},
    ],
)
def test_invalid_or_dangerous_matching_signals_are_rejected_at_write_time(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        merge_matching_signals(overrides)


@pytest.mark.parametrize("overrides", [{"name_pattern": "("}, {"booking_pattern": "(a+)+"}])
def test_invalid_or_dangerous_matching_signals_are_rejected_at_read_time(
    overrides: dict[str, object],
) -> None:
    recruiter = _recruiter(matching_signals=overrides)

    with pytest.raises(PermissionError, match="matching_signals"):
        resolve_matching_signals(recruiter)


@pytest.mark.parametrize("raw", [["x"], "pattern", 5])
def test_non_dict_matching_signals_is_recruiter_misconfiguration(raw: object) -> None:
    recruiter = _recruiter()
    recruiter.matching_signals = raw  # type: ignore[assignment]

    with pytest.raises(PermissionError, match="matching_signals"):
        resolve_matching_signals(recruiter)
