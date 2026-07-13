"""
one_click_scalping_engine.py
------------------------------
One-Click Trade Setup — Scalping composite.

Combines two structurally-independent liquidity-zone detectors that both require
price to be at the same HTF extreme but confirm entry differently:
  - scalp_crt_fvg_engine   — HTF CRT sweep + LTF Fair Value Gap (two-stage TP built in)
                             (app.trading_hubs.scalp_crt_fvg_engine)
  - scalp_sr_mss_engine    — HTF S/R zone + 1m Market Structure Shift
                             (app.trading_hubs.scalp_sr_mss_engine)

Both must be in the SAME direction (and, in strict mode, both must independently
fire) before a TAKE verdict. A session/kill-zone filter (from
app.trading_hubs.smc_golden_bullet_engine._in_killzone) and a volume (RVOL) check
adjust confidence up/down around that core confluence.

PORTING NOTE — momentum_engine unavailable in this backend:
  The original composite also read `momentum_engine.analyze_ticker()` (1m/5m/15m/1h)
  as a non-voting fast-timeframe trend+ADX-strength confidence filter. That module
  has not been ported into this backend (not present under app.trading_hubs.* or
  app.market_pulse.*), so per the porting instructions this non-voting context
  source is dropped — the composite's core two-engine vote and session/volume
  adjustments are otherwise unchanged and fully faithful to the original.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.one_click_common import (
    STRICT,
    combine_confluence,
    vote_from_live_schema,
)
from app.trading_hubs import scalp_crt_fvg_engine as crt_fvg
from app.trading_hubs import scalp_sr_mss_engine as sr_mss
from app.trading_hubs.smc_golden_bullet_engine import _in_killzone

logger = logging.getLogger(__name__)

_INDIA_SESSION_WINDOWS = [(9, 11), (13, 15)]  # IST hours — avoid the lunchtime chop


@dataclass
class OneClickScalpConfig:
    htf: str = "1h"
    ltf: str = "5m"
    strictness: str = STRICT
    rvol_lookback: int = 20
    lookback_bars: int = 400


def _session_ok(market: str, ltf_df: pd.DataFrame) -> tuple[bool, str]:
    if ltf_df is None or ltf_df.empty:
        return False, "No timestamp available for session check"
    ts = ltf_df.index[-1]
    if "CoinDCX" in market or "US Stocks" in market:
        ok, label = _in_killzone(pd.Timestamp(ts))
        return ok, (f"In kill zone ({label})" if ok else "Outside London/NY kill-zone hours")
    # India — approximate local session windows
    ist = pd.Timestamp(ts)
    if ist.tzinfo is not None:
        ist = ist.tz_convert("Asia/Kolkata")
    hour = ist.hour
    for start, end in _INDIA_SESSION_WINDOWS:
        if start <= hour < end:
            return True, f"Within active session window ({start}:00-{end}:00 IST)"
    return False, "Outside active session windows (avoiding midday chop)"


def _rvol(df: pd.DataFrame, lookback: int) -> float | None:
    if df is None or df.empty or "volume" not in df.columns or len(df) < lookback + 1:
        return None
    avg = df["volume"].iloc[-lookback - 1:-1].mean()
    if not avg or avg <= 0:
        return None
    return float(df["volume"].iloc[-1] / avg)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: OneClickScalpConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or OneClickScalpConfig()

    crt_result = crt_fvg.analyze_ticker(
        ticker, market, cfg=crt_fvg.CrtFvgConfig(htf=cfg.htf, ltf=cfg.ltf),
        groww_token=groww_token, exchange=exchange,
    )
    srmss_result = sr_mss.analyze_ticker(
        ticker, market, cfg=sr_mss.SrMssConfig(htf=cfg.htf),
        groww_token=groww_token, exchange=exchange,
    )

    votes = [
        vote_from_live_schema("CRT-FVG sweep", crt_result),
        vote_from_live_schema("HTF S/R + 1m MSS", srmss_result),
    ]

    is_crypto = "CoinDCX" in market
    ltf_df = normalize_ohlcv(fetch_data_for_gap_scan(ticker, cfg.ltf, market, groww_token, exchange, limit=cfg.lookback_bars))
    if ltf_df.empty:
        ltf_df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, cfg.ltf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market))

    session_ok, session_note = _session_ok(market, ltf_df)
    rvol = _rvol(ltf_df, cfg.rvol_lookback)
    rvol_note = f"RVOL {rvol:.2f}x 20-bar avg volume" if rvol is not None else "Volume data unavailable"

    min_agree_strict = 2  # BOTH liquidity-zone detectors must independently fire
    min_agree_loose = 1

    combo = combine_confluence(
        votes,
        strictness=cfg.strictness,
        min_agree_strict=min_agree_strict,
        min_agree_loose=min_agree_loose,
        take_threshold_strict=68.0,
        take_threshold_loose=55.0,
    )

    # Session + volume adjust confidence only when there's an actual directional signal;
    # hard-gate on session only in strict mode.
    has_direction = combo["direction"] in ("LONG", "SHORT")
    if not session_ok:
        if cfg.strictness == STRICT and has_direction:
            combo["take_trade"] = False
            combo["verdict"] = "NO TRADE (outside session window)"
        elif has_direction:
            combo["confidence_pct"] = max(0.0, combo["confidence_pct"] - 12.0)
        combo["reasons"].append(f"⏱️ Session: {session_note}")
    else:
        if has_direction:
            combo["confidence_pct"] = min(96.0, combo["confidence_pct"] + 5.0)
        combo["reasons"].append(f"⏱️ Session: {session_note}")

    if rvol is not None:
        if has_direction:
            if rvol >= 1.5:
                combo["confidence_pct"] = min(96.0, combo["confidence_pct"] + 6.0)
            elif rvol < 0.7:
                combo["confidence_pct"] = max(0.0, combo["confidence_pct"] - 8.0)
        combo["reasons"].append(f"📊 Volume: {rvol_note}")
    else:
        combo["reasons"].append(f"📊 Volume: {rvol_note}")

    combo["reasons"].append(
        "⚠️ Momentum filter unavailable — momentum_engine (1m/5m/15m/1h) is not ported into this "
        "backend, so no fast-timeframe strength adjustment is applied (core two-engine vote and "
        "session/volume adjustments are unaffected)."
    )

    # Re-check take_trade against threshold after adjustments (strict mode only re-gates session above).
    combo["take_trade"] = combo["take_trade"] and has_direction and combo["confidence_pct"] >= combo["take_threshold"]

    return {
        "ticker": ticker,
        "market": market,
        "style": "scalping",
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "session_ok": session_ok,
        "rvol": round(rvol, 2) if rvol is not None else None,
        "combo": combo,
        "sub_results": {"crt_fvg": crt_result, "sr_mss": srmss_result},
    }


def analyze_tickers(
    tickers: list[str],
    market: str,
    *,
    cfg: OneClickScalpConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    cfg = cfg or OneClickScalpConfig()
    out = []
    for t in tickers:
        try:
            out.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("one-click scalping failed for %s: %s", t, exc)
            out.append({"ticker": t, "market": market, "style": "scalping", "error": str(exc)[:200]})
    return out


# ---------------------------------------------------------------------------
# Backtest — trend filter + CRT-FVG-style sweep/gap trigger, replayed historically.
# ---------------------------------------------------------------------------

def _historical_signal_series(df: pd.DataFrame, trend_lookback: int = 20, max_sweep_age: int = 4) -> pd.DataFrame:
    work = crt_fvg.identify_trend(df, trend_lookback)
    work = crt_fvg.detect_crt_sweep(work)
    work = crt_fvg.find_fair_value_gaps(work)

    direction = [None] * len(work)
    for i in range(len(work)):
        window_start = max(0, i - max_sweep_age)
        recent = work.iloc[window_start:i + 1]
        nonzero = recent[recent["crt_signal"] != 0]
        if nonzero.empty:
            continue
        sweep_dir = "LONG" if int(nonzero.iloc[-1]["crt_signal"]) == crt_fvg.SIGNAL_BUY else "SHORT"
        fvg_col = "bullish_fvg" if sweep_dir == "LONG" else "bearish_fvg"
        if bool(work.iloc[i][fvg_col]):
            direction[i] = sweep_dir

    work["direction"] = direction
    return work


def run_backtest(
    ticker: str,
    start_date: str,
    end_date: str,
    market: str,
    *,
    timeframe: str = "1d",
    strictness: str = STRICT,
    groww_token: str = "",
    exchange: str = "NSE",
    sl_pct: float = 1.0,
) -> dict[str, Any]:
    from backtesting.data_fetcher import get_historical_data
    from app.market_pulse.one_click_common import simulate_two_stage_backtest

    df = get_historical_data(
        ticker, start_date, end_date, market=market, timeframe=timeframe,
        groww_token=groww_token, groww_exchange=exchange,
    )
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        return {"ticker": ticker, "error": "Insufficient historical data for backtest."}

    signals = _historical_signal_series(df)
    tp1_rr, tp2_rr = (1.0, 2.5) if strictness == STRICT else (1.0, 2.0)
    result = simulate_two_stage_backtest(df, signals, sl_pct=sl_pct, tp1_rr=tp1_rr, tp2_rr=tp2_rr, max_hold_bars=30)

    return {
        "ticker": ticker,
        "market": market,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "strictness": strictness,
        "bars": len(df),
        "note": "Backtest validates the core HTF-trend + CRT sweep/FVG trigger only — the live scan's "
                "additional S/R-MSS confirmation, session/kill-zone gate, and volume filter are not "
                "modeled here (they require live intraday microstructure not reliably available historically).",
        **result,
    }
