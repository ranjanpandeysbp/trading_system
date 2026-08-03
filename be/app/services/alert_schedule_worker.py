"""Background loop that runs due alert schedules across all users."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

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


async def run_due_suggestion_engines_once() -> int:
    """Kick off an Auto Trade sweep for every enabled, due
    `SuggestionEngineSchedule`. Returns count triggered. `next_run_at` is
    set provisionally here (interval from now) before the sweep starts, so
    a multi-minute sweep can't get re-triggered by the next 30s tick — the
    sweep overwrites it with the real value once it actually finishes."""
    from app.models.db_models import SuggestionEngineSchedule
    from app.services.suggestion_engine_service import run_suggestion_sweep

    now = datetime.utcnow()
    due_user_ids: list[int] = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SuggestionEngineSchedule).where(SuggestionEngineSchedule.enabled == True)  # noqa: E712
        )
        for row in result.scalars().all():
            if row.next_run_at is not None and row.next_run_at > now:
                continue
            due_user_ids.append(row.user_id)
            row.next_run_at = now + timedelta(minutes=row.interval_minutes)
            row.last_status = "Running…"
        if due_user_ids:
            await db.commit()

    triggered = 0
    for user_id in due_user_ids:
        try:
            run_suggestion_sweep(user_id)
            triggered += 1
        except Exception:
            logger.exception("Failed to trigger Auto Trade sweep for user %s", user_id)
    return triggered


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
            m = await run_due_suggestion_engines_once()
            if m:
                logger.info("Alert schedule worker triggered %s Auto Trade sweep(s)", m)
        except Exception:
            logger.exception("Auto Trade due-check tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("Alert schedule worker stopped")
