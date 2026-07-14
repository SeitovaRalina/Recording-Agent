from pydantic import SecretStr

from app.config import Settings, get_settings


def test_settings_secret_types_and_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
    monkeypatch.setenv("NOTION_TOKEN", "notion-secret")
    monkeypatch.setenv("YANDEX_CLIENT_SECRET", "yandex-secret")
    get_settings.cache_clear()

    settings = get_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.notion_token, SecretStr)
    assert isinstance(settings.yandex_client_secret, SecretStr)
    assert settings.storage_provider == "minio"
    assert settings.confidence_threshold == 0.7
    get_settings.cache_clear()


def test_phase_two_settings_parse_json_maps() -> None:
    settings = Settings(
        YANDEX_REFRESH_TOKENS='{"a@example.com":"refresh"}',
        YANDEX_CALDAV_PASSWORDS='{"a@example.com":"password"}',
    )

    assert settings.scan_hour == 2
    assert settings.caldav_base_url == "https://caldav.yandex.ru"
    assert isinstance(settings.yandex_refresh_tokens["a@example.com"], SecretStr)
    assert isinstance(settings.yandex_caldav_passwords["a@example.com"], SecretStr)
