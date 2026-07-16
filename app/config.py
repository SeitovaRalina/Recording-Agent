import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    synology_base_url: str = ""
    synology_api_key: SecretStr = SecretStr("")
    synology_user: str = ""
    synology_pass: SecretStr = SecretStr("")
    mattermost_url: str = ""
    mattermost_bot_token: SecretStr = SecretStr("")
    mattermost_channel_id: str = ""
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_bucket: str = "recordings"
    storage_provider: Literal["minio", "synology"] = "minio"
    openclaw_events_url: str = "http://localhost:8001/events"
    openclaw_secret: SecretStr = SecretStr("")
    confidence_threshold: float = Field(
        default=0.7,
        validation_alias=AliasChoices("confidence_threshold", "CONFIDENCE_THRESHOLD"),
    )

    @field_validator("yandex_refresh_tokens", "yandex_caldav_passwords", mode="before")
    @classmethod
    def parse_string_mapping(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
