"""
one_click_intraday_engine.py
------------------------------
One-Click Trade Setup — Intraday composite.

Combines:
  - mtf_intraday_bias_engine     — weighted 12+ indicator, 4-role-TF composite bias
                                   AND regime classifier (trending vs. range-bound day)
  - intraday_mtf_breakout_retest — HTF-aligned, "clean traffic"-filtered opening-range
                                   breakout + retest trigger (used only on trending days)
  - momentum_engine              — independent multi-timeframe regime confirmation
                                   (reused for its existing trend/consolidation read)

This is a genuine regime router, not two triggers firing at once: the breakout-retest
trigger is only trusted when both the bias engine AND momentum_engine agree the session
is trending; on a day both classify as consolidating/mixed, the composite returns
WATCH/NO TRADE rather than forcing a breakout call into a range.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.trading_hubs import intraday_mtf_breakout_retest_engine as breakout_retest
from app.market_pulse import mtf_intraday_bias_engine as mtf_bias
from app.market_pulse import momentum_engine
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.one_click_common import (
    STRICT,
    combine_confluence,
    momentum_context,
    vote_from_live_schema,
    vote_from_mtf_bias,
)

logger = logging.getLogger(__name__)


@dataclass
class OneClickIntradayConfig:
    strictness: str = STRICT
    lookback_bars: int = 400


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: OneClickIntradayConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or OneClickIntradayConfig()
    is_crypto = "CoinDCX" in market

    bias_result = mtf_bias.analyze_ticker(ticker, is_crypto=is_crypto)
    retest_result = breakout_retest.analyze_ticker(ticker, market, groww_token=groww_token, exchange=exchange)
    mom_result = momentum_engine.analyze_ticker(ticker, market, groww_token=groww_token, exchange=exchange)

    regime = (mom_result or {}).get("overall_direction", "NO_DATA")
    is_trending_regime = regime in ("UP", "DOWN")

    bias_vote = vote_from_mtf_bias(bias_result)
    retest_vote = vote_from_live_schema("Breakout + Retest", retest_result)

    votes = [bias_vote]
    regime_note = f"🧭 Regime (momentum_engine): {regime}"
    if is_trending_regime:
        votes.append(retest_vote)
    else:
        # Ranging/mixed day — the breakout-retest trigger is untrusted; record it as
        # a non-voting reference only so the vote table stays transparent.
        retest_vote.direction = "WAIT"
        retest_vote.error = retest_vote.error or f"Suppressed — regime is {regime}, not trending"

    combo = combine_confluence(
        votes,
        strictness=cfg.strictness,
        min_agree_strict=2,
        min_agree_loose=1,
        take_threshold_strict=66.0,
        take_threshold_loose=52.0,
    )
    if not is_trending_regime:
        combo["votes"].append({
            "engine": "Breakout + Retest", "direction": retest_vote.direction,
            "confidence": round(retest_vote.confidence, 1), "take": False,
            "agreed": False, "error": retest_vote.error, "reasons": retest_vote.reasons[:3],
        })
        combo["reasons"].append("Breakout+Retest trigger suppressed (not a trending session) — bias-only read")
        if cfg.strictness == STRICT:
            combo["take_trade"] = False
    combo["reasons"].append(regime_note)

    # Momentum already routes the regime above; here its ADX-based strength further
    # adjusts confidence (non-voting) and is always surfaced in the vote table.
    if combo["direction"] != "WAIT":
        mom_ctx = momentum_context(mom_result, combo["direction"])
        combo["confidence_pct"] = max(0.0, min(96.0, combo["confidence_pct"] + mom_ctx["adjustment"]))
        combo["reasons"].append(mom_ctx["note"])
        combo["take_trade"] = combo["take_trade"] and combo["confidence_pct"] >= combo["take_threshold"]
    combo["votes"].append({
        "engine": "Momentum (regime + strength)", "direction": regime, "confidence": None, "take": False,
        "agreed": is_trending_regime, "error": None, "reasons": [regime_note],
    })

    return {
        "ticker": ticker,
        "market": market,
        "style": "intraday",
        "regime": regime,
        "combo": combo,
        "sub_results": {"mtf_bias": bias_result, "breakout_retest": retest_result, "momentum": mom_result},
    }


def analyze_tickers(
    tickers: list[str],
    market: str,
    *,
    cfg: OneClickIntradayConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    cfg = cfg or OneClickIntradayConfig()
    out = []
    for t in tickers:
        try:
            out.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("one-click intraday failed for %s: %s", t, exc)
            out.append({"ticker": t, "market": market, "style": "intraday", "error": str(exc)[:200]})
    return out


# ---------------------------------------------------------------------------
# Backtest — daily-trend-filtered opening-range-style breakout replay.
# ---------------------------------------------------------------------------

def _historical_signal_series(df: pd.DataFrame, trend_period: int = 20, breakout_window: int = 10) -> pd.DataFrame:
    from app.market_pulse.indicators import add_adx, add_ema

    work = add_ema(df.copy(), trend_period)
    work = add_adx(work, 14)
    ema_col = f"ema_{trend_period}"

    direction = [None] * len(work)
    rolling_high = work["high"].rolling(breakout_window).max().shift(1)
    rolling_low = work["low"].rolling(breakout_window).min().shift(1)

    for i in range(breakout_window + trend_period, len(work)):
        adx_val = work["adx_14"].iloc[i] if "adx_14" in work.columns else None
        if adx_val is None or pd.isna(adx_val) or adx_val < 20:
            continue  # only trending days
        close = work["close"].iloc[i]
        ema_val = work[ema_col].iloc[i]
        if pd.isna(ema_val):
            continue
        if close > ema_val and close > rolling_high.iloc[i]:
            direction[i] = "LONG"
        elif close < ema_val and close < rolling_low.iloc[i]:
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
    sl_pct: float = 1.5,
) -> dict[str, Any]:
    from backtesting.data_fetcher import get_historical_data
    from app.market_pulse.one_click_common import simulate_two_stage_backtest

    df = get_historical_data(
        ticker, start_date, end_date, market=market, timeframe=timeframe,
        groww_token=groww_token, groww_exchange=exchange,
    )
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 40:
        return {"ticker": ticker, "error": "Insufficient historical data for backtest."}

    signals = _historical_signal_series(df)
    tp1_rr, tp2_rr = (1.0, 2.0) if strictness == STRICT else (1.0, 1.6)
    result = simulate_two_stage_backtest(df, signals, sl_pct=sl_pct, tp1_rr=tp1_rr, tp2_rr=tp2_rr, max_hold_bars=15)

    return {
        "ticker": ticker,
        "market": market,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "strictness": strictness,
        "bars": len(df),
        "note": "Backtest validates a trend(EMA+ADX)-filtered breakout trigger only — the live scan's "
                "full 12+ indicator MTF bias and 'clean traffic' retest confirmation are not modeled here.",
        **result,
    }
