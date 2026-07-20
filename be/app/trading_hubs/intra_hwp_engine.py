"""
intra_hwp_engine.py
----------------------
INTRA - HWP — "Two-Sided Gap Fill" with 21 EMA.
Video: "Try This Intraday Strategy In 2026 | Nifty, Stocks & Options" (HOLD with Priyank Live)
https://www.youtube.com/watch?v=Q_TY4lQrSZc

Core idea: the market rarely fills an opening gap in only one direction.
Mark the gap between the Previous Day's Close (PDC) and Today's Open (TO).
Once price tags the PDC (Side 1 of the gap), the strategy anticipates a
reversal back toward Today's Open (Side 2), timed on a 5-minute chart by a
21-period EMA cross:

- Gap DOWN (Today's Open < PDC): wait for price to rally and tag the PDC,
  then go SHORT the moment a 5m candle closes back below the 21 EMA.
- Gap UP (Today's Open > PDC): wait for price to fall and tag the PDC,
  then go LONG the moment a 5m candle closes back above the 21 EMA.

Target: Today's Open. Stop-loss: beyond the swing extreme since the PDC tag,
ATR-buffered (structural-stop convention rather than a fixed distance).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.trading_hubs.session_constants import IST_TZ, NY_TZ
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import _calc_atr
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_INTRA_HWP_URL = "https://www.youtube.com/watch?v=Q_TY4lQrSZc"

EXEC_TF = "5m"
HOLD_HWP = "Same session — enter on the EMA cross-back after the gap tag, exit at Today's Open or session close"

PHASE_NO_GAP = "NO_GAP"
PHASE_AWAIT_TAG = "AWAITING_GAP_TAG"
PHASE_AWAIT_CROSS = "AWAITING_EMA_CROSS"
PHASE_ENTRY = "ENTRY_TRIGGERED"


# Local copy of truebacktesting.fakeout_4h_engine.session_mode_for_market —
# that module has not been ported/available to this backend build, so this
# is kept self-contained here rather than editing shared modules (same
# convention as intraday_7_wasted_engine.py / intraday_mtf_breakout_retest_engine.py).
def session_mode_for_market(market: str) -> str:
    """Groww India stocks -> IST session; CoinDCX / others -> NY session."""
    if "Groww" in market or "India" in market:
        return "india"
    return "ny"


@dataclass
class HwpConfig:
    ema_period: int = 21
    min_gap_pct: float = 0.15
    swing_lookback: int = 10
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 60.0
    min_bars: int = 60


def _fetch_ohlcv(
    ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, EXEC_TF, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, EXEC_TF, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def _session_tz(market: str):
    return IST_TZ if session_mode_for_market(market) == "india" else NY_TZ


def _localize(df: pd.DataFrame, market: str) -> pd.DataFrame:
    work = df.copy()
    tz = _session_tz(market)
    if work.index.tz is None:
        work.index = work.index.tz_localize(tz)
    else:
        work.index = work.index.tz_convert(tz)
    return work


def analyze_ticker(
    ticker: str, market: str, *, cfg: HwpConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or HwpConfig()
    df = _fetch_ohlcv(ticker, market, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {EXEC_TF} data ({len(df)} bars, need {cfg.min_bars}+)."}

    work = _localize(df, market)
    session_dates = pd.Series(work.index.date, index=work.index)
    unique_days = sorted(session_dates.unique())
    if len(unique_days) < 2:
        return {"ticker": ticker, "market": market, "error": "Need at least 2 session days of 5m data for a prior close."}

    day_groups = work.groupby(session_dates)
    today = unique_days[-1]
    prior_day = unique_days[-2]
    today_df = day_groups.get_group(today)
    prior_df = day_groups.get_group(prior_day)

    today_open = float(today_df["open"].iloc[0])
    prior_close = float(prior_df["close"].iloc[-1])
    price = float(today_df["close"].iloc[-1])
    atr = _calc_atr(work, 14)
    if not atr or atr <= 0:
        atr = max(price * 0.003, 1e-6)

    gap_pct = (today_open - prior_close) / prior_close * 100 if prior_close else 0.0
    is_gap_down = gap_pct <= -cfg.min_gap_pct
    is_gap_up = gap_pct >= cfg.min_gap_pct

    base = {
        "ticker": ticker, "market": market, "timeframe": EXEC_TF,
        "price": price, "atr": round(float(atr), 6),
        "gap_pct": round(gap_pct, 3), "today_open": round(today_open, 6), "prior_close": round(prior_close, 6),
    }

    if not (is_gap_down or is_gap_up):
        base["phase"] = PHASE_NO_GAP
        base["live"] = enrich_intra_live({
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT", "phase": PHASE_NO_GAP, "confidence_pct": 0.0,
            "reasons": [
                f"Gap is only {gap_pct:.2f}% — below the {cfg.min_gap_pct}% noise threshold, no valid "
                f"two-sided setup today.",
            ],
        }, hold_duration=HOLD_HWP)
        return base

    # EMA computed on the continuous series (a trend indicator, not session-reset like VWAP).
    ema_full = work["close"].ewm(span=cfg.ema_period, adjust=False).mean()
    today_ema = ema_full.loc[today_df.index]

    highs = today_df["high"].values
    lows = today_df["low"].values
    closes = today_df["close"].values
    n = len(today_df)

    tag_idx = None
    if is_gap_down:
        for i in range(n):
            if highs[i] >= prior_close:
                tag_idx = i
                break
    else:
        for i in range(n):
            if lows[i] <= prior_close:
                tag_idx = i
                break

    if tag_idx is None:
        direction_word = "rally up to" if is_gap_down else "drop down to"
        base["phase"] = PHASE_AWAIT_TAG
        base["live"] = enrich_intra_live({
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT", "phase": PHASE_AWAIT_TAG, "confidence_pct": 30.0,
            "reasons": [
                f"Gap {'down' if is_gap_down else 'up'} of {abs(gap_pct):.2f}% — waiting for price to "
                f"{direction_word} yesterday's close ({prior_close:,.4g}) before Side 1 of the two-sided "
                f"fill is even tagged.",
            ],
        }, hold_duration=HOLD_HWP)
        return base

    direction = "SHORT" if is_gap_down else "LONG"
    entry_idx = None
    for i in range(tag_idx + 1, n):
        c = closes[i]
        e = today_ema.iloc[i]
        prev_c = closes[i - 1]
        prev_e = today_ema.iloc[i - 1]
        if pd.isna(e) or pd.isna(prev_e):
            continue
        if is_gap_down and c < e and prev_c >= prev_e:
            entry_idx = i
            break
        if is_gap_up and c > e and prev_c <= prev_e:
            entry_idx = i
            break

    if entry_idx is None:
        base["phase"] = PHASE_AWAIT_CROSS
        base["live"] = enrich_intra_live({
            "signal": "NONE", "direction": direction, "take_trade": False,
            "verdict": f"WATCH {direction}", "phase": PHASE_AWAIT_CROSS, "confidence_pct": 48.0,
            "reasons": [
                f"Side 1 filled — price tagged yesterday's close ({prior_close:,.4g}) "
                f"{n - 1 - tag_idx} bar(s) ago. Now watching for a 5m close "
                f"{'below' if is_gap_down else 'above'} the {cfg.ema_period} EMA to trigger the reversal "
                f"back toward today's open ({today_open:,.4g}).",
            ],
        }, hold_duration=HOLD_HWP)
        return base

    bars_since_entry = n - 1 - entry_idx
    fresh = bars_since_entry <= 2

    swing_start = max(tag_idx, entry_idx - cfg.swing_lookback)
    if direction == "SHORT":
        swing_extreme = float(np.max(highs[swing_start:entry_idx + 1]))
        stop = swing_extreme + atr * 0.25
    else:
        swing_extreme = float(np.min(lows[swing_start:entry_idx + 1]))
        stop = swing_extreme - atr * 0.25

    target = today_open
    sl_dist = abs(stop - price)
    tp_dist = abs(target - price)
    sl_pct = round(sl_dist / price * 100, 2) if price else 0.0
    tp_pct = round(tp_dist / price * 100, 2) if price else 0.0
    conf = 78.0 if fresh else 55.0
    take = fresh and tp_dist > 0 and sl_dist > 0 and conf >= cfg.take_confidence_threshold

    reasons = [
        f"Two-sided gap fill: {'gap down' if is_gap_down else 'gap up'} {abs(gap_pct):.2f}%, Side 1 tagged "
        f"at yesterday's close ({prior_close:,.4g}), Side 2 EMA-cross entry "
        f"{'just triggered' if fresh else f'fired {bars_since_entry} bars ago (stale — do not chase)'}.",
        f"Target = today's open ({today_open:,.4g}). Stop beyond the swing "
        f"{'high' if direction == 'SHORT' else 'low'} since the tag ({swing_extreme:,.4g}), ATR-buffered.",
    ]

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=EXEC_TF,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
        confidence_pct=conf,
        style="intraday",
        exit_rule="Exit if price closes back through the EMA against the trade, or at session close, whichever comes first.",
        max_hold_exit="Time stop: same session, exit by close.",
    )

    base["phase"] = PHASE_ENTRY
    base["live"] = enrich_intra_live({
        "signal": "BUY" if direction == "LONG" else "SELL",
        "direction": direction,
        "take_trade": take,
        "verdict": f"{'TAKE' if take else 'WATCH'} {direction}",
        "phase": PHASE_ENTRY,
        "confidence_pct": conf,
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "reasons": reasons,
        "trade_plan": {**plan, "direction": direction if take else "—", "holding_period": HOLD_HWP},
    }, hold_duration=HOLD_HWP)
    return base


def scan_universe(
    tickers: list[str], market: str, *, cfg: HwpConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or HwpConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Intra HWP scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and r.get("phase") in (PHASE_AWAIT_TAG, PHASE_AWAIT_CROSS, PHASE_ENTRY)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
