import pytest

from app.config import get_settings
from app.main import app
from app.tools.notion import ConnectRetryTransport


@pytest.mark.anyio
async def test_lifespan_uses_dedicated_notion_proxy_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("NOTION_PROXY_URL", "http://notion-proxy:7890")
    get_settings.cache_clear()

    async with app.router.lifespan_context(app):
        notion_client = app.state.notion_client
        direct_client = app.state.disk_scanner._http_client
        notion_http_client = app.state.notion_http_client

        assert notion_client._client is notion_http_client
        assert notion_http_client is not direct_client
        assert direct_client is not None
        assert direct_client._trust_env is False
        assert notion_http_client._trust_env is False
        assert isinstance(notion_http_client._transport, ConnectRetryTransport)
        assert notion_http_client._transport.inner._pool._proxy_url is not None

    assert notion_http_client.is_closed
    assert direct_client.is_closed
