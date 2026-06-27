"""
velez_retracement_tab.py
------------------------
Velez Retracement Scalping — Groww (NSE/BSE) & CoinDCX futures.
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
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import (
    render_run_digest,
    render_run_summary,
    summarize_error,
    summarize_velez_retracement,
)
from app.market_pulse.ta_screener_ui import render_ta_screener_options, render_strategy_mtf_panel
from app.market_pulse.ta_ticker_sections import should_expand_ticker, ticker_section_label
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    GROWW_MARKET,
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
    market_currency,
)
from app.market_pulse.velez_retracement_engine import (
    VELEZ_TF_OPTIONS,
    StrategyConfig,
    analyze_velez,
    fetch_velez_data,
)

PREFIX = "velez"
SECTION_ID = "velez_retracement"

PHASE_ICONS = {
    "ENTRY_READY": "🟢",
    "WATCH": "🟡",
    "NO_SETUP": "⚪",
    "NO_DATA": "⏳",
}

VELEZ_AI_SYSTEM = """You are an Oliver Velez retracement scalping coach.

Framework:
- Chart: 2-minute (or 5-minute) with **20 SMA** (short trend) and **200 SMA** (long trend)
- Detect **sharp fluid moves** then trade the counter-trend retracement

**Scenario A — Pure Scalp (~90% win-rate zone):**
- After sharp move, enter counter-trend while retrace < 50% of the move
- Target **25% retracement** of the initial move, tight stop (~0.3%)

**Scenario B — Trend Trade:**
- If counter-trend bounce/pullback exceeds **50%**, flip to trend mode
- Wait for pullback + **bullish/bearish engulfing** bar
- Target minimum **2:1 R:R**

SMA filter: after down-move price < SMA20 ideal; after up-move price > SMA20 ideal.

