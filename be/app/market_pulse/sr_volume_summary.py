"""
sr_volume_summary.py
--------------------
Shared helper: volume trend + proximity to S/R → plain-English break probability.
Used by Oil-Dollar-Bond and Ticker Chart.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Within this % of price → "approaching" the level
_APPROACH_PCT = 1.5
# Soft approach band (still mention but weaker)
_NEAR_PCT = 3.0


def _safe_float(v: Any) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _volume_trend(volumes: np.ndarray, *, lookback: int = 5) -> dict[str, Any]:
    """Compare recent avg volume vs prior window → rising / falling / flat."""
    empty = {
        "trend": "unknown",
        "label": "Volume n/a",
        "recent_avg": None,
        "prior_avg": None,
        "change_pct": None,
        "lookback_bars": 0,
    }
    vols = np.asarray(volumes, dtype=float)
    vols = vols[np.isfinite(vols) & (vols >= 0)]
    if len(vols) < 2:
        return empty
    lookback = min(lookback, max(1, len(vols) // 2)) if len(vols) < max(4, lookback * 2) else lookback
    lb = min(lookback, max(1, len(vols) // 2))

    recent = float(np.nanmean(vols[-lb:]))
    if len(vols) >= lb * 2:
        prior = float(np.nanmean(vols[-(lb * 2):-lb]))
    elif len(vols) > lb:
        prior = float(np.nanmean(vols[:-lb]))
    else:
        prior = recent

    if prior <= 0:
        change_pct = 0.0 if recent <= 0 else 100.0
    else:
        change_pct = ((recent / prior) - 1.0) * 100.0

    if change_pct >= 15:
        trend, label = "increasing", "Increasing volume"
    elif change_pct <= -15:
        trend, label = "decreasing", "Decreasing volume"
    else:
        trend, label = "flat", "Flat / consolidating volume"

    return {
        "trend": trend,
        "label": label,
        "recent_avg": round(recent, 2),
        "prior_avg": round(prior, 2),
        "change_pct": round(change_pct, 1),
        "lookback_bars": lb,
    }


def _proximity(last: float, level: float | None) -> float | None:
    if level is None or last == 0:
        return None
    return abs(last - level) / abs(last) * 100.0


def build_sr_volume_summary(
    df: pd.DataFrame,
    sr: dict[str, Any] | None,
    *,
    name: str = "",
) -> dict[str, Any]:
    """
    Analyze last price vs S1/R1 with volume trend.

    Returns structured fields + plain_english suggestion for break probability.
    """
    empty = {
        "name": name or None,
        "last": None,
        "volume_trend": "unknown",
        "volume_label": "Volume n/a",
        "volume_change_pct": None,
        "approach": "none",
        "approach_level": None,
        "approach_label": None,
        "distance_pct": None,
        "break_bias": "neutral",
        "break_probability_pct": None,
        "break_target": None,
        "summary": "Not enough data for volume / S/R read.",
        "plain_english": "Not enough data for volume / S/R read.",
    }
    if df is None or df.empty or len(df) < 3:
        return empty

    closes = df["close"].astype(float).values
    last = float(closes[-1])
    sr = sr or {}
    s1 = _safe_float(sr.get("s1"))
    r1 = _safe_float(sr.get("r1"))
    s2 = _safe_float(sr.get("s2"))
    r2 = _safe_float(sr.get("r2"))

    if "volume" in df.columns:
        vol_info = _volume_trend(df["volume"].astype(float).values)
    else:
        vol_info = {
            "trend": "unknown",
            "label": "Volume n/a",
            "recent_avg": None,
            "prior_avg": None,
            "change_pct": None,
            "lookback_bars": 0,
        }

    dist_s1 = _proximity(last, s1)
    dist_r1 = _proximity(last, r1)

    approach = "mid_range"
    approach_level = None
    approach_label = None
    distance_pct = None
    side: str | None = None

    candidates: list[tuple[str, float, float, str]] = []
    if s1 is not None and dist_s1 is not None and last >= s1:
        candidates.append(("support", s1, dist_s1, "S1"))
    elif s1 is not None and dist_s1 is not None and last < s1:
        if s2 is not None:
            d2 = _proximity(last, s2)
            if d2 is not None:
                candidates.append(("support", s2, d2, "S2"))
        candidates.append(("support", s1, dist_s1, "S1"))
    if r1 is not None and dist_r1 is not None and last <= r1:
        candidates.append(("resistance", r1, dist_r1, "R1"))
    elif r1 is not None and dist_r1 is not None and last > r1:
        if r2 is not None:
            d2 = _proximity(last, r2)
            if d2 is not None:
                candidates.append(("resistance", r2, d2, "R2"))
        candidates.append(("resistance", r1, dist_r1, "R1"))

    approaching = [c for c in candidates if c[2] <= _NEAR_PCT]
    if approaching:
        approaching.sort(key=lambda x: x[2])
        side, approach_level, distance_pct, approach_label = approaching[0]
        if distance_pct <= _APPROACH_PCT:
            approach = f"approaching_{side}"
        else:
            approach = f"near_{side}"
    else:
        approach = "mid_range"
        if dist_s1 is not None and dist_r1 is not None:
            if dist_s1 <= dist_r1 and s1 is not None:
                approach_level, distance_pct, approach_label, side = s1, dist_s1, "S1", "support"
            elif r1 is not None:
                approach_level, distance_pct, approach_label, side = r1, dist_r1, "R1", "resistance"
        elif dist_s1 is not None and s1 is not None:
            approach_level, distance_pct, approach_label, side = s1, dist_s1, "S1", "support"
        elif dist_r1 is not None and r1 is not None:
            approach_level, distance_pct, approach_label, side = r1, dist_r1, "R1", "resistance"

    vtrend = vol_info["trend"]
    break_bias = "neutral"
    break_target = None
    base = 35

    if approach.startswith("approaching_") or approach.startswith("near_"):
        tight = approach.startswith("approaching_")
        base = 55 if tight else 42
        if side == "resistance":
            break_target = approach_label
            if vtrend == "increasing":
                break_bias = "break_resistance"
                base += 22 if tight else 14
            elif vtrend == "decreasing":
                break_bias = "hold_resistance"
                base = max(20, base - 18)
            else:
                break_bias = "consolidate_at_resistance"
                base = max(25, base - 8)
        elif side == "support":
            break_target = approach_label
            if vtrend == "increasing":
                break_bias = "break_support"
                base += 22 if tight else 14
            elif vtrend == "decreasing":
                break_bias = "hold_support"
                base = max(20, base - 18)
            else:
                break_bias = "consolidate_at_support"
                base = max(25, base - 8)
    else:
        if vtrend == "increasing":
            break_bias = "expanding_range_possible"
            base = 40
        elif vtrend == "decreasing":
            break_bias = "range_bound"
            base = 28
        else:
            break_bias = "quiet_mid_range"
            base = 25

    prob = int(max(15, min(88, base)))

    vol_txt = vol_info["label"]
    if vol_info.get("change_pct") is not None:
        vol_txt = f"{vol_info['label']} ({vol_info['change_pct']:+.0f}% vs prior {vol_info.get('lookback_bars', 5)} bars)"

    if approach.startswith("approaching_resistance") or approach.startswith("near_resistance"):
        loc = (
            f"Price is {'approaching' if approach.startswith('approaching') else 'near'} "
            f"{approach_label} resistance at {approach_level:.4g} ({distance_pct:.2f}% away)."
        )
        if break_bias == "break_resistance":
            suggestion = (
                f"{loc} {vol_txt} — rising participation into resistance raises the chance of a "
                f"break above {approach_label} (~{prob}% heuristic). Watch for a close through the level with follow-through."
            )
        elif break_bias == "hold_resistance":
            suggestion = (
                f"{loc} {vol_txt} — fading volume into resistance favors a rejection / hold "
                f"(break probability only ~{prob}%). More likely fade back toward mid-range / support."
            )
        else:
            suggestion = (
                f"{loc} {vol_txt} — flat volume suggests consolidation under resistance; "
                f"break odds modest (~{prob}%). Wait for volume expansion for a cleaner break or fail."
            )
    elif approach.startswith("approaching_support") or approach.startswith("near_support"):
        loc = (
            f"Price is {'approaching' if approach.startswith('approaching') else 'near'} "
            f"{approach_label} support at {approach_level:.4g} ({distance_pct:.2f}% away)."
        )
        if break_bias == "break_support":
            suggestion = (
                f"{loc} {vol_txt} — rising volume into support raises the chance of a "
                f"break below {approach_label} (~{prob}% heuristic). Prefer confirmation on a close under the level."
            )
        elif break_bias == "hold_support":
            suggestion = (
                f"{loc} {vol_txt} — drying volume into support favors a bounce / hold "
                f"(break probability only ~{prob}%). More likely rebound toward mid-range / resistance."
            )
        else:
            suggestion = (
                f"{loc} {vol_txt} — flat volume suggests consolidation on support; "
                f"break odds modest (~{prob}%). Wait for volume expansion for a cleaner break or bounce."
            )
    else:
        s_bit = f"S1 {s1:.4g}" if s1 is not None else "S1 n/a"
        r_bit = f"R1 {r1:.4g}" if r1 is not None else "R1 n/a"
        suggestion = (
            f"Price is mid-range between {s_bit} and {r_bit} (last {last:.4g}). {vol_txt}. "
            f"No immediate S/R test — break probability of nearest level stays moderate (~{prob}%). "
            f"A volume surge toward S1 or R1 would clarify the next break/hold bias."
        )

    headline_map = {
        "break_resistance": f"Rising volume into {approach_label} → breakout risk ↑ (~{prob}%)",
        "hold_resistance": f"Fading volume into {approach_label} → rejection more likely (~{prob}% break)",
        "consolidate_at_resistance": f"Flat volume under {approach_label} → chop / wait (~{prob}% break)",
        "break_support": f"Rising volume into {approach_label} → breakdown risk ↑ (~{prob}%)",
        "hold_support": f"Fading volume into {approach_label} → bounce more likely (~{prob}% break)",
        "consolidate_at_support": f"Flat volume on {approach_label} → chop / wait (~{prob}% break)",
        "expanding_range_possible": f"Mid-range with rising volume → range expansion possible (~{prob}%)",
        "range_bound": f"Mid-range with falling volume → quiet range (~{prob}%)",
        "quiet_mid_range": f"Mid-range, flat volume → wait for level test (~{prob}%)",
        "neutral": f"S/R + volume read inconclusive (~{prob}%)",
    }
    summary = headline_map.get(break_bias, suggestion[:140])

    return {
        "name": name or None,
        "last": round(last, 4),
        "volume_trend": vtrend,
        "volume_label": vol_info["label"],
        "volume_change_pct": vol_info.get("change_pct"),
        "volume_recent_avg": vol_info.get("recent_avg"),
        "volume_prior_avg": vol_info.get("prior_avg"),
        "approach": approach,
        "approach_side": side,
        "approach_level": round(approach_level, 4) if approach_level is not None else None,
        "approach_label": approach_label,
        "distance_pct": round(distance_pct, 3) if distance_pct is not None else None,
        "break_bias": break_bias,
        "break_probability_pct": prob,
        "break_target": break_target,
        "summary": summary,
        "plain_english": suggestion,
    }


def ohlc_to_chart_points(df: pd.DataFrame, *, intraday: bool) -> list[dict[str, Any]]:
    """Close + volume points for FE line/bar combo charts."""
    points: list[dict[str, Any]] = []
    has_vol = "volume" in df.columns
    for ts, row in df.iterrows():
        try:
            v = float(row["close"])
        except (TypeError, ValueError, KeyError):
            continue
        if v != v:
            continue
        t = pd.Timestamp(ts)
        if intraday:
            label = t.strftime("%H:%M")
            iso = t.isoformat()
        else:
            label = t.strftime("%Y-%m-%d")
            iso = label
        vol = None
        if has_vol:
            try:
                raw_vol = float(row["volume"])
                if raw_vol == raw_vol and raw_vol >= 0:
                    vol = round(raw_vol, 2)
            except (TypeError, ValueError):
                vol = None
        points.append({"t": iso, "label": label, "value": round(v, 4), "volume": vol})
    return points
