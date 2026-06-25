"""
Zireman-style Confluence Strategy
==================================
A Python re-implementation of the *concepts* behind three TradingView
indicators (Ranked Order Block Zones, Ranked FVG Imbalance Zones, Ranked
Support & Resistance Zones) combined into one confluence-scoring signal
engine, with a simple bar-by-bar backtester.

This is an independent interpretation for backtesting/education -- it does
NOT reproduce Zireman's proprietary Pine Script. The underlying ideas
(order blocks, fair value gaps, support/resistance clustering, and
ranking/scoring by volume + ATR + trend alignment) are standard price-action
concepts; this module implements them in pandas/numpy.

Data format expected: a DataFrame with a clean RangeIndex (0..n-1) and
columns: open, high, low, close, volume  (lowercase).

Author: generated for educational / backtesting use. NOT FINANCIAL ADVICE.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# 0. Shared utilities
# ----------------------------------------------------------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a simple 0..n-1 integer index (required for positional logic)."""
    out = df.reset_index(drop=True).copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in out.columns:
            raise ValueError(f"DataFrame is missing required column '{col}'")
    if "volume" not in out.columns or out["volume"].isna().all():
        out["volume"] = 1.0
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(1.0)
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["open", "high", "low", "close"], how="any")


# ----------------------------------------------------------------------
# 1. Zone container
# ----------------------------------------------------------------------

@dataclass
class Zone:
    kind: str               # "order_block" | "fvg" | "sr"
    direction: str          # "bullish" | "bearish"
    top: float
    bottom: float
    index: int              # bar index where the zone formed
    score: float = 0.0      # rank score, 0-100 (higher = higher quality)
    pressure_pct: Optional[float] = None   # directional pressure %, 0-100
    label: str = ""
    mitigated: bool = False  # consumed by a trade already

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def overlaps(self, other: "Zone") -> bool:
        return not (self.top < other.bottom or self.bottom > other.top)


# ----------------------------------------------------------------------
# 2. Ranked Order Block Zones
# ----------------------------------------------------------------------

def detect_order_blocks(
    df: pd.DataFrame,
    atr_period: int = 14,
    ema_period: int = 50,
    vol_lookback: int = 20,
    displacement_atr_mult: float = 1.5,
    top_n: int = 8,
) -> List[Zone]:
    """
    An order block is the last opposite-colored candle right before a sharp
    displacement (impulse) move.
      - Bullish OB  = last bearish candle before a strong rally  -> support
      - Bearish OB  = last bullish candle before a strong drop   -> resistance
    """
    df = _clean(df)
    a = atr(df, atr_period)
    e = ema(df["close"], ema_period)
    avg_vol = df["volume"].rolling(vol_lookback).mean()
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

    zones: List[Zone] = []

    for i in range(vol_lookback, len(df) - 1):
        cur_atr = a.iloc[i]
        if pd.isna(cur_atr) or cur_atr == 0:
            continue

        body = c.iloc[i] - o.iloc[i]
        displacement = abs(body) / cur_atr
        if displacement < displacement_atr_mult:
            continue

        impulse_dir = "bullish" if body > 0 else "bearish"
        ob_idx = i - 1
        ob_dir = "bullish" if impulse_dir == "bullish" else "bearish"
        if ob_dir == "bullish" and c.iloc[ob_idx] >= o.iloc[ob_idx]:
            continue
        if ob_dir == "bearish" and c.iloc[ob_idx] <= o.iloc[ob_idx]:
            continue

        vol_avg = avg_vol.iloc[i]
        vol_exp = v.iloc[i] / vol_avg if (vol_avg and not pd.isna(vol_avg) and vol_avg > 0) else 1.0

        trend_alignment = 1.0
        e_i = e.iloc[i]
        if not pd.isna(e_i):
            aligned = (impulse_dir == "bullish" and c.iloc[i] > e_i) or \
                      (impulse_dir == "bearish" and c.iloc[i] < e_i)
            trend_alignment = 1.3 if aligned else 0.8

        raw_score = (displacement * 10 + vol_exp * 8) * trend_alignment
        score = float(min(100.0, raw_score))

        zones.append(Zone(
            kind="order_block",
            direction=ob_dir,
            top=float(h.iloc[ob_idx]),
            bottom=float(l.iloc[ob_idx]),
            index=ob_idx,
            score=score,
            label=f"{ob_dir.title()} Order Block (score {score:.1f}, "
                  f"disp={displacement:.1f}xATR, vol={vol_exp:.1f}x)",
        ))

    zones.sort(key=lambda z: z.score, reverse=True)
    return zones[:top_n]


