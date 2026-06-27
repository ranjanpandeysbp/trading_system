"""
kn_smart_rsi_tab.py
-------------------
KN Smart DP SL + RSI MTF + VWMA Master Trend scanner — Groww & CoinDCX.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from app.market_pulse.ai_view import (
    STANDARD_REPORT_FORMAT,
    render_ai_config,
    show_ai_view_block,
)
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.kn_smart_rsi_engine import (
    MTF_DEFAULT,
    INTRADAY_OPTIONS,
    StrategyConfig,
    analyze_kn_smart,
)
from app.market_pulse.run_summary import (
    render_run_digest,
    render_run_summary,
    summarize_error,
    summarize_kn_smart_rsi,
)
from app.market_pulse.ta_screener_ui import render_ta_screener_options
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

REF_VIDEO_URL = "https://www.youtube.com/watch?v=2bAwEz12MrE"
PREFIX = "knsmart"
SECTION_ID = "kn_smart_rsi_mtf"

PHASE_ICONS = {
    "BUY_SIGNAL": "🟢",
    "SELL_SIGNAL": "🔴",
    "EXIT_SIGNAL": "🟠",
    "APPROACHING_BUY": "🟡",
    "APPROACHING_SELL": "🟡",
    "TREND_ALIGNED": "🔵",
    "SIDEWAYS": "⚪",
    "NEUTRAL": "⚪",
    "NO_DATA": "⏳",
}

KN_AI_SYSTEM = """You are an expert intraday trader using the KN Smart DP SL + RSI MTF + VWMA strategy.

Components:
1. **Daily VWMA master trend** — bullish if close > VWMA(20), bearish if below, sideways if VWMA flat
2. **KN Smart DP SL** — fast EMA(5) / slow EMA(12), entry line = midpoint, ATR chandelier trail SL, TP1/2/3 at 1/2/3× ATR
3. **RSI + SMA on RSI** — bullish when RSI > RSI-SMA and RSI > 50; bearish when RSI < RSI-SMA and RSI < 50
4. **MTF dashboard** — ≥3 of 4 timeframes must align (fast EMA > slow EMA for longs)

Entry LONG: master bullish + ribbon + green candle above entry line + RSI bullish + MTF aligned
Entry SHORT: master bearish + inverted ribbon + red candle below entry line + RSI bearish + MTF aligned
Exit: RSI overbought (>80) in bull trend or oversold (<30) in bear trend

