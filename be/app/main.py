from contextlib import asynccontextmanager
import asyncio
import logging

# pandas_ta (unmaintained) still does `from numpy import NaN` internally —
# numpy 2.0 removed that alias entirely, so every `import pandas_ta` in the
# app silently fails inside its own try/except blocks, degrading several
# indicators (CMF, ADX, Ichimoku, MACD, VWAP position, SMC helpers) across
# market_pulse without ever surfacing as a visible error. Restore the alias
# once, here, before anything else has a chance to import pandas_ta.
import numpy as _np

if not hasattr(_np, "NaN"):
    _np.NaN = _np.nan  # type: ignore[attr-defined]

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
    try:
        from app.services.strategy_leaderboard_jobs import resume_orphaned_jobs

        resumed = await resume_orphaned_jobs()
        if resumed:
            logger.info("Resumed %d background job(s) interrupted by the last restart.", resumed)
    except Exception:
        logger.exception("Startup job-resume scan failed — any interrupted background jobs will not auto-resume this time.")
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
