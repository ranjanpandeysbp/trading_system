"""
reversal_strategy_engine.py
----------------------------
Reversal Strategy — a 6-step counter-trend/range reversal checklist run on a
higher swing timeframe (Daily by default; 4h/Weekly selectable).
https://www.youtube.com/watch?v=Lz9XmfDLXxI

The 6 checks, all evaluated before a trade is considered valid:
1. Market Condition   — bullish (HH/HL), bearish (LL/LH), ranging (oscillating
                         between a top and bottom), or choppy (neither —
                         skipped outright, this strategy trades less often).
2. Market Phase       — trends move in runs then pullbacks; a reversal wants
                         the EXHAUSTION of a run (an extended move, measured
                         against ATR), not a fresh pullback.
3. Support/Resistance — horizontal zones from swing rejection clusters (with
                         a "round number" / even-handle proximity note) plus
                         angular trendlines from the last two swing points.
4. MACD Divergence    — price makes a new high/low that MACD does not
                         confirm — the classic momentum-fading tell reversal
                         traders lean on (trend traders use MAs; reversal
                         traders lean on divergence).
5. Deceleration       — candle bodies shrinking on approach to the level,
                         proof the prevailing move is losing steam right
                         there.
6. Candlestick Trigger — Low/High Test candle, Tweezer Top/Bottom, Doji, or
                         Inside Bar on the signal candle actually pulls the
                         trigger.

Entry: a couple of ticks beyond the signal candle's extreme in the reversal
direction; stop just beyond the signal candle's opposite extreme (a small
ATR-based buffer stands in for the video's "3-5 pips", since this app trades
equities/crypto/commodities, not forex). Minimum 1:1 reward:risk is enforced.

Take profit — the video gives 3 options; this engine auto-selects between
two of them based on step 1's read: in a trending market condition, target
the 50 EMA (Option 1 — price reverting to the mean it stretched away from);
in a ranging market condition, target the next major horizontal level
(Option 3). Confidence-scored like this app's other multi-step hub engines —
MACD divergence, deceleration, and the candlestick trigger are the three hard
gates; market condition/phase set context and can reject the setup outright
if the market reads as choppy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_REVERSAL_URL = "https://www.youtube.com/watch?v=Lz9XmfDLXxI"

TIMEFRAME_OPTIONS = ["4h", "1d", "1wk"]
TP_MODE_OPTIONS = ["auto", "ema_target", "range_target"]

PHASE_NONE = "NO_SETUP"
PHASE_ZONE_TAPPED = "ZONE_TAPPED"
PHASE_ENTRY = "REVERSAL_CONFIRMED"

CONDITION_BULLISH = "bullish"
CONDITION_BEARISH = "bearish"
CONDITION_RANGING = "ranging"
CONDITION_CHOPPY = "choppy"


@dataclass
class ReversalConfig:
    timeframe: str = "1d"
    tp_mode: str = "auto"
    swing_window: int = 5
    zone_lookback_bars: int = 80
    zone_tap_buffer_pct: float = 0.2
    condition_swings: int = 3
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    deceleration_lookback: int = 4
    stop_buffer_atr_mult: float = 0.15
    rr_min: float = 1.0
    take_confidence_threshold: float = 60.0
    min_bars: int = 100
    lookback_bars: int = 300


# ---------------------------------------------------------------------------
# Shared low-level helpers (self-contained, matching the style of the other
# hub engines rather than a shared library)
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=max(2, period // 2)).mean()


def _swing_columns(df: pd.DataFrame, window: int) -> pd.DataFrame:
    out = df.copy()
    half = max(1, window // 2)
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    swing_hi = np.full(n, np.nan)
    swing_lo = np.full(n, np.nan)

    for i in range(half, n - half):
        w_hi = highs[i - half : i + half + 1].max()
        w_lo = lows[i - half : i + half + 1].min()
        if highs[i] == w_hi:
            swing_hi[i] = highs[i]
        if lows[i] == w_lo:
            swing_lo[i] = lows[i]

    out["swing_high"] = swing_hi
    out["swing_low"] = swing_lo
    return out


def _zone_from_swing(df: pd.DataFrame, idx: int, is_high: bool) -> dict[str, Any]:
    bar = df.iloc[idx]
    body_top = max(bar["open"], bar["close"])
    body_bottom = min(bar["open"], bar["close"])
    if is_high:
        return {"top": float(bar["high"]), "bottom": float(body_top), "origin_index": idx}
    return {"top": float(body_bottom), "bottom": float(bar["low"]), "origin_index": idx}


def find_active_zones(df: pd.DataFrame, cfg: ReversalConfig) -> dict[str, dict[str, Any] | None]:
    """Nearest horizontal support/resistance zones, break-and-retest role
    flip included, same construction used across this app's other hubs."""
    swung = _swing_columns(df, cfg.swing_window)
    n = len(df)
    start = max(0, n - cfg.zone_lookback_bars)
    price = float(df["close"].iloc[-1])
    closes = df["close"].values

    candidates: list[dict[str, Any]] = []
    for i in range(start, n):
        if not pd.isna(swung["swing_high"].iloc[i]):
            zone = _zone_from_swing(df, i, is_high=True)
            role = "resistance"
            after = closes[i + 1 :]
            if len(after) and after.max() > zone["top"]:
                role = "support"
            candidates.append({**zone, "role": role})
        if not pd.isna(swung["swing_low"].iloc[i]):
            zone = _zone_from_swing(df, i, is_high=False)
            role = "support"
            after = closes[i + 1 :]
            if len(after) and after.min() < zone["bottom"]:
                role = "resistance"
            candidates.append({**zone, "role": role})

    support = None
    resistance = None
    for z in sorted(candidates, key=lambda z: -z["origin_index"]):
        if z["role"] == "support" and z["top"] <= price and support is None:
            support = z
        elif z["role"] == "resistance" and z["bottom"] >= price and resistance is None:
            resistance = z
        if support and resistance:
            break

    return {"support": support, "resistance": resistance}


