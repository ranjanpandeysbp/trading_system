"""
accurate_strategy_tab.py
------------------------
Market Pulse — Zireman-style Accurate Strategy (OB + FVG + S/R confluence).
"""

from __future__ import annotations

import pandas as pd
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.news_scanner import _render_news_scanner_styles
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import MARKET_OPTIONS, is_crypto_market, market_currency
from app.market_pulse.zireman_confluence_engine import (
    run_strategy,
    serialize_result,
    signal_to_dict,
    zone_to_dict,
)

_PREFIX = "accurate_strat"
_PAYLOAD_KEY = "accurate_strategy_payload"

STRATEGY_EXPLANATION = """
### Zireman-style Confluence Strategy

A Python re-implementation of the **concepts** behind three TradingView indicators:

1. **Ranked Order Block Zones** — last opposite candle before an impulsive displacement (ATR + volume + EMA trend scored)
2. **Ranked FVG Imbalance Zones** — classic 3-candle fair value gaps with buy/sell pressure %
3. **Ranked Support & Resistance Zones** — clustered swing pivots scored by touches + recency

These are combined into a **confluence-scoring signal engine** with a simple bar-by-bar backtester.

> **Disclaimer:** Independent interpretation for backtesting and education.  
> Does **not** reproduce Zireman's proprietary Pine Script.  
> **NOT FINANCIAL ADVICE.**

---

#### How signals are generated

| Step | Logic |
|------|--------|
| 1 | Detect top-ranked **Order Blocks** and **FVG** zones |
| 2 | Detect overlapping **S/R** zones in the same direction |
| 3 | When price **first** trades into an OB/FVG, check S/R overlap |
| 4 | Combined score ≥ min confluence → **LONG** or **SHORT** |
| 5 | Stop beyond zone edge · target = **R:R** × risk |

Each primary zone triggers **at most one** trade (zone is marked mitigated after first touch).

---

#### Scoring ingredients

- **Order blocks:** displacement in ATR units, volume expansion vs rolling average, EMA(50) alignment
- **FVG:** gap size vs ATR, directional volume pressure across the 3-candle pattern
- **S/R:** pivot touch count, recency weight, buy/sell volume at touches

---

#### Backtest (on loaded history)

One position at a time — exit on stop or target hit on subsequent bars.  
Use as a **sanity check** on the loaded window; forward live trading requires your own risk rules.
"""


def _render_strategy_explanation() -> None:
    with st.expander("📖 Strategy explanation — Zireman-style Confluence", expanded=False):
        st.markdown(STRATEGY_EXPLANATION)


