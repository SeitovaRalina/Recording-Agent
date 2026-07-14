import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.db.base import Base
from app.services.yandex_token_manager import YandexTokenManager


@pytest.mark.anyio
async def test_get_access_token_uses_fresh_cache(session: AsyncSession) -> None:
    manager = YandexTokenManager(session)
    await manager.upsert_token(
        "recruiter@example.com",
        "cached",
        "refresh",
        datetime.now(UTC) + timedelta(hours=1),
    )

    assert await manager.get_access_token("recruiter@example.com") == "cached"


@pytest.mark.anyio
async def test_refresh_posts_form_and_updates_database(session: AsyncSession) -> None:
    settings = Settings(
        YANDEX_CLIENT_ID="client",
        YANDEX_CLIENT_SECRET="secret",
        YANDEX_REFRESH_TOKENS='{"recruiter@example.com":"refresh"}',
    )
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.post("https://oauth.yandex.ru/token").mock(
                return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
            )
            manager = YandexTokenManager(session, settings, client)
            assert await manager.refresh_token("recruiter@example.com") == "fresh"
    request = route.calls[0].request
    assert b"grant_type=refresh_token" in request.content
    assert (await manager.get_token("recruiter@example.com")).access_token == "fresh"


@pytest.mark.anyio
async def test_refresh_replaces_server_rejected_but_unexpired_token(
    session: AsyncSession,
) -> None:
    settings = Settings(YANDEX_CLIENT_ID="client", YANDEX_CLIENT_SECRET="secret")
    manager = YandexTokenManager(session, settings)
    await manager.upsert_token(
        "recruiter@example.com",
        "rejected",
        "refresh",
        datetime.now(UTC) + timedelta(hours=1),
    )
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.post("https://oauth.yandex.ru/token").mock(
                return_value=httpx.Response(
                    200, json={"access_token": "replacement", "expires_in": 3600}
                )
            )
            manager = YandexTokenManager(session, settings, client)
            token = await manager.refresh_token(
                "recruiter@example.com", stale_access_token="rejected"
            )
    assert token == "replacement"


@pytest.mark.anyio
async def test_expired_token_triggers_refresh(session: AsyncSession) -> None:
    settings = Settings(YANDEX_CLIENT_ID="client", YANDEX_CLIENT_SECRET="secret")
    manager = YandexTokenManager(session, settings)
    await manager.upsert_token(
        "recruiter@example.com",
        "expired",
        "refresh",
        datetime.now(UTC) - timedelta(seconds=1),
    )
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.post("https://oauth.yandex.ru/token").mock(
                return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
            )
            manager = YandexTokenManager(session, settings, client)
            token = await manager.get_access_token("recruiter@example.com")
    assert token == "fresh"
    assert route.call_count == 1


@pytest.mark.anyio
async def test_concurrent_first_refresh_posts_once() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        YANDEX_CLIENT_ID="client",
        YANDEX_CLIENT_SECRET="secret",
        YANDEX_REFRESH_TOKENS='{"recruiter@example.com":"refresh"}',
    )
    async with httpx.AsyncClient() as client:
        with respx.mock:
            route = respx.post("https://oauth.yandex.ru/token").mock(
                return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
            )
            manager = YandexTokenManager(factory, settings, client)
            tokens = await asyncio.gather(
                manager.refresh_token("recruiter@example.com"),
                manager.refresh_token("recruiter@example.com"),
            )
    await engine.dispose()

    assert list(tokens) == ["fresh", "fresh"]
    assert route.call_count == 1
