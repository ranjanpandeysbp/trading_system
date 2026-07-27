"""
strategy_leaderboard_service.py
---------------------------------
Strategy Lab — "which of the app's real strategies actually works best for
this ticker": runs every registered strategy (see `strategy_registry.py`)
through the walk-forward calibration harness for one or more tickers and
timeframes, and ranks the results.

Single-timeframe strategies are tested on every timeframe the caller
selects (so "which timeframe suits this strategy" is answered too).
Multi-timeframe strategies (SMC-style HTF-bias + LTF-execution setups, or
relative-strength-vs-benchmark reads) always run on their own designed
timeframe pairing regardless of what the caller selected — reassigning e.g.
a "1h bias + 15m execution" strategy to some other pair would silently
change what it is, not just when it runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from app.market_pulse.calibration_engine import (
    CalibrationResult,
    walk_forward_backtest,
    walk_forward_backtest_multi,
)
from app.services.settings_service import SettingsService
from app.services.strategy_registry import (
    StrategyDef,
    all_strategies,
    benchmark_ticker_for_market,
    get_strategy,
)
from app.services.ticker_universe_service import TickerUniverseService

logger = logging.getLogger(__name__)

_DEFAULT_BARS = 350
_DEFAULT_FORWARD_BARS = 10
_MIN_SAMPLE_FOR_TRUST = 30


class StrategyLeaderboardService:
    def __init__(self, settings: SettingsService, db: Any = None):
        self.settings = settings
        self.db = db
        self.universe = TickerUniverseService()

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str]:
        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        if asset_class == "india":
            return str(cfg["market"]), await self.settings.get_groww_exchange()
        return str(cfg["market"]), str(cfg.get("exchange") or "NSE")

    async def run(
        self,
        tickers: list[str],
        timeframes: list[str],
        *,
        asset_class: str = "india",
        strategy_ids: list[str] | None = None,
        bars: int = _DEFAULT_BARS,
        forward_bars: int = _DEFAULT_FORWARD_BARS,
        progress_cb: Any = None,
    ) -> dict[str, Any]:
        market, exchange = await self._asset_ctx(asset_class)
        token = await self.settings.get_groww_token() if asset_class == "india" else None
        resolved_tickers = list(self.universe.resolve(asset_class, tickers)) or tickers

        strategies = [get_strategy(sid) for sid in strategy_ids] if strategy_ids else all_strategies()
        strategies = [s for s in strategies if s is not None]
        if not strategies:
            return {"error": "No valid strategies selected.", "rows": []}
        if not resolved_tickers:
            return {"error": "No tickers resolved.", "rows": []}
        if not timeframes:
            timeframes = ["1d"]

        def _run_all() -> list[dict[str, Any]]:
            return _run_leaderboard_sync(
                resolved_tickers, timeframes, strategies,
                market=market, exchange=exchange, groww_token=token or "",
                bars=bars, forward_bars=forward_bars, progress_cb=progress_cb,
            )

        rows = await asyncio.to_thread(_run_all)
        rows.sort(key=lambda r: r.get("rank_score", -1e9), reverse=True)

        best_per_ticker: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r.get("total_signals", 0) < 1:
                continue
            t = r["ticker"]
            if t not in best_per_ticker or r["rank_score"] > best_per_ticker[t]["rank_score"]:
                best_per_ticker[t] = r

        return {
            "market": market,
            "asset_class": asset_class,
            "tickers": resolved_tickers,
            "timeframes": timeframes,
            "strategy_count": len(strategies),
            "bars": bars,
            "forward_bars": forward_bars,
            "rows": rows,
            "best_per_ticker": list(best_per_ticker.values()),
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def strategies_catalog(self) -> dict[str, Any]:
        return {
            "strategies": [
                {
                    "id": s.id, "label": s.label, "hub": s.hub,
                    "timeframes": s.timeframes, "multi_tf": s.multi_tf,
                    "needs_benchmark": s.needs_benchmark, "notes": s.notes,
                }
                for s in all_strategies()
            ],
        }

    # ------------------------------------------------------------------
    # Saved reports
    # ------------------------------------------------------------------

    async def save_report(self, name: str, payload: dict[str, Any], *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = SavedBacktestReport(
            user_id=user_id,
            name=name.strip()[:200] or f"Report {datetime.utcnow().isoformat()}",
            asset_class=str(payload.get("asset_class", "")),
            tickers=",".join(payload.get("tickers", [])),
            timeframes=",".join(payload.get("timeframes", [])),
            payload_json=json.dumps(payload, default=str),
        )
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        return {"id": report.id, "name": report.name, "created_at": report.created_at.isoformat()}

    async def list_reports(self, *, user_id: int | None) -> dict[str, Any]:
        from sqlalchemy import select

        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"reports": []}
        stmt = select(SavedBacktestReport).order_by(SavedBacktestReport.created_at.desc())
        if user_id is not None:
            stmt = stmt.where(SavedBacktestReport.user_id == user_id)
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return {
            "reports": [
                {
                    "id": r.id, "name": r.name, "asset_class": r.asset_class,
                    "tickers": r.tickers.split(",") if r.tickers else [],
                    "timeframes": r.timeframes.split(",") if r.timeframes else [],
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }

    async def get_report(self, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        if not report or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        return {
            "id": report.id, "name": report.name, "created_at": report.created_at.isoformat(),
            "payload": json.loads(report.payload_json),
        }

    async def delete_report(self, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        if not report or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        await self.db.delete(report)
        await self.db.commit()
        return {"deleted": True}


def _fetch_cached(
    cache: dict[tuple[str, str], Any], ticker: str, tf: str, *, market: str, exchange: str, groww_token: str, bars: int,
):
    key = (ticker, tf)
    if key not in cache:
        from app.market_pulse.gap_trading import fetch_data_for_gap_scan

        cache[key] = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=bars)
    return cache[key]


def _rank_score(result: CalibrationResult) -> float:
    """Confidence-adjusted expectancy: raw expectancy (avg forward return %,
    which already nets in both win-rate and win/loss magnitude) discounted
    toward zero when the sample is thin — a 3-signal 100%-win-rate strategy
    should not outrank a 400-signal 55%-win-rate one, and this makes that
    explicit and explainable rather than hiding it in a single opaque score."""
    if result.total_signals < 1:
        return -1e9
    all_rets = [r["forward_ret"] for r in result.records]
    avg_ret = sum(all_rets) / len(all_rets) if all_rets else 0.0
    confidence_mult = min(1.0, result.total_signals / _MIN_SAMPLE_FOR_TRUST)
    return avg_ret * confidence_mult


def _run_leaderboard_sync(
    tickers: list[str], timeframes: list[str], strategies: list[StrategyDef],
    *, market: str, exchange: str, groww_token: str, bars: int, forward_bars: int,
    progress_cb: Any = None,
) -> list[dict[str, Any]]:
    cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []

    # Total unit-of-work count for progress reporting: fixed-timeframe and
    # multi-tf strategies run once per ticker; timeframe-flexible strategies
    # run once per ticker per selected timeframe.
    total_units = 0
    for strategy in strategies:
        total_units += len(tickers) * (1 if (strategy.multi_tf or strategy.fixed_timeframe) else len(timeframes))
    done_units = 0

    def _tick(note: str) -> None:
        nonlocal done_units
        done_units += 1
        if progress_cb:
            try:
                progress_cb(done_units / total_units if total_units else 1.0, note)
            except Exception:
                pass

    for ticker in tickers:
        bench_cache: dict[str, Any] = {}
        for strategy in strategies:
            try:
                if strategy.multi_tf:
                    dfs: dict[str, Any] = {}
                    ok = True
                    for tf in strategy.timeframes:
                        df = _fetch_cached(cache, ticker, tf, market=market, exchange=exchange, groww_token=groww_token, bars=bars)
                        if df is None or df.empty:
                            ok = False
                            break
                        dfs[tf] = df
                    if strategy.needs_benchmark:
                        primary_tf = strategy.timeframes[0]
                        bench_sym = bench_cache.setdefault("_symbol", benchmark_ticker_for_market(market))
                        bench_df = _fetch_cached(cache, bench_sym, primary_tf, market=market, exchange=exchange, groww_token=groww_token, bars=bars)
                        if bench_df is not None and not bench_df.empty:
                            dfs["benchmark"] = bench_df
                    if not ok or not dfs:
                        rows.append(_error_row(ticker, strategy, strategy.timeframes[0], "Insufficient data for required timeframe(s)."))
                        _tick(f"{ticker} · {strategy.label}")
                        continue
                    primary_tf = strategy.timeframes[0]
                    signal_fn = strategy.make_signal_fn()
                    result = walk_forward_backtest_multi(
                        dfs, signal_fn, primary_tf=primary_tf,
                        warmup_bars=min(100, max(20, len(dfs[primary_tf]) // 5)),
                        forward_bars=forward_bars,
                        target_atr_mult=strategy.default_target_atr_mult,
                        stop_atr_mult=strategy.default_stop_atr_mult,
                        step=strategy.walk_forward_step,
                    )
                    rows.append(_result_row(ticker, strategy, primary_tf, result))
                    _tick(f"{ticker} · {strategy.label}")
                elif strategy.fixed_timeframe:
                    tf = strategy.timeframes[0]
                    df = _fetch_cached(cache, ticker, tf, market=market, exchange=exchange, groww_token=groww_token, bars=bars)
                    if df is None or df.empty or len(df) < 120:
                        rows.append(_error_row(ticker, strategy, tf, "Insufficient data at this timeframe."))
                    else:
                        signal_fn = strategy.make_signal_fn()
                        result = walk_forward_backtest(
                            df, signal_fn,
                            warmup_bars=min(100, max(20, len(df) // 5)),
                            forward_bars=forward_bars,
                            target_atr_mult=strategy.default_target_atr_mult,
                            stop_atr_mult=strategy.default_stop_atr_mult,
                            step=strategy.walk_forward_step,
                        )
                        rows.append(_result_row(ticker, strategy, tf, result))
                    _tick(f"{ticker} · {strategy.label}")
                else:
                    for tf in timeframes:
                        df = _fetch_cached(cache, ticker, tf, market=market, exchange=exchange, groww_token=groww_token, bars=bars)
                        if df is None or df.empty or len(df) < 120:
                            rows.append(_error_row(ticker, strategy, tf, "Insufficient data at this timeframe."))
                            _tick(f"{ticker} · {strategy.label} · {tf}")
                            continue
                        signal_fn = strategy.make_signal_fn()
                        result = walk_forward_backtest(
                            df, signal_fn,
                            warmup_bars=min(100, max(20, len(df) // 5)),
                            forward_bars=forward_bars,
                            target_atr_mult=strategy.default_target_atr_mult,
                            stop_atr_mult=strategy.default_stop_atr_mult,
                            step=strategy.walk_forward_step,
                        )
                        rows.append(_result_row(ticker, strategy, tf, result))
                        _tick(f"{ticker} · {strategy.label} · {tf}")
            except Exception as exc:
                logger.debug("Leaderboard run failed for %s / %s: %s", ticker, strategy.id, exc)
                rows.append(_error_row(ticker, strategy, timeframes[0] if timeframes else "—", str(exc)[:200]))
                _tick(f"{ticker} · {strategy.label} (error)")

    return rows


def _result_row(ticker: str, strategy: StrategyDef, timeframe: str, result: CalibrationResult) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "strategy_id": strategy.id,
        "strategy_label": strategy.label,
        "hub": strategy.hub,
        "timeframe": timeframe,
        "total_signals": result.total_signals,
        "overall_win_rate_pct": result.overall_win_rate_pct,
        "buckets": [
            {"label": b.label, "n": b.n, "win_rate_pct": b.win_rate_pct, "avg_forward_return_pct": b.avg_forward_return_pct}
            for b in result.buckets
        ],
        "avg_forward_return_pct": round(
            sum(r["forward_ret"] for r in result.records) / len(result.records), 3,
        ) if result.records else None,
        "rank_score": round(_rank_score(result), 4),
        "thin_sample": result.total_signals < _MIN_SAMPLE_FOR_TRUST,
        "notes": strategy.notes,
        "error": None,
    }


def _error_row(ticker: str, strategy: StrategyDef, timeframe: str, error: str) -> dict[str, Any]:
    return {
        "ticker": ticker, "strategy_id": strategy.id, "strategy_label": strategy.label,
        "hub": strategy.hub, "timeframe": timeframe, "total_signals": 0,
        "overall_win_rate_pct": 0.0, "buckets": [], "avg_forward_return_pct": None,
        "rank_score": -1e9, "thin_sample": True, "notes": strategy.notes, "error": error,
    }
