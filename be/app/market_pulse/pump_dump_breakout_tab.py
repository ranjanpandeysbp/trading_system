"""
pump_dump_breakout_tab.py
-------------------------
Market Pulse — Pump & Dump consolidation breakout / breakdown strategy.
"""

from __future__ import annotations

import pandas as pd
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.news_scanner import _render_news_scanner_styles
from app.market_pulse.pump_dump_breakout_engine import StrategyConfig, run_analysis
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import MARKET_OPTIONS, is_crypto_market, market_currency

_PREFIX = "pdb_breakout"
_PAYLOAD_KEY = "pump_dump_breakout_payload"

STRATEGY_EXPLANATION = """
### Pump & Dump Consolidation-Breakout Strategy

Implements the informal playbook:

1. **SCREEN** — highly volatile / trending tokens that already pumped (10%+ 24h) or dumped hard,  
   with a history of **repeating pump → consolidate → dump** cycles (Alpha / trending boards).

2. **WAIT** — price enters a **tight sideways consolidation box** after the impulse move.

3. **ENTER** on confirmed break:
   - **SHORT** — breakdown below consolidation (post-pump distribution)
   - **LONG** — breakout above a tight bottoming base (post-dump reversal)
   - Confirmation = **close** beyond zone + optional **volume spike** (filters wicks)

4. **RISK**
   - Stop loss: **2–4%** (default 3%)
   - Take profit: **10–20%** (default 15%) → ~5:1 R:R
   - Leverage capped at **10x** (default 5x); sizing by **% account risked**, not leverage
   - Fees applied entry + exit in backtest

---

| Stage | Rule |
|-------|------|
| Consolidation | Range over lookback ≤ max % · min bars inside box |
| Breakdown | Close below zone low − buffer % + volume ≥ 1.5× avg |
| Breakout | Close above zone high + buffer % + volume spike |
| Sizing | `risk_$ = equity × risk%` → units from SL distance |

> **Disclaimer:** Meme / pump-and-dump trading is extremely high risk.  
> Backtests on thin books often fail live (slippage, stop hunts, illiquidity).  
> **Signal generator + backtester only** — not live execution. **NOT FINANCIAL ADVICE.**
"""


def _render_strategy_explanation() -> None:
    with st.expander("📖 Strategy explanation — Pump & Dump Breakout / Breakdown", expanded=False):
        st.markdown(STRATEGY_EXPLANATION)


def _render_screening(res: dict) -> None:
    st.markdown("##### 🔍 Screening checklist")
    if res.get("screened"):
        st.success(
            f"**PASS** — 24h Δ **{res.get('change_24h_pct'):+.1f}%** · "
            f"repeating cycles **{'yes' if res.get('repeating_cycles') else 'no'}** · "
            f"trending={res.get('is_trending_listed')} · alpha={res.get('is_alpha_listed')}"
        )
    else:
        reasons = []
        ch = res.get("change_24h_pct", 0)
        if not (ch >= 10.0 or ch <= -20.0):
            reasons.append(f"24h move {ch:+.1f}% below pump/dump threshold")
        if not (res.get("is_trending_listed") or res.get("is_alpha_listed")):
            reasons.append("not flagged trending/alpha")
        if not res.get("repeating_cycles"):
            reasons.append("no repeating pump-dump cycles detected")
        st.warning("**FAIL screen** — " + "; ".join(reasons) if reasons else "**FAIL screen**")


