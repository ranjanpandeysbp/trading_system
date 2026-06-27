"""
fakeout_4h_tab.py
-----------------
5min – 4hrs Breakout-Fakeout **live screener** for Groww & CoinDCX.
Scans tickers for approaching, active, and ready fakeout trade setups.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from app.market_pulse.ai_view import (
    STANDARD_REPORT_FORMAT,
    render_ai_config,
    show_ai_view_block,
)
from app.market_pulse.demo_trading import render_demo_trade_panel
from app.market_pulse.env_config import api_key_env_hint
from app.market_pulse.fakeout_4h_engine import (
    normalize_ohlcv,
    run_fakeout_screener,
    session_mode_for_market,
)
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import (
    render_run_digest,
    render_run_summary,
    summarize_error,
    summarize_fakeout_4h,
)
from app.market_pulse.ta_screener_ui import render_strategy_mtf_panel
from app.market_pulse.ta_ticker_sections import should_expand_ticker, ticker_section_label
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
)


FAKEOUT_AI_SYSTEM = """You are an expert intraday fakeout/breakout screener analyst for Indian equities and crypto futures.

The screener flags:
- ENTRY_READY: fakeout confirmed — fade trade active
- BREAKOUT_ACTIVE: breakout in progress — fakeout re-entry imminent
- APPROACHING_HIGH/LOW: price near 4H range edge — breakout may start soon
- MONITORING: inside range, no imminent setup

Groww: IST 09:15–13:15 range, signals 13:15–15:30 IST. CoinDCX: NY 00:00–04:00 range.

