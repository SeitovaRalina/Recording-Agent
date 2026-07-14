from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import get_settings
from app.db.engine import create_engine, create_session_factory
from app.routers.events import router as events_router
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings)
    scheduler = AsyncIOScheduler()
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.scheduler = scheduler
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


app = FastAPI(title="Recording Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(events_router)
