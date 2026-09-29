"""Per-recruiter Notion property map and Synology interview roots.

Each recruiter row may override the global `Settings.notion_*` property names and
`Settings.synology_interview_roots`. A NULL column means "inherit the global value"; a partial
Notion map overrides only the keys it sets (per-field fallback).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig

ContactsMode = Literal["none", "formula", "relation"]
ProjectPropType = Literal["rich_text", "relation"]


class NotionPropertyMap(BaseModel):
    """Fully resolved Notion schema for one recruiter's Interviews database."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name_prop: str = Field(min_length=1)
    date_prop: str = Field(min_length=1)
    recording_prop: str = Field(min_length=1)
    project_prop: str
    project_prop_type: ProjectPropType
    contacts_mode: ContactsMode = "formula"
    contacts_prop: str = ""
    contacts_relation_prop: str = ""
    contacts_target_prop: str = ""

    @model_validator(mode="after")
    def validate_contacts(self) -> NotionPropertyMap:
        if self.contacts_mode == "formula" and not self.contacts_prop:
            raise ValueError("contacts_mode=formula requires contacts_prop")
        if self.contacts_mode == "relation" and not (
            self.contacts_relation_prop and self.contacts_target_prop
        ):
            raise ValueError(
                "contacts_mode=relation requires contacts_relation_prop and contacts_target_prop"
            )
        return self


class NotionPropertyOverrides(BaseModel):
    """Shape of `recruiter_config.notion_property_map`: any subset of NotionPropertyMap keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name_prop: str | None = Field(default=None, min_length=1)
    date_prop: str | None = Field(default=None, min_length=1)
    recording_prop: str | None = Field(default=None, min_length=1)
    project_prop: str | None = None
    project_prop_type: ProjectPropType | None = None
    contacts_mode: ContactsMode | None = None
    contacts_prop: str | None = None
    contacts_relation_prop: str | None = None
    contacts_target_prop: str | None = None


def default_notion_property_map(settings: Settings) -> NotionPropertyMap:
    """The global map a recruiter with a NULL `notion_property_map` resolves to."""
    return NotionPropertyMap(
        name_prop=settings.notion_name_prop,
        date_prop=settings.notion_date_prop,
        recording_prop=settings.notion_recording_prop,
        project_prop=settings.notion_project_prop,
        project_prop_type=settings.notion_project_prop_type,
        contacts_mode="formula",
        contacts_prop=settings.notion_contacts_prop,
    )


def merge_notion_property_map(
    settings: Settings, overrides: dict[str, Any] | None
) -> NotionPropertyMap:
    """Validate `overrides` and merge them key-by-key over the global defaults."""
    defaults = default_notion_property_map(settings)
    if not overrides:
        return defaults
    parsed = NotionPropertyOverrides.model_validate(overrides)
    merged = defaults.model_dump() | parsed.model_dump(exclude_none=True)
    return NotionPropertyMap.model_validate(merged)


def resolve_notion_property_map(
    settings: Settings, recruiter: RecruiterConfig | None
) -> NotionPropertyMap:
    """Recruiter-specific Notion map; NULL column (or no recruiter) means global defaults.

    A malformed stored map is recruiter misconfiguration: it raises PermissionError, the type
    callers already handle for recruiter scope/preflight failures.
    """
    raw = recruiter.notion_property_map if recruiter is not None else None
    if raw is not None and not isinstance(raw, dict):
        raise PermissionError("Recruiter notion_property_map must be a JSON object")
    try:
        return merge_notion_property_map(settings, raw)
    except ValidationError as error:
        raise PermissionError("Recruiter notion_property_map is invalid") from error


def normalize_synology_roots(value: Any) -> tuple[str, ...]:
    """Same JSON-or-CSV parsing and absolute/rstrip/dedupe rules as `Settings`."""
    parsed = Settings.parse_synology_interview_roots(value)
    return Settings.validate_synology_interview_roots(tuple(parsed))


def resolve_synology_roots(
    settings: Settings | None, recruiter: RecruiterConfig | None
) -> tuple[str, ...]:
    """Recruiter roots when set and non-empty, otherwise `Settings.synology_interview_roots`."""
    raw = recruiter.synology_interview_roots if recruiter is not None else None
    if raw is not None and not isinstance(raw, list):
        # tuple() of a str/dict would split it into characters/keys.
        raise ValueError("Recruiter synology_interview_roots must be a JSON array")
    if raw:
        return normalize_synology_roots(tuple(raw))
    return settings.synology_interview_roots if settings is not None else ()
