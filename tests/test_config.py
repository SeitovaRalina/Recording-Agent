import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings, get_settings


def test_settings_secret_types_and_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
    monkeypatch.setenv("NOTION_TOKEN", "notion-secret")
    monkeypatch.setenv("YANDEX_CLIENT_SECRET", "yandex-secret")
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("PIPELINE_TRACE_ENABLED", "false")
    get_settings.cache_clear()

    settings = get_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.notion_token, SecretStr)
    assert isinstance(settings.yandex_client_secret, SecretStr)
    assert settings.storage_provider == "minio"
    assert settings.notion_project_prop == "📍 Spots"
    assert settings.notion_project_prop_type == "relation"
    assert settings.confidence_threshold == 0.7
    assert settings.scan_ignore_before_today is True
    assert settings.scan_local_timezone == "Asia/Omsk"
    assert settings.recording_filename_timezone == "Europe/Moscow"
    assert settings.app_environment == "production"
    assert settings.pipeline_trace_active is False
    get_settings.cache_clear()


def test_phase_two_settings_parse_json_maps() -> None:
    settings = Settings(
        YANDEX_REFRESH_TOKENS='{"a@example.com":"refresh"}',
        YANDEX_CALDAV_PASSWORDS='{"a@example.com":"password"}',
        scan_hour=2,
        caldav_base_url="https://caldav.yandex.ru",
    )

    assert settings.scan_hour == 2
    assert settings.caldav_base_url == "https://caldav.yandex.ru"
    assert isinstance(settings.yandex_refresh_tokens["a@example.com"], SecretStr)
    assert isinstance(settings.yandex_caldav_passwords["a@example.com"], SecretStr)


def test_scan_cutoff_settings_support_environment_aliases(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SCAN_IGNORE_BEFORE_TODAY", "false")
    monkeypatch.setenv("SCAN_LOCAL_TIMEZONE", "UTC")
    monkeypatch.setenv("RECORDING_FILENAME_TIMEZONE", "Europe/Berlin")
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("PIPELINE_TRACE_ENABLED", "true")

    settings = Settings()

    assert settings.scan_ignore_before_today is False
    assert settings.scan_local_timezone == "UTC"
    assert settings.recording_filename_timezone == "Europe/Berlin"
    assert settings.pipeline_trace_active is True


def test_mattermost_delivery_can_be_disabled_only_in_test_mode() -> None:
    with pytest.raises(ValidationError, match="only in test mode"):
        Settings(test_mode_enabled=False, mattermost_delivery_enabled=False)

    settings = Settings(
        test_mode_enabled=True,
        yandex_source_mutation_enabled=False,
        mattermost_delivery_enabled=False,
    )
    assert settings.mattermost_delivery_enabled is False