Give concrete entry, trail SL, TP1/2/3, partial exit plan, hold time, green signs, red flags.
""" + STANDARD_REPORT_FORMAT


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _fmt_pct(val: float | None, *, sign: str = "+") -> str:
    if val is None:
        return "—"
    if sign == "-":
        return f"-{val:.2f}%"
    return f"+{val:.2f}%"


def build_kn_ai_prompt(symbol: str, market: str, analysis: dict, currency: str) -> str:
    live = analysis.get("live") or {}
    plan = analysis.get("trade_plan") or {}
    conds = live.get("conditions") or {}
    mtf = live.get("mtf") or {}
    lines = [
        "=== KN SMART DP SL + RSI MTF + VWMA ===",
        f"Symbol: {symbol}",
        f"Market: {market}",
        f"Intraday TF: {analysis.get('intraday_tf', '—')}",
        f"Phase: {analysis.get('phase')} — {analysis.get('primary_label', '')}",
        f"Master trend (daily VWMA): {analysis.get('master_trend', '—')}",
        f"Signal: {live.get('signal', 'HOLD')} · Confidence: {analysis.get('confidence', 0):.0f}%",
        f"Price: {currency}{live.get('close', 0):,.4f}",
        "",
        "=== LIVE INDICATORS ===",
        f"Fast EMA: {live.get('fast_ema', 0):.4f} · Slow EMA: {live.get('slow_ema', 0):.4f}",
        f"Entry line: {live.get('entry_line', 0):.4f} · Trail SL: {live.get('trail_sl', '—')}",
        f"RSI: {live.get('rsi', 0):.1f} · RSI SMA: {live.get('rsi_sma', 0):.1f}",
        f"ATR: {live.get('atr', 0):.4f}",
        "",
        "=== ENTRY CONDITIONS ===",
    ]
    for k, v in conds.items():
        lines.append(f"  {k}: {'✅' if v else '❌'}")
    lines.append("")
    lines.append("=== MTF DASHBOARD ===")
    for tf, bias in (mtf.get("timeframes") or {}).items():
        lines.append(f"  {tf}: {bias}")
    lines.append(
        f"Bullish TFs: {mtf.get('bullish_count', 0)} · Bearish TFs: {mtf.get('bearish_count', 0)}"
    )
    sc = analysis.get("signal_counts") or {}
    lines.extend([
        "",
        f"Recent signals (last ~120 bars): BUY {sc.get('buy', 0)} · SELL {sc.get('sell', 0)} · EXIT {sc.get('exit', 0)}",
    ])
    if plan:
        lines.extend([
            "",
            "=== TRADE PLAN ===",
            f"{plan.get('direction')} @ {currency}{plan.get('entry', 0):,.4f}",
            f"SL: {currency}{plan.get('stop_loss', 0):,.4f} ({_fmt_pct(plan.get('sl_pct'), sign='-')})",
            f"TP1: {currency}{plan.get('take_profit', 0):,.4f} ({_fmt_pct(plan.get('tp_pct'))})",
            f"TP2/TP3: {plan.get('tp2_pct', '—')}% / {plan.get('tp3_pct', '—')}%",
            f"Hold: {plan.get('hold_duration', '—')}",
        ])
    return "\n".join(lines)


def _build_chart(analysis: dict, symbol: str, currency: str) -> go.Figure:
    df = analysis.get("result_df")
    if df is None or df.empty:
        return go.Figure()

    tail = df.tail(min(150, len(df)))
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.62, 0.38],
        subplot_titles=(f"{symbol} — KN Smart ({analysis.get('intraday_tf', '')})", "RSI + SMA(RSI)"),
    )

    fig.add_trace(
        go.Candlestick(
            x=tail.index, open=tail["open"], high=tail["high"],
            low=tail["low"], close=tail["close"], name="OHLC",
        ),
        row=1, col=1,
    )
    fig.add_trace(go.Scatter(x=tail.index, y=tail["fast_ema"], name="Fast EMA", line=dict(color="#00e676", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=tail.index, y=tail["slow_ema"], name="Slow EMA", line=dict(color="#ff5252", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=tail.index, y=tail["entry_line"], name="Entry line", line=dict(color="#ffd54f", width=1, dash="dot")), row=1, col=1)
    if "trail_sl" in tail.columns:
        fig.add_trace(go.Scatter(x=tail.index, y=tail["trail_sl"], name="Trail SL", line=dict(color="#ef5350", width=1, dash="dash")), row=1, col=1)

    buys = tail[tail["signal"] == "BUY"]
    sells = tail[tail["signal"] == "SELL"]
    if not buys.empty:
        fig.add_trace(
            go.Scatter(x=buys.index, y=buys["close"], mode="markers", name="BUY",
                       marker=dict(symbol="triangle-up", size=9, color="#00e676")),
            row=1, col=1,
        )
    if not sells.empty:
        fig.add_trace(
            go.Scatter(x=sells.index, y=sells["close"], mode="markers", name="SELL",
                       marker=dict(symbol="triangle-down", size=9, color="#ff5252")),
            row=1, col=1,
        )

    fig.add_trace(go.Scatter(x=tail.index, y=tail["rsi"], name="RSI", line=dict(color="#4fc3f7")), row=2, col=1)
    fig.add_trace(go.Scatter(x=tail.index, y=tail["rsi_sma"], name="RSI SMA", line=dict(color="#ffd54f", dash="dash")), row=2, col=1)
    fig.add_hline(y=80, line_dash="dot", line_color="#ff9800", row=2, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="#78909c", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#69f0ae", row=2, col=1)

    fig.update_layout(
        template="plotly_dark", height=640, xaxis_rangeslider_visible=False,
        margin=dict(l=40, r=20, t=50, b=40), paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
    )
    fig.update_yaxes(title_text=f"Price ({currency.strip()})", row=1, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)
    return fig


def _render_setup_alerts(results: dict) -> None:
    buys, sells, approaching = [], [], []
    for tick, d in results.items():
        if d.get("error"):
            continue
        ph = d.get("phase", "")
        if ph == "BUY_SIGNAL":
            buys.append(tick)
        elif ph == "SELL_SIGNAL":
            sells.append(tick)
        elif ph.startswith("APPROACHING"):
            approaching.append(tick)
    if buys:
        st.success(f"**{len(buys)} BUY signal(s):** " + ", ".join(f"**{t}**" for t in buys[:10]))
    if sells:
        st.error(f"**{len(sells)} SELL signal(s):** " + ", ".join(f"**{t}**" for t in sells[:10]))
    if approaching:
        st.warning(f"**{len(approaching)} approaching setup(s):** " + ", ".join(f"**{t}**" for t in approaching[:10]))


def _render_screener_grid(results: dict) -> None:
    rows = []
    for tick, d in results.items():
        if d.get("error"):
            rows.append({"Ticker": tick, "Phase": "ERROR", "Trend": "—", "Signal": "—", "RSI": "—", "MTF": "—", "Conf.": "—", "_p": -1})
            continue
        live = d.get("live") or {}
        mtf = live.get("mtf") or {}
        plan = d.get("trade_plan") or {}
        rows.append({
            "Ticker": tick,
            "Phase": d.get("phase", "—"),
            "Trend": d.get("master_trend", "—"),
            "Signal": live.get("signal", "—"),
            "RSI": f"{live.get('rsi', 0):.0f}",
            "MTF": f"{mtf.get('bullish_count', 0)}↑ / {mtf.get('bearish_count', 0)}↓",
            "SL %": _fmt_pct(plan.get("sl_pct"), sign="-") if plan.get("sl_pct") else "—",
            "TP1 %": _fmt_pct(plan.get("tp_pct")) if plan.get("tp_pct") else "—",
            "Conf.": f"{d.get('confidence', 0):.0f}%",
            "_p": d.get("priority", 0),
        })
    st.markdown("#### 📋 Screener Grid")
    df = pd.DataFrame(rows).sort_values("_p", ascending=False)
    st.dataframe(df.drop(columns=["_p"]), width='stretch', hide_index=True)


def _render_conditions(conds: dict[str, bool]) -> None:
    labels = {
        "master_trend": "Daily VWMA trend",
        "ema_ribbon": "EMA ribbon",
        "candle": "Candle vs entry line",
        "rsi": "RSI + SMA filter",
        "mtf": "MTF alignment (≥3/4)",
    }
    cols = st.columns(len(labels))
    for col, (k, label) in zip(cols, labels.items()):
        ok = conds.get(k, False)
        col.metric(label, "✅" if ok else "❌")


def _render_result_block(ticker, data, is_crypto, market, provider, model, api_key):
    currency = "$" if is_crypto else "₹"
    if data.get("error"):
        st.error(data["error"])
        return

    live = data.get("live") or {}
    phase = data.get("phase", "NEUTRAL")
    icon = PHASE_ICONS.get(phase, "📊")
    st.markdown(f"### {icon} {data.get('primary_label', phase)}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Master Trend", data.get("master_trend", "—").upper())
    c2.metric("Signal", live.get("signal", "HOLD"))
    c3.metric("RSI", f"{live.get('rsi', 0):.1f}")
    c4.metric("Trail SL", f"{currency}{live.get('trail_sl', 0):,.2f}" if live.get("trail_sl") else "—")
    c5.metric("ATR", f"{live.get('atr', 0):.4f}")
    c6.metric("Confidence", f"{data.get('confidence', 0):.0f}%")

    st.markdown("#### ✅ Entry Condition Checklist")
    _render_conditions(live.get("conditions") or {})

    mtf = live.get("mtf") or {}
    if mtf.get("timeframes"):
        st.markdown("#### 📊 MTF Dashboard")
        mtf_rows = [{"TF": tf, "Bias": bias} for tf, bias in mtf["timeframes"].items()]
        st.dataframe(pd.DataFrame(mtf_rows), width='stretch', hide_index=True)

    plan = data.get("trade_plan")
    if plan:
        st.markdown("#### 🎯 Trade Plan (3-lot partial exits)")
        p1, p2, p3, p4, p5, p6 = st.columns(6)
        p1.metric("Direction", plan.get("direction", "—"))
        p2.metric("Entry", f"{currency}{plan.get('entry', 0):,.2f}")
        p3.metric("SL", _fmt_pct(plan.get("sl_pct"), sign="-"))
        p4.metric("TP1", _fmt_pct(plan.get("tp_pct")))
        p5.metric("TP2", _fmt_pct(plan.get("tp2_pct")))
        p6.metric("TP3", _fmt_pct(plan.get("tp3_pct")))
        st.caption(
            f"Trail SL {currency}{plan.get('stop_loss', 0):,.4f} · "
            f"TP1 {currency}{plan.get('take_profit', 0):,.4f} · "
            f"Hold {plan.get('hold_duration', '—')} · "
            f"Move SL to breakeven after TP1"
        )

    sc = data.get("signal_counts") or {}
    st.caption(f"Recent bar signals: **{sc.get('buy', 0)}** BUY · **{sc.get('sell', 0)}** SELL · **{sc.get('exit', 0)}** EXIT")

    st.plotly_chart(_build_chart(data, ticker, currency), width='stretch', config={"displayModeBar": False})

    render_run_summary(summarize_kn_smart_rsi(data, ticker))
    show_ai_view_block(
        session_prefix=PREFIX,
        result_key=_safe_key(f"{ticker}_{data.get('intraday_tf', '')}"),
        symbol=ticker,
        timeframe_label=f"KN Smart {data.get('intraday_tf', '')}",
        build_prompt_fn=lambda t=ticker, m=market, a=data, c=currency: build_kn_ai_prompt(t, m, a, c),
        system_prompt=KN_AI_SYSTEM,
        provider=provider, model=model, api_key=api_key,
        button_in_column=False,
    )


def render_kn_smart_rsi_tab():
    st.markdown("<h1>⚡ KN Smart DP SL + RSI MTF + VWMA</h1>", unsafe_allow_html=True)

    st.write(
        "Scan **Groww** and **CoinDCX** tickers for live KN Smart signals filtered by "
        "daily VWMA master trend and multi-timeframe EMA alignment."
    )

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets master trend, MTF dashboard, and trade plan per ticker.",
    )

    st.markdown("---")
    m1, m2 = st.columns(2)
    with m1:
        kn_market = st.selectbox("🌐 Market", MARKET_OPTIONS, key="kn_market")
    with m2:
        kn_exchange = st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="kn_exchange") if is_india_market(kn_market) else "NSE"

    st.markdown("### 📊 Tickers")
    kn_tickers: list[str] = []
    is_crypto = is_crypto_market(kn_market)
    if is_crypto:
        kn_tickers = render_coindcx_ticker_selection("knsmart")
    else:
        kn_tickers = render_equity_index_ticker_selection(kn_market, "knsmart")

    st.markdown("### ⏱️ Timeframes & Parameters")
    from app.market_pulse.ta_mtf_hub_ui import (
        render_ta_hub_badge,
        render_ta_multiselect_timeframes,
        render_ta_single_timeframe,
    )

    render_ta_hub_badge("knsmart")
    t1, t2, t3, t4 = st.columns(4)
    with t1:
        kn_intraday = render_ta_single_timeframe(
            "knsmart",
            INTRADAY_OPTIONS,
            role="LTF",
            legacy_default="15m",
            label="Intraday TF",
            widget_key="kn_intraday",
            show_hub_note=False,
        )
    with t2:
        kn_mtf = render_ta_multiselect_timeframes(
            "knsmart_mtf",
            MTF_DEFAULT,
            legacy_default=MTF_DEFAULT,
            label="MTF dashboard TFs",
            show_hub_note=False,
        )
    with t3:
        kn_bars = st.slider("Bars to load", 200, 600, 400, 50, key="kn_bars")
    with t4:
        kn_mtf_min = st.number_input("Min aligned TFs", 2, 4, 3, key="kn_mtf_min")

    with st.expander("⚙️ Advanced indicator settings", expanded=False):
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            kn_fast = st.number_input("Fast EMA", 3, 10, 5, key="kn_fast")
            kn_slow = st.number_input("Slow EMA", 8, 21, 12, key="kn_slow")
        with a2:
            kn_atr_p = st.number_input("ATR period", 7, 21, 14, key="kn_atr_p")
            kn_atr_m = st.number_input("ATR SL mult", 1.0, 3.0, 1.5, 0.1, key="kn_atr_m")
        with a3:
            kn_rsi = st.number_input("RSI length", 7, 21, 14, key="kn_rsi")
            kn_vwma = st.number_input("VWMA period (daily)", 10, 50, 20, key="kn_vwma")
        with a4:
            kn_tp1 = st.number_input("TP1 × ATR", 0.5, 2.0, 1.0, 0.5, key="kn_tp1")
            kn_tp2 = st.number_input("TP2 × ATR", 1.0, 3.0, 2.0, 0.5, key="kn_tp2")
            kn_tp3 = st.number_input("TP3 × ATR", 2.0, 5.0, 3.0, 0.5, key="kn_tp3")

    kn_actionable = render_ta_screener_options("knsmart")
    st.caption(f"🧮 **{len(kn_tickers)}** ticker(s) · intraday **{kn_intraday}** · MTF **{', '.join(kn_mtf)}**")

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button("🔎 RUN KN SMART SCAN", type="primary", width='stretch', key="kn_run")
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('kn_last_scan', '—')}")

    cfg = StrategyConfig(
        fast_ema=int(kn_fast), slow_ema=int(kn_slow),
        atr_period=int(kn_atr_p), atr_multiplier=float(kn_atr_m),
        rsi_length=int(kn_rsi), vwma_period=int(kn_vwma),
        tp_ratios=[float(kn_tp1), float(kn_tp2), float(kn_tp3)],
        mtf_min_bullish=int(kn_mtf_min), mtf_min_bearish=int(kn_mtf_min),
    )

    if run_btn:
        if not kn_tickers:
            st.error("Select at least one ticker.")
            return
        if not kn_mtf:
            st.error("Select at least one MTF timeframe.")
            return
        bar = st.progress(0, text="Running KN Smart scan…")
        groww_token = get_active_groww_token()
        results = {}
        for i, tick in enumerate(kn_tickers):
            bar.progress((i + 1) / len(kn_tickers), text=f"{tick} — KN Smart analysis…")
            try:
                results[tick] = analyze_kn_smart(
                    tick, kn_market, kn_intraday, kn_mtf,
                    groww_token, kn_exchange, kn_bars, cfg,
                )
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)
        bar.empty()
        st.session_state.kn_results = results
        st.session_state.kn_results_market = kn_market
        st.session_state.kn_is_crypto = is_crypto
        st.session_state.kn_intraday_tf = kn_intraday
        st.session_state.kn_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("kn_results", {})
    market_disp = st.session_state.get("kn_results_market", kn_market)
    is_crypto = st.session_state.get("kn_is_crypto", is_crypto)

    if not results:
        st.info("Select tickers and click **RUN KN SMART SCAN**.")
        return

    st.markdown("---")
    _render_setup_alerts(results)
    _render_screener_grid(results)

    digest = []
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, kn_intraday, d["error"], tab="KN Smart RSI MTF"))
        else:
            digest.append(summarize_kn_smart_rsi(d, tick))
    if kn_actionable:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 KN Smart Recommendations", group_filter=True)

    for ti, tick in enumerate(sorted(results.keys(), key=lambda t: results[t].get("priority", 0), reverse=True)):
        data = results[tick]
        if kn_actionable and not data.get("error") and not data.get("actionable"):
            continue
        summary = next((s for s in digest if s.get("ticker") == tick), None)
        with st.expander(
            ticker_section_label(tick, [summary] if summary else []),
            expanded=should_expand_ticker(ti) and not data.get("error") and data.get("actionable", False),
        ):
            _render_result_block(tick, data, is_crypto, market_disp, provider, model, api_key)

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai(SECTION_ID)

    st.caption("⚠️ Intraday signals — use trail SL and partial exits at TP1/TP2/TP3.")
