"""
smart_wave_crypto_tab.py
------------------------
Smart Wave Academy crypto strategies — CoinDCX only.
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
from app.market_pulse.run_summary import (
    render_run_digest,
    render_run_summary,
    summarize_error,
    summarize_smart_wave_crypto,
)
from app.market_pulse.smart_wave_crypto_engine import (
    MAX_LEVERAGE,
    RISK_PER_TRADE_INR,
    RR_RATIO,
    SMART_WAVE_TF_OPTIONS,
    STRATEGY_KEYS,
    STRATEGY_LABELS,
    TRADE_SIZE_BTC_INR,
    TRADE_SIZE_INR,
    analyze_smart_wave,
    liquidation_distance,
    phase_parameters,
)
from app.market_pulse.ta_screener_ui import render_ta_screener_options, render_strategy_mtf_panel
from app.market_pulse.ta_ticker_sections import should_expand_ticker, ticker_section_label
from app.market_pulse.ticker_selection_ui import render_coindcx_ticker_selection

PREFIX = "smartwave"
SECTION_ID = "smart_wave_crypto"
MARKET = "CoinDCX Futures"

PHASE_ICONS = {
    "ENTRY_LONG": "🟢",
    "ENTRY_SHORT": "🔴",
    "MB_READY": "🔴",
    "TREND_LONG": "🔵",
    "TREND_SHORT": "🟣",
    "WATCH": "🟡",
    "MB_SKIP": "⚪",
    "NO_SIGNAL": "⚪",
    "NO_DATA": "⏳",
}

SW_AI_SYSTEM = """You are a Smart Wave Academy crypto futures coach (Archit Mittal bootcamp framework).

Strategies:
1. **EMA Crossover** (30m/1h) — EMA10 crosses EMA30; SL = prev candle low/high; target 1:3 R:R
2. **SuperTrend** (30m/1h, 10,3) — GREEN below = LONG, RED above = SHORT; SL = ST line
3. **BB Reversal** (30m) — pierce band then close back inside; target opposite band (~80% accuracy)
4. **Multi-Bagger Reversal** (5m SHORT) — only after 40%+ daily move; price < EMA280 + ST RED
5. **Volume Confirmation** — volume > 20-bar MA confirms direction

