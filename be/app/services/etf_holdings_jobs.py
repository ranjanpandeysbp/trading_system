"""Background-job runner for Command Center's ETF Holdings tracker — handles
both the India (scheme-based) and US/Crypto (symbol-based) analysis paths
under one job source so they share the same saved-reports list. Reuses the
exact same generic in-memory job store as the other background features
rather than standing up a second copy of the create/get/update/complete/fail
machinery."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
    "complete_job", "fail_job", "run_etf_holdings_job", "job_to_dict", "ETF_HOLDINGS_SOURCE",
]

ETF_HOLDINGS_SOURCE = "etf_holdings"


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


def run_etf_holdings_job(
    job_id: str,
    asset_class: str,  # "india" (scheme-based) | "us" | "crypto" (symbol-based) — doubles as the mode marker
    scheme_ids: list[int],
    scheme_names: dict[int, str],
    symbols: list[str],
    symbol_names: dict[str, str],
    from_date: str,
    to_date: str,
    *,
    report_name: str | None = None,
    user_id: int | None = None,
) -> None:
    """Fire-and-forget entry point for `asyncio.create_task` — builds its own
    independent DB session rather than reusing the request-scoped one, since
    that session may already be closed by the time this background task
    finishes running (the HTTP request that started it returns immediately).
    `asset_class` picks India's scheme-based analysis vs. US/Crypto's
    symbol-based one — the same dispatch resume_orphaned_jobs uses to replay
    this after a restart.

    When ``report_name`` + ``user_id`` are set, the finished result is
    auto-saved to ``SavedBacktestReport`` (source="etf_holdings") so the
    user can leave the page and check back later.
    """

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal
        from app.services.command_center_service import CommandCenterService
        from app.services.settings_service import SettingsService

        try:
            is_india = asset_class == "india"
            update_progress(
                job_id, 0.1,
                "Fetching month-end ETF holdings…" if is_india else "Fetching ETF/fund holdings…",
            )
            async with AsyncSessionLocal() as db:
                service = CommandCenterService(SettingsService(db), db)
                if is_india:
                    result = await service.etf_india_holdings_change(scheme_ids, scheme_names, from_date, to_date)
                    names = [scheme_names.get(sid, str(sid)) for sid in scheme_ids]
                else:
                    result = await service.etf_us_holdings_change(asset_class, symbols, symbol_names, from_date, to_date)
                    names = [symbol_names.get(s, s) for s in symbols]

            report_id: int | None = None
            save_name = (report_name or "").strip()
            if save_name and user_id is not None and not result.get("error"):
                async with AsyncSessionLocal() as db:
                    service = CommandCenterService(SettingsService(db), db)
                    saved = await service.save_etf_holdings_report(
                        save_name, asset_class, names, from_date, to_date, result, user_id=user_id,
                    )
                    report_id = saved.get("id")
                    result = {
                        **result,
                        "saved_report_id": report_id,
                        "saved_report_name": saved.get("name") or save_name,
                    }

            await complete_job(job_id, result, report_id=report_id)
        except Exception as exc:
            logger.exception("ETF Holdings job %s failed", job_id)
            await fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())
