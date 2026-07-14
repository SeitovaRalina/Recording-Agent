from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/recording_agent"
    )
    yandex_client_id: str = ""
    yandex_client_secret: SecretStr = SecretStr("")
    notion_token: SecretStr = SecretStr("")
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
    confidence_threshold: float = 0.7


@lru_cache
def get_settings() -> Settings:
    return Settings()
