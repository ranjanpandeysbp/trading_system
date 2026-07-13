"""
breakout_mtf_engine.py
----------------------
Multi-period daily breakout / breakdown scanner (FoxTrader-style).

Lookback windows 10/20/50/90/200 — current bar excluded from rolling extremes.
RSI + MACD confirmation filters per Reliable Software Systems methodology.
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

YOUTUBE_BREAKOUT_MTF_URL = "http://www.youtube.com/watch?v=kQyruEPH108"

DEFAULT_PERIODS: tuple[int, ...] = (10, 20, 50, 90, 200)

PHASE_MULTI_BREAKOUT = "MULTI_BREAKOUT"
PHASE_BREAKOUT = "BREAKOUT"
PHASE_MULTI_BREAKDOWN = "MULTI_BREAKDOWN"
PHASE_BREAKDOWN = "BREAKDOWN"
PHASE_NONE = "NO_SETUP"

PHASE_PRIORITY = {
    PHASE_MULTI_BREAKOUT: 95,
    PHASE_BREAKOUT: 80,
    PHASE_MULTI_BREAKDOWN: 95,
    PHASE_BREAKDOWN: 80,
    PHASE_NONE: 10,
}


@dataclass
class BreakoutMtfConfig:
    periods: tuple[int, ...] = DEFAULT_PERIODS
    rsi_period: int = 14
    rsi_bull_min: float = 50.0
    rsi_bull_max: float = 70.0
    rsi_bear_min: float = 30.0
    rsi_bear_max: float = 50.0
    require_rsi_filter: bool = True
    require_macd_confirm: bool = True
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    min_breakout_periods: int = 1
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 55.0
    limit: int = 280
    min_bars: int = 210


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    exp1 = close.ewm(span=fast, adjust=False).mean()
    exp2 = close.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def _period_extremes(work: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series]:
    """Highest high / lowest low over past N bars, excluding current bar (shift 1)."""
    highest = work["high"].shift(1).rolling(window=period).max()
    lowest = work["low"].shift(1).rolling(window=period).min()
    return highest, lowest


def run_breakout_scan(work: pd.DataFrame, cfg: BreakoutMtfConfig) -> dict[str, Any]:
    """Compute multi-period breakout/breakdown flags and confirmation indicators."""
    df = normalize_ohlcv(work)
    if df.empty or len(df) < max(cfg.periods) + 5:
        return {"error": f"Need at least {max(cfg.periods) + 5} daily bars."}

    current_close = float(df["close"].iloc[-1])
    report: dict[str, Any] = {
        "close": round(current_close, 4),
        "periods": {},
        "breakout_periods": [],
        "breakdown_periods": [],
    }

    for p in cfg.periods:
        hi, lo = _period_extremes(df, p)
        hh = float(hi.iloc[-1]) if pd.notna(hi.iloc[-1]) else None
        ll = float(lo.iloc[-1]) if pd.notna(lo.iloc[-1]) else None
        is_breakout = hh is not None and current_close > hh
        is_breakdown = ll is not None and current_close < ll
        report["periods"][p] = {
            "highest_high": hh,
            "lowest_low": ll,
            "breakout": is_breakout,
            "breakdown": is_breakdown,
            "breakout_label": "BUY" if is_breakout else "-",
            "breakdown_label": "SELL" if is_breakdown else "-",
        }
        if is_breakout:
            report["breakout_periods"].append(p)
        if is_breakdown:
            report["breakdown_periods"].append(p)

    df = df.copy()
    df["rsi"] = calculate_rsi(df["close"], cfg.rsi_period)
    macd_line, signal_line = calculate_macd(
        df["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal,
    )
    df["macd"] = macd_line
    df["macd_signal"] = signal_line

    current_rsi = float(df["rsi"].iloc[-1]) if pd.notna(df["rsi"].iloc[-1]) else None
    current_macd = float(df["macd"].iloc[-1]) if pd.notna(df["macd"].iloc[-1]) else None
    macd_positive = current_macd is not None and current_macd > 0

    report["rsi"] = round(current_rsi, 2) if current_rsi is not None else None
    report["macd"] = round(current_macd, 4) if current_macd is not None else None
    report["macd_status"] = "Positive" if macd_positive else "Negative"
    report["rsi_bull_match"] = (
        current_rsi is not None
        and cfg.rsi_bull_min <= current_rsi <= cfg.rsi_bull_max
    )
    report["rsi_bear_match"] = (
        current_rsi is not None
        and cfg.rsi_bear_min <= current_rsi <= cfg.rsi_bear_max
    )
    report["signals_df"] = df
    return report


def evaluate_live(scan: dict[str, Any], cfg: BreakoutMtfConfig) -> dict[str, Any]:
    if scan.get("error"):
        return {"error": scan["error"]}

    price = float(scan["close"])
    bo_periods: list[int] = list(scan.get("breakout_periods") or [])
    bd_periods: list[int] = list(scan.get("breakdown_periods") or [])
    bo_count = len(bo_periods)
    bd_count = len(bd_periods)

    reasons: list[str] = []
    conf = 20.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    strategy = "Multi-Period Breakout"

    rsi = scan.get("rsi")
    macd_status = scan.get("macd_status", "—")
    rsi_bull = scan.get("rsi_bull_match", False)
    rsi_bear = scan.get("rsi_bear_match", False)

    if bo_count >= 3:
        phase = PHASE_MULTI_BREAKOUT
        direction = "LONG"
        conf += 18 + bo_count * 8
        reasons.append(f"Multi-period breakout — {bo_count} windows: {bo_periods}")
    elif bo_count >= cfg.min_breakout_periods:
        phase = PHASE_BREAKOUT
        direction = "LONG"
        conf += 15 + bo_count * 10
        reasons.append(f"Breakout on {bo_periods} day lookback(s) — close above prior highs")

    if bd_count >= 3 and bo_count == 0:
        phase = PHASE_MULTI_BREAKDOWN
        direction = "SHORT"
        conf += 18 + bd_count * 8
        reasons.append(f"Multi-period breakdown — {bd_count} windows: {bd_periods}")
    elif bd_count >= cfg.min_breakout_periods and bo_count == 0:
        phase = PHASE_BREAKDOWN
        direction = "SHORT"
        conf += 15 + bd_count * 10
        reasons.append(f"Breakdown on {bd_periods} day lookback(s) — close below prior lows")

    if bo_count > 0 and bd_count > 0:
        if bo_count > bd_count:
            phase = PHASE_MULTI_BREAKOUT if bo_count >= 3 else PHASE_BREAKOUT
            direction = "LONG"
            conf += 10
            reasons.append(f"Mixed signals — {bo_count} breakouts vs {bd_count} breakdowns; breakout side dominant")
        elif bd_count > bo_count:
            phase = PHASE_MULTI_BREAKDOWN if bd_count >= 3 else PHASE_BREAKDOWN
            direction = "SHORT"
            conf += 10
            reasons.append(f"Mixed signals — {bd_count} breakdowns vs {bo_count} breakouts; breakdown side dominant")
        else:
            conf -= 15
            reasons.append("Equal breakout and breakdown flags — wait for clarity")
            direction = "WAIT"
            verdict = "CONFLICT"
            phase = PHASE_NONE

    if direction == "LONG":
        if cfg.require_rsi_filter:
            if rsi_bull:
                conf += 14
                reasons.append(f"RSI {rsi} in bullish continuation zone ({cfg.rsi_bull_min}–{cfg.rsi_bull_max})")
            else:
                conf -= 8
                reasons.append(f"RSI {rsi} outside ideal bullish zone {cfg.rsi_bull_min}–{cfg.rsi_bull_max}")
        if cfg.require_macd_confirm:
            if macd_status == "Positive":
                conf += 10
                reasons.append("MACD positive — momentum supports breakout")
            else:
                conf -= 10
                reasons.append("MACD negative — weak momentum for fresh breakout")

    elif direction == "SHORT":
        if cfg.require_rsi_filter:
            if rsi_bear:
                conf += 12
                reasons.append(f"RSI {rsi} in bearish zone ({cfg.rsi_bear_min}–{cfg.rsi_bear_max})")
            else:
                conf -= 6
                reasons.append(f"RSI {rsi} outside bearish filter band")
        if cfg.require_macd_confirm:
            if macd_status == "Negative":
                conf += 10
                reasons.append("MACD negative — momentum supports breakdown")
            else:
                conf -= 8
                reasons.append("MACD positive — conflicts with breakdown")

    conf = max(12.0, min(92.0, conf))

    actionable = (
        phase in (PHASE_BREAKOUT, PHASE_MULTI_BREAKOUT, PHASE_BREAKDOWN, PHASE_MULTI_BREAKDOWN)
        and direction in ("LONG", "SHORT")
        and conf >= cfg.take_confidence_threshold
    )
    if actionable and cfg.require_rsi_filter:
        if direction == "LONG" and not rsi_bull:
            actionable = False
        if direction == "SHORT" and not rsi_bear:
            actionable = False
    if actionable and cfg.require_macd_confirm:
        if direction == "LONG" and macd_status != "Positive":
            actionable = False
        if direction == "SHORT" and macd_status != "Negative":
            actionable = False

    if actionable:
        verdict = f"TAKE {direction}"
    elif direction in ("LONG", "SHORT") and phase != PHASE_NONE:
        verdict = f"WATCH {direction}"
    else:
        verdict = verdict if verdict == "CONFLICT" else "WAIT"

    stop = price
    target = price
    ref_periods = bo_periods if direction == "LONG" else bd_periods
    period_data = scan.get("periods") or {}

    if direction == "LONG" and ref_periods:
        ref_p = min(ref_periods)
        ll = (period_data.get(ref_p) or {}).get("lowest_low")
        stop = float(ll) * 0.995 if ll else price * 0.97
        risk = max(price - stop, price * 0.008)
        target = price + risk * cfg.rr_ratio
    elif direction == "SHORT" and ref_periods:
        ref_p = min(ref_periods)
        hh = (period_data.get(ref_p) or {}).get("highest_high")
        stop = float(hh) * 1.005 if hh else price * 1.03
        risk = max(stop - price, price * 0.008)
        target = price - risk * cfg.rr_ratio

    if direction == "LONG" and stop < price:
        sl_pct = max(0.5, (price - stop) / price * 100)
        tp_pct = max(0.8, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.5, (stop - price) / price * 100)
        tp_pct = max(0.8, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 2.0
        tp_pct = sl_pct * cfg.rr_ratio

    hold = "Swing / position — multi-day breakout hold (1–4 weeks typical on daily trigger)"
    plan = make_trade_plan(
        direction=direction if actionable and direction in ("LONG", "SHORT") else "—",
        timeframe="1d",
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule="Exit if close falls back inside broken range or RSI/MACD thesis fails.",
        max_hold_exit="Re-evaluate after 20 sessions if target not reached.",
    )

    primary = verdict if actionable else (
        verdict if verdict.startswith("WATCH") else f"{phase} — no fresh trigger"
    )

    return {
        "phase": phase,
        "strategy": strategy,
        "primary_label": primary,
        "direction": direction,
        "verdict": verdict,
        "actionable": actionable,
        "confidence": round(conf, 1),
        "price": price,
        "breakout_periods": bo_periods,
        "breakdown_periods": bd_periods,
        "breakout_count": bo_count,
        "breakdown_count": bd_count,
        "rsi": rsi,
        "macd": scan.get("macd"),
        "macd_status": macd_status,
        "rsi_filter_match": "Yes" if (rsi_bull and direction == "LONG") or (rsi_bear and direction == "SHORT") else "No",
        "periods_detail": period_data,
        "priority": PHASE_PRIORITY.get(phase, 15),
        "trade_plan": {
            "direction": direction if actionable else "—",
            "entry": price,
            "stop_loss": round(stop, 4),
            "take_profit": round(target, 4),
            "sl_pct": round(sl_pct, 2),
            "tp_pct": round(tp_pct, 2),
            "rr_ratio": cfg.rr_ratio,
            "hold_duration": hold,
            "exit_rule": plan.get("exit_rule"),
            "notes": f"{bo_count} breakout / {bd_count} breakdown period(s)",
        },
        "signals_df": scan.get("signals_df"),
        "reasons": reasons,
    }


def fetch_daily_data(
    ticker: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 280,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 200:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def analyze_breakout_mtf(
    ticker: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: BreakoutMtfConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or BreakoutMtfConfig()
    raw = fetch_daily_data(ticker, market, groww_token=groww_token, exchange=exchange, limit=cfg.limit)
    if raw.empty or len(raw) < cfg.min_bars:
        return {
            "error": f"Insufficient daily data ({len(raw)} bars, need {cfg.min_bars}).",
            "symbol": ticker,
        }

    scan = run_breakout_scan(raw, cfg)
    if scan.get("error"):
        return {"error": scan["error"], "symbol": ticker}

    live = evaluate_live(scan, cfg)
    if live.get("error"):
        return {"error": live["error"], "symbol": ticker}

    return {
        "symbol": ticker,
        "chart_tf": "1d",
        **live,
        "scan": scan,
    }


def scan_row_for_table(ticker: str, data: dict[str, Any], periods: tuple[int, ...]) -> dict[str, Any]:
    """Flat row for dashboard-style scanner table."""
    if data.get("error"):
        return {"Ticker": ticker, "Phase": "ERROR", "Close": "—", "Action": data["error"][:50]}

    scan = data.get("scan") or {}
    row: dict[str, Any] = {
        "Ticker": ticker,
        "Close": data.get("price"),
        "Phase": data.get("phase", "—"),
        "Conf": f"{data.get('confidence', 0):.0f}%",
        "RSI": scan.get("rsi"),
        "MACD": scan.get("macd_status"),
        "RSI OK": data.get("rsi_filter_match", "—"),
        "BO#": data.get("breakout_count", 0),
        "BD#": data.get("breakdown_count", 0),
        "Action": "✅" if data.get("actionable") else "—",
    }
    pdetail = scan.get("periods") or {}
    for p in periods:
        pinfo = pdetail.get(p) or pdetail.get(str(p)) or {}
        row[f"{p}D BO"] = pinfo.get("breakout_label", "-")
        row[f"{p}D BD"] = pinfo.get("breakdown_label", "-")
    return row


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: BreakoutMtfConfig | None = None,
) -> dict[str, dict[str, Any]]:
    cfg = cfg or BreakoutMtfConfig()
    results: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        try:
            results[ticker] = analyze_breakout_mtf(
                ticker, market, groww_token=groww_token, exchange=exchange, cfg=cfg,
            )
        except Exception as exc:
            results[ticker] = {"error": str(exc)[:200], "symbol": ticker}
    return results
