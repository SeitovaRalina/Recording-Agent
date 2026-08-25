import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings, get_settings


def test_settings_secret_types_and_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost/test",  # pragma: allowlist secret
    )
    monkeypatch.setenv("NOTION_TOKEN", "notion-secret")
    monkeypatch.setenv("NOTION_PROXY_URL", "http://notion-proxy:7890")
    monkeypatch.setenv("YANDEX_CLIENT_SECRET", "yandex-secret")
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("PIPELINE_TRACE_ENABLED", "false")
    get_settings.cache_clear()

    settings = get_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.notion_token, SecretStr)
    assert isinstance(settings.notion_proxy_url, SecretStr)
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
    assert settings.scheduler_enabled is False
    assert settings.autonomous_routing_enabled is False
    assert settings.mattermost_delivery_enabled is False
    assert settings.notion_writes_enabled is False
    assert settings.yandex_source_mutation_enabled is False
    get_settings.cache_clear()


def test_production_requires_notion_proxy_url() -> None:
    with pytest.raises(ValidationError, match="Production requires NOTION_PROXY_URL"):
        Settings(app_environment="production")


@pytest.mark.parametrize(
    "proxy_url",
    [
        "socks5://notion-proxy:7890",
        "http://",
        "http://notion-proxy/not-allowed",
        "http://notion-proxy:70000",
        "https://notion-proxy:7890?token=secret",
    ],
)
def test_production_rejects_invalid_notion_proxy_url(proxy_url: str) -> None:
    with pytest.raises(ValidationError, match="NOTION_PROXY_URL must be a valid HTTP proxy URL"):
        Settings(app_environment="production", notion_proxy_url=proxy_url)


def test_notion_proxy_url_is_secret_and_development_may_omit_it() -> None:
    proxy_url = "http://proxy-user:proxy-password@notion-proxy:7890"
    settings = Settings(app_environment="development", notion_proxy_url=proxy_url)

    assert settings.notion_proxy_url.get_secret_value() == proxy_url
    assert proxy_url not in str(settings)
    assert proxy_url not in repr(settings)
    assert Settings(app_environment="test").notion_proxy_url.get_secret_value() == ""


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


def test_synology_interview_roots_parse_from_json_and_csv() -> None:
    json_settings = Settings(
        SYNOLOGY_INTERVIEW_ROOTS='["/home/Recruiting-E/2. Interviews external"]'
    )
    csv_settings = Settings(
        SYNOLOGY_INTERVIEW_ROOTS=(
            "/home/Recruiting-NE/2. Interviews,/home/Recruiting-E/3. Interviews internal/"
        )
    )

    assert json_settings.synology_interview_roots == ("/home/Recruiting-E/2. Interviews external",)
    assert csv_settings.synology_interview_roots == (
        "/home/Recruiting-NE/2. Interviews",
        "/home/Recruiting-E/3. Interviews internal",
    )


def test_synology_accepts_public_permanent_share_links() -> None:
    settings = Settings(
        storage_provider="synology",
        synology_base_url="https://nas.test",
        synology_api_key=SecretStr("key"),
        synology_interview_roots=("/home/Recruiting-E",),
    )
    assert settings.storage_provider == "synology"


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


def test_side_effect_flags_are_explicitly_opt_in() -> None:
    settings = Settings(
        scheduler_enabled=True,
        autonomous_routing_enabled=True,
        mattermost_delivery_enabled=True,
        notion_writes_enabled=True,
        yandex_source_mutation_enabled=True,
    )
    assert settings.scheduler_enabled is True
    assert settings.autonomous_routing_enabled is True
    assert settings.mattermost_delivery_enabled is True