# ----------------------------------------------------------------------
# 3. Ranked FVG Imbalance Zones
# ----------------------------------------------------------------------

def detect_fvg(
    df: pd.DataFrame,
    atr_period: int = 14,
    min_gap_atr: float = 0.10,
    top_n: int = 8,
) -> List[Zone]:
    """Classic 3-candle Fair Value Gap."""
    df = _clean(df)
    a = atr(df, atr_period)
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
    zones: List[Zone] = []

    for i in range(2, len(df)):
        i1, i2, i3 = i - 2, i - 1, i
        cur_atr = a.iloc[i]
        if pd.isna(cur_atr) or cur_atr == 0:
            continue

        total_vol = v.iloc[i1] + v.iloc[i2] + v.iloc[i3]

        if l.iloc[i3] > h.iloc[i1]:
            gap = l.iloc[i3] - h.iloc[i1]
            if gap / cur_atr < min_gap_atr:
                continue
            up_vol = sum(v.iloc[k] for k in (i1, i2, i3) if c.iloc[k] >= o.iloc[k])
            bull_pct = (up_vol / total_vol * 100) if total_vol > 0 else 50.0
            bear_pct = 100 - bull_pct
            score = float(min(100.0, (gap / cur_atr) * 20 + bull_pct * 0.3))
            strength = "Strong" if bull_pct >= 70 else ("Moderate" if bull_pct >= 55 else "Weak")
            zones.append(Zone(
                kind="fvg", direction="bullish",
                top=float(l.iloc[i3]), bottom=float(h.iloc[i1]), index=i2, score=score,
                pressure_pct=bull_pct,
                label=f"{strength} Bullish Imbalance ({bull_pct:.0f}% buy / {bear_pct:.0f}% sell)",
            ))

        if h.iloc[i3] < l.iloc[i1]:
            gap = l.iloc[i1] - h.iloc[i3]
            if gap / cur_atr < min_gap_atr:
                continue
            down_vol = sum(v.iloc[k] for k in (i1, i2, i3) if c.iloc[k] < o.iloc[k])
            bear_pct = (down_vol / total_vol * 100) if total_vol > 0 else 50.0
            bull_pct = 100 - bear_pct
            score = float(min(100.0, (gap / cur_atr) * 20 + bear_pct * 0.3))
            strength = "Strong" if bear_pct >= 70 else ("Moderate" if bear_pct >= 55 else "Weak")
            zones.append(Zone(
                kind="fvg", direction="bearish",
                top=float(l.iloc[i1]), bottom=float(h.iloc[i3]), index=i2, score=score,
                pressure_pct=bear_pct,
                label=f"{strength} Bearish Imbalance ({bear_pct:.0f}% sell / {bull_pct:.0f}% buy)",
            ))

    zones.sort(key=lambda z: z.score, reverse=True)
    return zones[:top_n]


# ----------------------------------------------------------------------
# 4. Ranked Support & Resistance Zones
# ----------------------------------------------------------------------

def detect_sr_zones(
    df: pd.DataFrame,
    pivot_lookback: int = 5,
    cluster_tolerance_pct: float = 0.25,
    min_touches: int = 2,
    top_n: int = 6,
) -> List[Zone]:
    """Swing pivots clustered into macro S/R zones."""
    df = _clean(df)
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
    n = len(df)

    pivot_highs, pivot_lows = [], []
    for i in range(pivot_lookback, n - pivot_lookback):
        win_h = h.iloc[i - pivot_lookback: i + pivot_lookback + 1]
        win_l = l.iloc[i - pivot_lookback: i + pivot_lookback + 1]
        if h.iloc[i] == win_h.max():
            pivot_highs.append(i)
        if l.iloc[i] == win_l.min():
            pivot_lows.append(i)

    def cluster_pivots(pivots, price_series, direction):
        clusters = []
        for idx in pivots:
            price = float(price_series.iloc[idx])
            placed = False
            for cl in clusters:
                if cl["level"] != 0 and abs(price - cl["level"]) / cl["level"] * 100 <= cluster_tolerance_pct:
                    cl["indices"].append(idx)
                    cl["level"] = float(np.mean([price_series.iloc[j] for j in cl["indices"]]))
                    placed = True
                    break
            if not placed:
                clusters.append({"level": price, "indices": [idx]})

        out_zones = []
        for cl in clusters:
            touches = len(cl["indices"])
            if touches < min_touches:
                continue
            last_idx = max(cl["indices"])
            recency_weight = 1 + (last_idx / n)
            score = float(min(100.0, touches * 15 * recency_weight))

            up_vol = sum(v.iloc[j] for j in cl["indices"] if c.iloc[j] >= o.iloc[j])
            down_vol = sum(v.iloc[j] for j in cl["indices"] if c.iloc[j] < o.iloc[j])
            total = up_vol + down_vol
            buy_pct = (up_vol / total * 100) if total > 0 else 50.0
            sell_pct = 100 - buy_pct

            band = cl["level"] * (cluster_tolerance_pct / 100)
            out_zones.append(Zone(
                kind="sr", direction=direction,
                top=cl["level"] + band, bottom=cl["level"] - band,
                index=last_idx, score=score,
                pressure_pct=sell_pct if direction == "bearish" else buy_pct,
                label=f"{direction.title()} S/R zone (touches={touches}, "
                      f"{buy_pct:.0f}% buy / {sell_pct:.0f}% sell)",
            ))
        return out_zones

    res_zones = cluster_pivots(pivot_highs, h, "bearish")
    sup_zones = cluster_pivots(pivot_lows, l, "bullish")
    all_zones = res_zones + sup_zones
    all_zones.sort(key=lambda z: z.score, reverse=True)
    return all_zones[:top_n]


