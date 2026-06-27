"""
crypto_scalping_tab.py
----------------------
EMA + VWAP pullback + RSI crypto scalping — CoinDCX futures.
Includes live screener, backtest report, and CSV upload.
"""

from __future__ import annotations

import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from app.market_pulse.ai_view import (
    STANDARD_REPORT_FORMAT,
    render_ai_config,
    show_ai_view_block,
)
from app.market_pulse.crypto_scalping_engine import (
    SCALPING_TF_OPTIONS,
    BacktestConfig,
    analyze_crypto_scalping,
    fetch_scalping_data,
    load_ohlcv_csv,
)
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import (
    render_run_digest,
    render_run_summary,
    summarize_crypto_scalping,
    summarize_error,
)
from app.market_pulse.ta_screener_ui import render_ta_screener_options, render_strategy_mtf_panel
from app.market_pulse.ta_ticker_sections import should_expand_ticker, ticker_section_label
from app.market_pulse.ticker_selection_ui import render_coindcx_ticker_selection

PREFIX = "cscalp"
SECTION_ID = "crypto_scalping"
MARKET = "CoinDCX Futures"

PHASE_ICONS = {
    "ENTRY_LONG": "🟢",
    "ENTRY_SHORT": "🔴",
    "WATCH_LONG": "🟡",
    "WATCH_SHORT": "🟡",
    "NO_SIGNAL": "⚪",
    "NO_DATA": "⏳",
}

SCALP_AI_SYSTEM = """You are a crypto scalping coach using EMA + VWAP + RSI confluence.

Strategy rules:
1. **Trend filter:** EMA9 vs EMA21 — only trade with trend (no counter-trend scalps).
2. **Entry:** VWAP pullback — long when price dips to/near VWAP then closes above; short on pop to VWAP then close below.
3. **RSI(14):** Long needs 50 < RSI < 70; short needs 30 < RSI < 50.
4. **Risk:** ATR-based stop, fixed R:R take-profit, fees + slippage modeled.

Give concrete entry, SL, TP, R:R, and whether backtest stats support paper-trading further.
Educational only — no guarantee of future performance.
""" + STANDARD_REPORT_FORMAT


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _render_strategy_explanation() -> None:
    with st.expander("📖 Strategy Guide — EMA + VWAP Pullback + RSI Scalping", expanded=False):
        st.markdown("""
### What this is
A **rule-based scalping strategy** for crypto OHLCV (1m or 5m candles). Three filters must agree before a trade is taken — this raises probability but **does not guarantee wins**. You get a quantifiable, repeatable edge you can test and tune.

### Strategy logic

| Step | Rule |
|------|------|
| **1. Trend filter** | EMA9 vs EMA21 — uptrend = EMA9 > EMA21 (longs only); downtrend = EMA9 < EMA21 (shorts only) |
| **2. Entry trigger** | **VWAP pullback** — long: price dips to/near VWAP then closes above; short: pop to VWAP then closes below |
| **3. RSI confirm** | Long: RSI > 50 and < 70 · Short: RSI < 50 and > 30 |
| **4. Risk mgmt** | Fixed fractional sizing · ATR stop · R:R take-profit · fees + slippage · max trades/day · daily loss cutoff |

### Risk management (matters more than entry)
- Risk a small **% of equity per trade** (default 0.5%)
- **Stop-loss** = ATR × multiplier (adapts to volatility)
- **Take-profit** at fixed reward:risk multiple
- Trading **fees + slippage** modeled on every trade
- Optional **max trades/day** and **max daily loss** cutoff

### How to use this section
1. Select **CoinDCX** tickers and **1m / 5m** timeframe.
2. Tune backtest parameters (risk %, R:R, fees, ATR stop).
3. Click **RUN SCALPING SCAN** — live signal + backtest on loaded bars.
4. Optionally upload a **CSV** (`timestamp, open, high, low, close, volume`) for offline backtest.
5. Read the performance report before risking real capital.

### Disclaimer
Educational software, not financial advice. Past backtest performance does not predict future results.
Crypto is volatile — you can lose money. Test on paper/small size first.
        """)


