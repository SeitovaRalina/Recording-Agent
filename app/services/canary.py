from __future__ import annotations

import hashlib
import json

from app.config import Settings
from app.db.models.recruiter_config import RecruiterConfig
from app.services.recruiter_schema import NotionPropertyMap, resolve_notion_property_map


def enforce_recruiter_scope(settings: Settings, recruiter: RecruiterConfig) -> None:
    if not settings.test_mode_enabled:
        return
    if not recruiter.active:
        raise PermissionError("Recruiter is inactive")
    if recruiter.email not in settings.test_recruiter_allowlist:
        raise PermissionError("Recruiter is outside the test-mode allowlist")
    notion_allowlist = {
        _normalize_notion_id(item) for item in settings.test_notion_database_allowlist
    }
    if _normalize_notion_id(recruiter.notion_database_id) not in notion_allowlist:
        raise PermissionError("Notion database is outside the test-mode allowlist")
    if not recruiter.mattermost_user_id or (
        recruiter.mattermost_user_id not in settings.test_mattermost_user_allowlist
    ):
        raise PermissionError("Mattermost user is outside the test-mode allowlist")
    configured_prefix = settings.minio_test_prefix.strip(" /")
    recruiter_prefix = recruiter.synology_base_folder.strip(" /")
    if recruiter_prefix != configured_prefix:
        raise PermissionError("Storage prefix is outside the test-mode allowlist")


def enforce_storage_key_scope(
    settings: Settings, recruiter: RecruiterConfig, storage_key: str
) -> None:
    if not settings.test_mode_enabled:
        return
    expected = recruiter.synology_base_folder.strip(" /") + "/"
    if not storage_key.startswith(expected):
        raise PermissionError("Storage key is outside the recruiter test prefix")


def notion_schema_hash(property_map: NotionPropertyMap) -> str:
    """Hash of one recruiter's resolved Notion schema.

    The global-default shape (formula contacts, relation project) produces exactly the legacy
    payload, so preflight hashes stored before per-recruiter maps stay valid. Any other
    project type or contacts mode adds its own entries, so changing it invalidates the preflight.
    """
    payload: dict[str, str] = {
        property_map.name_prop: "title",
        property_map.date_prop: "date",
        property_map.recording_prop: "files",
    }
    if property_map.contacts_mode == "formula":
        payload[property_map.contacts_prop] = "formula"
    else:
        payload["@contacts_mode"] = property_map.contacts_mode
        if property_map.contacts_mode == "relation":
            payload[property_map.contacts_relation_prop] = "relation"
            payload["@contacts_target_prop"] = property_map.contacts_target_prop
    # Legacy hardcoded "relation" here; the default map inherits NOTION_PROJECT_PROP_TYPE, which
    # is "relation" in prod, so the default shape still hashes to the legacy payload.
    payload[property_map.project_prop] = property_map.project_prop_type
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _normalize_notion_id(value: str) -> str:
    return value.replace("-", "").casefold()


def notion_token_hash(settings: Settings) -> str:
    return hashlib.sha256(settings.notion_token.get_secret_value().encode()).hexdigest()


def require_notion_preflight(settings: Settings, recruiter: RecruiterConfig) -> None:
    if not settings.notion_writes_enabled:
        raise PermissionError("Notion writes are disabled")
    valid = (
        recruiter.notion_preflight_completed_at is not None
        and recruiter.notion_preflight_database_id == recruiter.notion_database_id
        and recruiter.notion_preflight_token_hash == notion_token_hash(settings)
        and recruiter.notion_preflight_schema_hash
        == notion_schema_hash(resolve_notion_property_map(settings, recruiter))
        and bool(recruiter.notion_preflight_synthetic_page_id)
    )
    if not valid:
        raise PermissionError(
            "Notion writes require a current Backend-token schema and synthetic-row preflight"
        )
