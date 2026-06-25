"""
swing_trading_st_kiss_engine.py
--------------------------------
KISS (Keep It Swing Systematic) — Dhan / Animesh Ke masterclass.

Weekly Heikin Ashi trend filter + 1h/4h execution:
  55 EMA High-Low band · Signal MA Dhan (55 EMA) · MACD zero-line cross.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.swing_trading_st_shared import HOLD_KISS_1H, HOLD_KISS_4H, enrich_st_live
from app.trading_hubs.weekly_helpers import _resample_weekly

logger = logging.getLogger(__name__)

YOUTUBE_ST_KISS_URL = "http://www.youtube.com/watch?v=2YBmiyVmNNw"

EXEC_1H = "1h"
EXEC_4H = "4h"

SIGNAL_BUY = "KISS BUY"
SIGNAL_SHORT = "KISS SHORT"
SIGNAL_HOLD = "Hold/Neutral"


@dataclass
class KISSConfig:
    execution_tf: str = EXEC_1H
    ema_period: int = 55
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rr_ratio: float = 3.0
    risk_per_trade_pct: float = 1.5
    swing_lookback: int = 15
    take_confidence_threshold: float = 62.0
    daily_lookback: int = 800
    min_exec_bars: int = 80


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Convert OHLC to Heikin Ashi candles."""
    work = normalize_ohlcv(df)
    if work.empty:
        return work

    ha_close = (work["open"] + work["high"] + work["low"] + work["close"]) / 4
    ha_open = np.zeros(len(work))
    ha_open[0] = (work["open"].iloc[0] + work["close"].iloc[0]) / 2
    for i in range(1, len(work)):
        ha_open[i] = (ha_open[i - 1] + ha_close.iloc[i - 1]) / 2

    out = work.copy()
    out["ha_open"] = ha_open
    out["ha_close"] = ha_close
    out["ha_high"] = out[["high", "ha_open", "ha_close"]].max(axis=1)
    out["ha_low"] = out[["low", "ha_open", "ha_close"]].min(axis=1)
    return out


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    work = normalize_ohlcv(df)
    return work.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()


def _attach_weekly_ha_filter(exec_df: pd.DataFrame, weekly_ha: pd.DataFrame) -> pd.DataFrame:
    """Map previous week's closed HA trend (green=1, red=-1) onto execution bars."""
    exec_df = exec_df.copy()
    wk = weekly_ha.copy()
    wk["weekly_trend"] = np.where(wk["ha_close"] > wk["ha_open"], 1, -1)
    wk["weekly_trend_filter"] = wk["weekly_trend"].shift(1)
    wk["week_id"] = wk.index.to_period("W").astype(str)
    exec_df["week_id"] = exec_df.index.to_period("W").astype(str)
    levels = wk.set_index("week_id")[["weekly_trend", "weekly_trend_filter"]]
    merged = exec_df.join(levels, on="week_id")
    merged["weekly_trend_filter"] = merged["weekly_trend_filter"].ffill()
    merged["weekly_trend"] = merged["weekly_trend"].ffill()
    return merged


def implement_kiss_strategy(exec_df: pd.DataFrame, weekly_df: pd.DataFrame, cfg: KISSConfig) -> pd.DataFrame:
    """Full KISS indicator + signal frame on execution timeframe."""
    execution_df = normalize_ohlcv(exec_df)
    if execution_df.empty or len(execution_df) < cfg.min_exec_bars:
        return pd.DataFrame()

    weekly_ha = calculate_heikin_ashi(weekly_df)
    execution_df = _attach_weekly_ha_filter(execution_df, weekly_ha)

    p = cfg.ema_period
    execution_df["ema_high"] = execution_df["high"].ewm(span=p, adjust=False).mean()
    execution_df["ema_low"] = execution_df["low"].ewm(span=p, adjust=False).mean()
    execution_df["signal_ma_dhan"] = execution_df["close"].ewm(span=p, adjust=False).mean()
    execution_df["ma_dhan_state"] = np.where(
        execution_df["close"] > execution_df["signal_ma_dhan"], 1, -1,
    )

    ema_fast = execution_df["close"].ewm(span=cfg.macd_fast, adjust=False).mean()
    ema_slow = execution_df["close"].ewm(span=cfg.macd_slow, adjust=False).mean()
    execution_df["macd"] = ema_fast - ema_slow
    execution_df["macd_signal"] = execution_df["macd"].ewm(span=cfg.macd_signal, adjust=False).mean()

    execution_df["zone"] = np.where(
        execution_df["close"] > execution_df["ema_high"],
        "bullish",
        np.where(execution_df["close"] < execution_df["ema_low"], "bearish", "neutral"),
    )

    execution_df["signal"] = SIGNAL_HOLD
    execution_df["signal_code"] = 0

    buy_cond = (
        (execution_df["weekly_trend_filter"] == 1)
        & (execution_df["close"] > execution_df["ema_high"])
        & (execution_df["ma_dhan_state"] == 1)
        & (execution_df["macd"] > 0)
        & (execution_df["macd"].shift(1) <= 0)
    )
    short_cond = (
        (execution_df["weekly_trend_filter"] == -1)
        & (execution_df["close"] < execution_df["ema_low"])
        & (execution_df["ma_dhan_state"] == -1)
        & (execution_df["macd"] < 0)
        & (execution_df["macd"].shift(1) >= 0)
    )

    execution_df.loc[buy_cond, "signal"] = SIGNAL_BUY
    execution_df.loc[buy_cond, "signal_code"] = 1
    execution_df.loc[short_cond, "signal"] = SIGNAL_SHORT
    execution_df.loc[short_cond, "signal_code"] = -1

    return execution_df


