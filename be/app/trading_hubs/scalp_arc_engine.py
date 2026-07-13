"""
scalp_arc_engine.py
-------------------
ARC Method scalping — Area · Range · Candle (Doug / 26-year institutional blueprint).

Only trade the four boundary zones (box high/low + swing high/low).
Range validates via 20%+ unabated move; John Wick hammer triggers entry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.fakeout_4h_engine import INDIA_MARKET_CLOSE, INDIA_MARKET_OPEN, IST_TZ, NY_TZ
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_ARC_URL = "https://www.youtube.com/watch?v=T7QN-yqryr4&t=329s"

PHASE_NONE = "NO_SETUP"
PHASE_MIDDLE = "MIDDLE_NO_TRADE"
PHASE_AREA_LONG = "AREA_BUY_ZONE"
PHASE_AREA_SHORT = "AREA_SELL_ZONE"
PHASE_RANGE_OK = "RANGE_VALIDATED"
PHASE_SIGNAL = "JOHN_WICK"
PHASE_ENTRY = "ARC_ENTRY"

SIGNAL_BUY = 1
SIGNAL_SELL = -1

HOLD_ARC = "ARC scalp · target 50–100% box range · session exit if flat"


@dataclass
class ArcArea:
    box_high: float
    box_low: float
    swing_high: float | None
    swing_low: float | None
    box_range: float
    gapped: bool
    session_date: object = None


@dataclass
class ArcConfig:
    execution_tf: str = "5m"
    swing_window: int = 5
    zone_proximity_pct: float = 12.0
    range_move_min_pct: float = 20.0
    target_box_pct: float = 75.0
    wick_body_ratio: float = 2.0
    sl_buffer_pct: float = 0.05
    take_confidence_threshold: float = 58.0
    lookback_bars: int = 600
    min_bars: int = 80


def _ensure_market_tz(df: pd.DataFrame, market: str) -> pd.DataFrame:
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    work = work.copy()
    idx = pd.to_datetime(work.index)
    tz = IST_TZ if "Groww" in market else NY_TZ
    if idx.tz is not None:
        work.index = idx.tz_convert(tz)
    else:
        hours = idx.hour
        max_h = int(hours.max())
        median_h = float(np.median(hours))
        if "Groww" in market and max_h <= 11 and median_h < 8:
            work.index = idx.tz_localize("UTC").tz_convert(tz)
        else:
            work.index = idx.tz_localize(tz)
    return work


def _regular_session_mask(index: pd.DatetimeIndex, market: str) -> pd.Series:
    if "Groww" in market:
        return pd.Series(
            [INDIA_MARKET_OPEN <= ts.time() <= INDIA_MARKET_CLOSE for ts in index],
            index=index,
        )
    return pd.Series(True, index=index)


def _daily_ohlc(work: pd.DataFrame, market: str) -> pd.DataFrame:
    mask = _regular_session_mask(work.index, market)
    sess = work.loc[mask]
    if sess.empty:
        sess = work
    daily = sess.groupby(sess.index.normalize()).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"},
    ).dropna()
    return daily


def _nearest_swing_high_above(
    highs: np.ndarray, box_high: float, end_idx: int, window: int,
) -> float | None:
    # Only accept a bar as a confirmed swing once `window` later bars exist to
    # confirm it — otherwise the still-forming last bars could be mistaken for
    # a confirmed swing high (look-ahead-free confirmation lag).
    for i in range(end_idx - 1 - window, window, -1):
        left = max(0, i - window)
        right = min(len(highs), i + window + 1)
        if highs[i] == highs[left:right].max() and highs[i] > box_high:
            return float(highs[i])
    above = highs[:end_idx]
    above = above[above > box_high]
    return float(above.max()) if len(above) else None


def _nearest_swing_low_below(
    lows: np.ndarray, box_low: float, end_idx: int, window: int,
) -> float | None:
    for i in range(end_idx - 1 - window, window, -1):
        left = max(0, i - window)
        right = min(len(lows), i + window + 1)
        if lows[i] == lows[left:right].min() and lows[i] < box_low:
            return float(lows[i])
    below = lows[:end_idx]
    below = below[below < box_low]
    return float(below.min()) if len(below) else None


def _build_arc_area(
    work: pd.DataFrame,
    end_idx: int,
    market: str,
    cfg: ArcConfig,
) -> ArcArea | None:
    daily = _daily_ohlc(work.iloc[:end_idx], market)
    if len(daily) < 2:
        return None

    prev = daily.iloc[-2]
    box_high = float(prev["high"])
    box_low = float(prev["low"])
    gapped = False

    today_key = work.index[end_idx - 1].normalize()
    today_bars = work.iloc[:end_idx]
    today_bars = today_bars[today_bars.index.normalize() == today_key]
    if today_bars.empty:
        return None

    if "Groww" in market:
        reg = today_bars[
            today_bars.index.map(lambda t: INDIA_MARKET_OPEN <= t.time() <= INDIA_MARKET_CLOSE)
        ]
        pre = today_bars[today_bars.index.map(lambda t: t.time() < INDIA_MARKET_OPEN)]
    else:
        reg = today_bars
        pre = pd.DataFrame()

    if not reg.empty:
        session_open = float(reg["open"].iloc[0])
        if session_open > box_high or session_open < box_low:
            gapped = True
            if not pre.empty:
                box_high = float(max(box_high, pre["high"].max()))
                box_low = float(min(box_low, pre["low"].min()))
            else:
                box_high = float(max(box_high, reg["high"].iloc[0]))
                box_low = float(min(box_low, reg["low"].iloc[0]))

    box_range = max(box_high - box_low, box_high * 0.002)
    highs = work["high"].values[:end_idx]
    lows = work["low"].values[:end_idx]
    swing_high = _nearest_swing_high_above(highs, box_high, end_idx, cfg.swing_window)
    swing_low = _nearest_swing_low_below(lows, box_low, end_idx, cfg.swing_window)

    return ArcArea(
        box_high=box_high,
        box_low=box_low,
        swing_high=swing_high,
        swing_low=swing_low,
        box_range=box_range,
        gapped=gapped,
        session_date=today_key,
    )


def _near_zone(price: float, level: float, box_range: float, proximity_pct: float) -> bool:
    tol = box_range * (proximity_pct / 100.0)
    return abs(price - level) <= tol


def _zone_side(
    price: float, area: ArcArea, proximity_pct: float,
) -> tuple[str, str | None]:
    """Return (side, zone_name) — side LONG/SHORT/WAIT/MIDDLE."""
    levels_long = [("box_low", area.box_low)]
    levels_short = [("box_high", area.box_high)]
    if area.swing_low is not None:
        levels_long.append(("swing_low", area.swing_low))
    if area.swing_high is not None:
        levels_short.append(("swing_high", area.swing_high))

    for name, lvl in levels_long:
        if _near_zone(price, lvl, area.box_range, proximity_pct):
            return "LONG", name
    for name, lvl in levels_short:
        if _near_zone(price, lvl, area.box_range, proximity_pct):
            return "SHORT", name

    if area.box_low < price < area.box_high:
        return "MIDDLE", None
    return "WAIT", None


def _john_wick_hammer(o: float, h: float, l: float, c: float, ratio: float) -> bool:
    body = max(abs(c - o), (h - l) * 0.08)
    lower = min(o, c) - l
    upper = h - max(o, c)
    return lower >= ratio * body and lower > upper


def _john_wick_inverted(o: float, h: float, l: float, c: float, ratio: float) -> bool:
    body = max(abs(c - o), (h - l) * 0.08)
    lower = min(o, c) - l
    upper = h - max(o, c)
    return upper >= ratio * body and upper > lower


def _unabated_move_ok(
    work: pd.DataFrame,
    end_idx: int,
    direction: str,
    area: ArcArea,
    min_pct: float,
    market: str,
) -> tuple[bool, float]:
    today_key = work.index[end_idx - 1].normalize()
    day = work.iloc[:end_idx]
    day = day[day.index.normalize() == today_key]
    mask = _regular_session_mask(day.index, market)
    day = day.loc[mask] if mask.any() else day
    if day.empty:
        return False, 0.0

    move_need = area.box_range * (min_pct / 100.0)
    if direction == "LONG":
        session_hi = float(day["high"].max())
        zone = min(area.box_low, area.swing_low or area.box_low)
        move = session_hi - zone
    else:
        session_lo = float(day["low"].min())
        zone = max(area.box_high, area.swing_high or area.box_high)
        move = zone - session_lo

    pct = (move / area.box_range * 100.0) if area.box_range else 0.0
    return move >= move_need, pct


def implement_arc_strategy(
    df: pd.DataFrame,
    cfg: ArcConfig,
    market: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = _ensure_market_tz(df, market)
    if work.empty:
        return work, {}

    work = work.copy()
    work["signal"] = 0
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["setup_phase"] = PHASE_NONE
    work["box_high"] = np.nan
    work["box_low"] = np.nan
    work["zone_name"] = ""

    state: dict[str, Any] = {
        "pending_signal": None,
        "area": None,
        "setups": [],
    }

    n = len(work)
    for i in range(cfg.min_bars, n):
        ts = work.index[i]
        area = _build_arc_area(work, i + 1, market, cfg)
        if area is None:
            continue

        work.at[ts, "box_high"] = area.box_high
        work.at[ts, "box_low"] = area.box_low
        state["area"] = area

        row = work.iloc[i]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        side, zone_name = _zone_side(c, area, cfg.zone_proximity_pct)

        if side == "MIDDLE":
            work.at[ts, "setup_phase"] = PHASE_MIDDLE
            state["pending_signal"] = None
            continue

        if side == "WAIT":
            work.at[ts, "setup_phase"] = PHASE_NONE
            continue

        move_ok, move_pct = _unabated_move_ok(work, i + 1, side, area, cfg.range_move_min_pct, market)
        if not move_ok:
            work.at[ts, "setup_phase"] = PHASE_AREA_LONG if side == "LONG" else PHASE_AREA_SHORT
            continue

        work.at[ts, "setup_phase"] = PHASE_RANGE_OK
        work.at[ts, "zone_name"] = zone_name or ""

        pending = state.get("pending_signal")
        if pending and pending.get("bar_index") == i - 1:
            sig = pending
            if sig["direction"] == "LONG" and h > sig["trigger_high"]:
                sl = sig["wick_low"] * (1 - cfg.sl_buffer_pct / 100)
                risk = max(c - sl, c * 0.002)
                tp = c + area.box_range * (cfg.target_box_pct / 100.0)
                work.at[ts, "signal"] = SIGNAL_BUY
                work.at[ts, "stop_loss"] = sl
                work.at[ts, "take_profit"] = tp
                work.at[ts, "setup_phase"] = PHASE_ENTRY
                state["pending_signal"] = None
                state["setups"].append({"direction": "LONG", "bar_index": i, "zone": sig.get("zone")})
            elif sig["direction"] == "SHORT" and l < sig["trigger_low"]:
                sl = sig["wick_high"] * (1 + cfg.sl_buffer_pct / 100)
                risk = max(sl - c, c * 0.002)
                tp = c - area.box_range * (cfg.target_box_pct / 100.0)
                work.at[ts, "signal"] = SIGNAL_SELL
                work.at[ts, "stop_loss"] = sl
                work.at[ts, "take_profit"] = tp
                work.at[ts, "setup_phase"] = PHASE_ENTRY
                state["pending_signal"] = None
                state["setups"].append({"direction": "SHORT", "bar_index": i, "zone": sig.get("zone")})
            else:
                state["pending_signal"] = None

        if side == "LONG" and _john_wick_hammer(o, h, l, c, cfg.wick_body_ratio):
            work.at[ts, "setup_phase"] = PHASE_SIGNAL
            state["pending_signal"] = {
                "direction": "LONG",
                "bar_index": i,
                "trigger_high": h,
                "wick_low": l,
                "zone": zone_name,
                "move_pct": move_pct,
            }
        elif side == "SHORT" and _john_wick_inverted(o, h, l, c, cfg.wick_body_ratio):
            work.at[ts, "setup_phase"] = PHASE_SIGNAL
            state["pending_signal"] = {
                "direction": "SHORT",
                "bar_index": i,
                "trigger_low": l,
                "wick_high": h,
                "zone": zone_name,
                "move_pct": move_pct,
            }

    return work, state


def _signal_history(work: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(len(work) - 1, -1, -1):
        sig = int(work["signal"].iloc[i]) if not pd.isna(work["signal"].iloc[i]) else 0
        if sig == 0:
            continue
        ts = work.index[i]
        rows.append({
            "time": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "signal": "BUY" if sig == SIGNAL_BUY else "SELL",
            "close": round(float(work["close"].iloc[i]), 4),
            "zone": str(work["zone_name"].iloc[i] or "—"),
            "box_high": round(float(work["box_high"].iloc[i]), 4) if pd.notna(work["box_high"].iloc[i]) else None,
            "box_low": round(float(work["box_low"].iloc[i]), 4) if pd.notna(work["box_low"].iloc[i]) else None,
        })
        if len(rows) >= limit:
            break
    return rows


def evaluate_live_signal(
    work: pd.DataFrame,
    state: dict[str, Any],
    cfg: ArcConfig,
    market: str,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = float(work["close"].iloc[-1])
    latest_sig = int(work["signal"].iloc[-1]) if not pd.isna(work["signal"].iloc[-1]) else 0
    phase = str(work["setup_phase"].iloc[-1])
    area: ArcArea | None = state.get("area")
    pending = state.get("pending_signal")

    reasons: list[str] = []
    conf = 20.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    stop = price
    target = price
    zone_name = str(work["zone_name"].iloc[-1] or "")

    if area is None:
        return enrich_intra_live({"signal": "NO_DATA", "verdict": "NO_DATA", "reasons": ["Insufficient session history"]})

    reasons.append(
        f"Area — box {area.box_low:,.4g}–{area.box_high:,.4g} "
        f"(range {area.box_range:,.4g})"
        + (" · gap-adjusted pre-market box" if area.gapped else "")
    )
    if area.swing_high:
        reasons.append(f"Swing high (sell zone) {area.swing_high:,.4g}")
    if area.swing_low:
        reasons.append(f"Swing low (buy zone) {area.swing_low:,.4g}")

    side, zn = _zone_side(price, area, cfg.zone_proximity_pct)
    zone_name = zn or zone_name

    if side == "MIDDLE":
        phase = PHASE_MIDDLE
        verdict = "AVOID — middle of box"
        reasons.append("Core ARC rule: do not trade the middle — only the four boundaries")
        conf = 18.0
    elif side in ("LONG", "SHORT"):
        direction = side
        move_ok, move_pct = _unabated_move_ok(work, len(work), side, area, cfg.range_move_min_pct, market)
        if not move_ok:
            phase = PHASE_AREA_LONG if side == "LONG" else PHASE_AREA_SHORT
            verdict = f"WATCH {side} — awaiting {cfg.range_move_min_pct}% range move"
            conf += 16
            reasons.append(
                f"At {zone_name or 'boundary'} — move {move_pct:.0f}% of box "
                f"(need ≥{cfg.range_move_min_pct}%)"
            )
        else:
            conf += 22
            reasons.append(f"Range OK — unabated move {move_pct:.0f}% of box (≥{cfg.range_move_min_pct}%)")
            phase = PHASE_RANGE_OK

            if pending:
                phase = PHASE_SIGNAL
                verdict = f"WATCH {pending['direction']} — John Wick armed"
                conf += 20
                reasons.append("Signal candle (hammer / inverted hammer) at institutional zone")
                reasons.append("Await break of signal candle high (long) or low (short)")
                if pending["direction"] == "LONG":
                    stop = pending["wick_low"] * (1 - cfg.sl_buffer_pct / 100)
                    target = price + area.box_range * (cfg.target_box_pct / 100.0)
                else:
                    stop = pending["wick_high"] * (1 + cfg.sl_buffer_pct / 100)
                    target = price - area.box_range * (cfg.target_box_pct / 100.0)

            if latest_sig == SIGNAL_BUY:
                direction = "LONG"
                phase = PHASE_ENTRY
                verdict = "TAKE LONG"
                conf += 28
                stop = float(work["stop_loss"].iloc[-1]) if pd.notna(work["stop_loss"].iloc[-1]) else stop
                target = float(work["take_profit"].iloc[-1]) if pd.notna(work["take_profit"].iloc[-1]) else target
                reasons.append("Trigger candle broke above John Wick high — ARC long entry")
            elif latest_sig == SIGNAL_SELL:
                direction = "SHORT"
                phase = PHASE_ENTRY
                verdict = "TAKE SHORT"
                conf += 28
                stop = float(work["stop_loss"].iloc[-1]) if pd.notna(work["stop_loss"].iloc[-1]) else stop
                target = float(work["take_profit"].iloc[-1]) if pd.notna(work["take_profit"].iloc[-1]) else target
                reasons.append("Trigger candle broke below John Wick low — ARC short entry")

    conf = max(15.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.2, (price - stop) / price * 100)
        tp_pct = max(0.3, (target - price) / price * 100) if target > price else sl_pct * 1.5
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.2, (stop - price) / price * 100)
        tp_pct = max(0.3, (price - target) / price * 100) if target < price else sl_pct * 1.5
    else:
        sl_pct = 0.5
        tp_pct = area.box_range / price * (cfg.target_box_pct / 100.0) * 100 if price else 0.8

    hold = HOLD_ARC
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="SL beyond John Wick wick tip; target 50–100% of measured box range.",
        max_hold_exit="Session scalp — flatten if target not reached by session close.",
    )

    return enrich_intra_live({
        "signal": "BUY" if latest_sig == SIGNAL_BUY else ("SELL" if latest_sig == SIGNAL_SELL else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "box_high": area.box_high,
        "box_low": area.box_low,
        "box_range": round(area.box_range, 6),
        "swing_high": area.swing_high,
        "swing_low": area.swing_low,
        "zone_name": zone_name,
        "gapped_box": area.gapped,
        "execution_tf": cfg.execution_tf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: ArcConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(
        ticker, cfg.execution_tf, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(
                ticker, cfg.execution_tf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market,
            ),
        )
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: ArcConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ArcConfig()
    raw = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if raw.empty or len(raw) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work, state = implement_arc_strategy(raw, cfg, market)
    live = evaluate_live_signal(work, state, cfg, market)

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]) if not work.empty else 0.0,
        "signal_history": _signal_history(work),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: ArcConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ArcConfig()
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
            PHASE_AREA_LONG, PHASE_AREA_SHORT, PHASE_RANGE_OK, PHASE_SIGNAL,
        )
    ]
    avoids = [r for r in results if not r.get("error") and (r.get("live") or {}).get("phase") == PHASE_MIDDLE]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "middle_avoid": avoids,
        "entry_count": len(entries),
        "watch_count": len(watches),
        "avoid_count": len(avoids),
    }
