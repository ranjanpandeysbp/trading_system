"""
ta_structure_chart.py
---------------------
Shared candlestick charts for price vs EMA/SMA, support/resistance, and trendlines
with matching textual explanations — used across Technical Analysis sections.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
def _fmt_price(value: float, currency: str) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    if currency == "$":
        if value >= 1000:
            return f"{currency}{value:,.2f}"
        if value >= 1:
            return f"{currency}{value:.4f}"
        return f"{currency}{value:.6f}"
    return f"{currency}{value:,.2f}"


def _add_trendline_trace(fig, df: pd.DataFrame, tl_spec: dict | None, name: str, color: str) -> None:
    if not tl_spec or df is None or df.empty:
        return
    si = int(tl_spec.get("start_idx", 0))
    si = max(0, min(si, len(df) - 1))
    slope = float(tl_spec.get("slope", 0))
    intercept = float(tl_spec.get("intercept", 0))
    y_vals = [slope * i + intercept for i in range(si, len(df))]
    fig.add_trace(go.Scatter(
        x=df.index[si:],
        y=y_vals,
        mode="lines",
        name=name,
        line=dict(color=color, width=2, dash="dash"),
        opacity=0.85,
    ))


def build_structure_levels_chart(
    df: pd.DataFrame,
    *,
    symbol: str = "",
    timeframe: str = "",
    currency: str = "₹",
    sr: dict | None = None,
    trendlines: dict | None = None,
    ema: dict | None = None,
    sma_ema: dict | None = None,
    ema_ladder: dict | None = None,
    sr_breakout: dict | None = None,
    height: int = 400,
) -> go.Figure:
    """Candlestick chart with EMA/SMA, S/R, trendlines, and current price marker."""
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    price = float(df["close"].iloc[-1])
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Price",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ))

    ema_colors = {5: "#a78bfa", 9: "#ff9800", 20: "#2196f3", 21: "#06b6d4", 50: "#9c27b0", 200: "#e2e8f0"}

    if ema and ema.get("emas"):
        for period, arr in ema["emas"].items():
            if arr is not None and len(arr) == len(df) and not np.all(np.isnan(arr)):
                fig.add_trace(go.Scatter(
                    x=df.index,
                    y=arr,
                    mode="lines",
                    name=f"EMA {period}",
                    line=dict(width=1.5, color=ema_colors.get(period, "#888")),
                    opacity=0.8,
                ))

    if sma_ema and not sma_ema.get("insufficient"):
        close = df["close"].astype(float)
        sma_p = sma_ema.get("sma_period", 20)
        ema_p = sma_ema.get("ema_period", 9)
        sma_line = close.rolling(sma_p).mean()
        ema_line = close.ewm(span=ema_p, adjust=False).mean()
        if not sma_line.isna().all():
            fig.add_trace(go.Scatter(
                x=df.index, y=sma_line, name=f"SMA {sma_p}",
                line=dict(color="#60a5fa", width=2, dash="dot"),
            ))
        if not ema_line.isna().all():
            fig.add_trace(go.Scatter(
                x=df.index, y=ema_line, name=f"EMA {ema_p}",
                line=dict(color="#f59e0b", width=2),
            ))

    if ema_ladder and not ema_ladder.get("insufficient"):
        close = df["close"].astype(float)
        for e in ema_ladder.get("emas", []):
            if e.get("unavailable"):
                continue
            period = e.get("period")
            if period and period not in (ema or {}).get("emas", {}):
                series = close.ewm(span=period, adjust=False).mean()
                fig.add_trace(go.Scatter(
                    x=df.index, y=series, name=e.get("label", f"EMA {period}"),
                    line=dict(width=1, color=ema_colors.get(period, "#64748b"), dash="dot"),
                    opacity=0.65,
                ))

    if sr:
        for i, s in enumerate(sr.get("supports", [])[:3]):
            fig.add_hline(
                y=s["price"], line_dash="dash", line_color="rgba(76,175,80,0.85)", line_width=1.5,
                annotation_text=f"S{i+1} {_fmt_price(s['price'], currency)}",
                annotation_position="right",
            )
        for i, r in enumerate(sr.get("resistances", [])[:3]):
            fig.add_hline(
                y=r["price"], line_dash="dash", line_color="rgba(244,67,54,0.85)", line_width=1.5,
                annotation_text=f"R{i+1} {_fmt_price(r['price'], currency)}",
                annotation_position="right",
            )

    if sr_breakout and not sr_breakout.get("insufficient"):
        sup = sr_breakout.get("support")
        res = sr_breakout.get("resistance")
        if sup and (not sr or not any(abs(s["price"] - sup) < 1e-6 for s in sr.get("supports", []))):
            fig.add_hline(y=sup, line_dash="longdash", line_color="#34d399", line_width=2,
                          annotation_text=f"Range Sup {_fmt_price(sup, currency)}")
        if res and (not sr or not any(abs(r["price"] - res) < 1e-6 for r in sr.get("resistances", []))):
            fig.add_hline(y=res, line_dash="longdash", line_color="#f87171", line_width=2,
                          annotation_text=f"Range Res {_fmt_price(res, currency)}")
        bl = sr_breakout.get("broken_level")
        if bl:
            fig.add_hline(y=bl, line_dash="solid", line_color="#fbbf24", line_width=2,
                          annotation_text=f"Key level {_fmt_price(bl, currency)}")

    if trendlines:
        _add_trendline_trace(fig, df, trendlines.get("uptrend"), "Uptrend line", "#4caf50")
        _add_trendline_trace(fig, df, trendlines.get("downtrend"), "Downtrend line", "#ef5350")
        lr = trendlines.get("linear_regression")
        if lr:
            x_arr = np.arange(len(df))
            y_lr = lr["slope"] * x_arr + lr["intercept"]
            fig.add_trace(go.Scatter(
                x=df.index, y=y_lr, name="Lin. regression",
                line=dict(width=1, dash="dot", color="rgba(148,163,184,0.6)"),
            ))

    fig.add_hline(
        y=price, line_color="#fbbf24", line_width=1,
        annotation_text=f"Last {_fmt_price(price, currency)}",
        annotation_position="left",
    )

    title = f"{symbol} · {timeframe} — Structure" if symbol else f"Structure · {timeframe}"
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#e2e8f0")),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 41, 0.85)",
        font=dict(color="#94a3b8", size=10),
        xaxis=dict(gridcolor="#1e3a5f", rangeslider=dict(visible=False)),
        yaxis=dict(gridcolor="#1e3a5f", title="Price"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=90, t=50, b=30),
    )
    return fig


def format_structure_explanations(
    df: pd.DataFrame,
    currency: str = "₹",
    sr: dict | None = None,
    trendlines: dict | None = None,
    ema: dict | None = None,
    sma_ema: dict | None = None,
    ema_ladder: dict | None = None,
    sr_breakout: dict | None = None,
) -> list[str]:
    """Bullet explanations for price vs levels (shown beside/above chart)."""
    if df is None or df.empty:
        return ["Insufficient data for structure explanation."]
    lines: list[str] = []
    price = float(df["close"].iloc[-1])

    if ema and ema.get("emas"):
        stack = ema.get("ema_stack", "MIXED")
        lines.append(
            f"**EMA stack (9/21/50):** {stack} — "
            + ("9 > 21 > 50 (bullish alignment)." if stack == "BULLISH"
               else "9 < 21 < 50 (bearish alignment)." if stack == "BEARISH"
               else "mixed alignment — no clean stack.")
        )
        vs200 = ema.get("price_vs_ema200")
        arr200 = ema["emas"].get(200)
        if vs200 and arr200 is not None and not np.isnan(arr200[-1]):
            v200 = float(arr200[-1])
            pct = (price - v200) / v200 * 100
            lines.append(
                f"**Price vs EMA 200:** {vs200} — last { _fmt_price(price, currency)} is "
                f"{pct:+.2f}% vs EMA 200 ({_fmt_price(v200, currency)})."
            )
        for period in (9, 21, 50):
            arr = ema["emas"].get(period)
            if arr is not None and not np.isnan(arr[-1]):
                ev = float(arr[-1])
                rel = "above" if price > ev else "below"
                lines.append(
                    f"**Price {rel} EMA {period}:** {_fmt_price(price, currency)} vs "
                    f"{_fmt_price(ev, currency)} ({abs(price - ev) / ev * 100:.2f}% away)."
                )

    if sma_ema and not sma_ema.get("insufficient"):
        lines.append(f"**9 EMA / 20 SMA:** {sma_ema.get('position_summary', '').replace('**', '')}")
        if sma_ema.get("detail"):
            lines.append(sma_ema["detail"])

    if ema_ladder and not ema_ladder.get("insufficient"):
        lines.append(f"**EMA ladder:** {ema_ladder.get('stack_summary', '')}")
        ns, nr = ema_ladder.get("nearest_support"), ema_ladder.get("nearest_resistance")
        if ns:
            lines.append(
                f"Nearest **support EMA** — {ns['label']} at {_fmt_price(ns['value'], currency)} "
                f"({ns.get('dist_text', '')})."
            )
        if nr:
            lines.append(
                f"Nearest **resistance EMA** — {nr['label']} at {_fmt_price(nr['value'], currency)} "
                f"({nr.get('dist_text', '')})."
            )

    if sr:
        for i, s in enumerate(sr.get("supports", [])[:2], 1):
            dist = (price - s["price"]) / s["price"] * 100
            lines.append(
                f"**Support {i}** at {_fmt_price(s['price'], currency)} — price "
                f"{dist:+.2f}% above (strength {s.get('strength', 1)})."
            )
        for i, r in enumerate(sr.get("resistances", [])[:2], 1):
            dist = (r["price"] - price) / price * 100
            lines.append(
                f"**Resistance {i}** at {_fmt_price(r['price'], currency)} — "
                f"{dist:+.2f}% overhead (strength {r.get('strength', 1)})."
            )

    if trendlines:
        td = trendlines.get("trend_direction", "SIDEWAYS")
        lines.append(f"**Trendline / regression bias:** {td}.")
        if trendlines.get("uptrend"):
            lines.append(
                "**Ascending trendline** through rising swing lows — acts as dynamic support."
            )
        if trendlines.get("downtrend"):
            lines.append(
                "**Descending trendline** through falling swing highs — acts as dynamic resistance."
            )
        lr = trendlines.get("linear_regression") or {}
        if lr.get("slope_pct_per_bar") is not None:
            lines.append(
                f"Linear regression slope: **{lr['slope_pct_per_bar']:+.4f}%/bar** "
                f"(R² {lr.get('r_squared', 0):.2f})."
            )

    if sr_breakout and not sr_breakout.get("insufficient"):
        lines.append(
            f"**S/R event:** {sr_breakout.get('event_label', '')} — "
            f"{sr_breakout.get('bias', '')} ({sr_breakout.get('confidence', 0)}% conf). "
            f"Suggest **{sr_breakout.get('trade_suggestion', 'WAIT')}**."
        )
        if sr_breakout.get("detail"):
            lines.append(sr_breakout["detail"])

    return lines or ["No structure annotations available."]


def render_ta_structure_section(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    currency: str = "₹",
    *,
    compact: bool = False,
    sr: dict | None = None,
    trendlines: dict | None = None,
    ema: dict | None = None,
    sma_ema: dict | None = None,
    ema_ladder: dict | None = None,
    sr_breakout: dict | None = None,
    chart_height: int = 400,
) -> None:
    """Render structure explanations + annotated chart (keeps prose, adds visual)."""
    if df is None or df.empty or len(df) < 20:
        st.caption("⚠️ Structure chart needs at least 20 candles.")
        return

    if sr is None or trendlines is None or ema is None:
        from app.market_pulse.price_action import (
            analyze_ema_crossovers,
            detect_support_resistance,
            detect_trendlines,
        )
        if sr is None:
            sr = detect_support_resistance(df)
        if trendlines is None:
            trendlines = detect_trendlines(df)
        if ema is None:
            ema = analyze_ema_crossovers(df)

    title = "📈 Price · EMA · Support/Resistance · Trendlines"
    if compact:
        st.markdown(f"**{title}** (`{timeframe}`)")
    else:
        st.markdown(f"#### {title} — `{symbol}` · `{timeframe}`")

    explanations = format_structure_explanations(
        df, currency=currency, sr=sr, trendlines=trendlines, ema=ema,
        sma_ema=sma_ema, ema_ladder=ema_ladder, sr_breakout=sr_breakout,
    )

    col_txt, col_hint = st.columns([3, 1])
    with col_txt:
        st.markdown("**Explanation**")
        for line in explanations:
            st.markdown(f"- {line}")
    with col_hint:
        st.caption(
            "🟢 Supports / uptrend · 🔴 Resistances / downtrend · "
            "🟠 EMA 9 · 🔵 SMA/EMA 20+ · Yellow = last price"
        )

    fig = build_structure_levels_chart(
        df,
        symbol=symbol,
        timeframe=timeframe,
        currency=currency,
        sr=sr,
        trendlines=trendlines,
        ema=ema,
        sma_ema=sma_ema,
        ema_ladder=ema_ladder,
        sr_breakout=sr_breakout,
        height=chart_height,
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": True})


def render_structure_chart_for_panel(
    df: Optional[pd.DataFrame],
    timeframe: str,
    currency: str,
    *,
    sma_ema: dict | None = None,
    ema_ladder: dict | None = None,
    sr_breakout: dict | None = None,
    sr: dict | None = None,
    trendlines: dict | None = None,
    ema: dict | None = None,
    height: int = 360,
) -> None:
    """Compact chart add-on for existing text panels (explanation already rendered)."""
    if df is None or df.empty:
        return
    fig = build_structure_levels_chart(
        df,
        timeframe=timeframe,
        currency=currency,
        sr=sr,
        trendlines=trendlines,
        ema=ema,
        sma_ema=sma_ema,
        ema_ladder=ema_ladder,
        sr_breakout=sr_breakout,
        height=height,
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
