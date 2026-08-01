"""
intraday_london_breakout_engine.py
----------------------------------
London Session Breakout — classic day-trading range breakout (Trader Dale style / NQ video).

Source: https://www.youtube.com/watch?v=8KblOEu56dM&t=2247s

Canonical rules (5m):
  1. Draw a box from the absolute high/low of the early / pre-session window.
  2. In the active trade window, enter on the first 5m candle that breaks the box.
     Long: high > range high · Short: low < range low.
  3. Stop: opposite extreme of that breakout candle.
  4. Target: strict 2:1 risk-to-reward. One trade per session.

Asset-class session windows:
  - US: Pre-Market 04:00–09:30 ET (range) → RTH 09:30–16:00 ET (trade).
        After-Hours 16:00–20:00 ET is noted but not used for entries.
  - Crypto: Low Activity 04:00–11:00 IST (range) → Global Peak 17:30–01:30 IST (trade).
            Local Prime 18:30–23:30 IST sits inside the peak window.
  - India: early cash 09:15–11:30 IST (range) → 11:30–15:30 IST (unchanged).
  - Commodity: London 03:00–08:00 ET (range) → 08:00–16:00 ET (unchanged).

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.ticker_utils import is_crypto_market
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.session_constants import (
    INDIA_MARKET_CLOSE,
    INDIA_MARKET_OPEN,
    IST_TZ,
    NY_TZ,
)

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=8KblOEu56dM&t=2247s"
STRATEGY_NAME = "London Session Breakout"
EXEC_TF = "5m"
HOLD = "Same session · 2:1 R:R · flatten by trade-window end"

PHASE_WAIT_RANGE = "WAIT_RANGE"
PHASE_RANGE_DEFINED = "RANGE_DEFINED"
PHASE_OUTSIDE_TRADE = "OUTSIDE_TRADE_WINDOW"
PHASE_BREAKOUT_LONG = "BREAKOUT_LONG"
PHASE_BREAKOUT_SHORT = "BREAKOUT_SHORT"
PHASE_DONE = "DONE"
PHASE_NONE = "NO_SETUP"


@dataclass
class LondonBreakoutConfig:
    timeframe: str = EXEC_TF
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 58.0
    lookback_bars: int = 400
    min_bars: int = 40
    # Injected by TradingHubService.scan — distinguishes US vs commodity (same Yahoo market).
    asset_class: str = ""
    # Optional overrides (HH:MM local). Empty → asset-class defaults.
    range_start: str = ""
    range_end: str = ""
    trade_start: str = ""
    trade_end: str = ""


def resolve_profile(market: str, asset_class: str = "") -> str:
    ac = (asset_class or "").strip().lower()
    if ac in ("india", "us", "crypto", "commodity"):
        return ac
    if is_crypto_market(market):
        return "crypto"
    if "Groww" in market or "India" in market:
        return "india"
    # Yahoo market without asset_class — keep prior London-style (commodity) windows.
    return "commodity"


def _profile_tz(profile: str):
    if profile in ("india", "crypto"):
        return IST_TZ
    return NY_TZ


def _parse_hhmm(value: str, fallback: time) -> time:
    raw = (value or "").strip()
    if not raw:
        return fallback
    try:
        parts = raw.split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (TypeError, ValueError):
        return fallback


def session_windows(market: str, cfg: LondonBreakoutConfig | None = None) -> dict[str, Any]:
    """Range box + trade window in the profile's local timezone."""
    cfg = cfg or LondonBreakoutConfig()
    profile = resolve_profile(market, cfg.asset_class)

    if profile == "india":
        defaults = {
            "tz_name": "Asia/Kolkata",
            "market_open": INDIA_MARKET_OPEN,
            "market_close": INDIA_MARKET_CLOSE,
            "range_start": INDIA_MARKET_OPEN,
            "range_end": time(11, 30),
            "trade_start": time(11, 30),
            "trade_end": INDIA_MARKET_CLOSE,
            "label": "India early-session range (09:15–11:30 IST) → breakout to NSE close 15:30",
            "notes": "NSE cash session only.",
        }
    elif profile == "us":
        defaults = {
            "tz_name": "America/New_York",
            "market_open": time(9, 30),
            "market_close": time(16, 0),
            "range_start": time(4, 0),   # Pre-Market
            "range_end": time(9, 30),
            "trade_start": time(9, 30),  # Regular Trading Hours
            "trade_end": time(16, 0),
            "label": (
                "US Pre-Market range (04:00–09:30 ET) → RTH breakout (09:30–16:00 ET); "
                "After-Hours 16:00–20:00 ET not used for entries"
            ),
            "notes": "Pre-Market 04:00–09:30 · RTH 09:30–16:00 · After-Hours 16:00–20:00 ET",
        }
    elif profile == "crypto":
        defaults = {
            "tz_name": "Asia/Kolkata",
            "market_open": time(17, 30),
            "market_close": time(1, 30),
            "range_start": time(4, 0),    # Low Activity Zone
            "range_end": time(11, 0),
            "trade_start": time(17, 30),  # Global Peak Volume (overnight)
            "trade_end": time(1, 30),
            "label": (
                "Crypto Low Activity range (04:00–11:00 IST) → Global Peak Volume "
                "17:30–01:30 IST (Local Prime 18:30–23:30 IST inside peak)"
            ),
            "notes": (
                "Peak 17:30–01:30 IST (12:00–20:00 UTC) · "
                "Local Prime 18:30–23:30 IST · Low Activity 04:00–11:00 IST"
            ),
        }
    else:
        # Commodity — leave existing London → NY style windows.
        defaults = {
            "tz_name": "America/New_York",
            "market_open": time(9, 30),
            "market_close": time(16, 0),
            "range_start": time(3, 0),
            "range_end": time(8, 0),
            "trade_start": time(8, 0),
            "trade_end": time(16, 0),
            "label": "Commodity London range (03:00–08:00 ET) → breakout to 16:00 ET",
            "notes": "Unchanged London-style session mapping.",
        }

    return {
        "profile": profile,
        "mode": profile,
        "tz_name": defaults["tz_name"],
        "market_open": defaults["market_open"],
        "market_close": defaults["market_close"],
        "range_start": _parse_hhmm(cfg.range_start, defaults["range_start"]),
        "range_end": _parse_hhmm(cfg.range_end, defaults["range_end"]),
        "trade_start": _parse_hhmm(cfg.trade_start, defaults["trade_start"]),
        "trade_end": _parse_hhmm(cfg.trade_end, defaults["trade_end"]),
        "label": defaults["label"],
        "notes": defaults["notes"],
    }


