"""
weak_strong_sr_engine.py
------------------------
Institutional weak vs strong S/R strategy with VWAP, volume, Supertrend, and RSI
confluence across multiple timeframes (Groww · US · Crypto).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import calculate_two_level_sr, fetch_data_for_gap_scan
from app.market_pulse.indicators import add_atr, add_rsi, add_supertrend, add_vol_sma, add_vwap
from app.market_pulse.pa_sr_helpers import _calc_atr, detect_support_resistance
from app.market_pulse.sr_zone_context import (
    analyze_consolidation_near_sr,
    analyze_supply_demand_zones,
    zone_context_points,
)

STRONG_TOUCH_MIN = 3
WEAK_TOUCH_MAX = 2

_HOLD_BY_TF = {
    "1m": "15–45 min scalp",
    "5m": "1–3 hours intraday",
    "15m": "2–6 hours intraday",
    "30m": "4–12 hours intraday",
    "1h": "1–3 trading days",
    "4h": "3–10 trading days",
    "1d": "1–4 weeks swing",
}


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volume" not in out.columns:
        out["volume"] = 1.0
    return out.dropna(subset=["open", "high", "low", "close"], how="any")


def _classify_strength(touches: int, median_touches: float) -> str:
    if touches >= max(STRONG_TOUCH_MIN, int(median_touches) + 1):
        return "strong"
    if touches <= WEAK_TOUCH_MAX:
        return "weak"
    return "moderate"


def _nearest_levels(
    price: float,
    supports: list[dict],
    resistances: list[dict],
    atr: float,
) -> dict[str, Any]:
    tol = max(atr * 0.55, price * 0.0015)
    out: dict[str, Any] = {
        "nearest_support": None,
        "nearest_resistance": None,
        "support_dist_pct": None,
        "resistance_dist_pct": None,
    }

    sups = [s for s in supports if s.get("price") is not None and float(s["price"]) < price]
    ress = [r for r in resistances if r.get("price") is not None and float(r["price"]) > price]

    if sups:
        ns = max(sups, key=lambda x: float(x["price"]))
        out["nearest_support"] = ns
        out["support_dist_pct"] = (price - float(ns["price"])) / price * 100
    if ress:
        nr = min(ress, key=lambda x: float(x["price"]))
        out["nearest_resistance"] = nr
        out["resistance_dist_pct"] = (float(nr["price"]) - price) / price * 100

    # Levels on the *other* side of price — used to detect breakdowns/breakouts
    # (a support price has fallen below, or a resistance price has cleared).
    sups_above = [s for s in supports if s.get("price") is not None and float(s["price"]) >= price]
    ress_below = [r for r in resistances if r.get("price") is not None and float(r["price"]) <= price]
    out["broken_support"] = min(sups_above, key=lambda x: float(x["price"])) if sups_above else None
    out["broken_resistance"] = max(ress_below, key=lambda x: float(x["price"])) if ress_below else None

    out["at_support"] = (
        out["nearest_support"] is not None
        and out["support_dist_pct"] is not None
        and out["support_dist_pct"] <= (tol / price * 100)
    )
    out["at_resistance"] = (
        out["nearest_resistance"] is not None
        and out["resistance_dist_pct"] is not None
        and out["resistance_dist_pct"] <= (tol / price * 100)
    )
    return out


def _sr_bias_from_levels(
    price: float,
    nearest: dict[str, Any],
    median_touches: float,
    recent_low: float,
    recent_high: float,
) -> tuple[str, list[str], int, int]:
    """Return (primary_bias, reasons, bull_pts, bear_pts)."""
    bull_pts = 0
    bear_pts = 0
    reasons: list[str] = []
    bias = "NEUTRAL"

    ns = nearest.get("nearest_support")
    nr = nearest.get("nearest_resistance")

    if ns and nearest.get("at_support"):
        strength = _classify_strength(int(ns.get("touches", 1)), median_touches)
        lvl = float(ns["price"])
        if strength == "strong":
            bull_pts += 28
            reasons.append(f"Strong support {lvl:.4g} ({ns.get('touches', 1)} touches) — institutional buy zone.")
            bias = "BUY"
        elif strength == "weak":
            bear_pts += 24
            reasons.append(f"Weak support {lvl:.4g} — likely breakdown; fade longs / sell.")
            bias = "SELL"
        else:
            bull_pts += 10
            reasons.append(f"Moderate support {lvl:.4g} — wait for VWAP/volume confirm.")
            bias = "WATCH_BUY"

    if nr and nearest.get("at_resistance"):
        strength = _classify_strength(int(nr.get("touches", 1)), median_touches)
        lvl = float(nr["price"])
        if strength == "strong":
            bear_pts += 28
            reasons.append(f"Strong resistance {lvl:.4g} ({nr.get('touches', 1)} touches) — sell / take profit zone.")
            bias = "SELL" if bias != "BUY" else "CONFLICT"
        elif strength == "weak":
            bull_pts += 22
            reasons.append(f"Weak resistance {lvl:.4g} — breakout buy if volume confirms.")
            bias = "BUY" if bias != "SELL" else "CONFLICT"
        else:
            bear_pts += 8
            reasons.append(f"Moderate resistance {lvl:.4g} — trim longs unless volume breaks through.")

    bs = nearest.get("broken_support")
    if bs and not nearest.get("at_support") and price < float(bs["price"]) * 0.998:
        strength = _classify_strength(int(bs.get("touches", 1)), median_touches)
        if strength == "weak":
            bear_pts += 18
            reasons.append(f"Price broke weak support {float(bs['price']):.4g} — momentum sell.")
            bias = "SELL"
        elif strength == "strong":
            bear_pts += 8
            reasons.append(f"Price below strong support {float(bs['price']):.4g} — failed floor (sell).")
            bias = "SELL"

    br = nearest.get("broken_resistance")
    if br and not nearest.get("at_resistance") and price > float(br["price"]) * 1.002:
        strength = _classify_strength(int(br.get("touches", 1)), median_touches)
        if strength == "weak":
            bull_pts += 16
            reasons.append(f"Price cleared weak resistance {float(br['price']):.4g} — breakout buy.")
            bias = "BUY"
        elif strength == "strong":
            bull_pts += 6
            reasons.append(f"Price above strong resistance {float(br['price']):.4g} — breakout continuation.")

    if recent_low and price <= recent_low * 1.002 and bias == "NEUTRAL":
        bear_pts += 6
        reasons.append("Testing session/range low — weak-hand longs vulnerable.")

    if recent_high and price >= recent_high * 0.998 and bias == "NEUTRAL":
        bull_pts += 6
        reasons.append("Testing session/range high — weak resistance breakout watch.")

    return bias, reasons, bull_pts, bear_pts


def analyze_weak_strong_sr(
    df: pd.DataFrame,
    *,
    chart_tf: str = "15m",
    sr_window: int = 5,
    st_period: int = 10,
    st_mult: float = 3.0,
    atr_period: int = 14,
    vol_period: int = 20,
    rsi_period: int = 14,
    is_crypto: bool = False,
) -> dict[str, Any]:
    """
    Weak vs strong S/R engine with VWAP · volume · Supertrend · RSI confluence.
    """
    empty: dict[str, Any] = {
        "verdict": "NO SETUP",
        "direction": "—",
        "phase": "NO_DATA",
        "confidence": 0,
        "bull_score": 0,
        "bear_score": 0,
        "signals": [],
        "trade_plan": None,
        "sr_context": {},
        "chart_tf": chart_tf,
        "summary": "Insufficient data.",
    }
    if df is None or df.empty or len(df) < 45:
        empty["summary"] = f"Need ≥45 bars (have {len(df) if df is not None else 0})."
        return empty

    work = _normalize_df(df)
    work = add_atr(work, atr_period)
    work = add_vwap(work)
    work = add_vol_sma(work, vol_period)
    work = add_rsi(work, rsi_period)
    work = add_supertrend(work, st_period, st_mult)

    atr_col = f"atr_{atr_period}"
    st_col = f"supertrend_{st_period}_{st_mult}"
    st_dir_col = f"supertrend_dir_{st_period}_{st_mult}"
    vol_ratio_col = f"vol_ratio_{vol_period}"
    rsi_col = f"rsi_{rsi_period}"

    price = float(work["close"].iloc[-1])
    atr = float(work[atr_col].iloc[-1]) if atr_col in work.columns else _calc_atr(work, atr_period)
    vwap_val = float(work["vwap"].iloc[-1]) if "vwap" in work.columns else price
    st_dir = int(work[st_dir_col].iloc[-1]) if st_dir_col in work.columns else 0
    vol_ratio = float(work[vol_ratio_col].iloc[-1]) if vol_ratio_col in work.columns else 1.0
    rsi = float(work[rsi_col].iloc[-1]) if rsi_col in work.columns else 50.0

    sr = detect_support_resistance(work, window=sr_window, num_levels=4)
    sr2 = calculate_two_level_sr(work)
    supports = list(sr.get("supports") or [])
    resistances = list(sr.get("resistances") or [])

    # Recently crossed swing clusters so broken_support / broken_resistance can fire
    crossed_sup = sorted(
        [s for s in (sr.get("all_supports") or []) if s.get("price") is not None and float(s["price"]) >= price],
        key=lambda x: (abs(float(x["price"]) - price), -int(x.get("strength", 0))),
    )[:3]
    crossed_res = sorted(
        [r for r in (sr.get("all_resistances") or []) if r.get("price") is not None and float(r["price"]) <= price],
        key=lambda x: (abs(float(x["price"]) - price), -int(x.get("strength", 0))),
    )[:3]
    supports.extend(crossed_sup)
    resistances.extend(crossed_res)

    for key, kind in (("s1", "support"), ("s2", "support"), ("r1", "resistance"), ("r2", "resistance")):
        val = sr2.get(key)
        if val is None:
            continue
        entry = {"price": float(val), "strength": 2, "touches": 2}
        if kind == "support" and float(val) < price:
            supports.append(entry)
        elif kind == "resistance" and float(val) > price:
            resistances.append(entry)

    all_touches = [int(x.get("touches", 1)) for x in supports + resistances] or [2]
    median_touches = float(np.median(all_touches))

    nearest = _nearest_levels(price, supports, resistances, atr)
    recent_low = float(work["low"].tail(20).min())
    recent_high = float(work["high"].tail(20).max())

    sr_bias, sr_reasons, bull_pts, bear_pts = _sr_bias_from_levels(
        price, nearest, median_touches, recent_low, recent_high,
    )

    signals: list[str] = list(sr_reasons)

    # VWAP — institutional anchor
    if price > vwap_val * 1.0015:
        bull_pts += 14
        signals.append(f"Price above VWAP ({vwap_val:.4g}) — institutional bid support.")
    elif price < vwap_val * 0.9985:
        bear_pts += 14
        signals.append(f"Price below VWAP ({vwap_val:.4g}) — institutional supply overhead.")

    # Volume
    if vol_ratio >= 1.25:
        last_green = float(work["close"].iloc[-1]) >= float(work["open"].iloc[-1])
        if last_green:
            bull_pts += 12
            signals.append(f"Volume surge {vol_ratio:.2f}× on green bar — accumulation.")
        else:
            bear_pts += 12
            signals.append(f"Volume surge {vol_ratio:.2f}× on red bar — distribution.")
    elif vol_ratio < 0.75:
        signals.append(f"Thin volume ({vol_ratio:.2f}× avg) — lower confidence on breakouts.")

    # Supertrend
    if st_dir == 1:
        bull_pts += 16
        signals.append("Supertrend bullish — trend aligned for longs at support.")
    elif st_dir == -1:
        bear_pts += 16
        signals.append("Supertrend bearish — trend aligned for shorts at resistance.")

    # RSI
    if rsi >= 55 and rsi <= 72:
        bull_pts += 10
        signals.append(f"RSI {rsi:.0f} — bullish momentum without extreme overbought.")
    elif rsi <= 45 and rsi >= 28:
        bear_pts += 10
        signals.append(f"RSI {rsi:.0f} — bearish momentum without extreme oversold.")
    elif rsi > 72:
        bear_pts += 6
        signals.append(f"RSI {rsi:.0f} overbought — caution on breakout buys at resistance.")
    elif rsi < 28:
        bull_pts += 6
        signals.append(f"RSI {rsi:.0f} oversold — bounce potential at strong support.")

    sr_levels = {
        "price": price,
        "s1": sr2.get("s1"),
        "s2": sr2.get("s2"),
        "r1": sr2.get("r1"),
        "r2": sr2.get("r2"),
    }
    consolidation = analyze_consolidation_near_sr(work, sr_levels)
    supply_demand = analyze_supply_demand_zones(work, sr_window=sr_window)
    z_bull, z_bear, zone_signals = zone_context_points(consolidation, supply_demand)
    bull_pts += z_bull
    bear_pts += z_bear
    signals.extend(zone_signals)

    bull_score = bull_pts
    bear_score = bear_pts
    net = bull_score - bear_score
    confidence = min(92, max(38, 42 + abs(net) * 0.55))
    if consolidation.get("is_consolidating") or supply_demand.get("active_zone") not in ("none", None):
        confidence = min(92, confidence + int(supply_demand.get("confidence_boost", 0) or 0) + 4)

    direction = "—"
    verdict = "NO SETUP"
    phase = "MONITOR"

    if sr_bias == "CONFLICT":
        verdict = "WAIT"
        phase = "CONFLICT"
        confidence = max(38, confidence - 15)
    elif net >= 22 and bull_score >= 40:
        verdict = "STRONG BUY" if net >= 38 else "BUY"
        direction = "LONG"
        phase = "ENTRY_READY" if nearest.get("at_support") or sr_bias == "BUY" else "APPROACHING"
    elif net <= -22 and bear_score >= 40:
        verdict = "SELL"
        direction = "SHORT"
        phase = "ENTRY_READY" if nearest.get("at_resistance") or sr_bias == "SELL" else "APPROACHING"
    elif net >= 12 and bull_score >= 28:
        verdict = "WATCHLIST"
        direction = "LONG"
        phase = "APPROACHING"
    elif net <= -12 and bear_score >= 28:
        verdict = "WATCHLIST"
        direction = "SHORT"
        phase = "APPROACHING"

    # Penalize if indicators fight S/R bias
    if direction == "LONG" and st_dir == -1 and rsi < 45:
        confidence -= 12
        signals.append("⚠️ Long thesis vs bearish Supertrend/RSI — reduced confidence.")
    if direction == "SHORT" and st_dir == 1 and rsi > 55:
        confidence -= 12
        signals.append("⚠️ Short thesis vs bullish Supertrend/RSI — reduced confidence.")

    confidence = max(35, min(92, confidence))

    trade_plan: dict[str, Any] | None = None
    if verdict in ("BUY", "STRONG BUY", "SELL", "WATCHLIST") and direction in ("LONG", "SHORT"):
        ns = nearest.get("nearest_support")
        nr = nearest.get("nearest_resistance")
        if direction == "LONG":
            sl_price = float(ns["price"]) * 0.997 if ns else price - atr * 1.4
            tp_price = float(nr["price"]) if nr else price + atr * 2.2
            if tp_price <= price:
                tp_price = price + atr * 2.0
            sl_pct = max(0.25, (price - sl_price) / price * 100)
            tp_pct = max(sl_pct * 1.8, (tp_price - price) / price * 100)
        else:
            sl_price = float(nr["price"]) * 1.003 if nr else price + atr * 1.4
            tp_price = float(ns["price"]) if ns else price - atr * 2.2
            if tp_price >= price:
                tp_price = price - atr * 2.0
            sl_pct = max(0.25, (sl_price - price) / price * 100)
            tp_pct = max(sl_pct * 1.8, (price - tp_price) / price * 100)

        trade_plan = {
            "direction": direction,
            "entry": round(price, 6),
            "stop_loss": round(sl_price, 6),
            "take_profit": round(tp_price, 6),
            "sl_pct": round(sl_pct, 2),
            "tp_pct": round(tp_pct, 2),
            "confidence_pct": round(confidence, 0),
            "hold_duration": _HOLD_BY_TF.get(chart_tf, "1–5 sessions"),
            "rr_ratio": round(tp_pct / sl_pct, 2) if sl_pct > 0 else None,
        }

    ns = nearest.get("nearest_support")
    nr = nearest.get("nearest_resistance")
    summary = (
        f"{verdict} @ {chart_tf} — "
        f"S/R bias {sr_bias} · conf {confidence:.0f}% · "
        f"bull {bull_score} / bear {bear_score}"
    )

    return {
        "verdict": verdict,
        "direction": direction,
        "phase": phase,
        "confidence": round(confidence, 1),
        "bull_score": bull_score,
        "bear_score": bear_score,
        "net_score": net,
        "signals": signals,
        "trade_plan": trade_plan,
        "sr_context": {
            "sr_bias": sr_bias,
            "nearest_support": ns,
            "nearest_resistance": nr,
            "broken_support": nearest.get("broken_support"),
            "broken_resistance": nearest.get("broken_resistance"),
            "at_support": nearest.get("at_support"),
            "at_resistance": nearest.get("at_resistance"),
            "s1": sr2.get("s1"),
            "s2": sr2.get("s2"),
            "r1": sr2.get("r1"),
            "r2": sr2.get("r2"),
            "supports": supports[:4],
            "resistances": resistances[:4],
        },
        "consolidation": consolidation,
        "supply_demand": supply_demand,
        "indicators": {
            "vwap": round(vwap_val, 6),
            "rsi": round(rsi, 1),
            "vol_ratio": round(vol_ratio, 2),
            "supertrend_dir": st_dir,
            "atr": round(atr, 6),
        },
        "price": price,
        "chart_tf": chart_tf,
        "summary": summary,
    }


def aggregate_weak_strong_mtf(analyses: list[dict], chart_tfs: list[str]) -> dict[str, Any]:
    """Combine per-TF analyses into one MTF consensus."""
    valid = [a for a in analyses if a.get("verdict") not in ("NO SETUP",) and not a.get("error")]
    if not valid:
        return {"verdict": "NO SETUP", "confidence": 0, "mtf_alignment": 0, "legs": []}

    long_votes = sum(1 for a in valid if a.get("direction") == "LONG")
    short_votes = sum(1 for a in valid if a.get("direction") == "SHORT")
    avg_conf = sum(float(a.get("confidence", 0)) for a in valid) / len(valid)

    if long_votes >= len(valid) * 0.55 and long_votes > short_votes:
        mtf_verdict = "BUY"
        mtf_dir = "LONG"
    elif short_votes >= len(valid) * 0.55 and short_votes > long_votes:
        mtf_verdict = "SELL"
        mtf_dir = "SHORT"
    else:
        mtf_verdict = "MIXED"
        mtf_dir = "—"

    best = max(valid, key=lambda x: abs(x.get("net_score", 0)))
    plan = dict(best.get("trade_plan") or {})
    if plan and mtf_dir in ("LONG", "SHORT"):
        plan["direction"] = mtf_dir
        boost = min(8, (max(long_votes, short_votes) - 1) * 3)
        plan["confidence_pct"] = min(92, float(plan.get("confidence_pct", avg_conf)) + boost)

    alignment = round(max(long_votes, short_votes) / len(valid) * 100, 0)
    return {
        "verdict": mtf_verdict,
        "direction": mtf_dir,
        "confidence": round(min(92, avg_conf + alignment * 0.05), 1),
        "mtf_alignment_pct": alignment,
        "long_votes": long_votes,
        "short_votes": short_votes,
        "total_legs": len(valid),
        "trade_plan": plan if plan else None,
        "best_tf": best.get("chart_tf"),
        "legs": [
            {
                "tf": a.get("chart_tf"),
                "verdict": a.get("verdict"),
                "confidence": a.get("confidence"),
                "sr_bias": (a.get("sr_context") or {}).get("sr_bias"),
            }
            for a in valid
        ],
    }


def fetch_wssr_data(
    symbol: str,
    timeframe: str,
    market: str,
    groww_token: str,
    exchange: str,
    limit: int = 300,
) -> pd.DataFrame:
    """OHLCV fetch wrapper."""
    return fetch_data_for_gap_scan(symbol, timeframe, market, groww_token, exchange, limit=limit)
