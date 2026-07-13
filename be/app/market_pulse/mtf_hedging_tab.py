"""
mtf_hedging_tab.py
------------------
Multi-Timeframe Hedging — Beta, Pairs, Delta (puts), Inverse/Index ETF, Crypto correlation.
Groww (India) · US Stocks · CoinDCX crypto · LTF / MTF / HTF chart timeframes.
"""

from __future__ import annotations

from contextlib import nullcontext

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from app.market_pulse.hedging_toolkit_engine import (
    CRYPTO_HEDGE_DEFAULT,
    HEDGE_ROLES,
    INDIA_BENCHMARK_OPTIONS,
    MTF_PERIOD_LABELS,
    US_BENCHMARK_OPTIONS,
    currency_for_market,
    hedge_tf_options,
    run_full_mtf_hedging_suite,
    timeframe_label,
)
from app.market_pulse.ta_screener_ui import render_strategy_mtf_panel
from app.market_pulse.ticker_selection_ui import render_hedge_ticker_picker
from app.market_pulse.ticker_utils import (
    CRYPTO_MARKET,
    GROWW_MARKET,
    US_MARKET,
    is_crypto_market,
    is_india_market,
)

HEDGING_MARKETS = [GROWW_MARKET, US_MARKET, CRYPTO_MARKET]

STRATEGY_LABELS = {
    "beta": "Beta Hedge (Short Index / Sell ETF)",
    "pairs": "Pairs Trade (Stat-Arb)",
    "delta": "Delta Hedge (Put Options)",
    "inverse_etf": "Inverse / Index ETF Hedge",
    "crypto": "Crypto Min-Variance Hedge",
    "portfolio_risk": "Portfolio Risk Metrics",
}


def _first_ticker(picks: list[str], fallback: str) -> str:
    return (picks[0] if picks else fallback).strip()


def _display_value(value: Any) -> str:
    """Normalize result values for Streamlit/PyArrow (no mixed list/scalar column)."""
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _result_table(result: dict[str, Any] | None) -> None:
    if not result:
        st.warning("Insufficient data for this window.")
        return
    skip = {"interpretation", "strategy", "period", "timeframe", "timeframe_label"}
    rows = [(k, _display_value(v)) for k, v in result.items() if k not in skip]
    st.dataframe(pd.DataFrame(rows, columns=["Field", "Value"]), hide_index=True, width='stretch')
    interp = result.get("interpretation")
    if interp:
        st.info(f"💡 {interp}")


def _render_pairs_spread_chart(spread_df: pd.DataFrame | None, ticker_a: str, ticker_b: str) -> None:
    if spread_df is None or spread_df.empty:
        return
    fig = go.Figure()
    idx = spread_df.index
    fig.add_trace(go.Scatter(x=idx, y=spread_df["spread"], name="Spread", line=dict(color="#60a5fa", width=2)))
    fig.add_trace(go.Scatter(x=idx, y=spread_df["upper"], name="+1.5σ", line=dict(color="#f87171", dash="dot", width=1)))
    fig.add_trace(go.Scatter(x=idx, y=spread_df["lower"], name="-1.5σ", line=dict(color="#34d399", dash="dot", width=1)))
    fig.add_hline(y=float(spread_df["mean"].iloc[0]), line_dash="dash", line_color="#94a3b8", annotation_text="Mean")
    fig.update_layout(
        title=f"Pairs spread: {ticker_a} vs {ticker_b}",
        height=320,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.8)",
        font=dict(color="#94a3b8", size=11),
        margin=dict(l=40, r=20, t=50, b=30),
        legend=dict(orientation="h", y=-0.2),
    )
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})


def _render_mtf_strategy_block(strategy_key: str, suite: dict[str, Any]) -> None:
    st.markdown(f"#### {STRATEGY_LABELS.get(strategy_key, strategy_key)}")
    roles = suite.get("roles") or list(HEDGE_ROLES)
    tf_map = suite.get("timeframes") or {}
    tab_labels = [
        f"{MTF_PERIOD_LABELS.get(r, r)} · {timeframe_label(tf_map.get(r, '1d'))}"
        for r in roles
    ]
    period_tabs = st.tabs(tab_labels)
    for tab, role in zip(period_tabs, roles):
        with tab:
            block = (suite.get("strategies") or {}).get(role, {})
            _result_table(block.get(strategy_key))


