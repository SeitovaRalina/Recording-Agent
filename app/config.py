import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_environment: Literal["development", "test", "production"] = "production"
    pipeline_trace_enabled: bool = False
    test_mode_enabled: bool = False
    scheduler_enabled: bool = False
    yandex_source_mutation_enabled: bool = False
    cleanup_preview_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    cleanup_preview_max_items: int = Field(default=50, ge=1, le=100)
    notion_writes_enabled: bool = False
    test_recruiter_allowlist: set[str] = Field(default_factory=set)
    test_notion_database_allowlist: set[str] = Field(default_factory=set)
    test_mattermost_user_allowlist: set[str] = Field(default_factory=set)

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@"  # pragma: allowlist secret
        "localhost:5432/recording_agent"
    )
    yandex_client_id: str = Field(
        default="", validation_alias=AliasChoices("yandex_client_id", "YANDEX_CLIENT_ID")
    )
    yandex_client_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("yandex_client_secret", "YANDEX_CLIENT_SECRET"),
    )
    yandex_refresh_tokens: dict[str, SecretStr] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("yandex_refresh_tokens", "YANDEX_REFRESH_TOKENS"),
    )
    caldav_base_url: str = Field(
        default="https://caldav.yandex.ru",
        validation_alias=AliasChoices("caldav_base_url", "CALDAV_BASE_URL"),
    )
    yandex_caldav_passwords: dict[str, SecretStr] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("yandex_caldav_passwords", "YANDEX_CALDAV_PASSWORDS"),
    )
    scan_hour: int = Field(default=2, validation_alias=AliasChoices("scan_hour", "SCAN_HOUR"))
    scan_minute: int = Field(default=0, validation_alias=AliasChoices("scan_minute", "SCAN_MINUTE"))
    scan_ignore_before_today: bool = Field(
        default=True,
        validation_alias=AliasChoices("scan_ignore_before_today", "SCAN_IGNORE_BEFORE_TODAY"),
    )
    scan_local_timezone: str = Field(
        default="Asia/Omsk",
        validation_alias=AliasChoices("scan_local_timezone", "SCAN_LOCAL_TIMEZONE"),
    )
    recording_filename_timezone: str = Field(
        default="Europe/Moscow",
        validation_alias=AliasChoices("recording_filename_timezone", "RECORDING_FILENAME_TIMEZONE"),
    )
    disk_cleanup_hour: int = 3
    disk_cleanup_minute: int = 0
    disk_retention_days: int = 7
    notion_token: SecretStr = SecretStr("")
    notion_name_prop: str = "Name"
    notion_date_prop: str = "General Interview Date"
    notion_recording_prop: str = "General Interview recording"
    notion_contacts_prop: str = "TBD"
    notion_project_prop: str = "📍 Spots"
    notion_project_prop_type: Literal["rich_text", "relation"] = "relation"
    notion_interview_type: str = "general_interview"
    synology_base_url: str = ""
    synology_api_key: SecretStr = SecretStr("")
    synology_user: str = ""
    synology_pass: SecretStr = SecretStr("")
    synology_device_id: SecretStr = SecretStr("")
    synology_interview_roots: tuple[str, ...] = Field(
        default_factory=tuple,
        validation_alias=AliasChoices(
            "synology_interview_roots", "SYNOLOGY_INTERVIEW_ROOTS"
        ),
    )
    mattermost_url: str = ""
    mattermost_bot_token: SecretStr = SecretStr("")
    mattermost_channel_id: str = ""
    mattermost_bot_user_id: str = ""
    mattermost_delivery_enabled: bool = False
    review_token_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    question_capability_ttl_seconds: int = Field(default=90000, ge=86400, le=172800)
    intent_claim_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_bucket: str = "recordings"
    minio_test_prefix: str = "test-interviews"
    storage_provider: Literal["minio", "synology"] = "minio"
    synology_discovery_max_depth: int = Field(default=3, ge=0, le=8)
    synology_discovery_max_pages: int = Field(default=10, ge=1, le=50)
    synology_discovery_max_results: int = Field(default=100, ge=1, le=500)
    openclaw_events_url: str = "http://localhost:8001/events"
    openclaw_secret: SecretStr = SecretStr("")
    confidence_threshold: float = Field(
        default=0.7,
        validation_alias=AliasChoices("confidence_threshold", "CONFIDENCE_THRESHOLD"),
    )

    @property
    def pipeline_trace_active(self) -> bool:
        return self.app_environment == "development" and self.pipeline_trace_enabled

    @model_validator(mode="after")
    def validate_canary_boundary(self) -> "Settings":
        if self.test_mode_enabled:
            if self.storage_provider != "minio":
                raise ValueError("Test mode requires MinIO storage")
            if self.yandex_source_mutation_enabled:
                raise ValueError("Yandex source mutation is forbidden in test mode")
            if not self.minio_test_prefix.strip(" /"):
                raise ValueError("Test mode requires a non-empty MinIO prefix")
        if self.storage_provider == "synology":
            if not self.synology_base_url.strip():
                raise ValueError("Synology storage requires SYNOLOGY_BASE_URL")
            has_api_key = bool(self.synology_api_key.get_secret_value())
            has_sid_login = bool(
                self.synology_user.strip() and self.synology_pass.get_secret_value()
            )
            if not has_api_key and not has_sid_login:
                raise ValueError(
                    "Synology storage requires SYNOLOGY_API_KEY or SYNOLOGY_USER/SYNOLOGY_PASS"
                )
            if not self.synology_interview_roots:
                raise ValueError("Synology storage requires SYNOLOGY_INTERVIEW_ROOTS")
        return self

    @field_validator("yandex_refresh_tokens", "yandex_caldav_passwords", mode="before")
    @classmethod
    def parse_string_mapping(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_validator("synology_interview_roots", mode="before")
    @classmethod
    def parse_synology_interview_roots(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ()
            if stripped.startswith("["):
                return tuple(json.loads(stripped))
            return tuple(item.strip() for item in stripped.split(",") if item.strip())
        return value

    @field_validator("synology_interview_roots")
    @classmethod
    def validate_synology_interview_roots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for root in value:
            stripped = root.rstrip("/")
            if not stripped.startswith("/"):
                raise ValueError("Synology interview roots must be absolute Synology paths")
            normalized.append(stripped)
        return tuple(dict.fromkeys(normalized))

    @field_validator(
        "test_recruiter_allowlist",
        "test_notion_database_allowlist",
        "test_mattermost_user_allowlist",
        mode="before",
    )
    @classmethod
    def parse_string_set(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return set()
            if stripped.startswith("["):
                return set(json.loads(stripped))
            return {item.strip() for item in stripped.split(",") if item.strip()}
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
