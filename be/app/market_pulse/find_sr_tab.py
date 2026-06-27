"""
find_sr_tab.py
--------------
Find Support & Resistance — multi-ticker × multi-timeframe S/R levels,
trendline break risk, structure/pattern break signals, and AI refinement.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
from app.market_pulse.ai_view import (
    MTF_AI_SYSTEM,
    STANDARD_REPORT_FORMAT,
    combine_timeframe_sections,
    call_ai_report,
    mtf_ticker_button,
    render_ai_config,
    render_mtf_ai_view_report,
    show_ai_view_block,
)
from app.market_pulse.gap_trading import calculate_two_level_sr, fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.price_action import (
    _calc_atr,
    analyze_ema_crossovers,
    analyze_rsi,
    detect_candlestick_patterns,
    detect_chart_patterns,
    detect_support_resistance,
    detect_trendlines,
)
from app.market_pulse.price_extremes import classify_swing_structure
from app.market_pulse.ta_screener_ui import (
    render_ta_screener_options,
    render_ta_screener_results,
    render_strategy_mtf_panel,
    should_show_ticker_in_screener,
)
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
    render_market_selectbox,
)
from app.market_pulse.ta_ticker_sections import (
    should_expand_ticker,
    ticker_section_label,
)
from app.market_pulse.run_summary import (
    make_summary,
    render_run_summary,
    summarize_error,
)
from app.market_pulse.sma_ema_position import analyze_ema_ladder, _render_ema_ladder_panel
from app.market_pulse.sr_breakout import analyze_sr_breakout
from app.market_pulse.sr_zone_context import (
    analyze_consolidation_near_sr as _analyze_consolidation_near_sr,
    analyze_supply_demand_zones as _analyze_supply_demand_zones,
)
from app.market_pulse.ta_structure_chart import render_ta_structure_section

from app.market_pulse.ticker_utils import (
    is_crypto_market,
    is_india_market,
    market_currency,
)


FIND_SR_AI_SYSTEM = """You are an expert support/resistance and market-structure analyst for Indian equities (NSE/BSE) and crypto.

Focus on:
- Two immediate supports (S1, S2) and resistances (R1, R2)
- **Consolidation near resistance = bullish** (coiling under supply → breakout watch)
- **Consolidation near support = bearish** (coiling above demand → breakdown watch)
- **Supply vs demand zones** from historical swing reactions (rejections at highs / bounces at lows)
- Trendline break / imminent break in either direction
- Swing structure (HH/HL/LH/LL) and classical pattern completion risk
- Clear bullish, bearish, or neutral stance with confidence

