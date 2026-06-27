"""
weekly_stoch_sweet_spot_tab.py
------------------------------
Weekly Stochastic Sweet Spot scanner — Groww & CoinDCX.
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
    summarize_weekly_stoch_sweet_spot,
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
)
from app.market_pulse.weekly_stoch_sweet_spot_engine import (
    SWEET_BOTTOM,
    SWEET_TOP,
    analyze_weekly_stoch,
)

REF_VIDEO_URL = "https://www.youtube.com/watch?v=Tr_RXi6wQko"
PREFIX = "wstoch"
SECTION_ID = "weekly_stoch_sweet_spot"

PHASE_ICONS = {
    "ENTRY_SIGNAL": "🟢",
    "IN_TRADE": "📈",
    "EXIT_SIGNAL": "🔴",
    "APPROACHING": "🟡",
    "SWEET_WATCH": "🔶",
    "NEUTRAL": "⚪",
    "NO_DATA": "⏳",
}

WSTOCH_AI_SYSTEM = """You are an expert swing trader specializing in the Weekly Stochastic Sweet Spot strategy.

Rules:
- **Sweet spot zone**: weekly %K between 32% and 80%
- **Entry (BUY)**: %K (red/fast) crosses above %D (yellow/slow) INTO the sweet spot FROM BELOW 32%,
  with daily volume confirmation (majority of sessions above 20-day avg volume that week)
- **Hold**: ride through overbought (K can exceed 80 while K > D)
- **Exit (SELL)**: %K crosses below %D while %K is BELOW the 80% threshold

