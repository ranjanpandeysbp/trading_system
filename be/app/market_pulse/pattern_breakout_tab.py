"""
pattern_breakout_tab.py
-----------------------
S/R, trendlines, breakout/breakdown/fakeout/reversal, retracement,
chart & candlestick patterns, trade plans with hold duration, and AI View.
"""

from __future__ import annotations

import re
import time

import numpy as np
import pandas as pd
from app.market_pulse.ai_view import (
    MTF_AI_SYSTEM,
    STANDARD_REPORT_FORMAT,
    combine_timeframe_sections,
    mtf_ticker_button,
    render_ai_config,
    render_mtf_ai_view_report,
    show_ai_view_block,
)
from app.market_pulse.demo_trading import render_demo_trade_panel
from app.market_pulse.env_config import api_key_env_hint
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.price_action import (
    _calc_atr,
    analyze_advanced_indicators,
    analyze_ema_crossovers,
    analyze_fibonacci,
    analyze_rsi,
    build_analysis_chart,
    detect_candlestick_patterns,
    detect_chart_patterns,
    detect_support_resistance,
    detect_trendlines,
    generate_trade_setups,
)
from app.market_pulse.sr_breakout import analyze_sr_breakout, render_sr_breakout_panel
from app.market_pulse.run_summary import (
    render_run_summary,
    summarize_error,
    summarize_mtf_aggregate,
    summarize_pattern_breakout,
)
from app.market_pulse.ta_screener_ui import (
    render_ta_screener_options,
    render_ta_screener_results,
    render_strategy_mtf_panel,
    should_show_ticker_in_screener,
)
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    GROWW_MARKET,
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
)


PATTERN_BREAKOUT_AI_SYSTEM = """You are an expert chart-pattern and support/resistance analyst for Indian equities (NSE/BSE) and crypto futures.

Focus on: S/R levels, trendlines, breakouts, breakdowns, fakeouts, reversals, Fibonacci retracements,
candlestick patterns, and classical formations (flags, H&S, double/M/W tops, cup & handle).

Be data-driven — cite exact prices from the input. If signals conflict or confidence is low, verdict must be AVOID.
For every BUY or SELL verdict you MUST specify:
- Expected holding duration (aligned with the timeframe)
- Green signs to stay in the trade
- Red flags to exit early
""" + STANDARD_REPORT_FORMAT

_HOLD_BY_TIMEFRAME = {
    "1m": ("15–45 minutes (scalp)", "Scalping"),
    "5m": ("1–3 hours (intraday)", "Intraday"),
    "15m": ("2–6 hours (intraday)", "Intraday"),
    "30m": ("4–12 hours (intraday)", "Intraday"),
    "1h": ("1–3 trading days", "Short swing"),
    "4h": ("3–10 trading days", "Swing"),
    "1d": ("1–4 weeks", "Swing / position"),
}


def estimate_hold_duration(timeframe: str, style: str = "") -> tuple[str, str]:
    """Return (human-readable hold window, trade style label)."""
    hold, default_style = _HOLD_BY_TIMEFRAME.get(timeframe, ("2–10 bars on this timeframe", "Swing"))
    trade_style = style or default_style
    if trade_style == "Scalping" and timeframe in ("1h", "4h", "1d"):
        hold = f"Shorter than typical — target quick mean-reversion ({hold})"
    return hold, trade_style


def _swing_points(df: pd.DataFrame, window: int = 5):
    highs, lows = [], []
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    for i in range(window, len(df) - window):
        if h[i] == max(h[i - window : i + window + 1]):
            highs.append((i, float(h[i])))
        if l[i] == min(l[i - window : i + window + 1]):
            lows.append((i, float(l[i])))
    return highs, lows


