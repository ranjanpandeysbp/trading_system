"""
one_ta_engine.py
----------------
ONE TA — Golden Zone strategy with Fibonacci confluence, EMA trend,
engulfing / wick rejection entries, and Wyckoff-style volume context.

Professional trading blueprint: market structure + S/R + liquidity + VPA.
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

logger = logging.getLogger(__name__)

YOUTUBE_ONE_TA_URL = "https://www.youtube.com/watch?v=UbmSxPOQRb4&t=14s"

TF_OPTIONS = ["15m", "30m", "1h", "4h", "1d"]

PHASE_ENTRY_LONG = "GOLDEN_ENTRY_LONG"
PHASE_ENTRY_SHORT = "GOLDEN_ENTRY_SHORT"
PHASE_IN_ZONE = "IN_GOLDEN_ZONE"
PHASE_TREND_ONLY = "TREND_ALIGNED"
PHASE_NONE = "NO_SETUP"

PHASE_PRIORITY = {
    PHASE_ENTRY_LONG: 95,
    PHASE_ENTRY_SHORT: 95,
    PHASE_IN_ZONE: 70,
    PHASE_TREND_ONLY: 45,
    PHASE_NONE: 10,
}


@dataclass
class OneTaConfig:
    ema_period: int = 200
    swing_window: int = 20
    wick_ratio: float = 0.50
    require_ema_confluence: bool = True
    sl_range_buffer: float = 0.05
    take_confidence_threshold: float = 58.0
    limit: int = 400
    min_bars: int = 220


def _bullish_engulfing(o: float, h: float, l: float, c: float, prev_rows: list[tuple]) -> bool:
    if c <= o or len(prev_rows) < 2:
        return False
    bodies = [max(r[0], r[3]) for r in prev_rows[-2:]]  # open, high, low, close -> max(o,c)
    return c > max(bodies)


def _bearish_engulfing(o: float, h: float, l: float, c: float, prev_rows: list[tuple]) -> bool:
    if c >= o or len(prev_rows) < 2:
        return False
    bodies = [min(r[0], r[3]) for r in prev_rows[-2:]]
    return c < min(bodies)


def _lower_wick_rejection(o: float, h: float, l: float, c: float, ratio: float) -> bool:
    rng = h - l
    if rng <= 0:
        return False
    lower = min(o, c) - l
    return lower / rng >= ratio


def _upper_wick_rejection(o: float, h: float, l: float, c: float, ratio: float) -> bool:
    rng = h - l
    if rng <= 0:
        return False
    upper = h - max(o, c)
    return upper / rng >= ratio


def _ema_confluence(ema: float, fib_lo: float, fib_hi: float, *, tolerance_pct: float = 0.015) -> bool:
    zone_mid = (fib_lo + fib_hi) / 2
    tol = abs(zone_mid) * tolerance_pct if zone_mid else 0.01
    return fib_lo - tol <= ema <= fib_hi + tol


def _momentum_roc(close: pd.Series, period: int = 10) -> float | None:
    if len(close) < period + 1:
        return None
    prev = float(close.iloc[-period - 1])
    cur = float(close.iloc[-1])
    if prev == 0:
        return None
    return (cur - prev) / prev * 100


def implement_golden_zone_strategy(df: pd.DataFrame, cfg: OneTaConfig) -> pd.DataFrame:
    work = normalize_ohlcv(df)
    if work.empty:
        return work

    w = cfg.swing_window
    span = w * 2 + 1
    work = work.copy()
    work["ema_trend"] = work["close"].ewm(span=cfg.ema_period, adjust=False).mean()
    roll_h = work["high"].rolling(span, center=True).max()
    roll_l = work["low"].rolling(span, center=True).min()
    work["swing_high"] = roll_h.ffill()
    work["swing_low"] = roll_l.ffill()
    work["signal"] = 0
    work["setup_phase"] = PHASE_NONE
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan

    if "volume" in work.columns:
        work["vol_sma"] = work["volume"].rolling(20).mean()
    else:
        work["vol_sma"] = np.nan

    for i in range(2, len(work)):
        row = work.iloc[i]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        ema = float(row["ema_trend"]) if pd.notna(row["ema_trend"]) else c
        sh = float(row["swing_high"]) if pd.notna(row["swing_high"]) else h
        slv = float(row["swing_low"]) if pd.notna(row["swing_low"]) else l
        swing_range = sh - slv
        if swing_range <= 0:
            continue

        fib_50 = slv + 0.50 * swing_range
        fib_618 = slv + 0.618 * swing_range
        fib_382 = slv + 0.382 * swing_range
        fib_236 = slv + 0.236 * swing_range

        prev_rows = [
            (float(work.iloc[i - 2]["open"]), float(work.iloc[i - 2]["high"]),
             float(work.iloc[i - 2]["low"]), float(work.iloc[i - 2]["close"])),
            (float(work.iloc[i - 1]["open"]), float(work.iloc[i - 1]["high"]),
             float(work.iloc[i - 1]["low"]), float(work.iloc[i - 1]["close"])),
        ]

        ts = work.index[i]
        phase = PHASE_NONE
        sig = 0
        stop = np.nan
        target = np.nan

        vol_ok = True
        if pd.notna(row.get("vol_sma")) and row["vol_sma"] > 0:
            vol_ok = float(row.get("volume", 0) or 0) >= float(row["vol_sma"]) * 0.85

        if c > ema:
            in_golden = l <= fib_618 and h >= fib_50
            ema_conf = _ema_confluence(ema, fib_50, fib_618)
            engulf = _bullish_engulfing(o, h, l, c, prev_rows)
            wick = _lower_wick_rejection(o, h, l, c, cfg.wick_ratio)
            trigger = engulf or wick

            if in_golden:
                phase = PHASE_IN_ZONE
                if trigger and (not cfg.require_ema_confluence or ema_conf):
                    if vol_ok:
                        phase = PHASE_ENTRY_LONG
                        sig = 1
                        stop = fib_618 - swing_range * cfg.sl_range_buffer
                        target = sh
                        work.at[ts, "signal"] = sig
                        work.at[ts, "setup_phase"] = phase
                        work.at[ts, "stop_loss"] = stop
                        work.at[ts, "take_profit"] = target
                    else:
                        work.at[ts, "setup_phase"] = PHASE_IN_ZONE
                else:
                    work.at[ts, "setup_phase"] = PHASE_IN_ZONE
            elif c > ema:
                work.at[ts, "setup_phase"] = PHASE_TREND_ONLY

        elif c < ema:
            fib_short_50 = sh - 0.50 * swing_range
            fib_short_618 = sh - 0.618 * swing_range
            in_golden = h >= fib_short_618 and l <= fib_short_50
            ema_conf = _ema_confluence(ema, fib_short_618, fib_short_50)
            engulf = _bearish_engulfing(o, h, l, c, prev_rows)
            wick = _upper_wick_rejection(o, h, l, c, cfg.wick_ratio)
            trigger = engulf or wick

            if in_golden:
                phase = PHASE_IN_ZONE
                if trigger and (not cfg.require_ema_confluence or ema_conf):
                    if vol_ok:
                        phase = PHASE_ENTRY_SHORT
                        sig = -1
                        stop = fib_short_618 + swing_range * cfg.sl_range_buffer
                        target = slv
                        work.at[ts, "signal"] = sig
                        work.at[ts, "setup_phase"] = phase
                        work.at[ts, "stop_loss"] = stop
                        work.at[ts, "take_profit"] = target
                    else:
                        work.at[ts, "setup_phase"] = PHASE_IN_ZONE
                else:
                    work.at[ts, "setup_phase"] = PHASE_IN_ZONE
            else:
                work.at[ts, "setup_phase"] = PHASE_TREND_ONLY

    return work


def _fib_snapshot(sh: float, slv: float) -> dict[str, float]:
    rng = sh - slv
    if rng <= 0:
        return {}
    return {
        "fib_236": slv + 0.236 * rng,
        "fib_382": slv + 0.382 * rng,
        "fib_50": slv + 0.50 * rng,
        "fib_618": slv + 0.618 * rng,
        "swing_high": sh,
        "swing_low": slv,
    }


def evaluate_live(work: pd.DataFrame, cfg: OneTaConfig) -> dict[str, Any]:
    if work.empty or len(work) < cfg.min_bars:
        return {"error": "Insufficient data for ONE TA analysis."}

    row = work.iloc[-1]
    price = float(row["close"])
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), price
    ema = float(row["ema_trend"]) if pd.notna(row["ema_trend"]) else price
    sh = float(row["swing_high"]) if pd.notna(row["swing_high"]) else h
    slv = float(row["swing_low"]) if pd.notna(row["swing_low"]) else l
    swing_range = sh - slv
    fibs = _fib_snapshot(sh, slv)

    reasons: list[str] = []
    conf = 22.0
    direction = "WAIT"
    phase = str(row["setup_phase"]) if pd.notna(row.get("setup_phase")) else PHASE_NONE
    verdict = "WAIT"
    trigger_type = None

    latest_sig = int(row["signal"]) if pd.notna(row.get("signal")) and row["signal"] != 0 else 0
    roc = _momentum_roc(work["close"])

    prev_rows = []
    if len(work) >= 3:
        for j in (-2, -1):
            r = work.iloc[j]
            prev_rows.append((float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))

    if swing_range > 0:
        fib_50, fib_618 = fibs["fib_50"], fibs["fib_618"]
        fib_short_50 = sh - 0.50 * swing_range
        fib_short_618 = sh - 0.618 * swing_range

        if c > ema:
            direction = "LONG"
            conf += 12
            reasons.append(f"Bullish structure — price above {cfg.ema_period} EMA")
            in_golden = l <= fib_618 and h >= fib_50
            ema_conf = _ema_confluence(ema, fib_50, fib_618)
            engulf = _bullish_engulfing(o, h, l, c, prev_rows)
            wick = _lower_wick_rejection(o, h, l, c, cfg.wick_ratio)

            if in_golden:
                conf += 18
                reasons.append("Price in Golden Zone (50%–61.8% Fib retracement)")
                if ema_conf:
                    conf += 14
                    reasons.append("EMA confluence inside Golden Zone")
                elif cfg.require_ema_confluence:
                    conf -= 8
                    reasons.append("EMA not overlapping Golden Zone — lower confluence")

                if engulf:
                    trigger_type = "Engulfing"
                    conf += 20
                    reasons.append("Bullish engulfing — body engulfs prior 2 candles")
                elif wick:
                    trigger_type = "Wick rejection"
                    conf += 18
                    reasons.append("Long lower wick rejection at golden ratio")
                elif phase == PHASE_IN_ZONE:
                    verdict = "WATCH LONG"
                    reasons.append("In zone — await engulfing or wick rejection trigger")
            else:
                reasons.append("Pullback not yet in Golden Zone — monitor 50–61.8% band")

        elif c < ema:
            direction = "SHORT"
            conf += 12
            reasons.append(f"Bearish structure — price below {cfg.ema_period} EMA")
            in_golden = h >= fib_short_618 and l <= fib_short_50
            ema_conf = _ema_confluence(ema, fib_short_618, fib_short_50)
            engulf = _bearish_engulfing(o, h, l, c, prev_rows)
            wick = _upper_wick_rejection(o, h, l, c, cfg.wick_ratio)

            if in_golden:
                conf += 18
                reasons.append("Price in Golden Zone (50%–61.8% bearish retracement)")
                if ema_conf:
                    conf += 14
                    reasons.append("EMA confluence inside Golden Zone")
                elif cfg.require_ema_confluence:
                    conf -= 8

                if engulf:
                    trigger_type = "Engulfing"
                    conf += 20
                    reasons.append("Bearish engulfing — body engulfs prior 2 candles")
                elif wick:
                    trigger_type = "Wick rejection"
                    conf += 18
                    reasons.append("Long upper wick rejection at golden ratio")
                elif phase == PHASE_IN_ZONE:
                    verdict = "WATCH SHORT"
                    reasons.append("In zone — await bearish trigger candle")
            else:
                reasons.append("Retracement not yet in Golden Zone")

    if roc is not None:
        if direction == "LONG" and roc > 0:
            conf += 6
            reasons.append(f"Momentum gain ROC {roc:+.2f}%")
        elif direction == "SHORT" and roc < 0:
            conf += 6
            reasons.append(f"Momentum loss ROC {roc:+.2f}%")
        elif direction in ("LONG", "SHORT"):
            conf -= 4
            reasons.append(f"Momentum ROC {roc:+.2f}% — weak alignment")

    if latest_sig == 1 or phase == PHASE_ENTRY_LONG:
        phase = PHASE_ENTRY_LONG
        direction = "LONG"
        if not trigger_type and latest_sig == 1:
            trigger_type = "Signal bar"
    elif latest_sig == -1 or phase == PHASE_ENTRY_SHORT:
        phase = PHASE_ENTRY_SHORT
        direction = "SHORT"
        if not trigger_type and latest_sig == -1:
            trigger_type = "Signal bar"

    conf = max(15.0, min(92.0, conf))
    actionable = (
        phase in (PHASE_ENTRY_LONG, PHASE_ENTRY_SHORT)
        and trigger_type is not None
        and conf >= cfg.take_confidence_threshold
    )
    if actionable:
        verdict = f"TAKE {direction}"
    elif phase == PHASE_IN_ZONE:
        verdict = f"WATCH {direction}"
    elif phase == PHASE_TREND_ONLY:
        verdict = f"SETUP {direction}"

    stop = float(row["stop_loss"]) if pd.notna(row.get("stop_loss")) else price
    target = float(row["take_profit"]) if pd.notna(row.get("take_profit")) else price

    if direction == "LONG" and swing_range > 0:
        if not pd.notna(row.get("stop_loss")):
            stop = fibs["fib_618"] - swing_range * cfg.sl_range_buffer
        if not pd.notna(row.get("take_profit")):
            target = sh
        tp_partial_1 = fibs.get("fib_382", target)
        tp_partial_2 = fibs.get("fib_236", target)
    elif direction == "SHORT" and swing_range > 0:
        if not pd.notna(row.get("stop_loss")):
            stop = sh - 0.618 * swing_range + swing_range * cfg.sl_range_buffer
        if not pd.notna(row.get("take_profit")):
            target = slv
        tp_partial_1 = sh - 0.382 * swing_range
        tp_partial_2 = sh - 0.236 * swing_range
    else:
        tp_partial_1 = tp_partial_2 = target

    if direction == "LONG" and stop < price:
        sl_pct = max(0.4, (price - stop) / price * 100)
        tp_pct = max(0.6, (target - price) / price * 100) if target > price else sl_pct * 2
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.4, (stop - price) / price * 100)
        tp_pct = max(0.6, (price - target) / price * 100) if target < price else sl_pct * 2
    else:
        sl_pct = 1.5
        tp_pct = 3.0

    hold = "Swing — golden zone pullback trade (days to weeks on daily; hours on intraday)"
    plan = make_trade_plan(
        direction=direction if actionable and direction in ("LONG", "SHORT") else "—",
        timeframe="chart",
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule="Scale at 38.2% / 23.6% fib levels; full exit at swing origin (100%).",
        max_hold_exit="Exit if close breaks past 61.8% stop zone.",
    )

    primary = verdict if actionable else (
        verdict if verdict.startswith(("WATCH", "SETUP")) else f"{phase} — no trigger"
    )

    return {
        "phase": phase,
        "strategy": "Golden Zone Fib + EMA",
        "primary_label": primary,
        "direction": direction,
        "verdict": verdict,
        "actionable": actionable,
        "confidence": round(conf, 1),
        "price": price,
        "ema": round(ema, 4),
        "trigger_type": trigger_type,
        "momentum_roc": round(roc, 2) if roc is not None else None,
        "fib_levels": fibs,
        "tp_partial_382": round(tp_partial_1, 4) if swing_range > 0 else None,
        "tp_partial_236": round(tp_partial_2, 4) if swing_range > 0 else None,
        "priority": PHASE_PRIORITY.get(phase, 15),
        "trade_plan": {
            "direction": direction if actionable else "—",
            "entry": price,
            "stop_loss": round(stop, 4),
            "take_profit": round(target, 4),
            "sl_pct": round(sl_pct, 2),
            "tp_pct": round(tp_pct, 2),
            "hold_duration": hold,
            "exit_rule": plan.get("exit_rule"),
            "notes": "Partials @ 38.2% / 23.6% · full @ swing origin",
        },
        "signals_df": work,
        "reasons": reasons,
        "signal_count": int((work["signal"] != 0).sum()),
    }


def fetch_chart_data(
    ticker: str,
    timeframe: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 100:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def analyze_one_ta(
    ticker: str,
    market: str,
    timeframe: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: OneTaConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or OneTaConfig()
    raw = fetch_chart_data(
        ticker, timeframe, market, groww_token=groww_token, exchange=exchange, limit=cfg.limit,
    )
    if raw.empty or len(raw) < cfg.min_bars:
        return {
            "error": f"Insufficient data ({len(raw)} bars, need {cfg.min_bars}).",
            "symbol": ticker,
        }

    work = implement_golden_zone_strategy(raw, cfg)
    live = evaluate_live(work, cfg)
    if live.get("error"):
        return {"error": live["error"], "symbol": ticker}

    return {
        "symbol": ticker,
        "chart_tf": timeframe,
        **live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    timeframe: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: OneTaConfig | None = None,
) -> dict[str, dict[str, Any]]:
    cfg = cfg or OneTaConfig()
    results: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        try:
            results[ticker] = analyze_one_ta(
                ticker, market, timeframe,
                groww_token=groww_token, exchange=exchange, cfg=cfg,
            )
        except Exception as exc:
            results[ticker] = {"error": str(exc)[:200], "symbol": ticker}
    return results
