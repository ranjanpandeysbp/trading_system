"""
EMA / SMA position analysis — shared across all TrueBacktester tabs.
Covers 9 EMA vs 20 SMA stack plus multi-EMA ladder (5, 9, 20, 50, 200).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd
SMA_PERIOD = 20
EMA_PERIOD = 9
STANDARD_EMA_PERIODS = [5, 9, 20, 50, 200]

TF_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}


def _tf_minutes(timeframe: str) -> int:
    tf = (timeframe or "1d").lower().strip()
    for key, mins in TF_MINUTES.items():
        if key in tf:
            return mins
    return 1440


def _fmt_duration(bars: int, timeframe: str) -> str:
    if bars <= 0:
        return "0 bars"
    mins = bars * _tf_minutes(timeframe)
    if mins < 60:
        return f"{bars} bar{'s' if bars != 1 else ''} (~{mins} min)"
    if mins < 1440:
        hours = mins / 60
        return f"{bars} bars (~{hours:.1f} hr)"
    days = mins / 1440
    return f"{bars} bars (~{days:.1f} day{'s' if days != 1 else ''})"


def _fmt_ts(ts) -> str:
    if ts is None or (isinstance(ts, float) and np.isnan(ts)):
        return "N/A"
    try:
        return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def _bar_regime(price: float, sma: float, ema: float) -> str:
    if pd.isna(price) or pd.isna(sma) or pd.isna(ema):
        return "UNKNOWN"
    upper = max(sma, ema)
    lower = min(sma, ema)
    if price > upper:
        return "ABOVE_BOTH"
    if price < lower:
        return "BELOW_BOTH"
    return "BETWEEN"


def _regime_label(regime: str) -> str:
    return {
        "ABOVE_BOTH": "Above Both",
        "BELOW_BOTH": "Below Both",
        "BETWEEN": "Between MAs",
        "UNKNOWN": "Unknown",
    }.get(regime, regime)


def _estimate_bars_to_level(current: float, level: float, velocity: float) -> Optional[int]:
    if velocity == 0 or pd.isna(velocity) or pd.isna(current) or pd.isna(level):
        return None
    dist = level - current
    if dist * velocity <= 0:
        return None
    return max(1, int(round(abs(dist / velocity))))


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


def analyze_ema_ladder(
    df: pd.DataFrame,
    timeframe: str = "1d",
    periods: list[int] | None = None,
) -> dict:
    """
    Analyze price vs standard EMA ladder (5, 9, 20, 50, 200).
    Identifies which EMAs act as support (price above) vs resistance (price below).
    """
    periods = periods or STANDARD_EMA_PERIODS
    result = {
        "timeframe": timeframe,
        "periods": periods,
        "current_price": None,
        "emas": [],
        "support_emas": [],
        "resistance_emas": [],
        "nearest_support": None,
        "nearest_resistance": None,
        "above_count": 0,
        "below_count": 0,
        "stack_summary": "Insufficient data",
        "insufficient": True,
    }

    if df is None or df.empty or "close" not in df.columns:
        return result

    close = df["close"].astype(float)
    if len(close) < min(periods) + 2:
        return result

    price = float(close.iloc[-1])
    result["current_price"] = price
    result["insufficient"] = False

    ema_rows = []
    for p in periods:
        if len(close) < p:
            ema_rows.append({
                "period": p,
                "label": f"{p} EMA",
                "value": None,
                "above": None,
                "position": "N/A",
                "role": "N/A",
                "dist_pct": None,
                "dist_text": f"Need ≥{p} candles (have {len(close)})",
                "duration_bars": 0,
                "duration_text": "N/A",
                "unavailable": True,
            })
            continue

        ema_series = close.ewm(span=p, adjust=False).mean()
        ema_val = float(ema_series.iloc[-1])
        if pd.isna(ema_val):
            continue

        above = price > ema_val
        dist_pct = ((price - ema_val) / (ema_val + 1e-10)) * 100

        bars_same_side = 0
        for i in range(len(close) - 1, -1, -1):
            ev = float(ema_series.iloc[i])
            if pd.isna(ev):
                break
            if (float(close.iloc[i]) > ev) == above:
                bars_same_side += 1
            else:
                break

        role = "Support" if above else "Resistance"
        row = {
            "period": p,
            "label": f"{p} EMA",
            "value": ema_val,
            "above": above,
            "position": "Above" if above else "Below",
            "role": role,
            "dist_pct": dist_pct,
            "dist_text": f"{abs(dist_pct):.2f}% {'above' if above else 'below'}",
            "duration_bars": bars_same_side,
            "duration_text": _fmt_duration(bars_same_side, timeframe),
            "unavailable": False,
        }
        ema_rows.append(row)
        if above:
            result["support_emas"].append(row)
        else:
            result["resistance_emas"].append(row)

    result["emas"] = ema_rows
    available = [e for e in ema_rows if not e.get("unavailable")]
    if not available:
        result["insufficient"] = True
        return result
    result["above_count"] = len(result["support_emas"])
    result["below_count"] = len(result["resistance_emas"])

    # Nearest support = EMA closest below price (highest EMA value among supports)
    if result["support_emas"]:
        result["nearest_support"] = max(result["support_emas"], key=lambda x: x["value"])
    # Nearest resistance = EMA closest above price (lowest EMA value among resistances)
    if result["resistance_emas"]:
        result["nearest_resistance"] = min(result["resistance_emas"], key=lambda x: x["value"])

    n = len(available)
    ac = result["above_count"]
    if ac == n:
        result["stack_summary"] = f"Price is **ABOVE ALL {n} EMAs** — full bullish EMA stack (5→200)."
    elif ac == 0:
        result["stack_summary"] = f"Price is **BELOW ALL {n} EMAs** — full bearish EMA stack (5→200)."
    elif ac >= n - 1:
        below_labels = ", ".join(r["label"] for r in result["resistance_emas"])
        result["stack_summary"] = f"Price is above **{ac}/{n} EMAs** — only {below_labels} acting as resistance."
    elif ac <= 1:
        above_labels = ", ".join(r["label"] for r in result["support_emas"])
        result["stack_summary"] = f"Price is below **{n - ac}/{n} EMAs** — only {above_labels} acting as support."
    else:
        sup = ", ".join(r["label"] for r in result["support_emas"])
        res = ", ".join(r["label"] for r in result["resistance_emas"])
        result["stack_summary"] = (
            f"Price is **between EMAs** — support from {sup}; resistance from {res}."
        )

    return result


def analyze_sma_ema_position(
    df: pd.DataFrame,
    timeframe: str = "1d",
    sma_period: int = SMA_PERIOD,
    ema_period: int = EMA_PERIOD,
) -> dict:
    """Analyze price vs 20 SMA and 9 EMA with duration, last reversal, and next-reversal estimate."""
    result = {
        "timeframe": timeframe,
        "sma_period": sma_period,
        "ema_period": ema_period,
        "current_price": None,
        "sma_20": None,
        "ema_9": None,
        "regime": "UNKNOWN",
        "position_summary": "Insufficient data",
        "detail": "",
        "above_sma": None,
        "above_ema": None,
        "between_mas": False,
        "duration_bars": 0,
        "duration_text": "N/A",
        "duration_regime": None,
        "last_reversal_date": None,
        "last_reversal_type": None,
        "last_reversal_bars_ago": None,
        "last_reversal_text": "N/A",
        "next_reversal_estimate_bars": None,
        "next_reversal_estimate_text": "N/A",
        "next_reversal_reason": "",
        "ma_cross_estimate_bars": None,
        "ma_cross_estimate_text": "N/A",
        "ema_ladder": None,
        "insufficient": True,
    }

    min_bars = max(sma_period, ema_period) + 5
    if df is None or df.empty or len(df) < min_bars or "close" not in df.columns:
        return result

    close = df["close"].astype(float)
    sma = close.rolling(sma_period).mean()
    ema = close.ewm(span=ema_period, adjust=False).mean()

    price = float(close.iloc[-1])
    sma_val = float(sma.iloc[-1])
    ema_val = float(ema.iloc[-1])

    if pd.isna(sma_val) or pd.isna(ema_val):
        return result

    result["insufficient"] = False
    result["current_price"] = price
    result["sma_20"] = sma_val
    result["ema_9"] = ema_val
    result["above_sma"] = price > sma_val
    result["above_ema"] = price > ema_val

    upper = max(sma_val, ema_val)
    lower = min(sma_val, ema_val)
    regime = _bar_regime(price, sma_val, ema_val)
    result["regime"] = regime
    result["between_mas"] = regime == "BETWEEN"

    sma_name = f"{sma_period} SMA"
    ema_name = f"{ema_period} EMA"

    if regime == "ABOVE_BOTH":
        result["position_summary"] = f"Price is **ABOVE BOTH** {sma_name} and {ema_name}"
        result["detail"] = (
            f"Price ({price:.4f}) > {ema_name} ({ema_val:.4f}) and > {sma_name} ({sma_val:.4f}) — bullish stack."
        )
        result["duration_regime"] = "ABOVE_BOTH"
    elif regime == "BELOW_BOTH":
        result["position_summary"] = f"Price is **BELOW BOTH** {sma_name} and {ema_name}"
        result["detail"] = (
            f"Price ({price:.4f}) < {ema_name} ({ema_val:.4f}) and < {sma_name} ({sma_val:.4f}) — bearish stack."
        )
        result["duration_regime"] = "BELOW_BOTH"
    else:
        ma_above = ema_name if ema_val > sma_val else sma_name
        ma_below = sma_name if ema_val > sma_val else ema_name
        above_val = ema_val if ema_val > sma_val else sma_val
        below_val = sma_val if ema_val > sma_val else ema_val
        result["position_summary"] = f"Price is **BETWEEN** {sma_name} and {ema_name}"
        result["detail"] = (
            f"Price ({price:.4f}) is above {ma_below} ({below_val:.4f}) "
            f"and below {ma_above} ({above_val:.4f})."
        )
        if result["above_ema"] and not result["above_sma"]:
            result["detail"] += f" Specifically: above {ema_name}, below {sma_name}."
        elif result["above_sma"] and not result["above_ema"]:
            result["detail"] += f" Specifically: above {sma_name}, below {ema_name}."
        result["duration_regime"] = None

    # Per-bar regime series for duration & reversals
    regimes = []
    for i in range(len(close)):
        regimes.append(_bar_regime(float(close.iloc[i]), float(sma.iloc[i]), float(ema.iloc[i])))

    current_regime = regimes[-1]
    duration = 0
    for r in reversed(regimes):
        if r == current_regime:
            duration += 1
        else:
            break
    result["duration_bars"] = duration
    result["duration_text"] = _fmt_duration(duration, timeframe)

    # Duration for above-both / below-both specifically
    stack_duration = 0
    stack_regime = result["duration_regime"]
    if stack_regime in ("ABOVE_BOTH", "BELOW_BOTH"):
        for r in reversed(regimes):
            if r == stack_regime:
                stack_duration += 1
            else:
                break
        stack_label = "above both MAs" if stack_regime == "ABOVE_BOTH" else "below both MAs"
        result["stack_duration_bars"] = stack_duration
        result["stack_duration_text"] = _fmt_duration(stack_duration, timeframe)
        result["stack_duration_label"] = stack_label
    else:
        result["stack_duration_bars"] = 0
        result["stack_duration_text"] = "Not in a full above/below-both stack"
        result["stack_duration_label"] = ""

    # Last major reversal: ABOVE_BOTH <-> BELOW_BOTH
    last_rev_idx = None
    last_rev_type = None
    for i in range(len(regimes) - 1, 0, -1):
        prev_r, curr_r = regimes[i - 1], regimes[i]
        if prev_r == "ABOVE_BOTH" and curr_r == "BELOW_BOTH":
            last_rev_idx = i
            last_rev_type = "Bearish reversal (crossed below both MAs)"
            break
        if prev_r == "BELOW_BOTH" and curr_r == "ABOVE_BOTH":
            last_rev_idx = i
            last_rev_type = "Bullish reversal (crossed above both MAs)"
            break

    if last_rev_idx is None:
        for i in range(len(regimes) - 1, 0, -1):
            if regimes[i] != regimes[i - 1] and regimes[i] != "UNKNOWN" and regimes[i - 1] != "UNKNOWN":
                last_rev_idx = i
                last_rev_type = f"Regime change: {_regime_label(regimes[i - 1])} → {_regime_label(regimes[i])}"
                break

    if last_rev_idx is not None:
        bars_ago = len(regimes) - 1 - last_rev_idx
        rev_ts = df.index[last_rev_idx] if last_rev_idx < len(df.index) else None
        result["last_reversal_date"] = rev_ts
        result["last_reversal_type"] = last_rev_type
        result["last_reversal_bars_ago"] = bars_ago
        result["last_reversal_text"] = (
            f"{_fmt_ts(rev_ts)} ({_fmt_duration(bars_ago, timeframe)} ago) — {last_rev_type}"
        )
    else:
        result["last_reversal_text"] = "No clear reversal in lookback window"

    # Next reversal estimate — linear projection over last 5 bars
    lookback = min(5, len(close) - 1)
    price_vel = (float(close.iloc[-1]) - float(close.iloc[-1 - lookback])) / lookback
    sma_vel = (float(sma.iloc[-1]) - float(sma.iloc[-1 - lookback])) / lookback
    ema_vel = (float(ema.iloc[-1]) - float(ema.iloc[-1 - lookback])) / lookback

    est_bars = None
    reason = ""

    if regime == "ABOVE_BOTH":
        target = lower
        est_bars = _estimate_bars_to_level(price, lower, price_vel - max(0, sma_vel, ema_vel))
        if est_bars is None:
            est_bars = _estimate_bars_to_level(price, lower, price_vel)
        nearer = ema_name if ema_val >= sma_val else sma_name
        reason = f"Projected break below nearest MA support ({nearer} zone at {lower:.4f})"
    elif regime == "BELOW_BOTH":
        target = upper
        est_bars = _estimate_bars_to_level(price, upper, price_vel + min(0, sma_vel, ema_vel))
        if est_bars is None:
            est_bars = _estimate_bars_to_level(price, upper, price_vel)
        nearer = ema_name if ema_val <= sma_val else sma_name
        reason = f"Projected break above nearest MA resistance ({nearer} zone at {upper:.4f})"
    else:
        dist_up = upper - price
        dist_dn = price - lower
        bars_up = _estimate_bars_to_level(price, upper, price_vel) if price_vel > 0 else None
        bars_dn = _estimate_bars_to_level(price, lower, price_vel) if price_vel < 0 else None
        if bars_up and bars_dn:
            est_bars = min(bars_up, bars_dn)
            reason = "Projected breakout from between-MA zone (nearest boundary)"
        elif bars_up:
            est_bars = bars_up
            reason = f"Projected move above {ema_name if ema_val > sma_val else sma_name}"
        elif bars_dn:
            est_bars = bars_dn
            reason = f"Projected move below {sma_name if ema_val > sma_val else ema_name}"
        else:
            reason = "Price not trending toward a clear MA boundary — estimate unavailable"

    if est_bars is not None:
        est_mins = est_bars * _tf_minutes(timeframe)
        future_ts = df.index[-1]
        try:
            future_ts = pd.Timestamp(df.index[-1]) + timedelta(minutes=est_mins)
        except Exception:
            pass
        result["next_reversal_estimate_bars"] = est_bars
        result["next_reversal_estimate_text"] = (
            f"~{_fmt_duration(est_bars, timeframe)} (est. {_fmt_ts(future_ts)})"
        )
        result["next_reversal_reason"] = reason
    else:
        result["next_reversal_reason"] = reason or "Insufficient trend toward MA boundary"

    # 9 EMA vs 20 SMA crossover estimate
    ema_sma_gap = ema_val - sma_val
    gap_vel = ema_vel - sma_vel
    if gap_vel != 0 and ema_sma_gap * gap_vel < 0:
        cross_bars = max(1, int(round(abs(ema_sma_gap / gap_vel))))
        cross_type = "Bullish (9 EMA crossing above 20 SMA)" if gap_vel > 0 else "Bearish (9 EMA crossing below 20 SMA)"
        cross_mins = cross_bars * _tf_minutes(timeframe)
        try:
            cross_ts = pd.Timestamp(df.index[-1]) + timedelta(minutes=cross_mins)
        except Exception:
            cross_ts = None
        result["ma_cross_estimate_bars"] = cross_bars
        result["ma_cross_estimate_text"] = (
            f"{cross_type} in ~{_fmt_duration(cross_bars, timeframe)} (est. {_fmt_ts(cross_ts)})"
        )
    else:
        result["ma_cross_estimate_text"] = (
            "9 EMA / 20 SMA not converging — no imminent crossover"
            if abs(ema_sma_gap) > 0 else "9 EMA ≈ 20 SMA (at crossover)"
        )

    result["ema_ladder"] = analyze_ema_ladder(df, timeframe=timeframe)
    return result


def _bias_color(regime: str) -> str:
    if regime == "ABOVE_BOTH":
        return "#10b981"
    if regime == "BELOW_BOTH":
        return "#ef4444"
    if regime == "BETWEEN":
        return "#f59e0b"
    return "#94a3b8"


def render_sma_ema_position_panel(
    analysis: dict,
    currency: str = "₹",
    compact: bool = False,
    df: Optional[pd.DataFrame] = None,
    show_chart: bool = True,
):
    """Render 9 EMA / 20 SMA position section in Streamlit."""
    if not analysis or analysis.get("insufficient"):
        st.caption("⚠️ 9 EMA / 20 SMA analysis unavailable — need at least 25 candles.")
        return

    tf = analysis.get("timeframe", "")
    title = "📐 9 EMA / 20 SMA Position" + (f" ({tf})" if tf else "")
    if compact:
        st.markdown(f"**{title}**")
    else:
        st.markdown(f"#### {title}")

    regime = analysis.get("regime", "UNKNOWN")
    color = _bias_color(regime)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Regime", _regime_label(regime))
    with c2:
        st.metric("20 SMA", f"{currency}{analysis['sma_20']:,.4f}")
    with c3:
        st.metric("9 EMA", f"{currency}{analysis['ema_9']:,.4f}")
    with c4:
        st.metric("Current Price", f"{currency}{analysis['current_price']:,.4f}")

    st.markdown(
        f"""
        <div style="background:#0f1729;border:1px solid #1e3a5f;border-left:4px solid {color};
                    border-radius:10px;padding:14px 16px;margin-top:8px;">
            <div style="font-size:0.95rem;font-weight:700;color:{color};margin-bottom:6px;">
                {analysis.get('position_summary', '')}
            </div>
            <div style="font-size:0.82rem;color:#cbd5e1;line-height:1.55;margin-bottom:10px;">
                {analysis.get('detail', '')}
            </div>
            <div style="font-size:0.78rem;color:#94a3b8;line-height:1.6;">
                <b>vs 20 SMA:</b> {'Above ✓' if analysis.get('above_sma') else 'Below ✗'} &nbsp;|&nbsp;
                <b>vs 9 EMA:</b> {'Above ✓' if analysis.get('above_ema') else 'Below ✗'}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    d1, d2, d3 = st.columns(3)
    with d1:
        if analysis.get("duration_regime") in ("ABOVE_BOTH", "BELOW_BOTH"):
            label = "Above both" if analysis["duration_regime"] == "ABOVE_BOTH" else "Below both"
            st.metric(
                f"Time in stack ({label})",
                analysis.get("stack_duration_text", "N/A"),
            )
        else:
            st.metric("Current regime duration", analysis.get("duration_text", "N/A"))
    with d2:
        st.metric("Last reversal", "See detail")
        st.caption(analysis.get("last_reversal_text", "N/A")[:120])
    with d3:
        st.metric("Next reversal (est.)", "See detail")
        st.caption(analysis.get("next_reversal_estimate_text", "N/A"))

    ladder = analysis.get("ema_ladder") or {}
    if ladder and not ladder.get("insufficient"):
        _render_ema_ladder_panel(ladder, currency=currency, compact=compact)

    with st.expander("ℹ️ Reversal & crossover timing details", expanded=False):
        st.markdown(f"**Last reversal:** {analysis.get('last_reversal_text', 'N/A')}")
        st.markdown(f"**Next reversal (est.):** {analysis.get('next_reversal_estimate_text', 'N/A')}")
        if analysis.get("next_reversal_reason"):
            st.caption(analysis["next_reversal_reason"])
        st.markdown(f"**9 EMA / 20 SMA crossover:** {analysis.get('ma_cross_estimate_text', 'N/A')}")
        st.caption(
            "Estimates use linear projection of recent price/MA slopes over the last 5 bars. "
            "They are indicative only — not guaranteed reversal times."
        )

    if show_chart and df is not None and not df.empty:
        from app.market_pulse.ta_structure_chart import render_structure_chart_for_panel
        render_structure_chart_for_panel(
            df, analysis.get("timeframe", ""), currency,
            sma_ema=analysis,
            ema_ladder=analysis.get("ema_ladder"),
            height=340 if compact else 380,
        )


