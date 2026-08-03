"""Background-job runner for Command Center's Mutual Fund Holdings Tracker.
Reuses the exact same generic in-memory job store as the Strategy Lab /
Backtester leaderboards (job ids are UUIDs, so sharing one dict is safe)
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
    "complete_job", "fail_job", "run_mf_holdings_job", "job_to_dict", "MF_HOLDINGS_SOURCE",
]

MF_HOLDINGS_SOURCE = "mutual_fund_holdings"


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


def run_mf_holdings_job(
    job_id: str,
    scheme_ids: list[int],
    scheme_names: dict[int, str],
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

    When ``report_name`` + ``user_id`` are set, the finished result is
    auto-saved to ``SavedBacktestReport`` (source="mutual_fund_holdings") so
    the user can leave the page and check back later.
    """

    async def _run() -> None:
        from datetime import date as date_cls

        from app.market_pulse.mutual_fund_holdings_engine import analyze_holdings_change
        from app.market_pulse.serialize import json_safe

        try:
            names = {int(k): str(v) for k, v in (scheme_names or {}).items()}
            update_progress(job_id, 0.05, "Fetching month-end holdings across selected funds…")
            raw_result = await asyncio.to_thread(
                analyze_holdings_change,
                scheme_ids,
                names,
                date_cls.fromisoformat(from_date),
                date_cls.fromisoformat(to_date),
                progress_callback=lambda p, note: update_progress(job_id, min(p, 0.95), note),
            )
            result = json_safe(raw_result)

            report_id: int | None = None
            save_name = (report_name or "").strip()
            if save_name and user_id is not None:
                from app.core.database import AsyncSessionLocal
                from app.services.command_center_service import CommandCenterService
                from app.services.settings_service import SettingsService

                async with AsyncSessionLocal() as db:
                    service = CommandCenterService(SettingsService(db), db)
                    saved = await service.save_mutual_fund_holdings_report(
                        save_name, scheme_ids, names, from_date, to_date, result, user_id=user_id,
                    )
                    report_id = saved.get("id")
                    result = {
                        **result,
                        "saved_report_id": report_id,
                        "saved_report_name": saved.get("name") or save_name,
                    }

            await complete_job(job_id, result, report_id=report_id)
        except Exception as exc:
            logger.exception("Mutual Fund Holdings job %s failed", job_id)
            await fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())
