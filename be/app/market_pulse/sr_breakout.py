"""
Support / Resistance breakout analysis — shared across all TrueBacktester tabs.
Detects breakout, breakdown, fakeout, reversal; bias + trade confidence.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
def _find_swing_points(df: pd.DataFrame, window: int = 5):
    """Return lists of (index, price) for swing highs and swing lows."""
    if df is None or df.empty or len(df) < window * 2 + 1:
        return [], []
    highs = df["high"].values
    lows = df["low"].values
    idx = df.index
    swing_highs, swing_lows = [], []
    for i in range(window, len(df) - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            swing_highs.append((idx[i], float(highs[i])))
        if lows[i] == min(lows[i - window : i + window + 1]):
            swing_lows.append((idx[i], float(lows[i])))
    return swing_highs, swing_lows


def _fmt_price(value: float, currency: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    if currency == "$":
        if value >= 1000:
            return f"{currency}{value:,.2f}"
        if value >= 1:
            return f"{currency}{value:.4f}"
        return f"{currency}{value:.6f}"
    return f"{currency}{value:,.2f}"


def _nearest_swing_levels(df: pd.DataFrame, price: float, window: int = 5) -> tuple[float | None, float | None]:
    """Resistance = nearest swing high above price; support = nearest swing low below."""
    swing_highs, swing_lows = _find_swing_points(df.iloc[:-1], window=window)
    res_levels = [p for _, p in swing_highs if p > price * 1.001]
    sup_levels = [p for _, p in swing_lows if p < price * 0.999]
    resistance = min(res_levels) if res_levels else None
    support = max(sup_levels) if sup_levels else None
    if resistance is None and swing_highs:
        resistance = max(p for _, p in swing_highs[-3:])
    if support is None and swing_lows:
        support = min(p for _, p in swing_lows[-3:])
    return resistance, support


def analyze_sr_breakout(df: pd.DataFrame, timeframe: str = "1d", lookback: int = 40) -> dict:
    """
    Classify price action vs key S/R: breakout, breakdown, fakeout, reversal, or range.
    Returns bias, event, confidence (0–100), and trade suggestion.
    """
    result = {
        "timeframe": timeframe,
        "event": "RANGE",
        "event_label": "Trading in range",
        "bias": "NEUTRAL",
        "confidence": 0,
        "trade_suggestion": "WAIT",
        "summary": "Insufficient data for S/R breakout analysis.",
        "detail": "",
        "support": None,
        "resistance": None,
        "dist_support_pct": None,
        "dist_resistance_pct": None,
        "broken_level": None,
        "broken_direction": None,
        "insufficient": True,
    }

    if df is None or df.empty or len(df) < max(lookback, 25):
        return result

    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            return result

    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float) if "volume" in df.columns else pd.Series([0.0] * len(df))

    price = float(c.iloc[-1])
    hist = df.iloc[-(lookback + 1):-1]
    if hist.empty:
        return result

    resistance = float(hist["high"].max())
    support = float(hist["low"].min())
    swing_res, swing_sup = _nearest_swing_levels(df, price)
    if swing_res is not None:
        resistance = swing_res
    if swing_sup is not None:
        support = swing_sup

    if support >= resistance:
        result["insufficient"] = True
        return result

    result["insufficient"] = False
    result["support"] = support
    result["resistance"] = resistance
    result["dist_support_pct"] = ((price - support) / (support + 1e-10)) * 100
    result["dist_resistance_pct"] = ((resistance - price) / (price + 1e-10)) * 100

    vol_avg = float(v.iloc[-21:-1].mean()) if len(v) > 21 else float(v.mean() or 1)
    vol_ratio = float(v.iloc[-1] / (vol_avg + 1e-10))

    tol = 0.0015  # 0.15% tolerance for level tests
    event = "RANGE"
    bias = "NEUTRAL"
    broken_level = None
    broken_dir = None
    bars_held = 0

    # Scan last 8 bars for the most recent meaningful S/R interaction
    scan = min(8, len(df) - 1)
    for offset in range(scan, 0, -1):
        i = -offset
        prev_i = i - 1
        if abs(prev_i) > len(df):
            continue
        bar_h, bar_l, bar_c = float(h.iloc[i]), float(l.iloc[i]), float(c.iloc[i])
        prev_c = float(c.iloc[prev_i])

        # Bullish breakout: close above resistance
        if prev_c <= resistance * (1 + tol) and bar_c > resistance * (1 + tol):
            if bar_c > resistance and float(c.iloc[-1]) > resistance * (1 - tol):
                event = "BREAKOUT"
                bias = "BULLISH"
                broken_level = resistance
                broken_dir = "above_resistance"
            elif bar_h > resistance * (1 + tol) and bar_c < resistance:
                event = "FAKEOUT"
                bias = "BEARISH"
                broken_level = resistance
                broken_dir = "failed_above_resistance"
            break

        # Bearish breakdown: close below support
        if prev_c >= support * (1 - tol) and bar_c < support * (1 - tol):
            if bar_c < support and float(c.iloc[-1]) < support * (1 + tol):
                event = "BREAKDOWN"
                bias = "BEARISH"
                broken_level = support
                broken_dir = "below_support"
            elif bar_l < support * (1 - tol) and bar_c > support:
                event = "FAKEOUT"
                bias = "BULLISH"
                broken_level = support
                broken_dir = "failed_below_support"
            break

    # Reversal at level (current bar)
    body = abs(price - float(o.iloc[-1]))
    upper_wick = float(h.iloc[-1]) - max(price, float(o.iloc[-1]))
    lower_wick = min(price, float(o.iloc[-1])) - float(l.iloc[-1])
    near_sup = abs(float(l.iloc[-1]) - support) / (support + 1e-10) < 0.012
    near_res = abs(float(h.iloc[-1]) - resistance) / (resistance + 1e-10) < 0.012

    if event == "RANGE":
        if near_sup and lower_wick > body * 1.5 and price > float(o.iloc[-1]):
            event = "REVERSAL"
            bias = "BULLISH"
            broken_level = support
            broken_dir = "bounce_at_support"
        elif near_res and upper_wick > body * 1.5 and price < float(o.iloc[-1]):
            event = "REVERSAL"
            bias = "BEARISH"
            broken_level = resistance
            broken_dir = "rejection_at_resistance"
        elif price > resistance * (1 + tol):
            event = "BREAKOUT"
            bias = "BULLISH"
            broken_level = resistance
            broken_dir = "above_resistance"
        elif price < support * (1 - tol):
            event = "BREAKDOWN"
            bias = "BEARISH"
            broken_level = support
            broken_dir = "below_support"

    # Follow-through bars after breakout/breakdown
    if event in ("BREAKOUT", "BREAKDOWN") and broken_level:
        lvl = broken_level
        for j in range(1, min(5, len(c))):
            if event == "BREAKOUT" and float(c.iloc[-j]) > lvl:
                bars_held += 1
            elif event == "BREAKDOWN" and float(c.iloc[-j]) < lvl:
                bars_held += 1
            else:
                break

    # Confidence scoring
    confidence = 35
    if event == "BREAKOUT":
        confidence += 20
        confidence += min(15, bars_held * 5)
        confidence += min(15, max(0, (price - resistance) / (resistance + 1e-10) * 100) * 3)
        if vol_ratio >= 1.5:
            confidence += 12
        elif vol_ratio >= 1.1:
            confidence += 6
    elif event == "BREAKDOWN":
        confidence += 20
        confidence += min(15, bars_held * 5)
        confidence += min(15, max(0, (support - price) / (support + 1e-10) * 100) * 3)
        if vol_ratio >= 1.5:
            confidence += 12
        elif vol_ratio >= 1.1:
            confidence += 6
    elif event == "FAKEOUT":
        confidence += 18
        if vol_ratio >= 1.2:
            confidence += 10
        wick_ratio = max(upper_wick, lower_wick) / (body + 1e-10)
        if wick_ratio > 2:
            confidence += 8
    elif event == "REVERSAL":
        confidence += 22
        wick_ratio = max(upper_wick, lower_wick) / (body + 1e-10)
        if wick_ratio > 2:
            confidence += 12
        if vol_ratio >= 1.2:
            confidence += 6
    else:
        confidence = max(15, 40 - int(abs(result["dist_support_pct"] or 0) + abs(result["dist_resistance_pct"] or 0)))

    confidence = int(max(0, min(100, confidence)))

    event_labels = {
        "BREAKOUT": "Breakout above resistance",
        "BREAKDOWN": "Breakdown below support",
        "FAKEOUT": "Fakeout (false break & rejection)",
        "REVERSAL": "Reversal at key S/R level",
        "RANGE": "Range-bound between S/R",
    }
    trade_map = {
        ("BREAKOUT", "BULLISH"): "BUY",
        ("BREAKDOWN", "BEARISH"): "SELL",
        ("FAKEOUT", "BEARISH"): "SELL",
        ("FAKEOUT", "BULLISH"): "BUY",
        ("REVERSAL", "BULLISH"): "BUY",
        ("REVERSAL", "BEARISH"): "SELL",
        ("RANGE", "NEUTRAL"): "WAIT",
    }
    trade_suggestion = trade_map.get((event, bias), "WAIT")
    if confidence < 45 and trade_suggestion != "WAIT":
        trade_suggestion = "WAIT"

    summary = f"**{event_labels.get(event, event)}** — {bias} bias · {confidence}% confidence"
    detail_parts = [
        f"Support: {support:.4f} ({result['dist_support_pct']:+.2f}% away)",
        f"Resistance: {resistance:.4f} ({result['dist_resistance_pct']:+.2f}% away)",
    ]
    if broken_level:
        detail_parts.append(f"Key level: {broken_level:.4f} ({broken_dir or 'n/a'})")
    if bars_held > 0 and event in ("BREAKOUT", "BREAKDOWN"):
        detail_parts.append(f"Held beyond level for {bars_held} bar(s)")
    detail_parts.append(f"Volume ratio: {vol_ratio:.2f}x")

    result.update({
        "event": event,
        "event_label": event_labels.get(event, event),
        "bias": bias,
        "confidence": confidence,
        "trade_suggestion": trade_suggestion,
        "summary": summary,
        "detail": " · ".join(detail_parts),
        "broken_level": broken_level,
        "broken_direction": broken_dir,
        "volume_ratio": round(vol_ratio, 2),
        "bars_held": bars_held,
    })
    return result


def apply_sr_breakout_scoring(sr: dict) -> tuple[int, int, list[str]]:
    """Return (bull_pts, bear_pts, insights) for composite score engines."""
    if not sr or sr.get("insufficient"):
        return 0, 0, []
    conf = sr.get("confidence", 0) / 100.0
    weight = 18
    pts = int(weight * conf)
    icon = {
        "BREAKOUT": "🚀",
        "BREAKDOWN": "💥",
        "FAKEOUT": "⚠️",
        "REVERSAL": "🔄",
        "RANGE": "↔️",
    }.get(sr.get("event", ""), "📐")
    line = (
        f"{icon} S/R {sr.get('event_label', '')}: {sr.get('bias', 'NEUTRAL')} "
        f"({sr.get('confidence', 0)}% conf) — Suggest {sr.get('trade_suggestion', 'WAIT')}"
    )
    if sr.get("bias") == "BULLISH":
        return pts, 0, [line]
    if sr.get("bias") == "BEARISH":
        return 0, pts, [line]
    return 0, 0, [line]


def compute_trade_confidence(net_score: float, sr: dict) -> int:
    """
    Blend sentiment net score with S/R alignment into 0–100 trade confidence.
    """
    if not sr or sr.get("insufficient"):
        return int(min(100, max(0, 50 + abs(net_score) * 0.35)))
    base = min(100, max(0, 50 + net_score * 0.35))
    sr_conf = sr.get("confidence", 0)
    aligned = (
        (net_score > 0 and sr.get("bias") == "BULLISH")
        or (net_score < 0 and sr.get("bias") == "BEARISH")
    )
    opposed = (
        (net_score > 10 and sr.get("bias") == "BEARISH")
        or (net_score < -10 and sr.get("bias") == "BULLISH")
    )
    if aligned:
        base = min(100, base + sr_conf * 0.25)
    elif opposed:
        base = max(0, base - sr_conf * 0.3)
    else:
        base = min(100, base + sr_conf * 0.1)
    return int(round(base))


def _bias_color(bias: str) -> str:
    if bias == "BULLISH":
        return "#10b981"
    if bias == "BEARISH":
        return "#ef4444"
    return "#f59e0b"


def _event_color(event: str) -> str:
    return {
        "BREAKOUT": "#10b981",
        "BREAKDOWN": "#ef4444",
        "FAKEOUT": "#f59e0b",
        "REVERSAL": "#8b5cf6",
        "RANGE": "#64748b",
    }.get(event, "#64748b")


def render_sr_breakout_panel(
    sr: dict,
    currency: str = "₹",
    compact: bool = False,
    df: Optional[pd.DataFrame] = None,
    show_chart: bool = True,
):
    """Render S/R breakout section in Streamlit."""
    if not sr or sr.get("insufficient"):
        st.caption("⚠️ S/R breakout analysis unavailable — need at least 25 candles.")
        return

    tf = sr.get("timeframe", "")
    title = "🎯 Support / Resistance Breakout" + (f" ({tf})" if tf else "")
    if compact:
        st.markdown(f"**{title}**")
    else:
        st.markdown(f"#### {title}")

    color = _bias_color(sr.get("bias", "NEUTRAL"))
    evt_color = _event_color(sr.get("event", "RANGE"))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Event", sr.get("event", "RANGE"))
    with c2:
        st.metric("Bias", sr.get("bias", "NEUTRAL"))
    with c3:
        st.metric("Trade Confidence", f"{sr.get('confidence', 0)}%")
    with c4:
        st.metric("Suggest", sr.get("trade_suggestion", "WAIT"))

    st.markdown(
        f"""
        <div style="background:#0f1729;border:1px solid #1e3a5f;border-left:4px solid {evt_color};
                    border-radius:10px;padding:14px 16px;margin-top:8px;">
            <div style="font-size:0.92rem;font-weight:700;color:{color};margin-bottom:6px;">
                {sr.get('event_label', '')} — {sr.get('bias', '')} ({sr.get('confidence', 0)}% confidence)
            </div>
            <div style="font-size:0.8rem;color:#cbd5e1;line-height:1.55;margin-bottom:8px;">
                {sr.get('detail', '')}
            </div>
            <div style="font-size:0.78rem;color:#94a3b8;">
                <b>Support:</b> {_fmt_price(sr.get('support'), currency)} &nbsp;|&nbsp;
                <b>Resistance:</b> {_fmt_price(sr.get('resistance'), currency)} &nbsp;|&nbsp;
                <b>Suggested action:</b> <span style="color:{color};font-weight:700;">
                    {sr.get('trade_suggestion', 'WAIT')}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("ℹ️ How to read S/R events", expanded=False):
        st.markdown(
            "**Breakout** — Close above resistance with follow-through → bullish.\n\n"
            "**Breakdown** — Close below support with follow-through → bearish.\n\n"
            "**Fakeout** — Wick through a level but close back inside → fade the false move.\n\n"
            "**Reversal** — Rejection wick at support/resistance → counter-trend bounce.\n\n"
            "Confidence blends volume, distance beyond the level, and bars held after the break."
        )

    if show_chart and df is not None and not df.empty:
        from app.market_pulse.ta_structure_chart import render_structure_chart_for_panel
        render_structure_chart_for_panel(
            df, sr.get("timeframe", ""), currency,
            sr_breakout=sr,
            height=340 if compact else 380,
        )


def render_sr_breakout_for_ticker(
    df: pd.DataFrame,
    timeframe: str = "1d",
    currency: Optional[str] = None,
    compact: bool = False,
    show_chart: bool = True,
):
    """Compute and render S/R breakout analysis from OHLCV data."""
    if df is None or df.empty:
        return None
    if currency is None:
        currency = "₹"
    sr = analyze_sr_breakout(df, timeframe=timeframe)
    render_sr_breakout_panel(
        sr, currency=currency, compact=compact, df=df, show_chart=show_chart,
    )
    return sr
