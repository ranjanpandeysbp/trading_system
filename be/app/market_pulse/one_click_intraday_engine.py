"""
one_click_intraday_engine.py
------------------------------
One-Click Trade Setup — Intraday composite.

Combines:
  - mtf_intraday_bias_engine     — weighted 12+ indicator, 4-role-TF composite bias
                                   (app.market_pulse.mtf_intraday_bias_engine)
  - intraday_mtf_breakout_retest — HTF-aligned, "clean traffic"-filtered opening-range
                                   breakout + retest trigger
                                   (app.trading_hubs.intraday_mtf_breakout_retest_engine)

PORTING NOTE — momentum_engine unavailable in this backend:
  The original truebacktesting composite used `momentum_engine.analyze_ticker()` for
  two roles: (1) an independent multi-timeframe regime classifier (trending vs.
  range-bound) that GATED whether the breakout-retest vote was trusted at all, and
  (2) a non-voting confidence adjustment from its ADX-based strength read.
  `momentum_engine` has not been ported into this backend (it is not present under
  app.trading_hubs.* or app.market_pulse.*), so per the porting instructions this
  vote/context source is dropped rather than failing the whole composite: the regime
  gate is removed (the breakout-retest vote always participates) and the final
  strength-based confidence nudge is skipped. This is flagged in `combo["reasons"]`
  and in the returned `"regime"` field (always "UNAVAILABLE") so callers can see the
  composite is running as a plain 2-of-2 confluence rather than the original
  regime-routed 3-source design.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.trading_hubs import intraday_mtf_breakout_retest_engine as breakout_retest
from app.market_pulse import mtf_intraday_bias_engine as mtf_bias
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.one_click_common import (
    STRICT,
    combine_confluence,
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

    bias_vote = vote_from_mtf_bias(bias_result)
    retest_vote = vote_from_live_schema("Breakout + Retest", retest_result)

    votes = [bias_vote, retest_vote]

    combo = combine_confluence(
        votes,
        strictness=cfg.strictness,
        min_agree_strict=2,
        min_agree_loose=1,
        take_threshold_strict=66.0,
        take_threshold_loose=52.0,
    )
    combo["reasons"].append(
        "⚠️ Regime gate unavailable — momentum_engine is not ported into this backend, so the "
        "Breakout+Retest vote is not suppressed on ranging days as in the original design; "
        "this is a plain 2-of-2 confluence instead of the original regime-routed 3-source design."
    )

    return {
        "ticker": ticker,
        "market": market,
        "style": "intraday",
        "regime": "UNAVAILABLE",
        "combo": combo,
        "sub_results": {"mtf_bias": bias_result, "breakout_retest": retest_result},
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