def find_trendline(df: pd.DataFrame, cfg: ReversalConfig, *, ascending: bool) -> dict[str, Any] | None:
    """Angular support (ascending, from the last two higher swing lows) or
    angular resistance (descending, from the last two lower swing highs)."""
    swung = _swing_columns(df, cfg.swing_window)
    n = len(df)
    window = swung.iloc[max(0, n - cfg.zone_lookback_bars):]
    series = window["swing_low"].dropna() if ascending else window["swing_high"].dropna()
    if len(series) < 2:
        return None
    p1, p2 = float(series.iloc[-2]), float(series.iloc[-1])
    i1, i2 = df.index.get_loc(series.index[-2]), df.index.get_loc(series.index[-1])
    if i2 <= i1:
        return None
    if ascending and p2 <= p1:
        return None
    if not ascending and p2 >= p1:
        return None
    slope = (p2 - p1) / (i2 - i1)
    proj_price = p2 + slope * (n - 1 - i2)
    return {"type": "ascending" if ascending else "descending", "current_price": round(float(proj_price), 6)}


def _nearest_round_level(price: float) -> float:
    """Proxy for the video's forex 'even handle' (00/50) concept, generalized
    across wildly different price scales (a ₹24000 index vs a ₹150 stock) by
    rounding to the nearest half order-of-magnitude step below the price."""
    if price <= 0:
        return 0.0
    magnitude = 10 ** np.floor(np.log10(price))
    step = magnitude / 2
    return round(price / step) * step


def classify_market_condition(df: pd.DataFrame, cfg: ReversalConfig) -> dict[str, Any]:
    """Step 1 (bullish/bearish/ranging/choppy) + step 2 (run vs pullback
    phase, via how extended the latest push is relative to ATR)."""
    swung = _swing_columns(df, cfg.swing_window)
    n = len(df)
    window = swung.iloc[max(0, n - cfg.zone_lookback_bars):]
    highs = window["swing_high"].dropna()
    lows = window["swing_low"].dropna()

    condition = CONDITION_CHOPPY
    if len(highs) >= cfg.condition_swings and len(lows) >= cfg.condition_swings:
        h = highs.iloc[-cfg.condition_swings:].values
        l = lows.iloc[-cfg.condition_swings:].values
        rising_highs = all(h[i] < h[i + 1] for i in range(len(h) - 1))
        rising_lows = all(l[i] < l[i + 1] for i in range(len(l) - 1))
        falling_highs = all(h[i] > h[i + 1] for i in range(len(h) - 1))
        falling_lows = all(l[i] > l[i + 1] for i in range(len(l) - 1))
        h_range = h.max() - h.min()
        l_range = l.max() - l.min()
        mid = float(df["close"].iloc[-1])
        oscillating = (h_range / mid < 0.03 if mid else False) and (l_range / mid < 0.03 if mid else False)

        if rising_highs and rising_lows:
            condition = CONDITION_BULLISH
        elif falling_highs and falling_lows:
            condition = CONDITION_BEARISH
        elif oscillating:
            condition = CONDITION_RANGING

    atr = _atr(df, 14)
    atr_last = float(atr.dropna().iloc[-1]) if not atr.dropna().empty else None
    phase = "unclear"
    run_extension = None
    if atr_last and atr_last > 0 and not lows.empty and not highs.empty:
        last_extreme_idx = max(lows.index[-1], highs.index[-1])
        pos = df.index.get_loc(last_extreme_idx)
        run_move = float(df["close"].iloc[-1] - df["close"].iloc[pos])
        run_extension = abs(run_move) / atr_last
        phase = "run" if run_extension >= 2.0 else "pullback"

    return {
        "condition": condition,
        "phase": phase,
        "run_extension_atr": round(run_extension, 2) if run_extension is not None else None,
        "near_round_number": abs(float(df["close"].iloc[-1]) - _nearest_round_level(float(df["close"].iloc[-1]))) / float(df["close"].iloc[-1]) * 100 <= 0.3 if float(df["close"].iloc[-1]) else False,
    }