Risk rules: max 5X leverage, ₹200 max risk/trade, min 1:3 R:R, max 2 concurrent trades (Phase 1–2).
Give concrete entry, SL, target, margin sizing, liquidation distance, and which strategy fired.
""" + STANDARD_REPORT_FORMAT


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def build_sw_ai_prompt(symbol: str, analysis: dict) -> str:
    plan = analysis.get("trade_plan") or {}
    lines = [
        "=== SMART WAVE ACADEMY — CRYPTO ===",
        f"Symbol: {symbol}",
        f"Market: {MARKET}",
        f"Primary TF: {analysis.get('primary_tf', '—')}",
        f"Phase: {analysis.get('phase')} — {analysis.get('primary_label', '')}",
        f"Best strategy: {STRATEGY_LABELS.get(analysis.get('best_strategy', ''), '—')}",
        f"Confidence: {analysis.get('confidence', 0):.0f}%",
        f"Multi-bagger eligible (40%+ daily): {'YES' if analysis.get('mb_eligible') else 'NO'}",
        f"Margin ₹{analysis.get('margin_inr', 0):,.0f} · Leverage {analysis.get('leverage', 5)}X · "
        f"Liq distance ~{analysis.get('liquidation_pct', 20)}%",
        "",
        "=== PER-STRATEGY SNAPSHOT ===",
    ]
    for key, res in (analysis.get("strategies") or {}).items():
        lines.append(
            f"  {STRATEGY_LABELS.get(key, key)} [{res.get('timeframe', '—')}]: "
            f"{res.get('phase', '—')} — {res.get('primary_label', '')[:70]}"
        )
        trade = res.get("trade")
        if trade:
            lines.append(f"    → {trade.get('direction')} @ {trade.get('entry')} SL {trade.get('stoploss')} TP {trade.get('target')}")
        risk = res.get("risk")
        if risk:
            lines.append(f"    Risk ₹{risk.get('risk_inr', 0):.0f} ({'OK' if risk.get('within_limit') else 'OVER LIMIT'})")
    if plan:
        lines.extend([
            "",
            "=== TRADE PLAN ===",
            f"{plan.get('direction')} @ ${plan.get('entry', 0):,.4f}",
            f"SL: {plan.get('stop_loss')} ({plan.get('sl_pct', '—')}%)",
            f"TP: {plan.get('take_profit')} ({plan.get('tp_pct', '—')}%)",
            f"R:R {plan.get('rr_ratio', '—')} · Hold {plan.get('hold_duration', '—')}",
        ])
    return "\n".join(lines)


def _build_chart(result_df: pd.DataFrame, symbol: str, strategy_key: str, tf: str) -> go.Figure:
    if result_df is None or result_df.empty:
        return go.Figure()
    tail = result_df.tail(min(100, len(result_df)))
    fig = make_subplots(rows=1, cols=1)
    fig.add_trace(go.Candlestick(
        x=tail.index, open=tail["open"], high=tail["high"],
        low=tail["low"], close=tail["close"], name=symbol,
    ))
    if strategy_key == "ema_crossover":
        fig.add_trace(go.Scatter(x=tail.index, y=tail["ema10"], name="EMA10", line=dict(color="#22d3ee", width=1)))
        fig.add_trace(go.Scatter(x=tail.index, y=tail["ema30"], name="EMA30", line=dict(color="#f97316", width=1)))
    elif strategy_key in ("supertrend", "multibagger"):
        if "supertrend" in tail.columns:
            fig.add_trace(go.Scatter(
                x=tail.index, y=tail["supertrend"], name="SuperTrend",
                line=dict(color="#a855f7", width=1.5),
            ))
        if "ema280" in tail.columns:
            fig.add_trace(go.Scatter(
                x=tail.index, y=tail["ema280"], name="EMA280",
                line=dict(color="#eab308", width=1, dash="dot"),
            ))
    elif strategy_key == "bb_reversal":
        for col, color in [("bb_upper", "#ef4444"), ("bb_mid", "#94a3b8"), ("bb_lower", "#22c55e")]:
            if col in tail.columns:
                fig.add_trace(go.Scatter(x=tail.index, y=tail[col], name=col, line=dict(color=color, width=1)))
    fig.update_layout(
        title=f"{symbol} — {STRATEGY_LABELS.get(strategy_key, strategy_key)} ({tf})",
        template="plotly_dark", height=380,
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _render_setup_alerts(results: dict) -> None:
    ready = []
    watch = []
    for tick, d in results.items():
        if d.get("error"):
            continue
        if d.get("actionable"):
            ready.append(f"**{tick}** — {d.get('primary_label', '')[:60]}")
        elif d.get("phase") in ("WATCH", "TREND_LONG", "TREND_SHORT", "MB_SKIP"):
            watch.append(f"**{tick}** — {d.get('primary_label', '')[:60]}")
    if ready:
        st.success("🎯 **Entry-ready setups:** " + " · ".join(ready[:6]))
    if watch:
        st.info("👀 **Watchlist / trend:** " + " · ".join(watch[:6]))


def _render_screener_grid(results: dict) -> None:
    rows = []
    for tick, d in sorted(results.items(), key=lambda x: x[1].get("priority", 0), reverse=True):
        if d.get("error"):
            rows.append({
                "Ticker": tick, "Phase": "ERROR", "Strategy": "—",
                "TF": "—", "Confidence": 0, "Actionable": "❌",
            })
            continue
        best = STRATEGY_LABELS.get(d.get("best_strategy", ""), "—")
        rows.append({
            "Ticker": tick,
            "Phase": d.get("phase", "—"),
            "Strategy": best.split("·")[-1].strip() if "·" in best else best,
            "TF": d.get("primary_tf", "—"),
            "Confidence": f"{d.get('confidence', 0):.0f}%",
            "Actionable": "✅" if d.get("actionable") else "—",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


def _render_result_block(tick: str, data: dict, provider: str, model: str, api_key: str) -> None:
    if data.get("error"):
        st.error(data["error"])
        return

    icon = PHASE_ICONS.get(data.get("phase", ""), "⚪")
    st.markdown(f"### {icon} {data.get('primary_label', data.get('phase', ''))}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Phase", data.get("phase", "—"))
    c2.metric("Confidence", f"{data.get('confidence', 0):.0f}%")
    c3.metric("Leverage", f"{data.get('leverage', 5)}X")
    c4.metric("Liq @", f"{data.get('liquidation_pct', 20)}%")
    c5.metric("MB 40%+", "✅" if data.get("mb_eligible") else "❌")

    plan = data.get("trade_plan")
    if plan:
        st.markdown("#### 🎯 Best Trade Plan")
        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("Direction", plan.get("direction", "—"))
        p2.metric("Entry", f"${plan.get('entry', 0):,.4f}")
        sl = plan.get("stop_loss")
        p3.metric("SL", f"${sl:,.4f}" if isinstance(sl, (int, float)) else str(sl)[:12])
        tp = plan.get("take_profit")
        p4.metric("TP", f"${tp:,.4f}" if isinstance(tp, (int, float)) else "—")
        p5.metric("R:R", plan.get("rr_ratio", "—"))

    st.markdown("#### 📋 Strategy Breakdown")
    for key, res in (data.get("strategies") or {}).items():
        with st.expander(f"{STRATEGY_LABELS.get(key, key)} — {res.get('phase', '—')}", expanded=(key == data.get("best_strategy"))):
            st.caption(res.get("primary_label", ""))
            trade = res.get("trade")
            if trade:
                st.json(trade)
            risk = res.get("risk")
            if risk:
                ok = risk.get("within_limit")
                st.metric("Risk (₹)", f"₹{risk.get('risk_inr', 0):,.0f}", delta="Within limit" if ok else "Over ₹200!")
            rdf = res.get("result_df")
            if rdf is not None and not rdf.empty:
                st.plotly_chart(
                    _build_chart(rdf, tick, key, res.get("timeframe", "")),
                    width='stretch',
                    config={"displayModeBar": False},
                )

    render_run_summary(summarize_smart_wave_crypto(data, tick))
    plan = data.get("trade_plan") or {}
    render_strategy_mtf_panel(
        symbol=tick,
        market="CoinDCX Futures",
        groww_token=get_active_groww_token(),
        exchange="NSE",
        primary_tf=data.get("primary_tf", "30m"),
        strategy_direction=plan.get("direction"),
    )
    show_ai_view_block(
        session_prefix=PREFIX,
        result_key=_safe_key(tick),
        symbol=tick,
        timeframe_label=data.get("primary_tf", "30m"),
        build_prompt_fn=lambda t=tick, a=data: build_sw_ai_prompt(t, a),
        system_prompt=SW_AI_SYSTEM,
        provider=provider,
        model=model,
        api_key=api_key,
        button_in_column=False,
    )


def render_smart_wave_crypto_tab():
    """Smart Wave Academy crypto strategies — CoinDCX USDT pairs only."""
    st.markdown("<h1>🌊 Smart Wave Crypto Strategies</h1>", unsafe_allow_html=True)
    st.write(
        "CoinDCX-only scanner based on the **Smart Wave Academy 3-Day Bootcamp** "
        "(Archit Mittal): EMA Crossover, SuperTrend, BB Reversal, Multi-Bagger Reversal, "
        "and Volume Confirmation filter."
    )

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets Smart Wave setups, risk sizing, and per-strategy signals.",
    )

    st.markdown("---")
    st.markdown("### 📊 Tickers (CoinDCX USDT)")
    sw_tickers = render_coindcx_ticker_selection("smartwave")

    st.markdown("### ⏱️ Timeframes & Parameters")
    t1, t2, t3, t4 = st.columns(4)
    with t1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_single_timeframe

        sw_tf = render_ta_single_timeframe(
            "smartwave",
            SMART_WAVE_TF_OPTIONS,
            role="MTF",
            legacy_default="30m",
            label="Primary TF",
            widget_key="sw_tf",
        )
    with t2:
        sw_bars = st.slider("Bars to load", 200, 600, 400, 50, key="sw_bars")
    with t3:
        sw_margin = st.number_input("Margin (₹)", 500, 20000, TRADE_SIZE_INR, 500, key="sw_margin")
    with t4:
        sw_leverage = st.number_input("Leverage (max 5X)", 1, MAX_LEVERAGE, MAX_LEVERAGE, key="sw_leverage")

    st.markdown("### 🎯 Strategies")
    sw_strategies = st.multiselect(
        "Run strategies",
        STRATEGY_KEYS,
        default=STRATEGY_KEYS[:3],
        format_func=lambda k: STRATEGY_LABELS.get(k, k),
        key="sw_strategies",
    )
    sw_vol = st.checkbox("Apply Volume Confirmation filter (S5)", value=True, key="sw_vol")
    sw_actionable = render_ta_screener_options("smartwave")

    with st.expander("📅 90-Day Plan Phases", expanded=False):
        for ph in (1, 2, 3):
            p = phase_parameters(ph)
            st.markdown(f"**Phase {ph}:** {p}")

    st.caption(
        f"🧮 **{len(sw_tickers)}** ticker(s) · TF **{sw_tf}** · "
        f"**{len(sw_strategies)}** strategies · CoinDCX only"
    )

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button("🔎 RUN SMART WAVE SCAN", type="primary", width='stretch', key="sw_run")
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('sw_last_scan', '—')}")

    if run_btn:
        if not sw_tickers:
            st.error("Select at least one CoinDCX ticker.")
            return
        if not sw_strategies:
            st.error("Select at least one strategy.")
            return
        bar = st.progress(0, text="Running Smart Wave scan…")
        groww_token = get_active_groww_token()
        results = {}
        for i, tick in enumerate(sw_tickers):
            bar.progress((i + 1) / len(sw_tickers), text=f"{tick} — Smart Wave…")
            try:
                results[tick] = analyze_smart_wave(
                    tick,
                    market=MARKET,
                    strategies=sw_strategies,
                    primary_tf=sw_tf,
                    bars=sw_bars,
                    groww_token=groww_token,
                    margin_inr=float(sw_margin),
                    leverage=int(sw_leverage),
                    vol_filter=sw_vol,
                )
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)
        bar.empty()
        st.session_state.sw_results = results
        st.session_state.sw_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("sw_results", {})
    if not results:
        st.info("Select CoinDCX tickers and click **RUN SMART WAVE SCAN**.")
        return

    st.markdown("---")
    _render_setup_alerts(results)
    _render_screener_grid(results)

    digest = []
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, sw_tf, d["error"], tab="Smart Wave Crypto"))
        else:
            digest.append(summarize_smart_wave_crypto(d, tick))
    if sw_actionable:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 Smart Wave Recommendations", group_filter=True)

    for ti, tick in enumerate(sorted(results.keys(), key=lambda t: results[t].get("priority", 0), reverse=True)):
        data = results[tick]
        if sw_actionable and not data.get("error") and not data.get("actionable"):
            continue
        summary = next((s for s in digest if s.get("ticker") == tick), None)
        with st.expander(
            ticker_section_label(tick, [summary] if summary else []),
            expanded=should_expand_ticker(ti) and not data.get("error") and data.get("actionable", False),
        ):
            _render_result_block(tick, data, provider, model, api_key)

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai(SECTION_ID)

    st.caption("⚠️ Max 5X leverage · Risk ≤ ₹200/trade · SL first always.")
