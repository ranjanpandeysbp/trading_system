"""
smc_fake_market_shift_tab.py
----------------------------
SMC Fake Market Shift — BOS → POI → liquidity sweep → aggressive/conservative entries.
Groww (India) & CoinDCX futures.
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
    summarize_smc_fake_market_shift,
)
from app.market_pulse.smc_fake_market_shift_engine import (
    FMS_TF_OPTIONS,
    StrategyConfig,
    Trend,
    analyze_smc_fake_market_shift,
    fetch_fms_data,
)
from app.market_pulse.ta_screener_ui import render_ta_screener_options, render_strategy_mtf_panel
from app.market_pulse.ta_ticker_sections import should_expand_ticker, ticker_section_label
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
    market_currency,
)

PREFIX = "smcfms"
SECTION_ID = "smc_fake_market_shift"

PHASE_ICONS = {
    "ENTRY_READY": "🟢",
    "WATCH_SWEEP": "🟡",
    "STRUCTURE_ONLY": "🔵",
    "NO_SETUP": "⚪",
    "NO_DATA": "⏳",
}

FMS_AI_SYSTEM = """You are an SMC (Smart Money Concepts) coach specializing in the Fake Market Shift model.

3-step process:
1. **Market structure** — HH/HL/LH/LL via causal fractal swings; Break of Structure (BOS) sets trend bias.
2. **Point of Interest (POI)** — extreme zone / order block that originated the BOS move (demand or supply).
3. **Fake Market Shift** — price pulls into POI, forms internal structure, fake breakout grabs retail liquidity, then reverses.

Entry models:
- **Aggressive (A)** — stop order at sweep candle extreme; tightest stop, highest false-break risk.
- **Conservative (B)** — wait for Market Structure Shift (close breaks internal high/low), then limit entry on flip-zone mitigation.

Give concrete direction, model A vs B, entry, SL, TP, R:R, and red flags. Educational only.
""" + STANDARD_REPORT_FORMAT


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _render_strategy_explanation() -> None:
    with st.expander("📖 Strategy Guide — SMC Fake Market Shift", expanded=False):
        st.markdown("""
### What this is
A **3-step SMC strategy** that maps institutional-style manipulation: trend bias from structure, POI zones, then a **fake market shift** liquidity grab before the real move.

### Step 1 — Market structure (trend bias)
- Causal **fractal swings** (confirmed only after `right` bars — no lookahead)
- **Break of Structure (BOS)** when close breaks the last confirmed swing high/low
- Labels: HH, HL, LH, LL

### Step 2 — Point of Interest (POI)
- After each BOS, map the **extreme zone** / order block that originated the move
- Bullish BOS → **demand zone** between prior swing high and the low that started the rally
- Bearish BOS → **supply zone** (mirrored)

### Step 3 — Fake market shift + entries
1. Price **pulls back** into the POI
2. **Internal structure** forms (mini high/low)
3. **Inducement breakout** — retail reads a shift and places stops
4. **Liquidity sweep** — wick pierces those stops, then price reverses

| Model | Entry | Stop | Best for |
|-------|-------|------|----------|
| **A Aggressive** | Stop at sweep candle extreme | Beyond liquidity-grab wick | Fast entries, tighter risk |
| **B Conservative** | Limit on flip-zone after MSS confirm | Beyond flip zone + sweep wick | Higher confirmation, fewer trades |

### Backtest notes
Swing detection is **causal** (no future data). Sweep/flip heuristics approximate discretionary chart reading — **tune parameters** to your market and timeframe.

