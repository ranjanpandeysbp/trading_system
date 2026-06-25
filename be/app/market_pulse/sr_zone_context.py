"""
sr_zone_context.py
------------------
Consolidation near S/R and historical supply/demand zones — shared by Find S/R and Weak Strong S-R.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.market_pulse.pa_sr_helpers import _calc_atr
from app.market_pulse.sr_breakout import _find_swing_points


def _cluster_swing_prices(
    swings: list[tuple[Any, float]],
    price: float,
    *,
    tol_pct: float = 0.9,
) -> list[dict[str, Any]]:
    if not swings:
        return []
    tol = max(price * tol_pct / 100, price * 0.002)
    clusters: list[dict[str, Any]] = []
    for _idx, lv in sorted(swings, key=lambda x: x[1]):
        placed = False
        for c in clusters:
            if abs(lv - c["mid"]) <= tol:
                c["prices"].append(lv)
                c["mid"] = float(sum(c["prices"]) / len(c["prices"]))
                c["top"] = max(c["top"], lv)
                c["bottom"] = min(c["bottom"], lv)
                placed = True
                break
        if not placed:
            clusters.append({
                "prices": [lv],
                "mid": lv,
                "top": lv,
                "bottom": lv,
                "touches": 0,
            })
    return clusters


def _count_zone_touches(
    df: pd.DataFrame,
    zone: dict[str, Any],
    *,
    zone_type: str,
    tol_pct: float = 0.9,
) -> int:
    if df is None or df.empty:
        return 0
    price = float(df["close"].iloc[-1])
    tol = max(price * tol_pct / 100, price * 0.002)
    mid = zone["mid"]
    touches = 0
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    for i in range(max(0, len(df) - 80), len(df)):
        if zone_type == "supply":
            if h.iloc[i] >= mid - tol and h.iloc[i] <= mid + tol * 2 and c.iloc[i] < h.iloc[i] * 0.998:
                touches += 1
        else:
            if l.iloc[i] <= mid + tol and l.iloc[i] >= mid - tol * 2 and c.iloc[i] > l.iloc[i] * 1.002:
                touches += 1
    zone["touches"] = max(zone.get("touches", 0), touches)
    return zone["touches"]


def _zone_strength(touches: int) -> str:
    if touches >= 3:
        return "strong"
    if touches >= 2:
        return "moderate"
    return "weak"


def analyze_consolidation_near_sr(
    df: pd.DataFrame,
    levels: dict[str, Any],
    *,
    lookback: int = 12,
    near_pct: float = 2.5,
) -> dict[str, Any]:
    """
    Consolidation under resistance → bullish (breakout base).
    Consolidation above support → bearish (breakdown flag).
    """
    out: dict[str, Any] = {
        "is_consolidating": False,
        "near_level": None,
        "near_zone": None,
        "bias": "NEUTRAL",
        "range_pct": None,
        "bars": lookback,
        "label": "No tight consolidation at immediate S/R.",
        "score": 0.0,
    }
    if df is None or df.empty or len(df) < lookback + 5:
        return out

    price = float(levels.get("price") or df["close"].iloc[-1])
    tail = df.iloc[-lookback:]
    hi = float(tail["high"].max())
    lo = float(tail["low"].min())
    range_pct = (hi - lo) / price * 100 if price > 0 else 0.0
    atr = _calc_atr(df, 14)
    atr_pct = (atr / price * 100) if price > 0 else 1.0
    is_tight = range_pct < max(1.25, atr_pct * 2.4)

    out["range_pct"] = round(range_pct, 2)
    if not is_tight:
        return out

    candidates: list[tuple[float, str, str, float]] = []
    for tag, key, zone in (
        ("R1", "r1", "resistance"),
        ("R2", "r2", "resistance"),
        ("S1", "s1", "support"),
        ("S2", "s2", "support"),
    ):
        lv = levels.get(key)
        if lv is not None:
            dist_pct = abs(price - float(lv)) / price * 100
            candidates.append((dist_pct, tag, zone, float(lv)))

    if not candidates:
        return out

    dist_pct, tag, zone, lv = min(candidates, key=lambda x: x[0])
    if dist_pct > near_pct:
        out["label"] = (
            f"Tight {range_pct:.1f}% range over last {lookback} bars — "
            "not directly adjacent to S1/S2/R1/R2."
        )
        return out

    out["is_consolidating"] = True
    out["near_level"] = tag
    out["near_zone"] = zone

    if zone == "resistance":
        out["bias"] = "BULLISH"
        out["score"] = 1.85
        out["label"] = (
            f"**Bullish consolidation** — price coiling in a {range_pct:.1f}% range "
            f"under **{tag}** ({lv:.4g}, {dist_pct:.1f}% away). "
            "Bases under resistance often resolve with an upside break."
        )
    else:
        out["bias"] = "BEARISH"
        out["score"] = -1.85
        out["label"] = (
            f"**Bearish consolidation** — price coiling in a {range_pct:.1f}% range "
            f"above **{tag}** ({lv:.4g}, {dist_pct:.1f}% away). "
            "Flags on support often resolve with a downside break."
        )
    return out


def analyze_supply_demand_zones(
    df: pd.DataFrame,
    *,
    sr_window: int = 5,
    lookback: int = 80,
) -> dict[str, Any]:
    """Historical supply (rejection) and demand (bounce) zones from swing history."""
    out: dict[str, Any] = {
        "active_zone": "none",
        "bias": "NEUTRAL",
        "score": 0.0,
        "confidence_boost": 0,
        "label": "No clear supply/demand zone from recent history.",
        "demand_zones": [],
        "supply_zones": [],
        "nearest_demand": None,
        "nearest_supply": None,
    }
    if df is None or df.empty or len(df) < sr_window * 4 + 10:
        return out

    price = float(df["close"].iloc[-1])
    hist = df.iloc[-lookback:]
    swing_highs, swing_lows = _find_swing_points(hist, window=sr_window)

    supply_clusters = _cluster_swing_prices(swing_highs, price)
    demand_clusters = _cluster_swing_prices(swing_lows, price)

    supply_zones: list[dict[str, Any]] = []
    for cl in supply_clusters:
        touches = _count_zone_touches(hist, cl, zone_type="supply")
        strength = _zone_strength(touches)
        supply_zones.append({
            "type": "supply",
            "top": round(cl["top"], 4),
            "bottom": round(cl["bottom"], 4),
            "mid": round(cl["mid"], 4),
            "touches": touches,
            "strength": strength,
            "dist_pct": round((cl["mid"] - price) / price * 100, 2),
        })

    demand_zones: list[dict[str, Any]] = []
    for cl in demand_clusters:
        touches = _count_zone_touches(hist, cl, zone_type="demand")
        strength = _zone_strength(touches)
        demand_zones.append({
            "type": "demand",
            "top": round(cl["top"], 4),
            "bottom": round(cl["bottom"], 4),
            "mid": round(cl["mid"], 4),
            "touches": touches,
            "strength": strength,
            "dist_pct": round((price - cl["mid"]) / price * 100, 2),
        })

    supply_zones.sort(key=lambda z: abs(z["mid"] - price))
    demand_zones.sort(key=lambda z: abs(z["mid"] - price))
    out["supply_zones"] = supply_zones[:4]
    out["demand_zones"] = demand_zones[:4]

    tol_pct = 1.2
    in_supply = [
        z for z in supply_zones
        if price >= z["bottom"] * (1 - tol_pct / 100) and price <= z["top"] * (1 + tol_pct / 100)
    ]
    in_demand = [
        z for z in demand_zones
        if price >= z["bottom"] * (1 - tol_pct / 100) and price <= z["top"] * (1 + tol_pct / 100)
    ]

    above_supply = [z for z in supply_zones if z["mid"] > price * 1.001]
    below_demand = [z for z in demand_zones if z["mid"] < price * 0.999]
    if above_supply:
        out["nearest_supply"] = min(above_supply, key=lambda z: z["mid"] - price)
    if below_demand:
        out["nearest_demand"] = max(below_demand, key=lambda z: z["mid"])

    if in_demand:
        z = max(in_demand, key=lambda x: x["touches"])
        out["active_zone"] = "demand"
        out["bias"] = "BULLISH"
        out["score"] = 1.4 if z["strength"] == "weak" else (1.8 if z["strength"] == "moderate" else 2.2)
        out["confidence_boost"] = 8
        out["label"] = (
            f"Price inside **demand zone** ({z['bottom']:.4g}–{z['top']:.4g}) — "
            f"{z['strength']} ({z['touches']} historical bounces). Institutional buy-side memory."
        )
    elif in_supply:
        z = max(in_supply, key=lambda x: x["touches"])
        out["active_zone"] = "supply"
        out["bias"] = "BEARISH"
        out["score"] = -1.4 if z["strength"] == "weak" else (-1.8 if z["strength"] == "moderate" else -2.2)
        out["confidence_boost"] = 8
        out["label"] = (
            f"Price inside **supply zone** ({z['bottom']:.4g}–{z['top']:.4g}) — "
            f"{z['strength']} ({z['touches']} historical rejections). Overhead sell-side memory."
        )
    elif out["nearest_demand"] and out["nearest_supply"]:
        d, s = out["nearest_demand"], out["nearest_supply"]
        out["active_zone"] = "between"
        out["label"] = (
            f"Between **demand** ({d['mid']:.4g}, {d['strength']}) below and "
            f"**supply** ({s['mid']:.4g}, {s['strength']}) above."
        )
    elif out["nearest_demand"]:
        d = out["nearest_demand"]
        out["label"] = f"Nearest **demand** at {d['mid']:.4g} ({d['dist_pct']:.1f}% below, {d['strength']})."
        out["score"] = 0.6
    elif out["nearest_supply"]:
        s = out["nearest_supply"]
        out["label"] = f"Nearest **supply** at {s['mid']:.4g} ({s['dist_pct']:.1f}% above, {s['strength']})."
        out["score"] = -0.6

    return out


def zone_context_points(consolidation: dict, supply_demand: dict) -> tuple[int, int, list[str]]:
    """Return (bull_pts, bear_pts, signal_lines) from consolidation + supply/demand."""
    bull_pts = 0
    bear_pts = 0
    signals: list[str] = []

    cons = consolidation or {}
    if cons.get("is_consolidating"):
        label = (cons.get("label") or "").replace("**", "")
        if cons.get("bias") == "BULLISH":
            bull_pts += 18
            signals.append(label)
        elif cons.get("bias") == "BEARISH":
            bear_pts += 18
            signals.append(label)

    sd = supply_demand or {}
    label = (sd.get("label") or "").replace("**", "")
    if sd.get("active_zone") == "demand":
        bull_pts += 16
        if label:
            signals.append(label)
    elif sd.get("active_zone") == "supply":
        bear_pts += 16
        if label:
            signals.append(label)
    elif sd.get("score", 0) > 0:
        bull_pts += 6
        if label:
            signals.append(label)
    elif sd.get("score", 0) < 0:
        bear_pts += 6
        if label:
            signals.append(label)

    return bull_pts, bear_pts, signals