def _render_mtf_comparison_table(suite: dict[str, Any], field: str, strategy_key: str) -> None:
    rows = []
    for role in suite.get("roles") or HEDGE_ROLES:
        block = (suite.get("strategies") or {}).get(role, {})
        res = block.get(strategy_key) or {}
        tf = (suite.get("timeframes") or {}).get(role, "")
        rows.append({
            "Role": role,
            "Chart TF": tf,
            field: _display_value(res.get(field, "—")),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')


def render_mtf_hedging_tab() -> None:
    """Multi-Timeframe Hedging toolkit for India, US, and crypto."""
    st.markdown(
        "<h3>🛡️ Multi-Timeframe Hedging</h3>"
        "<p style='color:#94a3b8;margin-top:0;'>"
        "Groww · US · Crypto — index/universe dropdowns, multiselect + custom tickers, "
        "and <b>LTF · MTF · HTF</b> chart timeframes.</p>",
        unsafe_allow_html=True,
    )

    market = st.selectbox(
        "Market",
        HEDGING_MARKETS,
        key="mtf_hedge_market",
    )
    cur = currency_for_market(market)
    tf_opts = hedge_tf_options(market)

    st.markdown("##### 📊 LTF · MTF · HTF timeframes")
    from app.market_pulse.ta_mtf_hub_ui import render_ta_role_selectboxes

    tf_map = render_ta_role_selectboxes(
        "mtf_hedge",
        tf_opts,
        role_order=("LTF", "MTF", "HTF"),
        labels={r: MTF_PERIOD_LABELS.get(r, r) for r in HEDGE_ROLES},
    )

    st.markdown("##### 🎯 Primary position")
    primary_picks = render_hedge_ticker_picker(
        market, "mtf_hedge_primary", single=True, label="Primary",
    )
    primary = _first_ticker(
        primary_picks,
        "RELIANCE" if is_india_market(market) else ("AAPL" if not is_crypto_market(market) else "B-BTCUSDT"),
    )

    st.markdown("##### ↔ Pairs / hedge leg")
    pair_picks = render_hedge_ticker_picker(
        market, "mtf_hedge_pair", single=True, label="Pairs leg",
    )
    pair_ticker = _first_ticker(
        pair_picks,
        "TCS" if is_india_market(market) else ("MSFT" if not is_crypto_market(market) else "B-ETHUSDT"),
    )

    if is_crypto_market(market):
        benchmark = CRYPTO_HEDGE_DEFAULT
    elif is_india_market(market):
        benchmark = st.selectbox(
            "Benchmark index (beta / ETF hedge)",
            INDIA_BENCHMARK_OPTIONS,
            key="mtf_hedge_in_bench",
        )
    else:
        benchmark = st.selectbox("Benchmark / beta index", US_BENCHMARK_OPTIONS, key="mtf_hedge_bench")

    st.markdown("##### 📁 Portfolio risk basket (multiselect or custom)")
    basket_picks = render_hedge_ticker_picker(
        market, "mtf_hedge_basket", single=False, label="Portfolio basket", default_count=3,
    )
    if not basket_picks:
        basket_picks = (
            ["RELIANCE", "TCS", "INFY"] if is_india_market(market)
            else (["AAPL", "MSFT", "GOOGL"] if not is_crypto_market(market) else ["B-BTCUSDT", "B-ETHUSDT"])
        )

    n = len(basket_picks)
    st.caption(f"Selected **{n}** ticker(s) for portfolio VaR / Sharpe.")
    eq_w = round(1.0 / n, 4) if n else 1.0
    weights_raw = st.text_input(
        "Weights (comma-separated, optional — defaults to equal)",
        value=",".join([str(eq_w)] * n),
        key="mtf_hedge_weights",
    )

    default_port_val = 1_000_000.0 if is_india_market(market) else 100_000.0
    default_pair_val = 500_000.0 if is_india_market(market) else 50_000.0

    c1, c2, c3 = st.columns(3)
    with c1:
        portfolio_value = st.number_input(
            f"Portfolio value ({cur})",
            min_value=1_000.0,
            value=default_port_val,
            step=50_000.0 if is_india_market(market) else 5_000.0,
            key="mtf_hedge_port_val",
        )
    with c2:
        pair_value = st.number_input(
            f"Pairs notional ({cur})",
            min_value=1_000.0,
            value=default_pair_val,
            step=25_000.0 if is_india_market(market) else 5_000.0,
            key="mtf_hedge_pair_val",
        )
    with c3:
        hedge_label = "Index ETF hedge %" if is_india_market(market) else "Inverse ETF hedge %"
        hedge_pct = st.slider(hedge_label, 0.1, 1.0, 0.5, 0.05, key="mtf_hedge_inv_pct")

    strike_pct = 0.95
    days_to_expiry = 30
    if not is_crypto_market(market):
        d1, d2 = st.columns(2)
        with d1:
            strike_pct = st.slider("Put strike (% of spot)", 0.85, 1.0, 0.95, 0.01, key="mtf_hedge_strike")
        with d2:
            days_to_expiry = st.slider("Put days to expiry", 7, 90, 30, key="mtf_hedge_dte")

    if is_india_market(market):
        st.caption("India: hedge via NIFTYBEES / BANKBEES / ITBEES · puts are NSE F&O estimates.")

    run_btn = st.button("🛡️ Run MTF Hedging Analysis", type="primary", key="mtf_hedge_run")

    if run_btn:
        try:
            weights = [float(w.strip()) for w in weights_raw.split(",") if w.strip()]
        except ValueError:
            weights = [eq_w] * n
        if len(weights) != n:
            weights = [1.0 / n] * n

        with nullcontext():
            suite = run_full_mtf_hedging_suite(
                market=market,
                portfolio_ticker=primary,
                pair_ticker=pair_ticker,
                benchmark=benchmark,
                hedge_asset=CRYPTO_HEDGE_DEFAULT,
                portfolio_value=float(portfolio_value),
                pair_value=float(pair_value),
                hedge_pct=float(hedge_pct),
                strike_pct=float(strike_pct),
                days_to_expiry=int(days_to_expiry),
                portfolio_tickers=basket_picks,
                portfolio_weights=weights,
                timeframes=tf_map,
            )
        st.session_state["mtf_hedging_payload"] = suite

    suite = st.session_state.get("mtf_hedging_payload")
    if not suite or suite.get("market") != market:
        st.info(
            "Pick tickers from index/universe dropdowns (or Custom), set **LTF · MTF · HTF** chart "
            "timeframes, then click **Run MTF Hedging Analysis**."
        )
        return

    tf_disp = suite.get("timeframes") or {}
    st.success(
        f"**{suite.get('primary_yf')}** · pairs **{suite.get('pair_yf')}** · "
        f"benchmark **{suite.get('benchmark_yf')}** · "
        f"LTF `{tf_disp.get('LTF')}` · MTF `{tf_disp.get('MTF')}` · HTF `{tf_disp.get('HTF')}`"
    )

    if is_crypto_market(market):
        _render_mtf_strategy_block("crypto", suite)
        st.divider()

    if not is_crypto_market(market):
        _render_mtf_strategy_block("beta", suite)
        st.markdown("**Beta across LTF · MTF · HTF**")
        _render_mtf_comparison_table(suite, "beta", "beta")
        st.divider()
        _render_mtf_strategy_block("inverse_etf", suite)
        st.divider()
        _render_mtf_strategy_block("delta", suite)
        st.divider()
    else:
        _render_mtf_strategy_block("beta", suite)
        st.divider()

    _render_mtf_strategy_block("pairs", suite)
    spread_df = suite.get("pairs_spread")
    if spread_df is not None:
        _render_pairs_spread_chart(spread_df, suite.get("primary_yf", ""), suite.get("pair_yf", ""))

    st.divider()
    _render_mtf_strategy_block("portfolio_risk", suite)

    st.divider()
    render_strategy_mtf_panel(
        symbol=primary,
        market=market,
        primary_tf=tf_map.get("MTF", "1d"),
        expanded=False,
    )

    from app.market_pulse.ask_ai_context import sync_ask_ai_context
    sync_ask_ai_context("mtf_hedging")
