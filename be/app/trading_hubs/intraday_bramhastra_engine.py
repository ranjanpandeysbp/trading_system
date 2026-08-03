"""
intraday_bramhastra_engine.py
------------------------------
Bramhastra Strategy — pure price-action, indicator-free intraday breakout
system (Trade Swings). Works on indices, stocks, crypto, and commodities —
no indicators, just the first hour's range and a two-stage 5-minute
breakout confirmation.

Source: https://www.youtube.com/watch?v=KMbMaRH_FEw

Canonical rules:
  1. Mark the High/Low of the session's first 1-Hour candle (color doesn't
     matter). This is the observation range.
  2. Switch to 5-minute execution. Watch for a 5m candle to CLOSE beyond
     the range (above the high for a long setup, below the low for a
     short) — a break that doesn't close beyond the range (a wick-only
     "fake breakout") is ignored. Once it closes beyond, mark THAT
     candle's own high (long) / low (short) — this is the confirmation
     level.
  3. Entry triggers when a later 5m candle actually breaks the
     confirmation level.
  4. Stop-loss: a fixed max distance from entry (default ~0.2% of price,
     the video's "50 points max on a ~25,000 Nifty spot" translated to a
     percentage so it generalizes across instruments and asset classes).
  5. Target: risk:reward from config (video suggests 1:1 to 1:1.5; default
     here 1.3).
  6. Skip the whole session if the first-hour range itself is unusually
     wide ("monster candle") — the video's rule of thumb is it tends to
     chop and stop out setups for the rest of the day.

Session windows (first-hour observation start, execution-window end) reuse
the same per-asset-class session profile already defined for the London
Breakout strategy (India/US/Crypto/Commodity), so "first hour of the day"
means the right thing for each market rather than assuming NSE hours.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.ticker_utils import is_crypto_market
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.intraday_london_breakout_engine import (
    _active_session_date,
    _drop_ambiguous_date_column,
    _ensure_market_tz,
    _is_overnight,
    _session_date_series,
    _slice_window,
    _trade_bars_for_session,
    resolve_profile,
    session_windows,
)

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=KMbMaRH_FEw"
STRATEGY_NAME = "Bramhastra Strategy — 1H Range + 5m Two-Stage Breakout"
OBSERVATION_TF = "1h"
EXEC_TF = "5m"
HOLD = "Same session · confirm-then-break entry · flatten by session end"

PHASE_BUILDING_RANGE = "BUILDING_RANGE"
PHASE_NO_RANGE_DATA = "NO_RANGE_DATA"
PHASE_MONSTER_SKIP = "MONSTER_CANDLE_SKIP"
PHASE_NO_BREAK_YET = "NO_BREAK_YET"
PHASE_CONFIRMED_LONG = "CONFIRMED_LONG"
PHASE_CONFIRMED_SHORT = "CONFIRMED_SHORT"
PHASE_TRIGGERED_LONG = "TRIGGERED_LONG"
PHASE_TRIGGERED_SHORT = "TRIGGERED_SHORT"


@dataclass
class BramhastraConfig:
    # Video: "max 50 points on ~25,000 Nifty spot" ≈ 0.2% — a universal
    # percentage stop so this works the same way across any instrument.
    max_sl_pct: float = 0.2
    rr_ratio: float = 1.3
    # First-hour range this wide (% of price) or wider → skip the session.
    monster_range_pct: float = 0.7
    take_confidence_threshold: float = 55.0
    lookback_bars: int = 1500
    min_bars: int = 60
    # Injected by TradingHubService.scan — distinguishes US vs commodity (same Yahoo market).
    asset_class: str = ""
    # Unused by Bramhastra itself — session_windows() (shared with the London
    # Breakout engine) expects these four override fields to exist on any
    # config passed to it; left empty so asset-class defaults always apply.
    range_start: str = ""
    range_end: str = ""
    trade_start: str = ""
    trade_end: str = ""


def _observation_window(windows: dict[str, Any]) -> tuple[time, time]:
    start = windows["market_open"]
    end = (datetime.combine(date_cls.today(), start) + timedelta(hours=1)).time()
    return start, end


def _detect_two_stage_breakout(
    exec_bars: pd.DataFrame, range_hi: float, range_lo: float, cfg: BramhastraConfig,
) -> dict[str, Any]:
    """Stage A: first 5m candle to CLOSE beyond the range marks its own
    high/low as the confirmation level. Stage B: the first later candle to
    breach that level triggers entry. Whichever side (long/short) triggers
    first wins the session — one trade per day."""
    confirm_long_level: float | None = None
    confirm_short_level: float | None = None
    confirm_long_time: Any = None
    confirm_short_time: Any = None

    for ts, row in exec_bars.iterrows():
        close, high, low = float(row["close"]), float(row["high"]), float(row["low"])

        if confirm_long_level is not None and high >= confirm_long_level:
            entry = confirm_long_level
            sl_dist = entry * cfg.max_sl_pct / 100
            stop = entry - sl_dist
            target = entry + sl_dist * cfg.rr_ratio
            return {
                "phase": PHASE_TRIGGERED_LONG, "direction": "LONG",
                "confirm_level": round(confirm_long_level, 6), "confirm_time": str(confirm_long_time),
                "trigger_time": str(ts), "entry_price": round(entry, 6),
                "stop_price": round(stop, 6), "target_price": round(target, 6),
                "sl_pct": round(cfg.max_sl_pct, 4), "tp_pct": round(cfg.max_sl_pct * cfg.rr_ratio, 4),
            }
        if confirm_short_level is not None and low <= confirm_short_level:
            entry = confirm_short_level
            sl_dist = entry * cfg.max_sl_pct / 100
            stop = entry + sl_dist
            target = entry - sl_dist * cfg.rr_ratio
            return {
                "phase": PHASE_TRIGGERED_SHORT, "direction": "SHORT",
                "confirm_level": round(confirm_short_level, 6), "confirm_time": str(confirm_short_time),
                "trigger_time": str(ts), "entry_price": round(entry, 6),
                "stop_price": round(stop, 6), "target_price": round(target, 6),
                "sl_pct": round(cfg.max_sl_pct, 4), "tp_pct": round(cfg.max_sl_pct * cfg.rr_ratio, 4),
            }

        if confirm_long_level is None and close > range_hi:
            confirm_long_level = high
            confirm_long_time = ts
        if confirm_short_level is None and close < range_lo:
            confirm_short_level = low
            confirm_short_time = ts

    if confirm_long_level is not None:
        return {
            "phase": PHASE_CONFIRMED_LONG, "direction": "LONG",
            "confirm_level": round(confirm_long_level, 6), "confirm_time": str(confirm_long_time),
        }
    if confirm_short_level is not None:
        return {
            "phase": PHASE_CONFIRMED_SHORT, "direction": "SHORT",
            "confirm_level": round(confirm_short_level, 6), "confirm_time": str(confirm_short_time),
        }
    return {"phase": PHASE_NO_BREAK_YET}


def _analyze_session(
    work: pd.DataFrame,
    session_day: date_cls,
    windows: dict[str, Any],
    cfg: BramhastraConfig,
    *,
    is_today: bool = False,
    now_ts: pd.Timestamp | None = None,
) -> dict[str, Any]:
    obs_start, obs_end = _observation_window(windows)
    trade_windows = {"trade_start": obs_end, "trade_end": windows["market_close"]}

    if is_today and now_ts is not None and not _is_overnight(obs_start, obs_end) and now_ts.time() < obs_end:
        return {"phase": PHASE_BUILDING_RANGE, "session_date": str(session_day)}

    day_bars = work.loc[work.index.date == session_day]
    obs_bars = _slice_window(day_bars, obs_start, obs_end)
    if obs_bars.empty:
        return {"phase": PHASE_NO_RANGE_DATA, "session_date": str(session_day)}

    range_hi = float(obs_bars["high"].max())
    range_lo = float(obs_bars["low"].min())
    if range_hi <= range_lo:
        return {"phase": PHASE_NO_RANGE_DATA, "session_date": str(session_day)}

    ref_price = float(obs_bars["close"].iloc[-1])
    range_pct = (range_hi - range_lo) / ref_price * 100 if ref_price else 0.0
    base = {
        "session_date": str(session_day),
        "range_high": round(range_hi, 6), "range_low": round(range_lo, 6),
        "range_pct": round(range_pct, 3), "ref_price": ref_price,
    }

    if range_pct >= cfg.monster_range_pct:
        return {**base, "phase": PHASE_MONSTER_SKIP}

    exec_bars = _trade_bars_for_session(work, session_day, trade_windows)
    if exec_bars.empty:
        return {**base, "phase": PHASE_NO_BREAK_YET}

    setup = _detect_two_stage_breakout(exec_bars, range_hi, range_lo, cfg)
    return {**base, **setup}


def generate_trade_signals(
    df_5m: pd.DataFrame, market: str, *, cfg: BramhastraConfig | None = None,
) -> list[dict[str, Any]]:
    """One setup outcome per past session day (skips today, which the live
    read handles separately)."""
    cfg = cfg or BramhastraConfig()
    windows = session_windows(market, cfg)
    work = _drop_ambiguous_date_column(_ensure_market_tz(df_5m, market, asset_class=cfg.asset_class))
    if work.empty:
        return []

    obs_start, obs_end = _observation_window(windows)
    trade_windows = {"trade_start": obs_end, "trade_end": windows["market_close"]}
    now_ts = pd.Timestamp.now(tz=_ensure_market_tz(df_5m, market, asset_class=cfg.asset_class).index.tz)
    today_session = _active_session_date(now_ts, trade_windows)

    session_dates = _session_date_series(work)
    out: list[dict[str, Any]] = []
    for day in sorted(session_dates.unique()):
        if day == today_session:
            continue
        result = _analyze_session(work, day, windows, cfg)
        if result.get("phase") not in (PHASE_NO_RANGE_DATA,):
            out.append(result)
    return out[-30:]


def evaluate_live_signal(
    df_5m: pd.DataFrame, market: str, *, cfg: BramhastraConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or BramhastraConfig()
    windows = session_windows(market, cfg)
    work = _drop_ambiguous_date_column(_ensure_market_tz(df_5m, market, asset_class=cfg.asset_class))
    if work.empty:
        return enrich_intra_live({
            "signal": "NONE", "direction": "—", "take_trade": False, "verdict": "WAIT — no data",
            "phase": PHASE_NO_RANGE_DATA, "confidence_pct": 10.0, "reasons": ["No intraday data available."],
        }, hold_duration=HOLD)

    obs_start, obs_end = _observation_window(windows)
    trade_windows = {"trade_start": obs_end, "trade_end": windows["market_close"]}
    now_ts = pd.Timestamp.now(tz=work.index.tz)
    today_session = _active_session_date(now_ts, trade_windows)

    result = _analyze_session(work, today_session, windows, cfg, is_today=True, now_ts=now_ts)
    phase = result.get("phase")

    price = float(work["close"].iloc[-1])
    reasons = [
        f"Session profile: {windows['label']}",
        f"Observation 1H range: {obs_start.strftime('%H:%M')}–{obs_end.strftime('%H:%M')} {windows['tz_name']} "
        f"→ 5m execution to {windows['market_close'].strftime('%H:%M')}",
    ]

    direction = "—"
    verdict = "WAIT"
    conf = 25.0
    entry_price = price
    stop = price
    target = price
    sl_pct = 0.0
    tp_pct = 0.0

    range_hi = result.get("range_high")
    range_lo = result.get("range_low")
    if range_hi is not None and range_lo is not None:
        reasons.append(f"1H range High **{range_hi}** / Low **{range_lo}** ({result.get('range_pct')}% of price)")

    if phase == PHASE_BUILDING_RANGE:
        verdict = "WAIT — building 1H range"
        conf = 20.0
        reasons.append("First 1-hour candle of the session isn't complete yet — nothing to mark.")
    elif phase == PHASE_NO_RANGE_DATA:
        verdict = "WAIT — insufficient data"
        conf = 15.0
        reasons.append("Could not build the first-hour range from available data.")
    elif phase == PHASE_MONSTER_SKIP:
        verdict = "AVOID — monster first-hour candle"
        conf = 15.0
        reasons.append(
            f"First-hour range is {result.get('range_pct')}% of price (≥{cfg.monster_range_pct}% threshold) — "
            "an unusually wide opening range often means chop for the rest of the day. Skip this session."
        )
    elif phase == PHASE_NO_BREAK_YET:
        verdict = "WATCH — range marked, no break yet"
        conf = 32.0
        reasons.append("Waiting for a 5m candle to CLOSE beyond the range high or low (fake breakouts that don't close beyond it are ignored).")
    elif phase in (PHASE_CONFIRMED_LONG, PHASE_CONFIRMED_SHORT):
        direction = str(result.get("direction"))
        confirm_level = result.get("confirm_level")
        verdict = f"WATCH {direction} — breakout confirmed, waiting for trigger"
        conf = 55.0
        side = "high" if direction == "LONG" else "low"
        reasons.append(
            f"A 5m candle closed beyond the range {'high' if direction=='LONG' else 'low'} at {result.get('confirm_time')} — "
            f"confirmation candle's {side} **{confirm_level}** is now marked. Entry triggers when a later candle breaks this level."
        )
    elif phase in (PHASE_TRIGGERED_LONG, PHASE_TRIGGERED_SHORT):
        direction = str(result.get("direction"))
        entry_price = float(result["entry_price"])
        stop = float(result["stop_price"])
        target = float(result["target_price"])
        sl_pct = float(result["sl_pct"])
        tp_pct = float(result["tp_pct"])
        conf = 75.0
        verdict = f"TAKE {direction}"
        reasons.append(
            f"Confirmation level **{result.get('confirm_level')}** broken at {result.get('trigger_time')} — "
            f"entry **{entry_price}** · SL **{stop}** ({sl_pct}%) · TP **{target}** ({tp_pct}%, {cfg.rr_ratio}:1 R:R)."
        )
        reasons.append(f"{direction} = {'Call Buy / Put Sell' if direction == 'LONG' else 'Put Buy / Call Sell'} on the options side.")
        reasons.append("One trade per session — ignore further breaks today once triggered.")

    conf = max(10.0, min(92.0, conf))
    take = phase in (PHASE_TRIGGERED_LONG, PHASE_TRIGGERED_SHORT) and conf >= cfg.take_confidence_threshold

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=EXEC_TF,
        stop_loss_pct=round(sl_pct, 2) if sl_pct else None,
        take_profit_pct=round(tp_pct, 2) if tp_pct else None,
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule=f"Fixed {cfg.max_sl_pct}% SL · {cfg.rr_ratio}:1 R:R target. Trail after target if comfortable.",
        max_hold_exit="Flatten by session end if neither SL nor TP hit.",
    )

    return enrich_intra_live({
        "signal": "BUY" if take and direction == "LONG" else ("SELL" if take and direction == "SHORT" else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(plan["stop_loss_pct"], 2) if take else round(sl_pct, 2),
        "tp_pct": round(plan["take_profit_pct"], 2) if take else round(tp_pct, 2),
        "hold_duration": HOLD,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(entry_price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "range_high": range_hi,
        "range_low": range_lo,
        "range_pct": result.get("range_pct"),
        "confirm_level": result.get("confirm_level"),
        "session_profile": windows["label"],
        "asset_class": windows.get("profile"),
        "observation_tf": OBSERVATION_TF,
        "execution_tf": EXEC_TF,
        "observation_start": obs_start.strftime("%H:%M"),
        "observation_end": obs_end.strftime("%H:%M"),
        "session_close": windows["market_close"].strftime("%H:%M"),
        "tz": windows["tz_name"],
        "youtube": YOUTUBE_URL,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD},
    }, hold_duration=HOLD)


def fetch_data(
    ticker: str, market: str, cfg: BramhastraConfig, *, groww_token: str = "", exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(ticker, EXEC_TF, market, groww_token, exchange, limit=cfg.lookback_bars)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, EXEC_TF, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )
    return _drop_ambiguous_date_column(_ensure_market_tz(df, market, asset_class=cfg.asset_class))


def analyze_ticker(
    ticker: str, market: str, *, cfg: BramhastraConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BramhastraConfig()
    df = fetch_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)

    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {EXEC_TF} data."}

    signals = generate_trade_signals(df, market, cfg=cfg)
    live = evaluate_live_signal(df, market, cfg=cfg)
    windows = session_windows(market, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "observation_tf": OBSERVATION_TF,
        "execution_tf": EXEC_TF,
        "session_profile": windows["label"],
        "asset_class": windows.get("profile"),
        "bars": len(df),
        "last_close": float(df["close"].iloc[-1]),
        "signal_count": len(signals),
        "signals": signals,
        "live": live,
    }


def build_chart_payload(
    ticker: str, market: str, cfg: BramhastraConfig | None = None, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Chart data for today's session (or the most recent complete one, if
    today's 1H range hasn't formed yet) — 5m candles plus the range high/low
    as zones and, once a setup exists, the confirmation level or the
    triggered entry/SL/TP as labeled reference lines."""
    cfg = cfg or BramhastraConfig()
    df = fetch_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"error": f"Insufficient {EXEC_TF} data for {ticker}."}

    windows = session_windows(market, cfg)
    obs_start, obs_end = _observation_window(windows)
    trade_windows = {"trade_start": obs_end, "trade_end": windows["market_close"]}
    now_ts = pd.Timestamp.now(tz=df.index.tz)
    today_session = _active_session_date(now_ts, trade_windows)

    session_day = today_session
    result = _analyze_session(df, session_day, windows, cfg, is_today=True, now_ts=now_ts)
    if result.get("phase") in (PHASE_BUILDING_RANGE, PHASE_NO_RANGE_DATA):
        session_dates = sorted(_session_date_series(df).unique())
        past_days = [d for d in session_dates if d != today_session]
        if past_days:
            session_day = past_days[-1]
            result = _analyze_session(df, session_day, windows, cfg)

    day_bars = df.loc[df.index.date == session_day]
    if day_bars.empty:
        return {"error": f"No {EXEC_TF} bars found for session {session_day}."}

    bars = [
        {
            "time": str(idx),
            "open": round(float(row["open"]), 6), "high": round(float(row["high"]), 6),
            "low": round(float(row["low"]), 6), "close": round(float(row["close"]), 6),
            "volume": round(float(row["volume"]), 2) if "volume" in day_bars.columns and pd.notna(row.get("volume")) else None,
        }
        for idx, row in day_bars.iterrows()
    ]

    range_hi = result.get("range_high")
    range_lo = result.get("range_low")
    phase = result.get("phase")

    levels: list[dict[str, Any]] = []
    if phase in (PHASE_TRIGGERED_LONG, PHASE_TRIGGERED_SHORT):
        levels.append({"price": result["entry_price"], "label": f"Entry {result['entry_price']}", "color": "#38bdf8"})
        levels.append({"price": result["stop_price"], "label": f"SL {result['stop_price']}", "color": "#f43f5e"})
        levels.append({"price": result["target_price"], "label": f"TP {result['target_price']}", "color": "#10b981"})
    elif phase in (PHASE_CONFIRMED_LONG, PHASE_CONFIRMED_SHORT) and result.get("confirm_level") is not None:
        levels.append({"price": result["confirm_level"], "label": f"Trigger level {result['confirm_level']}", "color": "#facc15"})

    return {
        "ticker": ticker,
        "session_date": str(session_day),
        "is_today": session_day == today_session,
        "timeframe": EXEC_TF,
        "chart_data": bars,
        "support_zone": [round(range_lo, 6), round(range_lo, 6)] if range_lo is not None else None,
        "resistance_zone": [round(range_hi, 6), round(range_hi, 6)] if range_hi is not None else None,
        "levels": levels,
        "last_close": float(day_bars["close"].iloc[-1]),
        "phase": phase,
        "direction": result.get("direction"),
        "range_pct": result.get("range_pct"),
        "observation_start": obs_start.strftime("%H:%M"),
        "observation_end": obs_end.strftime("%H:%M"),
        "session_close": windows["market_close"].strftime("%H:%M"),
        "tz": windows["tz_name"],
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: BramhastraConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BramhastraConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("Bramhastra scan failed for %s", ticker)
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("phase") in (PHASE_CONFIRMED_LONG, PHASE_CONFIRMED_SHORT, PHASE_NO_BREAK_YET)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "strategy": STRATEGY_NAME,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
