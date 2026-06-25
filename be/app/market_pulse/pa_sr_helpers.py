"""Minimal S/R helpers extracted from price_action (avoids heavy imports)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    try:
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        tr = []
        for i in range(1, len(h)):
            tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        if not tr:
            return float((df["high"] - df["low"]).mean())
        return float(pd.Series(tr).ewm(span=period, adjust=False).mean().iloc[-1])
    except Exception:
        return float((df["high"] - df["low"]).mean())


def detect_support_resistance(
    df: pd.DataFrame,
    window: int = 5,
    num_levels: int = 3,
    atr_tolerance_mult: float = 0.5,
) -> dict:
    if df.empty or len(df) < window * 2 + 1:
        return {"supports": [], "resistances": []}

    highs = df["high"].values
    lows = df["low"].values
    close_arr = df["close"].values
    vol = df["volume"].values if "volume" in df.columns else np.ones(len(df))
    current_price = float(close_arr[-1])

    atr = _calc_atr(df, 14)
    tolerance = atr * atr_tolerance_mult

    swing_highs = []
    swing_lows = []
    for i in range(window, len(df) - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            swing_highs.append((float(highs[i]), float(vol[i]), i))
        if lows[i] == min(lows[i - window : i + window + 1]):
            swing_lows.append((float(lows[i]), float(vol[i]), i))

    def cluster_levels(levels, tol):
        if not levels:
            return []
        sorted_lvls = sorted(levels, key=lambda x: x[0])
        clusters = []
        current_cluster = [sorted_lvls[0]]
        for lvl in sorted_lvls[1:]:
            if abs(lvl[0] - current_cluster[-1][0]) <= tol:
                current_cluster.append(lvl)
            else:
                clusters.append(current_cluster)
                current_cluster = [lvl]
        clusters.append(current_cluster)

        result = []
        for cluster in clusters:
            total_vol = sum(l[1] for l in cluster)
            vwap = sum(l[0] * l[1] for l in cluster) / total_vol if total_vol > 0 else np.mean([l[0] for l in cluster])
            strength = len(cluster)
            recency = max(l[2] for l in cluster)
            result.append({"price": round(float(vwap), 4), "strength": strength, "touches": strength, "recency": recency})
        return result

    all_supports = cluster_levels(swing_lows, tolerance)
    all_resistances = cluster_levels(swing_highs, tolerance)
    supports = sorted([s for s in all_supports if s["price"] < current_price], key=lambda x: (-x["strength"], -x["recency"]))[:num_levels]
    resistances = sorted([r for r in all_resistances if r["price"] > current_price], key=lambda x: (-x["strength"], -x["recency"]))[:num_levels]
    return {"supports": supports, "resistances": resistances}