def _zone_table(zones: list, title: str) -> None:
    st.markdown(f"##### {title}")
    if not zones:
        st.caption("No zones detected on this window.")
        return
    rows = []
    for z in zones:
        d = zone_to_dict(z) if hasattr(z, "kind") else z
        rows.append({
            "Type": d.get("kind", "—"),
            "Dir": d.get("direction", "—"),
            "Top": d.get("top"),
            "Bottom": d.get("bottom"),
            "Score": d.get("score"),
            "Pressure %": d.get("pressure_pct") if d.get("pressure_pct") is not None else "—",
            "Detail": (d.get("label") or "")[:72],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_latest_setup(latest: dict | None, *, currency: str) -> None:
    st.markdown("##### 🎯 Latest confluence setup")
    if not latest:
        st.info("No confluence signal in the last few bars — wait for price to retest a ranked OB/FVG with S/R overlap.")
        return
    side = latest.get("side", "—")
    badge = "🟢 LONG" if side == "LONG" else "🔴 SHORT" if side == "SHORT" else side
    st.success(
        f"**{badge}** · confluence **{latest.get('confluence_score')}%** · "
        f"SL **-{latest.get('sl_pct')}%** · TP **+{latest.get('tp_pct')}%**"
        + (f" · R:R **{latest.get('rr_ratio')}**" if latest.get("rr_ratio") else "")
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Entry", latest.get("entry_fmt", latest.get("entry")))
    with c2:
        st.metric("Stop", latest.get("stop_fmt", latest.get("stop")))
    with c3:
        st.metric("Target", latest.get("target_fmt", latest.get("target")))
    for r in latest.get("reasons") or []:
        st.markdown(f"- {r}")


def _render_backtest_summary(summary: dict, trades_df: pd.DataFrame) -> None:
    st.markdown("##### 📊 Backtest on loaded window")
    if not summary:
        st.caption("No completed trades in this historical window (raise/lower min confluence or load more bars).")
        return
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Trades", summary.get("total_trades", 0))
    with c2:
        st.metric("Win rate", f"{summary.get('win_rate_pct', 0)}%")
    with c3:
        st.metric("Total PnL (pts)", summary.get("total_pnl", 0))
    with c4:
        st.metric("Avg PnL / trade", summary.get("avg_pnl_per_trade", 0))
    if trades_df is not None and not trades_df.empty:
        show = trades_df.tail(12).copy()
        show["entry"] = show["entry"].map(lambda x: f"{x:.4g}")
        show["exit"] = show["exit"].map(lambda x: f"{x:.4g}")
        show["pnl"] = show["pnl"].map(lambda x: f"{x:.4g}")
        st.dataframe(show, hide_index=True, width="stretch")


def _run_scan(
    ticker: str,
    market: str,
    timeframe: str,
    *,
    min_confluence: float,
    rr_target: float,
    bar_limit: int,
) -> dict | None:
    groww = get_active_groww_token() if "Groww" in market else ""
    exchange = "NSE"
    df = fetch_data_for_gap_scan(
        ticker, timeframe, market, groww, exchange, limit=bar_limit,
    )
    if df is None or df.empty or len(df) < 80:
        return None
    df.columns = [str(c).lower() for c in df.columns]
    result = run_strategy(df, min_confluence=min_confluence, rr_target=rr_target)
    currency = market_currency(market)
    payload = {
        "ticker": ticker,
        "market": market,
        "timeframe": timeframe,
        "min_confluence": min_confluence,
        "rr_target": rr_target,
        "currency": currency,
        **serialize_result(result, currency=currency),
    }
    if result.get("latest_signal"):
        payload["latest_signal"] = signal_to_dict(result["latest_signal"], currency=currency)
    payload["raw_summary"] = result.get("summary") or {}
    return payload


def render_accurate_strategy_tab(get_logged_in_mobile=None) -> None:
    """Market Pulse — OB + FVG + S/R confluence (Accurate Strategy)."""
    _render_news_scanner_styles()
    _render_strategy_explanation()

    st.caption(
        "**Accurate Strategy** ranks Order Blocks, Fair Value Gaps, and S/R zones, "
        "then fires trades only when same-direction zones **overlap** above the confluence threshold."
    )

    market = st.selectbox("Market", MARKET_OPTIONS, key=f"{_PREFIX}_market")
    is_crypto = is_crypto_market(market)

    if is_crypto:
        tickers = render_coindcx_ticker_selection(f"{_PREFIX}_crypto")
    else:
        tickers = render_equity_index_ticker_selection(
            market,
            f"{_PREFIX}_eq",
            default_count=1,
        )

    timeframe = st.selectbox(
        "Chart timeframe",
        ["15m", "1h", "4h", "1d"],
        index=1,
        key=f"{_PREFIX}_tf",
    )
    bar_limits = {"15m": 400, "1h": 350, "4h": 280, "1d": 220}
    bar_limit = bar_limits.get(timeframe, 300)

    with st.expander("⚙️ Engine parameters", expanded=False):
        min_confluence = st.slider(
            "Min confluence score",
            40.0, 85.0, 60.0, 1.0,
            key=f"{_PREFIX}_min_conf",
            help="OB/FVG score + 40% of overlapping S/R score must clear this.",
        )
        rr_target = st.slider(
            "Reward : risk target",
            1.0, 4.0, 2.0, 0.25,
            key=f"{_PREFIX}_rr",
        )

    run = st.button("▶ Run Accurate Strategy scan", type="primary", key=f"{_PREFIX}_run", use_container_width=True)

    if run:
        if not tickers:
            st.warning("Select at least one ticker.")
        else:
            prog = st.progress(0, text="Scanning confluence zones…")
            results = []
            for i, ticker in enumerate(tickers):
                prog.progress((i + 0.2) / len(tickers), text=f"Analyzing {ticker}…")
                try:
                    payload = _run_scan(
                        ticker, market, timeframe,
                        min_confluence=min_confluence,
                        rr_target=rr_target,
                        bar_limit=bar_limit,
                    )
                    if payload:
                        results.append(payload)
                except Exception as exc:
                    results.append({
                        "ticker": ticker,
                        "market": market,
                        "error": str(exc)[:200],
                    })
                prog.progress((i + 1) / len(tickers), text=f"Done {ticker}")
            prog.empty()
            st.session_state[_PAYLOAD_KEY] = {
                "market": market,
                "timeframe": timeframe,
                "results": results,
            }

    payload = st.session_state.get(_PAYLOAD_KEY)
    if not payload:
        return

    st.markdown("---")
    st.markdown(f"##### Results · `{payload.get('timeframe')}` · {payload.get('market')}")

    for i, res in enumerate(payload.get("results") or []):
        ticker = res.get("ticker", "?")
        currency = res.get("currency") or market_currency(res.get("market", ""))
        if res.get("error"):
            st.error(f"**{ticker}** — {res['error']}")
            continue

        price = res.get("price")
        headline = f"**{ticker}**"
        if price is not None:
            headline += f" · {currency}{price:,.4g}"
        headline += f" · {res.get('signal_count', 0)} signals · {res.get('bars', 0)} bars"

        with st.expander(headline, expanded=(i == 0)):
            _render_latest_setup(res.get("latest_signal"), currency=currency)

            c1, c2 = st.columns(2)
            with c1:
                _zone_table(res.get("order_blocks") or [], "🧱 Ranked Order Blocks")
            with c2:
                _zone_table(res.get("fvgs") or [], "📐 Ranked FVG Imbalances")
            _zone_table(res.get("sr_zones") or [], "🎯 Ranked S/R Zones")

            trades = res.get("recent_trades") or []
            trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
            _render_backtest_summary(res.get("summary") or res.get("raw_summary") or {}, trades_df)