def _ensure_market_tz(df: pd.DataFrame, market: str, *, asset_class: str = "") -> pd.DataFrame:
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    profile = resolve_profile(market, asset_class)
    tz = _profile_tz(profile)
    work = work.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(tz)
    else:
        hours = idx.hour
        max_h = int(hours.max()) if len(hours) else 0
        median_h = float(np.median(hours)) if len(hours) else 0.0
        if profile in ("india", "crypto") and max_h <= 11 and median_h < 8:
            work.index = idx.tz_localize("UTC").tz_convert(tz)
        else:
            work.index = idx.tz_localize(tz)
    return work


def _drop_ambiguous_date_column(work: pd.DataFrame) -> pd.DataFrame:
    out = work.copy()
    if out.index.name == "date":
        out.index.name = None
    if "date" in out.columns:
        out = out.drop(columns=["date"])
    return out


def _session_date_series(work: pd.DataFrame) -> pd.Series:
    return pd.Series(work.index.date, index=work.index, name="_session_day")


def _between(t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def _is_overnight(start: time, end: time) -> bool:
    return start > end


def _slice_window(day_bars: pd.DataFrame, start: time, end: time) -> pd.DataFrame:
    if day_bars.empty:
        return day_bars
    if start < end:
        end_excl = (
            pd.Timestamp("2000-01-01")
            + pd.Timedelta(hours=end.hour, minutes=end.minute)
            - pd.Timedelta(minutes=1)
        ).time()
        if end_excl < start:
            return day_bars.iloc[0:0]
        return day_bars.between_time(start, end_excl)
    return day_bars.between_time(start, end)


def _trade_slice(day_bars: pd.DataFrame, start: time, end: time) -> pd.DataFrame:
    if day_bars.empty:
        return day_bars
    return day_bars.between_time(start, end)


def _trade_bars_for_session(
    work: pd.DataFrame,
    session_day: date,
    windows: dict[str, Any],
) -> pd.DataFrame:
    """Trade-window bars for a range-session date (supports overnight crypto peak)."""
    start, end = windows["trade_start"], windows["trade_end"]
    day_bars = work.loc[work.index.date == session_day]
    if not _is_overnight(start, end):
        return _trade_slice(day_bars, start, end)

    part1 = day_bars.between_time(start, time(23, 59)) if not day_bars.empty else day_bars
    next_day = session_day + timedelta(days=1)
    next_bars = work.loc[work.index.date == next_day]
    part2 = next_bars.between_time(time(0, 0), end) if not next_bars.empty else next_bars.iloc[0:0]
    if part1.empty and part2.empty:
        return day_bars.iloc[0:0]
    return pd.concat([part1, part2]).sort_index()


def _active_session_date(now_ts: pd.Timestamp, windows: dict[str, Any]) -> date:
    """Map wall-clock to the range-session date (overnight trade tails → prior day)."""
    d = now_ts.date()
    t = now_ts.time()
    if _is_overnight(windows["trade_start"], windows["trade_end"]) and t <= windows["trade_end"]:
        return d - timedelta(days=1)
    return d


def _build_range(day_bars: pd.DataFrame, windows: dict[str, Any]) -> tuple[float, float] | None:
    box = _slice_window(day_bars, windows["range_start"], windows["range_end"])
    if box.empty or len(box) < 2:
        return None
    hi = float(box["high"].max())
    lo = float(box["low"].min())
    if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
        return None
    return hi, lo


def _entry_from_breakout_candle(
    row: pd.Series,
    *,
    london_high: float,
    london_low: float,
    rr_ratio: float,
) -> dict[str, Any] | None:
    high = float(row["high"])
    low = float(row["low"])
    open_ = float(row["open"])

    # Prefer long if both wick extremes break (rare); otherwise first match by priority long.
    if high > london_high:
        entry = max(open_, london_high)
        stop = low
        risk = entry - stop
        if risk <= 0:
            return None
        return {
            "direction": "LONG",
            "entry_price": entry,
            "stop_loss": stop,
            "target_price": entry + rr_ratio * risk,
            "risk": risk,
        }
    if low < london_low:
        entry = min(open_, london_low)
        stop = high
        risk = stop - entry
        if risk <= 0:
            return None
        return {
            "direction": "SHORT",
            "entry_price": entry,
            "stop_loss": stop,
            "target_price": entry - rr_ratio * risk,
            "risk": risk,
        }
    return None


def generate_trade_signals(
    df_5m: pd.DataFrame,
    market: str,
    *,
    cfg: LondonBreakoutConfig | None = None,
) -> list[dict[str, Any]]:
    """One breakout attempt per session day (first break of the range box)."""
    cfg = cfg or LondonBreakoutConfig()
    windows = session_windows(market, cfg)
    work = _drop_ambiguous_date_column(_ensure_market_tz(df_5m, market, asset_class=cfg.asset_class))
    if work.empty:
        return []

    session_dates = _session_date_series(work)
    trades: list[dict[str, Any]] = []

    for day in sorted(session_dates.unique()):
        day_bars = work.loc[session_dates == day]
        levels = _build_range(day_bars, windows)
        if levels is None:
            continue
        london_high, london_low = levels

        ny = _trade_bars_for_session(work, day, windows)
        if ny.empty:
            continue

        trade_active = False
        position = 0
        entry_price = stop_loss = take_profit = 0.0
        entry_time = None

        for idx, row in ny.iterrows():
            if not trade_active:
                setup = _entry_from_breakout_candle(
                    row,
                    london_high=london_high,
                    london_low=london_low,
                    rr_ratio=cfg.rr_ratio,
                )
                if setup is None:
                    continue
                trade_active = True
                position = 1 if setup["direction"] == "LONG" else -1
                entry_price = setup["entry_price"]
                stop_loss = setup["stop_loss"]
                take_profit = setup["target_price"]
                entry_time = idx
                if position == 1:
                    if float(row["low"]) <= stop_loss:
                        trades.append({
                            "Datetime": str(entry_time),
                            "Date": str(day),
                            "Direction": "LONG",
                            "Entry_Price": round(entry_price, 4),
                            "Stop_Loss": round(stop_loss, 4),
                            "Target_Price": round(take_profit, 4),
                            "Exit_Price": round(stop_loss, 4),
                            "Result": "Loss",
                            "London_High": round(london_high, 4),
                            "London_Low": round(london_low, 4),
                        })
                        break
                    if float(row["high"]) >= take_profit:
                        trades.append({
                            "Datetime": str(entry_time),
                            "Date": str(day),
                            "Direction": "LONG",
                            "Entry_Price": round(entry_price, 4),
                            "Stop_Loss": round(stop_loss, 4),
                            "Target_Price": round(take_profit, 4),
                            "Exit_Price": round(take_profit, 4),
                            "Result": "Win",
                            "London_High": round(london_high, 4),
                            "London_Low": round(london_low, 4),
                        })
                        break
                else:
                    if float(row["high"]) >= stop_loss:
                        trades.append({
                            "Datetime": str(entry_time),
                            "Date": str(day),
                            "Direction": "SHORT",
                            "Entry_Price": round(entry_price, 4),
                            "Stop_Loss": round(stop_loss, 4),
                            "Target_Price": round(take_profit, 4),
                            "Exit_Price": round(stop_loss, 4),
                            "Result": "Loss",
                            "London_High": round(london_high, 4),
                            "London_Low": round(london_low, 4),
                        })
                        break
                    if float(row["low"]) <= take_profit:
                        trades.append({
                            "Datetime": str(entry_time),
                            "Date": str(day),
                            "Direction": "SHORT",
                            "Entry_Price": round(entry_price, 4),
                            "Stop_Loss": round(stop_loss, 4),
                            "Target_Price": round(take_profit, 4),
                            "Exit_Price": round(take_profit, 4),
                            "Result": "Win",
                            "London_High": round(london_high, 4),
                            "London_Low": round(london_low, 4),
                        })
                        break
                continue

            if position == 1:
                if float(row["low"]) <= stop_loss:
                    trades.append({
                        "Datetime": str(entry_time),
                        "Date": str(day),
                        "Direction": "LONG",
                        "Entry_Price": round(entry_price, 4),
                        "Stop_Loss": round(stop_loss, 4),
                        "Target_Price": round(take_profit, 4),
                        "Exit_Price": round(stop_loss, 4),
                        "Result": "Loss",
                        "London_High": round(london_high, 4),
                        "London_Low": round(london_low, 4),
                    })
                    break
                if float(row["high"]) >= take_profit:
                    trades.append({
                        "Datetime": str(entry_time),
                        "Date": str(day),
                        "Direction": "LONG",
                        "Entry_Price": round(entry_price, 4),
                        "Stop_Loss": round(stop_loss, 4),
                        "Target_Price": round(take_profit, 4),
                        "Exit_Price": round(take_profit, 4),
                        "Result": "Win",
                        "London_High": round(london_high, 4),
                        "London_Low": round(london_low, 4),
                    })
                    break
            else:
                if float(row["high"]) >= stop_loss:
                    trades.append({
                        "Datetime": str(entry_time),
                        "Date": str(day),
                        "Direction": "SHORT",
                        "Entry_Price": round(entry_price, 4),
                        "Stop_Loss": round(stop_loss, 4),
                        "Target_Price": round(take_profit, 4),
                        "Exit_Price": round(stop_loss, 4),
                        "Result": "Loss",
                        "London_High": round(london_high, 4),
                        "London_Low": round(london_low, 4),
                    })
                    break
                if float(row["low"]) <= take_profit:
                    trades.append({
                        "Datetime": str(entry_time),
                        "Date": str(day),
                        "Direction": "SHORT",
                        "Entry_Price": round(entry_price, 4),
                        "Stop_Loss": round(stop_loss, 4),
                        "Target_Price": round(take_profit, 4),
                        "Exit_Price": round(take_profit, 4),
                        "Result": "Win",
                        "London_High": round(london_high, 4),
                        "London_Low": round(london_low, 4),
                    })
                    break
        else:
            if trade_active and entry_time is not None:
                trades.append({
                    "Datetime": str(entry_time),
                    "Date": str(day),
                    "Direction": "LONG" if position == 1 else "SHORT",
                    "Entry_Price": round(entry_price, 4),
                    "Stop_Loss": round(stop_loss, 4),
                    "Target_Price": round(take_profit, 4),
                    "Exit_Price": None,
                    "Result": "Open",
                    "London_High": round(london_high, 4),
                    "London_Low": round(london_low, 4),
                })

    return trades


def _evaluate_today(
    work: pd.DataFrame,
    market: str,
    cfg: LondonBreakoutConfig,
) -> dict[str, Any]:
    windows = session_windows(market, cfg)
    empty = {
        "phase": PHASE_NONE,
        "london_high": None,
        "london_low": None,
        "entry": None,
        "windows": windows,
        "session_date": None,
    }
    if work.empty:
        return empty

    now_ts = work.index[-1]
    day = _active_session_date(now_ts, windows)
    day_bars = work.loc[work.index.date == day]
    now_t = now_ts.time()

    state: dict[str, Any] = {
        "phase": PHASE_NONE,
        "london_high": None,
        "london_low": None,
        "entry": None,
        "windows": windows,
        "session_date": str(day),
        "now_local": str(now_ts),
    }

    if (
        now_ts.date() == day
        and _between(now_t, windows["range_start"], windows["range_end"])
        and now_t < windows["range_end"]
    ):
        box = day_bars.between_time(windows["range_start"], now_t) if not day_bars.empty else day_bars
        if not box.empty:
            state["london_high"] = round(float(box["high"].max()), 4)
            state["london_low"] = round(float(box["low"].min()), 4)
        state["phase"] = PHASE_WAIT_RANGE
        return state

    levels = _build_range(day_bars, windows) if not day_bars.empty else None
    if levels is None:
        state["phase"] = PHASE_WAIT_RANGE
        return state

    london_high, london_low = levels
    state["london_high"] = round(london_high, 4)
    state["london_low"] = round(london_low, 4)

    if not _between(now_t, windows["trade_start"], windows["trade_end"]):
        if (
            not _is_overnight(windows["trade_start"], windows["trade_end"])
            and now_t > windows["trade_end"]
        ):
            state["phase"] = PHASE_DONE
            return state
        if now_ts.date() == day and now_t < windows["trade_start"]:
            state["phase"] = PHASE_RANGE_DEFINED
            return state
        if _is_overnight(windows["trade_start"], windows["trade_end"]):
            if now_ts.date() == day and windows["range_end"] <= now_t < windows["trade_start"]:
                state["phase"] = PHASE_RANGE_DEFINED
                return state
            if now_ts.date() > day and now_t > windows["trade_end"]:
                state["phase"] = PHASE_DONE
                return state
        state["phase"] = PHASE_OUTSIDE_TRADE
        return state

    ny = _trade_bars_for_session(work, day, windows)
    if ny.empty:
        state["phase"] = PHASE_RANGE_DEFINED
        return state

    for idx, row in ny.iterrows():
        setup = _entry_from_breakout_candle(
            row,
            london_high=london_high,
            london_low=london_low,
            rr_ratio=cfg.rr_ratio,
        )
        if setup is None:
            continue
        state["entry"] = {
            **setup,
            "entry_time": str(idx),
            "entry_price": round(setup["entry_price"], 4),
            "stop_loss": round(setup["stop_loss"], 4),
            "target_price": round(setup["target_price"], 4),
        }
        state["phase"] = (
            PHASE_BREAKOUT_LONG if setup["direction"] == "LONG" else PHASE_BREAKOUT_SHORT
        )
        return state

    state["phase"] = PHASE_RANGE_DEFINED
    return state


def evaluate_live_signal(
    df_5m: pd.DataFrame,
    market: str,
    *,
    cfg: LondonBreakoutConfig | None = None,
    signals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = cfg or LondonBreakoutConfig()
    work = _drop_ambiguous_date_column(_ensure_market_tz(df_5m, market, asset_class=cfg.asset_class))
    windows = session_windows(market, cfg)
    price = float(work["close"].iloc[-1]) if not work.empty else 0.0

    today = _evaluate_today(work, market, cfg)
    phase = today["phase"]
    london_high = today.get("london_high")
    london_low = today.get("london_low")
    entry_info = today.get("entry")

    reasons: list[str] = [
        f"Session profile: **{windows['label']}**",
        (
            f"Range window {windows['range_start'].strftime('%H:%M')}–{windows['range_end'].strftime('%H:%M')} "
            f"· Trade {windows['trade_start'].strftime('%H:%M')}–{windows['trade_end'].strftime('%H:%M')} "
            f"({windows['tz_name']})"
        ),
    ]
    if windows.get("notes"):
        reasons.append(str(windows["notes"]))
    if london_high is not None and london_low is not None:
        reasons.append(f"Range box High **{london_high}** / Low **{london_low}**")

    direction = "—"
    verdict = "WAIT"
    conf = 35.0
    stop = price
    target = price

    if phase == PHASE_WAIT_RANGE:
        verdict = "WAIT — building range box"
        conf += 5
        reasons.append("Range window still open — do not trade the breakout yet")
    elif phase == PHASE_RANGE_DEFINED:
        verdict = "WATCH — range defined, wait for break"
        conf += 12
        reasons.append("First 5m candle that breaks the box high (long) or low (short) triggers entry")
    elif phase == PHASE_OUTSIDE_TRADE:
        verdict = "WAIT — outside trade window"
        reasons.append("Outside the post-range trade window for this market")
    elif phase == PHASE_DONE:
        verdict = "DONE — session closed"
        reasons.append("Flatten by trade-window end; no new entries after trade_end")
    elif phase in (PHASE_BREAKOUT_LONG, PHASE_BREAKOUT_SHORT) and entry_info:
        direction = str(entry_info["direction"])
        stop = float(entry_info["stop_loss"])
        target = float(entry_info["target_price"])
        entry_px = float(entry_info["entry_price"])
        verdict = f"TAKE {direction}"
        conf += 35
        reasons.append(
            f"Breakout candle entry **{entry_px}** · SL at opposite candle extreme "
            f"**{stop}** · TP **{cfg.rr_ratio}:1** → **{target}**"
        )
        reasons.append("One trade per day — ignore later breaks after the first")

    if signals:
        open_or_today = [s for s in signals if s.get("Result") in ("Open", "Win", "Loss")]
        if open_or_today:
            last = open_or_today[-1]
            reasons.append(
                f"Recent signal: {last.get('Direction')} @ {last.get('Entry_Price')} "
                f"({last.get('Result')}) on {last.get('Date')}"
            )

    conf = max(10.0, min(92.0, conf))
    take = phase in (PHASE_BREAKOUT_LONG, PHASE_BREAKOUT_SHORT) and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.1, (price - stop) / price * 100)
        tp_pct = max(0.2, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.1, (stop - price) / price * 100)
        tp_pct = max(0.2, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.4
        tp_pct = sl_pct * cfg.rr_ratio

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.timeframe or EXEC_TF,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule=f"Strict **{cfg.rr_ratio}:1** R:R · SL = opposite extreme of breakout candle.",
        max_hold_exit="Close by trade-window end if neither SL nor TP hit.",
    )

    return enrich_intra_live({
        "signal": "BUY" if take and direction == "LONG" else ("SELL" if take and direction == "SHORT" else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": HOLD,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(float(entry_info["entry_price"]), 6) if entry_info else round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "london_high": london_high,
        "london_low": london_low,
        "session_profile": windows["label"],
        "asset_class": windows.get("profile"),
        "range_start": windows["range_start"].strftime("%H:%M"),
        "range_end": windows["range_end"].strftime("%H:%M"),
        "trade_start": windows["trade_start"].strftime("%H:%M"),
        "trade_end": windows["trade_end"].strftime("%H:%M"),
        "tz": windows["tz_name"],
        "execution_tf": cfg.timeframe or EXEC_TF,
        "youtube": YOUTUBE_URL,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD},
    }, hold_duration=HOLD)


def fetch_data(
    ticker: str,
    market: str,
    cfg: LondonBreakoutConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    tf = cfg.timeframe or EXEC_TF
    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(
        ticker, tf, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )
    return _drop_ambiguous_date_column(_ensure_market_tz(df, market, asset_class=cfg.asset_class))


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: LondonBreakoutConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LondonBreakoutConfig()
    df = fetch_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)

    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.timeframe or EXEC_TF} data."}

    signals = generate_trade_signals(df, market, cfg=cfg)
    live = evaluate_live_signal(df, market, cfg=cfg, signals=signals)
    windows = session_windows(market, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "execution_tf": cfg.timeframe or EXEC_TF,
        "session_profile": windows["label"],
        "asset_class": windows.get("profile"),
        "bars": len(df),
        "last_close": float(df["close"].iloc[-1]),
        "signal_count": len(signals),
        "signals": signals[-20:],
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: LondonBreakoutConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LondonBreakoutConfig()
    windows = session_windows(market, cfg)
    results = []
    for ticker in tickers:
        try:
            results.append(
                analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("London breakout failed for %s", ticker)
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("phase") in (
            PHASE_WAIT_RANGE, PHASE_RANGE_DEFINED, PHASE_BREAKOUT_LONG, PHASE_BREAKOUT_SHORT,
        )
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "asset_class": windows.get("profile"),
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "execution_tf": cfg.timeframe or EXEC_TF,
        "session_profile": windows["label"],
        "session_windows": {
            "profile": windows.get("profile"),
            "tz": windows["tz_name"],
            "range_start": windows["range_start"].strftime("%H:%M"),
            "range_end": windows["range_end"].strftime("%H:%M"),
            "trade_start": windows["trade_start"].strftime("%H:%M"),
            "trade_end": windows["trade_end"].strftime("%H:%M"),
            "market_open": windows["market_open"].strftime("%H:%M"),
            "market_close": windows["market_close"].strftime("%H:%M"),
            "notes": windows.get("notes"),
        },
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
        "disclaimer": "Research / education only — not financial advice.",
    }