def _structural_stop(work: pd.DataFrame, idx: int, direction: str, lookback: int) -> float:
    window = work.iloc[max(0, idx - lookback): idx + 1]
    if direction == "LONG":
        return float(window["low"].min())
    return float(window["high"].max())


def _signal_history(work: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(len(work) - 1, -1, -1):
        sig = work["signal"].iloc[i]
        if sig == SIGNAL_HOLD:
            continue
        ts = work.index[i]
        rows.append({
            "date": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "signal": sig,
            "close": round(float(work["close"].iloc[i]), 4),
            "zone": work["zone"].iloc[i],
            "weekly_ha": "Green" if work["weekly_trend_filter"].iloc[i] == 1 else "Red",
        })
        if len(rows) >= limit:
            break
    return rows


def _backtest_kiss(work: pd.DataFrame, cfg: KISSConfig) -> dict[str, Any]:
    trades: list[float] = []
    in_pos = False
    direction = ""
    entry = 0.0
    stop = 0.0
    target = 0.0

    for i in range(len(work)):
        row = work.iloc[i]
        sig = row["signal"]
        close = float(row["close"])

        if sig == SIGNAL_BUY and not in_pos:
            in_pos = True
            direction = "LONG"
            entry = close
            stop = _structural_stop(work, i, "LONG", cfg.swing_lookback)
            risk = entry - stop
            target = entry + risk * cfg.rr_ratio if risk > 0 else entry
        elif sig == SIGNAL_SHORT and not in_pos:
            in_pos = True
            direction = "SHORT"
            entry = close
            stop = _structural_stop(work, i, "SHORT", cfg.swing_lookback)
            risk = stop - entry
            target = entry - risk * cfg.rr_ratio if risk > 0 else entry
        elif in_pos:
            if direction == "LONG" and (close <= stop or close >= target):
                trades.append((close - entry) / entry * 100)
                in_pos = False
            elif direction == "SHORT" and (close >= stop or close <= target):
                trades.append((entry - close) / entry * 100)
                in_pos = False

    if not trades:
        return {"total_trades": 0, "win_rate_pct": 0.0, "avg_pnl_pct": 0.0}
    wins = sum(1 for t in trades if t > 0)
    return {
        "total_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 1),
        "avg_pnl_pct": round(float(np.mean(trades)), 2),
    }


def evaluate_live_signal(work: pd.DataFrame, cfg: KISSConfig) -> dict[str, Any]:
    if work.empty or len(work) < cfg.min_exec_bars:
        return {"signal": "NO_DATA"}

    i = len(work) - 1
    row = work.iloc[i]
    prev = work.iloc[i - 1] if i > 0 else row

    close = float(row["close"])
    weekly_f = row.get("weekly_trend_filter")
    weekly_ok_long = pd.notna(weekly_f) and int(weekly_f) == 1
    weekly_ok_short = pd.notna(weekly_f) and int(weekly_f) == -1
    zone = str(row.get("zone", "neutral"))
    ma_state = int(row["ma_dhan_state"]) if pd.notna(row.get("ma_dhan_state")) else 0
    macd_now = float(row["macd"]) if pd.notna(row.get("macd")) else 0.0
    macd_prev = float(prev["macd"]) if pd.notna(prev.get("macd")) else 0.0
    latest_sig = str(row["signal"])

    reasons: list[str] = []
    conf = 28.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False

    if weekly_ok_long:
        reasons.append("Weekly HA filter: Green (longs only)")
        conf += 18
    elif weekly_ok_short:
        reasons.append("Weekly HA filter: Red (shorts only)")
        conf += 18
    else:
        reasons.append("Weekly HA filter unclear — reduce size")

    if zone == "bullish":
        conf += 15
        reasons.append("Price above 55 EMA High band")
    elif zone == "bearish":
        conf += 15
        reasons.append("Price below 55 EMA Low band")
    else:
        reasons.append("Inside 55 EMA band — no-trade zone")

    if ma_state == 1:
        conf += 12
        reasons.append("Signal MA Dhan bullish (close > 55 EMA)")
    elif ma_state == -1:
        conf += 12
        reasons.append("Signal MA Dhan bearish (close < 55 EMA)")

    macd_cross_up = macd_now > 0 and macd_prev <= 0
    macd_cross_dn = macd_now < 0 and macd_prev >= 0
    if macd_cross_up:
        conf += 20
        reasons.append("MACD crossed above zero line")
    elif macd_cross_dn:
        conf += 20
        reasons.append("MACD crossed below zero line")
    elif macd_now > 0:
        conf += 8
        reasons.append("MACD positive momentum")
    elif macd_now < 0:
        conf += 8
        reasons.append("MACD negative momentum")

    conf = max(20.0, min(92.0, conf))
    hold_duration = HOLD_KISS_1H if cfg.execution_tf == EXEC_1H else HOLD_KISS_4H

    if latest_sig == SIGNAL_BUY:
        direction = "LONG"
        verdict = "TAKE LONG"
        take = conf >= cfg.take_confidence_threshold
        stop = _structural_stop(work, i, "LONG", cfg.swing_lookback)
    elif latest_sig == SIGNAL_SHORT:
        direction = "SHORT"
        verdict = "TAKE SHORT"
        take = conf >= cfg.take_confidence_threshold
        stop = _structural_stop(work, i, "SHORT", cfg.swing_lookback)
    elif weekly_ok_long and zone == "bullish" and ma_state == 1:
        direction = "LONG"
        verdict = "WATCH LONG"
        stop = _structural_stop(work, i, "LONG", cfg.swing_lookback)
        reasons.append("Setup building — await MACD zero-line cross")
    elif weekly_ok_short and zone == "bearish" and ma_state == -1:
        direction = "SHORT"
        verdict = "WATCH SHORT"
        stop = _structural_stop(work, i, "SHORT", cfg.swing_lookback)
        reasons.append("Setup building — await MACD zero-line cross")
    else:
        stop = close

    if direction == "LONG" and stop < close:
        sl_pct = max(0.8, (close - stop) / close * 100)
        tp_pct = sl_pct * cfg.rr_ratio
        target = close * (1 + tp_pct / 100)
    elif direction == "SHORT" and stop > close:
        sl_pct = max(0.8, (stop - close) / close * 100)
        tp_pct = sl_pct * cfg.rr_ratio
        target = close * (1 - tp_pct / 100)
    else:
        sl_pct = 2.0
        tp_pct = sl_pct * cfg.rr_ratio
        target = close

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule="; ".join(reasons[:2]) if reasons else "KISS systematic rules",
        max_hold_exit=f"Close by Friday evening or if TP not hit within {hold_duration.split('(')[0].strip()}.",
    )

    weekly_ha_label = "Green" if weekly_ok_long else ("Red" if weekly_ok_short else "Neutral")

    return enrich_st_live({
        "signal": latest_sig if latest_sig != SIGNAL_HOLD else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold_duration,
        "rr_ratio": round(cfg.rr_ratio, 2),
        "entry_price": round(close, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "zone": zone,
        "weekly_ha": weekly_ha_label,
        "macd": round(macd_now, 4),
        "ema_high": round(float(row["ema_high"]), 4) if pd.notna(row.get("ema_high")) else None,
        "ema_low": round(float(row["ema_low"]), 4) if pd.notna(row.get("ema_low")) else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration},
    }, hold_duration=hold_duration)


