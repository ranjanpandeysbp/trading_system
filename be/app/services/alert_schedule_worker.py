"""Background loop that runs due alert schedules across all users."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.db_models import AlertSchedule
from app.services.schedule_alerts_service import ScheduleAlertsService, schedule_is_due
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

_POLL_SECONDS = 30


async def run_due_schedules_once() -> int:
    """Run all enabled due schedules. Returns count executed."""
    ran = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AlertSchedule).where(AlertSchedule.enabled == True)  # noqa: E712
        )
        schedules = list(result.scalars().all())
        # Group by user so SettingsService uses a fresh session context per user
        by_user: dict[int, list[AlertSchedule]] = {}
        for s in schedules:
            by_user.setdefault(s.user_id, []).append(s)

        for user_id, items in by_user.items():
            svc = ScheduleAlertsService(db, SettingsService(db))
            for sched in items:
                if not schedule_is_due(sched):
                    continue
                try:
                    await svc._execute_schedule(sched)  # noqa: SLF001
                    ran += 1
                except Exception:
                    logger.exception("Background schedule %s failed", sched.id)
    return ran


async def alert_schedule_worker(stop_event: asyncio.Event) -> None:
    logger.info("Alert schedule worker started (every %ss)", _POLL_SECONDS)
    while not stop_event.is_set():
        try:
            n = await run_due_schedules_once()
            if n:
                logger.info("Alert schedule worker ran %s schedule(s)", n)
        except Exception:
            logger.exception("Alert schedule worker tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("Alert schedule worker stopped")