Give concrete entry TF, SL%, TP%, hold time, scenario A vs B, and red flags.
""" + STANDARD_REPORT_FORMAT


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _fmt_pct(val: float | None, *, sign: str = "+") -> str:
    if val is None:
        return "—"
    if sign == "-":
        return f"-{val:.2f}%"
    return f"+{val:.2f}%"


def build_velez_ai_prompt(symbol: str, market: str, analysis: dict, currency: str) -> str:
    plan = analysis.get("trade_plan") or {}
    mv = analysis.get("recent_move") or {}
    bt = analysis.get("backtest_summary") or {}
    lines = [
        "=== VELEZ RETRACEMENT SCALPING ===",
        f"Symbol: {symbol}",
        f"Market: {market}",
        f"Chart TF: {analysis.get('chart_tf', '—')}",
        f"Phase: {analysis.get('phase')} — {analysis.get('primary_label', '')}",
        f"Confidence: {analysis.get('confidence', 0):.0f}%",
        f"Price: {currency}{analysis.get('price', 0):,.4f}",
        f"SMA20: {currency}{analysis.get('sma20') or 0:,.4f} · SMA200: {currency}{analysis.get('sma200') or 0:,.4f}",
        "",
    ]
    if mv:
        lines.append(
            f"Recent sharp move: {mv.get('direction')} · "
            f"{mv.get('magnitude_pct', 0):.2f}% · "
            f"{mv.get('start_price')} → {mv.get('end_price')}"
        )
    if plan:
        lines.extend([
            "",
            "=== TRADE PLAN ===",
            f"Scenario: {plan.get('scenario', '—')} · {plan.get('direction', '—')}",
            f"Entry: {currency}{plan.get('entry', 0):,.4f}",
            f"SL: {currency}{plan.get('stop_loss', 0):,.4f} ({_fmt_pct(plan.get('sl_pct'), sign='-')})",
            f"TP: {currency}{plan.get('take_profit', 0):,.4f} ({_fmt_pct(plan.get('tp_pct'))})",
            f"R:R 1:{plan.get('rr_ratio', '—')} · Hold: {plan.get('hold_duration', '—')}",
            f"Notes: {plan.get('notes', '')}",
        ])
    if bt.get("total"):
        lines.extend([
            "",
            "=== BACKTEST (loaded bars) ===",
            f"Signals: {bt.get('total')} · Closed: {bt.get('closed')} · "
            f"Win rate: {bt.get('win_rate', 0):.1f}% · PnL sum: {bt.get('total_pnl_pct', 0):.2f}%",
        ])
    return "\n".join(lines)


def _build_chart(analysis: dict, symbol: str) -> go.Figure:
    df = analysis.get("result_df")
    if df is None or df.empty:
        return go.Figure()
    tail = df.tail(min(120, len(df)))
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=tail.index,
        open=tail["open"], high=tail["high"],
        low=tail["low"], close=tail["close"],
        name=symbol,
    ))
    if "sma20" in tail.columns:
        fig.add_trace(go.Scatter(
            x=tail.index, y=tail["sma20"], name="SMA 20",
            line=dict(color="#22d3ee", width=1.2),
        ))
    if "sma200" in tail.columns:
        fig.add_trace(go.Scatter(
            x=tail.index, y=tail["sma200"], name="SMA 200",
            line=dict(color="#f97316", width=1.2),
        ))
    plan = analysis.get("trade_plan") or {}
    if plan.get("entry"):
        fig.add_hline(y=plan["entry"], line_dash="dot", line_color="#94a3b8", annotation_text="Entry")
    if plan.get("stop_loss"):
        fig.add_hline(y=plan["stop_loss"], line_dash="dash", line_color="#ef4444", annotation_text="SL")
    if plan.get("take_profit"):
        fig.add_hline(y=plan["take_profit"], line_dash="dash", line_color="#22c55e", annotation_text="TP")
    fig.update_layout(
        title=f"{symbol} — Velez ({analysis.get('chart_tf', '')})",
        template="plotly_dark",
        height=400,
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _render_screener_alerts(results: dict) -> None:
    ready, watch = [], []
    for tick, d in results.items():
        if d.get("error"):
            continue
        a = d.get("analysis") or {}
        if a.get("actionable"):
            ready.append(f"**{tick}** — {a.get('primary_label', '')[:55]}")
        elif a.get("phase") == "WATCH":
            watch.append(f"**{tick}** — {a.get('primary_label', '')[:55]}")
    if ready:
        st.success("🎯 **Entry-ready:** " + " · ".join(ready[:6]))
    if watch:
        st.info("👀 **Watch sharp-move retracements:** " + " · ".join(watch[:6]))


def _render_screener_table(results: dict, currency: str) -> None:
    rows = []
    for tick, d in sorted(results.items(), key=lambda x: (x[1].get("analysis") or {}).get("priority", 0), reverse=True):
        if d.get("error"):
            rows.append({"Ticker": tick, "Phase": "ERROR", "Scenario": "—", "TF": "—", "SL %": "—", "TP %": "—"})
            continue
        a = d.get("analysis") or {}
        plan = a.get("trade_plan") or {}
        rows.append({
            "Ticker": tick,
            "Phase": a.get("phase", "—"),
            "Scenario": plan.get("scenario", "—"),
            "Side": plan.get("direction", "—"),
            "TF": a.get("chart_tf", "—"),
            "Confidence": f"{a.get('confidence', 0):.0f}%",
            "SL %": _fmt_pct(plan.get("sl_pct"), sign="-") if plan.get("sl_pct") is not None else "—",
            "TP %": _fmt_pct(plan.get("tp_pct")) if plan.get("tp_pct") is not None else "—",
            "Hold": plan.get("hold_duration", "—"),
            "Action": "✅" if a.get("actionable") else "—",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


def _render_result_block(tick: str, data: dict, provider: str, model: str, api_key: str, currency: str) -> None:
    if data.get("error"):
        st.error(data["error"])
        return
    analysis = data["analysis"]
    icon = PHASE_ICONS.get(analysis.get("phase", ""), "⚪")
    st.markdown(f"### {icon} {analysis.get('primary_label', analysis.get('phase', ''))}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Phase", analysis.get("phase", "—"))
    c2.metric("Confidence", f"{analysis.get('confidence', 0):.0f}%")
    c3.metric("Chart TF", analysis.get("chart_tf", "—"))
    c4.metric("Signals (history)", analysis.get("signals_count", 0))

    plan = analysis.get("trade_plan")
    if plan:
        st.markdown("#### 🎯 Trade Plan")
        p1, p2, p3, p4, p5, p6 = st.columns(6)
        p1.metric("Scenario", plan.get("scenario", "—"))
        p2.metric("Direction", plan.get("direction", "—"))
        p3.metric("Entry TF", plan.get("entry_timeframe", "—"))
        p4.metric("SL", _fmt_pct(plan.get("sl_pct"), sign="-"))
        p5.metric("TP", _fmt_pct(plan.get("tp_pct")))
        p6.metric("Hold", plan.get("hold_duration", "—"))
        e1, e2, e3 = st.columns(3)
        e1.metric("Entry", f"{currency}{plan.get('entry', 0):,.4f}")
        e2.metric("Stop", f"{currency}{plan.get('stop_loss', 0):,.4f}")
        e3.metric("Target", f"{currency}{plan.get('take_profit', 0):,.4f}")
        st.caption(plan.get("notes", ""))

    mv = analysis.get("recent_move")
    if mv:
        st.caption(
            f"Recent sharp move: **{mv.get('direction')}** · "
            f"**{mv.get('magnitude_pct', 0):.2f}%** · "
            f"{currency}{mv.get('start_price', 0):,.2f} → {currency}{mv.get('end_price', 0):,.2f}"
        )

    bt = analysis.get("backtest_summary") or {}
    if bt.get("total"):
        st.caption(
            f"Backtest on loaded bars: **{bt.get('closed', 0)}** closed · "
            f"win **{bt.get('win_rate', 0):.1f}%** · "
            f"scalps **{bt.get('scalps', 0)}** · trends **{bt.get('trends', 0)}**"
        )

    rdf = analysis.get("result_df")
    if rdf is not None and not rdf.empty:
        st.plotly_chart(_build_chart(analysis, tick), width='stretch', config={"displayModeBar": False})

    trades = analysis.get("backtest_trades") or []
    if trades:
        with st.expander("📜 Historical signals (loaded window)", expanded=False):
            st.dataframe(pd.DataFrame(trades), width='stretch', hide_index=True)

    render_run_summary(summarize_velez_retracement(analysis, tick))
    render_strategy_mtf_panel(
        symbol=tick,
        market=st.session_state.get("velez_results_market", GROWW_MARKET),
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("velez_results_exchange", "NSE"),
        primary_tf=analysis.get("chart_tf", "5m"),
        strategy_direction=(plan or {}).get("direction"),
    )
    show_ai_view_block(
        session_prefix=PREFIX,
        result_key=_safe_key(tick),
        symbol=tick,
        timeframe_label=analysis.get("chart_tf", "5m"),
        build_prompt_fn=lambda t=tick, a=analysis, c=currency: build_velez_ai_prompt(
            t, st.session_state.get("velez_results_market", ""), a, c
        ),
        system_prompt=VELEZ_AI_SYSTEM,
        provider=provider,
        model=model,
        api_key=api_key,
        button_in_column=False,
    )


def render_velez_retracement_tab() -> None:
    """Velez Retracement Scalping — Groww & CoinDCX."""
    st.markdown("<h1>📐 Velez Retracement Scalping</h1>", unsafe_allow_html=True)
    st.write(
        "Oliver Velez methodology on **2m / 5m** charts with **20 & 200 SMA**, "
        "sharp-move detection, and **25% / 50% retracement** rules. "
        "**Groww (India)** and **CoinDCX (crypto)** supported."
    )

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets Scenario A scalps vs Scenario B trend trades.",
    )

    st.markdown("---")
    m1, m2 = st.columns(2)
    with m1:
        velez_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            key="velez_market",
        )
    with m2:
        velez_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="velez_exchange")
            if is_india_market(velez_market) else "NSE"
        )

    is_crypto = is_crypto_market(velez_market)
    currency = market_currency(velez_market)

    st.markdown("### 📊 Tickers")
    velez_tickers: list[str] = []
    if is_crypto:
        velez_tickers = render_coindcx_ticker_selection("velez")
    else:
        velez_tickers = render_equity_index_ticker_selection(velez_market, "velez")

    st.markdown("### ⚙️ Parameters")
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_single_timeframe

        velez_tf = render_ta_single_timeframe(
            "velez",
            VELEZ_TF_OPTIONS,
            role="MTF",
            legacy_default="5m",
            label="Chart TF",
            widget_key="velez_tf",
        )
    with p2:
        velez_bars = st.slider("Bars to load", 250, 800, 500, 50, key="velez_bars")
    with p3:
        velez_sharp = st.number_input(
            "Sharp move min %", 0.002, 0.02, 0.005, 0.001, format="%.3f", key="velez_sharp"
        )
    with p4:
        velez_rr = st.number_input("Trend min R:R", 1.5, 4.0, 2.0, 0.5, key="velez_rr")

    with st.expander("⚙️ Advanced SMA & stops", expanded=False):
        a1, a2, a3 = st.columns(3)
        with a1:
            velez_sma_short = st.number_input("Short SMA", 5, 50, 20, key="velez_sma20")
        with a2:
            velez_sma_long = st.number_input("Long SMA", 50, 300, 200, key="velez_sma200")
        with a3:
            velez_sl = st.number_input(
                "Scalp stop %", 0.001, 0.01, 0.003, 0.001, format="%.3f", key="velez_sl"
            )

    velez_actionable = render_ta_screener_options("velez")
    st.caption(f"🧮 **{len(velez_tickers)}** ticker(s) · **{velez_tf}** chart · Velez 20/200 SMA")

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button("🔎 RUN VELEZ RETRACEMENT SCAN", type="primary", width='stretch', key="velez_run")
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('velez_last_scan', '—')}")

    cfg = StrategyConfig(
        short_sma=int(velez_sma_short),
        long_sma=int(velez_sma_long),
        sharp_move_threshold=float(velez_sharp),
        stop_loss_pct=float(velez_sl),
        risk_reward_trend=float(velez_rr),
    )

    if run_btn:
        if not velez_tickers:
            st.error("Select at least one ticker.")
            return
        groww_token = get_active_groww_token()
        results = {}
        bar = st.progress(0, text="Running Velez scan…")
        for i, tick in enumerate(velez_tickers):
            bar.progress((i + 1) / len(velez_tickers), text=f"{tick} — Velez {velez_tf}…")
            try:
                df = fetch_velez_data(
                    tick, velez_tf, velez_market, groww_token, velez_exchange, velez_bars
                )
                if df.empty or len(df) < cfg.long_sma + 10:
                    results[tick] = {
                        "error": f"Insufficient {velez_tf} data ({len(df)} bars).",
                        "symbol": tick,
                    }
                    continue
                analysis = analyze_velez(df, chart_tf=velez_tf, cfg=cfg)
                results[tick] = {"analysis": analysis, "symbol": tick}
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)
        bar.empty()
        st.session_state.velez_results = results
        st.session_state.velez_results_market = velez_market
        st.session_state.velez_results_exchange = velez_exchange
        st.session_state.velez_is_crypto = is_crypto
        st.session_state.velez_chart_tf = velez_tf
        st.session_state.velez_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("velez_results", {})
    is_crypto = st.session_state.get("velez_is_crypto", is_crypto)
    currency = market_currency(st.session_state.get("velez_results_market", velez_market))

    if not results:
        st.info("Select tickers and click **RUN VELEZ RETRACEMENT SCAN**.")
        return

    st.markdown("---")
    _render_screener_alerts(results)
    _render_screener_table(results, currency)

    digest = []
    chart_tf = st.session_state.get("velez_chart_tf", velez_tf)
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, chart_tf, d["error"], tab="Velez Retracement"))
        else:
            digest.append(summarize_velez_retracement(d["analysis"], tick))

    if velez_actionable:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 Velez Recommendations", group_filter=True)

    tickers_sorted = sorted(
        results.keys(),
        key=lambda t: (results[t].get("analysis") or {}).get("priority", 0),
        reverse=True,
    )
    for ti, tick in enumerate(tickers_sorted):
        data = results[tick]
        if velez_actionable and not data.get("error") and not (data.get("analysis") or {}).get("actionable"):
            continue
        summary = next((s for s in digest if s.get("ticker") == tick), None)
        with st.expander(
            ticker_section_label(tick, [summary] if summary else []),
            expanded=should_expand_ticker(ti) and not data.get("error") and (data.get("analysis") or {}).get("actionable"),
        ):
            _render_result_block(tick, data, provider, model, api_key, currency)

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai(SECTION_ID)

    st.caption("⚠️ Velez rules are probabilistic — use stops and size down when SMAs are misaligned.")
