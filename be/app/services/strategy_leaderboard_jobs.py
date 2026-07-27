"""
strategy_leaderboard_jobs.py
------------------------------
In-memory background-job store for the Strategy Lab leaderboard. A full run
(many tickers x many strategies x hundreds of walk-forward steps each) can
legitimately take minutes — long enough that treating it as a synchronous
HTTP request is the wrong shape entirely (request timeouts, no progress
feedback, no way to keep working while it runs). This gives it the same
"start job, poll for status" shape used elsewhere for long-running work.

Deliberately a plain in-memory dict, not a persisted queue — this app is a
single process, and a job that's still running when the process restarts
isn't recoverable either way. Jobs age out after `_JOB_TTL_SECONDS` so this
dict doesn't grow unbounded over a long-running server process.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_JOB_TTL_SECONDS = 3600


@dataclass
class LeaderboardJob:
    id: str
    status: str = "running"  # running | done | error
    progress: float = 0.0
    progress_note: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


_JOBS: dict[str, LeaderboardJob] = {}


def _prune() -> None:
    cutoff = time.time() - _JOB_TTL_SECONDS
    stale = [jid for jid, j in _JOBS.items() if j.created_at < cutoff]
    for jid in stale:
        _JOBS.pop(jid, None)


def create_job() -> LeaderboardJob:
    _prune()
    job = LeaderboardJob(id=uuid.uuid4().hex)
    _JOBS[job.id] = job
    return job


def get_job(job_id: str) -> LeaderboardJob | None:
    return _JOBS.get(job_id)


def update_progress(job_id: str, progress: float, note: str = "") -> None:
    job = _JOBS.get(job_id)
    if job:
        job.progress = progress
        job.progress_note = note


def complete_job(job_id: str, result: dict[str, Any]) -> None:
    job = _JOBS.get(job_id)
    if job:
        job.status = "done"
        job.progress = 1.0
        job.result = result


def fail_job(job_id: str, error: str) -> None:
    job = _JOBS.get(job_id)
    if job:
        job.status = "error"
        job.error = error


def run_leaderboard_job(
    job_id: str,
    tickers: list[str],
    timeframes: list[str],
    *,
    asset_class: str,
    strategy_ids: list[str] | None,
    bars: int,
    forward_bars: int,
) -> None:
    """Fire-and-forget entry point for `asyncio.create_task` — builds its own
    independent DB session rather than reusing the request-scoped one, since
    that session may already be closed by the time this background task
    finishes running (the HTTP request that started it returns immediately)."""

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal
        from app.services.settings_service import SettingsService
        from app.services.strategy_leaderboard_service import StrategyLeaderboardService

        try:
            async with AsyncSessionLocal() as db:
                service = StrategyLeaderboardService(SettingsService(db), db)
                result = await service.run(
                    tickers, timeframes,
                    asset_class=asset_class, strategy_ids=strategy_ids,
                    bars=bars, forward_bars=forward_bars,
                    progress_cb=lambda p, note: update_progress(job_id, p, note),
                )
            complete_job(job_id, result)
        except Exception as exc:
            fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())
