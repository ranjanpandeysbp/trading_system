"""
divergence_engine.py
-----------------------
Command Center — Divergences: Price vs RSI and Price vs Volume (On-Balance
Volume) divergence detection, for Groww India, CoinDCX, US stocks, and
Commodities.

Two independent divergence checks, each comparing the last two swing lows
(bullish/positive) or swing highs (bearish/negative) in price against the
same two points on an oscillator:

1. **RSI Divergence** — classic momentum-oscillator divergence.
2. **Volume (OBV) Divergence** — On-Balance Volume is a running total that
   adds a bar's volume when price closes up and subtracts it when price
   closes down, so (unlike raw volume) "higher OBV" has the same directional
   meaning as "higher RSI" — this lets the exact same swing-comparison logic
   used for RSI apply cleanly to volume conviction as well.

A ticker's overall bias combines both checks: bullish (positive) when either
or both flag bullish with no conflicting bearish signal, bearish (negative)
symmetrically, and neutral when signals conflict or neither fires. Agreement
between RSI and Volume divergence (both firing the same direction) boosts
confidence — two independent reads confirming each other is a stronger signal
than either alone.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_obv, add_rsi
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

logger = logging.getLogger(__name__)

__all__ = ["analyze_ticker", "analyze_ticker_multi_tf", "analyze_tickers_multi_tf"]

_LOOKBACK_BARS = 500
_MIN_BARS = 80
_SWING_WINDOW = 5
_DIVERGENCE_LOOKBACK = 60


def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=_LOOKBACK_BARS)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=_LOOKBACK_BARS, market=market),
        )
    return df


def _swing_points_1d(values: np.ndarray, window: int) -> tuple[list[int], list[int]]:
    """Swing-high / swing-low bar indices for a 1D array (local extrema over a
    symmetric window)."""
    n = len(values)
    highs_idx: list[int] = []
    lows_idx: list[int] = []
    for i in range(window, n - window):
        seg = values[i - window : i + window + 1]
        if np.isnan(seg).all():
            continue
        if values[i] == np.nanmax(seg):
            highs_idx.append(i)
        if values[i] == np.nanmin(seg):
            lows_idx.append(i)
    return highs_idx, lows_idx


def _divergence_for(price: np.ndarray, osc: np.ndarray, *, window: int, lookback: int) -> dict[str, Any]:
    """Bullish (positive) / bearish (negative) divergence between price and one
    oscillator series, comparing the last two swing lows (bullish) / swing highs
    (bearish) within the lookback window."""
    n = len(price)
    start = max(0, n - lookback)
    p = price[start:]
    o = osc[start:]
    highs_idx, lows_idx = _swing_points_1d(p, window)

    out: dict[str, Any] = {"bullish": None, "bearish": None}

    if len(lows_idx) >= 2:
        i1, i2 = lows_idx[-2], lows_idx[-1]
        if not (np.isnan(o[i1]) or np.isnan(o[i2])) and p[i2] < p[i1] and o[i2] > o[i1]:
            out["bullish"] = {
                "price_1": round(float(p[i1]), 4), "price_2": round(float(p[i2]), 4),
                "osc_1": round(float(o[i1]), 4), "osc_2": round(float(o[i2]), 4),
                "bars_ago": len(p) - 1 - i2,
            }

    if len(highs_idx) >= 2:
        i1, i2 = highs_idx[-2], highs_idx[-1]
        if not (np.isnan(o[i1]) or np.isnan(o[i2])) and p[i2] > p[i1] and o[i2] < o[i1]:
            out["bearish"] = {
                "price_1": round(float(p[i1]), 4), "price_2": round(float(p[i2]), 4),
                "osc_1": round(float(o[i1]), 4), "osc_2": round(float(o[i2]), 4),
                "bars_ago": len(p) - 1 - i2,
            }

    return out


def _classify(rsi_div: dict, vol_div: dict, currency_fmt: str = ",.4g") -> tuple[str, float, list[str]]:
    reasons: list[str] = []
    bull_hits: list[str] = []
    bear_hits: list[str] = []

    if rsi_div.get("bullish"):
        d = rsi_div["bullish"]
        bull_hits.append("RSI")
        reasons.append(
            f"🟢 **Positive (Bullish) RSI Divergence** — price made a lower low "
            f"({d['price_2']:{currency_fmt}} vs {d['price_1']:{currency_fmt}}) while RSI made a "
            f"higher low ({d['osc_2']} vs {d['osc_1']}), {d['bars_ago']} bar(s) ago. Downside "
            "momentum is fading even as price falls — a classic reversal-up setup."
        )
    if rsi_div.get("bearish"):
        d = rsi_div["bearish"]
        bear_hits.append("RSI")
        reasons.append(
            f"🔴 **Negative (Bearish) RSI Divergence** — price made a higher high "
            f"({d['price_2']:{currency_fmt}} vs {d['price_1']:{currency_fmt}}) while RSI made a "
            f"lower high ({d['osc_2']} vs {d['osc_1']}), {d['bars_ago']} bar(s) ago. Upside "
            "momentum is fading even as price rises — a classic reversal-down setup."
        )
    if vol_div.get("bullish"):
        d = vol_div["bullish"]
        bull_hits.append("Volume (OBV)")
        reasons.append(
            f"🟢 **Positive (Bullish) Volume Divergence** — price made a lower low "
            f"({d['price_2']:{currency_fmt}} vs {d['price_1']:{currency_fmt}}) while On-Balance "
            f"Volume made a higher low, {d['bars_ago']} bar(s) ago. Sellers are losing "
            "conviction even as price falls — accumulation likely underway beneath the surface."
        )
    if vol_div.get("bearish"):
        d = vol_div["bearish"]
        bear_hits.append("Volume (OBV)")
        reasons.append(
            f"🔴 **Negative (Bearish) Volume Divergence** — price made a higher high "
            f"({d['price_2']:{currency_fmt}} vs {d['price_1']:{currency_fmt}}) while On-Balance "
            f"Volume made a lower high, {d['bars_ago']} bar(s) ago. Buyers are losing "
            "conviction even as price rises — distribution likely underway beneath the surface."
        )

    if bull_hits and not bear_hits:
        bias = "BULLISH"
        confidence = 60.0 + (18.0 if len(bull_hits) >= 2 else 0.0)
        reasons.insert(0, f"{len(bull_hits)} of 2 checks agree on a positive (bullish) divergence: {', '.join(bull_hits)}.")
    elif bear_hits and not bull_hits:
        bias = "BEARISH"
        confidence = 60.0 + (18.0 if len(bear_hits) >= 2 else 0.0)
        reasons.insert(0, f"{len(bear_hits)} of 2 checks agree on a negative (bearish) divergence: {', '.join(bear_hits)}.")
    elif bull_hits and bear_hits:
        bias = "NEUTRAL"
        confidence = 35.0
        reasons.append(
            "⚠️ Conflicting signals — RSI and Volume divergence disagree on direction. "
            "No clean directional read; treat with caution."
        )
    else:
        bias = "NEUTRAL"
        confidence = 0.0
        reasons.append("No RSI or Volume (OBV) divergence detected against the last two swing points.")

    return bias, round(min(96.0, confidence), 1), reasons


def analyze_ticker(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_ohlcv(ticker, market, timeframe, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < _MIN_BARS:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "error": f"Insufficient {timeframe} data ({len(df)} bars, need {_MIN_BARS}+).",
        }

    work = add_rsi(df.copy(), 14)
    work = add_obv(work)
    close = work["close"].values

    rsi_div = _divergence_for(close, work["rsi_14"].values, window=_SWING_WINDOW, lookback=_DIVERGENCE_LOOKBACK)
    vol_div = _divergence_for(close, work["obv"].values, window=_SWING_WINDOW, lookback=_DIVERGENCE_LOOKBACK)
    bias, confidence, reasons = _classify(rsi_div, vol_div)

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe,
        "price": float(work["close"].iloc[-1]),
        "bias": bias,
        "confidence_pct": confidence,
        "rsi_divergence": rsi_div,
        "volume_divergence": vol_div,
        "reasons": reasons,
    }


def analyze_ticker_multi_tf(
    ticker: str, timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """One ticker, independently analyzed **per selected timeframe**."""
    per_tf: dict[str, dict[str, Any]] = {}
    for tf in timeframes:
        try:
            per_tf[tf] = analyze_ticker(ticker, tf, market, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.debug("Divergence analysis failed for %s %s: %s", ticker, tf, exc)
            per_tf[tf] = {"ticker": ticker, "market": market, "timeframe": tf, "error": str(exc)[:200]}
    return {"ticker": ticker, "market": market, "per_tf": per_tf}


def analyze_tickers_multi_tf(
    tickers: list[str], timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    return [
        analyze_ticker_multi_tf(ticker, timeframes, market, groww_token=groww_token, exchange=exchange)
        for ticker in tickers
    ]