Be data-driven — cite exact prices from the input. If signals conflict, say NEUTRAL or AVOID with lower confidence.
""" + STANDARD_REPORT_FORMAT


def _trendline_value_at_bar(tl: dict, bar_idx: int) -> float | None:
    if not tl:
        return None
    return float(tl.get("slope", 0)) * bar_idx + float(tl.get("intercept", 0))


def analyze_trendline_break(df: pd.DataFrame, trendlines: dict) -> dict[str, Any]:
    """Detect trendline tests, breaks, and imminent break direction."""
    out: dict[str, Any] = {
        "uptrend": None,
        "downtrend": None,
        "imminent_direction": None,
        "summary": "No active trendline break setup.",
    }
    if df is None or df.empty or len(df) < 20:
        return out

    n = len(df)
    price = float(df["close"].iloc[-1])
    atr = _calc_atr(df, 14)
    tol = max(atr * 0.35, price * 0.002)

    up = trendlines.get("uptrend")
    if up:
        line = _trendline_value_at_bar(up, n - 1)
        if line is not None:
            dist = price - line
            status = "holding"
            note = f"Ascending trendline support near {_fmt(line)} — price above line."
            imminent = None
            if dist < -tol:
                status = "broken"
                imminent = "bearish"
                note = f"Bearish break: closed below ascending trendline ({_fmt(line)})."
            elif dist < tol:
                status = "testing"
                imminent = "bearish"
                note = f"Imminent bearish break — price testing ascending trendline ({_fmt(line)})."
            out["uptrend"] = {"level": line, "status": status, "distance": dist, "note": note}
            if imminent:
                out["imminent_direction"] = imminent

    down = trendlines.get("downtrend")
    if down:
        line = _trendline_value_at_bar(down, n - 1)
        if line is not None:
            dist = price - line
            status = "holding"
            note = f"Descending trendline resistance near {_fmt(line)} — price below line."
            imminent = None
            if dist > tol:
                status = "broken"
                imminent = "bullish"
                note = f"Bullish break: closed above descending trendline ({_fmt(line)})."
            elif dist > -tol:
                status = "testing"
                imminent = "bullish"
                note = f"Imminent bullish break — price testing descending trendline ({_fmt(line)})."
            out["downtrend"] = {"level": line, "status": status, "distance": dist, "note": note}
            if imminent and not out["imminent_direction"]:
                out["imminent_direction"] = imminent
            elif imminent and out["imminent_direction"] != imminent:
                out["imminent_direction"] = "mixed"

    parts = []
    if out.get("uptrend"):
        parts.append(out["uptrend"]["note"])
    if out.get("downtrend"):
        parts.append(out["downtrend"]["note"])
    if parts:
        out["summary"] = " ".join(parts)
    return out


def _pattern_break_risk(
    df: pd.DataFrame,
    structure: dict,
    sr_event: dict,
    chart_patterns: list[dict],
    candles: list[dict],
) -> dict[str, Any]:
    """Structure / pattern about to break or completing."""
    price = float(df["close"].iloc[-1])
    risks: list[str] = []
    direction = "neutral"
    score = 0.0

    bias = structure.get("structure_bias", "neutral")
    if bias == "bullish":
        score += 1.0
        risks.append(f"Bullish structure: {structure.get('structure_name', 'HH/HL')}")
    elif bias == "bearish":
        score -= 1.0
        risks.append(f"Bearish structure: {structure.get('structure_name', 'LH/LL')}")

    event = sr_event.get("event", "RANGE")
    ev_bias = sr_event.get("bias", "NEUTRAL")
    if event in ("BREAKOUT", "REVERSAL") and ev_bias == "BULLISH":
        score += 1.5
        risks.append(f"S/R event: {sr_event.get('event_label', 'bullish breakout/reversal')}")
    elif event in ("BREAKDOWN", "FAKEOUT") and ev_bias == "BEARISH":
        score -= 1.5
        risks.append(f"S/R event: {sr_event.get('event_label', 'bearish breakdown/fakeout')}")
    elif event == "RANGE":
        sup = sr_event.get("support")
        res = sr_event.get("resistance")
        if sup and res:
            mid = (float(sup) + float(res)) / 2
            if price > mid * 1.01:
                risks.append("Range compression — testing resistance side of range (breakout watch).")
                score += 0.5
            elif price < mid * 0.99:
                risks.append("Range compression — testing support side of range (breakdown watch).")
                score -= 0.5

    for p in chart_patterns[:3]:
        pname = p.get("name") or p.get("pattern") or "Pattern"
        ptype = pname.lower()
        pbias = (p.get("bias") or "").lower()
        rel = p.get("reliability", "")
        if pbias == "bullish" or "bull" in ptype or "inverse" in ptype or "cup" in ptype:
            score += 0.8
            risks.append(f"Pattern: {pname} ({rel}) — bullish completion / break-up risk.")
        elif pbias == "bearish" or "bear" in ptype or "head" in ptype or "double top" in ptype:
            score -= 0.8
            risks.append(f"Pattern: {pname} ({rel}) — bearish completion / break-down risk.")

    for c in candles[:2]:
        cbias = (c.get("bias") or c.get("type") or "").lower()
        cname = c.get("name") or "Candle"
        if "bull" in cbias:
            score += 0.4
            risks.append(f"Candle: {cname} — bullish reversal / continuation.")
        elif "bear" in cbias:
            score -= 0.4
            risks.append(f"Candle: {cname} — bearish reversal / continuation.")

    if score >= 1.5:
        direction = "bullish"
        label = "Bullish — structure/pattern favors upside break"
    elif score <= -1.5:
        direction = "bearish"
        label = "Bearish — structure/pattern favors downside break"
    else:
        direction = "neutral"
        label = "Neutral — no dominant break bias; wait for confirmation"

    return {
        "direction": direction,
        "label": label,
        "score": round(score, 2),
        "risks": risks[:6],
    }


def _compute_stand(
    levels: dict,
    tl_break: dict,
    pattern_risk: dict,
    sr_event: dict,
    consolidation: dict | None = None,
    supply_demand: dict | None = None,
) -> dict[str, Any]:
    """Overall bullish / bearish / neutral stand."""
    score = float(pattern_risk.get("score", 0))
    conf = 45
    notes: list[str] = []

    dist_s = None
    dist_r = None
    price = levels.get("price")
    if price and levels.get("s1"):
        dist_s = (price - levels["s1"]) / price * 100
    if price and levels.get("r1"):
        dist_r = (levels["r1"] - price) / price * 100

    if dist_s is not None and dist_s < 1.2:
        score += 0.5
    if dist_r is not None and dist_r < 1.2:
        score -= 0.5

    cons = consolidation or {}
    if cons.get("is_consolidating"):
        score += float(cons.get("score", 0))
        conf += 10
        notes.append(cons.get("label", ""))

    sd = supply_demand or {}
    score += float(sd.get("score", 0))
    if sd.get("active_zone") in ("demand", "supply"):
        conf += int(sd.get("confidence_boost", 6))
        if sd.get("label"):
            notes.append(sd["label"])

    imm = tl_break.get("imminent_direction")
    if imm == "bullish":
        score += 2.0
        conf += 12
    elif imm == "bearish":
        score -= 2.0
        conf += 12
    elif imm == "mixed":
        score *= 0.5

    if sr_event.get("bias") == "BULLISH":
        score += 1.2
        conf += int(sr_event.get("confidence", 0) * 0.15)
    elif sr_event.get("bias") == "BEARISH":
        score -= 1.2
        conf += int(sr_event.get("confidence", 0) * 0.15)

    conf = int(min(92, max(38, conf + abs(score) * 8)))

    if score >= 2.0:
        stand, verdict = "BULLISH", "BUY"
    elif score <= -2.0:
        stand, verdict = "BEARISH", "SELL"
    else:
        stand, verdict = "NEUTRAL", "HOLD"

    action = pattern_risk.get("label", "")
    if notes:
        action = f"{notes[0]} {' | '.join(notes[1:2])}"[:240]
    if tl_break.get("summary"):
        action = f"{action} {tl_break['summary']}"[:240]

    return {
        "stand": stand,
        "verdict": verdict,
        "confidence": conf,
        "score": round(score, 2),
        "action": action,
        "dist_support_pct": round(dist_s, 2) if dist_s is not None else None,
        "dist_resistance_pct": round(dist_r, 2) if dist_r is not None else None,
        "consolidation_note": cons.get("label"),
        "supply_demand_note": sd.get("label"),
    }


def _fmt(val: float | None, currency: str = "₹") -> str:
    if val is None:
        return "—"
    if currency == "$":
        return f"${val:,.4f}" if val < 1000 else f"${val:,.2f}"
    return f"₹{val:,.2f}"


def _fmt_pct(pct: float | None, *, is_support: bool) -> str:
    if pct is None:
        return "—"
    if is_support:
        return f"-{pct:.2f}% below LTP"
    return f"+{pct:.2f}% above LTP"


def _level_pct_dist(price: float, level: float | None, *, is_support: bool) -> float | None:
    if level is None or price <= 0:
        return None
    if is_support:
        return round(max(0.0, (price - level) / price * 100), 2)
    return round(max(0.0, (level - price) / price * 100), 2)


def _enrich_levels_with_pct(levels: dict[str, float | None]) -> dict[str, Any]:
    price = float(levels.get("price") or 0)
    out = dict(levels)
    out["s1_pct"] = _level_pct_dist(price, levels.get("s1"), is_support=True)
    out["s2_pct"] = _level_pct_dist(price, levels.get("s2"), is_support=True)
    out["r1_pct"] = _level_pct_dist(price, levels.get("r1"), is_support=False)
    out["r2_pct"] = _level_pct_dist(price, levels.get("r2"), is_support=False)
    return out


def _bar_as_of(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "—"
    if "datetime" in df.columns:
        dt = df["datetime"].iloc[-1]
        if hasattr(dt, "strftime"):
            return dt.strftime("%Y-%m-%d %H:%M")
        return str(dt)
    idx = df.index[-1]
    if hasattr(idx, "strftime"):
        return idx.strftime("%Y-%m-%d %H:%M")
    return str(idx)


def _volume_bias(df: pd.DataFrame, vol_period: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {
        "bias": "NEUTRAL",
        "vol_ratio": 1.0,
        "note": "Volume data unavailable.",
    }
    if df is None or df.empty or "volume" not in df.columns:
        return out
    vol = df["volume"].astype(float)
    if vol.iloc[-vol_period:].sum() <= 0:
        return out
    vol_ma = float(vol.rolling(vol_period).mean().iloc[-1])
    curr_vol = float(vol.iloc[-1])
    vol_ratio = round(curr_vol / vol_ma, 2) if vol_ma > 0 else 1.0
    close = df["close"].values.astype(float)
    open_ = df["open"].values.astype(float)
    last_green = close[-1] >= open_[-1]
    prev_green = close[-2] >= open_[-2] if len(close) > 1 else last_green
    rising_vol = vol_ratio >= 1.15
    if last_green and rising_vol:
        bias, note = "BULLISH", f"Up bar on {vol_ratio:.2f}× avg volume — buying pressure."
    elif not last_green and rising_vol:
        bias, note = "BEARISH", f"Down bar on {vol_ratio:.2f}× avg volume — selling pressure."
    elif last_green and prev_green:
        bias, note = "MILD BULLISH", f"Green closes; volume {vol_ratio:.2f}× average."
    elif not last_green and not prev_green:
        bias, note = "MILD BEARISH", f"Red closes; volume {vol_ratio:.2f}× average."
    else:
        bias, note = "NEUTRAL", f"Mixed tape; volume {vol_ratio:.2f}× average."
    return {"bias": bias, "vol_ratio": vol_ratio, "note": note}


def _rsi_bias(rsi_data: dict) -> dict[str, Any]:
    rsi = float(rsi_data.get("current_rsi", 50))
    if rsi_data.get("bullish_divergence"):
        return {
            "bias": "BULLISH",
            "rsi": rsi,
            "note": f"RSI {rsi:.1f} — bullish divergence (reversal up potential).",
        }
    if rsi_data.get("bearish_divergence"):
        return {
            "bias": "BEARISH",
            "rsi": rsi,
            "note": f"RSI {rsi:.1f} — bearish divergence (reversal down potential).",
        }
    zone = rsi_data.get("zone", "NEUTRAL")
    if zone == "OVERSOLD":
        return {"bias": "BULLISH", "rsi": rsi, "note": f"RSI {rsi:.1f} — oversold zone."}
    if zone == "OVERBOUGHT":
        return {"bias": "BEARISH", "rsi": rsi, "note": f"RSI {rsi:.1f} — overbought zone."}
    if rsi >= 55:
        return {"bias": "MILD BULLISH", "rsi": rsi, "note": f"RSI {rsi:.1f} — bullish momentum."}
    if rsi <= 45:
        return {"bias": "MILD BEARISH", "rsi": rsi, "note": f"RSI {rsi:.1f} — bearish momentum."}
    return {"bias": "NEUTRAL", "rsi": rsi, "note": f"RSI {rsi:.1f} — neutral."}


def _price_near_level(price: float, level: float | None, tol_pct: float = 2.5) -> bool:
    if level is None or price <= 0:
        return False
    return abs(price - level) / price * 100 <= tol_pct


def _patterns_near_sr(
    levels: dict,
    candles: list[dict],
    charts: list[dict],
    *,
    tol_pct: float = 2.5,
) -> list[dict[str, Any]]:
    """Candlestick/chart patterns forming near immediate S/R zones."""
    price = float(levels.get("price") or 0)
    zones: list[tuple[str, float, str]] = []
    for tag, key, zone in (
        ("S1", "s1", "support"),
        ("S2", "s2", "support"),
        ("R1", "r1", "resistance"),
        ("R2", "r2", "resistance"),
    ):
        lv = levels.get(key)
        if lv is not None:
            zones.append((tag, float(lv), zone))

    near_tags = [
        tag for tag, lv, _ in zones if _price_near_level(price, lv, tol_pct=tol_pct)
    ]
    if not near_tags and zones:
        nearest = min(zones, key=lambda z: abs(price - z[1]))
        near_tags = [nearest[0]]

    out: list[dict[str, Any]] = []
    for c in candles[:6]:
        bias = (c.get("bias") or "NEUTRAL").upper()
        out.append({
            "kind": "Candlestick",
            "name": c.get("name", "Pattern"),
            "bias": bias,
            "reliability": c.get("reliability", "—"),
            "near": ", ".join(near_tags) if near_tags else "price zone",
            "detail": c.get("description", ""),
        })

    for p in charts[:4]:
        bias = (p.get("bias") or "NEUTRAL").upper()
        neck = p.get("neckline")
        near = near_tags[:]
        if neck is not None:
            for tag, lv, zone in zones:
                if _price_near_level(float(neck), lv, tol_pct=tol_pct * 1.5):
                    if tag not in near:
                        near.append(tag)
        out.append({
            "kind": "Chart",
            "name": p.get("name", "Pattern"),
            "bias": bias,
            "reliability": p.get("reliability", "—"),
            "near": ", ".join(near) if near else "structure zone",
            "detail": p.get("notes") or p.get("description") or "",
        })
    return out[:8]


def _dedupe_prices(candidates: list[float], price: float) -> list[float]:
    """Merge nearby prices (float-safe) into one ordered unique list."""
    tol = max(price * 0.003, 0.05)
    unique: list[float] = []
    for raw in candidates:
        if raw is None:
            continue
        p = float(raw)
        if np.isnan(p):
            continue
        if not any(abs(p - u) <= tol for u in unique):
            unique.append(p)
    return unique


def _pick_two_levels(
    candidates: list[float],
    price: float,
    *,
    is_support: bool,
    fallback_near: float | None,
    fallback_far: float | None,
) -> tuple[float | None, float | None]:
    """Pick nearest + second nearest support (below) or resistance (above) LTP."""
    ordered = (
        sorted([p for p in candidates if p < price], reverse=True)
        if is_support
        else sorted(p for p in candidates if p > price)
    )
    l1 = ordered[0] if ordered else fallback_near
    l2 = ordered[1] if len(ordered) >= 2 else fallback_far
    tol = max(price * 0.003, 0.05)
    if l1 is not None and l2 is not None and abs(l2 - l1) <= tol:
        l2 = fallback_far if fallback_far is not None and abs(fallback_far - l1) > tol else None
    if l1 is None:
        l1 = fallback_near
    if l2 is None:
        l2 = fallback_far
    if l1 is not None and l2 is not None and abs(l2 - l1) <= tol:
        l2 = None
    return l1, l2


def _build_four_sr_levels(df: pd.DataFrame, sr_window: int = 5) -> dict[str, float | None]:
    """Two supports (S1, S2) below and two resistances (R1, R2) above last close."""
    price = float(df["close"].iloc[-1])
    two_lvl = calculate_two_level_sr(df)
    sr_clusters = detect_support_resistance(df, window=sr_window, num_levels=4)

    support_candidates = _dedupe_prices(
        [two_lvl.get("s1"), two_lvl.get("s2")]
        + [s.get("price") for s in (sr_clusters.get("supports") or [])],
        price,
    )
    resistance_candidates = _dedupe_prices(
        [two_lvl.get("r1"), two_lvl.get("r2")]
        + [r.get("price") for r in (sr_clusters.get("resistances") or [])],
        price,
    )

    s1, s2 = _pick_two_levels(
        support_candidates,
        price,
        is_support=True,
        fallback_near=two_lvl.get("s1"),
        fallback_far=two_lvl.get("s2"),
    )
    r1, r2 = _pick_two_levels(
        resistance_candidates,
        price,
        is_support=False,
        fallback_near=two_lvl.get("r1"),
        fallback_far=two_lvl.get("r2"),
    )
    # Always surface two levels per side — use swing-analysis fallbacks when clustering is sparse.
    if s1 is None and two_lvl.get("s1") is not None:
        s1 = float(two_lvl["s1"])
    if s2 is None and two_lvl.get("s2") is not None:
        s2 = float(two_lvl["s2"])
    if r1 is None and two_lvl.get("r1") is not None:
        r1 = float(two_lvl["r1"])
    if r2 is None and two_lvl.get("r2") is not None:
        r2 = float(two_lvl["r2"])
    return {"price": price, "s1": s1, "s2": s2, "r1": r1, "r2": r2}


def _sr_levels_for_chart(levels: dict) -> dict:
    """Support/resistance dict for charts — skip missing prices."""
    supports = [{"price": levels[k]} for k in ("s1", "s2") if levels.get(k) is not None]
    resistances = [{"price": levels[k]} for k in ("r1", "r2") if levels.get(k) is not None]
    return {"supports": supports, "resistances": resistances}


def run_find_sr_analysis(
    df: pd.DataFrame,
    timeframe: str,
    sr_window: int = 5,
) -> dict[str, Any]:
    """Full S/R + trendline + structure analysis for one ticker × timeframe."""
    levels = _enrich_levels_with_pct(_build_four_sr_levels(df, sr_window=sr_window))
    price = levels["price"]

    trendlines = detect_trendlines(df, window=sr_window)
    tl_break = analyze_trendline_break(df, trendlines)
    structure = classify_swing_structure(df.tail(min(80, len(df))), window=sr_window)
    sr_event = analyze_sr_breakout(df, timeframe=timeframe)
    charts = detect_chart_patterns(df, window=sr_window)
    candles = detect_candlestick_patterns(df)
    pattern_risk = _pattern_break_risk(df, structure, sr_event, charts, candles)
    rsi_raw = analyze_rsi(df)
    rsi = _rsi_bias(rsi_raw)
    volume = _volume_bias(df)
    patterns_near = _patterns_near_sr(levels, candles, charts)
    as_of = _bar_as_of(df)
    ema = analyze_ema_crossovers(df)
    ema_ladder = analyze_ema_ladder(df, timeframe=timeframe)
    consolidation = _analyze_consolidation_near_sr(df, levels)
    supply_demand = _analyze_supply_demand_zones(df, sr_window=sr_window)
    stand = _compute_stand(
        levels, tl_break, pattern_risk, sr_event, consolidation, supply_demand,
    )

    return {
        "current_price": price,
        "as_of": as_of,
        "levels": levels,
        "support_resistance": _sr_levels_for_chart(levels),
        "trendlines": trendlines,
        "trendline_break": tl_break,
        "structure": structure,
        "sr_breakout": sr_event,
        "chart_patterns": charts,
        "candlestick_patterns": candles,
        "patterns_near_sr": patterns_near,
        "pattern_break": pattern_risk,
        "consolidation": consolidation,
        "supply_demand": supply_demand,
        "rsi": rsi,
        "volume": volume,
        "ema": ema,
        "ema_ladder": ema_ladder,
        "stand": stand,
        "timeframe": timeframe,
    }


def _ema_stack_short(ladder: dict | None) -> str:
    if not ladder or ladder.get("insufficient"):
        return "—"
    ac = ladder.get("above_count", 0)
    total = len([e for e in ladder.get("emas", []) if not e.get("unavailable")])
    if total == 0:
        return "—"
    return f"{ac}/{total} above"


def _ema_lists_text(ladder: dict | None) -> tuple[str, str]:
    if not ladder or ladder.get("insufficient"):
        return "—", "—"
    above = ", ".join(e["label"] for e in ladder.get("support_emas", [])) or "None"
    below = ", ".join(e["label"] for e in ladder.get("resistance_emas", [])) or "None"
    return above, below


def build_find_sr_ai_prompt(
    symbol: str,
    timeframe: str,
    market: str,
    analysis: dict,
    currency: str,
) -> str:
    lv = analysis["levels"]
    stn = analysis["stand"]
    tl = analysis["trendline_break"]
    pat = analysis["pattern_break"]
    struct = analysis["structure"]
    sr_ev = analysis["sr_breakout"]

    lines = [
        "=== FIND SUPPORT & RESISTANCE ===",
        f"Symbol: {symbol}",
        f"Timeframe: {timeframe}",
        f"Market: {market}",
        f"As of: {analysis.get('as_of', '—')}",
        f"Price: {currency}{analysis['current_price']:,.4f}",
        "",
        "=== IMMEDIATE LEVELS ===",
    ]
    for tag, key, pct_key, is_sup in (
        ("S1", "s1", "s1_pct", True),
        ("S2", "s2", "s2_pct", True),
        ("R1", "r1", "r1_pct", False),
        ("R2", "r2", "r2_pct", False),
    ):
        val = lv.get(key)
        pct = lv.get(pct_key)
        if val is not None:
            lines.append(f"{tag}: {currency}{val:,.4f} ({_fmt_pct(pct, is_support=is_sup)})")
        else:
            lines.append(f"{tag}: N/A")
    vol = analysis.get("volume") or {}
    rsi = analysis.get("rsi") or {}
    lines.extend([
        "",
        "=== VOLUME & RSI ===",
        f"Volume: {vol.get('bias', '—')} · {vol.get('note', '')}",
        f"RSI: {rsi.get('bias', '—')} · {rsi.get('note', '')}",
        "",
        "=== PATTERNS NEAR S/R ===",
    ])
    for p in analysis.get("patterns_near_sr") or []:
        lines.append(
            f"- {p.get('kind')} {p.get('name')} near {p.get('near')} — {p.get('bias')} ({p.get('reliability')})"
        )
    if not analysis.get("patterns_near_sr"):
        lines.append("- No prominent pattern at immediate S/R.")
    ladder = analysis.get("ema_ladder") or {}
    ema = analysis.get("ema") or {}
    above_emas, below_emas = _ema_lists_text(ladder)
    lines.extend([
        "",
        "=== EMA POSITION (5 · 9 · 20 · 50 · 200) ===",
        ladder.get("stack_summary", "N/A").replace("**", ""),
        f"Price ABOVE (support EMAs): {above_emas}",
        f"Price BELOW (resistance EMAs): {below_emas}",
        f"EMA stack 9/21/50: {ema.get('ema_stack', 'MIXED')}",
        f"Price vs EMA 200: {ema.get('price_vs_ema200', 'N/A')}",
    ])
    ns, nr = ladder.get("nearest_support"), ladder.get("nearest_resistance")
    if ns:
        lines.append(
            f"Nearest support EMA: {ns['label']} at {currency}{ns['value']:,.4f} ({ns.get('dist_text', '')})"
        )
    if nr:
        lines.append(
            f"Nearest resistance EMA: {nr['label']} at {currency}{nr['value']:,.4f} ({nr.get('dist_text', '')})"
        )
    cons = analysis.get("consolidation") or {}
    sd = analysis.get("supply_demand") or {}
    lines.extend([
        "",
        "=== CONSOLIDATION AT S/R ===",
        f"Consolidating: {cons.get('is_consolidating', False)} · Bias: {cons.get('bias', '—')}",
        cons.get("label", "—"),
        "Rule: consolidation near resistance → bullish; near support → bearish.",
        "",
        "=== SUPPLY / DEMAND (HISTORY) ===",
        f"Active zone: {sd.get('active_zone', '—')} · Bias: {sd.get('bias', '—')}",
        sd.get("label", "—"),
    ])
    for z in (sd.get("demand_zones") or [])[:3]:
        lines.append(
            f"- Demand {z['bottom']:.4g}–{z['top']:.4g} · {z['strength']} · {z['touches']} touches"
        )
    for z in (sd.get("supply_zones") or [])[:3]:
        lines.append(
            f"- Supply {z['bottom']:.4g}–{z['top']:.4g} · {z['strength']} · {z['touches']} touches"
        )
    lines.extend([
        "",
        "=== QUANT STAND ===",
        f"Stance: {stn.get('stand')} ({stn.get('confidence')}% confidence)",
        f"Verdict: {stn.get('verdict')}",
        f"Action: {stn.get('action')}",
        "",
        "=== TRENDLINE BREAK ===",
        tl.get("summary", ""),
        f"Imminent direction: {tl.get('imminent_direction') or 'none'}",
        "",
        "=== STRUCTURE / PATTERN ===",
        f"Structure: {struct.get('structure_name')} — {struct.get('structure_detail')}",
        f"Pattern bias: {pat.get('label')}",
    ])
    for r in pat.get("risks") or []:
        lines.append(f"- {r}")
    lines.extend([
        "",
        "=== S/R EVENT ===",
        f"{sr_ev.get('event_label')} · {sr_ev.get('bias')} · {sr_ev.get('confidence')}%",
        sr_ev.get("detail", ""),
        "",
        "Synthesize into one trade stance: which level breaks next, trendline implication, and BUY/SELL/HOLD.",
    ])
    return "\n".join(lines)


def summarize_find_sr(analysis: dict, symbol: str, timeframe: str) -> dict:
    stn = analysis.get("stand") or {}
    lv = analysis.get("levels") or {}
    tl = analysis.get("trendline_break") or {}
    score = 5.0 + (stn.get("score", 0) * 0.4)
    score = max(1.0, min(10.0, score))
    verdict = stn.get("verdict", "HOLD")
    ladder = analysis.get("ema_ladder") or {}
    above_emas, below_emas = _ema_lists_text(ladder)
    cons = analysis.get("consolidation") or {}
    sd = analysis.get("supply_demand") or {}
    reasons = [
        f"As of {analysis.get('as_of', '—')}",
        f"S1 {_fmt(lv.get('s1'))} ({_fmt_pct(lv.get('s1_pct'), is_support=True)}) · "
        f"S2 {_fmt(lv.get('s2'))} ({_fmt_pct(lv.get('s2_pct'), is_support=True)})",
        f"R1 {_fmt(lv.get('r1'))} ({_fmt_pct(lv.get('r1_pct'), is_support=False)}) · "
        f"R2 {_fmt(lv.get('r2'))} ({_fmt_pct(lv.get('r2_pct'), is_support=False)})",
        f"Consolidation: {cons.get('bias', '—')} — {(cons.get('label') or '')[:90]}",
        f"Supply/Demand: {sd.get('active_zone', '—')} · {sd.get('bias', '—')} — {(sd.get('label') or '')[:90]}",
        f"Volume {(analysis.get('volume') or {}).get('bias', '—')} · "
        f"RSI {(analysis.get('rsi') or {}).get('bias', '—')}",
        f"EMAs above: {above_emas} · below: {below_emas}",
        f"Trendline: {tl.get('imminent_direction') or 'none'} — {(tl.get('summary') or '')[:80]}",
        f"Structure: {(analysis.get('structure') or {}).get('structure_name', 'N/A')}",
    ]
    return make_summary(
        ticker=symbol,
        timeframe=timeframe,
        tab="Find S/R",
        score=round(score, 1),
        verdict=verdict,
        action=(stn.get("action") or "")[:220],
        summary=f"{stn.get('stand', 'NEUTRAL')} ({stn.get('confidence', 0)}% conf) on {timeframe}.",
        reasons=reasons,
    )


def _render_levels_metrics(lv: dict, currency: str) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("LTP", _fmt(lv.get("price"), currency))
    c2.metric("S1", _fmt(lv.get("s1"), currency), _fmt_pct(lv.get("s1_pct"), is_support=True))
    c3.metric("S2", _fmt(lv.get("s2"), currency), _fmt_pct(lv.get("s2_pct"), is_support=True))
    c4.metric("R1", _fmt(lv.get("r1"), currency), _fmt_pct(lv.get("r1_pct"), is_support=False))
    c5.metric("R2", _fmt(lv.get("r2"), currency), _fmt_pct(lv.get("r2_pct"), is_support=False))


def _render_patterns_near_sr(patterns: list[dict]) -> None:
    st.markdown("#### Patterns near S/R")
    if not patterns:
        st.caption("No prominent candlestick or chart pattern at immediate S/R on this timeframe.")
        return
    rows = [{
        "Type": p.get("kind"),
        "Pattern": p.get("name"),
        "Bias": p.get("bias"),
        "Near": p.get("near"),
        "Reliability": p.get("reliability"),
    } for p in patterns]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    for p in patterns[:4]:
        if p.get("detail"):
            st.caption(f"{p.get('name')}: {p.get('detail')}")


def _render_volume_rsi(volume: dict, rsi: dict) -> None:
    v1, v2 = st.columns(2)
    with v1:
        st.metric("Volume bias", volume.get("bias", "—"), f"{volume.get('vol_ratio', 1):.2f}× avg")
        st.caption(volume.get("note", ""))
    with v2:
        st.metric("RSI bias", rsi.get("bias", "—"), f"RSI {rsi.get('rsi', '—')}")
        st.caption(rsi.get("note", ""))


def _render_consolidation_supply_demand(
    consolidation: dict,
    supply_demand: dict,
    currency: str,
) -> None:
    st.markdown("#### Consolidation & supply/demand")
    st.caption(
        "Consolidation **under resistance → bullish** (breakout base). "
        "**Above support → bearish** (breakdown flag). "
        "Zones use historical swing rejections (supply) and bounces (demand)."
    )
    c1, c2 = st.columns(2)
    with c1:
        cons = consolidation or {}
        bias = cons.get("bias", "—")
        delta = f"{cons.get('range_pct', '—')}% range" if cons.get("range_pct") is not None else None
        st.metric(
            "Consolidation",
            "Yes" if cons.get("is_consolidating") else "No",
            delta=f"{bias} · near {cons.get('near_level', '—')}" if cons.get("is_consolidating") else delta,
        )
        label = (cons.get("label") or "—").replace("**", "")
        st.caption(label)
    with c2:
        sd = supply_demand or {}
        st.metric(
            "Active zone",
            sd.get("active_zone", "—").replace("_", " ").title(),
            delta=f"{sd.get('bias', '—')} bias",
        )
        st.caption((sd.get("label") or "—").replace("**", ""))

    rows: list[dict[str, str]] = []
    for z in (supply_demand or {}).get("demand_zones") or []:
        rows.append({
            "Zone": "Demand",
            "Range": f"{_fmt(z.get('bottom'), currency)} – {_fmt(z.get('top'), currency)}",
            "Strength": z.get("strength", "—"),
            "Touches": str(z.get("touches", 0)),
            "Dist from LTP": f"{z.get('dist_pct', 0):.2f}% below",
        })
    for z in (supply_demand or {}).get("supply_zones") or []:
        rows.append({
            "Zone": "Supply",
            "Range": f"{_fmt(z.get('bottom'), currency)} – {_fmt(z.get('top'), currency)}",
            "Strength": z.get("strength", "—"),
            "Touches": str(z.get("touches", 0)),
            "Dist from LTP": f"{z.get('dist_pct', 0):.2f}% above",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_fsr_mtf_levels_table(items: list[tuple[str, dict]], currency: str) -> None:
    """Per-timeframe S1/S2/R1/R2 summary for one ticker."""
    rows: list[dict[str, str]] = []
    for _, d in items:
        tf = d.get("timeframe", "—")
        if "error" in d:
            rows.append({
                "Timeframe": tf,
                "S1": "—",
                "S2": "—",
                "R1": "—",
                "R2": "—",
                "Stance": "ERROR",
            })
            continue
        lv = (d.get("analysis") or {}).get("levels") or {}
        stn = (d.get("analysis") or {}).get("stand") or {}
        vol = (d.get("analysis") or {}).get("volume") or {}
        rsi = (d.get("analysis") or {}).get("rsi") or {}
        ladder = (d.get("analysis") or {}).get("ema_ladder") or {}
        cons = (d.get("analysis") or {}).get("consolidation") or {}
        sd = (d.get("analysis") or {}).get("supply_demand") or {}
        rows.append({
            "Timeframe": tf,
            "As of": (d.get("analysis") or {}).get("as_of", "—"),
            "S1": f"{_fmt(lv.get('s1'), currency)} ({_fmt_pct(lv.get('s1_pct'), is_support=True)})",
            "S2": f"{_fmt(lv.get('s2'), currency)} ({_fmt_pct(lv.get('s2_pct'), is_support=True)})",
            "R1": f"{_fmt(lv.get('r1'), currency)} ({_fmt_pct(lv.get('r1_pct'), is_support=False)})",
            "R2": f"{_fmt(lv.get('r2'), currency)} ({_fmt_pct(lv.get('r2_pct'), is_support=False)})",
            "Consol.": cons.get("bias", "—") if cons.get("is_consolidating") else "—",
            "S/D Zone": f"{sd.get('active_zone', '—')} ({sd.get('bias', '—')})",
            "EMAs": _ema_stack_short(ladder),
            "Volume": vol.get("bias", "—"),
            "RSI": rsi.get("bias", "—"),
            "Stance": f"{stn.get('stand', '—')} ({stn.get('confidence', 0)}%)",
        })
    if rows:
        st.markdown("#### S/R levels by timeframe")
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


def _stand_badge(stand: str) -> str:
    s = (stand or "").upper()
    if s == "BULLISH":
        return "🟢"
    if s == "BEARISH":
        return "🔴"
    return "🟡"


def render_find_sr_tab() -> None:
    st.markdown("<h1>📍 Find Support & Resistance</h1>", unsafe_allow_html=True)
    st.write(
        "Select **Groww · US · Crypto** tickers and **one or more timeframes**, then click **Find** to get "
        "**two immediate supports (S1, S2)** and **two resistances (R1, R2)** with **price and % from LTP**, "
        "which **EMAs (5/9/20/50/200)** price is above or below, **consolidation** at S/R "
        "(bullish under resistance · bearish above support), **supply/demand zones** from history, "
        "candlestick/chart patterns near S/R, **volume** and **RSI** bias, an annotated **chart**, "
        "and the **bar date/time** for each result."
    )

    provider, model, api_key = render_ai_config(
        "find_sr",
        caption="AI refines levels, break probability, and next-move prediction.",
    )

    m1, m2 = st.columns(2)
    with m1:
        fsr_market = render_market_selectbox("fsr_market")
    with m2:
        fsr_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="fsr_exchange")
            if is_india_market(fsr_market)
            else "NSE"
        )

    st.markdown("### 📊 Tickers")
    is_crypto = is_crypto_market(fsr_market)
    currency = market_currency(fsr_market)

    if is_crypto:
        fsr_tickers = render_coindcx_ticker_selection("fsr")
    else:
        fsr_tickers = render_equity_index_ticker_selection(fsr_market, "fsr")

    st.markdown("### ⏱️ Timeframes (duration)")
    tfc1, tfc2, tfc3 = st.columns(3)
    with tfc1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        fsr_tfs = render_ta_multiselect_timeframes(
            "fsr",
            ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"],
            legacy_default=["15m", "1h", "1d"],
            label="Timeframes",
        )
    with tfc2:
        fsr_candles = st.slider("Candle history", 80, 500, 200, 20, key="fsr_candles")
    with tfc3:
        fsr_sr_win = st.slider("Swing window", 3, 12, 5, key="fsr_sr_win")

    use_ai_auto = st.checkbox(
        "Auto-run AI on each result (uses API quota)",
        value=False,
        key="fsr_ai_auto",
    )

    total = len(fsr_tickers) * len(fsr_tfs)
    fsr_actionable_only = render_ta_screener_options("fsr")
    st.caption(f"🧮 **{total}** ticker × timeframe combinations")
    run_btn = st.button(
        "🔎 FIND",
        type="primary",
        width='stretch',
        key="fsr_run",
    )

    if run_btn:
        if not fsr_tickers or not fsr_tfs:
            st.error("Select at least one ticker and timeframe.")
            return
        results: dict[str, dict] = {}
        bar = st.progress(0, text="Scanning…")
        groww_token = get_active_groww_token()
        i = 0
        for tick in fsr_tickers:
            for tf in fsr_tfs:
                i += 1
                bar.progress(i / total, text=f"{tick} | {tf}")
                try:
                    df = fetch_data_for_gap_scan(
                        tick, tf, fsr_market, groww_token, fsr_exchange, limit=fsr_candles,
                    )
                    if df.empty or len(df) < 25:
                        results[f"{tick}|{tf}"] = {
                            "error": f"Insufficient data ({len(df)} bars).",
                            "symbol": tick,
                            "timeframe": tf,
                        }
                        continue
                    analysis = run_find_sr_analysis(df, tf, sr_window=fsr_sr_win)
                    ai_report = None
                    if use_ai_auto and api_key:
                        prompt = build_find_sr_ai_prompt(
                            tick, tf, fsr_market, analysis, currency,
                        )
                        ai_report = call_ai_report(
                            prompt, FIND_SR_AI_SYSTEM, provider, model, api_key,
                        )
                    results[f"{tick}|{tf}"] = {
                        "df": df,
                        "analysis": analysis,
                        "symbol": tick,
                        "timeframe": tf,
                        "ai_report": ai_report,
                    }
                except Exception as exc:
                    results[f"{tick}|{tf}"] = {
                        "error": str(exc)[:200],
                        "symbol": tick,
                        "timeframe": tf,
                    }
                time.sleep(0.04)
        bar.empty()
        st.session_state.fsr_results = results
        st.session_state.fsr_results_market = fsr_market
        st.session_state.fsr_results_is_crypto = is_crypto
        st.session_state.fsr_last_scan = time.strftime("%H:%M:%S")

    results = st.session_state.get("fsr_results", {})
    market_disp = st.session_state.get("fsr_results_market", fsr_market)
    is_crypto = st.session_state.get("fsr_results_is_crypto", is_crypto)
    currency = market_currency(market_disp)

    if not results:
        st.info("Select market, tickers, and timeframes, then click **FIND**.")
        return

    last_scan = st.session_state.get("fsr_last_scan")
    if last_scan:
        st.caption(f"Last scan: {last_scan}")

    st.markdown("---")
    digest = []
    for d in results.values():
        if "error" in d:
            digest.append(summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Find S/R"))
        else:
            digest.append(summarize_find_sr(d["analysis"], d["symbol"], d["timeframe"]))
    digest = render_ta_screener_results(
        digest,
        title="🧭 Find S/R Screener",
        strategy_label="S/R break",
        actionable_only=fsr_actionable_only,
    )

    if not api_key:
        st.info("💡 Add `GEMINI_API_KEY` or `GROQ_API_KEY` in `.env` for **AI View** on each result.")

    tickers_seen: list[str] = []
    for d in results.values():
        s = d.get("symbol")
        if s and s not in tickers_seen:
            tickers_seen.append(s)

    for ti, ticker in enumerate(tickers_seen):
        if not should_show_ticker_in_screener(ticker, digest, actionable_only=fsr_actionable_only):
            continue
        items = [(k, v) for k, v in results.items() if v.get("symbol") == ticker]
        summaries = [
            summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Find S/R")
            if "error" in d
            else summarize_find_sr(d["analysis"], d["symbol"], d["timeframe"])
            for _, d in items
        ]
        with st.expander(
            ticker_section_label(ticker, summaries),
            expanded=should_expand_ticker(ti),
        ):
            _render_fsr_mtf_levels_table(items, currency)

            if api_key and len(items) > 1:
                mtf_ticker_button("fsr", ticker)

                def _mtf_prompt(items=items, m=market_disp, t=ticker, cur=currency):
                    sections = []
                    for _, d in items:
                        if "error" in d:
                            sections.append(f"{d['timeframe']}: ERROR — {d['error']}")
                        else:
                            sections.append(build_find_sr_ai_prompt(
                                t, d["timeframe"], m, d["analysis"], cur,
                            ))
                    return combine_timeframe_sections(
                        "FIND SUPPORT & RESISTANCE — MTF", t, sections, market=m,
                    )

                render_mtf_ai_view_report(
                    "fsr", ticker, _mtf_prompt, MTF_AI_SYSTEM,
                    provider, model, api_key, len(items),
                )

            for key, d in items:
                tf = d.get("timeframe", "")
                if "error" in d:
                    st.warning(f"**{tf}** — {d['error']}")
                    continue

                analysis = d["analysis"]
                stn = analysis["stand"]
                lv = analysis["levels"]
                tl = analysis["trendline_break"]
                pat = analysis["pattern_break"]
                vol = analysis.get("volume") or {}
                rsi = analysis.get("rsi") or {}
                as_of = analysis.get("as_of", "—")

                with st.expander(
                    f"{_stand_badge(stn.get('stand'))} **{tf}** — "
                    f"{stn.get('stand')} ({stn.get('confidence')}%) · "
                    f"As of {as_of} · "
                    f"S1 {_fmt(lv.get('s1'), currency)} · R1 {_fmt(lv.get('r1'), currency)}",
                    expanded=(len(items) == 1),
                ):
                    st.caption(f"**Data as of:** {as_of} · **Timeframe:** {tf}")
                    render_run_summary(summarize_find_sr(analysis, ticker, tf))
                    render_strategy_mtf_panel(
                        symbol=ticker,
                        market=market_disp,
                        groww_token=get_active_groww_token(),
                        exchange=st.session_state.get("fsr_exchange", "NSE"),
                        primary_tf=tf,
                        strategy_direction=stn.get("stand"),
                    )
                    _render_levels_metrics(lv, currency)
                    _render_volume_rsi(vol, rsi)
                    _render_consolidation_supply_demand(
                        analysis.get("consolidation") or {},
                        analysis.get("supply_demand") or {},
                        currency,
                    )
                    _render_patterns_near_sr(analysis.get("patterns_near_sr") or [])

                    ema_ladder = analysis.get("ema_ladder") or {}
                    if not ema_ladder.get("insufficient"):
                        _render_ema_ladder_panel(ema_ladder, currency=currency, compact=True)

                    st.markdown(
                        f"**Stance:** {stn.get('stand')} · **Verdict:** {stn.get('verdict')} · "
                        f"**Confidence:** {stn.get('confidence')}%"
                    )
                    st.markdown(f"**Outlook:** {stn.get('action', '—')}")

                    st.markdown("#### Trendline break")
                    st.markdown(tl.get("summary", "—"))
                    if tl.get("imminent_direction"):
                        st.markdown(
                            f"**Imminent break bias:** {tl['imminent_direction'].upper()}"
                        )

                    st.markdown("#### Structure / pattern break risk")
                    st.markdown(f"**{pat.get('label', '—')}**")
                    for r in pat.get("risks") or []:
                        st.markdown(f"- {r}")

                    sr_ev = analysis.get("sr_breakout") or {}
                    if not sr_ev.get("insufficient"):
                        st.markdown(
                            f"**S/R event:** {sr_ev.get('event_label', '—')} · "
                            f"{sr_ev.get('bias', '—')} ({sr_ev.get('confidence', 0)}%)"
                        )

                    render_ta_structure_section(
                        df=d["df"],
                        symbol=ticker,
                        timeframe=tf,
                        currency=currency,
                        sr=analysis.get("support_resistance"),
                        trendlines=analysis.get("trendlines"),
                        ema=analysis.get("ema"),
                        ema_ladder=analysis.get("ema_ladder"),
                        sr_breakout=sr_ev,
                        compact=True,
                        chart_height=480,
                    )

                    struct = analysis.get("structure") or {}
                    if struct.get("structure_name"):
                        st.markdown(
                            f"**Swing structure:** {struct.get('structure_name')} — "
                            f"{struct.get('structure_detail', '')}"
                        )

                    if d.get("ai_report"):
                        st.markdown("#### 🤖 AI analysis")
                        st.markdown(d["ai_report"])

                    if api_key:
                        show_ai_view_block(
                            "fsr",
                            key,
                            ticker,
                            tf,
                            lambda d=d, t=ticker, tf=tf, m=market_disp, cur=currency: build_find_sr_ai_prompt(
                                t, tf, m, d["analysis"], cur,
                            ),
                            FIND_SR_AI_SYSTEM,
                            provider,
                            model,
                            api_key,
                            button_in_column=False,
                        )

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("find_sr")