# ----------------------------------------------------------------------
# 5. Confluence signal engine
# ----------------------------------------------------------------------

@dataclass
class Signal:
    index: int
    side: str          # "long" | "short"
    entry: float
    stop: float
    target: float
    confluence_score: float
    reasons: List[str] = field(default_factory=list)


def find_confluence_signals(
    df: pd.DataFrame,
    order_blocks: List[Zone],
    fvgs: List[Zone],
    sr_zones: List[Zone],
    min_confluence: float = 60.0,
    rr_target: float = 2.0,
) -> List[Signal]:
    """Walk forward — OB/FVG + overlapping S/R confluence."""
    df = _clean(df)
    h, l, c = df["high"], df["low"], df["close"]
    primary_zones = [Zone(**{**asdict(z), "mitigated": False}) for z in order_blocks + fvgs]
    signals: List[Signal] = []

    for i in range(len(df)):
        price_high, price_low, price_close = float(h.iloc[i]), float(l.iloc[i]), float(c.iloc[i])

        for pz in primary_zones:
            if pz.mitigated or pz.index >= i:
                continue
            touched = (price_low <= pz.top) and (price_high >= pz.bottom)
            if not touched:
                continue

            confluence_sr = [
                z for z in sr_zones
                if z.index < i and z.direction == pz.direction and z.overlaps(pz)
            ]
            confluence_bonus = max((z.score for z in confluence_sr), default=0.0) * 0.4
            total_score = float(min(100.0, pz.score * 0.6 + confluence_bonus))

            pz.mitigated = True

            if total_score < min_confluence:
                continue

            if pz.direction == "bearish":
                side = "short"
                entry = price_close
                stop = pz.top * 1.001
                risk = stop - entry
                if risk <= 0:
                    continue
                target = entry - risk * rr_target
            else:
                side = "long"
                entry = price_close
                stop = pz.bottom * 0.999
                risk = entry - stop
                if risk <= 0:
                    continue
                target = entry + risk * rr_target

            reasons = [pz.label] + [z.label for z in confluence_sr]
            signals.append(Signal(
                index=i, side=side, entry=entry, stop=stop, target=target,
                confluence_score=total_score, reasons=reasons,
            ))

    return signals


# ----------------------------------------------------------------------
# 6. Simple bar-by-bar backtester (one position at a time)
# ----------------------------------------------------------------------

def backtest_signals(df: pd.DataFrame, signals: List[Signal]) -> pd.DataFrame:
    df = _clean(df)
    h, l = df["high"], df["low"]

    signals_by_index: dict[int, list[Signal]] = {}
    for s in signals:
        signals_by_index.setdefault(s.index, []).append(s)

    trades = []
    in_position = False
    current: Optional[Signal] = None

    for i in range(len(df)):
        if in_position and current is not None:
            sig = current
            hit_stop = (l.iloc[i] <= sig.stop) if sig.side == "long" else (h.iloc[i] >= sig.stop)
            hit_target = (h.iloc[i] >= sig.target) if sig.side == "long" else (l.iloc[i] <= sig.target)
            if hit_stop or hit_target:
                exit_price = sig.stop if hit_stop else sig.target
                pnl = (exit_price - sig.entry) if sig.side == "long" else (sig.entry - exit_price)
                trades.append({
                    "entry_index": sig.index, "exit_index": i, "side": sig.side,
                    "entry": sig.entry, "exit": exit_price, "pnl": pnl,
                    "result": "loss" if hit_stop else "win",
                    "confluence_score": sig.confluence_score,
                    "reasons": "; ".join(sig.reasons),
                })
                in_position = False
                current = None
            continue

        if i in signals_by_index:
            current = sorted(signals_by_index[i], key=lambda s: s.confluence_score, reverse=True)[0]
            in_position = True

    return pd.DataFrame(trades)


