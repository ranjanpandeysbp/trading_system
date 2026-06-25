"""
swing_trading_st_supertrend_engine.py
------------------------------------
SuperTrend (10, 3) + SMA 10 strategy — swing (daily) and pyramiding (weekly).

Video playbook: SMA/SuperTrend crossover entries, SMA trail exit (swing),
SuperTrend structural exit + pyramid adds (long-term).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_supertrend
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.swing_trading_st_shared import (
    HOLD_SUPERTREND_PYRAMID,
    HOLD_SUPERTREND_SWING,
    enrich_st_live,
)
from app.trading_hubs.weekly_helpers import _resample_weekly

logger = logging.getLogger(__name__)

YOUTUBE_ST_SUPERTREND_URL = "http://www.youtube.com/watch?v=JuiWfkJukmc"

MODE_SWING = "swing_daily"
MODE_PYRAMID = "pyramid_weekly"

SIGNAL_SWING_BUY = "SWING BUY ENTRY"
SIGNAL_SWING_EXIT = "SWING EXIT"
SIGNAL_CORE_BUY = "CORE INVEST BUY"
SIGNAL_PYRAMID = "PYRAMID ADD QUANTITY"
SIGNAL_INVEST_EXIT = "INVESTMENT EXIT (STOP LOSS)"
SIGNAL_HOLD = "Hold/Neutral"


@dataclass
class STSuperTrendConfig:
    mode: str = MODE_SWING
    sma_period: int = 10
    st_period: int = 10
    st_multiplier: float = 3.0
    daily_lookback: int = 504
    weekly_lookback: int = 260
    min_bars: int = 30
    take_confidence_threshold: float = 58.0
    tp_risk_multiple: float = 2.0


def _st_cols(cfg: STSuperTrendConfig) -> tuple[str, str]:
    return (
        f"supertrend_{cfg.st_period}_{cfg.st_multiplier}",
        f"supertrend_dir_{cfg.st_period}_{cfg.st_multiplier}",
    )


def compute_strategy_frame(df: pd.DataFrame, cfg: STSuperTrendConfig) -> pd.DataFrame:
    """Add SMA, SuperTrend, trend, and historical signal column."""
    work = normalize_ohlcv(df)
    if work.empty:
        return work

    st_line_col, st_dir_col = _st_cols(cfg)
    work = add_supertrend(work, cfg.st_period, cfg.st_multiplier)
    work["sma_10"] = work["close"].rolling(cfg.sma_period).mean()
    work["supertrend"] = work[st_line_col]
    work["trend"] = work[st_dir_col]
    work["signal"] = SIGNAL_HOLD

    for i in range(1, len(work)):
        sma_now = work["sma_10"].iloc[i]
        sma_prev = work["sma_10"].iloc[i - 1]
        st_now = work["supertrend"].iloc[i]
        st_prev = work["supertrend"].iloc[i - 1]
        close_now = work["close"].iloc[i]
        close_prev = work["close"].iloc[i - 1]
        trend_now = int(work["trend"].iloc[i])
        trend_prev = int(work["trend"].iloc[i - 1])

        if any(pd.isna(x) for x in (sma_now, st_now, close_now)):
            continue

        if cfg.mode == MODE_SWING:
            if (
                sma_now > st_now
                and (pd.isna(sma_prev) or sma_prev <= st_prev)
                and trend_now == 1
            ):
                work.iloc[i, work.columns.get_loc("signal")] = SIGNAL_SWING_BUY
            elif close_now < sma_now and (pd.isna(close_prev) or close_prev >= sma_prev):
                work.iloc[i, work.columns.get_loc("signal")] = SIGNAL_SWING_EXIT
        else:
            if trend_now == 1 and trend_prev == -1:
                work.iloc[i, work.columns.get_loc("signal")] = SIGNAL_CORE_BUY
            elif (
                trend_now == 1
                and close_now > sma_now
                and (pd.isna(close_prev) or close_prev <= sma_prev)
            ):
                work.iloc[i, work.columns.get_loc("signal")] = SIGNAL_PYRAMID
            elif trend_now == -1 and trend_prev == 1:
                work.iloc[i, work.columns.get_loc("signal")] = SIGNAL_INVEST_EXIT

    return work


def _signal_history(work: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(len(work) - 1, -1, -1):
        sig = work["signal"].iloc[i]
        if sig == SIGNAL_HOLD:
            continue
        ts = work.index[i]
        rows.append({
            "date": ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts),
            "signal": sig,
            "close": round(float(work["close"].iloc[i]), 4),
            "sma_10": round(float(work["sma_10"].iloc[i]), 4) if pd.notna(work["sma_10"].iloc[i]) else None,
            "supertrend": round(float(work["supertrend"].iloc[i]), 4) if pd.notna(work["supertrend"].iloc[i]) else None,
            "trend": "Bull" if int(work["trend"].iloc[i]) == 1 else "Bear",
        })
        if len(rows) >= limit:
            break
    return rows


def _backtest_swing(work: pd.DataFrame) -> dict[str, Any]:
    in_pos = False
    entry = 0.0
    trades: list[float] = []
    for _, row in work.iterrows():
        sig = row["signal"]
        if sig == SIGNAL_SWING_BUY:
            in_pos = True
            entry = float(row["close"])
        elif sig == SIGNAL_SWING_EXIT and in_pos:
            exit_px = float(row["close"])
            trades.append((exit_px - entry) / entry * 100 if entry else 0.0)
            in_pos = False
    if not trades:
        return {"total_trades": 0, "win_rate_pct": 0.0, "avg_pnl_pct": 0.0}
    wins = sum(1 for t in trades if t > 0)
    return {
        "total_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 1),
        "avg_pnl_pct": round(float(np.mean(trades)), 2),
    }


def _backtest_pyramid(work: pd.DataFrame) -> dict[str, Any]:
    in_core = False
    entry = 0.0
    trades: list[float] = []
    pyramid_count = 0
    for _, row in work.iterrows():
        sig = row["signal"]
        if sig == SIGNAL_CORE_BUY:
            in_core = True
            entry = float(row["close"])
            pyramid_count = 0
        elif sig == SIGNAL_PYRAMID and in_core:
            pyramid_count += 1
        elif sig == SIGNAL_INVEST_EXIT and in_core:
            exit_px = float(row["close"])
            trades.append((exit_px - entry) / entry * 100 if entry else 0.0)
            in_core = False
    return {
        "total_trades": len(trades),
        "win_rate_pct": round(sum(1 for t in trades if t > 0) / len(trades) * 100, 1) if trades else 0.0,
        "avg_pnl_pct": round(float(np.mean(trades)), 2) if trades else 0.0,
        "pyramid_signals": int((work["signal"] == SIGNAL_PYRAMID).sum()),
    }


def evaluate_live_signal(work: pd.DataFrame, cfg: STSuperTrendConfig) -> dict[str, Any]:
    if work.empty or len(work) < cfg.min_bars:
        return {"signal": "NO_DATA"}

    row = work.iloc[-1]
    latest_sig = str(row["signal"])
    trend = int(row["trend"]) if pd.notna(row["trend"]) else 0
    close = float(row["close"])
    sma = float(row["sma_10"]) if pd.notna(row["sma_10"]) else close
    st = float(row["supertrend"]) if pd.notna(row["supertrend"]) else close

    reasons: list[str] = []
    conf = 30.0
    direction = "WAIT"
    verdict = "WAIT"
    action = latest_sig if latest_sig != SIGNAL_HOLD else "NONE"

    actionable = {
        SIGNAL_SWING_BUY,
        SIGNAL_CORE_BUY,
        SIGNAL_PYRAMID,
        SIGNAL_SWING_EXIT,
        SIGNAL_INVEST_EXIT,
    }
    take = latest_sig in actionable

    if cfg.mode == MODE_SWING:
        if latest_sig == SIGNAL_SWING_BUY:
            direction = "LONG"
            verdict = "TAKE LONG"
            conf += 35
            reasons.append("SMA 10 crossed above SuperTrend — swing entry")
        elif latest_sig == SIGNAL_SWING_EXIT:
            direction = "EXIT"
            verdict = "EXIT LONG"
            conf += 30
            reasons.append("Close crossed below SMA 10 — swing exit")
        elif trend == 1 and close > sma and sma > st:
            direction = "LONG"
            verdict = "HOLD LONG"
            conf += 20
            reasons.append("Bullish SuperTrend — price above SMA 10")
        elif trend == 1 and close > st:
            direction = "LONG"
            verdict = "WATCH LONG"
            conf += 12
            reasons.append("Uptrend active — watch for SMA cross above SuperTrend")
        else:
            reasons.append("No bullish swing alignment")
    else:
        if latest_sig == SIGNAL_CORE_BUY:
            direction = "LONG"
            verdict = "CORE BUY"
            conf += 38
            reasons.append("SuperTrend flipped bullish — core investment entry")
        elif latest_sig == SIGNAL_PYRAMID:
            direction = "LONG"
            verdict = "PYRAMID ADD"
            conf += 32
            reasons.append("Close reclaimed SMA 10 while SuperTrend still bullish")
        elif latest_sig == SIGNAL_INVEST_EXIT:
            direction = "EXIT"
            verdict = "STRUCTURAL EXIT"
            conf += 35
            reasons.append("SuperTrend broke down — long-term stop")
        elif trend == 1:
            direction = "LONG"
            verdict = "HOLD CORE"
            conf += 22
            reasons.append("Weekly SuperTrend bullish — hold / watch pyramid zones")
            if close <= sma * 1.02 and close >= sma * 0.98:
                conf += 10
                reasons.append("Price near SMA 10 — potential pyramid add zone")
        else:
            reasons.append("Weekly SuperTrend bearish — stay flat")

    if trend == 1:
        conf += 8
        reasons.append("SuperTrend direction: bullish")
    elif trend == -1:
        conf -= 5
        reasons.append("SuperTrend direction: bearish")

    conf = max(20.0, min(90.0, conf))
    if take and conf < cfg.take_confidence_threshold:
        take = False

    if direction == "EXIT":
        sl_pct = max(1.0, abs(close - st) / close * 100)
        tp_pct = sl_pct
        entry = close
        stop = st
        target = close
    else:
        stop = min(st, sma) if direction == "LONG" else st
        sl_pct = max(0.8, (close - stop) / close * 100) if close > 0 and stop < close else 3.0
        tp_pct = max(sl_pct * cfg.tp_risk_multiple, sl_pct + 1.5)
        entry = close
        target = close * (1 + tp_pct / 100)

    hold_duration = HOLD_SUPERTREND_PYRAMID if cfg.mode == MODE_PYRAMID else HOLD_SUPERTREND_SWING
    tf = "1wk" if cfg.mode == MODE_PYRAMID else "1d"

    plan = make_trade_plan(
        direction=direction if take and direction != "EXIT" else "—",
        timeframe=tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing" if cfg.mode == MODE_SWING else "position",
        exit_rule="; ".join(reasons[:2]) if reasons else "SuperTrend + SMA",
        max_hold_exit=f"Exit if TP not reached within {hold_duration.split('(')[0].strip()}.",
    )

    return enrich_st_live({
        "signal": action,
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold_duration,
        "rr_ratio": round(tp_pct / sl_pct, 2) if sl_pct > 0 else None,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "sma_10": round(sma, 6),
        "supertrend": round(st, 6),
        "trend": "Bullish" if trend == 1 else "Bearish",
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration},
    }, hold_duration=hold_duration)


def fetch_ohlc_for_mode(
    ticker: str,
    market: str,
    cfg: STSuperTrendConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    limit = cfg.daily_lookback if cfg.mode == MODE_SWING else cfg.weekly_lookback * 5

    daily = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    daily = normalize_ohlcv(daily)
    if daily.empty or len(daily) < cfg.min_bars:
        daily = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market),
        )

    if cfg.mode == MODE_SWING:
        return daily

    weekly = _resample_weekly(daily)
    if weekly.empty or len(weekly) < cfg.min_bars:
        wk = fetch_data_for_gap_scan(ticker, "1w", market, groww_token, exchange, limit=cfg.weekly_lookback)
        weekly = normalize_ohlcv(wk)
    return weekly


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: STSuperTrendConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or STSuperTrendConfig()
    ohlc = fetch_ohlc_for_mode(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if ohlc.empty or len(ohlc) < cfg.min_bars:
        tf = "weekly" if cfg.mode == MODE_PYRAMID else "daily"
        return {"ticker": ticker, "error": f"Insufficient {tf} OHLCV data."}

    work = compute_strategy_frame(ohlc, cfg)
    live = evaluate_live_signal(work, cfg)
    bt = _backtest_pyramid(work) if cfg.mode == MODE_PYRAMID else _backtest_swing(work)

    return {
        "ticker": ticker,
        "market": market,
        "mode": cfg.mode,
        "bars": len(work),
        "timeframe": "1wk" if cfg.mode == MODE_PYRAMID else "1d",
        "last_close": float(work["close"].iloc[-1]),
        "signal_history": _signal_history(work),
        "live": live,
        "backtest": bt,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: STSuperTrendConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or STSuperTrendConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entry_signals = {
        SIGNAL_SWING_BUY,
        SIGNAL_CORE_BUY,
        SIGNAL_PYRAMID,
        SIGNAL_SWING_EXIT,
        SIGNAL_INVEST_EXIT,
    }
    entries = [
        r for r in results
        if not r.get("error")
        and (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("signal") in entry_signals
    ]
    holds = [
        r for r in results
        if not r.get("error")
        and (r.get("live") or {}).get("verdict") in ("HOLD LONG", "HOLD CORE", "WATCH LONG")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    holds.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "mode": cfg.mode,
        "results": results,
        "entries": entries,
        "holds": holds,
        "entry_count": len(entries),
        "hold_count": len(holds),
    }
