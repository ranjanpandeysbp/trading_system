"""
scalp_weekly_engine.py
--------------------------
Scalp - Weekly: the previous week's high/low as a liquidity box, hunting false
breakouts on a lower timeframe (India · US · Crypto).

Source: https://www.youtube.com/watch?v=pODlX-CcVEo&t=319s

Step 1 — Mark the weekly range: the last fully-formed weekly candle's high
(incl. wick) and low form a box; a line through the middle marks "no man's
land." Top/bottom = high-liquidity zones algos hunt; middle = random, choppy
participation — do nothing there.

Step 2 — Lower-timeframe setup: wait for an LTF candle to fully CLOSE outside
the box (a wick poking out does not count), then wait for a later candle to
close back INSIDE.

Step 3 — Entry / SL / TP:
  - Broke above the high, closed back inside -> SHORT.
  - Broke below the low, closed back inside  -> LONG.
  - Stop-loss at the absolute extreme of the breakout move, UNLESS that move
    was massively overextended (> overextension_mult x the box height beyond
    the boundary) -- in that case, use the nearest significant support/
    resistance level instead (approximated here via a 2-level swing S/R read
    on the LTF data, the same primitive gap_trading.py uses elsewhere).
  - Take-profit at a minimum fixed risk:reward (default 2:1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import calculate_two_level_sr, fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.swing_trading_st_mtf_mss_engine import build_weekly_from_daily

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_WEEKLY_URL = "https://www.youtube.com/watch?v=pODlX-CcVEo&t=319s"

LTF_OPTIONS = ["15m", "1h", "4h"]

PHASE_NONE = "NO_SETUP"
PHASE_BROKE_UP = "AWAIT_REENTRY_FROM_ABOVE"
PHASE_BROKE_DOWN = "AWAIT_REENTRY_FROM_BELOW"
PHASE_ENTRY = "REENTRY_TRIGGERED"

HOLD_SCALP_WEEKLY = "Intraday–3 trading days (scalp off the weekly liquidity sweep — don't let it drift into a multi-week hold)"


@dataclass
class ScalpWeeklyConfig:
    execution_tf: str = "1h"
    rr_ratio: float = 2.0
    overextension_mult: float = 1.5     # excursion beyond the box, as a multiple of box height, before switching stop method
    recent_bars: int = 3                # a re-entry must be within this many bars of "now" to count as fresh
    take_confidence_threshold: float = 58.0
    daily_lookback: int = 400
    ltf_lookback: int = 500
    min_ltf_bars: int = 60
    min_daily_bars: int = 20
    sr_lookback: int = 40


def _fetch_daily(ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 400) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market))
    return df


def fetch_ltf_data(ticker: str, tf: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 500) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market))
    return df


def map_weekly_levels_to_ltf(df_ltf: pd.DataFrame, weekly_raw: pd.DataFrame) -> pd.DataFrame:
    """Attach the most recently COMPLETED week's high/low (pwh/pwl) to each LTF
    bar via an as-of lookup (most recent weekly candle whose own week ended
    strictly before the bar's own week started) -- NOT an exact week-id join,
    which breaks for the still-forming current week before any daily bar has
    posted for it (exactly when this strategy needs the reference level most)."""
    work = normalize_ohlcv(df_ltf).copy()
    if work.empty or weekly_raw is None or weekly_raw.empty:
        return work

    weekly = weekly_raw.sort_index()
    week_ends = weekly.index.to_numpy()
    highs = weekly["high"].to_numpy()
    lows = weekly["low"].to_numpy()

    bar_week_start = work.index.to_period("W").start_time.to_numpy()
    pos = np.searchsorted(week_ends, bar_week_start, side="left") - 1
    valid = pos >= 0
    pos_clipped = np.clip(pos, 0, len(highs) - 1)
    work["pwh"] = np.where(valid, highs[pos_clipped], np.nan)
    work["pwl"] = np.where(valid, lows[pos_clipped], np.nan)
    work["week_id"] = work.index.to_period("W").astype(str)
    return work


def _box_position(price: float, pwh: float, pwl: float) -> str:
    if pwh is None or pwl is None or pwh <= pwl:
        return "—"
    pos = (price - pwl) / (pwh - pwl)
    if pos >= 0.7:
        return "TOP_THIRD (no-buy zone — algos hunt longs here)"
    if pos <= 0.3:
        return "BOTTOM_THIRD (no-sell zone — algos hunt shorts here)"
    return "MIDDLE_THIRD (no man's land — do nothing)"


def scan_weekly_box_signals(work: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sequential state machine over LTF bars grouped by week: breakout CLOSE
    outside the previous week's box, then a later CLOSE back inside triggers
    a fade signal (broke-above -> SHORT, broke-below -> LONG).

    Returns (completed_signals, live_state) where live_state reflects whether
    the very last bar is currently mid-breakout awaiting a re-entry (an armed
    "watch" state, not yet a triggered signal)."""
    if work.empty or "pwh" not in work.columns:
        return [], {"state": PHASE_NONE}

    signals: list[dict[str, Any]] = []
    state = PHASE_NONE
    extreme = None
    breakout_idx = None
    cur_week = None

    closes = work["close"].to_numpy()
    highs = work["high"].to_numpy()
    lows = work["low"].to_numpy()
    pwh_arr = work["pwh"].to_numpy()
    pwl_arr = work["pwl"].to_numpy()
    week_ids = work["week_id"].to_numpy() if "week_id" in work.columns else [None] * len(work)

    for i in range(len(work)):
        pwh, pwl = pwh_arr[i], pwl_arr[i]
        if pd.isna(pwh) or pd.isna(pwl):
            continue
        if week_ids[i] != cur_week:
            cur_week = week_ids[i]
            state = PHASE_NONE
            extreme = None
            breakout_idx = None

        close, high, low = closes[i], highs[i], lows[i]

        if state == PHASE_NONE:
            if close > pwh:
                state, extreme, breakout_idx = PHASE_BROKE_UP, high, i
            elif close < pwl:
                state, extreme, breakout_idx = PHASE_BROKE_DOWN, low, i
        elif state == PHASE_BROKE_UP:
            extreme = max(extreme, high)
            if close < pwh:
                signals.append({
                    "bar_index": i, "timestamp": str(work.index[i]), "direction": "SHORT",
                    "entry": float(close), "extreme": float(extreme), "pwh": float(pwh), "pwl": float(pwl),
                    "breakout_bar_index": breakout_idx,
                })
                state, extreme, breakout_idx = PHASE_NONE, None, None
            elif close < pwl:
                state, extreme, breakout_idx = PHASE_BROKE_DOWN, low, i
        elif state == PHASE_BROKE_DOWN:
            extreme = min(extreme, low)
            if close > pwl:
                signals.append({
                    "bar_index": i, "timestamp": str(work.index[i]), "direction": "LONG",
                    "entry": float(close), "extreme": float(extreme), "pwh": float(pwh), "pwl": float(pwl),
                    "breakout_bar_index": breakout_idx,
                })
                state, extreme, breakout_idx = PHASE_NONE, None, None
            elif close > pwh:
                state, extreme, breakout_idx = PHASE_BROKE_UP, high, i

    live_state = {"state": state, "extreme": extreme, "breakout_bar_index": breakout_idx}
    return signals, live_state


def _resolve_stop(
    direction: str, entry: float, extreme: float, pwh: float, pwl: float,
    df_ltf: pd.DataFrame, cfg: ScalpWeeklyConfig,
) -> tuple[float, bool]:
    """Stop at the breakout extreme, unless the move overextended past the box
    by more than `overextension_mult` x box height — then fall back to the
    nearest significant swing S/R level (order-block proxy)."""
    box_height = max(pwh - pwl, entry * 0.001)
    if direction == "SHORT":
        excursion = extreme - pwh
        overextended = excursion > box_height * cfg.overextension_mult
        stop = extreme
        if overextended:
            sr = calculate_two_level_sr(df_ltf.tail(cfg.sr_lookback + 10), short_lb=cfg.sr_lookback)
            candidates = [lvl for lvl in (sr.get("r1"), sr.get("r2")) if lvl and lvl > entry]
            if candidates:
                stop = min(candidates)
        return stop, overextended
    else:
        excursion = pwl - extreme
        overextended = excursion > box_height * cfg.overextension_mult
        stop = extreme
        if overextended:
            sr = calculate_two_level_sr(df_ltf.tail(cfg.sr_lookback + 10), short_lb=cfg.sr_lookback)
            candidates = [lvl for lvl in (sr.get("s1"), sr.get("s2")) if lvl and lvl < entry]
            if candidates:
                stop = max(candidates)
        return stop, overextended


def evaluate_live_signal(
    work: pd.DataFrame, signals: list[dict[str, Any]], live_state: dict[str, Any],
    df_ltf: pd.DataFrame, cfg: ScalpWeeklyConfig,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA", "phase": PHASE_NONE, "verdict": "NO DATA", "take_trade": False}

    last = work.iloc[-1]
    price = float(last["close"])
    pwh = float(last["pwh"]) if pd.notna(last.get("pwh")) else None
    pwl = float(last["pwl"]) if pd.notna(last.get("pwl")) else None
    box_pos = _box_position(price, pwh, pwl) if pwh is not None and pwl is not None else "—"

    last_idx = len(work) - 1
    fresh_signals = [s for s in signals if last_idx - s["bar_index"] <= cfg.recent_bars]
    last_signal = fresh_signals[-1] if fresh_signals else None
    is_fresh = bool(last_signal and last_signal["bar_index"] == last_idx)

    reasons = [f"Weekly box: high **{pwh:,.4g}** / low **{pwl:,.4g}** (previous fully-formed weekly candle)."] if pwh and pwl else ["No previous weekly range available yet."]
    reasons.append(f"Price is currently in the box's {box_pos}.")

    verdict, direction, take = "WAIT", "WAIT", False
    entry = stop = target = price
    confidence = 30.0
    overextended = False

    if is_fresh:
        direction = last_signal["direction"]
        entry = last_signal["entry"]
        extreme = last_signal["extreme"]
        stop, overextended = _resolve_stop(direction, entry, extreme, last_signal["pwh"], last_signal["pwl"], df_ltf, cfg)
        risk = abs(entry - stop)
        target = entry + risk * cfg.rr_ratio if direction == "LONG" else entry - risk * cfg.rr_ratio

        reentry_body_pct = abs(price - float(last["open"])) / price * 100 if price else 0
        vol_avg = work["volume"].iloc[-21:-1].mean() if len(work) > 21 else 0
        vol_ratio = float(last["volume"]) / vol_avg if vol_avg else 1.0

        confidence = 58.0
        confidence += 10 if reentry_body_pct >= 0.15 else 0
        confidence += 10 if vol_ratio >= 1.2 else 0
        confidence -= 8 if overextended else 0
        take = confidence >= cfg.take_confidence_threshold
        verdict = f"{'SHORT' if direction == 'SHORT' else 'LONG'} — false breakout {'above' if direction == 'SHORT' else 'below'} the weekly box, closed back inside"

        reasons.append(
            f"{'Broke above the weekly high' if direction == 'SHORT' else 'Broke below the weekly low'} "
            f"to {extreme:,.4g}, then closed back inside the box on the last completed candle — the false-breakout trigger."
        )
        reasons.append(
            f"Stop at {'the overextension-adjusted swing level' if overextended else 'the absolute extreme of the breakout'} "
            f"({stop:,.4g}){' — move was massively overextended past the box, so the absolute extreme was too far for a sane risk.' if overextended else '.'}"
        )
        reasons.append(f"Re-entry candle volume {vol_ratio:.2f}x its 20-bar average — {'supports' if vol_ratio >= 1.2 else 'does not strongly confirm'} the reversal.")
    elif live_state.get("state") in (PHASE_BROKE_UP, PHASE_BROKE_DOWN):
        side = "above the weekly high" if live_state["state"] == PHASE_BROKE_UP else "below the weekly low"
        reasons.append(
            f"Currently ARMED — price has closed {side} (extreme so far {live_state.get('extreme'):,.4g}) and is "
            "awaiting a close back inside the box to trigger the fade entry. Watch, don't enter yet."
        )
    elif last_signal:
        reasons.append(
            f"Most recent qualifying {last_signal['direction']} false-breakout was {last_signal['timestamp']} — "
            "not the current candle, so no fresh trigger right now."
        )
    else:
        reasons.append("No breakout-and-reclose sequence against the weekly box found in the fetched window yet.")

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else sl_pct * cfg.rr_ratio

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe="1h", stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="scalp",
        exit_rule=f"Exit at the fixed 1:{cfg.rr_ratio:.1f} target, or on a close back through the entry level against the trade.",
        max_hold_exit="Close the position if the target isn't reached within a few sessions — this is a scalp off a weekly-range fade, not a swing hold.",
    )

    live = enrich_intra_live({
        "signal": direction if take else "NONE", "direction": direction, "take_trade": take, "verdict": verdict,
        "phase": PHASE_ENTRY if is_fresh else live_state.get("state", PHASE_NONE),
        "confidence_pct": round(confidence, 1), "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "weekly_high": round(pwh, 6) if pwh is not None else None,
        "weekly_low": round(pwl, 6) if pwl is not None else None,
        "box_position": box_pos, "overextended": overextended,
        "reasons": reasons, "trade_plan": {**plan, "holding_period": HOLD_SCALP_WEEKLY},
    }, hold_duration=HOLD_SCALP_WEEKLY)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: ScalpWeeklyConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpWeeklyConfig()
    daily = _fetch_daily(ticker, market, groww_token=groww_token, exchange=exchange, limit=cfg.daily_lookback)
    if daily.empty or len(daily) < cfg.min_daily_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient daily data ({len(daily)} bars) to build the weekly range."}

    df_ltf = fetch_ltf_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.ltf_lookback)
    if df_ltf.empty or len(df_ltf) < cfg.min_ltf_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {cfg.execution_tf} data ({len(df_ltf)} bars)."}

    weekly = build_weekly_from_daily(daily)
    work = map_weekly_levels_to_ltf(df_ltf, weekly)
    if work.empty or "pwh" not in work.columns:
        return {"ticker": ticker, "market": market, "error": "Could not map the weekly range onto the execution timeframe."}

    signals, live_state = scan_weekly_box_signals(work)
    live = evaluate_live_signal(work, signals, live_state, df_ltf, cfg)

    return {
        "ticker": ticker, "market": market, "execution_tf": cfg.execution_tf,
        "bars": len(work), "last_close": float(work["close"].iloc[-1]),
        "signal_history": signals[-8:], "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: ScalpWeeklyConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpWeeklyConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Scalp Weekly failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error") and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("phase") in (PHASE_BROKE_UP, PHASE_BROKE_DOWN)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "execution_tf": cfg.execution_tf, "results": results,
        "entries": entries, "watchlist": watches,
        "entry_count": len(entries), "watch_count": len(watches),
    }
