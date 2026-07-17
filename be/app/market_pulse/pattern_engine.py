"""
pattern_engine.py
-----------------
Command Center — Candlestick & Chart Patterns
(Groww India · CoinDCX · US stocks · Commodities).

Scans each ticker's recent price history for two families of price-action
pattern, reusing this app's existing detectors — the same ones behind the
Trade Setup drill-down — and combines everything found into one
Bullish/Bearish/Neutral bias per ticker per timeframe, weighted by each
pattern's reliability rating.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pattern_breakout_tab import detect_extended_chart_patterns
from app.market_pulse.price_action import detect_candlestick_patterns, detect_chart_patterns

logger = logging.getLogger(__name__)

__all__ = ["analyze_ticker", "analyze_ticker_multi_tf", "analyze_tickers_multi_tf"]

_LOOKBACK_BARS = 500
_MIN_BARS = 80
_RELIABILITY_WEIGHT = {"VERY HIGH": 30.0, "HIGH": 20.0, "MODERATE": 10.0}


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


def _pattern_line(p: dict) -> str:
    when = f" ({p['bars_ago']} bar(s) ago)" if p.get("bars_ago") is not None else ""
    reason = p.get("description") or p.get("notes") or ""
    return f"**{p.get('name', '—')}** [{p.get('reliability', '—')} reliability]{when} — {reason}"


def _score(items: list[dict]) -> float:
    return sum(_RELIABILITY_WEIGHT.get(str(p.get("reliability", "")).upper(), 8.0) for p in items)


def analyze_ticker(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_ohlcv(ticker, market, timeframe, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < _MIN_BARS:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "error": f"Insufficient {timeframe} data ({len(df)} bars, need {_MIN_BARS}+).",
        }

    candles = detect_candlestick_patterns(df)
    charts = detect_chart_patterns(df) + detect_extended_chart_patterns(df)
    patterns = candles + charts

    bullish = [p for p in patterns if p.get("bias") == "BULLISH"]
    bearish = [p for p in patterns if p.get("bias") == "BEARISH"]
    neutral = [p for p in patterns if p.get("bias") not in ("BULLISH", "BEARISH")]

    bull_score = _score(bullish)
    bear_score = _score(bearish)

    reasons: list[str] = []
    if bull_score > bear_score and bull_score > 0:
        bias = "BULLISH"
        confidence = round(min(95.0, 45.0 + bull_score), 1)
        reasons.append(f"{len(bullish)} bullish pattern(s) outweigh {len(bearish)} bearish — net positive read.")
    elif bear_score > bull_score and bear_score > 0:
        bias = "BEARISH"
        confidence = round(min(95.0, 45.0 + bear_score), 1)
        reasons.append(f"{len(bearish)} bearish pattern(s) outweigh {len(bullish)} bullish — net negative read.")
    elif bull_score and bear_score:
        bias = "NEUTRAL"
        confidence = 35.0
        reasons.append(
            f"Conflicting signals — {len(bullish)} bullish and {len(bearish)} bearish pattern(s) of "
            "similar weight fired together. No clean directional read; treat with caution."
        )
    else:
        bias = "NEUTRAL"
        confidence = 0.0
        reasons.append("No notable bullish or bearish candlestick/chart pattern formed in the recent bars.")

    for p in bullish:
        reasons.append(f"🟢 {_pattern_line(p)}")
    for p in bearish:
        reasons.append(f"🔴 {_pattern_line(p)}")
    for p in neutral:
        reasons.append(f"⚪ {_pattern_line(p)}")

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe,
        "price": float(df["close"].iloc[-1]) if not df.empty else None,
        "bias": bias,
        "confidence_pct": confidence,
        "bullish_patterns": bullish,
        "bearish_patterns": bearish,
        "neutral_patterns": neutral,
        "reasons": reasons,
    }


def analyze_ticker_multi_tf(
    ticker: str, timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """One ticker, independently scanned **per selected timeframe**."""
    per_tf: dict[str, dict[str, Any]] = {}
    for tf in timeframes:
        try:
            per_tf[tf] = analyze_ticker(ticker, tf, market, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.debug("Pattern scan failed for %s %s: %s", ticker, tf, exc)
            per_tf[tf] = {"ticker": ticker, "market": market, "timeframe": tf, "error": str(exc)[:200]}
    return {"ticker": ticker, "market": market, "per_tf": per_tf}


def analyze_tickers_multi_tf(
    tickers: list[str], timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    return [
        analyze_ticker_multi_tf(ticker, timeframes, market, groww_token=groww_token, exchange=exchange)
        for ticker in tickers
    ]
