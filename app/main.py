from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import get_settings
from app.db.engine import create_engine, create_session_factory
from app.routers.calendars import router as calendars_router
from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.routers.tools import router as tools_router
from app.scheduler.cron import register_jobs
from app.services.candidate import CandidateService
from app.services.cleanup import CleanupService
from app.services.destinations import DestinationService
from app.services.matching import InterviewMatcher
from app.services.non_interview import NonInterviewService
from app.services.question_queue import QuestionQueueService
from app.services.reviews import ReviewService
from app.services.status import StatusService
from app.services.storage import StorageFactory
from app.services.transfer import TransferService
from app.services.yandex_token_manager import YandexTokenManager
from app.tools.calendar import CalDAVClient
from app.tools.disk import DiskScanner
from app.tools.mattermost import MattermostClient
from app.tools.notion import NotionClient
from app.tools.synology import SynologyBackend


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
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=300, pool=10))
    disk = DiskScanner(token_manager, session_factory, http_client=http_client)
    calendar = CalDAVClient(settings, session_factory, http_client=http_client)
    app.state.calendar_client = calendar
    matcher = InterviewMatcher(settings)
    app.state.disk_scanner = disk
    app.state.matcher = matcher
    notion = NotionClient(settings.notion_token, http_client, settings=settings)
    storage = StorageFactory.create(settings, http_client)
    candidate_service = CandidateService(notion, settings)
    transfer_service = TransferService(disk, storage, http_client)
    status_service = StatusService()
    mattermost = MattermostClient(
        settings.mattermost_url,
        settings.mattermost_bot_token,
        settings.mattermost_bot_user_id,
        http_client,
    )
    review_service = ReviewService(mattermost, settings)
    question_queue_service = QuestionQueueService(review_service, mattermost, settings)
    cleanup_service = CleanupService(disk, settings)
    destination_service = (
        DestinationService(storage, settings) if isinstance(storage, SynologyBackend) else None
    )
    non_interview_service = (
        NonInterviewService(session_factory, destination_service, transfer_service)
        if destination_service is not None
        else None
    )
    app.state.notion_client = notion
    app.state.storage_backend = storage
    app.state.candidate_service = candidate_service
    app.state.transfer_service = transfer_service
    app.state.status_service = status_service
    app.state.review_service = review_service
    app.state.question_queue_service = question_queue_service
    app.state.cleanup_service = cleanup_service
    app.state.destination_service = destination_service
    app.state.non_interview_service = non_interview_service
    register_jobs(
        scheduler,
        session_factory,
        disk,
        calendar,
        matcher,
        candidate_service,
        transfer_service,
        status_service,
        notion,
        review_service,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await http_client.aclose()
        await engine.dispose()


app = FastAPI(title="Recording Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(events_router)
app.include_router(calendars_router)
app.include_router(tools_router)
