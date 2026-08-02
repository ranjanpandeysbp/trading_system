"""
strategy_leaderboard_jobs.py
------------------------------
Background-job store for the Strategy Lab / Backtester leaderboards. A full
run (many tickers x many strategies x hundreds of walk-forward steps each)
can legitimately take minutes — long enough that treating it as a
synchronous HTTP request is the wrong shape (request timeouts, no progress
feedback, no way to keep working while it runs). This gives it the same
"start job, poll for status" shape used elsewhere for long-running work.

Durability: live progress is kept in a plain in-memory dict (fast, and
progress ticks are cosmetic — losing them on a restart is fine). But job
*lifecycle* (created / done / error) is also written to the `background_jobs`
DB table, because a pure in-memory job silently vanishes if the backend
process restarts mid-run — the exact bug this was rewritten to fix: a
background backtest that was genuinely running would just disappear with no
report saved and no error shown, since nothing survived the restart to ever
call save_report() or fail_job().

On startup, `resume_orphaned_jobs()` finds any DB row still marked "running"
(which, if the process just (re)started, cannot actually still be running —
it's a job that was interrupted mid-flight) and transparently re-launches it
from the same stored request, reusing the same job id, so it completes and
saves normally instead of vanishing. The user sees the same job "catch up"
rather than an error, in the common case (deploy/restart) where nothing
about the request itself was invalid.

Jobs age out of the in-memory dict after `_JOB_TTL_SECONDS` so it doesn't
grow unbounded over a long-running server process; the DB row is the
permanent record.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

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
    # Optional metadata for multi-job UIs (Backtester background runs).
    name: str | None = None
    user_id: int | None = None
    source: str = "strategy_leaderboard"
    report_id: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    request_payload: dict[str, Any] = field(default_factory=dict)


_JOBS: dict[str, LeaderboardJob] = {}


def _prune() -> None:
    cutoff = time.time() - _JOB_TTL_SECONDS
    stale = [jid for jid, j in _JOBS.items() if j.created_at < cutoff and j.status != "running"]
    for jid in stale:
        _JOBS.pop(jid, None)


async def _persist_new(job: LeaderboardJob) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.db_models import BackgroundJob

    try:
        async with AsyncSessionLocal() as db:
            db.add(BackgroundJob(
                id=job.id, user_id=job.user_id, source=job.source, name=job.name,
                status=job.status, request_json=json.dumps(job.request_payload),
                meta_json=json.dumps(job.meta),
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to persist new background job %s — it will not survive a restart.", job.id)


async def _persist_update(job_id: str, *, status: str, error: str | None = None, report_id: int | None = None) -> None:
    from sqlalchemy import update as sa_update

    from app.core.database import AsyncSessionLocal
    from app.models.db_models import BackgroundJob

    try:
        async with AsyncSessionLocal() as db:
            values: dict[str, Any] = {"status": status}
            if error is not None:
                values["error"] = error
            if report_id is not None:
                values["report_id"] = report_id
            await db.execute(sa_update(BackgroundJob).where(BackgroundJob.id == job_id).values(**values))
            await db.commit()
    except Exception:
        logger.exception("Failed to persist status update for background job %s", job_id)


async def create_job(
    *,
    name: str | None = None,
    user_id: int | None = None,
    source: str = "strategy_leaderboard",
    meta: dict[str, Any] | None = None,
    request_payload: dict[str, Any] | None = None,
) -> LeaderboardJob:
    _prune()
    job = LeaderboardJob(
        id=uuid.uuid4().hex,
        name=(name or "").strip()[:200] or None,
        user_id=user_id,
        source=source,
        meta=meta or {},
        request_payload=request_payload or {},
    )
    _JOBS[job.id] = job
    await _persist_new(job)
    return job


def get_job(job_id: str) -> LeaderboardJob | None:
    return _JOBS.get(job_id)


def list_jobs(
    *,
    user_id: int | None = None,
    source: str | None = None,
    status: str | None = None,
) -> list[LeaderboardJob]:
    """Return jobs newest-first, optionally filtered by user / source /
    status. `status=None` (or "all") returns every status this process has
    seen — running, done, and error alike — so a user who left the page and
    came back can see what happened to a job that finished or failed while
    they were away, not just currently-running ones."""
    _prune()
    jobs = list(_JOBS.values())
    if user_id is not None:
        jobs = [j for j in jobs if j.user_id == user_id]
    if source is not None:
        jobs = [j for j in jobs if j.source == source]
    if status not in (None, "", "all"):
        jobs = [j for j in jobs if j.status == status]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs


def update_progress(job_id: str, progress: float, note: str = "") -> None:
    job = _JOBS.get(job_id)
    if job:
        job.progress = progress
        job.progress_note = note


async def complete_job(job_id: str, result: dict[str, Any], *, report_id: int | None = None) -> None:
    job = _JOBS.get(job_id)
    if job:
        job.status = "done"
        job.progress = 1.0
        job.result = result
        if report_id is not None:
            job.report_id = report_id
    await _persist_update(job_id, status="done", report_id=report_id)


async def fail_job(job_id: str, error: str) -> None:
    job = _JOBS.get(job_id)
    if job:
        job.status = "error"
        job.error = error
    await _persist_update(job_id, status="error", error=error)


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
    import asyncio

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
            await complete_job(job_id, result)
        except Exception as exc:
            logger.exception("Strategy Lab leaderboard job %s failed", job_id)
            await fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())


async def resume_orphaned_jobs() -> int:
    """Called once at app startup. Any DB row still marked "running" was
    interrupted by a process restart — it cannot genuinely still be running
    in a process that just started. Re-launches each one from its stored
    request payload, reusing the same job id, so it completes (and, for
    Backtester jobs with an auto-save name, still gets saved as a report)
    instead of silently vanishing. Returns the number of jobs resumed."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.db_models import BackgroundJob
    from app.services.backtester_leaderboard_jobs import BACKTESTER_SOURCE, run_backtester_job

    resumed = 0
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(BackgroundJob).where(BackgroundJob.status == "running"))).scalars().all()
            for row in rows:
                try:
                    payload = json.loads(row.request_json or "{}")
                    meta = json.loads(row.meta_json or "{}")
                except Exception:
                    logger.warning("Could not decode stored request for orphaned job %s — marking failed.", row.id)
                    row.status = "error"
                    row.error = "Interrupted by a server restart and the original request could not be replayed."
                    continue

                job = LeaderboardJob(
                    id=row.id, status="running", name=row.name, user_id=row.user_id,
                    source=row.source, meta=meta, request_payload=payload,
                )
                _JOBS[row.id] = job

                if row.source == BACKTESTER_SOURCE:
                    run_backtester_job(
                        row.id, payload.get("tickers", []), payload.get("strategy_ids", []),
                        asset_class=payload.get("asset_class", "india"), timeframe=payload.get("timeframe"),
                        period=payload.get("period"), costs_pct=payload.get("costs_pct"),
                        bars=payload.get("bars", 350), forward_bars=payload.get("forward_bars", 10),
                        report_name=payload.get("report_name"), user_id=row.user_id,
                    )
                else:
                    run_leaderboard_job(
                        row.id, payload.get("tickers", []), payload.get("timeframes", ["1d"]),
                        asset_class=payload.get("asset_class", "india"), strategy_ids=payload.get("strategy_ids"),
                        bars=payload.get("bars", 350), forward_bars=payload.get("forward_bars", 10),
                    )
                resumed += 1
                logger.info("Resumed orphaned background job %s (%s) after restart.", row.id, row.source)
            await db.commit()
    except Exception:
        logger.exception("Failed to scan for orphaned background jobs at startup.")
    return resumed
