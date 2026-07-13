"""
box_trading_engine.py
---------------------
TradingLab "Box Strategy" — previous-day high/low box, edge reversals & breakout retests.

Video: https://www.youtube.com/watch?v=oXb2lySZhCU&t=40s

Note: session-timezone constants (IST/NY market hours) are defined locally here rather
than imported from fakeout_4h_engine.py, to keep this module self-contained — it only
needs four small constants, not the full fakeout engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from typing import Any

import numpy as np
import pandas as pd
import pytz

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_BOX_TRADING_URL = "https://www.youtube.com/watch?v=oXb2lySZhCU&t=40s"

IST_TZ = pytz.timezone("Asia/Kolkata")
NY_TZ = pytz.timezone("America/New_York")
INDIA_MARKET_OPEN = time(9, 15)
INDIA_MARKET_CLOSE = time(15, 30)

EXEC_5M = "5m"
EXEC_15M = "15m"
EXEC_OPTIONS = [EXEC_5M, EXEC_15M, "1m"]

PHASE_LONG_REV = "LONG_REVERSAL"
PHASE_SHORT_REV = "SHORT_REVERSAL"
PHASE_BR_LONG = "BREAKOUT_RETEST_LONG"
PHASE_BR_SHORT = "BREAKOUT_RETEST_SHORT"
PHASE_NO_TRADE = "NO_TRADE_ZONE"
PHASE_WATCH_BOTTOM = "WATCH_BOX_BOTTOM"
PHASE_WATCH_TOP = "WATCH_BOX_TOP"
PHASE_NONE = "NO_SETUP"

HOLD_BOX = "Box day-trade · exit by session close (~15:15 IST / 4:00 PM ET)"

PHASE_PRIORITY = {
    PHASE_LONG_REV: 92,
    PHASE_SHORT_REV: 92,
    PHASE_BR_LONG: 88,
    PHASE_BR_SHORT: 88,
    PHASE_WATCH_BOTTOM: 70,
    PHASE_WATCH_TOP: 70,
    PHASE_NO_TRADE: 20,
    PHASE_NONE: 10,
}


def _enrich_intra_live(live: dict | None, *, hold_duration: str = "") -> dict:
    """Fold trade-plan hold/SL/TP fields up onto the top-level live dict (no streamlit dep)."""
    if not live:
        return {}
    out = dict(live)
    plan = out.get("trade_plan") or {}
    hold = hold_duration or out.get("hold_duration") or plan.get("holding_period") or HOLD_BOX
    out["hold_duration"] = hold
    out["confidence_pct"] = out.get("confidence_pct", plan.get("confidence_pct"))
    out["sl_pct"] = out.get("sl_pct", plan.get("stop_loss_pct"))
    out["tp_pct"] = out.get("tp_pct", plan.get("take_profit_pct"))
    if out.get("trade_plan"):
        out["trade_plan"] = {**plan, "holding_period": hold}
    return out


@dataclass
class BoxTradingConfig:
    execution_tf: str = EXEC_5M
    touch_tolerance_pct: float = 0.05
    no_trade_zone_pct: float = 0.50
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 60.0
    lookback_bars: int = 500
    min_bars: int = 60
    sl_buffer_pct: float = 0.05


def fetch_exec_data(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 500,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def _session_tz(market: str):
    return IST_TZ if "Groww" in market else NY_TZ


def _ensure_session_index(df: pd.DataFrame, market: str) -> pd.DataFrame:
    work = normalize_ohlcv(df).copy()
    if work.empty:
        return work
    tz = _session_tz(market)
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(tz)
    else:
        hours = idx.hour
        if "Groww" in market and int(hours.max()) <= 11 and float(np.median(hours)) < 8:
            work.index = idx.tz_localize("UTC").tz_convert(tz)
        else:
            work.index = idx.tz_localize(tz)
    return work


def _in_regular_session(ts: pd.Timestamp, market: str) -> bool:
    tz = _session_tz(market)
    ts = ts.tz_convert(tz) if ts.tz else ts.tz_localize(tz)
    if "Groww" in market:
        return INDIA_MARKET_OPEN <= ts.time() <= INDIA_MARKET_CLOSE
    return True


def _box_levels(box_top: float, box_bottom: float, cfg: BoxTradingConfig) -> dict[str, float]:
    height = box_top - box_bottom
    if height <= 0:
        height = abs(box_top) * 0.01 or 1.0
    mid = (box_top + box_bottom) / 2.0
    half_zone = height * (cfg.no_trade_zone_pct / 2.0)
    return {
        "box_top": box_top,
        "box_bottom": box_bottom,
        "box_mid": mid,
        "no_trade_low": mid - half_zone,
        "no_trade_high": mid + half_zone,
        "box_height": height,
    }


def _tolerance(price: float, cfg: BoxTradingConfig) -> float:
    return abs(price) * cfg.touch_tolerance_pct / 100.0


def _bullish_rejection(row: pd.Series, prev: pd.Series | None) -> bool:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    if c <= o:
        return False
    body = abs(c - o)
    lower_wick = min(o, c) - l
    if body > 0 and lower_wick >= body * 1.5:
        return True
    if prev is not None:
        po, pc = float(prev["open"]), float(prev["close"])
        if c > po and o < pc and c > pc and o < po:
            return True
    return True


def _bearish_rejection(row: pd.Series, prev: pd.Series | None) -> bool:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    if c >= o:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    if body > 0 and upper_wick >= body * 1.5:
        return True
    if prev is not None:
        po, pc = float(prev["open"]), float(prev["close"])
        if c < po and o > pc and c < pc and o > po:
            return True
    return True


def _in_no_trade_zone(price: float, levels: dict[str, float], tol: float) -> bool:
    return (levels["no_trade_low"] - tol) <= price <= (levels["no_trade_high"] + tol)


def _attach_previous_day_box(work: pd.DataFrame, cfg: BoxTradingConfig) -> pd.DataFrame:
    """Map previous session day's high/low onto each intraday bar."""
    if work.empty:
        return work
    session_dates = pd.Series(work.index.date, index=work.index)
    daily = work.groupby(session_dates).agg(box_src_high=("high", "max"), box_src_low=("low", "min"))
    shifted = daily.shift(1)
    work = work.copy()
    work["_session_date"] = session_dates.values
    work = work.join(shifted, on="_session_date")
    work.rename(columns={"box_src_high": "box_top", "box_src_low": "box_bottom"}, inplace=True)
    work["box_mid"] = (work["box_top"] + work["box_bottom"]) / 2.0
    height = (work["box_top"] - work["box_bottom"]).replace(0, np.nan)
    half = height * (cfg.no_trade_zone_pct / 2.0)
    work["no_trade_low"] = work["box_mid"] - half
    work["no_trade_high"] = work["box_mid"] + half
    return work