def _render_ema_ladder_panel(ladder: dict, currency: str = "₹", compact: bool = False):
    """Render multi-EMA support / resistance ladder."""
    tf = ladder.get("timeframe", "")
    title = "📊 EMA Support & Resistance Ladder (5 · 9 · 20 · 50 · 200)" + (f" — {tf}" if tf else "")
    if compact:
        st.markdown(f"**{title}**")
    else:
        st.markdown(f"#### {title}")

    ac = ladder.get("above_count", 0)
    total = len(ladder.get("emas", []))
    bc = ladder.get("below_count", 0)
    stack_color = "#10b981" if ac == total else ("#ef4444" if ac == 0 else "#f59e0b")

    st.markdown(
        f"""
        <div style="background:#0f1729;border:1px solid #1e3a5f;border-left:4px solid {stack_color};
                    border-radius:10px;padding:14px 16px;margin-top:8px;margin-bottom:10px;">
            <div style="font-size:0.92rem;font-weight:700;color:{stack_color};margin-bottom:6px;">
                {ladder.get('stack_summary', '')}
            </div>
            <div style="font-size:0.78rem;color:#94a3b8;">
                Above {ac}/{total} EMAs &nbsp;|&nbsp; Below {bc}/{total} EMAs
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    ns = ladder.get("nearest_support")
    nr = ladder.get("nearest_resistance")
    n1, n2 = st.columns(2)
    with n1:
        if ns:
            st.metric(
                "Nearest Support EMA",
                ns["label"],
                delta=f"{ns['dist_text']} · holding {ns['duration_text']}",
                delta_color="normal",
            )
        else:
            st.metric("Nearest Support EMA", "None — price below all EMAs")
    with n2:
        if nr:
            st.metric(
                "Nearest Resistance EMA",
                nr["label"],
                delta=f"{nr['dist_text']} · capping {nr['duration_text']}",
                delta_color="inverse",
            )
        else:
            st.metric("Nearest Resistance EMA", "None — price above all EMAs")

    rows = []
    for e in ladder.get("emas", []):
        if e.get("unavailable"):
            rows.append({
                "EMA": e["label"],
                "EMA Value": "N/A",
                "Price Position": "—",
                "Role": "N/A",
                "Distance": e["dist_text"],
                "Holding Since": "N/A",
            })
            continue
        icon = "🟢" if e["above"] else "🔴"
        role_tag = "Support ✓" if e["above"] else "Resistance ✗"
        rows.append({
            "EMA": e["label"],
            "EMA Value": _fmt_price(e["value"], currency),
            "Price Position": f"{icon} {e['position']}",
            "Role": role_tag,
            "Distance": e["dist_text"],
            "Holding Since": e["duration_text"],
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

    sup_labels = [e["label"] for e in ladder.get("support_emas", [])]
    res_labels = [e["label"] for e in ladder.get("resistance_emas", [])]

    with st.expander("ℹ️ How to read EMA support & resistance", expanded=False):
        st.markdown(
            "**Support EMAs** — price is trading **above** these EMAs; they act as dynamic floors "
            "if price pulls back.\n\n"
            "**Resistance EMAs** — price is trading **below** these EMAs; they act as dynamic ceilings "
            "if price rallies."
        )
        if sup_labels:
            st.markdown(f"**Current support EMAs:** {', '.join(sup_labels)}")
        else:
            st.markdown("**Current support EMAs:** None (price below entire EMA stack)")
        if res_labels:
            st.markdown(f"**Current resistance EMAs:** {', '.join(res_labels)}")
        else:
            st.markdown("**Current resistance EMAs:** None (price above entire EMA stack)")
        st.caption(
            "Duration shows how long price has continuously stayed above/below each EMA "
            "within the loaded candle history for this timeframe."
        )


def render_sma_ema_position_for_ticker(
    df: pd.DataFrame,
    timeframe: str = "1d",
    currency: Optional[str] = None,
    compact: bool = False,
    show_chart: bool = True,
):
    """Compute and render 9 EMA / 20 SMA position from OHLCV data."""
    if df is None or df.empty:
        return
    if currency is None:
        currency = "₹"
    analysis = analyze_sma_ema_position(df, timeframe=timeframe)
    render_sma_ema_position_panel(
        analysis, currency=currency, compact=compact, df=df, show_chart=show_chart,
    )
