"""Per-recruiter Notion property map, Synology interview roots, and matching signals.

Each recruiter row may override the global `Settings.notion_*` property names,
`Settings.synology_interview_roots`, and the `app.services.matching` regex signals. A NULL
column means "inherit the global value"; a partial map overrides only the keys it sets
(per-field fallback).

`resolve_matching_signals` deliberately deviates from the `resolve_notion_property_map`/
`resolve_synology_roots` precedent by taking no `settings` argument: its defaults live in
`app.services.matching` module constants (`DEFAULT_MATCHING_SIGNALS`), not a `Settings` field.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.services.matching import DEFAULT_MATCHING_SIGNALS, MatchingSignals

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


# A parenthesized group that itself contains an unescaped '+'/'*' quantifier, immediately
# followed by another '+'/'*'/'{...}' quantifier — the classic catastrophic-backtracking shape
# (e.g. "(a+)+", "(a*)*", "([a-zA-Z]+)*"). Flat (non-nested) groups only; this is a heuristic,
# not an exhaustive ReDoS detector, proportionate to the threat model (an authenticated
# operator's CLI typo, not adversarial input).
_NESTED_QUANTIFIER_RE = re.compile(r"\(([^()]*)\)(?:[+*]|\{\d+(?:,\d*)?\})")
_UNESCAPED_QUANTIFIER_RE = re.compile(r"(?<!\\)[+*]")


def reject_dangerous_regex(value: str) -> str:
    """Validate regex syntax and reject classic catastrophic-backtracking shapes.

    This is the single validation choke point: both the `set-matching-signals` CLI write path
    (via `merge_matching_signals`/`MatchingSignalsOverrides`) and every `resolve_matching_signals`
    read go through it, so a pattern that somehow reached the DB via a raw edit is still caught at
    resolve time, not silently accepted.
    """
    try:
        re.compile(value)
    except re.error as error:
        raise ValueError(f"Invalid regular expression {value!r}: {error}") from error
    for match in _NESTED_QUANTIFIER_RE.finditer(value):
        if _UNESCAPED_QUANTIFIER_RE.search(match.group(1)):
            raise ValueError(
                f"Regular expression {value!r} rejected: a group containing its own '+'/'*' "
                "quantifier followed by another quantifier risks catastrophic backtracking "
                "(e.g. '(a+)+')"
            )
    return value


class MatchingSignalsOverrides(BaseModel):
    """Shape of `recruiter_config.matching_signals`: any subset of MatchingSignals keys.

    Values are regex source strings, not compiled patterns. Unlike the global
    `INTERVIEW_PATTERN`/`BOOKING_PATTERN` constants, an override is compiled with no implicit
    flags — an override that doesn't embed `(?i)` loses case-insensitivity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name_pattern: str | None = None
    interview_pattern: str | None = None
    booking_pattern: str | None = None

    @field_validator("name_pattern", "interview_pattern", "booking_pattern")
    @classmethod
    def validate_safe_regex(cls, value: str | None) -> str | None:
        return reject_dangerous_regex(value) if value is not None else value


def merge_matching_signals(overrides: dict[str, Any] | None) -> MatchingSignals:
    """Validate `overrides` and merge them key-by-key over `DEFAULT_MATCHING_SIGNALS`."""
    if not overrides:
        return DEFAULT_MATCHING_SIGNALS
    parsed = MatchingSignalsOverrides.model_validate(overrides)
    return MatchingSignals(
        name_pattern=(
            re.compile(parsed.name_pattern)
            if parsed.name_pattern is not None
            else DEFAULT_MATCHING_SIGNALS.name_pattern
        ),
        interview_pattern=(
            re.compile(parsed.interview_pattern)
            if parsed.interview_pattern is not None
            else DEFAULT_MATCHING_SIGNALS.interview_pattern
        ),
        booking_pattern=(
            re.compile(parsed.booking_pattern)
            if parsed.booking_pattern is not None
            else DEFAULT_MATCHING_SIGNALS.booking_pattern
        ),
    )


def resolve_matching_signals(recruiter: RecruiterConfig | None) -> MatchingSignals:
    """Recruiter-specific matching signals; NULL column (or no recruiter) means global defaults.

    A malformed stored value is recruiter misconfiguration: it raises PermissionError, the type
    callers already handle for recruiter scope/preflight failures (see
    `resolve_notion_property_map`). Unlike that function, this takes no `settings` argument —
    defaults live in `app.services.matching` module constants, not a `Settings` field.
    """
    raw = recruiter.matching_signals if recruiter is not None else None
    if raw is not None and not isinstance(raw, dict):
        raise PermissionError("Recruiter matching_signals must be a JSON object")
    try:
        return merge_matching_signals(raw)
    except ValidationError as error:
        raise PermissionError("Recruiter matching_signals is invalid") from error


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