Interpret backtest metrics (win rate, avg win/loss, strategy vs buy-and-hold) and the live phase.
For ENTRY or IN_TRADE, give concrete levels, hold time (weeks), green signs, and red flags.
""" + STANDARD_REPORT_FORMAT


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _fmt_pct(val: float | None, *, sign: str = "+") -> str:
    if val is None:
        return "—"
    if sign == "-":
        return f"-{val:.2f}%"
    return f"+{val:.2f}%"


def build_wstoch_ai_prompt(symbol: str, market: str, analysis: dict, currency: str) -> str:
    m = analysis.get("metrics") or {}
    plan = analysis.get("trade_plan") or {}
    lines = [
        "=== WEEKLY STOCHASTIC SWEET SPOT ===",
        f"Symbol: {symbol}",
        f"Market: {market}",
        f"Phase: {analysis.get('phase', 'N/A')} — {analysis.get('primary_label', '')}",
        f"Confidence: {analysis.get('confidence', 0):.0f}%",
        f"Price: {currency}{analysis.get('price', 0):,.4f}",
        "",
        "=== LIVE STOCHASTIC (weekly) ===",
        f"%K (fast/red): {analysis.get('k', '—')}",
        f"%D (slow/yellow): {analysis.get('d', '—')}",
        f"In sweet spot (32–80): {analysis.get('in_sweet_spot', False)}",
        f"Daily volume confirm: {analysis.get('vol_confirm', False)}",
        f"Position: {'LONG' if analysis.get('position') else 'FLAT'}",
        "",
        "=== BACKTEST METRICS ===",
        f"Total trades: {m.get('total_trades', 0)}",
        f"Win rate: {m.get('win_rate_pct', 0)}%",
        f"Avg win: {m.get('avg_win_pct', 0)}% · Avg loss: {m.get('avg_loss_pct', 0)}%",
        f"Strategy return: {m.get('strategy_return_pct', 0)}% · Buy & hold: {m.get('buy_and_hold_ret_pct', 0)}%",
    ]
    for tr in analysis.get("trades") or []:
        lines.append(
            f"  Trade {tr.get('entry_date')} → {tr.get('exit_date')}: "
            f"{tr.get('pnl_pct', 0):+.2f}% ({tr.get('duration_wks', 0)} wks)"
            + (" [OPEN]" if tr.get("open") else "")
        )
    if plan:
        lines.extend([
            "",
            "=== TRADE PLAN ===",
            f"Entry: {currency}{plan.get('entry', 0):,.4f}",
            f"SL: {currency}{plan.get('stop_loss', 0):,.4f} ({_fmt_pct(plan.get('sl_pct'), sign='-')})",
            f"TP: {currency}{plan.get('take_profit', 0):,.4f} ({_fmt_pct(plan.get('tp_pct'))})",
            f"Hold: {plan.get('hold_duration', '—')}",
        ])
    return "\n".join(lines)


def _build_strategy_chart(analysis: dict, symbol: str, currency: str) -> go.Figure:
    df = analysis.get("signals_df")
    if df is None or df.empty:
        return go.Figure()

    m = analysis.get("metrics") or {}
    init_cap = m.get("initial_capital", 10_000)
    bh = init_cap * (df["close"] / df["close"].iloc[0])

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.45, 0.30, 0.25],
        subplot_titles=(
            f"{symbol} — Weekly Close",
            "Weekly Stochastic (%K red · %D yellow)",
            "Strategy Equity vs Buy & Hold",
        ),
    )

    fig.add_trace(
        go.Scatter(x=df.index, y=df["close"], name="Close", line=dict(color="#4fc3f7", width=1.5)),
        row=1, col=1,
    )

    entries = df[df["entry_signal"]]
    exits = df[df["exit_signal"]]
    if not entries.empty:
        fig.add_trace(
            go.Scatter(
                x=entries.index, y=entries["close"], mode="markers",
                name="Entry", marker=dict(symbol="triangle-up", size=10, color="#00e676"),
            ),
            row=1, col=1,
        )
    if not exits.empty:
        fig.add_trace(
            go.Scatter(
                x=exits.index, y=exits["close"], mode="markers",
                name="Exit", marker=dict(symbol="triangle-down", size=10, color="#ff5252"),
            ),
            row=1, col=1,
        )

    fig.add_trace(
        go.Scatter(x=df.index, y=df["K"], name="%K", line=dict(color="#ef5350", width=1.2)),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=df["D"], name="%D", line=dict(color="#ffd54f", width=1, dash="dash")),
        row=2, col=1,
    )
    fig.add_hrect(
        y0=SWEET_BOTTOM, y1=SWEET_TOP, fillcolor="rgba(105,240,174,0.12)",
        line_width=0, row=2, col=1,
    )
    fig.add_hline(y=SWEET_BOTTOM, line_dash="dot", line_color="#69f0ae", row=2, col=1)
    fig.add_hline(y=SWEET_TOP, line_dash="dot", line_color="#ff9800", row=2, col=1)

    if "equity" in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["equity"], name="Strategy", line=dict(color="#ce93d8", width=1.2)),
            row=3, col=1,
        )
    fig.add_trace(
        go.Scatter(x=df.index, y=bh, name="Buy & Hold", line=dict(color="#78909c", width=1, dash="dash")),
        row=3, col=1,
    )

    fig.update_layout(
        template="plotly_dark",
        height=720,
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
    )
    fig.update_yaxes(title_text=f"Price ({currency.strip()})", row=1, col=1)
    fig.update_yaxes(title_text="Stoch", range=[0, 100], row=2, col=1)
    fig.update_yaxes(title_text="Equity", row=3, col=1)
    return fig


def _render_setup_alerts(results: dict) -> None:
    entries, in_trade, approaching = [], [], []
    for tick, d in results.items():
        if d.get("error"):
            continue
        phase = d.get("phase", "")
        if phase == "ENTRY_SIGNAL":
            entries.append(tick)
        elif phase == "IN_TRADE":
            in_trade.append(tick)
        elif phase in ("APPROACHING", "SWEET_WATCH"):
            approaching.append(tick)

    if entries:
        st.success(f"**{len(entries)} ENTRY signal(s) this week:** " + ", ".join(f"**{t}**" for t in entries[:10]))
    if in_trade:
        st.info(f"**{len(in_trade)} in active trade:** " + ", ".join(f"**{t}**" for t in in_trade[:10]))
    if approaching:
        st.warning(
            f"**{len(approaching)} approaching sweet spot:** "
            + ", ".join(f"**{t}**" for t in approaching[:10])
        )


def _render_screener_grid(results: dict) -> None:
    rows = []
    for tick, d in results.items():
        if d.get("error"):
            rows.append({
                "Ticker": tick, "Phase": "ERROR", "K": "—", "D": "—",
                "Vol": "—", "Conf.": "—", "Win%": "—", "Strat Ret": "—", "_priority": -1,
            })
            continue
        m = d.get("metrics") or {}
        plan = d.get("trade_plan") or {}
        rows.append({
            "Ticker": tick,
            "Phase": d.get("phase", "—"),
            "K": f"{d.get('k', 0):.1f}",
            "D": f"{d.get('d', 0):.1f}",
            "Vol": "✅" if d.get("vol_confirm") else "❌",
            "Conf.": f"{d.get('confidence', 0):.0f}%",
            "SL %": _fmt_pct(plan.get("sl_pct"), sign="-") if plan.get("sl_pct") else "—",
            "TP %": _fmt_pct(plan.get("tp_pct")) if plan.get("tp_pct") else "—",
            "Win%": f"{m.get('win_rate_pct', 0):.0f}%",
            "Strat Ret": f"{m.get('strategy_return_pct', 0):+.1f}%",
            "_priority": d.get("priority", 0),
        })

    st.markdown("#### 📋 Screener Grid")
    df = pd.DataFrame(rows).sort_values("_priority", ascending=False)
    st.dataframe(df.drop(columns=["_priority"]), width='stretch', hide_index=True)


def _render_result_block(
    ticker: str,
    data: dict,
    is_crypto: bool,
    market: str,
    provider: str,
    model: str,
    api_key: str,
) -> None:
    currency = "$" if is_crypto else "₹"

    if data.get("error"):
        st.error(data["error"])
        return

    phase = data.get("phase", "NEUTRAL")
    icon = PHASE_ICONS.get(phase, "📊")
    st.markdown(f"### {icon} {data.get('primary_label', phase)}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("%K", f"{data.get('k', 0):.1f}")
    c2.metric("%D", f"{data.get('d', 0):.1f}")
    c3.metric("Sweet Spot", "✅" if data.get("in_sweet_spot") else "❌")
    c4.metric("Vol Confirm", "✅" if data.get("vol_confirm") else "❌")
    c5.metric("Confidence", f"{data.get('confidence', 0):.0f}%")
    c6.metric("Position", "LONG" if data.get("position") else "FLAT")

    m = data.get("metrics") or {}
    st.markdown("#### 📊 Backtest Performance")
    b1, b2, b3, b4, b5, b6 = st.columns(6)
    b1.metric("Trades", m.get("total_trades", 0))
    b2.metric("Win Rate", f"{m.get('win_rate_pct', 0):.0f}%")
    b3.metric("Avg Win", f"{m.get('avg_win_pct', 0):+.1f}%")
    b4.metric("Avg Loss", f"{m.get('avg_loss_pct', 0):+.1f}%")
    b5.metric("Strategy", f"{m.get('strategy_return_pct', 0):+.1f}%")
    b6.metric("Buy & Hold", f"{m.get('buy_and_hold_ret_pct', 0):+.1f}%")

    plan = data.get("trade_plan")
    if plan:
        st.markdown("#### 🎯 Trade Plan")
        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("Entry", f"{currency}{plan.get('entry', 0):,.2f}")
        p2.metric("SL", _fmt_pct(plan.get("sl_pct"), sign="-"))
        p3.metric("TP", _fmt_pct(plan.get("tp_pct")))
        p4.metric("R:R", f"1:{plan.get('rr_ratio', 0):.1f}")
        p5.metric("Hold", plan.get("hold_duration", "—"))

    trades = data.get("trades") or []
    if trades:
        st.markdown("#### 📜 Recent Trades")
        st.dataframe(pd.DataFrame(trades), width='stretch', hide_index=True)

    fig = _build_strategy_chart(data, ticker, currency)
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

    summary = summarize_weekly_stoch_sweet_spot(data, ticker)
    render_run_summary(summary)
    plan = data.get("trade_plan") or {}
    render_strategy_mtf_panel(
        symbol=ticker,
        market=market,
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("wstoch_results_exchange", st.session_state.get("wstoch_exchange", "NSE")),
        primary_tf="1w",
        strategy_direction=plan.get("direction"),
    )

    show_ai_view_block(
        session_prefix=PREFIX,
        result_key=_safe_key(ticker),
        symbol=ticker,
        timeframe_label="Weekly Stoch",
        build_prompt_fn=lambda t=ticker, m=market, a=data, c=currency: build_wstoch_ai_prompt(t, m, a, c),
        system_prompt=WSTOCH_AI_SYSTEM,
        provider=provider,
        model=model,
        api_key=api_key,
        button_in_column=False,
    )


def render_weekly_stoch_sweet_spot_tab():
    """Weekly Stochastic Sweet Spot scanner — Groww & CoinDCX."""
    st.markdown("<h1>📈 Weekly Stochastic Sweet Spot</h1>", unsafe_allow_html=True)
    st.write(
        "Swing scanner based on the **weekly stochastic sweet spot (32–80%)**: enter when **%K crosses above %D** "
        "from below the zone with **daily volume confirmation**, hold through overbought, exit on bearish cross below 80%."
    )

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets live stochastic phase, backtest stats, and trade plan per ticker.",
    )

    st.markdown("---")

    m1, m2 = st.columns(2)
    with m1:
        wstoch_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            key="wstoch_market",
        )
    with m2:
        wstoch_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="wstoch_exchange")
            if is_india_market(wstoch_market) else "NSE"
        )

    st.markdown("### 📊 Tickers")
    wstoch_tickers: list[str] = []
    if is_crypto_market(wstoch_market):
        wstoch_tickers = render_coindcx_ticker_selection("wstoch")
    else:
        wstoch_tickers = render_equity_index_ticker_selection(wstoch_market, "wstoch")

    is_crypto = is_crypto_market(wstoch_market)

    from app.market_pulse.ta_mtf_hub_ui import render_ta_hub_badge

    render_ta_hub_badge("wstoch")
    st.caption("Weekly Stoch uses **weekly** bars; hub HTF provides higher-level trend context in AI View.")

    st.markdown("### ⚙️ Strategy Parameters")
    p1, p2, p3, p4, p5 = st.columns(5)
    with p1:
        wstoch_period = st.selectbox("History", ["2y", "5y", "10y"], index=1, key="wstoch_period")
    with p2:
        wstoch_k = st.number_input("%K period (weeks)", 5, 21, 14, key="wstoch_k")
    with p3:
        wstoch_d = st.number_input("%D smoothing", 2, 7, 3, key="wstoch_d")
    with p4:
        wstoch_vol = st.number_input("Vol MA (days)", 10, 40, 20, key="wstoch_vol")
    with p5:
        wstoch_capital = st.number_input("Backtest capital", 1000, 100_000, 10_000, step=1000, key="wstoch_cap")

    wstoch_actionable_only = render_ta_screener_options("wstoch")
    st.caption(f"🧮 **{len(wstoch_tickers)}** ticker(s) · **{wstoch_period}** daily history → weekly bars")

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button(
            "🔎 RUN SWEET SPOT SCAN",
            type="primary",
            width='stretch',
            key="wstoch_run",
        )
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('wstoch_last_scan', '—')}")

    if run_btn:
        if not wstoch_tickers:
            st.error("Select at least one ticker.")
            return

        bar = st.progress(0, text="Scanning weekly stochastic sweet spot…")
        groww_token = get_active_groww_token()
        results: dict[str, dict] = {}
        n = len(wstoch_tickers)

        for i, tick in enumerate(wstoch_tickers):
            bar.progress((i + 1) / n, text=f"{tick} — weekly stoch analysis…")
            try:
                results[tick] = analyze_weekly_stoch(
                    tick,
                    wstoch_market,
                    groww_token,
                    wstoch_exchange,
                    period=wstoch_period,
                    k_period=int(wstoch_k),
                    d_period=int(wstoch_d),
                    vol_lookback=int(wstoch_vol),
                    initial_capital=float(wstoch_capital),
                )
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)

        bar.empty()
        st.session_state.wstoch_results = results
        st.session_state.wstoch_results_market = wstoch_market
        st.session_state.wstoch_is_crypto = is_crypto
        st.session_state.wstoch_results_exchange = wstoch_exchange
        st.session_state.wstoch_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("wstoch_results", {})
    market_disp = st.session_state.get("wstoch_results_market", wstoch_market)
    is_crypto = st.session_state.get("wstoch_is_crypto", is_crypto)

    if not results:
        st.info("Select tickers, then click **RUN SWEET SPOT SCAN**.")
        return

    st.markdown("---")
    _render_setup_alerts(results)
    _render_screener_grid(results)

    digest = []
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, "Weekly", d["error"], tab="Weekly Stoch Sweet Spot"))
        else:
            digest.append(summarize_weekly_stoch_sweet_spot(d, tick))

    if wstoch_actionable_only:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 Sweet Spot Recommendations", group_filter=True)

    tickers_sorted = sorted(
        results.keys(),
        key=lambda t: results[t].get("priority", 0) if not results[t].get("error") else -1,
        reverse=True,
    )

    for ti, ticker in enumerate(tickers_sorted):
        data = results[ticker]
        if wstoch_actionable_only and not data.get("error"):
            if not data.get("actionable"):
                continue

        summary = next((s for s in digest if s.get("ticker") == ticker), None)
        summaries = [summary] if summary else []

        with st.expander(
            ticker_section_label(ticker, summaries),
            expanded=should_expand_ticker(ti) and not data.get("error") and data.get("actionable", False),
        ):
            _render_result_block(ticker, data, is_crypto, market_disp, provider, model, api_key)

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai(SECTION_ID)

    st.caption("⚠️ Weekly swing signals — confirm with daily chart and risk management before trading.")
