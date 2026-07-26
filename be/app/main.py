from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router
from app.core.config import settings
from app.core.database import init_db
from app.services.alert_schedule_worker import alert_schedule_worker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    stop = asyncio.Event()
    worker_task = asyncio.create_task(alert_schedule_worker(stop), name="alert-schedule-worker")
    logger.info("Started alert schedule background worker")
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(worker_task, timeout=10)
        except (asyncio.TimeoutError, Exception):
            worker_task.cancel()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
