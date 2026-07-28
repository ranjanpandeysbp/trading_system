"""Background-job runner for the Backtester leaderboard. Reuses the exact
same generic in-memory job store as the Strategy Lab leaderboard (job ids
are UUIDs, so the two features sharing one dict is safe) rather than
standing up a second copy of the same create/get/update/complete/fail
machinery."""

from __future__ import annotations

import asyncio

from app.services.strategy_leaderboard_jobs import (
    LeaderboardJob,
    complete_job,
    create_job,
    fail_job,
    get_job,
    update_progress,
)

__all__ = [
    "LeaderboardJob", "create_job", "get_job", "update_progress",
    "complete_job", "fail_job", "run_backtester_job",
]


def run_backtester_job(
    job_id: str,
    tickers: list[str],
    strategy_ids: list[str],
    *,
    asset_class: str,
    timeframe: str | None,
    period: str | None,
    costs_pct: float | None,
    bars: int = 350,
    forward_bars: int = 10,
) -> None:
    """Fire-and-forget entry point for `asyncio.create_task` — builds its own
    independent DB session rather than reusing the request-scoped one, since
    that session may already be closed by the time this background task
    finishes running (the HTTP request that started it returns immediately)."""

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal
        from app.services.backtester_leaderboard_service import BacktesterLeaderboardService
        from app.services.settings_service import SettingsService

        try:
            async with AsyncSessionLocal() as db:
                service = BacktesterLeaderboardService(SettingsService(db), db)
                result = await service.run(
                    tickers, strategy_ids,
                    asset_class=asset_class, timeframe=timeframe, period=period, costs_pct=costs_pct,
                    bars=bars, forward_bars=forward_bars,
                    progress_cb=lambda p, note: update_progress(job_id, p, note),
                )
            complete_job(job_id, result)
        except Exception as exc:
            fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())