Recommend only when setup phase and prices support action. Otherwise WAIT.
""" + STANDARD_REPORT_FORMAT

REF_VIDEO_URL = "https://www.youtube.com/watch?v=O5eC5lY7ZXY&start=65"

PHASE_ICONS = {
    "ENTRY_READY": "🟢",
    "BREAKOUT_ACTIVE": "🟡",
    "APPROACHING_HIGH": "🔶",
    "APPROACHING_LOW": "🔶",
    "MONITORING": "⚪",
    "WAIT_RANGE": "⏳",
    "SESSION_CLOSED": "🔒",
    "NO_RANGE": "—",
    "NO_DATA": "⚠️",
}


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _plotly_dt(ts) -> datetime | None:
    """Convert pandas Timestamp to plain datetime for Plotly shapes/lines."""
    if ts is None:
        return None
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime()
    return ts


def _plotly_x_series(index: pd.Index) -> list:
    return [_plotly_dt(t) for t in index]


def _plan_sl_tp_pct(plan: dict | None) -> tuple[float | None, float | None]:
    """Return (risk_pct, reward_pct) from plan, computing from prices if needed."""
    if not plan or not plan.get("entry"):
        return None, None
    entry = float(plan["entry"])
    if entry <= 0:
        return None, None
    risk = plan.get("risk_pct")
    reward = plan.get("reward_pct")
    if risk is None and plan.get("stop_loss") is not None:
        risk = round(abs(entry - float(plan["stop_loss"])) / entry * 100, 2)
    if reward is None and plan.get("take_profit") is not None:
        reward = round(abs(float(plan["take_profit"]) - entry) / entry * 100, 2)
    return risk, reward


def _fmt_sl_pct(plan: dict | None) -> str:
    risk, _ = _plan_sl_tp_pct(plan)
    return f"-{risk:.2f}%" if risk is not None else "—"


def _fmt_tp_pct(plan: dict | None) -> str:
    _, reward = _plan_sl_tp_pct(plan)
    return f"+{reward:.2f}%" if reward is not None else "—"


def fetch_5m_screener_data(
    symbol: str,
    market: str,
    groww_token: str,
    exchange: str,
    lookback_bars: int = 400,
) -> pd.DataFrame:
    """Fetch recent 5M OHLCV for live screener (today + prior session)."""
    df = fetch_data_for_gap_scan(
        symbol, "5m", market, groww_token, exchange, limit=lookback_bars,
    )
    return normalize_ohlcv(df)


def build_fakeout_ai_prompt(
    symbol: str,
    market: str,
    analysis: dict,
    currency: str,
) -> str:
    session_mode = analysis.get("session_mode") or session_mode_for_market(market)
    session_label = "IST (NSE/BSE)" if session_mode == "india" else "NY"
    sc = analysis.get("screener") or analysis.get("live_setup") or {}

    lines = [
        "=== 5MIN – 4HR FAKEOUT SCREENER ===",
        f"Symbol: {symbol}",
        f"Market: {market}",
        f"Session: {session_label}",
        f"Primary phase: {sc.get('primary_phase', 'N/A')} — {sc.get('primary_label', '')}",
        f"Actionable: {sc.get('actionable', False)}",
        "",
    ]

    if analysis.get("current_price") is not None:
        lines.append(f"Current price: {currency}{analysis['current_price']:,.4f}")

    lines.extend([
        "",
        "=== RANGE & STATUS ===",
        f"Status: {sc.get('status', 'N/A')}",
        f"Message: {sc.get('message', '')}",
        f"Session date: {sc.get('session_date', 'N/A')}",
    ])
    if sc.get("range_high") is not None:
        lines.append(f"Range High: {currency}{sc['range_high']:,.4f}")
        lines.append(f"Range Low: {currency}{sc['range_low']:,.4f}")
        lines.append(f"Price vs range: {sc.get('price_vs_range', 'N/A')}")

    setups = sc.get("setups") or []
    if setups:
        lines.append("\n=== DETECTED SETUPS ===")
        for i, su in enumerate(setups, 1):
            lines.append(f"  {i}. [{su.get('phase')}] {su.get('label')} — {su.get('hint', '')}")
            tp = su.get("trade_plan")
            if tp:
                lines.append(
                    f"     Plan: {tp['direction'].upper()} entry {currency}{tp['entry']:,.4f} "
                    f"SL {_fmt_sl_pct(tp)} TP {_fmt_tp_pct(tp)}"
                )

    plan = sc.get("trade_plan")
    if plan:
        lines.extend([
            "",
            "=== PRIMARY TRADE PLAN ===",
            f"Direction: {plan['direction'].upper()}",
            f"Entry: {currency}{plan['entry']:,.4f}",
            f"Stop Loss: {_fmt_sl_pct(plan)} ({currency}{plan['stop_loss']:,.4f})",
            f"Take Profit: {_fmt_tp_pct(plan)} ({currency}{plan['take_profit']:,.4f})",
            f"R:R: {plan.get('rr_ratio', 2):.1f}",
        ])

    return "\n".join(lines)


def _build_screener_chart(df_5m: pd.DataFrame, analysis: dict, symbol: str) -> go.Figure:
    """5M candlesticks with 4H range window, TOP/BOTTOM lines, and signal zone."""
    df = normalize_ohlcv(df_5m)
    if df.empty:
        return go.Figure()

    sc = analysis.get("screener") or {}
    session_mode = analysis.get("session_mode", "ny")
    rh, rl = sc.get("range_high"), sc.get("range_low")
    r_start = sc.get("range_start")
    r_end = sc.get("range_end")
    s_end = sc.get("session_end")
    range_label = sc.get("range_label") or ("09:15–13:15 IST" if session_mode == "india" else "00:00–04:00 NY")
    c_open = sc.get("candle_open")
    c_close = sc.get("candle_close")

    x_vals = _plotly_x_series(df.index)
    r_start_x = _plotly_dt(r_start)
    r_end_x = _plotly_dt(r_end)
    line_x1 = _plotly_dt(s_end if s_end is not None else df.index[-1])

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x_vals,
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="5M",
        increasing_line_color="#22c55e",
        decreasing_line_color="#ef4444",
    ))

    # 4H range formation window (shaded)
    if r_start_x is not None and r_end_x is not None:
        fig.add_shape(
            type="rect",
            x0=r_start_x, x1=r_end_x,
            y0=0, y1=1,
            xref="x", yref="paper",
            fillcolor="rgba(59, 130, 246, 0.14)",
            line=dict(color="rgba(59, 130, 246, 0.45)", width=1),
            layer="below",
        )
        fig.add_annotation(
            x=r_start_x, y=1, yref="paper",
            text=f"4H candle · {range_label}",
            showarrow=False,
            yanchor="bottom",
            font=dict(size=11, color="#93c5fd"),
            bgcolor="rgba(15, 23, 42, 0.6)",
        )

    # 4H candle body (open → close) inside the range window
    if (
        rh is not None and rl is not None
        and r_start_x is not None and r_end_x is not None
        and c_open is not None and c_close is not None
    ):
        body_top = max(c_open, c_close)
        body_bot = min(c_open, c_close)
        fig.add_shape(
            type="rect",
            x0=r_start_x, x1=r_end_x, y0=body_bot, y1=body_top,
            xref="x", yref="y",
            line=dict(color="#f59e0b", width=1.5),
            fillcolor="rgba(245, 158, 11, 0.18)",
            layer="below",
        )

    # 4H TOP / BOTTOM — full-width reference lines + bold segment after range completes
    if rh is not None and rl is not None:
        for y_val, color, label in (
            (rh, "#ef4444", "4H TOP"),
            (rl, "#10b981", "4H BOTTOM"),
        ):
            fig.add_hline(
                y=y_val,
                line_dash="dot",
                line_color=color,
                line_width=1,
                opacity=0.35,
            )
            if r_end_x is not None and line_x1 is not None:
                fig.add_shape(
                    type="line",
                    x0=r_end_x, x1=line_x1, y0=y_val, y1=y_val,
                    xref="x", yref="y",
                    line=dict(color=color, width=2.5),
                    layer="above",
                )
            if line_x1 is not None:
                fig.add_annotation(
                    x=line_x1, y=y_val,
                    text=f"{label} {y_val:,.2f}",
                    showarrow=False,
                    xanchor="left",
                    xshift=4,
                    font=dict(size=10, color=color),
                    bgcolor="rgba(15, 23, 42, 0.85)",
                    bordercolor=color,
                    borderwidth=1,
                )

    # Vertical marker: signal window starts after 4H range completes
    if r_end_x is not None:
        fig.add_shape(
            type="line",
            x0=r_end_x, x1=r_end_x,
            y0=0, y1=1,
            xref="x", yref="paper",
            line=dict(color="#94a3b8", width=1.5, dash="dash"),
            layer="above",
        )
        fig.add_annotation(
            x=r_end_x, y=1, yref="paper",
            text="Breakout / fakeout zone →",
            showarrow=False,
            yanchor="bottom",
            font=dict(size=10, color="#94a3b8"),
        )

    # Current price marker
    price = sc.get("current_price") or analysis.get("current_price")
    if price is not None:
        fig.add_hline(
            y=price,
            line_dash="dashdot",
            line_color="#e2e8f0",
            line_width=1,
            opacity=0.7,
            annotation_text="Price",
            annotation_position="left",
            annotation_font_color="#e2e8f0",
        )

    title_suffix = f" · {range_label}" if range_label else ""
    fig.update_layout(
        title=dict(
            text=f"{symbol} — 5M screener{title_suffix}",
            font=dict(size=14),
        ),
        xaxis_rangeslider_visible=False,
        height=420,
        template="plotly_dark",
        margin=dict(l=48, r=88, t=48, b=28),
        legend=dict(orientation="h", y=1.02, x=0),
        yaxis=dict(title="Price", gridcolor="#1e293b"),
        xaxis=dict(gridcolor="#1e293b"),
    )
    return fig


def _render_priority_screener_charts(results: dict, is_crypto: bool, *, max_charts: int = 3) -> None:
    """Show charts for highest-priority tickers directly in the screener panel."""
    ranked = []
    for tick, d in results.items():
        if "error" in d:
            continue
        sc = (d.get("analysis") or {}).get("screener") or {}
        if sc.get("range_high") is None or sc.get("range_low") is None:
            continue
        ranked.append((sc.get("priority", 0), tick, d))
    if not ranked:
        return

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[:max_charts]
    st.markdown("### 📈 4H Range Chart — Top / Bottom Lines")
    st.caption(
        "Blue zone = 4H range forming · **Red** = 4H TOP (high) · **Green** = 4H BOTTOM (low) · "
        "Solid lines extend into the breakout/fakeout window after the range completes."
    )
    cols = st.columns(len(top))
    for col, (_, tick, d) in zip(cols, top):
        with col:
            analysis = d["analysis"]
            sc = analysis.get("screener") or {}
            phase = sc.get("primary_phase", "—")
            icon = PHASE_ICONS.get(phase, "📊")
            st.markdown(f"**{icon} {tick}** · {sc.get('primary_label', phase)}")
            st.plotly_chart(
                _build_screener_chart(d["df"], analysis, tick),
                width='stretch',
                config={"displayModeBar": False},
            )


def _render_setup_cards(setups: list[dict], currency: str) -> None:
    if not setups:
        st.info("No setups detected for this ticker.")
        return
    for su in setups:
        phase = su.get("phase", "")
        icon = PHASE_ICONS.get(phase, "•")
        with st.container(border=True):
            st.markdown(f"**{icon} {su.get('label', phase)}**")
            st.caption(su.get("hint", ""))
            if su.get("direction"):
                st.markdown(f"Bias: **{su['direction']}**")
            tp = su.get("trade_plan")
            if tp:
                risk, reward = _plan_sl_tp_pct(tp)
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Entry", f"{currency}{tp['entry']:,.4f}")
                c2.metric("Stop Loss", _fmt_sl_pct(tp))
                c3.metric("Take Profit", _fmt_tp_pct(tp))
                c4.metric("R:R", f"{tp.get('rr_ratio', 2):.1f}")
                c5.metric("Exp. move", f"+{reward:.2f}%" if reward is not None else "—")
                if risk is not None and reward is not None:
                    st.caption(
                        f"Prices: SL {currency}{tp['stop_loss']:,.4f} · "
                        f"TP {currency}{tp['take_profit']:,.4f} · "
                        f"Risk {risk:.2f}% → Reward {reward:.2f}%"
                    )


def _render_screener_alerts(results: dict, is_crypto: bool) -> None:
    """Top banner: count of actionable / approaching setups."""
    actionable = []
    approaching = []
    for tick, d in results.items():
        if "error" in d:
            continue
        sc = (d.get("analysis") or {}).get("screener") or {}
        phase = sc.get("primary_phase", "")
        if phase == "ENTRY_READY":
            actionable.append((tick, sc))
        elif phase in ("BREAKOUT_ACTIVE", "APPROACHING_HIGH", "APPROACHING_LOW"):
            approaching.append((tick, sc))

    if actionable:
        st.success(
            f"**{len(actionable)} ticker(s) with READY fakeout entry:** "
            + ", ".join(f"**{t}** ({s.get('primary_label', '')})" for t, s in actionable)
        )
    if approaching:
        st.warning(
            f"**{len(approaching)} ticker(s) with approaching / active setup:** "
            + ", ".join(f"**{t}** ({s.get('primary_label', '')})" for t, s in approaching)
        )
    if not actionable and not approaching:
        st.info("No immediate setups — expand tickers below or re-scan. Setups appear when price nears range edges or a fakeout triggers.")


def _render_screener_table(results: dict, is_crypto: bool) -> None:
    """Compact screener grid sorted by urgency."""
    currency = "$" if is_crypto else "₹"
    rows = []
    for tick, d in results.items():
        if "error" in d:
            rows.append({
                "Ticker": tick,
                "Phase": "ERROR",
                "Setup": d["error"][:60],
                "Direction": "—",
                "Price": "—",
                "Range": "—",
                "Entry": "—",
                "SL %": "—",
                "TP %": "—",
                "Priority": 0,
            })
            continue
        sc = (d.get("analysis") or {}).get("screener") or {}
        price = sc.get("current_price")
        rh, rl = sc.get("range_high"), sc.get("range_low")
        plan = sc.get("trade_plan") or {}
        # Fallback: use first setup with a trade plan (e.g. BREAKOUT_ACTIVE projected)
        if not plan:
            for su in sc.get("setups") or []:
                if su.get("trade_plan"):
                    plan = su["trade_plan"]
                    break
        rows.append({
            "Ticker": tick,
            "Phase": sc.get("primary_phase", "—"),
            "Setup": sc.get("primary_label", "—"),
            "Direction": plan.get("direction", sc.get("setups", [{}])[0].get("direction", "—") if sc.get("setups") else "—"),
            "Price": f"{currency}{price:,.2f}" if price else "—",
            "Range": f"{currency}{rl:,.2f} – {currency}{rh:,.2f}" if rh and rl else "—",
            "Entry": f"{currency}{plan['entry']:,.2f}" if plan.get("entry") else "—",
            "SL %": _fmt_sl_pct(plan),
            "TP %": _fmt_tp_pct(plan),
            "Priority": sc.get("priority", 0),
        })

    if not rows:
        return
    df = pd.DataFrame(rows).sort_values("Priority", ascending=False)
    st.markdown("### 📋 Live Screener Grid")
    st.dataframe(
        df.drop(columns=["Priority"]),
        width='stretch',
        hide_index=True,
    )


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
    safe = _safe_key(key)

    if "error" in data:
        st.error(f"**{symbol}** — {data['error']}")
        return

    analysis = data["analysis"]
    df = data["df"]
    sc = analysis.get("screener") or {}

    def _body() -> None:
        render_run_summary(summarize_fakeout_4h(analysis, symbol))
        plan_mtf = sc.get("trade_plan") or {}
        if not plan_mtf:
            for su in sc.get("setups") or []:
                if su.get("trade_plan"):
                    plan_mtf = su["trade_plan"]
                    break
        render_strategy_mtf_panel(
            symbol=symbol,
            market=market,
            groww_token=get_active_groww_token(),
            exchange=st.session_state.get("f4h_results_exchange", "NSE"),
            primary_tf="5m",
            strategy_direction=plan_mtf.get("direction"),
        )

        session_mode = analysis.get("session_mode", "ny")
        range_title = (
            "4H Range (IST · 09:15–13:15)"
            if session_mode == "india"
            else "4H Range (NY Session)"
        )
        st.markdown(f"### 📍 {range_title}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Range High", f"{currency}{sc.get('range_high', 0):,.2f}" if sc.get("range_high") else "—")
        c2.metric("Range Low", f"{currency}{sc.get('range_low', 0):,.2f}" if sc.get("range_low") else "—")
        c3.metric("Phase", sc.get("primary_phase", "—"))
        c4.metric("Price vs Range", sc.get("price_vs_range", "—"))
        st.caption(sc.get("message", ""))

        plan = sc.get("trade_plan") or {}
        if not plan:
            for su in sc.get("setups") or []:
                if su.get("trade_plan"):
                    plan = su["trade_plan"]
                    break
        if plan:
            risk, reward = _plan_sl_tp_pct(plan)
            st.markdown("### 🎯 Trade Plan")
            p1, p2, p3, p4, p5 = st.columns(5)
            p1.metric("Entry", f"{currency}{plan['entry']:,.4f}")
            p2.metric("Stop Loss", _fmt_sl_pct(plan))
            p3.metric("Take Profit", _fmt_tp_pct(plan))
            p4.metric("R:R", f"{plan.get('rr_ratio', 2):.1f}")
            p5.metric("Direction", plan.get("direction", "—").upper())
            if risk is not None and reward is not None:
                st.caption(
                    f"SL at {currency}{plan['stop_loss']:,.4f} ({risk:.2f}% from entry) · "
                    f"TP at {currency}{plan['take_profit']:,.4f} ({reward:.2f}% from entry)"
                )

        st.markdown("### 📈 5M Chart · 4H TOP / BOTTOM Lines")
        st.plotly_chart(
            _build_screener_chart(df, analysis, symbol),
            width='stretch',
            config={"displayModeBar": True},
        )

        st.markdown("### 🎯 Detected Setups")
        _render_setup_cards(sc.get("setups") or [], currency)

        st.markdown("### 🤖 AI View")
        if not api_key:
            st.info(f"💡 Set API keys in `.env` to enable AI View. {api_key_env_hint(provider)}")
        else:
            show_ai_view_block(
                session_prefix="f4h",
                result_key=safe,
                symbol=symbol,
                timeframe_label="5M",
                build_prompt_fn=lambda s=symbol, m=market, a=analysis, c=currency: build_fakeout_ai_prompt(
                    s, m, a, c,
                ),
                system_prompt=FAKEOUT_AI_SYSTEM,
                provider=provider,
                model=model,
                api_key=api_key,
                button_in_column=False,
            )

        plan = sc.get("trade_plan")
        if plan and sc.get("primary_phase") == "ENTRY_READY":
            render_demo_trade_panel(
                "f4h",
                safe,
                symbol,
                "5m",
                market,
                f"Fakeout · {plan['direction'].upper()}",
                current_price=analysis.get("current_price"),
                source_tab="5min-4hr Screener",
                groww_token=get_active_groww_token(),
                exchange=st.session_state.get("f4h_results_exchange", "NSE"),
            )

    if nested:
        _body()
        return

    phase = sc.get("primary_phase", "SCAN")
    icon = PHASE_ICONS.get(phase, "📊")
    with st.expander(f"{icon} **{symbol}** — {sc.get('primary_label', phase)}", expanded=False):
        _body()


def render_fakeout_4h_tab():
    """5min – 4hrs Breakout-Fakeout live screener."""
    st.markdown("<h1>🔎 5min – 4hrs Breakout Screener</h1>", unsafe_allow_html=True)
    st.write(
        "Scans **multiple tickers** on **5M** for approaching and active fakeout setups. "
        "**Groww:** 4H range **09:15–13:15 IST**, signals **13:15–15:30 IST**. "
        "**CoinDCX:** NY 4H range. Alerts when breakouts, fakeouts, or edge approaches are detected."
    )

    provider, model, api_key = render_ai_config(
        "fakeout_4h",
        caption="AI View interprets screener phases and trade plans per ticker.",
    )

    st.markdown("---")
    m1, m2 = st.columns(2)
    with m1:
        f4h_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            key="f4h_market",
        )
    with m2:
        f4h_exchange = st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="f4h_exchange") if is_india_market(f4h_market) else "NSE"

    st.markdown("### 📊 Tickers")
    f4h_tickers: list[str] = []
    if is_crypto_market(f4h_market):
        f4h_tickers = render_coindcx_ticker_selection("f4h")
    else:
        f4h_tickers = render_equity_index_ticker_selection(f4h_market, "f4h")

    is_crypto = is_crypto_market(f4h_market)

    from app.market_pulse.ta_mtf_hub_ui import render_ta_fixed_scan_note

    render_ta_fixed_scan_note("5m", engine_label="5min–4hr breakout engine")

    st.markdown("### ⚙️ Screener Parameters")
    tfc1, tfc2, tfc3, tfc4 = st.columns(4)
    with tfc1:
        f4h_rr = st.number_input("Reward : Risk", min_value=1.0, max_value=5.0, value=2.0, step=0.5, key="f4h_rr")
    with tfc2:
        f4h_approach = st.slider("Approaching edge (× range)", 0.05, 0.35, 0.15, 0.05, key="f4h_approach")
    with tfc3:
        f4h_bars = st.slider("5M bars to load", 150, 600, 350, 50, key="f4h_bars")
    with tfc4:
        f4h_actionable_only = st.checkbox("Show actionable only", value=False, key="f4h_actionable_only")

    with st.expander("⚙️ Advanced", expanded=False):
        f4h_large_brk = st.slider("Large breakout threshold (× range)", 0.2, 1.0, 0.5, 0.1, key="f4h_large_brk")
        f4h_max_sl = st.number_input(
            "Max SL % of entry",
            min_value=0.001, max_value=0.02, value=0.005, step=0.001, format="%.3f",
            key="f4h_max_sl",
        )
        f4h_auto_refresh = st.checkbox("Auto-refresh scan (2 min)", value=False, key="f4h_auto_refresh")

    total = len(f4h_tickers)
    session_hint = "IST 09:15–15:30" if not is_crypto else "NY 4H range"
    st.caption(f"🧮 **{total}** ticker(s) · live 5M screener · {session_hint}")

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button(
            "🔎 SCAN FOR FAKEOUT SETUPS",
            type="primary",
            width='stretch',
            key="f4h_run",
        )
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('f4h_last_scan', '—')}")

    if run_btn or st.session_state.get("f4h_auto_refresh_trigger"):
        st.session_state.pop("f4h_auto_refresh_trigger", None)
        if not f4h_tickers:
            st.error("Select at least one ticker.")
            return
        results = {}
        bar = st.progress(0, text="Scanning tickers…")
        groww_token = get_active_groww_token()
        session_mode = session_mode_for_market(f4h_market)
        for i, tick in enumerate(f4h_tickers):
            bar.progress((i + 1) / total, text=f"{tick} — scanning 5M…")
            try:
                df = fetch_5m_screener_data(
                    tick, f4h_market, groww_token, f4h_exchange, f4h_bars,
                )
                if df.empty or len(df) < 30:
                    results[tick] = {
                        "error": f"Insufficient 5M data ({len(df)} bars).",
                        "symbol": tick,
                    }
                    continue
                analysis = run_fakeout_screener(
                    df,
                    rr_ratio=f4h_rr,
                    large_breakout_threshold=f4h_large_brk,
                    max_sl_pct=f4h_max_sl,
                    session_mode=session_mode,
                    approach_pct=f4h_approach,
                )
                results[tick] = {"df": df, "analysis": analysis, "symbol": tick}
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)
        bar.empty()
        st.session_state.f4h_results = results
        st.session_state.f4h_results_market = f4h_market
        st.session_state.f4h_is_crypto = is_crypto
        st.session_state.f4h_results_exchange = f4h_exchange
        st.session_state.f4h_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("f4h_results", {})
    market_disp = st.session_state.get("f4h_results_market", f4h_market)
    is_crypto = st.session_state.get("f4h_is_crypto", is_crypto)

    if not results:
        st.info("Select tickers and click **SCAN FOR FAKEOUT SETUPS** to find approaching or ready trades.")
        return

    st.markdown("---")
    _render_screener_alerts(results, is_crypto)
    _render_screener_table(results, is_crypto)
    _render_priority_screener_charts(results, is_crypto, max_charts=3)

    digest = []
    for tick, d in results.items():
        if "error" in d:
            digest.append(summarize_error(d["symbol"], "5m", d["error"], tab="5min-4hr Screener"))
        else:
            digest.append(summarize_fakeout_4h(d["analysis"], d["symbol"]))

    if f4h_actionable_only:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 Screener Recommendations", group_filter=True)

    if not api_key:
        st.info("💡 Add API keys for **AI View** on each ticker.")

    tickers_sorted = sorted(
        results.keys(),
        key=lambda t: (
            (results[t].get("analysis") or {}).get("screener") or {}
        ).get("priority", 0),
        reverse=True,
    )

    for ti, ticker in enumerate(tickers_sorted):
        data = results[ticker]
        if f4h_actionable_only and "error" not in data:
            sc = (data.get("analysis") or {}).get("screener") or {}
            if not sc.get("actionable"):
                continue

        summary = next((s for s in digest if s.get("ticker") == ticker), None)
        summaries = [summary] if summary else []

        with st.expander(
            ticker_section_label(ticker, summaries),
            expanded=should_expand_ticker(ti) and (
                "error" not in data
                and ((data.get("analysis") or {}).get("screener") or {}).get("actionable", False)
            ),
        ):
            if "error" in data:
                st.error(data["error"])
            else:
                _render_result_block(
                    ticker, data, is_crypto, market_disp,
                    provider, model, api_key, nested=True,
                )

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("fakeout_4h")

    if st.session_state.get("f4h_auto_refresh"):
        time.sleep(120)
        st.session_state.f4h_auto_refresh_trigger = True
        st.rerun()

    st.caption(
        "⚠️ Screener flags approaching setups — always confirm on 5M chart before entry."
    )
