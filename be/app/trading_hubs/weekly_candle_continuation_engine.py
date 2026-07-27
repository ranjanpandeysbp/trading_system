"""
weekly_candle_continuation_engine.py
-----------------------------------------
Scalping — Weekly Candle Continuation: trades WITH the market makers when
they hold and extend a trend, rather than fading strength at the previous
week's high/low (https://www.youtube.com/watch?v=4JrjAY7nAFU).

Step 1 — Mark the previous week's high/low (reuses the same "most recently
COMPLETED week" mapping the Scalp - Weekly section uses).
Step 2 — Drop to an entry timeframe (4h/1h/15m/5m) to watch the new week.
Step 3 — The FIRST close beyond the weekly high (or low) is NOT an entry —
it's the initial push. No trade yet.
Step 4 — After that push, find its extreme (the highest high / lowest low
reached before price paused) — that becomes the confirmation level. Wait
for a pullback/consolidation of at least a few bars off that extreme.
Step 5 — Entry: a fresh, strong-bodied ("displacement") close back beyond
the confirmation level, in the same direction as the original break.

Stop-loss: the swing low (longs) / swing high (shorts) that formed DURING
the consolidation just before entry — not the confirmation level itself.
Take-profit: the nearest prior swing high/low "to the left" (before this
week's break) that lies beyond entry in the trade direction; falls back to
a fixed risk:reward if no such level exists.

The video's own optional alternative triggers (FVG pullback entry, trendline
break entry) are not reproduced here — the displacement-close trigger is the
primary, clearly-specified mechanism and is what's mechanized.

Long or short, symmetric. Confidence is a heuristic confluence score, not a
statistical win probability. Research / education only — NOT FINANCIAL ADVICE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.sr_breakout import _find_swing_points
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.scalp_weekly_engine import map_weekly_levels_to_ltf
from app.trading_hubs.swing_trading_st_mtf_mss_engine import build_weekly_from_daily

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=4JrjAY7nAFU"

ENTRY_TF_OPTIONS = ["5m", "15m", "1h", "4h"]

HOLD_WEEKLY_CONTINUATION = "Intraday-3 trading days (continuation off the weekly break — don't let a stalled trade drift)"


@dataclass
class WeeklyCandleContinuationConfig:
    entry_tf: str = "1h"
    consolidation_min_bars: int = 2
    consolidation_max_bars: int = 30
    displacement_body_ratio: float = 0.55
    recent_bars: int = 1
    swing_window: int = 5
    rr_ratio: float = 2.0
    sl_buffer_pct: float = 0.1
    take_confidence_threshold: float = 58.0
    daily_lookback: int = 300
    entry_tf_lookback: int = 500
    min_daily_bars: int = 20
    min_entry_bars: int = 80


def _fetch_daily(ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market))
    return df


def fetch_entry_data(ticker: str, tf: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 500) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market))
    return df


def evaluate_live_signal(work: pd.DataFrame, cfg: WeeklyCandleContinuationConfig) -> dict[str, Any]:
    if work.empty or "pwh" not in work.columns:
        return {"signal": "NO_DATA", "direction": "WAIT", "verdict": "NO DATA", "take_trade": False, "reasons": ["No data."]}

    last = work.iloc[-1]
    pwh = float(last["pwh"]) if pd.notna(last.get("pwh")) else None
    pwl = float(last["pwl"]) if pd.notna(last.get("pwl")) else None
    if pwh is None or pwl is None:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — no weekly range yet", "confidence_pct": 20.0,
            "reasons": ["No previous completed weekly candle available yet."],
        }

    reasons = [f"Weekly box: high **{pwh:,.4g}** / low **{pwl:,.4g}** (previous fully-formed weekly candle)."]

    cur_week = last.get("week_id")
    week_mask = work["week_id"] == cur_week
    week_df = work[week_mask]
    if len(week_df) < 3:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — new week just started", "confidence_pct": 25.0,
            "reasons": reasons + ["Not enough bars into the new week yet to look for a break."],
        }

    bull_breaks = week_df.index[week_df["close"] > week_df["pwh"]]
    bear_breaks = week_df.index[week_df["close"] < week_df["pwl"]]

    if bull_breaks.empty and bear_breaks.empty:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — no weekly-level break yet this week", "confidence_pct": 25.0,
            "reasons": reasons + ["Price hasn't closed beyond either weekly level yet this week."],
        }
    if not bull_breaks.empty and not bear_breaks.empty:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — whipsawed both levels this week", "confidence_pct": 20.0,
            "reasons": reasons + ["Both the weekly high and low were broken this week — no clean continuation direction."],
        }

    direction = "LONG" if not bull_breaks.empty else "SHORT"
    break_ts = bull_breaks[0] if direction == "LONG" else bear_breaks[0]
    break_pos = work.index.get_loc(break_ts)
    last_pos = len(work) - 1
    reasons.append(
        f"Initial break {'above the weekly high' if direction == 'LONG' else 'below the weekly low'} on "
        f"{break_ts} — the first push, not an entry by itself."
    )

    # Walk forward from the break, tracking the running extreme of the push —
    # but LOCK it in as soon as a pullback of `consolidation_min_bars` shows up,
    # so a later displacement bar (which by definition makes a new extreme)
    # can never retroactively swallow the earlier push as "the confirmation
    # level" — the whole point is two distinct legs: push, then pullback,
    # then a SECOND break past that locked-in level.
    running_extreme = float(work["high"].iloc[break_pos]) if direction == "LONG" else float(work["low"].iloc[break_pos])
    push_pos = break_pos
    bars_since_update = 0
    locked = False
    for pos in range(break_pos + 1, last_pos + 1):
        if direction == "LONG":
            bar_extreme = float(work["high"].iloc[pos])
            improved = bar_extreme > running_extreme
        else:
            bar_extreme = float(work["low"].iloc[pos])
            improved = bar_extreme < running_extreme
        if improved:
            running_extreme = bar_extreme
            push_pos = pos
            bars_since_update = 0
        else:
            bars_since_update += 1
        if bars_since_update >= cfg.consolidation_min_bars:
            locked = True
            break

    confirmation_level = running_extreme
    if not locked:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": f"WATCH {direction} — pushed to a new extreme, no pullback yet",
            "confidence_pct": 35.0,
            "reasons": reasons + [
                f"Pushed to {confirmation_level:,.4g} — waiting for a pullback/consolidation of at least "
                f"{cfg.consolidation_min_bars} bar(s) before a confirmation level is usable."
            ],
        }

    bars_since_push = last_pos - push_pos
    if bars_since_push > cfg.consolidation_max_bars:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — confirmation level too old", "confidence_pct": 30.0,
            "reasons": reasons + [
                f"The push to {confirmation_level:,.4g} was {bars_since_push} bars ago — too stale for a fresh "
                "continuation entry (resets each new week)."
            ],
        }

    consolidation_window = work.iloc[push_pos + 1:last_pos + 1]
    if consolidation_window.empty:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": f"WATCH {direction} — awaiting consolidation", "confidence_pct": 35.0,
            "reasons": reasons + ["No consolidation bars yet since the push."],
        }
    stop_ref = float(consolidation_window["low"].min()) if direction == "LONG" else float(consolidation_window["high"].max())
    reasons.append(
        f"Consolidation formed off that push — {'swing low' if direction == 'LONG' else 'swing high'} at "
        f"{stop_ref:,.4g} (the stop reference)."
    )

    start = max(push_pos + 1, last_pos - cfg.recent_bars + 1)
    displacement_pos = None
    for pos in range(last_pos, start - 1, -1):
        row = work.iloc[pos]
        rng = max(float(row["high"]) - float(row["low"]), 1e-9)
        body_ratio = abs(float(row["close"]) - float(row["open"])) / rng
        if direction == "LONG" and float(row["close"]) > confirmation_level and body_ratio >= cfg.displacement_body_ratio:
            displacement_pos = pos
            break
        if direction == "SHORT" and float(row["close"]) < confirmation_level and body_ratio >= cfg.displacement_body_ratio:
            displacement_pos = pos
            break

    if displacement_pos is None:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": f"WATCH {direction} — awaiting displacement past {confirmation_level:,.4g}",
            "confidence_pct": 42.0,
            "reasons": reasons + [
                f"Consolidating — need a strong-bodied close beyond the confirmation level ({confirmation_level:,.4g}) "
                "to trigger the continuation entry."
            ],
        }

    entry = float(work["close"].iloc[-1])
    if direction == "LONG":
        stop = stop_ref * (1 - cfg.sl_buffer_pct / 100)
    else:
        stop = stop_ref * (1 + cfg.sl_buffer_pct / 100)
    risk = max(abs(entry - stop), entry * 0.002)

    swing_highs, swing_lows = _find_swing_points(work.iloc[:break_pos], window=cfg.swing_window)
    if direction == "LONG":
        candidates = [lvl for _, lvl in swing_highs if lvl > entry]
        target = min(candidates) if candidates else None
    else:
        candidates = [lvl for _, lvl in swing_lows if lvl < entry]
        target = max(candidates) if candidates else None
    reward = abs(target - entry) if target is not None else 0.0
    if target is None or risk <= 0 or reward / risk < cfg.rr_ratio:
        target = entry + risk * cfg.rr_ratio if direction == "LONG" else entry - risk * cfg.rr_ratio
        reasons.append(f"No qualifying prior swing level gave a full 1:{cfg.rr_ratio:.1f} — using the fixed R:R target.")
    else:
        reasons.append(f"Target at the nearest prior swing level to the left ({target:,.4g}).")

    bars_ago = last_pos - displacement_pos
    confidence = cfg.take_confidence_threshold
    confidence += 12 if bars_ago == 0 else (5 if bars_ago <= cfg.recent_bars else 0)
    confidence += 10 if bars_since_push >= cfg.consolidation_min_bars + 2 else 0
    take = confidence >= cfg.take_confidence_threshold

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else sl_pct * cfg.rr_ratio

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe="1d", stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="scalp",
        exit_rule="Exit at the target, or on a close back through the confirmation level against the trade.",
        max_hold_exit="Close the position if the target isn't reached within a few sessions.",
    )

    reasons.append(
        f"Displacement close beyond the confirmation level ({confirmation_level:,.4g}), {bars_ago} bar(s) ago — "
        "clean, strong-bodied breakout, the continuation trigger."
    )

    live = enrich_intra_live({
        "signal": direction if take else "NONE", "direction": direction, "take_trade": take,
        "verdict": f"TAKE {direction} — weekly candle continuation" if take else f"WATCH {direction} — displacement found, confidence below threshold",
        "confidence_pct": round(confidence, 1), "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "weekly_high": round(pwh, 6), "weekly_low": round(pwl, 6), "confirmation_level": round(confirmation_level, 6),
        "reasons": reasons, "trade_plan": {**plan, "holding_period": HOLD_WEEKLY_CONTINUATION},
    }, hold_duration=HOLD_WEEKLY_CONTINUATION)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: WeeklyCandleContinuationConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or WeeklyCandleContinuationConfig()
    daily = _fetch_daily(ticker, market, groww_token=groww_token, exchange=exchange, limit=cfg.daily_lookback)
    if daily.empty or len(daily) < cfg.min_daily_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient daily data ({len(daily)} bars) to build the weekly range."}

    entry_df = fetch_entry_data(ticker, cfg.entry_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.entry_tf_lookback)
    if entry_df.empty or len(entry_df) < cfg.min_entry_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {cfg.entry_tf} data ({len(entry_df)} bars)."}

    weekly = build_weekly_from_daily(daily)
    work = map_weekly_levels_to_ltf(entry_df, weekly)
    if work.empty or "pwh" not in work.columns:
        return {"ticker": ticker, "market": market, "error": "Could not map the weekly range onto the entry timeframe."}

    live = evaluate_live_signal(work, cfg)
    return {
        "ticker": ticker, "market": market, "entry_tf": cfg.entry_tf,
        "bars": len(work), "last_close": float(work["close"].iloc[-1]), "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: WeeklyCandleContinuationConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or WeeklyCandleContinuationConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Weekly Candle Continuation failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error") and not (r.get("live") or {}).get("take_trade")
        and str((r.get("live") or {}).get("verdict", "")).startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "entry_tf": cfg.entry_tf, "results": results,
        "entries": entries, "watchlist": watches,
        "entry_count": len(entries), "watch_count": len(watches),
    }