def build_scalp_ai_prompt(symbol: str, analysis: dict) -> str:
    plan = analysis.get("trade_plan") or {}
    bt = analysis.get("backtest_metrics") or {}
    lines = [
        "=== CRYPTO SCALPING — EMA + VWAP + RSI ===",
        f"Symbol: {symbol}",
        f"Market: {MARKET}",
        f"TF: {analysis.get('chart_tf', '—')}",
        f"Phase: {analysis.get('phase')} — {analysis.get('primary_label', '')}",
        f"Trend: {analysis.get('trend')} · RSI {analysis.get('rsi')} · VWAP dist {analysis.get('vwap_dist_pct')}%",
        f"Price: ${analysis.get('price', 0):,.4f} · VWAP ${analysis.get('vwap', 0):,.4f}",
        f"EMA9: {analysis.get('ema_fast')} · EMA21: {analysis.get('ema_slow')} · ATR: {analysis.get('atr')}",
        "",
    ]
    if plan:
        lines.extend([
            "=== TRADE PLAN ===",
            f"{plan.get('direction')} @ ${plan.get('entry', 0):,.4f}",
            f"SL: ${plan.get('stop_loss', 0):,.4f} ({plan.get('sl_pct', 0):.3f}%)",
            f"TP: ${plan.get('take_profit', 0):,.4f} ({plan.get('tp_pct', 0):.3f}%)",
            f"R:R 1:{plan.get('rr_ratio', '—')} · {plan.get('notes', '')}",
        ])
    if bt.get("total_trades"):
        lines.extend([
            "",
            "=== BACKTEST (loaded window) ===",
            f"Trades: {bt.get('total_trades')} · Win rate: {bt.get('win_rate', 0):.1f}% · "
            f"PF: {bt.get('profit_factor', 0):.2f} · Return: {bt.get('total_return_pct', 0):.2f}% · "
            f"Max DD: {bt.get('max_drawdown_pct', 0):.2f}%",
        ])
    return "\n".join(lines)


def _build_chart(analysis: dict, symbol: str) -> go.Figure:
    df = analysis.get("result_df")
    if df is None or df.empty:
        return go.Figure()
    tail = df.tail(min(150, len(df)))
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.04)

    fig.add_trace(go.Candlestick(
        x=tail.index, open=tail["open"], high=tail["high"],
        low=tail["low"], close=tail["close"], name=symbol,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=tail.index, y=tail["ema_fast"], name="EMA9",
        line=dict(color="#22d3ee", width=1),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=tail.index, y=tail["ema_slow"], name="EMA21",
        line=dict(color="#f97316", width=1),
    ), row=1, col=1)
    if "vwap" in tail.columns:
        fig.add_trace(go.Scatter(
            x=tail.index, y=tail["vwap"], name="VWAP",
            line=dict(color="#a855f7", width=1.2, dash="dot"),
        ), row=1, col=1)

    plan = analysis.get("trade_plan") or {}
    if plan.get("entry"):
        fig.add_hline(y=plan["entry"], line_dash="dot", line_color="#94a3b8", annotation_text="Entry", row=1, col=1)
    if plan.get("stop_loss"):
        fig.add_hline(y=plan["stop_loss"], line_dash="dash", line_color="#ef4444", annotation_text="SL", row=1, col=1)
    if plan.get("take_profit"):
        fig.add_hline(y=plan["take_profit"], line_dash="dash", line_color="#22c55e", annotation_text="TP", row=1, col=1)

    if "rsi" in tail.columns:
        fig.add_trace(go.Scatter(x=tail.index, y=tail["rsi"], name="RSI", line=dict(color="#eab308", width=1)), row=2, col=1)
        fig.add_hline(y=50, line_dash="dot", line_color="#64748b", row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="#22c55e", row=2, col=1)

    fig.update_layout(
        title=f"{symbol} — Scalping ({analysis.get('chart_tf', '')})",
        template="plotly_dark", height=480,
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)
    return fig


def _render_backtest_metrics(metrics: dict) -> None:
    if not metrics or not metrics.get("total_trades"):
        st.caption("No closed trades in backtest window — try more bars or looser VWAP tolerance.")
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Trades", metrics.get("total_trades", 0))
    c2.metric("Win rate", f"{metrics.get('win_rate', 0):.1f}%")
    c3.metric("Profit factor", f"{metrics.get('profit_factor', 0):.2f}")
    c4.metric("Return", f"{metrics.get('total_return_pct', 0):.2f}%")
    c5.metric("Max DD", f"{metrics.get('max_drawdown_pct', 0):.2f}%")


