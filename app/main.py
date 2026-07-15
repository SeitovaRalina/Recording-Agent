from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import get_settings
from app.db.engine import create_engine, create_session_factory
from app.routers.calendars import router as calendars_router
from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.scheduler.cron import register_jobs
from app.services.matching import InterviewMatcher
from app.services.yandex_token_manager import YandexTokenManager
from app.tools.calendar import CalDAVClient
from app.tools.disk import DiskScanner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings)
    scheduler = AsyncIOScheduler()
    app.state.engine = engine
    session_factory = create_session_factory(engine)
    app.state.session_factory = session_factory
    app.state.scheduler = scheduler
    token_manager = YandexTokenManager(session_factory, settings)
    disk = DiskScanner(token_manager, session_factory)
    calendar = CalDAVClient(settings, session_factory)
    app.state.calendar_client = calendar
    matcher = InterviewMatcher(settings)
    register_jobs(scheduler, session_factory, disk, calendar, matcher)
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


app = FastAPI(title="Recording Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(events_router)
app.include_router(calendars_router)