def _render_live_state(live: dict, *, currency: str) -> None:
    st.markdown("##### 🎯 Live state (last bar)")
    if not live:
        st.caption("No live state.")
        return

    price = live.get("price")
    if price is not None:
        st.caption(f"Last close: **{currency}{price:,.6g}**")

    if live.get("is_consolidating"):
        zh, zl = live.get("zone_high"), live.get("zone_low")
        st.info(
            f"**CONSOLIDATING** — box **{currency}{zl:,.6g}** – **{currency}{zh:,.6g}** "
            f"(watch for breakout/breakdown + volume)"
        )
    elif live.get("watch"):
        st.caption("Monitoring for consolidation…")

    setup = live.get("latest_signal")
    if setup:
        side = setup.get("side", "—")
        badge = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
        st.success(
            f"**{badge}** · {setup.get('status')} · SL **-{setup.get('sl_pct')}%** · "
            f"TP **+{setup.get('tp_pct')}%** · R:R **{setup.get('rr_ratio')}** · "
            f"lev **{setup.get('leverage')}x**"
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Entry", f"{currency}{setup.get('entry', 0):,.6g}")
        with c2:
            st.metric("Stop", f"{currency}{setup.get('sl_price', 0):,.6g}")
        with c3:
            st.metric("Target", f"{currency}{setup.get('tp_price', 0):,.6g}")
    elif not live.get("is_consolidating"):
        st.caption("No fresh breakout signal on the latest bar.")


def _render_backtest(summary: dict, trades: list) -> None:
    st.markdown("##### 📊 Backtest (loaded window)")
    if not summary or summary.get("trades", 0) == 0:
        st.caption("No completed trades in this window — loosen consolidation or load more bars.")
        return
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Trades", summary.get("trades", 0))
    with c2:
        st.metric("Win rate", f"{summary.get('win_rate_pct', 0)}%")
    with c3:
        st.metric("Net PnL", f"${summary.get('net_pnl_$', 0)}")
    with c4:
        st.metric("Breakeven WR", f"{summary.get('breakeven_win_rate_pct_needed', 0)}%")
    st.caption(
        f"Configured R:R **{summary.get('configured_rr_ratio')}** · "
        f"Final balance **${summary.get('final_balance_$')}**"
    )
    if trades:
        st.dataframe(pd.DataFrame(trades), hide_index=True, width="stretch")


def _run_ticker(
    ticker: str,
    market: str,
    timeframe: str,
    *,
    config: StrategyConfig,
    is_trending: bool,
    is_alpha: bool,
    bar_limit: int,
    initial_balance: float,
) -> dict:
    groww = get_active_groww_token() if "Groww" in market else ""
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww, "NSE", limit=bar_limit)
    if df is None or df.empty:
        return {"symbol": ticker, "error": "No OHLCV data returned."}
    return run_analysis(
        df,
        symbol=ticker,
        config=config,
        initial_balance=initial_balance,
        is_trending_listed=is_trending,
        is_alpha_listed=is_alpha,
        timeframe=timeframe,
    )


