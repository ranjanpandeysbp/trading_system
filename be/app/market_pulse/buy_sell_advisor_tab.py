"""
buy_sell_advisor_tab.py
-----------------------
Command Center — Buy or Sell advisor (Crypto · India · US · Commodity).
"""

from __future__ import annotations

import pandas as pd
from app.market_pulse.ai_view import render_ai_config, render_mtf_ai_view_report, mtf_ticker_button
from app.market_pulse.buy_sell_advisor_engine import (
    ALL_DURATIONS,
    ASSET_CLASS_CONFIG,
    BUY_SELL_AI_SYSTEM,
    build_buy_sell_ai_prompt,
    resolve_tickers,
    run_buy_sell_advisor,
    ticker_suggestions,
)
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.news_scanner import _render_news_scanner_styles
from app.market_pulse.run_summary import render_run_summary
from app.market_pulse.ticker_utils import market_currency

_PREFIX = "bsa"
_PAYLOAD_KEY = "buy_sell_advisor_payload"


def _dir_badge(take: bool, direction: str) -> str:
    if not take:
        return "⚪ NO TRADE"
    if direction == "LONG":
        return "🟢 TAKE LONG"
    if direction == "SHORT":
        return "🔴 TAKE SHORT"
    return "⚪ WAIT"


def _render_ticker_picker(asset_class: str, prefix: str) -> list[str]:
    cfg = ASSET_CLASS_CONFIG[asset_class]
    st.markdown("**Tickers** — type to filter, then select one or more")
    query = st.text_input(
        "🔍 Type symbol / name",
        placeholder="e.g. BTC, RELIANCE, AAPL, CL=F, Gold…",
        key=f"{prefix}_ticker_q",
    )
    pool = ticker_suggestions(asset_class, query)
    if not pool:
        pool = list(cfg["default_tickers"])

    default_sel = [t for t in cfg["default_tickers"] if t in pool][:3]
    selected = st.multiselect(
        "Select / unselect tickers",
        pool,
        default=default_sel or pool[: min(3, len(pool))],
        key=f"{prefix}_ticker_sel",
        help="Resolved automatically for CoinDCX API, NSE, US Yahoo, or commodity futures.",
    )
    if selected:
        resolved = resolve_tickers(asset_class, selected)
        st.caption(f"Resolved: **{', '.join(resolved)}**")
        return resolved
    return []


def _render_duration_picker(asset_class: str, prefix: str) -> list[str]:
    cfg = ASSET_CLASS_CONFIG[asset_class]
    return st.multiselect(
        "⏱️ Durations (one or more)",
        ALL_DURATIONS,
        default=list(cfg["default_durations"]),
        key=f"{prefix}_durations",
        help="Multi-timeframe confluence — intraday through weekly.",
    )


def _render_results(payload: dict, *, provider: str, model: str, api_key: str) -> None:
    recs = payload.get("recommendations") or []
    if not recs:
        st.warning("No analysis results.")
        return

    currency = market_currency(payload.get("market", ""))

    summary_rows = []
    for r in recs:
        summary_rows.append({
            "Ticker": r["ticker"],
            "Take trade?": "✅ YES" if r["take_trade"] else "❌ NO",
            "Signal": _dir_badge(r["take_trade"], r["direction"]),
            "Verdict": r["verdict"],
            "Score": f"{r['score']}/10",
            "Confidence": f"{r['confidence_pct']:.0f}%",
            "SL %": f"-{r['sl_pct']:.2f}%",
            "TP %": f"+{r['tp_pct']:.2f}%",
            "Engines": r["engine_count"],
        })
    st.markdown("##### 📊 Trade decision summary")
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")

    for i, rec in enumerate(recs):
        badge = _dir_badge(rec["take_trade"], rec["direction"])
        with st.expander(f"**{rec['ticker']}** — {badge} · conf {rec['confidence_pct']:.0f}%", expanded=(i == 0)):
            if rec["take_trade"]:
                st.success(
                    f"**{rec['direction']}** · SL **-{rec['sl_pct']:.2f}%** · "
                    f"TP **+{rec['tp_pct']:.2f}%** · Confidence **{rec['confidence_pct']:.0f}%**"
                )
            else:
                st.info("**No trade** — insufficient multi-engine confluence. Wait for alignment.")

            if rec.get("summary"):
                st.markdown(rec["summary"])
            if rec.get("reasons"):
                st.markdown("**Engine confluence**")
                for line in rec["reasons"]:
                    st.markdown(f"- {line}")

            plan = rec.get("trade_plan") or {}
            if plan and rec["take_trade"]:
                render_run_summary({
                    "ticker": rec["ticker"],
                    "timeframe": rec.get("timeframe", ""),
                    "tab": "Buy / Sell Advisor",
                    "score": rec["score"],
                    "verdict": rec["verdict"],
                    "action": rec.get("action", ""),
                    "summary": rec.get("summary", ""),
                    "reasons": rec.get("reasons", []),
                    "trade_plan": plan,
                    "signal_type": "trade" if rec["take_trade"] else "no_trade",
                })

            if api_key:
                mtf_ticker_button("bsa", rec["ticker"], button_in_column=False)
                render_mtf_ai_view_report(
                    "bsa",
                    rec["ticker"],
                    lambda t=rec["ticker"], p=payload, c=currency: build_buy_sell_ai_prompt(p, t, c),
                    BUY_SELL_AI_SYSTEM,
                    provider,
                    model,
                    api_key,
                    rec["engine_count"],
                    inline_ai_picker=False,
                )
            else:
                st.caption("Set `GEMINI_API_KEY` or `GROQ_API_KEY` in `.env` for AI View synthesis.")


