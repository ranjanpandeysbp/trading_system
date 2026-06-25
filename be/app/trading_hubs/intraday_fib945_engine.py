"""
intraday_fib945_engine.py
-------------------------
9:45 AM Fibonacci 50% bias + 10 EMA execution strategy.

Wait for first 30m candle (9:15–9:45), set 50% equilibrium, trade with bias on 5m/1m.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.trading_hubs.session_constants import IST_TZ
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_alpha_945_engine import (
    _ensure_ist_index,
    fetch_intraday_for_opening_range,
    get_opening_30m_candle,
)
from app.trading_hubs.intraday_shared import HOLD_FIB_945, enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_INTRA_FIB945_URL = "http://www.youtube.com/watch?v=5o7V6fi7mV4"

EXEC_1M = "1m"
EXEC_5M = "5m"

BIAS_BULL = "BULLISH"
BIAS_BEAR = "BEARISH"
BIAS_NEUTRAL = "NEUTRAL"

SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_HOLD = "HOLD"


@dataclass
class Fib945Config:
    execution_tf: str = EXEC_5M
    ema_fast: int = 10
    ma_confirm: int = 30
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 60.0
    min_exec_bars: int = 40


def fib_50_level(morning_high: float, morning_low: float) -> float:
    return morning_low + 0.5 * (morning_high - morning_low)


def _post_945_bars(df: pd.DataFrame, opening: dict[str, Any]) -> pd.DataFrame:
    """Execution bars after the opening range on the same IST session day."""
    work = _ensure_ist_index(df)
    if work.empty:
        return work

    range_end = opening["range_end"]
    if range_end.tzinfo is None:
        range_end = pd.Timestamp(range_end).tz_localize(IST_TZ)
    else:
        range_end = range_end.tz_convert(IST_TZ)

    session_day = pd.Timestamp(opening["session_date"]).tz_localize(IST_TZ).normalize()
    day_bars = work[work.index.normalize() == session_day]
    # Strictly after 9:45 close (exclude the opening-range bar itself)
    return day_bars[day_bars.index > range_end].copy()


def implement_fib945_strategy(
    df_exec: pd.DataFrame,
    opening: dict[str, Any],
    cfg: Fib945Config,
) -> pd.DataFrame:
    """Annotate execution bars with fib 50%, bias, EMA, and signals for the session."""
    work = _post_945_bars(df_exec, opening)
    if work.empty:
        return pd.DataFrame()

    mh, ml = float(opening["high"]), float(opening["low"])
    f50 = fib_50_level(mh, ml)
    work["fib_50"] = f50
    work["morning_high"] = mh
    work["morning_low"] = ml
    work["ema_fast"] = work["close"].ewm(span=cfg.ema_fast, adjust=False).mean()
    work["ma_confirm"] = work["close"].rolling(cfg.ma_confirm).mean()
    work["bias"] = BIAS_NEUTRAL
    work["signal"] = SIGNAL_HOLD

    prev_close = work["close"].shift(1)
    prev_ema = work["ema_fast"].shift(1)

    for idx in work.index:
        row = work.loc[idx]
        close = float(row["close"])
        if close > f50:
            work.at[idx, "bias"] = BIAS_BULL
        elif close < f50:
            work.at[idx, "bias"] = BIAS_BEAR

    bull_cross = (
        (work["bias"] == BIAS_BULL)
        & (work["close"] > work["ema_fast"])
        & (prev_close <= prev_ema)
    )
    bear_cross = (
        (work["bias"] == BIAS_BEAR)
        & (work["close"] < work["ema_fast"])
        & (prev_close >= prev_ema)
    )
    work.loc[bull_cross, "signal"] = SIGNAL_BUY
    work.loc[bear_cross, "signal"] = SIGNAL_SELL
    return work


def _signal_history(work: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(len(work) - 1, -1, -1):
        sig = str(work["signal"].iloc[i])
        if sig == SIGNAL_HOLD:
            continue
        ts = work.index[i]
        rows.append({
            "time": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "signal": sig,
            "bias": work["bias"].iloc[i],
            "close": round(float(work["close"].iloc[i]), 4),
            "fib_50": round(float(work["fib_50"].iloc[i]), 4),
        })
        if len(rows) >= limit:
            break
    return rows


def evaluate_live_signal(
    work: pd.DataFrame,
    opening: dict[str, Any],
    cfg: Fib945Config,
) -> dict[str, Any]:
    if work.empty or len(work) < 3:
        return {"signal": "NO_DATA"}

    row = work.iloc[-1]
    prev = work.iloc[-2]
    close = float(row["close"])
    prev_close = float(prev["close"])
    ema = float(row["ema_fast"])
    prev_ema = float(prev["ema_fast"])
    ma30 = float(row["ma_confirm"]) if pd.notna(row["ma_confirm"]) else close
    f50 = float(row["fib_50"])
    bias = str(row["bias"])
    latest_sig = str(row["signal"])

    reasons: list[str] = []
    conf = 28.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False

    dist_pct = abs(close - f50) / f50 * 100 if f50 else 0.0
    reasons.append(f"Opening range H/L → 50% Fib = {f50:,.4g}")

    if bias == BIAS_BULL:
        conf += 22
        reasons.append("Bias BULLISH — price above 50% equilibrium (longs only)")
        direction = "LONG"
    elif bias == BIAS_BEAR:
        conf += 22
        reasons.append("Bias BEARISH — price below 50% equilibrium (shorts only)")
        direction = "SHORT"
    else:
        reasons.append("Price at equilibrium — wait for clear bias")

    if dist_pct > 0.15:
        conf += min(12, dist_pct * 2)
        reasons.append(f"Distance from 50% level: {dist_pct:.2f}%")

    ema_cross_up = close > ema and prev_close <= prev_ema
    ema_cross_dn = close < ema and prev_close >= prev_ema

    if bias == BIAS_BULL and close > ema:
        conf += 14
        reasons.append("Price above 10 EMA")
        if close > ma30:
            conf += 10
            reasons.append("Price above 30 MA confirmation")
    elif bias == BIAS_BEAR and close < ema:
        conf += 14
        reasons.append("Price below 10 EMA")
        if close < ma30:
            conf += 10
            reasons.append("Price below 30 MA confirmation")

    if latest_sig == SIGNAL_BUY or (bias == BIAS_BULL and ema_cross_up):
        verdict = "TAKE LONG"
        direction = "LONG"
        latest_sig = SIGNAL_BUY if ema_cross_up else latest_sig
    elif latest_sig == SIGNAL_SELL or (bias == BIAS_BEAR and ema_cross_dn):
        verdict = "TAKE SHORT"
        direction = "SHORT"
        latest_sig = SIGNAL_SELL if ema_cross_dn else latest_sig
    elif bias == BIAS_BULL:
        verdict = "WATCH LONG"
        reasons.append("Await 10 EMA cross-up in bullish bias")
    elif bias == BIAS_BEAR:
        verdict = "WATCH SHORT"
        reasons.append("Await 10 EMA cross-down in bearish bias")

    conf = max(20.0, min(90.0, conf))
    take = verdict.startswith("TAKE") and conf >= cfg.take_confidence_threshold

    prev_low = float(prev["low"])
    prev_high = float(prev["high"])

    if direction == "LONG":
        stop = min(prev_low, f50 * 0.999)
        sl_pct = max(0.35, (close - stop) / close * 100) if stop < close else 1.0
        tp_pct = sl_pct * cfg.rr_ratio
        target = close * (1 + tp_pct / 100)
    elif direction == "SHORT":
        stop = max(prev_high, f50 * 1.001)
        sl_pct = max(0.35, (stop - close) / close * 100) if stop > close else 1.0
        tp_pct = sl_pct * cfg.rr_ratio
        target = close * (1 - tp_pct / 100)
    else:
        stop = close
        sl_pct = 1.0
        tp_pct = cfg.rr_ratio
        target = close

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="SL below prior candle low or 50% Fib support (longs); mirror for shorts.",
        max_hold_exit="Close intraday positions by ~15:15 IST.",
    )

    return enrich_intra_live({
        "signal": latest_sig if latest_sig != SIGNAL_HOLD else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": HOLD_FIB_945,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(close, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "bias": bias,
        "fib_50": round(f50, 6),
        "morning_high": round(float(opening["high"]), 6),
        "morning_low": round(float(opening["low"]), 6),
        "ema_fast": round(ema, 6),
        "ma_confirm": round(ma30, 6) if pd.notna(ma30) else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD_FIB_945},
    }, hold_duration=HOLD_FIB_945)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: Fib945Config,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    limit = 500 if cfg.execution_tf == EXEC_1M else 400
    df = fetch_data_for_gap_scan(ticker, cfg.execution_tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_exec_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.execution_tf, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: Fib945Config | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Fib945Config()
    exec_df = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if exec_df.empty:
        return {"ticker": ticker, "error": f"No {cfg.execution_tf} data."}

    opening = get_opening_30m_candle(exec_df)
    if not opening:
        intra = fetch_intraday_for_opening_range(
            ticker, market, groww_token=groww_token, exchange=exchange,
        )
        if not intra.empty:
            opening = get_opening_30m_candle(intra)
    if not opening:
        return {"ticker": ticker, "error": "Could not build 9:15–9:45 opening range."}

    work = implement_fib945_strategy(exec_df, opening, cfg)
    if work.empty:
        return {"ticker": ticker, "error": "No post-9:45 bars for signal evaluation."}

    live = evaluate_live_signal(work, opening, cfg)
    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars_post_945": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "opening_candle": opening,
        "fib_50": live.get("fib_50"),
        "bias": live.get("bias"),
        "signal_history": _signal_history(work),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: Fib945Config | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Fib945Config()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
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
