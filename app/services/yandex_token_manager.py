from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.yandex_token import YandexToken


class YandexTokenManager:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_token(self, recruiter_email: str) -> YandexToken:
        token = await self._session.scalar(
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
        token = await self._session.scalar(
            select(YandexToken).where(YandexToken.recruiter_email == recruiter_email)
        )
        if token is None:
            token = YandexToken(
                recruiter_email=recruiter_email,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )
            self._session.add(token)
        else:
            token.access_token = access_token
            token.refresh_token = refresh_token
            token.expires_at = expires_at
            token.updated_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(token)
        return token

    async def is_expired(self, recruiter_email: str) -> bool:
        token = await self.get_token(recruiter_email)
        if token.access_token is None or token.expires_at is None:
            return True
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC)

    async def refresh_token(self, recruiter_email: str) -> str:
        del recruiter_email
        raise NotImplementedError("Yandex OAuth refresh is implemented in Phase 2")