def _render_asset_panel(asset_class: str, prefix: str, get_mobile) -> None:
    cfg = ASSET_CLASS_CONFIG[asset_class]
    st.caption(
        f"**{cfg['label']}** · TA profile: *{cfg['scenario']}* — "
        "Price Action · S/R · Confluence · MTF · Fakeout · Pump/Dump · Session Bias · more."
    )

    if asset_class == "india":
        st.caption("Optional: set Groww token in sidebar for live NSE quotes.")

    c1, c2 = st.columns([2, 1])
    with c1:
        tickers = _render_ticker_picker(asset_class, prefix)
    with c2:
        durations = _render_duration_picker(asset_class, prefix)

    analyze = st.button(
        f"🔍 Analyse & suggest Buy / Sell",
        key=f"{prefix}_run",
        type="primary",
        use_container_width=True,
    )

    payload = st.session_state.get(_PAYLOAD_KEY, {}).get(asset_class)

    if analyze:
        if not tickers:
            st.warning("Select at least one ticker.")
        elif not durations:
            st.warning("Select at least one duration.")
        else:
            groww = get_active_groww_token()
            mobile = get_mobile() if callable(get_mobile) else ""
            prog = st.progress(0, text="Starting analysis…")
            try:
                result = run_buy_sell_advisor(
                    asset_class,
                    tickers,
                    durations,
                    groww_token=groww,
                    mobile=mobile,
                    progress_callback=lambda p, t: prog.progress(min(p, 1.0), text=t[:80]),
                )
            finally:
                prog.empty()
            if result:
                if _PAYLOAD_KEY not in st.session_state:
                    st.session_state[_PAYLOAD_KEY] = {}
                st.session_state[_PAYLOAD_KEY][asset_class] = result
                payload = result
            else:
                st.error("Analysis failed — check tickers and network.")

    if not payload:
        st.info("Pick tickers & durations, then click **Analyse & suggest Buy / Sell**.")
        return

    provider, model, api_key = render_ai_config(
        prefix,
        caption="AI View synthesizes all engines into one institutional-grade trade plan.",
    )
    _render_results(payload, provider=provider, model=model, api_key=api_key)


def render_buy_sell_advisor_tab(get_logged_in_mobile=None) -> None:
    """Command Center — multi-asset Buy or Sell advisor."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">⚖️ Buy or Sell — Multi-Asset Trade Advisor</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Institutional-style stack: **SMC · price action · MTF confluence · fakeout · pump/dump · "
        "session bias · weak/strong S/R** — per asset class. Outputs **TAKE TRADE** or **NO TRADE** "
        "with **confidence %**, **SL %**, **TP %**, plus **AI View**."
    )

    tab_crypto, tab_india, tab_us, tab_cmdty = st.tabs([
        "₿ Crypto",
        "🇮🇳 Indian stocks",
        "🇺🇸 US stocks",
        "🛢️ Commodity",
    ])

    with tab_crypto:
        _render_asset_panel("crypto", f"{_PREFIX}_crypto", get_logged_in_mobile)
    with tab_india:
        _render_asset_panel("india", f"{_PREFIX}_india", get_logged_in_mobile)
    with tab_us:
        _render_asset_panel("us", f"{_PREFIX}_us", get_logged_in_mobile)
    with tab_cmdty:
        _render_asset_panel("commodity", f"{_PREFIX}_cmdty", get_logged_in_mobile)

    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai

    snapshot_section_for_ask_ai("buy_sell_advisor")
