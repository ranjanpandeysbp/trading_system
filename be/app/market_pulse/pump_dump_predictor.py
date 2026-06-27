"""
pump_dump_predictor.py
----------------------
Crypto pre-pump / pre-dump signal engine with confluence scoring and trade plans.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import requests

from app.market_pulse.heatmap import fetch_coindcx_ohlcv
from app.market_pulse.indicators import add_atr, add_bollinger_bands, add_ema, add_rsi
from app.market_pulse.price_action import analyze_fibonacci, detect_candlestick_patterns, detect_support_resistance


PRE_PUMP_SIGNALS = [
    ("volume_accumulation", "Volume Accumulation", "Pump signal"),
    ("order_book_imbalance", "Order Book Imbalance", "Pump signal"),
    ("rsi_bullish_divergence", "RSI Bullish Divergence", "Pump signal"),
    ("compression_squeeze", "Compression Squeeze", "Pump signal"),
    ("support_absorption", "Support Absorption", "Pump signal"),
    ("resistance_breakout", "Resistance Breakout", "Pump signal"),
    ("golden_cross", "Golden Cross (EMA)", "Pump signal"),
    ("ema_breakout", "EMA Breakout", "Pump signal"),
    ("bullish_candle", "Bullish Candle Pattern", "Pump signal"),
    ("bb_lower_zone", "Lower Bollinger Band", "Pump signal"),
    ("funding_negative", "Funding Rate Negative", "Pump signal"),
]

def compute_tf_momentum(df: pd.DataFrame, bars: int = 6) -> dict[str, float | None]:
    """Price % change and volume % change over recent bars on the entry timeframe."""
    if df is None or df.empty or len(df) < bars + 2:
        return {"price_chg_pct": None, "vol_chg_pct": None, "price_chg_1bar_pct": None}
    close = df["close"]
    vol = df["volume"]
    p_now = float(close.iloc[-1])
    p_start = float(close.iloc[-1 - bars])
    price_chg = (p_now - p_start) / (p_start + 1e-12) * 100
    p_prev = float(close.iloc[-2])
    price_1bar = (p_now - p_prev) / (p_prev + 1e-12) * 100
    vol_recent = float(vol.iloc[-bars:].mean())
    vol_prior = float(vol.iloc[-2 * bars:-bars].mean()) if len(vol) >= 2 * bars else float(vol.iloc[:-bars].mean())
    vol_chg = (vol_recent / (vol_prior + 1e-12) - 1) * 100
    return {
        "price_chg_pct": round(price_chg, 2),
        "vol_chg_pct": round(vol_chg, 2),
        "price_chg_1bar_pct": round(price_1bar, 2),
    }


def format_active_signal_labels(
    signals: dict[str, dict],
    catalog: list[tuple[str, str, str]],
    *,
    max_items: int = 6,
) -> str:
    """Human-readable list of active signals for scan table."""
    parts: list[str] = []
    for key, title, _tag in catalog:
        data = signals.get(key, {})
        if not data.get("active"):
            continue
        note = (data.get("note") or "").strip()
        if note and len(note) <= 48:
            parts.append(f"{title}: {note}")
        else:
            parts.append(title)
        if len(parts) >= max_items:
            break
    extra = sum(1 for k, v in signals.items() if v.get("active")) - len(parts)
    if extra > 0:
        parts.append(f"+{extra} more")
    return " · ".join(parts) if parts else "No active signals"


PRE_DUMP_SIGNALS = [
    ("volume_distribution", "Volume Distribution", "Dump signal"),
    ("ask_wall_stacking", "Ask Wall Stacking", "Dump signal"),
    ("rsi_bearish_divergence", "RSI Bearish Divergence", "Dump signal"),
    ("liquidity_grab", "Liquidity Grab / Fakeout", "Dump signal"),
    ("resistance_rejection", "Resistance Rejection", "Dump signal"),
    ("support_breakdown", "Support Breakdown", "Dump signal"),
    ("death_cross", "Death Cross (EMA)", "Dump signal"),
    ("ema_breakdown", "EMA Breakdown", "Dump signal"),
    ("bearish_candle", "Bearish Candle Pattern", "Dump signal"),
    ("bb_upper_zone", "Upper Bollinger Band", "Dump signal"),
    ("funding_high_positive", "Funding Rate High Positive", "Dump signal"),
]

MOVE_EXPECTATIONS = {
    "BTC-USDT": {"1m": "0.3% – 1%", "5m": "0.3% – 1%", "15m": "0.5% – 1.5%"},
    "ETH-USDT": {"1m": "0.3% – 1%", "5m": "0.4% – 1.2%", "15m": "0.5% – 2%"},
    "SOL-USDT": {"1m": "0.5% – 1.5%", "5m": "0.5% – 2%", "15m": "1% – 3%"},
    "DEFAULT": {
        "1m": "0.3% – 0.8%", "5m": "0.5% – 2%", "15m": "1% – 5%",
        "30m": "0.8% – 3%", "1h": "1% – 4%", "4h": "2% – 8%",
        "1d": "3% – 15%", "1w": "5% – 25%",
    },
}

CRYPTO_ENTRY_TF_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

ENTRY_MOMENTUM_BARS: dict[str, int] = {
    "1m": 10, "3m": 8, "5m": 6, "10m": 5, "15m": 4, "30m": 4,
    "1h": 3, "4h": 3, "1d": 2, "1w": 2,
}

HOLD_DURATIONS = {
    "1m": "5–20 min scalp · exit if flat after ~15 min",
    "5m": "15–60 min · hold 6–12 candles or until TP2",
    "15m": "1–3 hours · max ~8–12 candles",
    "30m": "2–6 hours",
    "1h": "4–12 hours · review funding every 8h",
    "4h": "6–24 hours · hold 2–4 candles",
    "1d": "2–10 days · swing trade",
    "1w": "1–4 weeks · position trade",
}

HTF_OPTIONS = ["15m", "1h", "4h", "1d", "1w"]

OHLCV_LIMITS: dict[str, int] = {
    "1m": 120, "5m": 120, "15m": 120, "30m": 120, "1h": 120,
    "4h": 150, "1d": 200, "1w": 80,
}

HTF_MOMENTUM_BARS: dict[str, int] = {
    "15m": 4, "30m": 4, "1h": 3, "4h": 3, "1d": 2, "1w": 2,
}

# Points for stacked active rules (main driver of score above ~50)
_SIGNAL_STACK_TABLE = {0: 0, 1: 3, 2: 7, 3: 12, 4: 17, 5: 21, 6: 24, 7: 27, 8: 30}


def signal_stack_points(active_count: int, cap: int = 30) -> int:
    if active_count <= 0:
        return 0
    return min(cap, _SIGNAL_STACK_TABLE.get(active_count, cap))


def htf_alignment_points(direction: str, htf_trend: str) -> tuple[int, str]:
    t = (htf_trend or "neutral").lower()
    aligned = (direction == "long" and t == "up") or (direction == "short" and t == "down")
    if aligned:
        return 15, f"HTF aligned ({htf_trend})"
    if t == "neutral":
        return 7, "HTF neutral — trade smaller size"
    return 2, f"HTF counter-trend ({htf_trend}) — need extra signals"


def order_book_points(direction: str, ob: dict) -> tuple[int, str]:
    ratio = float(ob.get("ratio") or 1.0)
    if direction == "long":
        if ob.get("bid_heavy") or ratio >= 1.4:
            return 12, f"Strong bid book {ratio:.2f}x"
        if ratio >= 1.1:
            return 8, f"Bid lean {ratio:.2f}x"
        if ratio <= 0.9:
            return 0, f"Ask pressure vs long {ratio:.2f}x"
        return 4, f"Balanced book {ratio:.2f}x"
    if ob.get("ask_heavy") or ratio <= 0.72:
        return 12, f"Strong ask book {ratio:.2f}x"
    if ratio <= 0.91:
        return 8, f"Ask lean {ratio:.2f}x"
    if ratio >= 1.1:
        return 0, f"Bid pressure vs short {ratio:.2f}x"
    return 4, f"Balanced book {ratio:.2f}x"


def key_level_points(at_key_level: bool, key_level_note: str) -> tuple[int, str]:
    if at_key_level:
        return 12, key_level_note or "At key S/R / fib"
    if key_level_note:
        return 5, f"Near level — {key_level_note}"
    return 0, "Not at a marked key level"


def trigger_points(trigger: dict) -> tuple[int, str]:
    if trigger.get("closed"):
        return 10, trigger.get("note", "Trigger closed")
    ttype = str(trigger.get("type", ""))
    if ttype not in ("none", ""):
        return 5, "Trigger forming — wait for candle close"
    return 0, trigger.get("note", "No trigger yet")


def _finalize_confluence_score(
    total: int,
    breakdown: list[dict],
    signal_count: int,
    *,
    stack_cap: int = 30,
) -> dict[str, Any]:
    stack = signal_stack_points(signal_count, cap=stack_cap)
    breakdown.append({
        "label": "Active signal stack",
        "max": stack_cap,
        "earned": stack,
        "detail": f"{signal_count} green rule(s) — more signals = higher conviction",
    })
    total = min(100, total + stack)
    verdict = "SKIP"
    if total >= 75 and signal_count >= 3:
        verdict = "STRONG"
    elif total >= 55 and signal_count >= 3:
        verdict = "TRADE"
    elif total >= 38:
        verdict = "WATCH"
    return {
        "total": total,
        "breakdown": breakdown,
        "signal_count": signal_count,
        "verdict": verdict,
        "min_signals_met": signal_count >= 3,
    }


def _api_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if s.startswith("B-"):
        return s if "_USDT" in s else f"B-{s[2:].replace('USDT', '')}_USDT"
    base = s.replace("-USDT", "").replace("USDT", "").replace("-", "").upper()
    return f"B-{base}_USDT"


def _display_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if s.startswith("B-"):
        return s[2:].replace("_", "-")
    return s if "-USDT" in s else f"{s.replace('USDT', '')}-USDT"


def _binance_symbol(symbol: str) -> str:
    base = _display_symbol(symbol).replace("-USDT", "").replace("-", "")
    return f"{base}USDT"


def fetch_ohlcv(symbol: str, timeframe: str, limit: int | None = None) -> pd.DataFrame:
    bar_limit = limit if limit is not None else OHLCV_LIMITS.get(timeframe, 120)
    df = fetch_coindcx_ohlcv(_api_symbol(symbol), timeframe, limit=bar_limit)
    if df is None or df.empty:
        return pd.DataFrame()
    if "time" in df.columns and "date" not in df.columns:
        df = df.copy()
        df["date"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("date", inplace=True)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        if "time" in df.columns:
            df["date"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("date", inplace=True)
    return df.sort_index()


def fetch_funding_rate(symbol: str) -> float | None:
    """Binance futures funding proxy (same underlying as most USDT perps)."""
    try:
        sym = _binance_symbol(symbol)
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": sym},
            timeout=8,
        )
        r.raise_for_status()
        return float(r.json().get("lastFundingRate", 0)) * 100
    except Exception:
        return None


def fetch_order_book_imbalance(symbol: str) -> dict[str, Any]:
    """Bid vs ask notional depth — Binance futures proxy."""
    try:
        sym = _binance_symbol(symbol)
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/depth",
            params={"symbol": sym, "limit": 25},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        bid_notional = sum(float(p) * float(q) for p, q in data.get("bids", []))
        ask_notional = sum(float(p) * float(q) for p, q in data.get("asks", []))
        ratio = bid_notional / (ask_notional + 1e-9)
        return {
            "bid_notional": bid_notional,
            "ask_notional": ask_notional,
            "ratio": ratio,
            "bid_heavy": ratio >= 3.0,
            "ask_heavy": ratio <= (1 / 3.0),
        }
    except Exception:
        return {"bid_notional": 0, "ask_notional": 0, "ratio": 1.0, "bid_heavy": False, "ask_heavy": False}


def _prep_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = add_rsi(out, 14)
    out = add_ema(out, 9)
    out = add_ema(out, 21)
    out = add_ema(out, 50)
    if len(out) >= 205:
        out = add_ema(out, 200)
    out = add_bollinger_bands(out, 20, 2.0)
    out = add_atr(out, 14)
    ema20 = out["close"].ewm(span=20, adjust=False).mean()
    atr = out["atr_14"]
    out["kc_upper"] = ema20 + 1.5 * atr
    out["kc_lower"] = ema20 - 1.5 * atr
    out["bb_upper"] = out["bb_upper_20_2.0"]
    out["bb_lower"] = out["bb_lower_20_2.0"]
    out["bb_middle"] = out["bb_middle_20_2.0"]
    return out


_EMA_CROSS_PAIRS = [(9, 21), (9, 50), (21, 50), (21, 200), (50, 200)]
_EMA_BREAK_PERIODS = [9, 21, 50, 200]
_CANDLE_RELIABILITY = {"VERY HIGH": 4, "HIGH": 3, "MODERATE": 2}


def _ema_cross_events(d: pd.DataFrame, lookback: int = 6) -> tuple[list[str], list[str]]:
    golden: list[str] = []
    death: list[str] = []
    for fast, slow in _EMA_CROSS_PAIRS:
        fc, sc = f"ema_{fast}", f"ema_{slow}"
        if fc not in d.columns or sc not in d.columns:
            continue
        for i in range(-lookback + 1, 0):
            if i - 1 < -len(d):
                continue
            pf, ps = float(d[fc].iloc[i - 1]), float(d[sc].iloc[i - 1])
            cf, cs = float(d[fc].iloc[i]), float(d[sc].iloc[i])
            tag = f"EMA{fast}/EMA{slow}"
            if pf <= ps and cf > cs and tag not in golden:
                golden.append(tag)
            elif pf >= ps and cf < cs and tag not in death:
                death.append(tag)
    return golden, death


def _ema_price_break_events(d: pd.DataFrame, lookback: int = 4) -> tuple[list[int], list[int]]:
    breakout: list[int] = []
    breakdown: list[int] = []
    for period in _EMA_BREAK_PERIODS:
        col = f"ema_{period}"
        if col not in d.columns:
            continue
        for i in range(-lookback + 1, 0):
            if i - 1 < -len(d):
                continue
            prev_c = float(d["close"].iloc[i - 1])
            curr_c = float(d["close"].iloc[i])
            prev_e = float(d[col].iloc[i - 1])
            curr_e = float(d[col].iloc[i])
            if prev_c <= prev_e and curr_c > curr_e and period not in breakout:
                breakout.append(period)
            elif prev_c >= prev_e and curr_c < curr_e and period not in breakdown:
                breakdown.append(period)
    return breakout, breakdown


def _bb_position_info(d: pd.DataFrame) -> dict[str, Any]:
    close = float(d["close"].iloc[-1])
    upper = float(d["bb_upper_20_2.0"].iloc[-1])
    lower = float(d["bb_lower_20_2.0"].iloc[-1])
    middle = float(d["bb_middle_20_2.0"].iloc[-1])
    width = upper - lower
    pct_b = (close - lower) / (width + 1e-9)

    if close > upper:
        zone, note = "above_upper", f"Above upper BB ({close:,.4f} > {upper:,.4f})"
    elif close >= upper * 0.997:
        zone, note = "upper", f"At upper Bollinger Band · %B {pct_b:.0%}"
    elif close < lower:
        zone, note = "below_lower", f"Below lower BB ({close:,.4f} < {lower:,.4f})"
    elif close <= lower * 1.003:
        zone, note = "lower", f"At lower Bollinger Band · %B {pct_b:.0%}"
    elif abs(close - middle) / (middle + 1e-9) < 0.004:
        zone, note = "middle", f"At middle band (20 SMA) · %B {pct_b:.0%}"
    elif close > middle:
        zone, note = "upper_half", f"Upper half of bands · %B {pct_b:.0%} (between mid & upper)"
    else:
        zone, note = "lower_half", f"Lower half of bands · %B {pct_b:.0%} (between lower & mid)"
    return {"zone": zone, "note": note, "pct_b": pct_b, "upper": upper, "middle": middle, "lower": lower}


def _best_recent_candle_pattern(df: pd.DataFrame, bias: str) -> dict | None:
    patterns = detect_candlestick_patterns(df)
    candidates = [
        p for p in patterns
        if p.get("bias") == bias
        and p.get("bars_ago", 99) <= 2
        and _CANDLE_RELIABILITY.get(p.get("reliability", ""), 0) >= _CANDLE_RELIABILITY["HIGH"]
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p: (_CANDLE_RELIABILITY.get(p.get("reliability", ""), 0), -p.get("bars_ago", 99)),
    )


def _ema_stack_summary(d: pd.DataFrame) -> str:
    e9 = float(d["ema_9"].iloc[-1])
    e21 = float(d["ema_21"].iloc[-1])
    e50 = float(d["ema_50"].iloc[-1])
    close = float(d["close"].iloc[-1])
    parts = [f"9={e9:,.2f}", f"21={e21:,.2f}", f"50={e50:,.2f}"]
    if "ema_200" in d.columns:
        e200 = float(d["ema_200"].iloc[-1])
        parts.append(f"200={e200:,.2f}")
    if e9 > e21 > e50 and close > e21:
        return f"Bullish stack (9>21>50) · {' · '.join(parts)}"
    if e9 < e21 < e50 and close < e21:
        return f"Bearish stack (9<21<50) · {' · '.join(parts)}"
    above = [p for p in (9, 21, 50) if close > float(d[f"ema_{p}"].iloc[-1])]
    return f"Mixed alignment · price above EMA {','.join(map(str, above)) or 'none'} · {' · '.join(parts)}"


def detect_technical_structure_signals(df: pd.DataFrame) -> tuple[dict[str, dict], dict[str, dict], dict[str, Any]]:
    """EMA crosses/breaks, key candles, and Bollinger position — shared crypto + India."""
    empty_ctx: dict[str, Any] = {"bb_zone": "n/a", "bb_note": "Insufficient bars", "ema_stack": ""}
    if df is None or df.empty or len(df) < 25:
        inactive = lambda msg: {"active": False, "note": msg}
        pump = {
            "golden_cross": inactive("Need 25+ bars"),
            "ema_breakout": inactive("Need 25+ bars"),
            "bullish_candle": inactive("Need 25+ bars"),
            "bb_lower_zone": inactive("Need 25+ bars"),
        }
        dump = {
            "death_cross": inactive("Need 25+ bars"),
            "ema_breakdown": inactive("Need 25+ bars"),
            "bearish_candle": inactive("Need 25+ bars"),
            "bb_upper_zone": inactive("Need 25+ bars"),
        }
        return pump, dump, empty_ctx

    d = _prep_indicators(df)
    golden, death = _ema_cross_events(d)
    break_up, break_dn = _ema_price_break_events(d)
    bb = _bb_position_info(d)
    bull_pat = _best_recent_candle_pattern(df, "BULLISH")
    bear_pat = _best_recent_candle_pattern(df, "BEARISH")
    stack = _ema_stack_summary(d)

    at_lower = bb["zone"] in ("lower", "below_lower")
    at_upper = bb["zone"] in ("upper", "above_upper")

    pump = {
        "golden_cross": {
            "active": bool(golden),
            "note": "Golden cross: " + " · ".join(golden) if golden else "No golden cross in last 6 bars",
        },
        "ema_breakout": {
            "active": bool(break_up),
            "note": (
                "Price broke above EMA " + ", ".join(str(x) for x in break_up)
                if break_up else "No EMA breakout in last 4 bars"
            ),
        },
        "bullish_candle": {
            "active": bull_pat is not None,
            "note": (
                f"{bull_pat['name']} ({bull_pat['reliability']})"
                + (f" — {bull_pat.get('description', '')[:72]}" if bull_pat else "")
                if bull_pat else "No HIGH-reliability bullish candle on last 2 bars"
            ),
        },
        "bb_lower_zone": {
            "active": at_lower,
            "note": bb["note"] if at_lower else f"BB now: {bb['note']}",
        },
    }
    dump = {
        "death_cross": {
            "active": bool(death),
            "note": "Death cross: " + " · ".join(death) if death else "No death cross in last 6 bars",
        },
        "ema_breakdown": {
            "active": bool(break_dn),
            "note": (
                "Price broke below EMA " + ", ".join(str(x) for x in break_dn)
                if break_dn else "No EMA breakdown in last 4 bars"
            ),
        },
        "bearish_candle": {
            "active": bear_pat is not None,
            "note": (
                f"{bear_pat['name']} ({bear_pat['reliability']})"
                + (f" — {bear_pat.get('description', '')[:72]}" if bear_pat else "")
                if bear_pat else "No HIGH-reliability bearish candle on last 2 bars"
            ),
        },
        "bb_upper_zone": {
            "active": at_upper,
            "note": bb["note"] if at_upper else f"BB now: {bb['note']}",
        },
    }
    context = {
        "bb_zone": bb["zone"],
        "bb_note": bb["note"],
        "bb_pct_b": round(bb["pct_b"] * 100, 1),
        "ema_stack": stack,
        "golden_crosses": golden,
        "death_crosses": death,
        "ema_breakouts": break_up,
        "ema_breakdowns": break_dn,
        "bullish_candle": bull_pat["name"] if bull_pat else "",
        "bearish_candle": bear_pat["name"] if bear_pat else "",
    }
    return pump, dump, context


def _htf_trend(df: pd.DataFrame) -> str:
    if len(df) < 25:
        return "neutral"
    d = _prep_indicators(df)
    e9, e21, e50 = d["ema_9"].iloc[-1], d["ema_21"].iloc[-1], d["ema_50"].iloc[-1]
    close = d["close"].iloc[-1]
    if e9 > e21 > e50 and close > e21:
        return "up"
    if e9 < e21 < e50 and close < e21:
        return "down"
    return "neutral"


def _swing_points(series: pd.Series, window: int = 3) -> tuple[list[int], list[int]]:
    lows, highs = [], []
    for i in range(window, len(series) - window):
        seg = series.iloc[i - window : i + window + 1]
        if series.iloc[i] == seg.min():
            lows.append(i)
        if series.iloc[i] == seg.max():
            highs.append(i)
    return lows, highs


def _rsi_divergence(df: pd.DataFrame, bullish: bool) -> bool:
    if len(df) < 30 or "rsi_14" not in df.columns:
        return False
    price = df["close"]
    rsi = df["rsi_14"]
    if bullish:
        lows, _ = _swing_points(price, 2)
        if len(lows) < 2:
            return False
        i1, i2 = lows[-2], lows[-1]
        return price.iloc[i2] < price.iloc[i1] and rsi.iloc[i2] > rsi.iloc[i1]
    highs, _ = _swing_points(price, 2)
    if len(highs) < 2:
        return False
    i1, i2 = highs[-2], highs[-1]
    return price.iloc[i2] > price.iloc[i1] and rsi.iloc[i2] < rsi.iloc[i1]


def _near_level(price: float, level: float, tol_pct: float = 0.4) -> bool:
    if not level or level <= 0:
        return False
    return abs(price - level) / price * 100 <= tol_pct


def _sr_close_tol(price: float) -> float:
    """Fractional tolerance for S/R close tests (scales with price)."""
    if price >= 50_000:
        return 0.0008
    if price >= 1_000:
        return 0.001
    if price >= 100:
        return 0.0015
    return 0.0025


def _recent_volume_ratio(df: pd.DataFrame) -> float:
    if df is None or df.empty or "volume" not in df.columns:
        return 1.0
    vol_avg = float(df["volume"].iloc[-21:-1].mean()) if len(df) >= 22 else float(df["volume"].iloc[:-1].mean())
    return float(df["volume"].iloc[-1]) / (vol_avg + 1e-9)


def detect_resistance_breakout(df: pd.DataFrame) -> tuple[bool, str]:
    """Pump confirmation: close above tested resistance, volume-backed, not a wick fakeout."""
    if df is None or df.empty or len(df) < 20:
        return False, "Need 20+ bars for S/R breakout"

    price = float(df["close"].iloc[-1])
    prev_c = float(df["close"].iloc[-2])
    bar_h = float(df["high"].iloc[-1])
    bar_o = float(df["open"].iloc[-1])
    tol = _sr_close_tol(price)
    vol_ratio = _recent_volume_ratio(df)

    hist = df.iloc[:-1]
    sr = detect_support_resistance(hist, window=5, num_levels=4)
    levels = [float(x["price"]) for x in sr.get("resistances", []) if x.get("price")]
    swing_high = float(hist["high"].iloc[-30:].max())
    if swing_high < price * 1.015:
        levels.append(swing_high)

    for level in sorted(set(round(l, 8) for l in levels if l > 0)):
        if level >= price * (1 + tol):
            continue
        prior_below = prev_c <= level * (1 + tol)
        closed_above = price > level * (1 + tol)
        fakeout = bar_h > level * (1 + tol) and price <= level
        if not prior_below or not closed_above or fakeout:
            continue
        dist_pct = (price - level) / level * 100
        vol_ok = vol_ratio >= 1.12
        bullish_bar = price >= bar_o
        if dist_pct < 0.06 and not vol_ok:
            continue
        if not bullish_bar and dist_pct < 0.12:
            continue
        note = f"Resistance breakout @ {level:,.4f} (+{dist_pct:.2f}%)"
        if vol_ok:
            note += f" · vol {vol_ratio:.1f}x"
        return True, note

    for level in sorted(set(round(l, 8) for l in levels if l > 0), reverse=True):
        if price <= level * (1 + tol):
            continue
        for off in range(2, min(5, len(df))):
            prior = float(df["close"].iloc[-off])
            after = float(df["close"].iloc[-off + 1])
            if prior <= level * (1 + tol) and after > level * (1 + tol):
                dist_pct = (price - level) / level * 100
                if price > level * (1 - tol) and dist_pct <= 1.2:
                    note = f"Holding above broken resistance @ {level:,.4f} (+{dist_pct:.2f}%)"
                    if vol_ratio >= 1.1:
                        note += f" · vol {vol_ratio:.1f}x"
                    return True, note
                break

    return False, "No resistance breakout — need close above S/R with volume"


def detect_support_breakdown(df: pd.DataFrame) -> tuple[bool, str]:
    """Dump confirmation: close below tested support, volume-backed, not a wick fakeout."""
    if df is None or df.empty or len(df) < 20:
        return False, "Need 20+ bars for S/R breakdown"

    price = float(df["close"].iloc[-1])
    prev_c = float(df["close"].iloc[-2])
    bar_l = float(df["low"].iloc[-1])
    bar_o = float(df["open"].iloc[-1])
    tol = _sr_close_tol(price)
    vol_ratio = _recent_volume_ratio(df)

    hist = df.iloc[:-1]
    sr = detect_support_resistance(hist, window=5, num_levels=4)
    levels = [float(x["price"]) for x in sr.get("supports", []) if x.get("price")]
    swing_low = float(hist["low"].iloc[-30:].min())
    if swing_low > price * 0.985:
        levels.append(swing_low)

    for level in sorted(set(round(l, 8) for l in levels if l > 0), reverse=True):
        if level <= price * (1 - tol):
            continue
        prior_above = prev_c >= level * (1 - tol)
        closed_below = price < level * (1 - tol)
        fakeout = bar_l < level * (1 - tol) and price >= level
        if not prior_above or not closed_below or fakeout:
            continue
        dist_pct = (level - price) / level * 100
        vol_ok = vol_ratio >= 1.12
        bearish_bar = price <= bar_o
        if dist_pct < 0.06 and not vol_ok:
            continue
        if not bearish_bar and dist_pct < 0.12:
            continue
        note = f"Support breakdown @ {level:,.4f} (-{dist_pct:.2f}%)"
        if vol_ok:
            note += f" · vol {vol_ratio:.1f}x"
        return True, note

    for level in sorted(set(round(l, 8) for l in levels if l > 0)):
        if price >= level * (1 - tol):
            continue
        for off in range(2, min(5, len(df))):
            prior = float(df["close"].iloc[-off])
            after = float(df["close"].iloc[-off + 1])
            if prior >= level * (1 - tol) and after < level * (1 - tol):
                dist_pct = (level - price) / level * 100
                if price < level * (1 + tol) and dist_pct <= 1.2:
                    note = f"Holding below broken support @ {level:,.4f} (-{dist_pct:.2f}%)"
                    if vol_ratio >= 1.1:
                        note += f" · vol {vol_ratio:.1f}x"
                    return True, note
                break

    return False, "No support breakdown — need close below S/R with volume"


def _round_number_levels(price: float) -> list[float]:
    if price >= 1000:
        step = 1000 if price < 50000 else 5000
        base = round(price / step) * step
        return [base - step, base, base + step]
    if price >= 100:
        step = 10
        base = round(price / step) * step
        return [base - step, base, base + step]
    step = 1 if price >= 10 else 0.1
    base = round(price / step) * step
    return [base - step, base, base + step]


def _key_level_hit(df: pd.DataFrame, price: float) -> tuple[bool, str]:
    sr = detect_support_resistance(df, window=5, num_levels=3)
    supports = [x["price"] for x in sr.get("supports", []) if x.get("price")]
    resistances = [x["price"] for x in sr.get("resistances", []) if x.get("price")]
    fib = analyze_fibonacci(df, lookback=min(80, len(df) - 1))
    fib_levels = [v for k, v in (fib.get("levels") or {}).items() if "50" in k or "61.8" in k or "38.2" in k]

    h24, l24 = df["high"].iloc[-24:].max(), df["low"].iloc[-24:].min()
    candidates: list[tuple[str, float]] = []
    for s in supports:
        candidates.append(("support", s))
    for r in resistances:
        candidates.append(("resistance", r))
    for f in fib_levels:
        candidates.append(("fib", f))
    candidates.append(("session_high", h24))
    candidates.append(("session_low", l24))
    for rn in _round_number_levels(price):
        candidates.append(("round", rn))

    for kind, lvl in candidates:
        if _near_level(price, lvl):
            return True, f"{kind} @ {lvl:,.4f}"
    return False, ""


def _trigger_candle(df: pd.DataFrame, direction: str) -> dict[str, Any]:
    if len(df) < 3:
        return {"closed": False, "type": "none", "note": "Insufficient bars"}
    o, h, l, c = df.iloc[-2][["open", "high", "low", "close"]]
    body = abs(c - o)
    rng = h - l + 1e-9
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if direction == "long":
        bullish_engulf = c > o and df.iloc[-3]["close"] < df.iloc[-3]["open"] and c >= df.iloc[-3]["open"] and o <= df.iloc[-3]["close"]
        pin = lower_wick / rng > 0.55 and body / rng < 0.35 and c > o
        squeeze_break = c > df["bb_upper_20_2.0"].iloc[-2] if "bb_upper_20_2.0" in df.columns else False
        ok = bullish_engulf or pin or squeeze_break
        kind = "bullish engulfing" if bullish_engulf else "pin bar" if pin else "squeeze breakout" if squeeze_break else "none"
    else:
        bearish_engulf = c < o and df.iloc[-3]["close"] > df.iloc[-3]["open"] and c <= df.iloc[-3]["open"] and o >= df.iloc[-3]["close"]
        pin = upper_wick / rng > 0.55 and body / rng < 0.35 and c < o
        breakdown = c < df["bb_lower_20_2.0"].iloc[-2] if "bb_lower_20_2.0" in df.columns else False
        ok = bearish_engulf or pin or breakdown
        kind = "bearish engulfing" if bearish_engulf else "pin bar" if pin else "breakdown" if breakdown else "none"

    return {
        "closed": ok,
        "type": kind,
        "note": f"Prior bar: {kind} — enter on next candle open" if ok else "Wait for trigger candle to close",
        "stop_ref": float(l if direction == "long" else h),
    }


def _volume_accumulation(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < 25:
        return False, "Need more history"
    vol5 = df["volume"].iloc[-5:].mean()
    vol_prev = df["volume"].iloc[-15:-5].mean()
    price_chg = abs(df["close"].iloc[-5] - df["close"].iloc[-1]) / df["close"].iloc[-1] * 100
    vol_rising = vol5 > vol_prev * 1.15
    flat = price_chg < 1.2
    if vol_rising and flat:
        return True, f"Volume +{(vol5 / (vol_prev + 1e-9) - 1) * 100:.0f}% while price flat ({price_chg:.2f}%)"
    return False, f"Vol trend {vol5 / (vol_prev + 1e-9):.2f}x · price move {price_chg:.2f}%"


def _volume_distribution(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < 10:
        return False, "Need more history"
    recent = df.iloc[-5:]
    up_vol = recent.loc[recent["close"] >= recent["open"], "volume"].sum()
    adv = (recent["close"] - recent["open"]).clip(lower=0).sum()
    price_adv = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[0] * 100
    vol_surge = recent["volume"].mean() / (df["volume"].iloc[-20:-5].mean() + 1e-9)
    if vol_surge >= 1.5 and up_vol > 0 and price_adv < 0.8:
        return True, f"High volume ({vol_surge:.1f}x) but price only +{price_adv:.2f}%"
    return False, f"Vol {vol_surge:.1f}x · price +{price_adv:.2f}%"


def _compression_squeeze(df: pd.DataFrame, htf_trend: str) -> tuple[bool, str]:
    if len(df) < 25:
        return False, "Need more history"
    d = _prep_indicators(df)
    row = d.iloc[-1]
    inside = row["bb_upper"] < row["kc_upper"] and row["bb_lower"] > row["kc_lower"]
    if inside:
        bias = "bullish" if htf_trend == "up" else "bearish" if htf_trend == "down" else "neutral"
        return True, f"BB inside Keltner — squeeze active (HTF bias: {bias})"
    return False, "No squeeze — bands outside Keltner"


def _support_absorption(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < 15:
        return False, "Need more history"
    lows = df["low"].iloc[-12:]
    level = lows.min()
    touches = sum(1 for x in lows if abs(x - level) / level < 0.004)
    bounces = sum(
        1 for i in range(-6, 0)
        if df["low"].iloc[i] <= level * 1.003 and df["close"].iloc[i] > df["open"].iloc[i]
    )
    if touches >= 2 and bounces >= 2:
        return True, f"Floor {level:,.4f} tested {touches}x with {bounces} absorption candles"
    return False, f"Touches {touches} · bounces {bounces}"


def _resistance_rejection(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < 15:
        return False, "Need more history"
    highs = df["high"].iloc[-12:]
    level = highs.max()
    touches = sum(1 for x in highs if abs(x - level) / level < 0.004)
    vols = df["volume"].iloc[-12:]
    rejections = [
        i for i in range(-6, 0)
        if df["high"].iloc[i] >= level * 0.997 and df["close"].iloc[i] < df["high"].iloc[i] * 0.998
    ]
    vol_fading = len(rejections) >= 2 and vols.iloc[rejections[-1]] < vols.iloc[rejections[0]]
    if touches >= 2 and len(rejections) >= 2:
        note = f"Resistance {level:,.4f} rejected {len(rejections)}x"
        if vol_fading:
            note += " · volume fading"
        return True, note
    return False, f"Touches {touches} · rejections {len(rejections)}"


def _liquidity_grab(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < 10:
        return False, "Need more history"
    recent_high = df["high"].iloc[-10:-1].max()
    last = df.iloc[-1]
    wick_up = last["high"] > recent_high * 1.001
    closed_below = last["close"] < recent_high
    long_wick = (last["high"] - max(last["open"], last["close"])) / (last["high"] - last["low"] + 1e-9) > 0.45
    if wick_up and closed_below and long_wick:
        return True, f"Stop-hunt above {recent_high:,.4f} then closed back below"
    return False, "No fakeout pattern on latest bar"


def detect_pre_pump_signals(
    df_entry: pd.DataFrame,
    htf_trend: str,
    ob: dict,
    funding: float | None,
) -> dict[str, dict]:
    d = _prep_indicators(df_entry)
    out: dict[str, dict] = {}

    ok, note = _volume_accumulation(d)
    out["volume_accumulation"] = {"active": ok, "note": note}

    bid_ok = ob.get("bid_heavy", False)
    out["order_book_imbalance"] = {
        "active": bid_ok,
        "note": f"Bid/ask ratio {ob.get('ratio', 1):.2f}x" + (" — bid wall" if bid_ok else ""),
    }

    div = _rsi_divergence(d, bullish=True)
    out["rsi_bullish_divergence"] = {
        "active": div,
        "note": "Price lower low, RSI higher low" if div else "No bullish divergence",
    }

    ok, note = _compression_squeeze(d, htf_trend)
    out["compression_squeeze"] = {"active": ok, "note": note}

    ok, note = _support_absorption(d)
    out["support_absorption"] = {"active": ok, "note": note}

    ok, note = detect_resistance_breakout(d)
    out["resistance_breakout"] = {"active": ok, "note": note}

    fund_ok = funding is not None and funding < -0.01
    out["funding_negative"] = {
        "active": fund_ok,
        "note": f"Funding {funding:+.4f}%" if funding is not None else "Funding data unavailable",
    }
    return out


def detect_pre_dump_signals(
    df_entry: pd.DataFrame,
    ob: dict,
    funding: float | None,
) -> dict[str, dict]:
    d = _prep_indicators(df_entry)

    ok, note = _volume_distribution(d)
    out: dict[str, dict] = {"volume_distribution": {"active": ok, "note": note}}

    ask_ok = ob.get("ask_heavy", False)
    out["ask_wall_stacking"] = {
        "active": ask_ok,
        "note": f"Bid/ask ratio {ob.get('ratio', 1):.2f}x" + (" — ask wall" if ask_ok else ""),
    }

    div = _rsi_divergence(d, bullish=False)
    out["rsi_bearish_divergence"] = {
        "active": div,
        "note": "Price higher high, RSI lower high" if div else "No bearish divergence",
    }

    ok, note = _liquidity_grab(d)
    out["liquidity_grab"] = {"active": ok, "note": note}

    ok, note = _resistance_rejection(d)
    out["resistance_rejection"] = {"active": ok, "note": note}

    ok, note = detect_support_breakdown(d)
    out["support_breakdown"] = {"active": ok, "note": note}

    fund_ok = funding is not None and funding > 0.03
    out["funding_high_positive"] = {
        "active": fund_ok,
        "note": f"Funding {funding:+.4f}%" if funding is not None else "Funding data unavailable",
    }
    return out


def score_confluence(
    *,
    direction: str,
    htf_trend: str,
    at_key_level: bool,
    key_level_note: str,
    pump_signals: dict[str, dict],
    dump_signals: dict[str, dict],
    volume_confirms: bool,
    ob: dict,
    rsi_aligns: bool,
    funding: float | None,
    trigger: dict,
    rr_ok: bool,
) -> dict[str, Any]:
    """Live trade scorer — max 100 pts."""
    breakdown: list[dict] = []
    total = 0

    def add(label: str, pts: int, earned: int, detail: str = ""):
        nonlocal total
        total += earned
        breakdown.append({"label": label, "max": pts, "earned": earned, "detail": detail})

    htf_pts, htf_note = htf_alignment_points(direction, htf_trend)
    add("Higher TF trend", 15, htf_pts, htf_note)
    kl_pts, kl_note = key_level_points(at_key_level, key_level_note)
    sr_confirm = (
        pump_signals.get("resistance_breakout", {}).get("active")
        if direction == "long"
        else dump_signals.get("support_breakdown", {}).get("active")
    )
    if sr_confirm and kl_pts < 12:
        kl_pts = min(12, kl_pts + 6)
        kl_note = (kl_note + " · S/R break confirmed") if kl_note else "S/R breakout/breakdown confirmed"
    add("Key S/R / Fib level", 12, kl_pts, kl_note)
    vol_pts = 10 if volume_confirms else (6 if sr_confirm else 0)
    vol_detail = "Volume + S/R break" if volume_confirms and sr_confirm else (
        "S/R breakout/breakdown volume" if sr_confirm else ""
    )
    add("Volume confirms the move", 10, vol_pts, vol_detail)
    ob_pts, ob_note = order_book_points(direction, ob)
    add("Order book bias", 12, ob_pts, ob_note)
    add("RSI / EMA / candle momentum", 8, 8 if rsi_aligns else 0, "")
    fund_ok = (
        (direction == "long" and funding is not None and funding < 0)
        or (direction == "short" and funding is not None and funding > 0.02)
    )
    fund_pts = 8 if fund_ok else (4 if funding is not None and abs(funding or 0) < 0.01 else 0)
    add(
        "Funding rate",
        8,
        fund_pts,
        f"{funding:+.4f}%" if funding is not None else "n/a",
    )
    trig_pts, trig_note = trigger_points(trigger)
    add("Trigger candle", 10, trig_pts, trig_note)
    add("RR ratio ≥ 1:2", 5, 5 if rr_ok else 0, "")

    active_pump = sum(1 for v in pump_signals.values() if v.get("active"))
    active_dump = sum(1 for v in dump_signals.values() if v.get("active"))
    signal_count = active_pump if direction == "long" else active_dump

    return _finalize_confluence_score(total, breakdown, signal_count)


def build_trade_plan(
    direction: str,
    entry_tf: str,
    price: float,
    stop_ref: float,
    symbol: str = "",
    account_risk_pct: float = 1.0,
) -> dict[str, Any]:
    if direction == "long":
        risk = max(price - stop_ref, price * 0.002)
        sl = price - risk
        tp1 = price + risk * 1.5
        tp2 = price + risk * 2.5
        tp3 = price + risk * 3.5
    else:
        risk = max(stop_ref - price, price * 0.002)
        sl = price + risk
        tp1 = price - risk * 1.5
        tp2 = price - risk * 2.5
        tp3 = price - risk * 3.5

    rr = 2.5
    disp = _display_symbol(symbol) if symbol else "DEFAULT"
    move = MOVE_EXPECTATIONS.get(disp, MOVE_EXPECTATIONS["DEFAULT"])
    return {
        "direction": "LONG" if direction == "long" else "SHORT",
        "entry": price,
        "stop_loss": sl,
        "risk_pct": account_risk_pct,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp1_action": "Close 40% at 1:1.5 RR",
        "tp2_action": "Close 40% at 1:2.5 RR",
        "tp3_action": "Trail remaining 20%",
        "breakeven_rule": "Move stop to entry after TP1",
        "rr_ratio": rr,
        "rr_ok": rr >= 2.0,
        "expected_move": move.get(entry_tf, move.get("5m", "0.5% – 2%")),
        "hold_duration": HOLD_DURATIONS.get(entry_tf, HOLD_DURATIONS["5m"]),
        "entry_rule": "Enter on OPEN of next candle after trigger closes",
        "actionable": False,
    }


@dataclass
class PumpDumpAnalysis:
    symbol: str
    entry_tf: str
    htf: str
    price: float
    htf_trend: str
    bias: str
    pump_signals: dict = field(default_factory=dict)
    dump_signals: dict = field(default_factory=dict)
    confluence_long: dict = field(default_factory=dict)
    confluence_short: dict = field(default_factory=dict)
    trade_plan_long: dict | None = None
    trade_plan_short: dict | None = None
    funding: float | None = None
    order_book: dict = field(default_factory=dict)
    key_level: str = ""
    price_chg_pct: float | None = None
    vol_chg_pct: float | None = None
    price_chg_1bar_pct: float | None = None
    htf_price_chg_pct: float | None = None
    momentum_bars: int = 6
    technical_context: dict = field(default_factory=dict)
    error: str = ""


def analyze_crypto_pair(
    symbol: str,
    entry_tf: str = "5m",
    htf: str = "15m",
) -> PumpDumpAnalysis:
    disp = _display_symbol(symbol)
    result = PumpDumpAnalysis(symbol=disp, entry_tf=entry_tf, htf=htf, price=0, htf_trend="neutral", bias="neutral")

    df_entry = fetch_ohlcv(symbol, entry_tf)
    df_htf = fetch_ohlcv(symbol, htf)
    if df_entry.empty or len(df_entry) < 15:
        result.error = "Insufficient OHLCV data — check symbol or try 5m/15m"
        return result

    result.price = float(df_entry["close"].iloc[-1])
    mom_bars = ENTRY_MOMENTUM_BARS.get(entry_tf, 6)
    result.momentum_bars = mom_bars
    mom = compute_tf_momentum(df_entry, mom_bars)
    result.price_chg_pct = mom["price_chg_pct"]
    result.vol_chg_pct = mom["vol_chg_pct"]
    result.price_chg_1bar_pct = mom["price_chg_1bar_pct"]
    htf_mom_bars = HTF_MOMENTUM_BARS.get(htf, mom_bars)
    if not df_htf.empty and len(df_htf) >= htf_mom_bars + 2:
        htf_mom = compute_tf_momentum(df_htf, htf_mom_bars)
        result.htf_price_chg_pct = htf_mom["price_chg_pct"]
    result.htf_trend = _htf_trend(df_htf if not df_htf.empty else df_entry)
    result.funding = fetch_funding_rate(symbol)
    result.order_book = fetch_order_book_imbalance(symbol)

    at_level, level_note = _key_level_hit(df_entry, result.price)
    result.key_level = level_note

    result.pump_signals = detect_pre_pump_signals(df_entry, result.htf_trend, result.order_book, result.funding)
    result.dump_signals = detect_pre_dump_signals(df_entry, result.order_book, result.funding)
    tech_pump, tech_dump, result.technical_context = detect_technical_structure_signals(df_entry)
    result.pump_signals.update(tech_pump)
    result.dump_signals.update(tech_dump)

    active_pump = sum(1 for v in result.pump_signals.values() if v.get("active"))
    active_dump = sum(1 for v in result.dump_signals.values() if v.get("active"))
    if active_pump > active_dump:
        result.bias = "pump"
    elif active_dump > active_pump:
        result.bias = "dump"
    else:
        result.bias = "neutral"

    vol_confirms_pump = (
        result.pump_signals.get("volume_accumulation", {}).get("active", False)
        or result.pump_signals.get("resistance_breakout", {}).get("active", False)
    )
    vol_confirms_dump = (
        result.dump_signals.get("volume_distribution", {}).get("active", False)
        or result.dump_signals.get("support_breakdown", {}).get("active", False)
    )

    trig_long = _trigger_candle(_prep_indicators(df_entry), "long")
    trig_short = _trigger_candle(_prep_indicators(df_entry), "short")
    plan_l = build_trade_plan("long", entry_tf, result.price, trig_long["stop_ref"], symbol=disp)
    plan_s = build_trade_plan("short", entry_tf, result.price, trig_short["stop_ref"], symbol=disp)

    result.confluence_long = score_confluence(
        direction="long",
        htf_trend=result.htf_trend,
        at_key_level=at_level,
        key_level_note=level_note,
        pump_signals=result.pump_signals,
        dump_signals=result.dump_signals,
        volume_confirms=vol_confirms_pump,
        ob=result.order_book,
        rsi_aligns=(
            result.pump_signals.get("rsi_bullish_divergence", {}).get("active", False)
            or result.pump_signals.get("bullish_candle", {}).get("active", False)
            or result.pump_signals.get("golden_cross", {}).get("active", False)
            or result.pump_signals.get("ema_breakout", {}).get("active", False)
        ),
        funding=result.funding,
        trigger=trig_long,
        rr_ok=plan_l["rr_ok"],
    )
    result.confluence_short = score_confluence(
        direction="short",
        htf_trend=result.htf_trend,
        at_key_level=at_level,
        key_level_note=level_note,
        pump_signals=result.pump_signals,
        dump_signals=result.dump_signals,
        volume_confirms=vol_confirms_dump,
        ob=result.order_book,
        rsi_aligns=(
            result.dump_signals.get("rsi_bearish_divergence", {}).get("active", False)
            or result.dump_signals.get("bearish_candle", {}).get("active", False)
            or result.dump_signals.get("death_cross", {}).get("active", False)
            or result.dump_signals.get("ema_breakdown", {}).get("active", False)
        ),
        funding=result.funding,
        trigger=trig_short,
        rr_ok=plan_s["rr_ok"],
    )
    plan_l["actionable"] = result.confluence_long["verdict"] in ("TRADE", "STRONG")
    plan_s["actionable"] = result.confluence_short["verdict"] in ("TRADE", "STRONG")
    result.trade_plan_long = plan_l
    result.trade_plan_short = plan_s
    return result


def scan_crypto_universe(
    symbols: list[str],
    entry_tf: str = "5m",
    htf: str = "15m",
    mode: str = "BOTH",
    min_signals: int = 0,
) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    meta: dict = {"scanned": 0, "errors": [], "with_data": 0}
    for sym in symbols:
        meta["scanned"] += 1
        try:
            a = analyze_crypto_pair(sym, entry_tf, htf)
            if a.error:
                meta["errors"].append(f"{sym}: {a.error}")
                continue
            meta["with_data"] += 1
            if mode in ("PUMP", "BOTH"):
                cl = a.confluence_long
                if cl["signal_count"] >= min_signals:
                    rows.append(_row_from_analysis(a, "LONG", cl))
            if mode in ("DUMP", "BOTH"):
                cs = a.confluence_short
                if cs["signal_count"] >= min_signals:
                    rows.append(_row_from_analysis(a, "SHORT", cs))
        except Exception as exc:
            meta["errors"].append(f"{sym}: {exc}")
        time.sleep(0.05)
    return sorted(rows, key=lambda x: x.get("score", 0), reverse=True), meta


def _row_from_analysis(a: PumpDumpAnalysis, side: str, conf: dict) -> dict:
    signals = a.pump_signals if side == "LONG" else a.dump_signals
    catalog = PRE_PUMP_SIGNALS if side == "LONG" else PRE_DUMP_SIGNALS
    active = [k for k, v in signals.items() if v.get("active")]
    return {
        "symbol": a.symbol,
        "side": side,
        "price": a.price,
        "entry_tf": a.entry_tf,
        "htf": a.htf,
        "htf_trend": a.htf_trend,
        "score": conf["total"],
        "verdict": conf["verdict"],
        "signals": len(active),
        "signal_detail": format_active_signal_labels(signals, catalog),
        "signal_names": active,
        "price_chg_pct": a.price_chg_pct,
        "vol_chg_pct": a.vol_chg_pct,
        "price_chg_1bar_pct": a.price_chg_1bar_pct,
        "htf_price_chg_pct": a.htf_price_chg_pct,
        "momentum_bars": a.momentum_bars,
        "funding": a.funding,
        "ob_ratio": a.order_book.get("ratio"),
        "key_level": a.key_level,
        "bb_zone": (a.technical_context or {}).get("bb_zone", ""),
        "bb_note": (a.technical_context or {}).get("bb_note", ""),
        "analysis": a,
    }