def _macd(df: pd.DataFrame, cfg: ReversalConfig) -> pd.DataFrame:
    close = df["close"]
    fast = close.ewm(span=cfg.macd_fast, adjust=False).mean()
    slow = close.ewm(span=cfg.macd_slow, adjust=False).mean()
    macd_line = fast - slow
    signal_line = macd_line.ewm(span=cfg.macd_signal, adjust=False).mean()
    out = df.copy()
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = macd_line - signal_line
    return out


def detect_macd_divergence(df: pd.DataFrame, cfg: ReversalConfig) -> dict[str, Any] | None:
    """Bullish divergence (price lower low, MACD higher low) or bearish
    divergence (price higher high, MACD lower high) at the two most recent
    comparable swing points — the step-4 momentum-fading tell."""
    swung = _swing_columns(df, cfg.swing_window)
    macd_line = df["macd"]

    highs = swung["swing_high"].dropna()
    if len(highs) >= 2:
        i1, i2 = highs.index[-2], highs.index[-1]
        p1, p2 = float(highs.loc[i1]), float(highs.loc[i2])
        m1, m2 = macd_line.get(i1), macd_line.get(i2)
        if m1 is not None and m2 is not None and pd.notna(m1) and pd.notna(m2) and p2 > p1 and m2 < m1:
            return {
                "direction": "bearish",
                "note": f"price made a higher high ({p1:,.4g} → {p2:,.4g}) but MACD made a lower high ({m1:,.4g} → {m2:,.4g})",
            }

    lows = swung["swing_low"].dropna()
    if len(lows) >= 2:
        i1, i2 = lows.index[-2], lows.index[-1]
        p1, p2 = float(lows.loc[i1]), float(lows.loc[i2])
        m1, m2 = macd_line.get(i1), macd_line.get(i2)
        if m1 is not None and m2 is not None and pd.notna(m1) and pd.notna(m2) and p2 < p1 and m2 > m1:
            return {
                "direction": "bullish",
                "note": f"price made a lower low ({p1:,.4g} → {p2:,.4g}) but MACD made a higher low ({m1:,.4g} → {m2:,.4g})",
            }
    return None


def detect_deceleration(df: pd.DataFrame, cfg: ReversalConfig) -> bool:
    """Step 5 — candle bodies shrinking on approach to the level: each of the
    last `deceleration_lookback` bars has a smaller body than the one before."""
    n = len(df)
    if n < cfg.deceleration_lookback + 1:
        return False
    tail = df.iloc[-cfg.deceleration_lookback:]
    bodies = (tail["close"] - tail["open"]).abs().values
    return bool(all(bodies[i] > bodies[i + 1] for i in range(len(bodies) - 1)))