def detect_extended_chart_patterns(df: pd.DataFrame, window: int = 5) -> list[dict]:
    """Bull/bear flags, cup & handle, triple top/bottom (M/W)."""
    patterns = []
    if df.empty or len(df) < 40:
        return patterns

    close = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    n = len(df)
    current = float(close[-1])
    atr = _calc_atr(df, 14)
    tol = atr * 0.6
    swing_highs, swing_lows = _swing_points(df, window)

    # ── Bull Flag ──
    pole_len = max(8, n // 5)
    flag_len = max(6, n // 6)
    if n > pole_len + flag_len + 5:
        pole_start = close[-(pole_len + flag_len)]
        pole_end = close[-flag_len]
        pole_rise = (pole_end - pole_start) / (pole_start + 1e-10) * 100
        flag_highs = highs[-flag_len:]
        flag_lows = lows[-flag_len:]
        flag_range = float(np.max(flag_highs) - np.min(flag_lows))
        flag_drift = (close[-1] - close[-flag_len]) / (close[-flag_len] + 1e-10) * 100
        if pole_rise >= 4 and flag_range < abs(pole_end - pole_start) * 0.55 and -3 < flag_drift < 2:
            target = current + abs(pole_end - pole_start)
            flag_top = float(np.max(flag_highs))
            breakout = current > flag_top
            patterns.append({
                "name": "Bull Flag",
                "bias": "BULLISH",
                "reliability": "HIGH" if breakout else "MODERATE",
                "neckline": round(float(np.min(flag_lows)), 4),
                "target": round(float(target), 4),
                "notes": f"Flagpole +{pole_rise:.1f}% then tight consolidation — "
                         f"{'breakout confirmed above ' + f'{flag_top:.2f}' if breakout else 'awaiting breakout above ' + f'{flag_top:.2f}'}, target ≈ {target:.2f}",
            })

    # ── Bear Flag ──
    if n > pole_len + flag_len + 5:
        pole_start = close[-(pole_len + flag_len)]
        pole_end = close[-flag_len]
        pole_drop = (pole_start - pole_end) / (pole_start + 1e-10) * 100
        flag_highs = highs[-flag_len:]
        flag_lows = lows[-flag_len:]
        flag_range = float(np.max(flag_highs) - np.min(flag_lows))
        flag_drift = (close[-1] - close[-flag_len]) / (close[-flag_len] + 1e-10) * 100
        if pole_drop >= 4 and flag_range < abs(pole_start - pole_end) * 0.55 and -2 < flag_drift < 3:
            target = current - abs(pole_start - pole_end)
            flag_bottom = float(np.min(flag_lows))
            breakdown = current < flag_bottom
            patterns.append({
                "name": "Bear Flag",
                "bias": "BEARISH",
                "reliability": "HIGH" if breakdown else "MODERATE",
                "neckline": round(float(np.max(flag_highs)), 4),
                "target": round(float(target), 4),
                "notes": f"Flagpole -{pole_drop:.1f}% then consolidation — "
                         f"{'breakdown confirmed below ' + f'{flag_bottom:.2f}' if breakdown else 'awaiting breakdown below ' + f'{flag_bottom:.2f}'}, target ≈ {target:.2f}",
            })

    # ── Cup & Handle ──
    cup_len = min(60, max(30, n - 10))
    if n >= cup_len + 8:
        segment = close[-cup_len:]
        seg_h = highs[-cup_len:]
        seg_l = lows[-cup_len:]
        left_rim = float(np.max(seg_h[: cup_len // 4]))
        right_rim = float(np.max(seg_h[-cup_len // 4 : -cup_len // 8]))
        cup_bottom = float(np.min(seg_l[cup_len // 4 : -cup_len // 4]))
        depth_pct = (left_rim - cup_bottom) / (left_rim + 1e-10) * 100
        rim_match = abs(left_rim - right_rim) / (left_rim + 1e-10) * 100
        handle_pullback = (right_rim - float(np.min(seg_l[-cup_len // 8:]))) / (right_rim + 1e-10) * 100
        if 8 <= depth_pct <= 35 and rim_match < 4 and 2 <= handle_pullback <= 12:
            target = right_rim + (right_rim - cup_bottom)
            breakout = current > right_rim
            patterns.append({
                "name": "Cup & Handle",
                "bias": "BULLISH",
                "reliability": "VERY HIGH" if breakout else "HIGH",
                "neckline": round(right_rim, 4),
                "target": round(float(target), 4),
                "notes": f"U-shaped base depth {depth_pct:.1f}% — "
                         f"{'breakout confirmed above rim ' + f'{right_rim:.2f}' if breakout else 'awaiting breakout above rim ' + f'{right_rim:.2f}'}, measured move target {target:.2f}",
            })

    # ── Triple Top (M) / Triple Bottom (W) ──
    if len(swing_highs) >= 3:
        h3 = swing_highs[-3:]
        if abs(h3[0][1] - h3[1][1]) <= tol and abs(h3[1][1] - h3[2][1]) <= tol:
            neckline = float(np.min(lows[h3[0][0] : h3[2][0] + 1]))
            target = neckline - (h3[1][1] - neckline)
            patterns.append({
                "name": "Triple Top (M)",
                "bias": "BEARISH",
                "reliability": "VERY HIGH",
                "neckline": round(neckline, 4),
                "target": round(float(target), 4),
                "notes": "Three peaks at similar resistance — bearish reversal if neckline breaks.",
            })

    if len(swing_lows) >= 3:
        l3 = swing_lows[-3:]
        if abs(l3[0][1] - l3[1][1]) <= tol and abs(l3[1][1] - l3[2][1]) <= tol:
            neckline = float(np.max(highs[l3[0][0] : l3[2][0] + 1]))
            target = neckline + (neckline - l3[1][1])
            patterns.append({
                "name": "Triple Bottom (W)",
                "bias": "BULLISH",
                "reliability": "VERY HIGH",
                "neckline": round(neckline, 4),
                "target": round(float(target), 4),
                "notes": "Three troughs at similar support — bullish reversal if neckline breaks.",
            })

    return patterns


def _plan_from_direction(
    df: pd.DataFrame,
    direction: str,
    confidence: int,
    explanation: str,
    signals: list[str],
    opposing: list[str],
    timeframe: str,
    is_crypto: bool,
    sr: dict,
    fib: dict,
    chart_target: float | None = None,
    style: str = "",
) -> dict:
    """Build one trade plan dict with SL/TP/hold duration."""
    currency = "$" if is_crypto else "₹"
    entry = float(df["close"].iloc[-1])
    atr = _calc_atr(df, 14)
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])
    nearest_sup = supports[0]["price"] if supports else entry - atr * 2
    nearest_res = resistances[0]["price"] if resistances else entry + atr * 2

    if direction == "LONG":
        sl = max(nearest_sup - atr * 0.25, entry - atr * 2.5)
        tp1 = chart_target if chart_target and chart_target > entry else nearest_res
        tp2 = tp1 + abs(tp1 - entry) * 0.618
    else:
        sl = min(nearest_res + atr * 0.25, entry + atr * 2.5)
        tp1 = chart_target if chart_target and chart_target < entry else nearest_sup
        tp2 = tp1 - abs(entry - tp1) * 0.618

    sl_dist = abs(entry - sl) or 1e-10
    tp1_dist = abs(tp1 - entry)
    hold, trade_style = estimate_hold_duration(timeframe, style)

    return {
        "direction": direction,
        "entry": round(entry, 4),
        "stop_loss": round(sl, 4),
        "take_profit_1": round(tp1, 4),
        "take_profit_2": round(tp2, 4),
        "sl_pct": round(abs(entry - sl) / entry * 100, 2),
        "tp1_pct": round(tp1_dist / entry * 100, 2),
        "tp2_pct": round(abs(tp2 - entry) / entry * 100, 2),
        "rr_ratio_1": round(tp1_dist / sl_dist, 2),
        "rr_ratio_2": round(abs(tp2 - entry) / sl_dist, 2),
        "confidence": min(95, confidence),
        "signals": signals,
        "opposing_signals": opposing,
        "style": trade_style,
        "hold_duration": hold,
        "explanation": explanation,
        "currency": currency,
        "stay_in_trade": _stay_in_flags(direction, fib, sr),
        "exit_early_if": _exit_early_flags(direction),
    }


def _stay_in_flags(direction: str, fib: dict, sr: dict) -> list[str]:
    flags = []
    if direction == "LONG":
        flags.append("Price holds above broken resistance / key support")
        if fib.get("price_in_golden_zone"):
            flags.append("Fibonacci golden zone holding as support")
        flags.append("Volume not collapsing on pullbacks")
    else:
        flags.append("Price stays below broken support / rejected at resistance")
        if fib.get("price_in_golden_zone"):
            flags.append("Golden zone acting as resistance cap")
        flags.append("Rallies fade with lower highs")
    return flags


def _exit_early_flags(direction: str) -> list[str]:
    if direction == "LONG":
        return [
            "Close back below breakout level or stop loss",
            "Bearish engulfing at resistance with volume spike",
            "Opposite S/R fakeout (failed breakout)",
        ]
    return [
        "Close back above breakdown level or stop loss",
        "Bullish reversal candle at support with volume",
        "Failed breakdown — price reclaims range",
    ]


def build_pattern_trade_plans(
    df: pd.DataFrame,
    sr: dict,
    trendlines: dict,
    fib: dict,
    sr_event: dict,
    candles: list,
    charts: list,
    base_setups: list,
    timeframe: str,
    is_crypto: bool,
) -> list[dict]:
    """Merge S/R events, chart patterns, fib, and engine setups into explained trade plans."""
    plans = []
    seen_keys = set()

    def _add(plan: dict):
        key = (plan["direction"], round(plan["entry"], 2), plan["explanation"][:40])
        if key not in seen_keys:
            seen_keys.add(key)
            plans.append(plan)

    # 1) S/R breakout / fakeout / reversal event
    if not sr_event.get("insufficient"):
        sug = sr_event.get("trade_suggestion", "WAIT")
        conf = int(sr_event.get("confidence", 0))
        if sug in ("BUY", "SELL") and conf >= 45:
            direction = "LONG" if sug == "BUY" else "SHORT"
            expl = (
                f"**{sr_event.get('event_label', '')}** — {sr_event.get('detail', '')}. "
                f"Trend: {trendlines.get('trend_direction', 'N/A')}."
            )
            if fib.get("price_in_golden_zone"):
                expl += " Price in Fibonacci golden retracement zone."
            _add(_plan_from_direction(
                df, direction, conf + 10, expl,
                [f"S/R: {sr_event.get('event', '')}", f"Bias: {sr_event.get('bias', '')}"],
                [], timeframe, is_crypto, sr, fib,
            ))

    # 2) Chart pattern driven plans
    for cp in charts:
        weight = {"VERY HIGH": 85, "HIGH": 75, "MODERATE": 65}.get(cp.get("reliability"), 60)
        direction = "LONG" if cp["bias"] == "BULLISH" else "SHORT"
        expl = f"**{cp['name']}** ({cp['reliability']}) — {cp.get('notes', '')}"
        if cp.get("neckline"):
            expl += f" Neckline near {cp['neckline']}."
        _add(_plan_from_direction(
            df, direction, weight, expl,
            [f"Chart: {cp['name']}"], [],
            timeframe, is_crypto, sr, fib,
            chart_target=cp.get("target"),
        ))

    # 3) Recent high-reliability candlesticks
    for c in candles:
        if c.get("bars_ago", 99) > 2 or c.get("reliability") not in ("HIGH", "VERY HIGH"):
            continue
        if c["bias"] not in ("BULLISH", "BEARISH"):
            continue
        direction = "LONG" if c["bias"] == "BULLISH" else "SHORT"
        _add(_plan_from_direction(
            df, direction, 62,
            f"**{c['name']}** candlestick — {c.get('description', '')}",
            [f"Candle: {c['name']}"], [],
            timeframe, is_crypto, sr, fib,
        ))

    # 4) Merge top engine setups with hold duration
    for setup in base_setups[:2]:
        hold, _ = estimate_hold_duration(timeframe, setup.get("style", ""))
        _add({
            **setup,
            "hold_duration": hold,
            "explanation": (
                f"Multi-signal confluence — {', '.join(setup.get('signals', [])[:4])}."
            ),
            "stay_in_trade": _stay_in_flags(setup["direction"], fib, sr),
            "exit_early_if": _exit_early_flags(setup["direction"]),
        })

    plans.sort(key=lambda p: p.get("confidence", 0), reverse=True)
    # Deduplicate by direction keeping highest confidence
    final = []
    dirs_seen = set()
    for p in plans:
        if p["direction"] in dirs_seen:
            continue
        dirs_seen.add(p["direction"])
        final.append(p)
    return final[:3]


def run_pattern_breakout_analysis(
    df: pd.DataFrame,
    timeframe: str,
    is_crypto: bool = False,
    sr_window: int = 5,
    fib_lookback: int = 100,
) -> dict:
    """Full pattern / breakout analysis package."""
    from app.market_pulse.price_action import analyze_elliott_waves

    sr = detect_support_resistance(df, window=sr_window)
    trendlines = detect_trendlines(df, window=sr_window)
    fib = analyze_fibonacci(df, lookback=fib_lookback)
    sr_event = analyze_sr_breakout(df, timeframe=timeframe)
    candles = detect_candlestick_patterns(df)
    charts = detect_chart_patterns(df, window=sr_window) + detect_extended_chart_patterns(df, sr_window)
    rsi = analyze_rsi(df)
    ema = analyze_ema_crossovers(df)
    adv = analyze_advanced_indicators(df)
    elliott = analyze_elliott_waves(df, zigzag_pct=3.0)
    base_setups = generate_trade_setups(
        df, sr, trendlines, rsi, ema, fib, elliott,
        candles, charts, adv, is_crypto=is_crypto,
    )
    trade_plans = build_pattern_trade_plans(
        df, sr, trendlines, fib, sr_event, candles, charts,
        base_setups, timeframe, is_crypto,
    )

    return {
        "current_price": float(df["close"].iloc[-1]),
        "support_resistance": sr,
        "trendlines": trendlines,
        "fibonacci": fib,
        "sr_breakout": sr_event,
        "candlestick_patterns": candles,
        "chart_patterns": charts,
        "trade_plans": trade_plans,
        "rsi": rsi,
        "ema": ema,
        "adv_indicators": adv,
        "elliott_wave": elliott,
    }


def build_pattern_breakout_ai_prompt(
    symbol: str,
    timeframe: str,
    market: str,
    analysis: dict,
    currency: str,
) -> str:
    """AI prompt for pattern / breakout tab."""
    lines = [
        "=== PATTERN & BREAKOUT ANALYZER ===",
        f"Symbol: {symbol}",
        f"Timeframe: {timeframe}",
        f"Market: {market}",
        f"Price: {currency}{analysis['current_price']:,.4f}",
        "",
        "=== TRENDLINES ===",
        f"Direction: {analysis['trendlines'].get('trend_direction', 'N/A')}",
    ]
    lr = analysis["trendlines"].get("linear_regression") or {}
    if lr:
        lines.append(f"Regression slope %/bar: {lr.get('slope_pct_per_bar', 0)}")

    sr_ev = analysis.get("sr_breakout") or {}
    lines.extend([
        "",
        "=== S/R EVENT (BREAKOUT / FAKEOUT / REVERSAL) ===",
        f"Event: {sr_ev.get('event_label', 'N/A')}",
        f"Bias: {sr_ev.get('bias', 'N/A')}",
        f"Confidence: {sr_ev.get('confidence', 0)}%",
        f"Suggestion: {sr_ev.get('trade_suggestion', 'WAIT')}",
        sr_ev.get("detail", ""),
    ])

    fib = analysis.get("fibonacci") or {}
    lines.extend([
        "",
        "=== FIBONACCI RETRACEMENT ===",
        f"Direction: {fib.get('direction', 'N/A')}",
        f"In Golden Zone: {fib.get('price_in_golden_zone', False)}",
    ])
    for name, px in (fib.get("levels") or {}).items():
        lines.append(f"  {name}: {currency}{px:,.4f}")

    sr = analysis.get("support_resistance") or {}
    lines.append("\n=== KEY S/R LEVELS ===")
    for i, s in enumerate(sr.get("supports", [])[:3], 1):
        lines.append(f"  Support {i}: {currency}{s['price']:,.4f}")
    for i, r in enumerate(sr.get("resistances", [])[:3], 1):
        lines.append(f"  Resistance {i}: {currency}{r['price']:,.4f}")

    if analysis.get("candlestick_patterns"):
        lines.append("\n=== CANDLESTICK PATTERNS ===")
        for c in analysis["candlestick_patterns"][:8]:
            lines.append(f"  - {c['name']} ({c['bias']}, {c['reliability']}) — {c.get('description', '')[:80]}")

    if analysis.get("chart_patterns"):
        lines.append("\n=== CHART PATTERNS ===")
        for c in analysis["chart_patterns"]:
            lines.append(
                f"  - {c['name']} ({c['bias']}, {c['reliability']}) "
                f"Target: {currency}{c.get('target', 0):,.4f} — {c.get('notes', '')}"
            )

    lines.append("\n=== SUGGESTED TRADE PLANS (ENGINE) ===")
    for i, p in enumerate(analysis.get("trade_plans") or [], 1):
        lines.extend([
            f"Plan {i}: {p['direction']} | Confidence {p['confidence']}% | Hold: {p.get('hold_duration', 'N/A')}",
            f"  Explanation: {p.get('explanation', '')}",
            f"  Entry: {currency}{p['entry']:,.4f}",
            f"  SL: {currency}{p['stop_loss']:,.4f} ({p['sl_pct']:.2f}%)",
            f"  TP1: {currency}{p['take_profit_1']:,.4f} ({p['tp1_pct']:.2f}%)",
            f"  TP2: {currency}{p['take_profit_2']:,.4f} ({p['tp2_pct']:.2f}%)",
            f"  R:R TP1: {p['rr_ratio_1']:.2f}",
            f"  Stay in if: {'; '.join(p.get('stay_in_trade', [])[:3])}",
            f"  Exit if: {'; '.join(p.get('exit_early_if', [])[:3])}",
        ])
    if not analysis.get("trade_plans"):
        lines.append("  No high-confidence plan — wait for clearer structure.")

    return "\n".join(lines)


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _render_trade_plan_card(plan: dict) -> None:
    """Display one trade plan with full explanation."""
    cur = plan.get("currency", "₹")
    icon = "🟢" if plan["direction"] == "LONG" else "🔴"
    st.markdown(f"#### {icon} {plan['direction']} — Confidence **{plan['confidence']}%** · {plan.get('style', '')}")
    st.markdown(plan.get("explanation", ""))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entry", f"{cur}{plan['entry']:,.4f}")
    c2.metric("Stop Loss", f"{cur}{plan['stop_loss']:,.4f}", f"-{plan['sl_pct']:.2f}%")
    c3.metric("Take Profit 1", f"{cur}{plan['take_profit_1']:,.4f}", f"+{plan['tp1_pct']:.2f}%")
    c4.metric("R:R (TP1)", f"{plan['rr_ratio_1']:.2f}")
    st.markdown(f"**⏱️ Expected hold:** {plan.get('hold_duration', 'N/A')}")
    st.markdown(f"**🎯 TP2:** {cur}{plan['take_profit_2']:,.4f} ({plan['tp2_pct']:+.2f}%) · R:R {plan['rr_ratio_2']:.2f}")
    if plan.get("signals"):
        st.caption(f"✅ Signals: {', '.join(plan['signals'][:6])}")
    if plan.get("opposing_signals"):
        st.caption(f"⚠️ Opposing: {', '.join(plan['opposing_signals'][:4])}")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**🟢 Stay in trade if:**")
        for item in plan.get("stay_in_trade", []):
            st.markdown(f"- {item}")
    with col_b:
        st.markdown("**🔴 Exit early if:**")
        for item in plan.get("exit_early_if", []):
            st.markdown(f"- {item}")
    st.markdown("---")


def _render_result_block(
    key: str,
    data: dict,
    is_crypto: bool,
    market: str,
    provider: str,
    model: str,
    api_key: str,
    *,
    nested: bool = False,
) -> None:
    currency = "$" if is_crypto else "₹"
    symbol = data["symbol"]
    tf = data["timeframe"]
    safe = _safe_key(key)

    if "error" in data:
        st.error(f"**{symbol} | {tf}** — {data['error']}")
        return

    df = data["df"]
    a = data["analysis"]
    price = a["current_price"]

    bias_icon = "📐"
    sr_ev = a.get("sr_breakout") or {}
    if sr_ev.get("event") == "BREAKOUT":
        bias_icon = "🚀"
    elif sr_ev.get("event") == "BREAKDOWN":
        bias_icon = "💥"
    elif sr_ev.get("event") == "FAKEOUT":
        bias_icon = "⚠️"
    elif sr_ev.get("event") == "REVERSAL":
        bias_icon = "🔄"

    def _body() -> None:
        render_run_summary(summarize_pattern_breakout(a, symbol, tf))
        plan_mtf = (a.get("trade_plan") or {})
        render_strategy_mtf_panel(
            symbol=symbol,
            market=st.session_state.get("pbo_results_market", GROWW_MARKET),
            groww_token=get_active_groww_token(),
            exchange=st.session_state.get("pbo_results_exchange", "NSE"),
            primary_tf=tf,
            strategy_direction=plan_mtf.get("direction"),
        )

        from app.market_pulse.sma_ema_position import analyze_sma_ema_position
        from app.market_pulse.ta_structure_chart import render_ta_structure_section

        sma_ema = analyze_sma_ema_position(df, timeframe=tf)
        render_ta_structure_section(
            df, symbol, tf, currency,
            compact=True,
            sr=a["support_resistance"],
            trendlines=a["trendlines"],
            ema=a["ema"],
            sma_ema=sma_ema,
            ema_ladder=sma_ema.get("ema_ladder"),
            sr_breakout=sr_ev,
            chart_height=380,
        )
        st.markdown("---")
        render_sr_breakout_panel(sr_ev, currency=currency, compact=False, show_chart=False)

        tl = a["trendlines"]
        st.markdown(
            f"**Trendline bias:** {tl.get('trend_direction', 'N/A')} · "
            f"Fib golden zone: {'Yes' if a['fibonacci'].get('price_in_golden_zone') else 'No'}"
        )

        plans = a.get("trade_plans") or []
        if plans:
            st.markdown("### 💼 Suggested Trades")
            for plan in plans:
                _render_trade_plan_card(plan)
        else:
            st.info("No high-confidence trade plan — structure unclear or conflicting signals.")

        chart_analysis = {
            "support_resistance": a["support_resistance"],
            "trendlines": a["trendlines"],
            "fibonacci": a["fibonacci"],
            "rsi": a["rsi"],
            "ema": a["ema"],
            "elliott_wave": a.get("elliott_wave", {"waves": [], "pattern": "NONE"}),
            "candlestick_patterns": a["candlestick_patterns"],
            "chart_patterns": a["chart_patterns"],
            "adv_indicators": a.get("adv_indicators", {}),
        }
        st.plotly_chart(
            build_analysis_chart(df, chart_analysis, symbol, tf),
            width="stretch",
            config={"displayModeBar": True},
        )

        if a.get("candlestick_patterns"):
            st.markdown("**🕯️ Candlestick patterns**")
            rows = [{
                "Pattern": c["name"],
                "Bias": c["bias"],
                "Reliability": c["reliability"],
                "Bars ago": c.get("bars_ago", 0),
            } for c in a["candlestick_patterns"][:12]]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

        if a.get("chart_patterns"):
            st.markdown("**📐 Chart patterns**")
            for cp in a["chart_patterns"]:
                bicon = "🟢" if cp["bias"] == "BULLISH" else "🔴"
                st.markdown(
                    f"- {bicon} **{cp['name']}** ({cp['reliability']}) — "
                    f"Target `{currency}{cp.get('target', 0):,.4f}` · {cp.get('notes', '')}"
                )

        st.markdown("### 🤖 AI View")
        if not api_key:
            st.info(f"💡 Set API keys in `.env` to enable AI View. {api_key_env_hint(provider)}")
        else:
            show_ai_view_block(
                session_prefix="pbo",
                result_key=safe,
                symbol=symbol,
                timeframe_label=tf,
                build_prompt_fn=lambda s=symbol, t=tf, m=market, an=a, c=currency: build_pattern_breakout_ai_prompt(
                    s, t, m, an, c,
                ),
                system_prompt=PATTERN_BREAKOUT_AI_SYSTEM,
                provider=provider,
                model=model,
                api_key=api_key,
                button_in_column=False,
            )

        best = plans[0] if plans else None
        if best:
            render_demo_trade_panel(
                "pbo",
                safe,
                symbol,
                tf,
                market,
                f"Pattern · {best['direction']}",
                current_price=price,
                source_tab="Pattern & Breakout",
                groww_token=get_active_groww_token(),
                exchange=st.session_state.get("pbo_results_exchange", "NSE"),
            )

    if nested:
        _body()
        return

    with st.expander(
        f"{bias_icon} **{symbol}** · `{tf}` — {sr_ev.get('event_label', 'Pattern scan')}",
        expanded=False,
    ):
        _body()


def render_pattern_breakout_tab():
    """Pattern, S/R breakout, and trade suggestion analyzer."""
    st.markdown("<h1>📐 Pattern & Breakout Analyzer</h1>", unsafe_allow_html=True)
    st.write(
        "Support/resistance, trendlines, **breakout · breakdown · fakeout · reversal**, "
        "Fibonacci retracement, candlesticks, and classical patterns "
        "(flags, H&S, M/W, cup & handle) — with **trade plans**, hold duration, and **AI View**."
    )

    provider, model, api_key = render_ai_config(
        "pattern_breakout",
        caption="AI View synthesizes patterns, S/R events, and trade plans into a verdict.",
    )

    st.markdown("---")
    m1, m2 = st.columns(2)
    with m1:
        pbo_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            key="pbo_market",
        )
    with m2:
        pbo_exchange = st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="pbo_exchange") if is_india_market(pbo_market) else "NSE"

    st.markdown("### 📊 Tickers")
    pbo_tickers: list[str] = []
    is_crypto = is_crypto_market(pbo_market)

    if is_crypto:
        pbo_tickers = render_coindcx_ticker_selection("pbo")
    else:
        pbo_tickers = render_equity_index_ticker_selection(pbo_market, "pbo")

    st.markdown("### ⏱️ Timeframes")
    tfc1, tfc2, tfc3 = st.columns(3)
    with tfc1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        pbo_tfs = render_ta_multiselect_timeframes(
            "pbo",
            ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            legacy_default=["15m", "1h", "1d"],
            label="Timeframes",
        )
    with tfc2:
        pbo_candles = st.slider("Candle history", 80, 650, 250, 50, key="pbo_candles")
    with tfc3:
        pbo_sr_win = st.slider("S/R swing window", 3, 12, 5, key="pbo_sr_win")

    with st.expander("⚙️ Advanced", expanded=False):
        pbo_fib_lb = st.slider("Fibonacci lookback", 30, 300, 100, 10, key="pbo_fib_lb")

    total = len(pbo_tickers) * len(pbo_tfs)
    pbo_actionable_only = render_ta_screener_options("pbo")
    st.caption(f"🧮 **{total}** combinations")
    run_btn = st.button("🔎 SCAN PATTERN & BREAKOUT SETUPS", type="primary", width='stretch', key="pbo_run")

    if run_btn:
        if not pbo_tickers or not pbo_tfs:
            st.error("Select at least one ticker and timeframe.")
            return
        results = {}
        bar = st.progress(0, text="Scanning…")
        groww_token = get_active_groww_token()
        i = 0
        for tick in pbo_tickers:
            for tf in pbo_tfs:
                i += 1
                bar.progress(i / total, text=f"{tick} | {tf}")
                try:
                    df = fetch_data_for_gap_scan(
                        tick, tf, pbo_market, groww_token, pbo_exchange, limit=pbo_candles,
                    )
                    if df.empty or len(df) < 25:
                        results[f"{tick}|{tf}"] = {
                            "error": f"Insufficient data ({len(df)} bars).",
                            "symbol": tick, "timeframe": tf,
                        }
                        continue
                    analysis = run_pattern_breakout_analysis(
                        df, tf, is_crypto=is_crypto,
                        sr_window=pbo_sr_win, fib_lookback=pbo_fib_lb,
                    )
                    results[f"{tick}|{tf}"] = {
                        "df": df, "analysis": analysis,
                        "symbol": tick, "timeframe": tf,
                    }
                except Exception as exc:
                    results[f"{tick}|{tf}"] = {
                        "error": str(exc)[:180],
                        "symbol": tick, "timeframe": tf,
                    }
                time.sleep(0.04)
        bar.empty()
        st.session_state.pbo_results = results
        st.session_state.pbo_results_market = pbo_market
        st.session_state.pbo_is_crypto = is_crypto
        st.session_state.pbo_results_exchange = pbo_exchange

    results = st.session_state.get("pbo_results", {})
    market_disp = st.session_state.get("pbo_results_market", pbo_market)
    is_crypto = st.session_state.get("pbo_is_crypto", is_crypto)

    if not results:
        st.info("Configure tickers & timeframes, then run the scan.")
        return

    st.markdown("---")
    digest = []
    for d in results.values():
        if "error" in d:
            digest.append(summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Pattern & Breakout"))
        else:
            digest.append(summarize_pattern_breakout(d["analysis"], d["symbol"], d["timeframe"]))
    digest = render_ta_screener_results(
        digest,
        title="🧭 Pattern & Breakout Screener",
        strategy_label="pattern/breakout",
        actionable_only=pbo_actionable_only,
    )

    if api_key:
        pass
    else:
        st.info("💡 Add `GROQ_API_KEY` or `GEMINI_API_KEY` for **AI View** on each result.")

    tickers = []
    for d in results.values():
        s = d.get("symbol")
        if s and s not in tickers:
            tickers.append(s)

    for ti, ticker in enumerate(tickers):
        if not should_show_ticker_in_screener(ticker, digest, actionable_only=pbo_actionable_only):
            continue
        items = [(k, v) for k, v in results.items() if v.get("symbol") == ticker]
        summaries = [
            summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Pattern & Breakout")
            if "error" in d
            else summarize_pattern_breakout(d["analysis"], d["symbol"], d["timeframe"])
            for _, d in items
        ]
        with st.expander(
            ticker_section_label(ticker, summaries),
            expanded=should_expand_ticker(ti),
        ):
            if api_key and len(items) > 1:
                mtf_ticker_button("pbo", ticker)

                def _mtf_prompt(items=items, m=market_disp, t=ticker, cur="$" if is_crypto else "₹"):
                    sections = []
                    for _, d in items:
                        if "error" in d:
                            sections.append(f"{d['timeframe']}: ERROR — {d['error']}")
                        else:
                            sections.append(build_pattern_breakout_ai_prompt(
                                t, d["timeframe"], m, d["analysis"], cur,
                            ))
                    return combine_timeframe_sections(
                        f"PATTERN & BREAKOUT — {t}", t, sections, market=m,
                    )

                render_mtf_ai_view_report(
                    "pbo", ticker, _mtf_prompt, PATTERN_BREAKOUT_AI_SYSTEM,
                    provider, model, api_key, len(items),
                )
            if len(items) > 1:
                render_run_summary(summarize_mtf_aggregate(summaries, ticker, "Pattern & Breakout"))
            for key, data in items:
                tf = data.get("timeframe", "?")
                summary = next((s for s in summaries if s.get("timeframe") == tf), None)
                extra = ""
                if "error" not in data:
                    sr_ev = (data.get("analysis") or {}).get("sr_breakout") or {}
                    extra = sr_ev.get("event_label", "Pattern scan")
                with st.expander(
                    tf_section_label(tf, summary, extra=extra),
                    expanded=(len(items) == 1),
                ):
                    _render_result_block(
                        key, data, is_crypto, market_disp, provider, model, api_key, nested=True,
                    )

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("pattern_breakout")

    st.caption("⚠️ Pattern recognition is algorithmic. Always confirm with volume, context, and risk limits.")
