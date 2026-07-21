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
    scheduler_enabled: bool = True
    yandex_source_mutation_enabled: bool = True
    notion_writes_enabled: bool = True
    test_recruiter_allowlist: set[str] = Field(default_factory=set)
    test_notion_database_allowlist: set[str] = Field(default_factory=set)
    test_mattermost_user_allowlist: set[str] = Field(default_factory=set)

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/recording_agent"
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
    notion_project_prop: str = "Spot Client"
    notion_interview_type: str = "general_interview"
    synology_base_url: str = ""
    synology_api_key: SecretStr = SecretStr("")
    synology_user: str = ""
    synology_pass: SecretStr = SecretStr("")
    mattermost_url: str = ""
    mattermost_bot_token: SecretStr = SecretStr("")
    mattermost_channel_id: str = ""
    mattermost_bot_user_id: str = ""
    review_token_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_bucket: str = "recordings"
    minio_test_prefix: str = "test-interviews"
    storage_provider: Literal["minio", "synology"] = "minio"
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
        return self

    @field_validator("yandex_refresh_tokens", "yandex_caldav_passwords", mode="before")
    @classmethod
    def parse_string_mapping(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

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