def fetch_kiss_data(
    ticker: str,
    market: str,
    cfg: KISSConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (execution_df, weekly_df)."""
    is_crypto = "CoinDCX" in market
    daily = fetch_data_for_gap_scan(
        ticker, "1d", market, groww_token, exchange, limit=cfg.daily_lookback,
    )
    daily = normalize_ohlcv(daily)
    if daily.empty or len(daily) < 60:
        daily = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=cfg.daily_lookback, market=market),
        )
    weekly = _resample_weekly(daily)

    tf = cfg.execution_tf
    limit = 500 if tf == EXEC_1H else 400
    exec_df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    exec_df = normalize_ohlcv(exec_df)
    if exec_df.empty or len(exec_df) < cfg.min_exec_bars:
        exec_df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market),
        )
    if tf == EXEC_4H and (exec_df.empty or len(exec_df) < cfg.min_exec_bars):
        h1 = fetch_data_for_gap_scan(ticker, "1h", market, groww_token, exchange, limit=800)
        h1 = normalize_ohlcv(h1)
        if h1.empty:
            h1 = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, "1h", is_crypto=is_crypto, limit=800, market=market))
        exec_df = _resample_4h(h1)

    return exec_df, weekly


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: KISSConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or KISSConfig()
    exec_df, weekly = fetch_kiss_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if exec_df.empty or len(exec_df) < cfg.min_exec_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} execution data."}
    if weekly.empty or len(weekly) < 10:
        return {"ticker": ticker, "error": "Insufficient weekly data for HA trend filter."}

    work = implement_kiss_strategy(exec_df, weekly, cfg)
    if work.empty:
        return {"ticker": ticker, "error": "KISS frame could not be built."}

    live = evaluate_live_signal(work, cfg)
    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "weekly_ha": live.get("weekly_ha"),
        "zone": live.get("zone"),
        "signal_history": _signal_history(work),
        "live": live,
        "backtest": _backtest_kiss(work, cfg),
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: KISSConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or KISSConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [
        r for r in results
        if not r.get("error") and (r.get("live") or {}).get("take_trade")
    ]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
