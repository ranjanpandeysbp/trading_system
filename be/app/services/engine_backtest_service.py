"""Backtest runners for Trading Hubs and Technical Analysis engines."""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.engine import run_true_backtest
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.indicators import calculate_dynamic_indicators
from app.market_pulse.mtf_scanner_engine import MIN_BARS as MTF_MIN_BARS, analyze_timeframe, normalize_ohlcv
from app.market_pulse.sentiment_screener_engine import analyze_ticker_sentiment
from app.market_pulse.ticker_utils import GROWW_MARKET
from app.models.schemas import BacktestRequest
from app.services.settings_service import SettingsService
from app.services.ta_screener_service import (
    _DEFAULT_TF,
    evaluate_screener_on_df,
    is_actionable_result,
)
from app.strategies.backtest import backtest_signals
from app.strategies.engine_strategies import ENGINE_STRATEGY_META, engine_runner_kind
from app.strategies.preset_strategies import is_preset_strategy, preset_for_id
from app.trading_hubs.registry import build_config, get_section

_PERIOD_DAYS = {
    "7d": 7,
    "30d": 30,
    "60d": 60,
    "90d": 90,
    "180d": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
}

_BARS_PER_DAY: dict[str, float] = {
    "1m": 375,
    "3m": 125,
    "5m": 75,
    "15m": 25,
    "30m": 13,
    "1h": 6.5,
    "4h": 1.6,
    "1d": 1,
    "1wk": 0.2,
}

_BUY_TOKENS = frozenset({
    "1", 1,
    "BUY", "BUY LONG / CALL",
    "KISS BUY", "SWING BUY ENTRY", "CORE INVEST BUY",
    "Buy",
})
_SELL_TOKENS = frozenset({
    "-1", -1,
    "SELL", "KISS SHORT",
    "Sell",
})


def _period_to_limit(period: str, timeframe: str) -> int:
    days = _PERIOD_DAYS.get(period)
    if days is None:
        m = re.match(r"^(\d+)d$", period)
        days = int(m.group(1)) if m else 365
    bars_per_day = _BARS_PER_DAY.get(timeframe, 1)
    if timeframe == "1wk":
        return max(52, int(days / 7) + 10)
    return max(100, int(days * bars_per_day) + 50)


def _stats_from_true_backtest(bt: dict[str, Any]) -> dict[str, Any]:
    metrics = bt.get("metrics") or {}
    trades_df = bt.get("trades")
    trade_rows: list[dict[str, float]] = []
    if trades_df is not None and not trades_df.empty:
        for _, row in trades_df.iterrows():
            trade_rows.append({"pnl_pct": round(float(row["pnl_pct"]), 3)})
    n = int(metrics.get("n_trades") or len(trade_rows))
    total = float(metrics.get("total_return_pct") or 0)
    return {
        "num_trades": n,
        "win_rate_pct": metrics.get("win_rate_pct"),
        "total_return_pct": round(total, 2),
        "avg_return_per_trade_pct": round(total / n, 3) if n else None,
        "max_drawdown_pct": float(metrics.get("max_drawdown_pct") or 0),
        "trades": trade_rows,
    }