def detect_candlestick_trigger(df: pd.DataFrame, direction: str) -> dict[str, Any] | None:
    """Step 6 — the actual entry-trigger candle: Low/High Test, Tweezer
    Top/Bottom, Doji, or Inside Bar, checked on the latest bar."""
    if len(df) < 2:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    o, h, l, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
    po, ph, pl, pc = float(prev["open"]), float(prev["high"]), float(prev["low"]), float(prev["close"])
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)

    if body <= rng * 0.1:
        return {"name": "Doji", "note": "small indecision body at the level"}

    if h <= ph and l >= pl:
        return {"name": "Inside Bar", "note": "consolidating fully inside the prior bar's range at the level"}

    tol = rng * 0.15
    if abs(l - pl) <= tol and c > l:
        return {"name": "Tweezer Bottom" if direction == "LONG" else "Tweezer", "note": "two matching lows rejecting the same level"}
    if abs(h - ph) <= tol and c < h:
        return {"name": "Tweezer Top" if direction == "SHORT" else "Tweezer", "note": "two matching highs rejecting the same level"}

    if direction == "LONG" and lower_wick >= body * 1.5 and c > o:
        return {"name": "Low Test", "note": "long lower wick rejecting a fresh low, closing back up"}
    if direction == "SHORT" and upper_wick >= body * 1.5 and c < o:
        return {"name": "High Test", "note": "long upper wick rejecting a fresh high, closing back down"}

    return None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_reversal_pipeline(df: pd.DataFrame, cfg: ReversalConfig) -> dict[str, Any]:
    work = normalize_ohlcv(df)
    if work.empty or len(work) < cfg.min_bars:
        return {"error": f"Insufficient {cfg.timeframe} data."}
    work = _macd(work, cfg)
    ema50 = work["close"].ewm(span=50, adjust=False).mean()
    ema20 = work["close"].ewm(span=20, adjust=False).mean()
    return {"df": work, "ema50": ema50, "ema20": ema20}


