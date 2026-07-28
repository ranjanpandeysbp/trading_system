"""
zero_to_hero_engine.py
-----------------------
"Zero to Hero" Intraday Option Buying Strategy — AbhishekXTrades.

Source: https://www.youtube.com/watch?v=slAtZyGfAlI

Rules (as taught), on a 15-minute chart:

Step 1 — Mark levels: the previous trading day's high and low (only the
previous day, not older history).

Step 2 — Bias: trading above the previous day's high -> buy-side setups
only. Trading below the previous day's low -> sell-side setups only.
Trading between the two -> a sideways trap zone where option buyers lose
money; take no trades.

Step 3 — Entry (pullback + reversal-through-open):
  - Sell bias: wait for a green (buyer) candle to close, then wait for a
    later red candle to close BELOW that green candle's OPEN -> SHORT
    (buy a Put).
  - Buy bias: wait for a red (seller) candle to close, then wait for a
    later green candle to close ABOVE that red candle's OPEN -> LONG
    (buy a Call).
  - 3-candle rule: if three continuous same-colour pullback candles form,
    the setup is cancelled (a pullback should resolve in 1-2 candles; three
    suggests an actual trend reversal, not a pullback).

Step 4 — Stop-loss & exit:
  - Stop just beyond the entry candle's extreme (low for a long, high for a
    short), with a small buffer so an exact double-top/bottom wick doesn't
    stop it out.
  - Book ~50-60% of the position the moment price reaches 1:1 risk:reward.
  - Do NOT put a fixed target on the remainder — let it ride, uncapped,
    until 3:15 PM IST. Some days it gives the 1:1 gain back on the runner;
    on trending days it captures a 200-400 point Nifty move.
  - Re-entry: if stopped out before 1:1, a fresh setup may be taken again;
    once 1:1 has been booked, no re-entry for that session's move.

This is a stateless scanner (like every other engine in this app) — it
reports whether a *fresh* entry signal exists right now. It does not track
whether you already booked 1:1 or got stopped out; use the `reasons` /
`trade_plan` text as the management checklist per the rules above.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

YOUTUBE_ZERO_TO_HERO_URL = "https://www.youtube.com/watch?v=slAtZyGfAlI"

INDEX_NAMES = ["Nifty 50", "Bank Nifty"]

LTF_OPTIONS = ["15m", "5m", "30m"]


@dataclass
class ZeroToHeroConfig:
    execution_tf: str = "15m"
    daily_lookback: int = 30
    ltf_lookback: int = 400
    min_daily_bars: int = 3
    min_ltf_bars: int = 30
    sl_buffer_pct: float = 0.05        # small buffer beyond the entry candle's extreme
    max_pullback_candles: int = 3       # 3-in-a-row pullback candles cancels the setup
    partial_book_rr: float = 1.0        # book partial profits at this R:R
    partial_book_pct: float = 55.0      # % of position booked at the partial level
    session_end: str = "15:15"          # flat / let-it-ride-until time (IST)


def map_daily_levels_to_ltf(df_ltf: pd.DataFrame, daily_raw: pd.DataFrame) -> pd.DataFrame:
    """Attach the previous COMPLETE trading day's high/low (pdh/pdl) to each
    LTF bar via an as-of lookup (most recent daily bar strictly before the
    LTF bar's own calendar day) — not same-day, and not stale multi-day-old
    data once a new day's daily bar has posted."""
    work = normalize_ohlcv(df_ltf).copy()
    if work.empty or daily_raw is None or daily_raw.empty:
        return work

    daily = daily_raw.sort_index()
    day_dates = pd.to_datetime(daily.index).normalize().to_numpy()
    highs = daily["high"].to_numpy()
    lows = daily["low"].to_numpy()

    bar_dates = pd.to_datetime(work.index).normalize().to_numpy()
    pos = np.searchsorted(day_dates, bar_dates, side="left") - 1
    valid = pos >= 0
    pos_clipped = np.clip(pos, 0, len(highs) - 1)
    work["pdh"] = np.where(valid, highs[pos_clipped], np.nan)
    work["pdl"] = np.where(valid, lows[pos_clipped], np.nan)
    work["day_id"] = pd.to_datetime(work.index).normalize().astype(str)
    return work


def scan_zero_to_hero_signals(
    work: pd.DataFrame, cfg: ZeroToHeroConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sequential state machine over LTF bars: bias from the previous day's
    range, then a pullback-candle-sequence followed by a reversal candle
    closing through the pullback candle's open triggers an entry."""
    if work.empty or "pdh" not in work.columns:
        return [], {"bias": "NONE", "pullback_count": 0, "pullback_color": None}

    signals: list[dict[str, Any]] = []
    bias = "NONE"
    pullback_count = 0
    pullback_ref_open: float | None = None
    pullback_color: str | None = None
    cur_day = None

    opens = work["open"].to_numpy()
    closes = work["close"].to_numpy()
    highs = work["high"].to_numpy()
    lows = work["low"].to_numpy()
    pdh_arr = work["pdh"].to_numpy()
    pdl_arr = work["pdl"].to_numpy()
    day_ids = work["day_id"].to_numpy() if "day_id" in work.columns else [None] * len(work)

    for i in range(len(work)):
        pdh, pdl = pdh_arr[i], pdl_arr[i]
        if pd.isna(pdh) or pd.isna(pdl):
            continue

        if day_ids[i] != cur_day:
            cur_day = day_ids[i]
            bias, pullback_count, pullback_ref_open, pullback_color = "NONE", 0, None, None

        o, c, h, l = float(opens[i]), float(closes[i]), float(highs[i]), float(lows[i])
        candle_color = "GREEN" if c > o else "RED" if c < o else "DOJI"

        new_bias = "BUY" if c > pdh else "SELL" if c < pdl else "NONE"
        if new_bias != bias:
            bias = new_bias
            pullback_count, pullback_ref_open, pullback_color = 0, None, None

        if bias == "NONE":
            continue

        pullback_needed = "RED" if bias == "BUY" else "GREEN"
        confirm_needed = "GREEN" if bias == "BUY" else "RED"

        if candle_color == pullback_needed:
            pullback_count = pullback_count + 1 if pullback_color == pullback_needed else 1
            pullback_color = pullback_needed
            pullback_ref_open = o
            if pullback_count >= cfg.max_pullback_candles:
                # Three same-colour pullback candles in a row — likely a real
                # trend reversal, not a pullback. Cancel and wait for a fresh one.
                pullback_count, pullback_ref_open, pullback_color = 0, None, None
        elif candle_color == confirm_needed and pullback_count > 0 and pullback_ref_open is not None:
            broke = (c > pullback_ref_open) if bias == "BUY" else (c < pullback_ref_open)
            if broke:
                signals.append({
                    "bar_index": i, "timestamp": str(work.index[i]),
                    "direction": "LONG" if bias == "BUY" else "SHORT",
                    "entry": c, "entry_low": l, "entry_high": h,
                    "pdh": float(pdh), "pdl": float(pdl), "pullback_candles": pullback_count,
                })
                pullback_count, pullback_ref_open, pullback_color = 0, None, None
            # A reversal-colour candle that fails to break through the pullback
            # candle's open doesn't extend or reset the pullback count — just keep waiting.

    live_state = {"bias": bias, "pullback_count": pullback_count, "pullback_color": pullback_color}
    return signals, live_state


def evaluate_live_signal(
    work: pd.DataFrame, signals: list[dict[str, Any]], live_state: dict[str, Any], cfg: ZeroToHeroConfig,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA", "verdict": "NO DATA", "take_trade": False}

    last = work.iloc[-1]
    price = float(last["close"])
    pdh = float(last["pdh"]) if pd.notna(last.get("pdh")) else None
    pdl = float(last["pdl"]) if pd.notna(last.get("pdl")) else None
    bias = "BUY" if (pdh is not None and price > pdh) else "SELL" if (pdl is not None and price < pdl) else "NONE"

    reasons: list[str] = []
    if pdh is not None and pdl is not None:
        reasons.append(f"Previous day's range: high **{pdh:,.4g}** / low **{pdl:,.4g}**.")
        reasons.append(
            "Bias: **"
            + bias
            + "** — "
            + (
                "price trading above the previous day's high; buy-side (Call) setups only."
                if bias == "BUY"
                else "price trading below the previous day's low; sell-side (Put) setups only."
                if bias == "SELL"
                else "price is trapped between the previous day's high and low — sideways trap zone, no trades."
            )
        )
    else:
        reasons.append("No previous trading day's range available yet.")

    last_idx = len(work) - 1
    last_signal = signals[-1] if signals else None
    is_fresh = bool(last_signal and last_signal["bar_index"] == last_idx)

    verdict, direction, take = "WAIT", "WAIT", False
    entry = stop = target_1r = price
    confidence = 0.0

    if is_fresh and last_signal:
        direction = last_signal["direction"]
        entry = last_signal["entry"]
        buffer = entry * (cfg.sl_buffer_pct / 100.0)
        stop = (last_signal["entry_low"] - buffer) if direction == "LONG" else (last_signal["entry_high"] + buffer)
        risk = abs(entry - stop)
        target_1r = entry + risk * cfg.partial_book_rr if direction == "LONG" else entry - risk * cfg.partial_book_rr

        n_pb = last_signal["pullback_candles"]
        confidence = 60.0 + (8.0 if n_pb == 1 else 4.0 if n_pb == 2 else 0.0)
        take = True
        verdict = (
            ("BUY CALL" if direction == "LONG" else "BUY PUT")
            + f" — {n_pb}-candle pullback reversed through the open"
        )
        reasons.append(
            f"Entry trigger: after a {n_pb}-candle "
            + ("red (seller)" if direction == "LONG" else "green (buyer)")
            + " pullback, a "
            + ("green" if direction == "LONG" else "red")
            + " candle closed "
            + ("above" if direction == "LONG" else "below")
            + " the pullback candle's open."
        )
        reasons.append(
            f"Stop-loss just {'below' if direction == 'LONG' else 'above'} the entry candle's "
            f"{'low' if direction == 'LONG' else 'high'}, with a small buffer -> {stop:,.4g}."
        )
        reasons.append(
            f"Book ~{cfg.partial_book_pct:.0f}% of the position the moment it reaches 1:{cfg.partial_book_rr:.0f} "
            f"(~{target_1r:,.4g}). Leave the rest running with NO fixed target until {cfg.session_end} IST — "
            "this is the 'zero to hero' piece that catches the big trending days."
        )
        reasons.append(
            "Re-entry rule: if stopped out before 1:1, a fresh pullback-and-reversal setup can be taken again; "
            "once 1:1 has already been booked, do not re-enter this session."
        )
    elif live_state.get("bias") != "NONE" and (live_state.get("pullback_count") or 0) > 0:
        reasons.append(
            f"Pullback forming: {live_state['pullback_count']} "
            + ("red" if live_state.get("pullback_color") == "RED" else "green")
            + f" candle(s) against the {live_state['bias']} bias — watching for the reversal "
            + "candle to close through the pullback candle's open."
        )
    elif last_signal:
        reasons.append(
            f"Most recent qualifying setup was {last_signal['direction']} at {last_signal['timestamp']} — "
            "not the current candle, so no fresh trigger right now."
        )
    else:
        reasons.append("No pullback-and-reversal sequence against the previous day's range found in the fetched window yet.")

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target_1r - entry) / entry * 100, 2) if entry else sl_pct  # the 1:1 partial-book level, not a final target

    hold_duration = f"Intraday — book ~{cfg.partial_book_pct:.0f}% at 1:1, ride the rest to {cfg.session_end} IST ('Zero to Hero' hold)"

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe=cfg.execution_tf, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="intraday",
        exit_rule=(
            f"Book ~{cfg.partial_book_pct:.0f}% at 1:{cfg.partial_book_rr:.0f} R:R, then let the remainder ride "
            f"with no fixed target until {cfg.session_end} IST (or its own stop)."
        ),
        max_hold_exit=f"Flat by {cfg.session_end} IST — no overnight hold on the remaining quantity either.",
    )

    live = enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction if take else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": bias,
        "confidence_pct": round(confidence, 1) if take else 0.0,
        "sl_pct": sl_pct if take else None,
        "tp_pct": tp_pct if take else None,
        "entry_price": round(entry, 6) if take else None,
        "stop_price": round(stop, 6) if take else None,
        "target_price": round(target_1r, 6) if take else None,
        "prev_day_high": round(pdh, 6) if pdh is not None else None,
        "prev_day_low": round(pdl, 6) if pdl is not None else None,
        "option_action": ("BUY CALL" if direction == "LONG" else "BUY PUT") if take else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration} if take else None,
    }, hold_duration=hold_duration)

    return live