### Disclaimer
Educational/backtesting only. Not financial advice.
        """)


def build_fms_ai_prompt(symbol: str, market: str, analysis: dict, currency: str) -> str:
    plan = analysis.get("trade_plan") or {}
    bt = analysis.get("backtest_summary") or {}
    live = analysis.get("live_signal")
    lines = [
        "=== SMC FAKE MARKET SHIFT ===",
        f"Symbol: {symbol}",
        f"Market: {market}",
        f"TF: {analysis.get('chart_tf', '—')}",
        f"Phase: {analysis.get('phase')} — {analysis.get('primary_label', '')}",
        f"Trend bias: {analysis.get('trend_bias', '—')} · Confidence: {analysis.get('confidence', 0):.0f}%",
        f"Price: {currency}{analysis.get('price', 0):,.4f}",
        f"BOS: {analysis.get('bos_count', 0)} · POI zones: {analysis.get('poi_count', 0)} · "
        f"Sweeps: {analysis.get('sweep_count', 0)} · Signals: {analysis.get('signal_count', 0)}",
        "",
    ]
    if live:
        lines.append(
            f"Latest signal: {live.model} · {live.direction.value} @ bar {live.entry_index} · {live.notes}"
        )
    if plan:
        lines.extend([
            "",
            "=== TRADE PLAN ===",
            f"Model {plan.get('model', '—')} · {plan.get('direction', '—')}",
            f"Entry: {currency}{plan.get('entry', 0):,.4f}",
            f"SL: {currency}{plan.get('stop_loss', 0):,.4f} ({plan.get('sl_pct', 0):.3f}%)",
            f"TP: {currency}{plan.get('take_profit', 0):,.4f} ({plan.get('tp_pct', 0):.3f}%)",
            f"R:R 1:{plan.get('rr_ratio', '—')} · {plan.get('notes', '')}",
        ])
    if bt.get("closed_trades"):
        lines.extend([
            "",
            "=== BACKTEST (loaded window) ===",
            f"Signals: {bt.get('total_signals')} · Filled: {bt.get('filled')} · "
            f"Closed: {bt.get('closed_trades')} · Win: {bt.get('win_rate', 0):.1f}% · "
            f"Total R: {bt.get('total_R', 0):.2f} · Avg R: {bt.get('avg_R', 0):.2f}",
        ])
    return "\n".join(lines)


def _build_chart(analysis: dict, symbol: str, currency: str) -> go.Figure:
    df = analysis.get("result_df")
    if df is None or df.empty:
        return go.Figure()

    tail_start = max(0, len(df) - 200)
    tail = df.iloc[tail_start:]
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=tail.index, open=tail["open"], high=tail["high"],
        low=tail["low"], close=tail["close"], name=symbol,
    ))

    for poi in analysis.get("poi_zones") or []:
        if poi.end_index < tail_start:
            continue
        color = "rgba(34,197,94,0.15)" if poi.direction == Trend.BULLISH else "rgba(239,68,68,0.15)"
        x0 = df.index[max(poi.start_index, tail_start)]
        x1 = df.index[min(poi.end_index, len(df) - 1)]
        fig.add_shape(
            type="rect", x0=x0, x1=x1, y0=poi.bottom, y1=poi.top,
            fillcolor=color, line=dict(width=0), layer="below",
        )

    for sw in analysis.get("sweeps") or []:
        if sw.sweep_candle_index < tail_start:
            continue
        fig.add_vline(
            x=df.index[sw.sweep_candle_index], line_dash="dot", line_color="#eab308",
            annotation_text="Sweep",
        )

    plan = analysis.get("trade_plan") or {}
    if plan.get("entry"):
        fig.add_hline(y=plan["entry"], line_dash="dot", line_color="#94a3b8", annotation_text="Entry")
    if plan.get("stop_loss"):
        fig.add_hline(y=plan["stop_loss"], line_dash="dash", line_color="#ef4444", annotation_text="SL")
    if plan.get("take_profit"):
        fig.add_hline(y=plan["take_profit"], line_dash="dash", line_color="#22c55e", annotation_text="TP")

    fig.update_layout(
        title=f"{symbol} — Fake Market Shift ({analysis.get('chart_tf', '')})",
        template="plotly_dark", height=420,
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _render_backtest_summary(bt: dict) -> None:
    if not bt or not bt.get("total_signals"):
        st.caption("No signals in backtest window — try more bars or adjust swing/POI parameters.")
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Signals", bt.get("total_signals", 0))
    c2.metric("Filled", bt.get("filled", 0))
    c3.metric("Win rate", f"{bt.get('win_rate', 0):.1f}%")
    c4.metric("Total R", f"{bt.get('total_R', 0):.2f}")
    c5.metric("Avg R", f"{bt.get('avg_R', 0):.2f}")


def _render_screener_table(results: dict) -> None:
    rows = []
    for tick, d in sorted(results.items(), key=lambda x: (x[1].get("analysis") or {}).get("priority", 0), reverse=True):
        if d.get("error"):
            rows.append({"Ticker": tick, "Phase": "ERROR", "Bias": "—", "BOS": "—", "Sweeps": "—", "Model": "—"})
            continue
        a = d.get("analysis") or {}
        plan = a.get("trade_plan") or {}
        rows.append({
            "Ticker": tick,
            "Phase": a.get("phase", "—"),
            "Bias": a.get("trend_bias", "—"),
            "BOS": a.get("bos_count", 0),
            "Sweeps": a.get("sweep_count", 0),
            "Model": plan.get("model", "—"),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_result_block(tick: str, data: dict, currency: str, provider: str, model: str, api_key: str) -> None:
    if data.get("error"):
        st.error(data["error"])
        return

    analysis = data.get("analysis") or {}
    icon = PHASE_ICONS.get(analysis.get("phase", ""), "⚪")
    st.markdown(f"### {icon} {analysis.get('primary_label', analysis.get('phase', ''))}")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Bias", analysis.get("trend_bias", "—"))
    m2.metric("BOS", analysis.get("bos_count", 0))
    m3.metric("POI zones", analysis.get("poi_count", 0))
    m4.metric("Sweeps", analysis.get("sweep_count", 0))
    m5.metric("Confidence", f"{analysis.get('confidence', 0):.0f}%")

    _render_backtest_summary(analysis.get("backtest_summary") or {})
    st.plotly_chart(_build_chart(analysis, tick, currency), width="stretch", config={"displayModeBar": False})

    signals = analysis.get("signals") or []
    if signals:
        with st.expander("📜 All signals (loaded window)", expanded=False):
            sig_rows = []
            for sig in signals[-25:]:
                sig_rows.append({
                    "model": sig.model,
                    "direction": sig.direction.value.upper(),
                    "bar": sig.entry_index,
                    "entry": round(sig.entry_price, 4),
                    "sl": round(sig.stop_loss, 4),
                    "tp": round(sig.take_profit, 4) if sig.take_profit else None,
                    "notes": sig.notes[:60],
                })
            st.dataframe(pd.DataFrame(sig_rows), width="stretch", hide_index=True)

    bt_trades = analysis.get("backtest_trades") or []
    if bt_trades:
        with st.expander("📊 Backtest outcomes", expanded=False):
            st.dataframe(pd.DataFrame(bt_trades), width="stretch", hide_index=True)

    render_run_summary(summarize_smc_fake_market_shift(analysis, tick))
    render_strategy_mtf_panel(
        symbol=tick,
        market=st.session_state.get("smcfms_results_market", MARKET_OPTIONS[0]),
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("smcfms_results_exchange", "NSE"),
        primary_tf=analysis.get("chart_tf", "15m"),
        strategy_direction=(analysis.get("trade_plan") or {}).get("direction"),
    )
    show_ai_view_block(
        session_prefix=PREFIX,
        result_key=_safe_key(tick),
        symbol=tick,
        timeframe_label=analysis.get("chart_tf", "15m"),
        build_prompt_fn=lambda t=tick, a=analysis, c=currency: build_fms_ai_prompt(
            t, st.session_state.get("smcfms_results_market", ""), a, c
        ),
        system_prompt=FMS_AI_SYSTEM,
        provider=provider,
        model=model,
        api_key=api_key,
        button_in_column=False,
    )


def render_smc_fake_market_shift_tab() -> None:
    """SMC Fake Market Shift — Groww & CoinDCX."""
    st.markdown("<h1>🎭 SMC — Fake Market Shift</h1>", unsafe_allow_html=True)
    st.write(
        "Smart Money Concepts **3-step model**: **BOS structure** → **POI / extreme zone** → "
        "**liquidity sweep** with **Aggressive (A)** or **Conservative (B)** entries. "
        "**Groww (India)** and **CoinDCX (crypto)** supported."
    )

    _render_strategy_explanation()

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets structure, POI, sweep, and Model A vs B trade plans.",
    )

    st.markdown("---")
    m1, m2 = st.columns(2)
    with m1:
        fms_market = st.selectbox("🌐 Market", MARKET_OPTIONS, key="smcfms_market")
    with m2:
        fms_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="smcfms_exchange")
            if is_india_market(fms_market) else "NSE"
        )

    is_crypto = is_crypto_market(fms_market)
    currency = market_currency(fms_market)

    st.markdown("### 📊 Tickers")
    fms_tickers: list[str] = []
    if is_crypto:
        fms_tickers = render_coindcx_ticker_selection("smcfms")
    else:
        fms_tickers = render_equity_index_ticker_selection(fms_market, "smcfms")

    st.markdown("### ⚙️ Parameters")
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_single_timeframe

        fms_tf = render_ta_single_timeframe(
            "smcfms", FMS_TF_OPTIONS, role="MTF", legacy_default="15m",
            label="Chart TF", widget_key="smcfms_tf",
        )
    with p2:
        fms_bars = st.slider("Bars to load", 300, 1200, 600, 50, key="smcfms_bars")
    with p3:
        fms_model = st.selectbox(
            "Entry model",
            ["both", "aggressive", "conservative"],
            format_func=lambda x: {"both": "A + B", "aggressive": "A Aggressive", "conservative": "B Conservative"}[x],
            key="smcfms_entry_model",
        )
    with p4:
        fms_lookback = st.number_input("Live signal bars", 10, 60, 25, key="smcfms_lookback")

    with st.expander("⚙️ Advanced structure & R:R", expanded=False):
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            swing_l = st.number_input("Swing left", 1, 5, 2, key="smcfms_swing_l")
        with a2:
            swing_r = st.number_input("Swing right", 1, 5, 2, key="smcfms_swing_r")
        with a3:
            rr_a = st.number_input("R:R aggressive", 1.0, 4.0, 2.0, 0.5, key="smcfms_rr_a")
        with a4:
            rr_c = st.number_input("R:R conservative", 1.5, 5.0, 3.0, 0.5, key="smcfms_rr_c")
        poi_la = st.slider("POI lookahead bars", 40, 150, 80, 10, key="smcfms_poi_la")

    cfg = StrategyConfig(
        swing_left=int(swing_l),
        swing_right=int(swing_r),
        poi_lookahead=int(poi_la),
        rr_aggressive=float(rr_a),
        rr_conservative=float(rr_c),
        live_lookback_bars=int(fms_lookback),
        entry_model=fms_model,  # type: ignore[arg-type]
    )

    fms_actionable = render_ta_screener_options("smcfms")
    st.caption(f"🧮 **{len(fms_tickers)}** ticker(s) · **{fms_tf}** · SMC Fake Market Shift")

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button("🔎 RUN FAKE MARKET SHIFT SCAN", type="primary", width="stretch", key="smcfms_run")
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('smcfms_last_scan', '—')}")

    if run_btn:
        if not fms_tickers:
            st.error("Select at least one ticker.")
            return
        groww_token = get_active_groww_token()
        results = {}
        bar = st.progress(0, text="Running SMC Fake Market Shift scan…")
        for i, tick in enumerate(fms_tickers):
            bar.progress((i + 1) / len(fms_tickers), text=f"{tick} — {fms_tf}…")
            try:
                df = fetch_fms_data(tick, fms_tf, fms_market, groww_token, fms_exchange, fms_bars)
                if df.empty or len(df) < 80:
                    results[tick] = {"error": f"Insufficient {fms_tf} data ({len(df)} bars).", "symbol": tick}
                    continue
                analysis = analyze_smc_fake_market_shift(df, chart_tf=fms_tf, cfg=cfg)
                results[tick] = {"analysis": analysis, "symbol": tick}
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)
        bar.empty()
        st.session_state.smcfms_results = results
        st.session_state.smcfms_results_market = fms_market
        st.session_state.smcfms_results_exchange = fms_exchange
        st.session_state.smcfms_chart_tf = fms_tf
        st.session_state.smcfms_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("smcfms_results", {})
    if not results:
        st.info("Select tickers and click **RUN FAKE MARKET SHIFT SCAN**.")
        return

    currency = market_currency(st.session_state.get("smcfms_results_market", fms_market))

    st.markdown("---")
    ready = [
        f"**{t}** — {(d.get('analysis') or {}).get('primary_label', '')[:50]}"
        for t, d in results.items()
        if (d.get("analysis") or {}).get("actionable")
    ]
    if ready:
        st.success("🎯 **Entry-ready:** " + " · ".join(ready[:5]))

    _render_screener_table(results)

    digest = []
    chart_tf = st.session_state.get("smcfms_chart_tf", fms_tf)
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, chart_tf, d["error"], tab="SMC Fake Market Shift"))
        else:
            digest.append(summarize_smc_fake_market_shift(d["analysis"], tick))

    if fms_actionable:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 Fake Market Shift Recommendations", group_filter=True)

    tickers_sorted = sorted(
        results.keys(),
        key=lambda t: (results[t].get("analysis") or {}).get("priority", 0),
        reverse=True,
    )
    for ti, tick in enumerate(tickers_sorted):
        data = results[tick]
        if fms_actionable and not data.get("error") and not (data.get("analysis") or {}).get("actionable"):
            continue
        summary = next((s for s in digest if s.get("ticker") == tick), None)
        with st.expander(
            ticker_section_label(tick, [summary] if summary else []),
            expanded=should_expand_ticker(ti),
        ):
            _render_result_block(tick, data, currency, provider, model, api_key)