def _render_screener_table(results: dict) -> None:
    rows = []
    for tick, d in sorted(results.items(), key=lambda x: (x[1].get("analysis") or {}).get("priority", 0), reverse=True):
        if d.get("error"):
            rows.append({"Ticker": tick, "Phase": "ERROR", "Trend": "—", "RSI": "—", "Signal": "—", "BT Win%": "—"})
            continue
        a = d.get("analysis") or {}
        bt = a.get("backtest_metrics") or {}
        rows.append({
            "Ticker": tick,
            "Phase": a.get("phase", "—"),
            "Trend": a.get("trend", "—"),
            "RSI": a.get("rsi", "—"),
            "Signal": (a.get("live_signal") or "flat").upper(),
            "BT Win%": f"{bt.get('win_rate', 0):.1f}%" if bt.get("total_trades") else "—",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_result_block(tick: str, data: dict, provider: str, model: str, api_key: str) -> None:
    if data.get("error"):
        st.error(data["error"])
        return

    analysis = data.get("analysis") or {}
    icon = PHASE_ICONS.get(analysis.get("phase", ""), "⚪")
    st.markdown(f"### {icon} {analysis.get('primary_label', analysis.get('phase', ''))}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Trend", analysis.get("trend", "—"))
    m2.metric("RSI", analysis.get("rsi", "—"))
    m3.metric("VWAP dist %", f"{analysis.get('vwap_dist_pct', 0):.3f}")
    m4.metric("Confidence", f"{analysis.get('confidence', 0):.0f}%")

    _render_backtest_metrics(analysis.get("backtest_metrics") or {})

    eq = analysis.get("equity_df")
    if eq is not None and not eq.empty and "equity" in eq.columns:
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(x=eq["timestamp"], y=eq["equity"], name="Equity", line=dict(color="#22d3ee")))
        fig_eq.update_layout(
            title="Equity curve (backtest window)", template="plotly_dark", height=220,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_eq, width="stretch", config={"displayModeBar": False})

    st.plotly_chart(_build_chart(analysis, tick), width="stretch", config={"displayModeBar": False})

    trades = analysis.get("backtest_trades") or []
    if trades:
        with st.expander("📜 Backtest trade log (last 20)", expanded=False):
            st.dataframe(pd.DataFrame(trades), width="stretch", hide_index=True)

    render_run_summary(summarize_crypto_scalping(analysis, tick))
    render_strategy_mtf_panel(
        symbol=tick,
        market=MARKET,
        groww_token=get_active_groww_token(),
        exchange="NSE",
        primary_tf=analysis.get("chart_tf", "5m"),
        strategy_direction=(analysis.get("trade_plan") or {}).get("direction"),
    )
    show_ai_view_block(
        session_prefix=PREFIX,
        result_key=_safe_key(tick),
        symbol=tick,
        timeframe_label=analysis.get("chart_tf", "5m"),
        build_prompt_fn=lambda t=tick, a=analysis: build_scalp_ai_prompt(t, a),
        system_prompt=SCALP_AI_SYSTEM,
        provider=provider,
        model=model,
        api_key=api_key,
        button_in_column=False,
    )


def render_crypto_scalping_tab() -> None:
    """Crypto scalping — EMA + VWAP + RSI — CoinDCX only."""
    st.markdown("<h1>⚡ Crypto Scalping — EMA + VWAP + RSI</h1>", unsafe_allow_html=True)
    st.write(
        "Rule-based **crypto scalping** on **1m / 5m** candles: **EMA9/21 trend filter**, "
        "**VWAP pullback** entry, **RSI(14)** confirmation, and **ATR-based** risk management. "
        "**CoinDCX Futures** only."
    )

    _render_strategy_explanation()

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets live signal vs backtest stats on loaded bars.",
    )

    st.markdown("---")
    st.markdown("### 📊 Tickers")
    scalp_tickers = render_coindcx_ticker_selection("cscalp")

    st.markdown("### ⏱️ Timeframe & data")
    t1, t2 = st.columns(2)
    with t1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_single_timeframe

        scalp_tf = render_ta_single_timeframe(
            "cscalp",
            SCALPING_TF_OPTIONS,
            role="MTF",
            legacy_default="5m",
            label="Chart TF",
            widget_key="cscalp_tf",
        )
    with t2:
        scalp_bars = st.slider("Bars to load", 300, 1500, 800, 50, key="cscalp_bars")

    st.markdown("### ⚙️ Backtest & risk parameters")
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        risk_pct = st.number_input("Risk % / trade", 0.1, 2.0, 0.5, 0.1, key="cscalp_risk")
    with p2:
        rr = st.number_input("Reward : Risk", 1.0, 3.0, 1.5, 0.1, key="cscalp_rr")
    with p3:
        atr_stop = st.number_input("ATR stop mult", 0.8, 2.5, 1.2, 0.1, key="cscalp_atr")
    with p4:
        vwap_tol = st.number_input("VWAP tolerance %", 0.01, 0.2, 0.05, 0.01, format="%.2f", key="cscalp_vwap")

    with st.expander("⚙️ Advanced fees & limits", expanded=False):
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            fee_pct = st.number_input("Fee % / side", 0.01, 0.2, 0.04, 0.01, format="%.2f", key="cscalp_fee")
        with a2:
            slip_pct = st.number_input("Slippage % / side", 0.0, 0.1, 0.02, 0.01, format="%.2f", key="cscalp_slip")
        with a3:
            max_trades = st.number_input("Max trades / day", 1, 50, 10, key="cscalp_max_trades")
        with a4:
            max_loss = st.number_input("Max daily loss %", 1.0, 10.0, 3.0, 0.5, key="cscalp_max_loss")
        starting_eq = st.number_input("Starting equity ($)", 1000.0, 100_000.0, 10_000.0, 1000.0, key="cscalp_equity")

    st.markdown("### 📁 Optional CSV backtest")
    csv_file = st.file_uploader(
        "Upload OHLCV CSV (timestamp, open, high, low, close, volume)",
        type=["csv"],
        key="cscalp_csv",
    )

    cfg = BacktestConfig(
        risk_pct=float(risk_pct),
        reward_risk=float(rr),
        atr_mult_stop=float(atr_stop),
        vwap_tolerance_pct=float(vwap_tol),
        fee_pct=float(fee_pct),
        slippage_pct=float(slip_pct),
        max_trades_per_day=int(max_trades),
        max_daily_loss_pct=float(max_loss),
        starting_equity=float(starting_eq),
    )

    scalp_actionable = render_ta_screener_options("cscalp")
    st.caption(f"🧮 **{len(scalp_tickers)}** ticker(s) · **{scalp_tf}** · EMA9/21 + VWAP + RSI")

    col_run, col_csv, col_time = st.columns([2, 1, 1])
    with col_run:
        run_btn = st.button("🔎 RUN SCALPING SCAN", type="primary", width="stretch", key="cscalp_run")
    with col_csv:
        csv_btn = st.button("📊 BACKTEST CSV", width="stretch", key="cscalp_csv_run", disabled=csv_file is None)
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('cscalp_last_scan', '—')}")

    if csv_btn and csv_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(csv_file.getvalue())
            tmp_path = tmp.name
        try:
            df = load_ohlcv_csv(tmp_path)
            analysis = analyze_crypto_scalping(df, chart_tf=scalp_tf, cfg=cfg)
            st.session_state.cscalp_csv_result = {"analysis": analysis, "symbol": csv_file.name}
            st.session_state.cscalp_last_scan = datetime.now().strftime("%H:%M:%S")
        except Exception as exc:
            st.error(f"CSV backtest failed: {exc}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if run_btn:
        if not scalp_tickers:
            st.error("Select at least one CoinDCX ticker.")
            return
        groww_token = get_active_groww_token()
        results = {}
        bar = st.progress(0, text="Running scalping scan…")
        for i, tick in enumerate(scalp_tickers):
            bar.progress((i + 1) / len(scalp_tickers), text=f"{tick} — {scalp_tf}…")
            try:
                df = fetch_scalping_data(tick, scalp_tf, MARKET, groww_token, "NSE", scalp_bars)
                if df.empty or len(df) < cfg.ema_slow + 10:
                    results[tick] = {
                        "error": f"Insufficient {scalp_tf} data ({len(df)} bars).",
                        "symbol": tick,
                    }
                    continue
                analysis = analyze_crypto_scalping(df, chart_tf=scalp_tf, cfg=cfg)
                results[tick] = {"analysis": analysis, "symbol": tick}
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)
        bar.empty()
        st.session_state.cscalp_results = results
        st.session_state.cscalp_chart_tf = scalp_tf
        st.session_state.cscalp_last_scan = datetime.now().strftime("%H:%M:%S")

    csv_result = st.session_state.get("cscalp_csv_result")
    if csv_result and not st.session_state.get("cscalp_results"):
        st.markdown("---")
        st.markdown("#### CSV backtest result")
        _render_result_block(csv_result["symbol"], csv_result, provider, model, api_key)
        return

    results = st.session_state.get("cscalp_results", {})
    if not results:
        st.info("Select tickers and click **RUN SCALPING SCAN**, or upload a CSV for offline backtest.")
        return

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
    chart_tf = st.session_state.get("cscalp_chart_tf", scalp_tf)
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, chart_tf, d["error"], tab="Crypto Scalping"))
        else:
            digest.append(summarize_crypto_scalping(d["analysis"], tick))

    if scalp_actionable:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 Scalping Recommendations", group_filter=True)

    tickers_sorted = sorted(
        results.keys(),
        key=lambda t: (results[t].get("analysis") or {}).get("priority", 0),
        reverse=True,
    )
    for ti, tick in enumerate(tickers_sorted):
        data = results[tick]
        if scalp_actionable and not data.get("error") and not (data.get("analysis") or {}).get("actionable"):
            continue
        summary = next((s for s in digest if s.get("ticker") == tick), None)
        with st.expander(
            ticker_section_label(tick, [summary] if summary else []),
            expanded=should_expand_ticker(ti),
        ):
            _render_result_block(tick, data, provider, model, api_key)