def render_pump_dump_breakout_tab(get_logged_in_mobile=None) -> None:
    """Market Pulse — pump/dump consolidation breakout & breakdown."""
    _render_news_scanner_styles()
    _render_strategy_explanation()

    st.caption(
        "Screen volatile trending tokens → detect **consolidation boxes** → "
        "trade **breakdown** (short) or **breakout** (long) with volume confirmation."
    )

    market = st.selectbox(
        "Market",
        MARKET_OPTIONS,
        index=2 if len(MARKET_OPTIONS) > 2 else 0,
        key=f"{_PREFIX}_market",
    )
    is_crypto = is_crypto_market(market)
    currency = market_currency(market)

    if is_crypto:
        tickers = render_coindcx_ticker_selection(f"{_PREFIX}_crypto")
    else:
        tickers = render_equity_index_ticker_selection(market, f"{_PREFIX}_eq", default_count=3)

    timeframe = st.selectbox("Timeframe", ["5m", "15m", "1h", "4h"], index=1, key=f"{_PREFIX}_tf")
    bar_limits = {"5m": 500, "15m": 450, "1h": 400, "4h": 300}
    bar_limit = bar_limits.get(timeframe, 400)

    c1, c2 = st.columns(2)
    with c1:
        is_trending = st.checkbox(
            "Treat as trending-board listed",
            value=True,
            key=f"{_PREFIX}_trending",
            help="Manual flag for exchange trending / hot list (crypto default on).",
        )
    with c2:
        is_alpha = st.checkbox(
            "Treat as Alpha / innovation zone",
            value=is_crypto,
            key=f"{_PREFIX}_alpha",
        )

    with st.expander("⚙️ Strategy & risk parameters", expanded=False):
        consolidation_max = st.slider("Max consolidation range %", 3.0, 12.0, 6.0, 0.5, key=f"{_PREFIX}_box")
        breakout_buffer = st.slider("Breakout buffer %", 0.2, 2.0, 0.5, 0.1, key=f"{_PREFIX}_buf")
        vol_spike = st.slider("Volume spike multiplier", 1.0, 3.0, 1.5, 0.1, key=f"{_PREFIX}_vol")
        require_vol = st.checkbox("Require volume spike", value=True, key=f"{_PREFIX}_req_vol")
        sl_pct = st.slider("Stop loss %", 2.0, 4.0, 3.0, 0.25, key=f"{_PREFIX}_sl")
        tp_pct = st.slider("Take profit %", 10.0, 20.0, 15.0, 0.5, key=f"{_PREFIX}_tp")
        leverage = st.slider("Leverage (max 10x)", 2, 10, 5, 1, key=f"{_PREFIX}_lev")
        risk_pct = st.slider("Risk per trade % of equity", 0.5, 3.0, 1.0, 0.25, key=f"{_PREFIX}_risk")
        initial_balance = st.number_input("Backtest starting balance ($)", 100.0, 100_000.0, 1000.0, key=f"{_PREFIX}_bal")
        allow_long = st.checkbox("Allow LONG breakouts", value=True, key=f"{_PREFIX}_long")
        allow_short = st.checkbox("Allow SHORT breakdowns", value=True, key=f"{_PREFIX}_short")

    try:
        config = StrategyConfig(
            consolidation_max_range_pct=consolidation_max,
            breakout_buffer_pct=breakout_buffer,
            volume_spike_multiplier=vol_spike,
            require_volume_spike=require_vol,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            leverage=leverage,
            risk_per_trade_pct=risk_pct,
            allow_long=allow_long,
            allow_short=allow_short,
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    run = st.button("▶ Run Pump/Dump Breakout scan", type="primary", key=f"{_PREFIX}_run", use_container_width=True)

    if run:
        if not tickers:
            st.warning("Select at least one ticker.")
        else:
            prog = st.progress(0, text="Scanning consolidation zones…")
            results = []
            for i, ticker in enumerate(tickers):
                prog.progress((i + 0.2) / len(tickers), text=f"Analyzing {ticker}…")
                try:
                    results.append(_run_ticker(
                        ticker, market, timeframe,
                        config=config,
                        is_trending=is_trending,
                        is_alpha=is_alpha,
                        bar_limit=bar_limit,
                        initial_balance=float(initial_balance),
                    ))
                except Exception as exc:
                    results.append({"symbol": ticker, "error": str(exc)[:200]})
                prog.progress((i + 1) / len(tickers), text=f"Done {ticker}")
            prog.empty()
            st.session_state[_PAYLOAD_KEY] = {
                "market": market,
                "timeframe": timeframe,
                "currency": currency,
                "results": results,
            }

    payload = st.session_state.get(_PAYLOAD_KEY)
    if not payload:
        return

    st.markdown("---")
    st.markdown(f"##### Results · `{payload.get('timeframe')}` · {payload.get('market')}")

    screened_pass = [r for r in payload.get("results") or [] if r.get("screened")]
    if screened_pass:
        st.caption(f"**{len(screened_pass)}** ticker(s) passed the pump/dump screen.")

    for i, res in enumerate(payload.get("results") or []):
        sym = res.get("symbol", "?")
        if res.get("error"):
            st.error(f"**{sym}** — {res['error']}")
            continue

        flag = "✅ SCREEN" if res.get("screened") else "⚠️ WATCH"
        live = res.get("live") or {}
        sig = (live.get("latest_signal") or {}).get("side", "—")
        headline = f"{flag} **{sym}** · 24h {res.get('change_24h_pct', 0):+.1f}% · signal {sig}"

        with st.expander(headline, expanded=(i == 0 and res.get("screened"))):
            _render_screening(res)
            _render_live_state(live, currency=currency)
            counts = res.get("signal_counts") or {}
            if counts:
                st.caption(f"Historical signals in window: {counts}")
            _render_backtest(res.get("backtest") or {}, res.get("recent_trades") or [])
