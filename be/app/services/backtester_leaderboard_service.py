"""Backtester — multi-ticker × multi-strategy leaderboard over the FULL
catalog (built-in indicator strategies, Trading Hub engines, TA screeners,
and Strategy Lab presets), reusing BacktestService.run() per combination
rather than re-deriving any engine-specific logic. Save/list/get/delete
reports reuse the same SavedBacktestReport table as the Strategy Lab
leaderboard — both are "saved backtest reports," just from different runs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.models.schemas import BacktestRequest
from app.services.backtest_service import BacktestService
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService
from app.strategies.registry import default_backtest_period, get_strategy_meta

_MIN_TRADES_FOR_TRUST = 10
_CURATED_BARS = 350
_CURATED_FORWARD_BARS = 10


def _rank_score(stats: dict[str, Any]) -> float:
    """Confidence-adjusted total return — discounts thin-sample results
    rather than letting a 1-trade lucky strategy rank artificially high."""
    n = int(stats.get("num_trades") or 0)
    total_ret = float(stats.get("total_return_pct") or 0.0)
    return total_ret * min(1.0, n / _MIN_TRADES_FOR_TRUST)


def _curated_catalog_category() -> dict[str, Any] | None:
    """Command Center strategies from the walk-forward-adapted registry
    (strategy_registry.py) — not duplicated from the 186-strategy generic
    catalog, which has no Command Center entries at all."""
    from app.services.strategy_registry import all_strategies as curated_strategies

    cc = [s for s in curated_strategies() if s.hub == "Command Center"]
    if not cc:
        return None
    return {
        "id": "command_center",
        "label": "Command Center",
        "description": (
            "Walk-forward-calibrated Command Center scanners (Momentum, Weak/Strong, Divergences, "
            "20/200 SMA) — evaluated bar-by-bar with no lookahead, the same harness behind the "
            "Strategy Lab leaderboard."
        ),
        "timeframes": ["1d"],
        "strategy_count": len(cc),
        "strategies": [
            {
                "id": s.id, "name": s.label, "category": "command_center",
                "category_label": "Command Center", "timeframes": s.timeframes,
                "summary": s.notes, "description": s.notes,
                "indicators": [], "entry_rules": [], "exit_rules": [],
                "needs_benchmark": s.needs_benchmark, "min_bars": 120,
            }
            for s in cc
        ],
    }


def _curated_row(ticker: str, strategy: Any, timeframe: str, result: Any) -> dict[str, Any]:
    """Adapt a CalibrationResult (walk-forward harness) into this service's
    row shape, so curated and generic-catalog strategies rank on one table."""
    records = result.records or []
    total_return_pct = round(sum(r["forward_ret"] for r in records), 3) if records else 0.0
    avg_return = round(total_return_pct / len(records), 3) if records else None
    stats = {"num_trades": result.total_signals, "total_return_pct": total_return_pct}
    return {
        "ticker": ticker, "strategy_id": strategy.id, "strategy_label": strategy.label,
        "category": "Command Center", "timeframe": timeframe, "period": f"{_CURATED_BARS} bars (walk-forward)",
        "num_trades": result.total_signals, "win_rate_pct": result.overall_win_rate_pct,
        "total_return_pct": total_return_pct, "max_drawdown_pct": None,
        "avg_return_per_trade_pct": avg_return,
        "rank_score": round(_rank_score(stats), 4),
        "thin_sample": result.total_signals < _MIN_TRADES_FOR_TRUST,
        "summary": strategy.notes or None, "error": None,
    }


def _curated_error_row(ticker: str, strategy: Any, error: str) -> dict[str, Any]:
    return {
        "ticker": ticker, "strategy_id": strategy.id, "strategy_label": strategy.label,
        "category": "Command Center", "timeframe": None, "period": None,
        "num_trades": 0, "win_rate_pct": None, "total_return_pct": None, "max_drawdown_pct": None,
        "avg_return_per_trade_pct": None, "rank_score": -1_000_000_000.0, "thin_sample": True,
        "summary": None, "error": error,
    }


def _result_row(ticker: str, strategy_id: str, meta: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    stats = result.get("stats") or {}
    advanced = stats.get("advanced_report")
    if not advanced and stats.get("trades"):
        from app.strategies.advanced_backtest_report import build_advanced_report

        full = build_advanced_report(
            stats.get("trades") or [],
            period=result.get("period"),
            costs_pct=float(result.get("costs_pct") or stats.get("costs_pct") or 0.0008),
            label=f"{ticker} · {meta.get('name', strategy_id)}",
            context={
                "ticker": ticker,
                "strategy_id": strategy_id,
                "timeframe": result.get("timeframe"),
                "period": result.get("period"),
            },
        )
        advanced = {
            k: full[k]
            for k in (
                "label", "context", "core_performance", "risk_drawdown",
                "risk_adjusted", "execution_costs", "robustness", "assessment",
            )
        }
    elif advanced:
        advanced = {
            **advanced,
            "label": f"{ticker} · {meta.get('name', strategy_id)}",
            "context": {
                "ticker": ticker,
                "strategy_id": strategy_id,
                "timeframe": result.get("timeframe"),
                "period": result.get("period"),
            },
        }

    return {
        "ticker": ticker,
        "strategy_id": strategy_id,
        "strategy_label": meta.get("name", strategy_id),
        "category": meta.get("category_label", ""),
        "timeframe": result.get("timeframe"),
        "period": result.get("period"),
        "num_trades": stats.get("num_trades", 0),
        "win_rate_pct": stats.get("win_rate_pct"),
        "total_return_pct": stats.get("total_return_pct"),
        "max_drawdown_pct": stats.get("max_drawdown_pct"),
        "avg_return_per_trade_pct": stats.get("avg_return_per_trade_pct"),
        "cagr_pct": stats.get("cagr_pct"),
        "payoff_ratio": stats.get("payoff_ratio"),
        "profit_factor": stats.get("profit_factor"),
        "expectancy_pct": stats.get("expectancy_pct"),
        "sharpe_ratio": stats.get("sharpe_ratio"),
        "sortino_ratio": stats.get("sortino_ratio"),
        "calmar_ratio": stats.get("calmar_ratio"),
        "rank_score": round(_rank_score(stats), 4),
        "thin_sample": int(stats.get("num_trades") or 0) < _MIN_TRADES_FOR_TRUST,
        "summary": result.get("summary"),
        "advanced": advanced,
        "error": None,
    }


def _error_row(ticker: str, strategy_id: str, meta: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "ticker": ticker, "strategy_id": strategy_id, "strategy_label": meta.get("name", strategy_id),
        "category": meta.get("category_label", ""), "timeframe": None, "period": None,
        "num_trades": 0, "win_rate_pct": None, "total_return_pct": None, "max_drawdown_pct": None,
        "avg_return_per_trade_pct": None, "rank_score": -1_000_000_000.0, "thin_sample": True,
        "summary": None, "error": error,
    }


class BacktesterLeaderboardService:
    def __init__(self, settings: SettingsService, db: Any = None):
        self.settings = settings
        self.db = db
        self.universe = TickerUniverseService()
        self.backtest_service = BacktestService(settings)

    async def catalog(self) -> dict[str, Any]:
        from app.strategies.registry import list_categories

        categories = list_categories()
        curated = _curated_catalog_category()
        if curated:
            categories.append(curated)
        return {"categories": categories}

    async def _run_curated(
        self, ticker: str, strategy: Any, *, market: str, exchange: str, groww_token: str,
        cache: dict[tuple[str, str], Any], bars: int = _CURATED_BARS, forward_bars: int = _CURATED_FORWARD_BARS,
    ) -> dict[str, Any]:
        from app.market_pulse.calibration_engine import walk_forward_backtest, walk_forward_backtest_multi
        from app.market_pulse.gap_trading import fetch_data_for_gap_scan
        from app.services.strategy_registry import benchmark_ticker_for_market

        def _fetch(tk: str, tf: str) -> Any:
            key = (tk, tf)
            if key not in cache:
                cache[key] = fetch_data_for_gap_scan(tk, tf, market, groww_token, exchange, limit=bars)
            return cache[key]

        if strategy.multi_tf:
            dfs: dict[str, Any] = {}
            for tf in strategy.timeframes:
                df = _fetch(ticker, tf)
                if df is None or df.empty:
                    return _curated_error_row(ticker, strategy, "Insufficient data for required timeframe(s).")
                dfs[tf] = df
            if strategy.needs_benchmark:
                primary_tf = strategy.timeframes[0]
                bench_df = _fetch(benchmark_ticker_for_market(market), primary_tf)
                if bench_df is not None and not bench_df.empty:
                    dfs["benchmark"] = bench_df
            primary_tf = strategy.timeframes[0]
            signal_fn = strategy.make_signal_fn()
            result = walk_forward_backtest_multi(
                dfs, signal_fn, primary_tf=primary_tf,
                warmup_bars=min(100, max(20, len(dfs[primary_tf]) // 5)),
                forward_bars=forward_bars,
                target_atr_mult=strategy.default_target_atr_mult, stop_atr_mult=strategy.default_stop_atr_mult,
                step=strategy.walk_forward_step,
            )
            return _curated_row(ticker, strategy, primary_tf, result)

        tf = strategy.timeframes[0]
        df = _fetch(ticker, tf)
        if df is None or df.empty or len(df) < 120:
            return _curated_error_row(ticker, strategy, "Insufficient data at this timeframe.")
        signal_fn = strategy.make_signal_fn()
        result = walk_forward_backtest(
            df, signal_fn,
            warmup_bars=min(100, max(20, len(df) // 5)), forward_bars=forward_bars,
            target_atr_mult=strategy.default_target_atr_mult, stop_atr_mult=strategy.default_stop_atr_mult,
            step=strategy.walk_forward_step,
        )
        return _curated_row(ticker, strategy, tf, result)

    async def run(
        self,
        tickers: list[str],
        strategy_ids: list[str],
        *,
        asset_class: str = "india",
        timeframe: str | None = None,
        period: str | None = None,
        costs_pct: float | None = None,
        bars: int = _CURATED_BARS,
        forward_bars: int = _CURATED_FORWARD_BARS,
        direction: str = "both",
        progress_cb: Any = None,
    ) -> dict[str, Any]:
        from app.services.strategy_registry import get_strategy as get_curated_strategy

        resolved_tickers = list(self.universe.resolve(asset_class, tickers)) or tickers
        if not resolved_tickers:
            return {"error": "No tickers resolved.", "rows": []}
        if not strategy_ids:
            return {"error": "No strategies selected.", "rows": []}

        total_units = len(resolved_tickers) * len(strategy_ids)
        done_units = 0
        rows: list[dict[str, Any]] = []
        curated_cache: dict[tuple[str, str], Any] = {}
        market, exchange, groww_token = await self.backtest_service._asset_ctx(asset_class)

        for ticker in resolved_tickers:
            for sid in strategy_ids:
                curated = get_curated_strategy(sid)
                if curated:
                    try:
                        rows.append(await self._run_curated(
                            ticker, curated, market=market, exchange=exchange, groww_token=groww_token,
                            cache=curated_cache, bars=bars, forward_bars=forward_bars,
                        ))
                    except Exception as exc:
                        rows.append(_curated_error_row(ticker, curated, str(exc)[:300]))
                    done_units += 1
                    if progress_cb:
                        progress_cb(done_units / total_units, f"{ticker} · {curated.label}")
                    continue

                meta = get_strategy_meta(sid) or {}
                tfs = meta.get("timeframes") or ["1d"]
                tf = timeframe if timeframe in tfs else tfs[0]
                per = period or default_backtest_period(tf)
                req = BacktestRequest(
                    ticker=ticker, strategy=sid, timeframe=tf, period=per,
                    costs_pct=costs_pct if costs_pct is not None else 0.0008,
                    asset_class=asset_class,
                    direction=direction,  # type: ignore[arg-type]
                )
                try:
                    result = await self.backtest_service.run(req)
                    rows.append(_result_row(ticker, sid, meta, result))
                except Exception as exc:
                    rows.append(_error_row(ticker, sid, meta, str(exc)[:300]))
                done_units += 1
                if progress_cb:
                    progress_cb(done_units / total_units, f"{ticker} · {meta.get('name', sid)}")

        rows.sort(key=lambda r: r.get("rank_score", -1e9), reverse=True)

        best_per_ticker: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r.get("error") or int(r.get("num_trades") or 0) < 1:
                continue
            t = r["ticker"]
            if t not in best_per_ticker or r["rank_score"] > best_per_ticker[t]["rank_score"]:
                best_per_ticker[t] = r

        advanced_report = None
        for r in rows:
            if r.get("error") or not r.get("advanced"):
                continue
            if int(r.get("num_trades") or 0) < 1:
                continue
            advanced_report = r["advanced"]
            break

        return {
            "asset_class": asset_class,
            "tickers": resolved_tickers,
            "strategy_count": len(strategy_ids),
            "timeframe": timeframe,
            "period": period,
            "rows": rows,
            "best_per_ticker": list(best_per_ticker.values()),
            "advanced_report": advanced_report,
            "generated_at": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Saved reports — shares the SavedBacktestReport table with the
    # Strategy Lab leaderboard; both are "saved backtest reports."
    # ------------------------------------------------------------------

    async def save_report(self, name: str, payload: dict[str, Any], *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = SavedBacktestReport(
            user_id=user_id,
            name=name.strip()[:200] or f"Backtest report {datetime.utcnow().isoformat()}",
            asset_class=str(payload.get("asset_class", "")),
            tickers=",".join(payload.get("tickers", [])),
            timeframes=str(payload.get("timeframe") or ""),
            payload_json=json.dumps(payload),
            source="backtester_leaderboard",
        )
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        return {"id": report.id, "name": report.name, "created_at": report.created_at.isoformat()}

    @staticmethod
    def _report_summary(payload: dict[str, Any]) -> dict[str, Any]:
        rows = payload.get("rows") or []
        ok_rows = [r for r in rows if isinstance(r, dict) and not r.get("error")]
        best = None
        for r in ok_rows:
            ret = r.get("total_return_pct")
            if ret is None:
                continue
            if best is None or float(ret) > float(best.get("total_return_pct") or -1e18):
                best = r
        best_per = payload.get("best_per_ticker") or []
        return {
            "ticker_count": len(payload.get("tickers") or []),
            "strategy_count": int(payload.get("strategy_count") or 0),
            "combo_count": len(rows),
            "period": payload.get("period"),
            "timeframe": payload.get("timeframe"),
            "best_return_pct": best.get("total_return_pct") if best else None,
            "best_strategy": best.get("strategy_label") if best else None,
            "best_ticker": best.get("ticker") if best else None,
            "best_per_ticker_count": len(best_per),
            "error_count": sum(1 for r in rows if isinstance(r, dict) and r.get("error")),
            "cagr_pct": (best or {}).get("cagr_pct") if best else None,
            "sharpe_ratio": (best or {}).get("sharpe_ratio") if best else None,
            "profit_factor": (best or {}).get("profit_factor") if best else None,
            "assessment_verdict": (
                ((payload.get("advanced_report") or {}).get("assessment") or {}).get("verdict")
            ),
            "assessment_score": (
                ((payload.get("advanced_report") or {}).get("assessment") or {}).get("score")
            ),
        }

    async def list_reports(self, *, user_id: int | None) -> dict[str, Any]:
        from sqlalchemy import select

        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"reports": []}
        stmt = select(SavedBacktestReport).where(
            SavedBacktestReport.source == "backtester_leaderboard"
        ).order_by(SavedBacktestReport.created_at.desc())
        if user_id is not None:
            stmt = stmt.where(SavedBacktestReport.user_id == user_id)
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        reports = []
        for r in rows:
            try:
                payload = json.loads(r.payload_json) if r.payload_json else {}
            except Exception:
                payload = {}
            reports.append({
                "id": r.id,
                "name": r.name,
                "asset_class": r.asset_class,
                "tickers": r.tickers.split(",") if r.tickers else [],
                "timeframes": r.timeframes.split(",") if r.timeframes else [],
                "created_at": r.created_at.isoformat(),
                "summary": self._report_summary(payload if isinstance(payload, dict) else {}),
            })
        return {"reports": reports}
    async def get_report(self, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        if not report or report.source != "backtester_leaderboard" or (user_id is not None and report.user_id not in (None, user_id)):
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
        if not report or report.source != "backtester_leaderboard" or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        await self.db.delete(report)
        await self.db.commit()
        return {"deleted": True}
