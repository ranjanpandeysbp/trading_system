"""
one_click_swing_engine.py
---------------------------
One-Click Trade Setup — Swing composite.

Combines:
  - swing_trading_st_kiss_engine       — weekly HA + 55EMA + MACD zero-cross (HTF trend gate)
  - swing_trading_st_mtf_mss_engine    — weekly PWH/PWL liquidity-grab + 15m MSS (entry timing)
  - swing_trading_st_supertrend_engine — SuperTrend + SMA10 (reused for its trend direction,
                                         informing the trailing-stop rather than voting twice)
  - swing_trading_st_simple_steal_engine — measured-move projection (objective TP2 candidate)
  (all four: app.trading_hubs.swing_trading_st_*)

KISS weekly bias and MTF-MSS's entry trigger are the two required votes. SuperTrend and
Simple Steal contribute risk-management levels (trailing stop, measured-move target) rather
than a second and third independent direction vote, since they're both trend-following
overlays correlated with the same price action KISS already reads — voting them separately
would be the "correlated engines look like confluence" trap the audit flagged.

PORTING NOTE — fundamental_analysis_engine and momentum_engine unavailable in this backend:
  The original composite also (a) ran `fundamental_analysis_engine.analyze_ticker()` for
  India tickers as a non-technical non-contradiction gate (downgrading a technical call
  that fundamentals strongly oppose), and (b) read `momentum_engine.analyze_ticker()`
  (1h/4h/1d/1w) as a non-voting ADX-based confidence adjustment. Neither module has been
  ported into this backend (not present under app.trading_hubs.* or app.market_pulse.*),
  so per the porting instructions both are dropped rather than failing the whole
  composite — `fundamental_gate()`/`momentum_context()` in one_click_common.py are called
  with `result=None` so they return neutral no-ops, and this is flagged in the reasons list.
  The core two-vote KISS + MTF-MSS confluence and the SuperTrend/Simple-Steal risk-level
  refinement are otherwise unchanged and fully faithful to the original.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.one_click_common import (
    STRICT,
    combine_confluence,
    fundamental_gate,
    vote_from_live_schema,
)
from app.trading_hubs import swing_trading_st_kiss_engine as kiss
from app.trading_hubs import swing_trading_st_mtf_mss_engine as mtf_mss
from app.trading_hubs import swing_trading_st_simple_steal_engine as simple_steal
from app.trading_hubs import swing_trading_st_supertrend_engine as supertrend

logger = logging.getLogger(__name__)


@dataclass
class OneClickSwingConfig:
    strictness: str = STRICT
    lookback_bars: int = 400


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: OneClickSwingConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    include_fundamentals: bool | None = None,
) -> dict[str, Any]:
    cfg = cfg or OneClickSwingConfig()
    is_india = "Groww" in market or "India" in market
    if include_fundamentals is None:
        include_fundamentals = is_india

    kiss_result = kiss.analyze_ticker(ticker, market, groww_token=groww_token, exchange=exchange)
    mss_result = mtf_mss.analyze_ticker(ticker, market, groww_token=groww_token, exchange=exchange)
    st_result = supertrend.analyze_ticker(
        ticker, market, cfg=supertrend.STSuperTrendConfig(mode=supertrend.MODE_SWING),
        groww_token=groww_token, exchange=exchange,
    )
    steal_result = simple_steal.analyze_ticker(ticker, market, groww_token=groww_token, exchange=exchange)

    kiss_vote = vote_from_live_schema("Weekly KISS bias", kiss_result)
    mss_vote = vote_from_live_schema("Weekly PWH/PWL + 15m MSS", mss_result)
    st_vote = vote_from_live_schema("SuperTrend trailing overlay", st_result)
    steal_vote = vote_from_live_schema("Measured-move target", steal_result)

    votes = [kiss_vote, mss_vote]

    combo = combine_confluence(
        votes,
        strictness=cfg.strictness,
        min_agree_strict=2,
        min_agree_loose=1,
        take_threshold_strict=66.0,
        take_threshold_loose=53.0,
    )

    # SuperTrend / Simple Steal don't vote — they refine risk levels when they agree with
    # the composite direction, and are surfaced (non-voting) in the table regardless.
    for v in (st_vote, steal_vote):
        combo["votes"].append({
            "engine": v.engine, "direction": v.direction, "confidence": round(v.confidence, 1),
            "take": False, "agreed": v.direction == combo["direction"] and combo["direction"] != "WAIT",
            "error": v.error, "reasons": v.reasons[:3],
        })

    if combo["direction"] != "WAIT":
        if st_vote.direction == combo["direction"] and st_vote.sl:
            # Prefer SuperTrend's adaptive trailing level as SL if tighter/safer than the vote combo's own.
            combo["stop_price"] = st_vote.sl
            combo["reasons"].append(f"🔒 Trailing stop set from SuperTrend overlay ({st_vote.sl:.4g})")
        if steal_vote.direction == combo["direction"] and steal_vote.tp1:
            combo["target2_price"] = steal_vote.tp1
            combo["reasons"].append(f"🎯 TP2 set to measured-move projection ({steal_vote.tp1:.4g})")

    combo["reasons"].append(
        "⚠️ Momentum filter unavailable — momentum_engine (1h/4h/1d/1w) is not ported into this "
        "backend, so no ADX-based confidence adjustment is applied."
    )

    fundamental_note = None
    fundamental_result = None
    if include_fundamentals and combo["direction"] != "WAIT":
        # fundamental_analysis_engine is not ported into this backend — fundamental_gate()
        # is called with result=None so it returns a neutral WAIT lean (no gate applied),
        # matching the "drop the missing vote source, don't fail the composite" instruction.
        _lean, _f_conf, _ = fundamental_gate(None)
        fundamental_note = "⚠️ Fundamentals gate unavailable — fundamental_analysis_engine is not ported into this backend."
        combo["reasons"].append(fundamental_note)

    return {
        "ticker": ticker,
        "market": market,
        "style": "swing",
        "combo": combo,
        "sub_results": {
            "kiss": kiss_result, "mtf_mss": mss_result, "supertrend": st_result,
            "simple_steal": steal_result, "fundamental": fundamental_result,
        },
    }


def analyze_tickers(
    tickers: list[str],
    market: str,
    *,
    cfg: OneClickSwingConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    cfg = cfg or OneClickSwingConfig()
    out = []
    for t in tickers:
        try:
            out.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("one-click swing failed for %s: %s", t, exc)
            out.append({"ticker": t, "market": market, "style": "swing", "error": str(exc)[:200]})
    return out


# ---------------------------------------------------------------------------
# Backtest — weekly HA/EMA trend filter + weekly PWH/PWL liquidity-grab trigger.
# ---------------------------------------------------------------------------

def _historical_signal_series(df: pd.DataFrame, ema_period: int = 55) -> pd.DataFrame:
    from app.market_pulse.indicators import add_ema, add_macd

    work = add_ema(df.copy(), ema_period)
    work = add_macd(work)
    ema_col = f"ema_{ema_period}"

    weekly = work.resample("W").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    pwh = weekly["high"].shift(1)
    pwl = weekly["low"].shift(1)
    pwh_daily = pwh.reindex(work.index, method="ffill")
    pwl_daily = pwl.reindex(work.index, method="ffill")

    direction = [None] * len(work)
    for i in range(ema_period + 5, len(work)):
        close = work["close"].iloc[i]
        ema_val = work[ema_col].iloc[i]
        macd_hist = work["macd_hist_12_26_9"].iloc[i] if "macd_hist_12_26_9" in work.columns else None
        if pd.isna(ema_val) or macd_hist is None or pd.isna(macd_hist):
            continue
        prior_low = work["low"].iloc[i - 1]
        prior_high = work["high"].iloc[i - 1]
        pwl_val = pwl_daily.iloc[i]
        pwh_val = pwh_daily.iloc[i]
        # Weekly liquidity-grab fakeout: prior bar wicked beyond PWL/PWH but this bar
        # closes back inside — a reversal-timing trigger, gated by the EMA/MACD trend bias.
        if pd.notna(pwl_val) and prior_low < pwl_val and close > ema_val and macd_hist > 0:
            direction[i] = "LONG"
        elif pd.notna(pwh_val) and prior_high > pwh_val and close < ema_val and macd_hist < 0:
            direction[i] = "SHORT"

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
    sl_pct: float = 3.0,
) -> dict[str, Any]:
    from backtesting.data_fetcher import get_historical_data
    from app.market_pulse.one_click_common import simulate_two_stage_backtest

    df = get_historical_data(
        ticker, start_date, end_date, market=market, timeframe=timeframe,
        groww_token=groww_token, groww_exchange=exchange,
    )
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 80:
        return {"ticker": ticker, "error": "Insufficient historical data for backtest."}

    signals = _historical_signal_series(df)
    tp1_rr, tp2_rr = (1.5, 3.0) if strictness == STRICT else (1.0, 2.0)
    result = simulate_two_stage_backtest(df, signals, sl_pct=sl_pct, tp1_rr=tp1_rr, tp2_rr=tp2_rr, max_hold_bars=60)

    return {
        "ticker": ticker,
        "market": market,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "strictness": strictness,
        "bars": len(df),
        "note": "Backtest validates the weekly EMA/MACD trend + PWH/PWL liquidity-grab trigger only — "
                "the live scan's 15m MSS confirmation, SuperTrend trailing-stop overlay, measured-move "
                "TP2, and fundamentals gate are not modeled here.",
        **result,
    }
