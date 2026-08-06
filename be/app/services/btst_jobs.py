"""Background-job runner for Pro Trade's Buy Today Sell Tomorrow (BTST/STBT)
scan. Reuses the exact same generic in-memory job store as the other
background features (job ids are UUIDs, so sharing one dict is safe) rather
than standing up a second copy of the create/get/update/complete/fail
machinery."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.pro_trade_service import BTST_SOURCE
from app.services.strategy_leaderboard_jobs import (
    LeaderboardJob,
    complete_job,
    create_job,
    fail_job,
    get_job,
    list_jobs,
    update_progress,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LeaderboardJob", "create_job", "get_job", "list_jobs", "update_progress",
    "complete_job", "fail_job", "run_btst_job", "job_to_dict", "BTST_SOURCE",
]


def job_to_dict(job: LeaderboardJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "progress_note": job.progress_note,
        "result": job.result,
        "error": job.error,
        "name": job.name,
        "report_id": job.report_id,
        "source": job.source,
        "created_at": job.created_at,
        "meta": job.meta,
    }


def run_btst_job(
    job_id: str,
    tickers: list[str],
    asset_class: str,
    config: dict[str, Any] | None,
    *,
    report_name: str | None = None,
    user_id: int | None = None,
) -> None:
    """Fire-and-forget entry point for `asyncio.create_task` — builds its own
    independent DB session rather than reusing the request-scoped one, since
    that session may already be closed by the time this background task
    finishes running (the HTTP request that started it returns immediately).

    When ``report_name`` + ``user_id`` are set, the finished result is
    auto-saved to ``SavedBacktestReport`` (source="btst") so the user can
    leave the page and check back later.
    """

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal
        from app.services.pro_trade_service import ProTradeService
        from app.services.settings_service import SettingsService

        try:
            update_progress(job_id, 0.05, "Reading closing strength, trend, volume, options OI, and historical follow-through…")
            async with AsyncSessionLocal() as db:
                service = ProTradeService(SettingsService(db), db)
                result = await service.btst(tickers, asset_class=asset_class, cfg_overrides=config)

            report_id: int | None = None
            save_name = (report_name or "").strip()
            if save_name and user_id is not None:
                async with AsyncSessionLocal() as db:
                    service = ProTradeService(SettingsService(db), db)
                    saved = await service.save_btst_report(
                        save_name, tickers, asset_class, result, user_id=user_id,
                    )
                    report_id = saved.get("id")
                    result = {
                        **result,
                        "saved_report_id": report_id,
                        "saved_report_name": saved.get("name") or save_name,
                    }

            await complete_job(job_id, result, report_id=report_id)
        except Exception as exc:
            logger.exception("BTST job %s failed", job_id)
            await fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())
