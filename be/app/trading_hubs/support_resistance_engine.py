"""
support_resistance_engine.py
------------------------------
Support and Resistance — break-and-retest zones on a higher timeframe, entry
confirmation via market structure on a lower timeframe. Works across Groww
India, US, Crypto, and Commodities (the standard market/groww_token/exchange
plumbing every hub section already gets).
https://www.youtube.com/watch?v=d5T-k_-ejd0&t=29s

The method, in order:
1. Zones, not lines — on the HTF, a resistance zone runs from the highest
   wick down to the highest candle body in a rejection cluster; a support
   zone runs from the lowest wick up to the lowest body. Price reacts to a
   zone, not an exact price.
2. Break and retest — a resistance zone that gets strongly broken above
   becomes a new support zone the next time price returns to it (and the
   mirror image for a broken support zone becoming resistance).
3. Alert, don't stare — nothing happens until price actually taps back into
   a zone.
4. Lower-timeframe confirmation — once tapped, drop to the LTF and read
   market structure. Approaching support, price should be making lower
   highs/lows; the trigger is a clean break above the most recent LTF lower
   high (the mirror image at resistance: break below the most recent higher
   low). Never enter on the tap alone.
5. Entry at the structure break; stop beyond the zone (or the pre-entry
   extreme); target the next recent structural high/low.
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

YOUTUBE_SUPPORT_RESISTANCE_URL = "https://www.youtube.com/watch?v=d5T-k_-ejd0&t=29s"

HTF_OPTIONS = ["15m", "30m", "1h", "4h", "1d", "1wk"]
LTF_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h"]

PHASE_NONE = "NO_SETUP"
PHASE_ZONE_TAPPED = "ZONE_TAPPED"
PHASE_ENTRY = "STRUCTURE_BREAK_ENTRY"


@dataclass
class SupportResistanceConfig:
    htf: str = "4h"
    ltf: str = "1m"
    zone_lookback_bars: int = 100
    swing_window: int = 3
    zone_tap_buffer_pct: float = 0.1
    rr_ratio_fallback: float = 2.0
    max_setup_age_bars: int = 40
    take_confidence_threshold: float = 60.0
    min_bars: int = 80
    lookback_bars: int = 500


# ---------------------------------------------------------------------------
# Shared low-level helpers (self-contained, matching the style of the other
# hub engines rather than a shared library)
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


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


# ---------------------------------------------------------------------------
# Step 1-2: HTF zones + break-and-retest role flip
# ---------------------------------------------------------------------------

def _zone_from_swing(df: pd.DataFrame, idx: int, is_high: bool) -> dict[str, Any]:
    """Zone = wick extreme to body extreme of the swing bar (a 1-bar
    rejection cluster keeps this simple and robust across timeframes)."""
    bar = df.iloc[idx]
    body_top = max(bar["open"], bar["close"])
    body_bottom = min(bar["open"], bar["close"])
    if is_high:
        return {"top": float(bar["high"]), "bottom": float(body_top), "origin_index": idx}
    return {"top": float(body_bottom), "bottom": float(bar["low"]), "origin_index": idx}


def _zone_candidates(df_htf: pd.DataFrame, swung: pd.DataFrame, start: int) -> list[dict[str, Any]]:
    n = len(df_htf)
    closes = df_htf["close"].values
    candidates: list[dict[str, Any]] = []
    for i in range(start, n):
        if not pd.isna(swung["swing_high"].iloc[i]):
            zone = _zone_from_swing(df_htf, i, is_high=True)
            role = "resistance"
            # Broken upward since formation -> flips to support.
            after = closes[i + 1 :]
            if len(after) and after.max() > zone["top"]:
                role = "support"
            candidates.append({**zone, "role": role, "kind": "swing_high"})
        if not pd.isna(swung["swing_low"].iloc[i]):
            zone = _zone_from_swing(df_htf, i, is_high=False)
            role = "support"
            after = closes[i + 1 :]
            if len(after) and after.min() < zone["bottom"]:
                role = "resistance"
            candidates.append({**zone, "role": role, "kind": "swing_low"})
    return candidates


def _pick_zones(candidates: list[dict[str, Any]], price: float) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    support = None
    resistance = None
    for z in sorted(candidates, key=lambda z: -z["origin_index"]):
        if z["role"] == "support" and z["top"] <= price and support is None:
            support = z
        elif z["role"] == "resistance" and z["bottom"] >= price and resistance is None:
            resistance = z
        if support and resistance:
            break
    return support, resistance


def find_active_zones(df_htf: pd.DataFrame, cfg: SupportResistanceConfig) -> dict[str, dict[str, Any] | None]:
    """Latest active support zone (below price) and resistance zone (above
    price) — each may be an original zone, or an opposite zone that's been
    broken-and-flipped per the break-and-retest rule.

    Within the recent `zone_lookback_bars` window it's possible every
    candidate on the correct side of price has already been broken-and-flipped
    away (e.g. a strong rally leaves no resistance candidate above price in
    that narrow window) even though an older, still-untouched swing level
    exists further back. Rather than showing nothing, fall back to searching
    the full available history for the nearest raw swing high/low on the
    correct side of price, so a level is always surfaced when one exists.
    """
    swung = _swing_columns(df_htf, cfg.swing_window)
    n = len(df_htf)
    start = max(0, n - cfg.zone_lookback_bars)
    price = float(df_htf["close"].iloc[-1])

    candidates = _zone_candidates(df_htf, swung, start)
    support, resistance = _pick_zones(candidates, price)

    if (support is None or resistance is None) and start > 0:
        full_candidates = _zone_candidates(df_htf, swung, 0)
        if support is None:
            lows_below = [z for z in full_candidates if z["kind"] == "swing_low" and z["top"] <= price]
            if lows_below:
                support = max(lows_below, key=lambda z: z["top"])
        if resistance is None:
            highs_above = [z for z in full_candidates if z["kind"] == "swing_high" and z["bottom"] >= price]
            if highs_above:
                resistance = min(highs_above, key=lambda z: z["bottom"])

    return {"support": support, "resistance": resistance}


# ---------------------------------------------------------------------------
# Trendline: connects the two most recent higher-lows (ascending) or the two
# most recent lower-highs (descending) — the simple, standard TA construction.
# Only returned when the swings actually support a clean, monotonic trend.
# ---------------------------------------------------------------------------

def find_trendlines(df_htf: pd.DataFrame, cfg: SupportResistanceConfig) -> list[dict[str, Any]]:
    swung = _swing_columns(df_htf, cfg.swing_window)
    n = len(df_htf)
    start = max(0, n - cfg.zone_lookback_bars)
    window = swung.iloc[start:]

    lows = window["swing_low"].dropna()
    highs = window["swing_high"].dropna()
    lines: list[dict[str, Any]] = []

    if len(lows) >= 2:
        i1, i2 = lows.index[-2], lows.index[-1]
        p1, p2 = float(lows.iloc[-2]), float(lows.iloc[-1])
        if p2 > p1:  # higher low -> ascending support trendline
            slope = (p2 - p1) / max(1, (df_htf.index.get_loc(i2) - df_htf.index.get_loc(i1)))
            proj_price = p2 + slope * (n - 1 - df_htf.index.get_loc(i2))
            lines.append({
                "type": "ascending",
                "points": [
                    {"time": str(i1), "price": round(p1, 6)},
                    {"time": str(i2), "price": round(p2, 6)},
                    {"time": str(df_htf.index[-1]), "price": round(float(proj_price), 6)},
                ],
            })

    if len(highs) >= 2:
        i1, i2 = highs.index[-2], highs.index[-1]
        p1, p2 = float(highs.iloc[-2]), float(highs.iloc[-1])
        if p2 < p1:  # lower high -> descending resistance trendline
            slope = (p2 - p1) / max(1, (df_htf.index.get_loc(i2) - df_htf.index.get_loc(i1)))
            proj_price = p2 + slope * (n - 1 - df_htf.index.get_loc(i2))
            lines.append({
                "type": "descending",
                "points": [
                    {"time": str(i1), "price": round(p1, 6)},
                    {"time": str(i2), "price": round(p2, 6)},
                    {"time": str(df_htf.index[-1]), "price": round(float(proj_price), 6)},
                ],
            })

    return lines


def build_chart_data(df_htf: pd.DataFrame, cfg: SupportResistanceConfig, *, max_bars: int = 120) -> list[dict[str, Any]]:
    tail = df_htf.iloc[-max_bars:]
    return [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
        }
        for idx, bar in tail.iterrows()
    ]


# ---------------------------------------------------------------------------
# Dedicated chart endpoint — date range + volume/EMA/RSI overlays, decoupled
# from the fixed 120-bar live-signal snapshot above so a user can inspect a
# wider window without re-running the strategy evaluation.
# ---------------------------------------------------------------------------

EMA_OVERLAY_OPTIONS = [5, 9, 20, 50, 200]
_CHART_BARS_PER_DAY = {
    "1m": 375, "3m": 125, "5m": 75, "15m": 25, "30m": 13, "1h": 7, "4h": 2, "1d": 1, "1wk": 1,
}


def _crossover_bars_ago(fast: pd.Series, slow: pd.Series) -> tuple[int, bool] | None:
    """Bars since fast/slow last flipped which is on top, and the new direction
    (True = fast now above slow). None if no crossover in the overlapping window."""
    common = fast.dropna().index.intersection(slow.dropna().index)
    if len(common) < 3:
        return None
    diff = (fast.loc[common] - slow.loc[common])
    sign = diff.apply(lambda v: 1 if v > 0 else (-1 if v < 0 else 0))
    flips = sign.index[(sign != sign.shift(1)) & (sign.shift(1) != 0) & (sign != 0)]
    flips = [f for f in flips if f != sign.index[0]]
    if not flips:
        return None
    last_flip = flips[-1]
    bars_ago = len(sign) - 1 - list(sign.index).index(last_flip)
    return bars_ago, bool(sign.loc[last_flip] > 0)


# ---------------------------------------------------------------------------
# Candlestick patterns, chart patterns (double top/bottom), and RSI divergence
# ---------------------------------------------------------------------------

def detect_candlestick_patterns(df: pd.DataFrame, lookback: int = 5) -> list[dict[str, Any]]:
    """Well-known single/multi-candle patterns in the most recent bars."""
    patterns: list[dict[str, Any]] = []
    n = len(df)
    if n < 3:
        return patterns

    opens, highs, lows, closes = df["open"].values, df["high"].values, df["low"].values, df["close"].values

    for i in range(max(2, n - lookback), n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        po, pc = opens[i - 1], closes[i - 1]
        rng = h - l
        if rng <= 0:
            continue
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        bars_ago = n - 1 - i

        if body <= rng * 0.1:
            patterns.append({
                "name": "Doji", "direction": "neutral", "bars_ago": bars_ago,
                "note": "small body relative to its range — indecision between buyers and sellers",
            })

        if c > o and pc < po and o <= pc and c >= po:
            patterns.append({
                "name": "Bullish Engulfing", "direction": "bullish", "bars_ago": bars_ago,
                "note": "this candle's body fully engulfs the prior bearish candle",
            })
        if c < o and pc > po and o >= pc and c <= po:
            patterns.append({
                "name": "Bearish Engulfing", "direction": "bearish", "bars_ago": bars_ago,
                "note": "this candle's body fully engulfs the prior bullish candle",
            })

        if body > 0 and lower_wick >= body * 2 and upper_wick <= body * 0.5:
            prior = closes[max(0, i - 5):i]
            if len(prior) >= 2 and prior[-1] < prior[0]:
                patterns.append({
                    "name": "Hammer", "direction": "bullish", "bars_ago": bars_ago,
                    "note": "long lower wick after a decline — buyers stepped in and rejected the lows",
                })

        if body > 0 and upper_wick >= body * 2 and lower_wick <= body * 0.5:
            prior = closes[max(0, i - 5):i]
            if len(prior) >= 2 and prior[-1] > prior[0]:
                patterns.append({
                    "name": "Shooting Star", "direction": "bearish", "bars_ago": bars_ago,
                    "note": "long upper wick after an advance — sellers stepped in and rejected the highs",
                })

        if i >= 2:
            o2, c2 = opens[i - 2], closes[i - 2]
            body2, body1 = abs(c2 - o2), abs(pc - po)
            if body2 > 0:
                if c2 < o2 and body1 <= body2 * 0.5 and c > o and c >= (o2 + c2) / 2:
                    patterns.append({
                        "name": "Morning Star", "direction": "bullish", "bars_ago": bars_ago,
                        "note": "3-candle bottoming reversal — long bearish candle, indecision, then a strong bullish close",
                    })
                if c2 > o2 and body1 <= body2 * 0.5 and c < o and c <= (o2 + c2) / 2:
                    patterns.append({
                        "name": "Evening Star", "direction": "bearish", "bars_ago": bars_ago,
                        "note": "3-candle topping reversal — long bullish candle, indecision, then a strong bearish close",
                    })

    dedup: dict[str, dict[str, Any]] = {}
    for p in patterns:
        key = p["name"]
        if key not in dedup or p["bars_ago"] < dedup[key]["bars_ago"]:
            dedup[key] = p
    return sorted(dedup.values(), key=lambda p: p["bars_ago"])


def detect_chart_patterns(df: pd.DataFrame, cfg: SupportResistanceConfig) -> list[dict[str, Any]]:
    """Double top / double bottom — the two most recent comparable swing
    extremes, with price now trading back through the trough/peak between them."""
    swung = _swing_columns(df, cfg.swing_window)
    highs = swung["swing_high"].dropna()
    lows = swung["swing_low"].dropna()
    price = float(df["close"].iloc[-1])
    patterns: list[dict[str, Any]] = []

    if len(highs) >= 2:
        h1, h2 = float(highs.iloc[-2]), float(highs.iloc[-1])
        if max(h1, h2) > 0 and abs(h1 - h2) / max(h1, h2) <= 0.015 and price < min(h1, h2):
            level = (h1 + h2) / 2
            patterns.append({
                "name": "Double Top", "direction": "bearish", "level": round(level, 6),
                "note": f"two comparable swing highs near {level:,.4g} — a classic bearish reversal setup if the neckline gives way",
            })

    if len(lows) >= 2:
        l1, l2 = float(lows.iloc[-2]), float(lows.iloc[-1])
        if max(l1, l2) > 0 and abs(l1 - l2) / max(l1, l2) <= 0.015 and price > max(l1, l2):
            level = (l1 + l2) / 2
            patterns.append({
                "name": "Double Bottom", "direction": "bullish", "level": round(level, 6),
                "note": f"two comparable swing lows near {level:,.4g} — a classic bullish reversal setup if the neckline gives way",
            })

    return patterns


def detect_rsi_divergence(df: pd.DataFrame, rsi_series: pd.Series | None, cfg: SupportResistanceConfig) -> list[dict[str, Any]]:
    """Price vs. RSI divergence at the two most recent comparable swing points."""
    if rsi_series is None:
        return []
    swung = _swing_columns(df, cfg.swing_window)
    out: list[dict[str, Any]] = []

    highs = swung["swing_high"].dropna()
    if len(highs) >= 2:
        i1, i2 = highs.index[-2], highs.index[-1]
        p1, p2 = float(highs.loc[i1]), float(highs.loc[i2])
        r1, r2 = rsi_series.get(i1), rsi_series.get(i2)
        if r1 is not None and r2 is not None and pd.notna(r1) and pd.notna(r2) and p2 > p1 and r2 < r1:
            out.append({
                "name": "Bearish Divergence", "direction": "bearish",
                "note": f"price made a higher high ({p1:,.4g} → {p2:,.4g}) but RSI made a lower high ({r1:.0f} → {r2:.0f}) — upside momentum is weakening",
            })

    lows = swung["swing_low"].dropna()
    if len(lows) >= 2:
        i1, i2 = lows.index[-2], lows.index[-1]
        p1, p2 = float(lows.loc[i1]), float(lows.loc[i2])
        r1, r2 = rsi_series.get(i1), rsi_series.get(i2)
        if r1 is not None and r2 is not None and pd.notna(r1) and pd.notna(r2) and p2 < p1 and r2 > r1:
            out.append({
                "name": "Bullish Divergence", "direction": "bullish",
                "note": f"price made a lower low ({p1:,.4g} → {p2:,.4g}) but RSI made a higher low ({r1:.0f} → {r2:.0f}) — downside momentum is weakening",
            })

    return out


# ---------------------------------------------------------------------------
# Bollinger Band mean-reversion check and Fibonacci retracement — a plain
# stretch-vs-mean read and a standard swing-based retracement ladder,
# offered as extra confluence context alongside the break-and-retest setup
# (not a replacement for it).
# ---------------------------------------------------------------------------

def detect_bollinger_mean_reversion(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> dict[str, Any] | None:
    """Price vs. its Bollinger Bands — flags when price is stretched far
    enough from the mean that a reversion back toward it is the higher-odds
    read (classic mean-reversion, independent of the break-and-retest trend
    logic used elsewhere in this engine)."""
    if len(df) < period:
        return None
    closes = df["close"]
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    if mid.dropna().empty or std.dropna().empty:
        return None
    mean = float(mid.iloc[-1])
    sd = float(std.iloc[-1])
    if sd <= 0 or pd.isna(mean):
        return None
    upper = mean + std_mult * sd
    lower = mean - std_mult * sd
    price = float(closes.iloc[-1])
    percent_b = (price - lower) / (upper - lower) if upper > lower else 0.5

    if percent_b >= 1.0:
        signal = "bearish"
        note = f"price ({price:,.4g}) is at/above the upper Bollinger Band ({upper:,.4g}) — stretched, favors a pullback toward the {period}-bar mean ({mean:,.4g})"
    elif percent_b <= 0.0:
        signal = "bullish"
        note = f"price ({price:,.4g}) is at/below the lower Bollinger Band ({lower:,.4g}) — stretched, favors a bounce toward the {period}-bar mean ({mean:,.4g})"
    elif percent_b >= 0.9:
        signal = "bearish"
        note = f"price is approaching the upper Bollinger Band ({upper:,.4g}) — extended, some mean-reversion risk toward {mean:,.4g}"
    elif percent_b <= 0.1:
        signal = "bullish"
        note = f"price is approaching the lower Bollinger Band ({lower:,.4g}) — extended, some mean-reversion potential toward {mean:,.4g}"
    else:
        signal = "none"
        note = f"price is trading inside its Bollinger Bands ({lower:,.4g}–{upper:,.4g}), not stretched enough for a mean-reversion read"

    return {
        "signal": signal,
        "price": round(price, 6),
        "mean": round(mean, 6),
        "upper": round(upper, 6),
        "lower": round(lower, 6),
        "percent_b": round(percent_b, 3),
        "note": note,
    }


_FIB_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]


def compute_fibonacci_retracement(df: pd.DataFrame, cfg: SupportResistanceConfig) -> dict[str, Any] | None:
    """Retracement ladder between the most recent swing high and swing low —
    0% at whichever extreme formed last (the end of the current leg), 100%
    at the one before it (the start of the leg), standard convention."""
    swung = _swing_columns(df, cfg.swing_window)
    n = len(df)
    start = max(0, n - cfg.zone_lookback_bars)
    window = swung.iloc[start:]
    highs = window["swing_high"].dropna()
    lows = window["swing_low"].dropna()
    if highs.empty or lows.empty:
        return None

    hi_idx, hi_val = highs.index[-1], float(highs.iloc[-1])
    lo_idx, lo_val = lows.index[-1], float(lows.iloc[-1])
    if hi_val <= lo_val:
        return None
    hi_pos = df.index.get_loc(hi_idx)
    lo_pos = df.index.get_loc(lo_idx)
    if hi_pos == lo_pos:
        return None

    uptrend = hi_pos > lo_pos
    start_price, end_price = (lo_val, hi_val) if uptrend else (hi_val, lo_val)
    diff = end_price - start_price

    levels = [{"ratio": r, "price": round(end_price - diff * r, 6)} for r in _FIB_RATIOS]
    price_now = float(df["close"].iloc[-1])
    nearest = min(levels, key=lambda lv: abs(lv["price"] - price_now))
    at_key_level = price_now > 0 and abs(nearest["price"] - price_now) / price_now * 100 <= 0.5

    return {
        "trend": "uptrend" if uptrend else "downtrend",
        "swing_low": round(lo_val, 6),
        "swing_high": round(hi_val, 6),
        "levels": levels,
        "nearest_level": nearest,
        "at_key_level": at_key_level,
    }


# ---------------------------------------------------------------------------
# Supply/Demand zones and Order Blocks — both optional overlays, distinct
# from the break-and-retest zones above:
#   - Supply/Demand: a short multi-bar "base" (tight-range consolidation)
#     immediately followed by a strong displacement candle — the classic
#     rally-base-drop / drop-base-rally construction.
#   - Order Block: the single last opposite-colour candle right before a
#     strong displacement candle — the standard SMC definition.
# Both are only returned while still unmitigated (price hasn't traded back
# through the zone since it formed), most-recent-first.
# ---------------------------------------------------------------------------

def _mitigated_since(df: pd.DataFrame, origin_idx: int, top: float, bottom: float) -> bool:
    after = df.iloc[origin_idx + 1:]
    if after.empty:
        return False
    return bool(((after["low"] <= top) & (after["high"] >= bottom)).any())


def detect_supply_demand_zones(
    df: pd.DataFrame, *, base_max_bars: int = 3, base_atr_mult: float = 0.6,
    displacement_atr_mult: float = 1.8, max_zones: int = 5,
) -> list[dict[str, Any]]:
    n = len(df)
    if n < 10:
        return []
    atr = _atr(df, 14)
    highs, lows, opens, closes = df["high"].values, df["low"].values, df["open"].values, df["close"].values
    ranges = highs - lows

    zones: list[dict[str, Any]] = []
    for i in range(1, n):
        a = atr.iloc[i]
        if pd.isna(a) or a <= 0 or ranges[i] < a * displacement_atr_mult:
            continue
        bullish = closes[i] > opens[i]

        base_start = i - 1
        floor_idx = max(0, i - base_max_bars)
        while base_start > floor_idx and ranges[base_start] <= a * base_atr_mult:
            base_start -= 1
        if ranges[base_start] > a * base_atr_mult:
            base_start += 1
        if base_start >= i:
            continue

        top, bottom = float(highs[base_start:i].max()), float(lows[base_start:i].min())
        zones.append({
            "top": round(top, 6), "bottom": round(bottom, 6),
            "type": "demand" if bullish else "supply",
            "origin_time": str(df.index[base_start]),
            "mitigated": _mitigated_since(df, i, top, bottom),
        })

    active = [z for z in zones if not z["mitigated"]]
    active.sort(key=lambda z: z["origin_time"], reverse=True)
    return active[:max_zones]


def detect_order_blocks(
    df: pd.DataFrame, *, displacement_atr_mult: float = 1.8, max_blocks: int = 5,
) -> list[dict[str, Any]]:
    n = len(df)
    if n < 5:
        return []
    atr = _atr(df, 14)
    highs, lows, opens, closes = df["high"].values, df["low"].values, df["open"].values, df["close"].values
    ranges = highs - lows

    blocks: list[dict[str, Any]] = []
    for i in range(1, n):
        a = atr.iloc[i]
        if pd.isna(a) or a <= 0 or ranges[i] < a * displacement_atr_mult:
            continue
        impulse_bullish = closes[i] > opens[i]
        prev = i - 1
        prev_bullish = closes[prev] > opens[prev]
        if impulse_bullish and not prev_bullish:
            ob_type = "bullish"
        elif not impulse_bullish and prev_bullish:
            ob_type = "bearish"
        else:
            continue

        top, bottom = float(highs[prev]), float(lows[prev])
        blocks.append({
            "top": round(top, 6), "bottom": round(bottom, 6), "type": ob_type,
            "origin_time": str(df.index[prev]),
            "mitigated": _mitigated_since(df, i, top, bottom),
        })

    active = [b for b in blocks if not b["mitigated"]]
    active.sort(key=lambda b: b["origin_time"], reverse=True)
    return active[:max_blocks]


def build_observation_summary(
    df: pd.DataFrame,
    zones: dict[str, dict[str, Any] | None],
    *,
    ema_series: dict[int, pd.Series],
    rsi_series: pd.Series | None,
    include_volume: bool,
) -> list[str]:
    obs: list[str] = []
    if df.empty:
        return obs
    price = float(df["close"].iloc[-1])

    support, resistance = zones.get("support"), zones.get("resistance")
    if support:
        dist = (price - support["top"]) / price * 100
        obs.append(
            f"Price is {dist:.1f}% above the nearest support zone ({support['bottom']:,.4g}–{support['top']:,.4g})."
            if dist >= 0 else
            f"Price is inside/below the nearest support zone ({support['bottom']:,.4g}–{support['top']:,.4g}) — a break, not a bounce."
        )
    if resistance:
        dist = (resistance["bottom"] - price) / price * 100
        obs.append(
            f"Price is {dist:.1f}% below the nearest resistance zone ({resistance['bottom']:,.4g}–{resistance['top']:,.4g})."
            if dist >= 0 else
            f"Price is inside/above the nearest resistance zone ({resistance['bottom']:,.4g}–{resistance['top']:,.4g}) — a break, not a rejection."
        )
    if not support and not resistance:
        obs.append("No clear support/resistance zone found in the visible range.")

    if include_volume and "volume" in df.columns and len(df) >= 20:
        recent_vol = float(df["volume"].iloc[-5:].mean())
        avg_vol = float(df["volume"].iloc[-20:].mean())
        if avg_vol > 0:
            pct = (recent_vol - avg_vol) / avg_vol * 100
            if abs(pct) >= 15:
                obs.append(
                    f"Volume is running {abs(pct):.0f}% {'above' if pct > 0 else 'below'} its 20-bar average — "
                    f"{'above-average participation backing recent moves' if pct > 0 else 'quiet trading, moves may lack conviction'}."
                )
            else:
                obs.append("Volume is in line with its recent average — no unusual participation either way.")

    if rsi_series is not None and not rsi_series.dropna().empty:
        rsi_val = float(rsi_series.dropna().iloc[-1])
        if rsi_val >= 70:
            obs.append(f"RSI(14) is {rsi_val:.0f} — overbought, momentum stretched to the upside.")
        elif rsi_val <= 30:
            obs.append(f"RSI(14) is {rsi_val:.0f} — oversold, momentum stretched to the downside.")
        else:
            obs.append(f"RSI(14) is {rsi_val:.0f} — neutral, no extreme momentum either way.")

    ema_last: dict[int, float] = {}
    for period, series in sorted(ema_series.items()):
        clean = series.dropna()
        if clean.empty:
            continue
        val = float(clean.iloc[-1])
        ema_last[period] = val
        side = "above" if price > val else "below"
        near = abs(price - val) / price * 100 < 0.5
        obs.append(
            f"Price is trading {side} its {period} EMA ({val:,.4g}){' — sitting right on it, acting as active support/resistance' if near else '.'}"
        )

    periods_sorted = sorted(ema_series.keys())
    for i in range(len(periods_sorted)):
        for j in range(i + 1, len(periods_sorted)):
            fast_p, slow_p = periods_sorted[i], periods_sorted[j]
            cross = _crossover_bars_ago(ema_series[fast_p], ema_series[slow_p])
            if cross is None:
                continue
            bars_ago, fast_now_above = cross
            if bars_ago > 20:
                continue
            direction = "bullish" if fast_now_above else "bearish"
            obs.append(
                f"{fast_p} EMA crossed {'above' if fast_now_above else 'below'} the {slow_p} EMA "
                f"{bars_ago} bar(s) ago — {direction} crossover."
            )

    return obs


# ---------------------------------------------------------------------------
# Breakout / breakdown probability — a transparent, rules-based ESTIMATE
# (not a trained model) blending momentum, volume, EMA structure, and how
# many times the level has already been tested. Reported so it's clearly
# a heuristic read of current conditions, not a statistical forecast.
# ---------------------------------------------------------------------------

def estimate_breakout_breakdown(
    df: pd.DataFrame,
    zones: dict[str, dict[str, Any] | None],
    *,
    ema_series: dict[int, pd.Series],
    rsi_series: pd.Series | None,
) -> dict[str, Any]:
    price = float(df["close"].iloc[-1])
    out: dict[str, Any] = {"breakout": None, "breakdown": None}
    if df.empty:
        return out

    rsi_last = None
    if rsi_series is not None and not rsi_series.dropna().empty:
        rsi_last = float(rsi_series.dropna().iloc[-1])

    vol_signal = 0.0
    if "volume" in df.columns and len(df) >= 20:
        recent_vol = float(df["volume"].iloc[-5:].mean())
        avg_vol = float(df["volume"].iloc[-20:].mean())
        if avg_vol > 0:
            vol_signal = (recent_vol - avg_vol) / avg_vol

    ema_last = {p: float(s.dropna().iloc[-1]) for p, s in ema_series.items() if not s.dropna().empty}
    total_emas = len(ema_last)
    above_emas = sum(1 for v in ema_last.values() if price > v)
    below_emas = total_emas - above_emas

    atr = _atr(df, 14)
    atr_last = float(atr.dropna().iloc[-1]) if not atr.dropna().empty else None
    tail = df.iloc[-40:]

    resistance = zones.get("resistance")
    if resistance:
        dist_pct = (resistance["bottom"] - price) / price * 100
        touches = int(((tail["high"] >= resistance["bottom"]) & (tail["low"] <= resistance["top"])).sum())
        proximity_weight = _clamp(1 - abs(dist_pct) / 5, 0.2, 1.0)
        signal = 0.0
        if rsi_last is not None:
            if 55 <= rsi_last <= 75:
                signal += 12
            elif rsi_last > 80:
                signal -= 12
            elif rsi_last < 45:
                signal -= 8
        signal += _clamp(vol_signal * 30, -15, 20)
        if total_emas:
            signal += (above_emas / total_emas - 0.5) * 30
        if touches >= 2:
            signal += 6
        prob = round(_clamp(50 + signal * proximity_weight, 5, 90), 1)
        move_pct = round(max((resistance["top"] - resistance["bottom"]), atr_last or 0) / price * 100 * 1.5, 2) if price else None
        out["breakout"] = {
            "level": round(resistance["bottom"], 6),
            "probability_pct": prob,
            "distance_pct": round(dist_pct, 2),
            "touches_recent": touches,
            "projected_move_pct": move_pct,
        }

    support = zones.get("support")
    if support:
        dist_pct = (price - support["top"]) / price * 100
        touches = int(((tail["low"] <= support["top"]) & (tail["high"] >= support["bottom"])).sum())
        proximity_weight = _clamp(1 - abs(dist_pct) / 5, 0.2, 1.0)
        signal = 0.0
        if rsi_last is not None:
            if 25 <= rsi_last <= 45:
                signal += 12
            elif rsi_last < 20:
                signal -= 12
            elif rsi_last > 55:
                signal -= 8
        signal += _clamp(-vol_signal * 30, -15, 20)
        if total_emas:
            signal += (below_emas / total_emas - 0.5) * 30
        if touches >= 2:
            signal += 6
        prob = round(_clamp(50 + signal * proximity_weight, 5, 90), 1)
        move_pct = round(max((support["top"] - support["bottom"]), atr_last or 0) / price * 100 * 1.5, 2) if price else None
        out["breakdown"] = {
            "level": round(support["top"], 6),
            "probability_pct": prob,
            "distance_pct": round(dist_pct, 2),
            "touches_recent": touches,
            "projected_move_pct": move_pct,
        }

    return out


def build_chart_payload(
    ticker: str,
    market: str,
    cfg: SupportResistanceConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    start_date: str | None = None,
    end_date: str | None = None,
    ltf: str | None = None,
    include_volume: bool = True,
    ema_periods: list[int] | None = None,
    include_rsi: bool = False,
    include_fibonacci: bool = False,
    include_supply_demand: bool = False,
    include_order_blocks: bool = False,
) -> dict[str, Any]:
    """Chart data for the Support and Resistance UI — its own timeframe/date
    range independent of the live-signal HTF/LTF pair, with optional volume,
    EMA, and RSI overlays, plus a plain-English observation summary."""
    is_crypto = "CoinDCX" in market
    limit = cfg.lookback_bars
    if start_date and end_date:
        try:
            days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1
        except Exception:
            days = 180
        bars_per_day = _CHART_BARS_PER_DAY.get(cfg.htf, 1)
        limit = max(150, min(3000, int(days * bars_per_day * 1.3) + 50))

    df = fetch_data_for_gap_scan(ticker, cfg.htf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, cfg.htf, is_crypto=is_crypto, limit=limit, market=market))
    if df.empty:
        return {"error": f"Insufficient {cfg.htf} data for {ticker}."}

    if start_date:
        df = df[df.index >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df.index <= pd.Timestamp(end_date) + pd.Timedelta(days=1)]
    if df.empty:
        return {"error": "No bars in the selected date range."}
    if not start_date and not end_date:
        df = df.iloc[-min(len(df), 300):]

    zones = find_active_zones(df, cfg)
    trendlines = find_trendlines(df, cfg)

    ema_series: dict[int, pd.Series] = {}
    emas_out: dict[str, list[dict[str, Any]]] = {}
    for period in sorted(set(p for p in (ema_periods or []) if p > 0)):
        if period >= len(df):
            continue
        series = df["close"].ewm(span=period, adjust=False).mean()
        ema_series[period] = series
        emas_out[str(period)] = [
            {"time": str(idx), "value": round(float(v), 6)} for idx, v in series.items()
        ]

    # Computed unconditionally (cheap) since the breakout/breakdown estimate
    # below benefits from it even when the user hasn't toggled RSI ON for
    # the chart itself — only the plotted `rsi_out` points respect the toggle.
    rsi_series: pd.Series | None = None
    rsi_out: list[dict[str, Any]] | None = None
    if len(df) > 14:
        from app.market_pulse.indicators import add_rsi

        work = add_rsi(df.copy(), 14)
        rsi_series = work["rsi_14"]
        if include_rsi:
            rsi_out = [
                {"time": str(idx), "value": round(float(v), 2)}
                for idx, v in rsi_series.items() if pd.notna(v)
            ]

    bars = [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if include_volume and "volume" in df.columns else None,
        }
        for idx, bar in df.iterrows()
    ]

    summary = build_observation_summary(
        df, zones, ema_series=ema_series, rsi_series=rsi_series, include_volume=include_volume,
    )

    bollinger = detect_bollinger_mean_reversion(df)
    if bollinger and bollinger["signal"] != "none":
        summary.append(f"Bollinger Bands (20, 2σ) — {bollinger['note']} (%B {bollinger['percent_b']:.2f}).")

    fibonacci = compute_fibonacci_retracement(df, cfg) if include_fibonacci else None
    if fibonacci:
        nl = fibonacci["nearest_level"]
        summary.append(
            f"Fibonacci retracement of the recent {fibonacci['trend']} ({fibonacci['swing_low']:,.4g}–{fibonacci['swing_high']:,.4g}): "
            f"price is nearest the {nl['ratio'] * 100:.1f}% level ({nl['price']:,.4g})"
            + (" — sitting right at a key retracement zone." if fibonacci["at_key_level"] else ".")
        )

    supply_demand_zones = detect_supply_demand_zones(df) if include_supply_demand else []
    for z in supply_demand_zones[:3]:
        summary.append(
            f"{'Demand' if z['type'] == 'demand' else 'Supply'} zone (base + breakout) at "
            f"{z['bottom']:,.4g}–{z['top']:,.4g}, formed {z['origin_time']}."
        )

    order_blocks = detect_order_blocks(df) if include_order_blocks else []
    for ob in order_blocks[:3]:
        summary.append(
            f"{'Bullish' if ob['type'] == 'bullish' else 'Bearish'} order block at "
            f"{ob['bottom']:,.4g}–{ob['top']:,.4g}, formed {ob['origin_time']}."
        )

    # Trade setup — always evaluated against CURRENT data, independent of any
    # date range picked for the chart view above, so browsing history never
    # produces a stale "live" verdict. Reuses the exact same strategy
    # evaluation the live scan uses (Permission/tap/structure-break), just
    # with the chart's own HTF/LTF pair.
    trade_setup: dict[str, Any] | None = None
    setup_cfg = SupportResistanceConfig(
        htf=cfg.htf, ltf=ltf or cfg.ltf,
        zone_lookback_bars=cfg.zone_lookback_bars, swing_window=cfg.swing_window,
        lookback_bars=cfg.lookback_bars, min_bars=cfg.min_bars,
    )
    try:
        setup_result = analyze_ticker(ticker, market, cfg=setup_cfg, groww_token=groww_token, exchange=exchange)
    except Exception as exc:
        setup_result = {"error": str(exc)[:200]}
    if not setup_result.get("error"):
        live = setup_result.get("live") or {}
        trade_setup = {
            "verdict": live.get("verdict"),
            "direction": live.get("direction"),
            "take_trade": bool(live.get("take_trade")),
            "confidence_pct": live.get("confidence_pct"),
            "sl_pct": live.get("sl_pct"),
            "tp_pct": live.get("tp_pct"),
            "hold_duration": live.get("hold_duration"),
            "htf": setup_cfg.htf,
            "ltf": setup_cfg.ltf,
        }
        summary.append(
            f"Trade setup ({setup_cfg.ltf} entry / {setup_cfg.htf} zones, live): {trade_setup['verdict']} "
            f"— {trade_setup['confidence_pct']}% confidence, SL {trade_setup['sl_pct']}%, TP {trade_setup['tp_pct']}%, "
            f"stay in trade ~{trade_setup['hold_duration']}."
        )

        # Confluence — does the Bollinger mean-reversion read and/or the
        # Fibonacci retracement level agree with this setup's direction, or
        # conflict with it? Informational only; does not alter the setup's
        # own confidence_pct, which comes from the break-and-retest engine.
        direction = trade_setup.get("direction")
        confluence: list[str] = []
        if bollinger and bollinger["signal"] != "none":
            agrees = (bollinger["signal"] == "bullish" and direction == "LONG") or (bollinger["signal"] == "bearish" and direction == "SHORT")
            confluence.append(
                f"Bollinger Band mean-reversion is {bollinger['signal']} — "
                f"{'supports' if agrees else 'conflicts with'} this {direction or 'setup'}."
            )
        if fibonacci and fibonacci["at_key_level"]:
            nl = fibonacci["nearest_level"]
            confluence.append(
                f"Price is at the {nl['ratio'] * 100:.1f}% Fibonacci retracement of the recent {fibonacci['trend']} — "
                "a common reaction zone, adding confluence to a reaction here either way."
            )
        trade_setup["confluence_notes"] = confluence

    breakout_breakdown = estimate_breakout_breakdown(
        df, zones, ema_series=ema_series, rsi_series=rsi_series,
    )
    bo, bd = breakout_breakdown.get("breakout"), breakout_breakdown.get("breakdown")
    if bo:
        summary.append(
            f"Breakout above {bo['level']:,.4g} (resistance): ~{bo['probability_pct']:.0f}% likely from here "
            f"(rules-based estimate, not a statistical forecast) — tested {bo['touches_recent']}x recently; "
            f"if it breaks, a typical initial move is around {bo['projected_move_pct']:.1f}% higher."
        )
    if bd:
        summary.append(
            f"Breakdown below {bd['level']:,.4g} (support): ~{bd['probability_pct']:.0f}% likely from here "
            f"(rules-based estimate, not a statistical forecast) — tested {bd['touches_recent']}x recently; "
            f"if it breaks, a typical initial move is around {bd['projected_move_pct']:.1f}% lower."
        )

    candle_patterns = detect_candlestick_patterns(df)
    for cp in candle_patterns:
        when = "on the latest bar" if cp["bars_ago"] == 0 else f"{cp['bars_ago']} bar(s) ago"
        summary.append(f"Candlestick pattern — {cp['name']} ({cp['direction']}) {when}: {cp['note']}.")

    chart_patterns = detect_chart_patterns(df, cfg)
    for pat in chart_patterns:
        summary.append(f"Chart pattern — {pat['name']} ({pat['direction']}): {pat['note']}.")

    divergences = detect_rsi_divergence(df, rsi_series, cfg)
    for dv in divergences:
        summary.append(f"{dv['name']}: {dv['note']}.")

    return {
        "ticker": ticker,
        "timeframe": cfg.htf,
        "chart_data": bars,
        "support_zone": [round(zones["support"]["bottom"], 6), round(zones["support"]["top"], 6)] if zones.get("support") else None,
        "resistance_zone": [round(zones["resistance"]["bottom"], 6), round(zones["resistance"]["top"], 6)] if zones.get("resistance") else None,
        "trendlines": trendlines,
        "emas": emas_out,
        "rsi": rsi_out,
        "trade_setup": trade_setup,
        "breakout": bo,
        "breakdown": bd,
        "candlestick_patterns": candle_patterns,
        "chart_patterns": chart_patterns,
        "divergences": divergences,
        "bollinger": bollinger,
        "fibonacci": fibonacci,
        "supply_demand_zones": supply_demand_zones,
        "order_blocks": order_blocks,
        "include_volume": include_volume,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Step 4: LTF market-structure-break confirmation after a zone tap
# ---------------------------------------------------------------------------

def _structure_break_after_tap(df_ltf: pd.DataFrame, direction: str, tap_index: int, swing_window: int) -> int | None:
    swung = _swing_columns(df_ltf, max(3, swing_window - 1))
    after = swung.iloc[tap_index:]
    if direction == "LONG":
        highs = after["swing_high"].dropna()
        if highs.empty:
            return None
        level = float(highs.iloc[0])
        broke = df_ltf.iloc[tap_index:][df_ltf["close"].iloc[tap_index:] > level]
        return df_ltf.index.get_loc(broke.index[0]) if not broke.empty else None
    lows = after["swing_low"].dropna()
    if lows.empty:
        return None
    level = float(lows.iloc[0])
    broke = df_ltf.iloc[tap_index:][df_ltf["close"].iloc[tap_index:] < level]
    return df_ltf.index.get_loc(broke.index[0]) if not broke.empty else None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_sr_pipeline(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, cfg: SupportResistanceConfig) -> dict[str, Any]:
    ltf = normalize_ohlcv(df_ltf)
    htf = normalize_ohlcv(df_htf)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"error": f"Insufficient {cfg.ltf} data."}
    if htf.empty or len(htf) < max(cfg.swing_window * 4, 20):
        return {"error": f"Insufficient {cfg.htf} data."}
    return {"ltf": ltf, "htf": htf}


def evaluate_live_signal(pipeline: dict[str, Any], cfg: SupportResistanceConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    ltf, htf = pipeline["ltf"], pipeline["htf"]
    price = float(ltf["close"].iloc[-1])
    zones = find_active_zones(htf, cfg)
    support, resistance = zones["support"], zones["resistance"]

    reasons: list[str] = []
    if support:
        flipped = " (flipped from a broken resistance zone — break-and-retest)" if support.get("kind") == "swing_high" else ""
        reasons.append(f"Support zone{flipped} at {support['bottom']:,.4g}–{support['top']:,.4g} on {cfg.htf}.")
    else:
        reasons.append(f"No support zone found below price in the last {cfg.zone_lookback_bars} {cfg.htf} bars.")
    if resistance:
        flipped_r = " (flipped from a broken support zone — break-and-retest)" if resistance.get("kind") == "swing_low" else ""
        reasons.append(f"Resistance zone{flipped_r} at {resistance['bottom']:,.4g}–{resistance['top']:,.4g} on {cfg.htf}.")
    else:
        reasons.append(f"No resistance zone found above price in the last {cfg.zone_lookback_bars} {cfg.htf} bars.")

    buffer_support = (support["top"] - support["bottom"]) * cfg.zone_tap_buffer_pct if support else 0
    buffer_resistance = (resistance["top"] - resistance["bottom"]) * cfg.zone_tap_buffer_pct if resistance else 0

    tapping_support = bool(support and support["bottom"] - buffer_support <= price <= support["top"] + buffer_support)
    tapping_resistance = bool(resistance and resistance["bottom"] - buffer_resistance <= price <= resistance["top"] + buffer_resistance)

    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "NO_SETUP"
    conf = 20.0
    entry, stop, target = price, price, price
    zone = None

    if tapping_support:
        direction, zone = "LONG", support
    elif tapping_resistance:
        direction, zone = "SHORT", resistance

    if zone is None:
        take = False
    else:
        phase = PHASE_ZONE_TAPPED
        conf += 20
        reasons.append(f"Price has tapped into the {'support' if direction == 'LONG' else 'resistance'} zone — waiting for a lower-timeframe structure break to confirm, per the strategy's own rule against entering on the tap alone.")

        # Find the tap bar on the LTF to anchor the structure-break search.
        z_top, z_bottom = zone["top"] + (buffer_support if direction == "LONG" else buffer_resistance), zone["bottom"] - (buffer_support if direction == "LONG" else buffer_resistance)
        tap_mask = (ltf["low"] <= z_top) & (ltf["high"] >= z_bottom)
        tap_positions = ltf.index[tap_mask]
        tap_pos = ltf.index.get_loc(tap_positions[0]) if len(tap_positions) else max(0, len(ltf) - cfg.max_setup_age_bars)

        break_idx = _structure_break_after_tap(ltf, direction, tap_pos, cfg.swing_window)
        if break_idx is None:
            verdict = f"WATCH {direction}"
            reasons.append(f"No LTF ({cfg.ltf}) structure break yet — still waiting for the clean break of the most recent {'lower high' if direction == 'LONG' else 'higher low'}.")
        else:
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            conf += 30
            entry = price
            stop = zone["bottom"] - buffer_support if direction == "LONG" else zone["top"] + buffer_resistance
            opposing = resistance if direction == "LONG" else support
            if opposing:
                target = opposing["bottom"] if direction == "LONG" else opposing["top"]
            else:
                risk = abs(entry - stop) or max(price * 0.005, 0.01)
                target = entry + risk * cfg.rr_ratio_fallback if direction == "LONG" else entry - risk * cfg.rr_ratio_fallback
            reasons.append(
                f"LTF ({cfg.ltf}) market structure broke {'above the most recent lower high' if direction == 'LONG' else 'below the most recent higher low'} — entry triggered, stop beyond the zone, target the next structural {'high' if direction == 'LONG' else 'low'}."
            )
        take = phase == PHASE_ENTRY

    conf = max(10.0, min(90.0, conf))
    take = take and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < entry:
        sl_pct = max(0.15, (entry - stop) / entry * 100)
        tp_pct = max(0.2, (target - entry) / entry * 100) if target > entry else sl_pct * cfg.rr_ratio_fallback
    elif direction == "SHORT" and stop > entry:
        sl_pct = max(0.15, (stop - entry) / entry * 100)
        tp_pct = max(0.2, (entry - target) / entry * 100) if target < entry else sl_pct * cfg.rr_ratio_fallback
    else:
        sl_pct = 0.4
        tp_pct = sl_pct * cfg.rr_ratio_fallback

    hold = hold_for_tf(cfg.ltf, "intraday" if cfg.ltf in ("1m", "5m", "15m") else "swing")
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule="Target the next recent structural high/low. Exit if price closes back beyond the zone (setup invalidated).",
        max_hold_exit=f"Time stop per {cfg.ltf} window if neither SL nor TP hits.",
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
        "target_price": round(target, 6),
        "support_zone": [round(support["bottom"], 6), round(support["top"], 6)] if support else None,
        "resistance_zone": [round(resistance["bottom"], 6), round(resistance["top"], 6)] if resistance else None,
        "trendlines": find_trendlines(htf, cfg),
        "chart_data": build_chart_data(htf, cfg),
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: SupportResistanceConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    df_ltf = fetch_data_for_gap_scan(ticker, cfg.ltf, market, groww_token, exchange, limit=cfg.lookback_bars)
    df_ltf = normalize_ohlcv(df_ltf)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        df_ltf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.ltf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )

    df_htf = fetch_data_for_gap_scan(ticker, cfg.htf, market, groww_token, exchange, limit=max(150, cfg.lookback_bars // 4))
    df_htf = normalize_ohlcv(df_htf)
    if df_htf.empty:
        df_htf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.htf, is_crypto=is_crypto, limit=max(150, cfg.lookback_bars // 4), market=market),
        )

    return df_ltf, df_htf


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: SupportResistanceConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SupportResistanceConfig()
    df_ltf, df_htf = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.ltf} data."}
    if df_htf.empty:
        return {"ticker": ticker, "error": f"Insufficient {cfg.htf} data."}

    pipeline = run_sr_pipeline(df_ltf, df_htf, cfg)
    if pipeline.get("error"):
        return {"ticker": ticker, "error": pipeline["error"]}

    live = evaluate_live_signal(pipeline, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "bars_htf": len(pipeline["htf"]),
        "bars_ltf": len(pipeline["ltf"]),
        "last_close": float(pipeline["ltf"]["close"].iloc[-1]),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: SupportResistanceConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    run_bt: bool = False,
) -> dict[str, Any]:
    cfg = cfg or SupportResistanceConfig()
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
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
