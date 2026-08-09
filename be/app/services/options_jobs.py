"""Background-job runner for Options subsections (Double Calendar, Delta
Neutral, Hedging, Gokul Chhabra, Zero to Hero, Market Prediction).

Reuses the shared in-memory + durable ``BackgroundJob`` store from
``strategy_leaderboard_jobs`` — same create / poll / complete / fail /
orphan-resume machinery as Intra-Hedging and Backtester.
"""

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
    "complete_job", "fail_job", "run_options_job", "job_to_dict",
    "OPTIONS_SECTIONS", "options_source", "is_options_source",
]

OPTIONS_SECTIONS = frozenset({
    "double_calendar",
    "delta_neutral",
    "hedging",
    "gokul_chhabra",
    "zero_to_hero",
    "market_prediction",
    "call_put_writing",
})


def options_source(section_id: str) -> str:
    return f"options:{section_id}"


def is_options_source(source: str | None) -> bool:
    return bool(source) and source.startswith("options:")


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


async def execute_options_section(service: Any, section_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a section scan from a flat request dict (sync or background)."""
    if section_id == "double_calendar":
        return await service.double_calendar(
            payload.get("tickers") or [],
            asset_class=payload.get("asset_class") or "india",
            timeframes=payload.get("timeframes"),
            exchange=payload.get("exchange"),
            cfg_overrides={
                "short_dte": payload.get("short_dte", 14),
                "long_dte": payload.get("long_dte", 21),
                "otm_offset_pct": payload.get("otm_offset_pct", 1.5),
                "diagonal_widen_pct": payload.get("diagonal_widen_pct", 0.0),
                "take_profit_start": payload.get("take_profit_start", 0.20),
                "take_profit_max": payload.get("take_profit_max", 0.40),
                "stop_loss": payload.get("stop_loss", -0.30),
                "vix_max_threshold": payload.get("vix_max_threshold", 20.0),
                "vol_percentile_max": payload.get("vol_percentile_max", 40.0),
            },
        )
    if section_id == "delta_neutral":
        return await service.delta_neutral(
            payload.get("tickers") or [],
            asset_class=payload.get("asset_class") or "india",
            timeframes=payload.get("timeframes"),
            exchange=payload.get("exchange"),
            cfg_overrides={
                "dte": payload.get("dte", 30),
                "short_delta_target": payload.get("short_delta_target", 0.20),
                "wing_width_pct": payload.get("wing_width_pct", 5.0),
                "iron_fly": payload.get("iron_fly", False),
                "profit_target_pct": payload.get("profit_target_pct", 0.50),
                "stop_loss_multiple": payload.get("stop_loss_multiple", 1.0),
                "vix_max_threshold": payload.get("vix_max_threshold", 20.0),
                "vol_percentile_max": payload.get("vol_percentile_max", 40.0),
                "adx_trend_max": payload.get("adx_trend_max", 25.0),
            },
        )
    if section_id == "hedging":
        return await service.hedging(
            payload.get("tickers") or [],
            asset_class=payload.get("asset_class") or "india",
            exchange=payload.get("exchange"),
            cfg_overrides={
                "dte": payload.get("dte", 2),
                "hedge_distance_pct": payload.get("hedge_distance_pct", 4.0),
                "zone_timeframe": payload.get("zone_timeframe", "15m"),
                "zone_fallback_timeframe": payload.get("zone_fallback_timeframe", "1h"),
                "total_capital": payload.get("total_capital", 500_000.0),
                "profit_target_pct_of_capital": payload.get("profit_target_pct_of_capital", 0.0125),
                "max_loss_pct_of_capital": payload.get("max_loss_pct_of_capital", 0.025),
                "max_adjustments_per_day": payload.get("max_adjustments_per_day", 1),
            },
        )
    if section_id == "gokul_chhabra":
        return await service.gokul_chhabra(
            tickers=payload.get("tickers"),
            exchange=payload.get("exchange"),
            cfg_overrides={
                "vwma_length": payload.get("vwma_length", 20),
                "st_period": payload.get("st_period", 10),
                "st_multiplier": payload.get("st_multiplier", 3.0),
                "session_start": payload.get("session_start", "09:45"),
                "session_end": payload.get("session_end", "15:15"),
                "pullback_tol_pct": payload.get("pullback_tol_pct", 0.08),
                "min_rr": payload.get("min_rr", 2.0),
                "target_delta_min": payload.get("target_delta_min", 0.60),
                "target_delta_max": payload.get("target_delta_max", 0.75),
            },
        )
    if section_id == "zero_to_hero":
        return await service.zero_to_hero(
            tickers=payload.get("tickers"),
            exchange=payload.get("exchange"),
            cfg_overrides={
                "execution_tf": payload.get("execution_tf", "15m"),
                "sl_buffer_pct": payload.get("sl_buffer_pct", 0.05),
                "max_pullback_candles": payload.get("max_pullback_candles", 3),
                "partial_book_rr": payload.get("partial_book_rr", 1.0),
                "partial_book_pct": payload.get("partial_book_pct", 55.0),
                "session_end": payload.get("session_end", "15:15"),
            },
        )
    if section_id == "market_prediction":
        return await service.market_prediction(
            payload.get("symbol") or "NIFTY",
            is_index=bool(payload.get("is_index", True)),
            exchange=payload.get("exchange"),
            futures_price=payload.get("futures_price"),
            fii_index_position_cut=payload.get("fii_index_position_cut"),
            further_analysis=payload.get("further_analysis"),
        )
    if section_id == "call_put_writing":
        return await service.call_put_writing(
            payload.get("symbol") or "NIFTY",
            is_index=bool(payload.get("is_index", True)),
            exchange=payload.get("exchange"),
        )
    raise ValueError(f"Unknown Options section: {section_id}")


def run_options_job(
    job_id: str,
    section_id: str,
    payload: dict[str, Any],
    *,
    report_name: str | None = None,
    user_id: int | None = None,
) -> None:
    """Fire-and-forget entry for ``asyncio.create_task`` — owns its DB session."""

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal
        from app.services.options_service import OptionsService
        from app.services.settings_service import SettingsService

        try:
            update_progress(job_id, 0.05, f"Running Options · {section_id.replace('_', ' ')}…")
            async with AsyncSessionLocal() as db:
                service = OptionsService(SettingsService(db), db)
                result = await execute_options_section(service, section_id, payload)

            report_id: int | None = None
            save_name = (report_name or "").strip()
            if save_name and user_id is not None:
                async with AsyncSessionLocal() as db:
                    service = OptionsService(SettingsService(db), db)
                    saved = await service.save_report(
                        section_id, save_name, result, user_id=user_id,
                    )
                    report_id = saved.get("id")
                    result = {
                        **result,
                        "saved_report_id": report_id,
                        "saved_report_name": saved.get("name") or save_name,
                    }

            await complete_job(job_id, result, report_id=report_id)
        except Exception as exc:
            logger.exception("Options job %s (%s) failed", job_id, section_id)
            await fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())
