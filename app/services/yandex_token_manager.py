import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models.yandex_token import YandexToken


class YandexTokenManager:
    def __init__(
        self,
        session_provider: AsyncSession | async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session_provider = session_provider
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def _session_scope(self) -> AsyncIterator[AsyncSession]:
        if isinstance(self._session_provider, AsyncSession):
            yield self._session_provider
            return
        async with self._session_provider() as session:
            yield session

    async def get_token(self, recruiter_email: str) -> YandexToken:
        async with self._session_scope() as session:
            token = await session.scalar(
                select(YandexToken).where(YandexToken.recruiter_email == recruiter_email)
            )
            if token is None:
                raise KeyError(recruiter_email)
            return token

    async def upsert_token(
        self,
        recruiter_email: str,
        access_token: str | None,
        refresh_token: str,
        expires_at: datetime | None,
    ) -> YandexToken:
        async with self._session_scope() as session:
            token = await session.scalar(
                select(YandexToken).where(YandexToken.recruiter_email == recruiter_email)
            )
            if token is None:
                token = YandexToken(
                    recruiter_email=recruiter_email,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                )
                session.add(token)
            else:
                token.access_token = access_token
                token.refresh_token = refresh_token
                token.expires_at = expires_at
                token.updated_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(token)
            return token

    async def is_expired(self, recruiter_email: str) -> bool:
        token = await self.get_token(recruiter_email)
        return not self._is_fresh(token, timedelta())

    @staticmethod
    def _is_fresh(token: YandexToken, margin: timedelta) -> bool:
        if token.access_token is None or token.expires_at is None:
            return False
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at > datetime.now(UTC) + margin

    async def get_access_token(self, recruiter_email: str) -> str:
        async with self._session_scope() as session:
            token = await session.scalar(
                select(YandexToken).where(YandexToken.recruiter_email == recruiter_email)
            )
            if token is not None and self._is_fresh(token, timedelta(minutes=5)):
                assert token.access_token is not None
                return token.access_token
        return await self.refresh_token(recruiter_email)

    async def refresh_token(
        self, recruiter_email: str, stale_access_token: str | None = None
    ) -> str:
        lock = self._refresh_locks.setdefault(recruiter_email, asyncio.Lock())
        async with lock:
            return await self._refresh_token_locked(recruiter_email, stale_access_token)

    async def _refresh_token_locked(
        self, recruiter_email: str, stale_access_token: str | None
    ) -> str:
        async with self._session_scope() as session:
            configured_refresh_token = self._settings.yandex_refresh_tokens.get(recruiter_email)
            if configured_refresh_token:
                await self._seed_token_row(session, recruiter_email, configured_refresh_token)
            async with session.begin_nested():
                token = await session.scalar(
                    select(YandexToken)
                    .where(YandexToken.recruiter_email == recruiter_email)
                    .with_for_update()
                )
                if (
                    token is not None
                    and self._is_fresh(token, timedelta(minutes=5))
                    and (stale_access_token is None or token.access_token != stale_access_token)
                ):
                    assert token.access_token is not None
                    return token.access_token

                refresh_token = (
                    token.refresh_token
                    if token is not None
                    else self._settings.yandex_refresh_tokens.get(recruiter_email)
                )
                if not refresh_token:
                    raise KeyError(f"No Yandex refresh token configured for {recruiter_email}")

                data = {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._settings.yandex_client_id,
                    "client_secret": self._settings.yandex_client_secret.get_secret_value(),
                }
                if self._http_client is None:
                    async with httpx.AsyncClient() as client:
                        response = await client.post("https://oauth.yandex.ru/token", data=data)
                else:
                    response = await self._http_client.post(
                        "https://oauth.yandex.ru/token", data=data
                    )
                response.raise_for_status()
                payload = response.json()
                access_token = str(payload["access_token"])
                expires_at = datetime.now(UTC) + timedelta(seconds=int(payload["expires_in"]))

                if token is None:
                    token = YandexToken(
                        recruiter_email=recruiter_email,
                        refresh_token=refresh_token,
                    )
                    session.add(token)
                token.access_token = access_token
                token.expires_at = expires_at
                token.updated_at = datetime.now(UTC)
                await session.flush()
            if not isinstance(self._session_provider, AsyncSession):
                await session.commit()
            return access_token

    @staticmethod
    async def _seed_token_row(
        session: AsyncSession, recruiter_email: str, refresh_token: str
    ) -> None:
        """Atomically create the lockable row before SELECT FOR UPDATE.

        The commit makes the seed visible before the refresh transaction takes its row lock.
        Concurrent PostgreSQL workers serialize on the unique key, then on FOR UPDATE.
        """
        bind = session.get_bind()
        values = {"recruiter_email": recruiter_email, "refresh_token": refresh_token}
        if bind.dialect.name == "postgresql":
            statement = postgresql_insert(YandexToken).values(**values)
            await session.execute(
                statement.on_conflict_do_nothing(index_elements=["recruiter_email"])
            )
        elif bind.dialect.name == "sqlite":
            sqlite_statement = sqlite_insert(YandexToken).values(**values)
            await session.execute(
                sqlite_statement.on_conflict_do_nothing(index_elements=["recruiter_email"])
            )
        else:
            raise RuntimeError(f"Unsupported token-store dialect: {bind.dialect.name}")
        await session.commit()