def annotate_box_strategy(
    df: pd.DataFrame,
    cfg: BoxTradingConfig,
    market: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = _attach_previous_day_box(_ensure_session_index(df, market), cfg)
    if work.empty:
        return work, {}

    work["signal"] = 0
    work["setup_type"] = ""
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan

    state: dict[str, Any] = {"signals": [], "pending_breakout": None}
    n = len(work)

    for i in range(1, n):
        row = work.iloc[i]
        prev = work.iloc[i - 1]
        ts = work.index[i]

        if not _in_regular_session(ts, market):
            continue
        if pd.isna(row["box_top"]) or pd.isna(row["box_bottom"]):
            continue

        levels = _box_levels(float(row["box_top"]), float(row["box_bottom"]), cfg)
        price = float(row["close"])
        tol = _tolerance(price, cfg)
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

        if _in_no_trade_zone(price, levels, tol):
            work.iat[i, work.columns.get_loc("setup_type")] = PHASE_NO_TRADE
            continue

        test_bottom = (l <= levels["box_bottom"] + tol) and (l >= levels["box_bottom"] - tol * 3)
        test_top = (h >= levels["box_top"] - tol) and (h <= levels["box_top"] + tol * 3)

        if test_bottom and _bullish_rejection(row, prev):
            if not (h >= levels["box_top"] - tol):
                entry = c
                stop = levels["box_bottom"] - _tolerance(levels["box_bottom"], cfg)
                risk = max(entry - stop, tol)
                target = entry + risk * cfg.rr_ratio
                work.iat[i, work.columns.get_loc("signal")] = 1
                work.iat[i, work.columns.get_loc("setup_type")] = PHASE_LONG_REV
                work.iat[i, work.columns.get_loc("stop_loss")] = stop
                work.iat[i, work.columns.get_loc("take_profit")] = target
                state["signals"].append({"index": i, "type": PHASE_LONG_REV, "ts": ts})

        elif test_top and _bearish_rejection(row, prev):
            if not (l <= levels["box_bottom"] + tol):
                entry = c
                stop = levels["box_top"] + _tolerance(levels["box_top"], cfg)
                risk = max(stop - entry, tol)
                target = entry - risk * cfg.rr_ratio
                work.iat[i, work.columns.get_loc("signal")] = -1
                work.iat[i, work.columns.get_loc("setup_type")] = PHASE_SHORT_REV
                work.iat[i, work.columns.get_loc("stop_loss")] = stop
                work.iat[i, work.columns.get_loc("take_profit")] = target
                state["signals"].append({"index": i, "type": PHASE_SHORT_REV, "ts": ts})

        pc = float(prev["close"])
        if c > levels["box_top"] and pc <= levels["box_top"]:
            state["pending_breakout"] = {"direction": "LONG", "level": levels["box_top"], "from_index": i}
        elif c < levels["box_bottom"] and pc >= levels["box_bottom"]:
            state["pending_breakout"] = {"direction": "SHORT", "level": levels["box_bottom"], "from_index": i}

        pending = state.get("pending_breakout")
        if pending and i > pending["from_index"]:
            lvl = pending["level"]
            if pending["direction"] == "LONG":
                retest = (l <= lvl + tol) and c >= lvl - tol
                if retest and c > o:
                    entry = c
                    stop = lvl - _tolerance(lvl, cfg)
                    risk = max(entry - stop, tol)
                    target = entry + risk * cfg.rr_ratio
                    work.iat[i, work.columns.get_loc("signal")] = 1
                    work.iat[i, work.columns.get_loc("setup_type")] = PHASE_BR_LONG
                    work.iat[i, work.columns.get_loc("stop_loss")] = stop
                    work.iat[i, work.columns.get_loc("take_profit")] = target
                    state["pending_breakout"] = None
                    state["signals"].append({"index": i, "type": PHASE_BR_LONG, "ts": ts})
            else:
                retest = (h >= lvl - tol) and c <= lvl + tol
                if retest and c < o:
                    entry = c
                    stop = lvl + _tolerance(lvl, cfg)
                    risk = max(stop - entry, tol)
                    target = entry - risk * cfg.rr_ratio
                    work.iat[i, work.columns.get_loc("signal")] = -1
                    work.iat[i, work.columns.get_loc("setup_type")] = PHASE_BR_SHORT
                    work.iat[i, work.columns.get_loc("stop_loss")] = stop
                    work.iat[i, work.columns.get_loc("take_profit")] = target
                    state["pending_breakout"] = None
                    state["signals"].append({"index": i, "type": PHASE_BR_SHORT, "ts": ts})

    return work, state


def _latest_session_slice(work: pd.DataFrame, market: str) -> pd.DataFrame:
    if work.empty:
        return work
    days: list[object] = []
    for ts in reversed(work.index):
        if not _in_regular_session(ts, market):
            continue
        d = ts.date()
        if d not in days:
            days.append(d)
        if len(days) >= 1:
            break
    if not days:
        return work.tail(80)
    return work[work.index.map(lambda t: t.date()) == days[0]]


def evaluate_live_signal(
    work: pd.DataFrame,
    cfg: BoxTradingConfig,
    market: str,
    *,
    annotate_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if work.empty:
        return _enrich_intra_live({"signal": "NO_DATA", "verdict": "NO DATA", "phase": PHASE_NONE})

    session = _latest_session_slice(work, market)
    if session.empty:
        return _enrich_intra_live({"signal": "NO_DATA", "verdict": "NO SESSION", "phase": PHASE_NONE})

    last = session.iloc[-1]
    if pd.isna(last.get("box_top")) or pd.isna(last.get("box_bottom")):
        return _enrich_intra_live({
            "signal": "NO_DATA",
            "verdict": "NO BOX",
            "phase": PHASE_NONE,
            "reasons": ["Previous session box not available — need more history."],
        })

    levels = _box_levels(float(last["box_top"]), float(last["box_bottom"]), cfg)
    price = float(last["close"])
    tol = _tolerance(price, cfg)
    reasons: list[str] = []
    conf = 40.0
    phase = PHASE_NONE
    direction = "—"
    take = False
    entry = stop = target = price

    signals_today = session[session["signal"] != 0]
    latest_sig = signals_today.iloc[-1] if not signals_today.empty else None

    if latest_sig is not None and session.index.get_loc(latest_sig.name) >= len(session) - 3:
        sig = int(latest_sig["signal"])
        direction = "LONG" if sig > 0 else "SHORT"
        phase = str(latest_sig.get("setup_type") or (PHASE_LONG_REV if sig > 0 else PHASE_SHORT_REV))
        entry = float(latest_sig["close"])
        stop = float(latest_sig["stop_loss"])
        target = float(latest_sig["take_profit"])
        conf += 35
        reasons.append(f"Active {phase.replace('_', ' ').lower()} on latest session bar")
        take = conf >= cfg.take_confidence_threshold
    elif _in_no_trade_zone(price, levels, tol):
        phase = PHASE_NO_TRADE
        reasons.append("Price in middle 50% no-trade chop zone — stand aside")
        verdict = "WAIT"
    elif (last["low"] <= levels["box_bottom"] + tol) and price > levels["box_bottom"]:
        phase = PHASE_WATCH_BOTTOM
        conf += 15
        direction = "LONG"
        entry = price
        stop = levels["box_bottom"] - tol
        risk = max(entry - stop, tol)
        target = entry + risk * cfg.rr_ratio
        reasons.append("Testing box bottom — watch for bullish rejection (pin / engulfing)")
        verdict = "WATCH LONG"
    elif (last["high"] >= levels["box_top"] - tol) and price < levels["box_top"]:
        phase = PHASE_WATCH_TOP
        conf += 15
        direction = "SHORT"
        entry = price
        stop = levels["box_top"] + tol
        risk = max(stop - entry, tol)
        target = entry - risk * cfg.rr_ratio
        reasons.append("Testing box top — watch for bearish rejection")
        verdict = "WATCH SHORT"
    else:
        reasons.append("Price between edges and outside no-trade zone — no trigger yet")
        verdict = "WAIT"

    if latest_sig is not None and session.index.get_loc(latest_sig.name) >= len(session) - 3:
        verdict = "TAKE LONG" if take and direction == "LONG" else (
            "TAKE SHORT" if take and direction == "SHORT" else f"WATCH {direction}"
        )
    elif phase not in (PHASE_WATCH_BOTTOM, PHASE_WATCH_TOP):
        verdict = "WAIT"
    elif phase == PHASE_WATCH_BOTTOM:
        verdict = "WATCH LONG"
    elif phase == PHASE_WATCH_TOP:
        verdict = "WATCH SHORT"
    else:
        verdict = "WAIT"

    # Golden rule reminders in reasons
    if abs(price - levels["box_top"]) <= tol:
        reasons.append("Golden rule: never go LONG at box top limit")
    if abs(price - levels["box_bottom"]) <= tol:
        reasons.append("Golden rule: never go SHORT at box bottom limit")

    ref = entry if entry > 0 else 1.0
    if direction == "LONG":
        sl_pct = max(entry - stop, 0) / ref * 100
        tp_pct = max(target - entry, 0) / ref * 100
    elif direction == "SHORT":
        sl_pct = max(stop - entry, 0) / ref * 100
        tp_pct = max(entry - target, 0) / ref * 100
    else:
        sl_pct = tp_pct = 0.0

    conf = max(25.0, min(92.0, conf))
    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Box edge reversal or breakout-retest — avoid midpoint chop.",
        max_hold_exit="Close by session end.",
    )

    return _enrich_intra_live({
        "signal": "BUY" if take and direction == "LONG" else (
            "SELL" if take and direction == "SHORT" else "NONE"
        ),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": HOLD_BOX,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "box_top": round(levels["box_top"], 6),
        "box_bottom": round(levels["box_bottom"], 6),
        "box_mid": round(levels["box_mid"], 6),
        "no_trade_low": round(levels["no_trade_low"], 6),
        "no_trade_high": round(levels["no_trade_high"], 6),
        "execution_tf": cfg.execution_tf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD_BOX},
    }, hold_duration=HOLD_BOX)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: BoxTradingConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BoxTradingConfig()
    df = fetch_exec_data(
        ticker, cfg.execution_tf, market,
        groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
    )
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data ({len(df)} bars)."}

    work, state = annotate_box_strategy(df, cfg, market)
    live = evaluate_live_signal(work, cfg, market, annotate_state=state)
    signals = work[work["signal"] != 0]

    prev_box = {}
    session = _latest_session_slice(work, market)
    if not session.empty and pd.notna(session.iloc[-1].get("box_top")):
        last = session.iloc[-1]
        prev_box = {
            "box_top": float(last["box_top"]),
            "box_bottom": float(last["box_bottom"]),
            "session_date": str(session.index[-1].date()),
        }

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "signal_count": len(signals),
        "box": prev_box,
        "live": live,
        "priority": PHASE_PRIORITY.get(live.get("phase", PHASE_NONE), 10),
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: BoxTradingConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BoxTradingConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("phase") in (
            PHASE_LONG_REV, PHASE_SHORT_REV, PHASE_BR_LONG, PHASE_BR_SHORT,
            PHASE_WATCH_BOTTOM, PHASE_WATCH_TOP,
        )
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -x.get("priority", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