def analyze_ticker(
    index_name: str, market: str, *, cfg: ZeroToHeroConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ZeroToHeroConfig()
    daily = fetch_index_ohlcv_for_interval(index_name, "1d", limit=cfg.daily_lookback, groww_token=groww_token, exchange=exchange)
    if daily is None or daily.empty or len(daily) < cfg.min_daily_bars:
        return {
            "ticker": index_name, "market": market,
            "error": f"Insufficient daily data ({0 if daily is None else len(daily)} bars) for the previous day's range.",
        }

    df_ltf = fetch_index_ohlcv_for_interval(index_name, cfg.execution_tf, limit=cfg.ltf_lookback, groww_token=groww_token, exchange=exchange)
    if df_ltf is None or df_ltf.empty or len(df_ltf) < cfg.min_ltf_bars:
        return {
            "ticker": index_name, "market": market,
            "error": f"Insufficient {cfg.execution_tf} data ({0 if df_ltf is None else len(df_ltf)} bars).",
        }

    work = map_daily_levels_to_ltf(df_ltf, daily)
    if work.empty or "pdh" not in work.columns:
        return {"ticker": index_name, "market": market, "error": "Could not map the previous day's range onto the execution timeframe."}

    signals, live_state = scan_zero_to_hero_signals(work, cfg)
    live = evaluate_live_signal(work, signals, live_state, cfg)

    return {
        "ticker": index_name, "market": market, "execution_tf": cfg.execution_tf,
        "bars": len(work), "last_close": float(work["close"].iloc[-1]),
        "signal_history": signals[-8:], "live": live,
    }


def analyze_ticker_many(
    index_names: list[str], market: str, *, cfg: ZeroToHeroConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results = []
    for name in index_names:
        try:
            results.append(analyze_ticker(name, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Zero to Hero scan failed for %s: %s", name, exc)
            results.append({"ticker": name, "market": market, "error": str(exc)[:200]})
    return results


def scan_universe(
    tickers: list[str], market: str, *, cfg: ZeroToHeroConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Trading-hubs / Options API entry — restricted to INDEX_NAMES (the
    strategy is specifically for Nifty / Bank Nifty option buying)."""
    cfg = cfg or ZeroToHeroConfig()
    names = [n for n in (tickers or INDEX_NAMES) if n in INDEX_NAMES] or list(INDEX_NAMES)
    results = analyze_ticker_many(names, market, cfg=cfg, groww_token=groww_token, exchange=exchange)

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "execution_tf": cfg.execution_tf, "results": results,
        "entries": entries, "entry_count": len(entries),
        "strategy": "Zero to Hero — Previous Day High/Low Intraday Option Buying (AbhishekXTrades)",
        "youtube": YOUTUBE_ZERO_TO_HERO_URL,
        "fixed_universe": list(INDEX_NAMES),
    }