def evaluate_live_signal(pipeline: dict[str, Any], cfg: ReversalConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    df, ema50, ema20 = pipeline["df"], pipeline["ema50"], pipeline["ema20"]
    price = float(df["close"].iloc[-1])
    zones = find_active_zones(df, cfg)
    support, resistance = zones["support"], zones["resistance"]
    ascending_tl = find_trendline(df, cfg, ascending=True)
    descending_tl = find_trendline(df, cfg, ascending=False)

    mkt = classify_market_condition(df, cfg)
    reasons: list[str] = [
        f"Step 1 — Market condition: {mkt['condition']}"
        + (f" (near a round-number handle)" if mkt["near_round_number"] else "") + ".",
        f"Step 2 — Market phase: {mkt['phase']}"
        + (f" (~{mkt['run_extension_atr']}x ATR since the last swing)" if mkt["run_extension_atr"] is not None else "") + ".",
    ]

    if support:
        reasons.append(f"Step 3 — Horizontal support zone at {support['bottom']:,.4g}–{support['top']:,.4g}.")
    if resistance:
        reasons.append(f"Step 3 — Horizontal resistance zone at {resistance['bottom']:,.4g}–{resistance['top']:,.4g}.")
    if ascending_tl:
        reasons.append(f"Step 3 — Ascending trendline support projects to ~{ascending_tl['current_price']:,.4g}.")
    if descending_tl:
        reasons.append(f"Step 3 — Descending trendline resistance projects to ~{descending_tl['current_price']:,.4g}.")

    buf_s = (support["top"] - support["bottom"]) * cfg.zone_tap_buffer_pct if support else 0
    buf_r = (resistance["top"] - resistance["bottom"]) * cfg.zone_tap_buffer_pct if resistance else 0
    tapping_support = bool(support and support["bottom"] - buf_s <= price <= support["top"] + buf_s)
    tapping_resistance = bool(resistance and resistance["bottom"] - buf_r <= price <= resistance["top"] + buf_r)

    direction = "WAIT"
    zone = None
    if tapping_support:
        direction, zone = "LONG", support
    elif tapping_resistance:
        direction, zone = "SHORT", resistance

    phase = PHASE_NONE
    verdict = "NO_SETUP"
    conf = 20.0
    entry, stop, target = price, price, price
    take = False

    if mkt["condition"] == CONDITION_CHOPPY:
        reasons.append("Market condition is choppy/indecisive — this strategy deliberately sits out choppy markets.")
    elif zone is None:
        reasons.append("Price isn't tapping a horizontal support/resistance zone right now — no level to react at.")
    else:
        phase = PHASE_ZONE_TAPPED
        atr_last = float(_atr(df, 14).dropna().iloc[-1]) if not _atr(df, 14).dropna().empty else max(price * 0.01, 0.01)

        divergence = detect_macd_divergence(df, cfg)
        wanted_div = "bullish" if direction == "LONG" else "bearish"
        divergence_ok = bool(divergence and divergence["direction"] == wanted_div)
        if divergence:
            reasons.append(f"Step 4 — MACD Divergence ({divergence['direction']}): {divergence['note']} — {'favors' if divergence_ok else 'wrong direction for'} this {direction}.")
        else:
            reasons.append("Step 4 — MACD Divergence: none found at the recent swing points yet.")
        if divergence_ok:
            conf += 20

        deceleration_ok = detect_deceleration(df, cfg)
        reasons.append(
            "Step 5 — Deceleration: candle bodies are progressively shrinking into the level — momentum fading."
            if deceleration_ok else
            "Step 5 — Deceleration: no shrinking-body sequence into the level yet."
        )
        if deceleration_ok:
            conf += 15

        trigger = detect_candlestick_trigger(df, direction)
        if trigger:
            reasons.append(f"Step 6 — Candlestick trigger: {trigger['name']} — {trigger['note']}.")
        else:
            reasons.append("Step 6 — Candlestick trigger: no Low/High Test, Tweezer, Doji, or Inside Bar on the latest bar yet.")
        trigger_ok = trigger is not None
        if trigger_ok:
            conf += 20

        if mkt["condition"] in (CONDITION_BULLISH, CONDITION_BEARISH):
            conf += 10

        if divergence_ok and deceleration_ok and trigger_ok:
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            last = df.iloc[-1]
            buffer = atr_last * cfg.stop_buffer_atr_mult
            if direction == "LONG":
                entry = float(last["high"]) + buffer
                stop = float(last["low"]) - buffer
            else:
                entry = float(last["low"]) - buffer
                stop = float(last["high"]) + buffer

            tp_mode = cfg.tp_mode
            if tp_mode == "auto":
                tp_mode = "range_target" if mkt["condition"] == CONDITION_RANGING else "ema_target"

            if tp_mode == "range_target":
                opposing = resistance if direction == "LONG" else support
                target = opposing["bottom"] if (opposing and direction == "LONG") else (opposing["top"] if opposing else None)
                tp_note = "next major horizontal level (ranging market)"
            else:
                target = float(ema50.iloc[-1])
                tp_note = "the 50 EMA (price reverting to the mean it stretched away from)"

            risk = abs(entry - stop) or max(price * 0.005, 0.01)
            min_reward_target = entry + risk * cfg.rr_min if direction == "LONG" else entry - risk * cfg.rr_min
            if target is None or (direction == "LONG" and target < min_reward_target) or (direction == "SHORT" and target > min_reward_target):
                target = min_reward_target
                tp_note += ", extended to hold the minimum 1:1 reward:risk"
            reasons.append(f"All 3 hard gates confirm (Divergence, Deceleration, Trigger) — target: {tp_note}.")
        else:
            verdict = f"WATCH {direction}"
            missing = [n for n, ok in (("MACD Divergence", divergence_ok), ("Deceleration", deceleration_ok), ("Candlestick Trigger", trigger_ok)) if not ok]
            reasons.append(f"Waiting on: {', '.join(missing)} before this is a confirmed setup.")

        take = phase == PHASE_ENTRY

    conf = max(10.0, min(90.0, conf))
    take = take and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < entry:
        sl_pct = max(0.15, (entry - stop) / entry * 100)
        tp_pct = max(0.2, (target - entry) / entry * 100) if target > entry else sl_pct
    elif direction == "SHORT" and stop > entry:
        sl_pct = max(0.15, (stop - entry) / entry * 100)
        tp_pct = max(0.2, (entry - target) / entry * 100) if target < entry else sl_pct
    else:
        sl_pct = 0.5
        tp_pct = 0.5

    hold = hold_for_tf(cfg.timeframe, "swing")
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule="Target the 50 EMA or the next major level per the market-condition read. Exit if price closes back beyond the zone (setup invalidated).",
        max_hold_exit="Re-evaluate weekly — this is a patience-first setup, pending orders may sit unfilled for days.",
    )

    return enrich_smc_live({
        "signal": direction if phase == PHASE_ENTRY else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6) if target is not None else None,
        "market_condition": mkt["condition"],
        "market_phase": mkt["phase"],
        "support_zone": [round(support["bottom"], 6), round(support["top"], 6)] if support else None,
        "resistance_zone": [round(resistance["bottom"], 6), round(resistance["top"], 6)] if resistance else None,
        "timeframe": cfg.timeframe,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: ReversalConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, cfg.timeframe, market, groww_token, exchange, limit=cfg.lookback_bars)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.timeframe, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: ReversalConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ReversalConfig()
    df = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.timeframe} data."}

    pipeline = run_reversal_pipeline(df, cfg)
    if pipeline.get("error"):
        return {"ticker": ticker, "error": pipeline["error"]}

    live = evaluate_live_signal(pipeline, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "timeframe": cfg.timeframe,
        "bars": len(pipeline["df"]),
        "last_close": float(pipeline["df"]["close"].iloc[-1]),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: ReversalConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    run_bt: bool = False,
) -> dict[str, Any]:
    cfg = cfg or ReversalConfig()
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
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "timeframe": cfg.timeframe,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