# ----------------------------------------------------------------------
# 7. One-call pipeline
# ----------------------------------------------------------------------

def run_strategy(
    df: pd.DataFrame,
    min_confluence: float = 60.0,
    rr_target: float = 2.0,
) -> dict:
    """Runs all three detectors + confluence engine + backtest in one call."""
    df = _clean(df)
    obs = detect_order_blocks(df)
    fvgs = detect_fvg(df)
    sr = detect_sr_zones(df)
    signals = find_confluence_signals(df, obs, fvgs, sr, min_confluence, rr_target)
    trades = backtest_signals(df, signals)

    summary: dict[str, Any] = {}
    if not trades.empty:
        wins = (trades["result"] == "win").sum()
        summary = {
            "total_trades": len(trades),
            "win_rate_pct": round(wins / len(trades) * 100, 1),
            "total_pnl": round(float(trades["pnl"].sum()), 5),
            "avg_pnl_per_trade": round(float(trades["pnl"].mean()), 5),
        }

    price = float(df["close"].iloc[-1])
    latest = latest_signal(signals, lookback_bars=5)

    return {
        "order_blocks": obs,
        "fvgs": fvgs,
        "sr_zones": sr,
        "signals": signals,
        "trades": trades,
        "summary": summary,
        "price": price,
        "latest_signal": latest,
        "bars": len(df),
    }


def latest_signal(signals: List[Signal], lookback_bars: int = 5) -> Optional[Signal]:
    """Most recent confluence signal within the last N bars."""
    if not signals:
        return None
    max_idx = max(s.index for s in signals)
    cutoff = max_idx - lookback_bars
    recent = [s for s in signals if s.index >= cutoff]
    if not recent:
        return None
    return max(recent, key=lambda s: (s.index, s.confluence_score))


def zone_to_dict(z: Zone) -> dict[str, Any]:
    return {
        "kind": z.kind,
        "direction": z.direction,
        "top": round(z.top, 6),
        "bottom": round(z.bottom, 6),
        "score": round(z.score, 1),
        "pressure_pct": z.pressure_pct,
        "label": z.label,
        "bar_index": z.index,
    }


def signal_to_dict(s: Signal, *, currency: str = "₹") -> dict[str, Any]:
    entry, stop, target = s.entry, s.stop, s.target
    if s.side == "long":
        sl_pct = (entry - stop) / entry * 100 if entry else 0
        tp_pct = (target - entry) / entry * 100 if entry else 0
    else:
        sl_pct = (stop - entry) / entry * 100 if entry else 0
        tp_pct = (entry - target) / entry * 100 if entry else 0
    rr = tp_pct / sl_pct if sl_pct > 0 else None
    return {
        "side": s.side.upper(),
        "entry": entry,
        "stop": stop,
        "target": target,
        "confluence_score": round(s.confluence_score, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "rr_ratio": round(rr, 2) if rr else None,
        "reasons": s.reasons,
        "bar_index": s.index,
        "entry_fmt": f"{currency}{entry:,.4g}",
        "stop_fmt": f"{currency}{stop:,.4g}",
        "target_fmt": f"{currency}{target:,.4g}",
    }


def serialize_result(result: dict, *, currency: str = "₹") -> dict[str, Any]:
    """JSON-friendly payload for UI / Ask AI."""
    latest = result.get("latest_signal")
    return {
        "price": result.get("price"),
        "bars": result.get("bars"),
        "summary": result.get("summary") or {},
        "order_blocks": [zone_to_dict(z) for z in result.get("order_blocks") or []],
        "fvgs": [zone_to_dict(z) for z in result.get("fvgs") or []],
        "sr_zones": [zone_to_dict(z) for z in result.get("sr_zones") or []],
        "signal_count": len(result.get("signals") or []),
        "latest_signal": signal_to_dict(latest, currency=currency) if latest else None,
        "recent_trades": (
            result["trades"].tail(8).to_dict(orient="records")
            if isinstance(result.get("trades"), pd.DataFrame) and not result["trades"].empty
            else []
        ),
    }