def _recent_from_rule_df(df_result: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    if df_result is None or df_result.empty or "buy_signal" not in df_result.columns:
        return []
    hits = df_result[df_result["buy_signal"] == True]  # noqa: E712
    rows: list[dict[str, Any]] = []
    for idx, row in hits.tail(limit).iterrows():
        rows.append({
            "timestamp": str(idx),
            "close": round(float(row["close"]), 2),
            "signal": 1,
            "action": "BUY",
        })
    return rows


def _stats_from_engine_backtest(bt: dict[str, Any]) -> dict[str, Any]:
    if bt.get("error"):
        raise ValueError(str(bt["error"]))

    if "pnl_pct" in bt and "total_trades" in bt:
        num = int(bt["total_trades"])
        total_ret = float(bt["pnl_pct"])
        wr = bt.get("win_rate_pct")
        avg = round(total_ret / num, 3) if num else None
        return {
            "num_trades": num,
            "win_rate_pct": wr,
            "total_return_pct": round(total_ret, 2),
            "avg_return_per_trade_pct": avg,
            "max_drawdown_pct": 0.0,
            "trades": [],
        }

    if "avg_pnl_pct" in bt:
        num = int(bt.get("total_trades", 0))
        avg = float(bt["avg_pnl_pct"])
        wr = bt.get("win_rate_pct")
        return {
            "num_trades": num,
            "win_rate_pct": wr,
            "total_return_pct": round(avg * num, 2) if num else 0.0,
            "avg_return_per_trade_pct": round(avg, 3) if num else None,
            "max_drawdown_pct": 0.0,
            "trades": [],
        }

    raise ValueError("Engine backtest returned no trade statistics.")


def _normalize_signal_column(work: pd.DataFrame) -> pd.DataFrame:
    out = work.copy()
    if "signal" not in out.columns:
        raise ValueError("Strategy frame has no signal column.")

    numeric = pd.to_numeric(out["signal"], errors="coerce")
    if numeric.notna().sum() >= len(out) * 0.5:
        out["signal"] = numeric.fillna(0).astype(int)
        return out

    mapped: list[int] = []
    for val in out["signal"]:
        if val in _BUY_TOKENS or str(val) in _BUY_TOKENS:
            mapped.append(1)
        elif val in _SELL_TOKENS or str(val) in _SELL_TOKENS:
            mapped.append(-1)
        else:
            mapped.append(0)
    out["signal"] = mapped
    return out


def _recent_signals_from_df(result: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    recent = result[result["signal"] != 0].tail(limit)
    rows: list[dict[str, Any]] = []
    for idx, row in recent.iterrows():
        sig = int(row["signal"])
        rows.append({
            "timestamp": str(idx),
            "close": round(float(row["close"]), 2),
            "signal": sig,
            "action": "BUY" if sig > 0 else "SELL",
        })
    return rows


def _rolling_sentiment_backtest(
    df: pd.DataFrame,
    *,
    market: str,
    timeframe: str,
    costs_pct: float,
    warmup: int = 55,
    step: int = 3,
) -> tuple[dict[str, Any], pd.DataFrame, str | None]:
    work = normalize_ohlcv(df)
    if len(work) < warmup + 10:
        raise ValueError(f"Not enough bars for sentiment backtest (need ≥{warmup + 10}).")

    signals = pd.Series(0, index=work.index, dtype=int)
    for i in range(warmup, len(work), step):
        window = work.iloc[: i + 1]
        result = analyze_ticker_sentiment(window, market=market, timeframe=timeframe)
        sig = str(result.get("trade_signal", "WAIT"))
        conf = int(result.get("trade_confidence", 0) or 0)
        if sig == "BUY" and conf >= 50:
            signals.iloc[i] = 1
        elif sig == "SELL" and conf >= 50:
            signals.iloc[i] = -1

    frame = work.copy()
    frame["signal"] = signals.values
    stats = backtest_signals(frame, costs_pct=costs_pct)
    note = "Rolling composite sentiment backtest (bar-by-bar score replay)."
    return stats, frame, note


def _rolling_mtf_backtest(
    df: pd.DataFrame,
    *,
    timeframe: str,
    costs_pct: float,
    warmup: int | None = None,
    step: int = 3,
) -> tuple[dict[str, Any], pd.DataFrame, str | None]:
    work = normalize_ohlcv(df)
    min_bars = warmup or max(MTF_MIN_BARS, 60)
    if len(work) < min_bars + 10:
        raise ValueError(f"Not enough bars for MTF backtest (need ≥{min_bars + 10}).")

    signals = pd.Series(0, index=work.index, dtype=int)
    for i in range(min_bars, len(work), step):
        window = work.iloc[: i + 1]
        result = analyze_timeframe(window, timeframe)
        if not result:
            continue
        composite = float(result.get("composite", 50))
        conf = float(result.get("confidence", 0))
        if composite >= 62 and conf >= 50:
            signals.iloc[i] = 1
        elif composite <= 38 and conf >= 50:
            signals.iloc[i] = -1

    frame = work.copy()
    frame["signal"] = signals.values
    stats = backtest_signals(frame, costs_pct=costs_pct)
    note = "Rolling MTF composite score backtest on selected timeframe."
    return stats, frame, note


class EngineBacktestService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def run(self, request: BacktestRequest) -> dict[str, Any]:
        groww_token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()
        costs_pct = request.costs_pct or await self.settings.get_costs_pct()
        market = GROWW_MARKET
        period = request.period or "2y"
        limit = _period_to_limit(period, request.timeframe)
        kind = engine_runner_kind(request.strategy)

        if is_preset_strategy(request.strategy):
            return await self._run_preset_backtest(
                request, groww_token, exchange, costs_pct, period, limit,
            )
        if kind == "ta_native_bt":
            return await self._run_ta_native_backtest(
                request, groww_token, exchange, costs_pct, period, limit,
            )
        if kind == "rolling_ta_screener":
            return await self._run_rolling_ta_screener_backtest(
                request, groww_token, exchange, costs_pct, period, limit,
            )

        if kind == "analyze_bt":
            return await self._run_analyze_backtest(
                request, market, groww_token, exchange, costs_pct, period, limit,
            )
        if kind == "signal_df":
            return await self._run_signal_df_backtest(
                request, market, groww_token, exchange, costs_pct, period, limit,
            )
        return await self._run_rolling_backtest(
            request, market, groww_token, exchange, costs_pct, period, limit, kind,
        )

    async def _run_preset_backtest(
        self,
        request: BacktestRequest,
        groww_token: str,
        exchange: str,
        costs_pct: float,
        period: str,
        limit: int,
    ) -> dict[str, Any]:
        preset = preset_for_id(request.strategy)
        if not preset:
            raise ValueError(f"Unknown preset strategy: {request.strategy}")

        def _run():
            from app.strategies.preset_strategies import PRESET_ID_TO_MARKET

            mkt = PRESET_ID_TO_MARKET.get(request.strategy, GROWW_MARKET)
            set_groww_token(groww_token)
            tf = request.timeframe or preset.get("recommended_timeframe", "1d")
            df = fetch_data_for_gap_scan(
                request.ticker, tf, mkt, groww_token, exchange, limit=limit,
            )
            df = normalize_ohlcv(df)
            if df.empty or len(df) < 30:
                raise ValueError(f"Insufficient data for {request.ticker} ({tf})")

            df = calculate_dynamic_indicators(df, preset["indicators"])
            sl = float(preset.get("recommended_sl") or 0)
            tp = float(preset.get("recommended_tp") or 0)
            bt = run_true_backtest(
                df,
                preset["entry_rules"],
                preset.get("exit_rules") or [],
                initial_capital=100_000.0,
                commission=float(costs_pct),
                sl_pct=sl,
                tp_pct=tp,
            )
            return bt, tf, len(df)

        bt, tf, bars = await asyncio.to_thread(_run)
        stats = _stats_from_true_backtest(bt)
        df_result = bt.get("df")
        signal_count = 0
        if df_result is not None and not df_result.empty and "buy_signal" in df_result.columns:
            signal_count = int(df_result["buy_signal"].sum())
        recent = _recent_from_rule_df(df_result) if df_result is not None else []

        summary = None
        if stats["num_trades"] == 0:
            summary = f"No completed trades ({period}, {bars} bars). Try a longer period."

        return {
            "ticker": request.ticker,
            "strategy": request.strategy,
            "timeframe": tf,
            "period": period,
            "bars_evaluated": bars,
            "signal_count": signal_count,
            "benchmark_ticker": None,
            "summary": summary,
            "stats": stats,
            "recent_signals": recent,
        }

    async def _run_ta_native_backtest(
        self,
        request: BacktestRequest,
        groww_token: str,
        exchange: str,
        costs_pct: float,
        period: str,
        limit: int,
    ) -> dict[str, Any]:
        market = await self.settings.get_default_market()
        tf = request.timeframe or _DEFAULT_TF.get(request.strategy, "1d")

        def _run():
            set_groww_token(groww_token)
            df = fetch_data_for_gap_scan(
                request.ticker, tf, market, groww_token, exchange, limit=limit,
            )
            df = normalize_ohlcv(df)
            if df.empty:
                raise ValueError(f"No data for {request.ticker}")
            result = evaluate_screener_on_df(
                request.strategy, request.ticker, df,
                market=market, timeframe=tf, groww_token=groww_token, exchange=exchange,
            )
            if result.get("error"):
                raise ValueError(result["error"])
            return result, df, tf

        result, df, tf = await asyncio.to_thread(_run)

        if request.strategy == "zireman_confluence":
            trades_df = result.get("trades")
            if trades_df is None or (hasattr(trades_df, "empty") and trades_df.empty):
                stats = {
                    "num_trades": 0, "win_rate_pct": None, "total_return_pct": 0.0,
                    "avg_return_per_trade_pct": None, "max_drawdown_pct": 0.0, "trades": [],
                }
            else:
                if not isinstance(trades_df, pd.DataFrame):
                    trades_df = pd.DataFrame(trades_df)
                pnl_col = "pnl_pct" if "pnl_pct" in trades_df.columns else "return_pct"
                trade_rows = [
                    {"pnl_pct": round(float(r[pnl_col]), 3)}
                    for _, r in trades_df.iterrows()
                    if pnl_col in trades_df.columns
                ]
                wins = trades_df[trades_df[pnl_col] > 0] if pnl_col in trades_df.columns else trades_df.iloc[0:0]
                n = len(trade_rows)
                total = sum(t["pnl_pct"] for t in trade_rows)
                stats = {
                    "num_trades": n,
                    "win_rate_pct": round(len(wins) / n * 100, 2) if n else None,
                    "total_return_pct": round(total, 2),
                    "avg_return_per_trade_pct": round(total / n, 3) if n else None,
                    "max_drawdown_pct": 0.0,
                    "trades": trade_rows,
                }
            signal_count = int(result.get("signal_count") or stats["num_trades"])
        else:
            bt = result.get("backtest") or {}
            stats = _stats_from_engine_backtest({
                "total_trades": bt.get("trades", 0),
                "pnl_pct": bt.get("total_pnl_pct", bt.get("pnl_pct", 0)),
                "win_rate_pct": bt.get("win_rate", bt.get("win_rate_pct")),
            })
            signal_count = int(bt.get("trades") or stats["num_trades"])

        recent = []
        for item in (result.get("recent_trades") or [])[-10:]:
            recent.append({
                "timestamp": str(item.get("entry_time", item.get("time", ""))),
                "close": float(item.get("entry", item.get("close", 0)) or 0),
                "signal": 1,
                "action": "BUY",
            })

        return {
            "ticker": request.ticker,
            "strategy": request.strategy,
            "timeframe": tf,
            "period": period,
            "bars_evaluated": len(df),
            "signal_count": signal_count,
            "benchmark_ticker": None,
            "summary": None if stats["num_trades"] else "No trades in engine backtest for this period.",
            "stats": stats,
            "recent_signals": recent,
        }

    async def _run_rolling_ta_screener_backtest(
        self,
        request: BacktestRequest,
        groww_token: str,
        exchange: str,
        costs_pct: float,
        period: str,
        limit: int,
    ) -> dict[str, Any]:
        market = await self.settings.get_default_market()
        meta = ENGINE_STRATEGY_META.get(request.strategy, {})
        tf = request.timeframe or meta.get("default_tf") or _DEFAULT_TF.get(request.strategy, "15m")
        min_bars = int(meta.get("min_bars", 80))
        warmup = max(min_bars, 60)

        def _run():
            set_groww_token(groww_token)
            df = fetch_data_for_gap_scan(
                request.ticker, tf, market, groww_token, exchange, limit=limit,
            )
            df = normalize_ohlcv(df)
            if len(df) < warmup + 10:
                raise ValueError(f"Not enough bars (need ≥{warmup + 10}). Try a longer period.")

            signals = pd.Series(0, index=df.index, dtype=int)
            step = 5 if len(df) > 300 else 3
            for i in range(warmup, len(df), step):
                window = df.iloc[: i + 1]
                row = evaluate_screener_on_df(
                    request.strategy, request.ticker, window,
                    market=market, timeframe=tf,
                    groww_token=groww_token, exchange=exchange,
                )
                if is_actionable_result(row):
                    verdict = str(row.get("verdict", row.get("signal", ""))).upper()
                    if "SELL" in verdict or "SHORT" in verdict or row.get("direction") == "SHORT":
                        signals.iloc[i] = -1
                    else:
                        signals.iloc[i] = 1

            frame = df.copy()
            frame["signal"] = signals.values
            stats = backtest_signals(frame, costs_pct=costs_pct)
            return frame, stats

        frame, stats = await asyncio.to_thread(_run)
        signal_count = int((frame["signal"] != 0).sum())
        recent_signals = _recent_signals_from_df(frame)
        note = "Rolling TA screener replay (bar-by-bar engine evaluation)."

        summary = note
        if signal_count == 0:
            summary += " No actionable signals in selected period."
        elif stats["num_trades"] == 0:
            summary += " Signals found but no completed trades."

        return {
            "ticker": request.ticker,
            "strategy": request.strategy,
            "timeframe": tf,
            "period": period,
            "bars_evaluated": len(frame),
            "signal_count": signal_count,
            "benchmark_ticker": None,
            "summary": summary,
            "stats": stats,
            "recent_signals": recent_signals,
        }

    async def _run_analyze_backtest(
        self,
        request: BacktestRequest,
        market: str,
        groww_token: str,
        exchange: str,
        costs_pct: float,
        period: str,
        limit: int,
    ) -> dict[str, Any]:
        section = get_section(request.strategy)
        if not section:
            raise ValueError(f"Unknown hub strategy: {request.strategy}")

        mod = section["module"]
        cfg = build_config(section["config_cls"], None)

        if request.strategy == "swing_trading_st_supertrend":
            if request.timeframe == "1wk":
                cfg.mode = mod.MODE_PYRAMID
            else:
                cfg.mode = mod.MODE_SWING

        allowed_tfs = ENGINE_STRATEGY_META.get(request.strategy, {}).get("timeframes", [request.timeframe])
        if hasattr(cfg, "execution_tf") and request.timeframe in allowed_tfs:
            cfg.execution_tf = request.timeframe

        sig = inspect.signature(mod.analyze_ticker)
        kwargs: dict[str, Any] = {
            "ticker": request.ticker,
            "market": market,
            "cfg": cfg,
            "groww_token": groww_token,
            "exchange": exchange,
        }
        if "run_bt" in sig.parameters:
            kwargs["run_bt"] = True

        result = mod.analyze_ticker(**kwargs)
        if result.get("error"):
            raise ValueError(result["error"])

        bt = result.get("backtest")
        if not bt:
            raise ValueError("Engine did not return backtest statistics.")

        stats = _stats_from_engine_backtest(bt)
        bars = int(result.get("bars", bt.get("bars", 0)) or 0)
        signal_count = int(result.get("backtest", {}).get("total_trades", stats["num_trades"]))

        summary = None
        if stats["num_trades"] == 0:
            summary = (
                f"No completed trades in engine backtest ({period}, {bars} bars). "
                "Try a longer period or different timeframe."
            )

        recent = []
        for item in (result.get("signal_history") or [])[-10:]:
            sig_label = str(item.get("signal", ""))
            action = "BUY" if "BUY" in sig_label.upper() or sig_label == "1" else (
                "SELL" if "SELL" in sig_label.upper() or "SHORT" in sig_label.upper() else "HOLD"
            )
            if action == "HOLD":
                continue
            recent.append({
                "timestamp": str(item.get("time", "")),
                "close": float(item.get("close", 0)),
                "signal": 1 if action == "BUY" else -1,
                "action": action,
            })

        return {
            "ticker": request.ticker,
            "strategy": request.strategy,
            "timeframe": request.timeframe,
            "period": period,
            "bars_evaluated": bars,
            "signal_count": signal_count,
            "benchmark_ticker": None,
            "summary": summary,
            "stats": stats,
            "recent_signals": recent,
        }

    async def _run_signal_df_backtest(
        self,
        request: BacktestRequest,
        market: str,
        groww_token: str,
        exchange: str,
        costs_pct: float,
        period: str,
        limit: int,
    ) -> dict[str, Any]:
        section = get_section(request.strategy)
        if not section:
            raise ValueError(f"Unknown hub strategy: {request.strategy}")

        mod = section["module"]
        cfg = build_config(section["config_cls"], None)
        if hasattr(cfg, "execution_tf"):
            cfg.execution_tf = request.timeframe

        work = await self._build_signal_frame(
            request.strategy, mod, cfg, request.ticker, market, groww_token, exchange, limit,
        )
        if work.empty:
            raise ValueError(f"No data for {request.ticker} ({request.timeframe}).")

        work = _normalize_signal_column(work)
        signal_count = int((work["signal"] != 0).sum())
        stats = backtest_signals(work, costs_pct=costs_pct)
        recent_signals = _recent_signals_from_df(work)

        summary = None
        if signal_count == 0:
            summary = f"No buy/sell signals in period ({period}, {len(work)} bars)."
        elif stats["num_trades"] == 0:
            summary = "Signals found but no completed round-trip trades in this period."

        return {
            "ticker": request.ticker,
            "strategy": request.strategy,
            "timeframe": request.timeframe,
            "period": period,
            "bars_evaluated": len(work),
            "signal_count": signal_count,
            "benchmark_ticker": None,
            "summary": summary,
            "stats": stats,
            "recent_signals": recent_signals,
        }

    async def _build_signal_frame(
        self,
        strategy_id: str,
        mod: Any,
        cfg: Any,
        ticker: str,
        market: str,
        groww_token: str,
        exchange: str,
        limit: int,
    ) -> pd.DataFrame:
        if strategy_id == "intraday_vwap_fade":
            df = mod.fetch_exec_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange)
            return mod.backtest_vwap_fade_strategy(df, cfg, market)

        if strategy_id == "intraday_fib_945":
            exec_df = mod.fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
            opening = mod.get_opening_30m_candle(exec_df)
            if not opening:
                intra = mod.fetch_intraday_for_opening_range(
                    ticker, market, groww_token=groww_token, exchange=exchange,
                )
                opening = mod.get_opening_30m_candle(intra) if not intra.empty else None
            if not opening:
                raise ValueError("Could not build 9:15–9:45 opening range for Fib 9:45 backtest.")
            return mod.implement_fib945_strategy(exec_df, opening, cfg)

        if strategy_id == "scalp_rectangle":
            from app.market_pulse.gap_trading import fetch_ohlcv_yfinance

            is_crypto = "CoinDCX" in market
            df = fetch_data_for_gap_scan(
                ticker, cfg.execution_tf, market, groww_token, exchange, limit=limit,
            )
            df = normalize_ohlcv(df)
            if df.empty:
                df = normalize_ohlcv(
                    fetch_ohlcv_yfinance(
                        ticker, cfg.execution_tf, is_crypto=is_crypto, limit=limit, market=market,
                    ),
                )
            work, _state = mod.implement_rectangle_strategy(
                df, swing_window=cfg.swing_window, rr_ratio=cfg.rr_ratio,
            )
            return work

        if strategy_id == "smc_cisd":
            ltf = mod.fetch_tf_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange)
            work, _setups = mod.implement_cisd_strategy(ltf, cfg)
            return work

        if strategy_id == "smc_weekly_sweep_cisd":
            daily = mod._fetch_daily(
                ticker, market, groww_token=groww_token, exchange=exchange, limit=cfg.daily_lookback,
            )
            weekly = mod.build_weekly_from_daily(daily)
            levels = mod.calculate_weekly_levels(weekly)
            ltf = mod.fetch_ltf_data(
                ticker, cfg.execution_tf, market,
                groww_token=groww_token, exchange=exchange, limit=cfg.ltf_lookback,
            )
            work, _setups = mod.implement_weekly_sweep_cisd(ltf, levels, cfg)
            return work

        if strategy_id == "smc_golden_bullet":
            htf = mod.fetch_tf_data(ticker, cfg.htf_tf, market, groww_token=groww_token, exchange=exchange)
            ltf = mod.fetch_tf_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange)
            bias = mod._htf_bias(htf, cfg.swing_window)
            work, _state = mod.golden_bullet_strategy(
                ltf,
                swing_window=cfg.swing_window,
                rr_ratio=cfg.rr_ratio,
                require_killzone=cfg.require_killzone,
                htf_bias=bias.get("bias", "NEUTRAL"),
                require_htf_alignment=cfg.require_htf_alignment,
            )
            return work

        raise ValueError(f"No signal-frame builder for {strategy_id}")

    async def _run_rolling_backtest(
        self,
        request: BacktestRequest,
        market: str,
        groww_token: str,
        exchange: str,
        costs_pct: float,
        period: str,
        limit: int,
        kind: str,
    ) -> dict[str, Any]:
        df = fetch_data_for_gap_scan(
            request.ticker, request.timeframe, market, groww_token, exchange, limit=limit,
        )
        df = normalize_ohlcv(df)
        if df.empty:
            raise ValueError(f"No data for {request.ticker} (period={period}, timeframe={request.timeframe})")

        min_bars = max(80, MTF_MIN_BARS if kind == "rolling_mtf" else 55)
        if len(df) < min_bars:
            raise ValueError(
                f"Not enough bars: got {len(df)}, need at least {min_bars}. Try a longer period."
            )

        note: str | None = None
        if kind == "rolling_mtf":
            stats, frame, note = _rolling_mtf_backtest(df, timeframe=request.timeframe, costs_pct=costs_pct)
        else:
            stats, frame, note = _rolling_sentiment_backtest(
                df, market=market, timeframe=request.timeframe, costs_pct=costs_pct,
            )

        signal_count = int((frame["signal"] != 0).sum())
        recent_signals = _recent_signals_from_df(frame)

        summary = note
        if signal_count == 0:
            summary = (summary + " " if summary else "") + "No actionable signals in selected period."
        elif stats["num_trades"] == 0:
            summary = (summary + " " if summary else "") + "Signals found but no completed trades."

        return {
            "ticker": request.ticker,
            "strategy": request.strategy,
            "timeframe": request.timeframe,
            "period": period,
            "bars_evaluated": len(frame),
            "signal_count": signal_count,
            "benchmark_ticker": None,
            "summary": summary,
            "stats": stats,
            "recent_signals": recent_signals,
        }
