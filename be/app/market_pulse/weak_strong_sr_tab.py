"""
weak_strong_sr_tab.py
---------------------
Weak Strong S-R — institutional S/R strength screener with MTF confluence.
Groww · US · Crypto — VWAP · Volume · Supertrend · RSI.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
from app.market_pulse.ai_view import (
    STANDARD_REPORT_FORMAT,
    call_ai_report,
    render_ai_config,
    show_ai_view_block,
)
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import (
    summarize_error,
    summarize_weak_strong_sr,
)
from app.market_pulse.ta_screener_ui import (
    render_ta_screener_options,
    render_ta_screener_results,
)
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
    render_market_selectbox,
)
from app.market_pulse.ticker_utils import is_crypto_market, is_india_market, market_currency
from app.market_pulse.weak_strong_sr_engine import (
    aggregate_weak_strong_mtf,
    analyze_weak_strong_sr,
    fetch_wssr_data,
)

PREFIX = "wssr"
SECTION_ID = "weak_strong_sr"

WSSR_AI_SYSTEM = """You are an institutional-grade support/resistance strategist.

Framework:
- **Strong support** → BUY (institutional floor, high touch count)
- **Weak support** → SELL (breakdown / stop-run risk)
- **Weak resistance** → BUY (breakout through thin supply)
- **Strong resistance** → SELL (rejection at heavy supply)

Confirm with VWAP bias, volume ratio, Supertrend direction, and RSI.
**Consolidation at S/R:** coiling under resistance → bullish breakout base; above support → bearish breakdown flag.
**Supply/demand zones:** historical swing rejections (supply) and bounces (demand) refine entries.
Multi-timeframe alignment increases confidence.

Provide entry, SL%, TP%, confidence%, and hold duration. If TFs conflict → WAIT.
""" + STANDARD_REPORT_FORMAT


def _fmt(price: float | None, currency: str) -> str:
    if price is None:
        return "—"
    if currency == "$":
        return f"${price:,.4f}" if price < 1000 else f"${price:,.2f}"
    return f"{currency}{price:,.2f}"


def _build_ai_prompt(symbol: str, market: str, mtf: dict, legs: list[dict], currency: str) -> str:
    lines = [
        f"Symbol: {symbol} · Market: {market}",
        f"MTF verdict: {mtf.get('verdict')} · direction {mtf.get('direction')} · "
        f"alignment {mtf.get('mtf_alignment_pct')}% · confidence {mtf.get('confidence')}%",
    ]
    plan = mtf.get("trade_plan") or {}
    if plan:
        lines.append(
            f"Plan: {plan.get('direction')} SL -{plan.get('sl_pct')}% TP +{plan.get('tp_pct')}% "
            f"RR {plan.get('rr_ratio')} · hold {plan.get('hold_duration')}"
        )
    for leg in legs[:6]:
        ctx = leg.get("sr_context") or {}
        lines.append(
            f"  {leg.get('chart_tf')}: {leg.get('verdict')} conf {leg.get('confidence')}% "
            f"S/R bias {ctx.get('sr_bias')} · bull {leg.get('bull_score')} bear {leg.get('bear_score')}"
        )
        for sig in (leg.get("signals") or [])[:3]:
            lines.append(f"    - {sig}")
        cons = leg.get("consolidation") or {}
        sd = leg.get("supply_demand") or {}
        if cons.get("is_consolidating") or sd.get("active_zone") not in ("none", None, ""):
            lines.append(
                f"    Consolidation: {cons.get('bias', '—')} · "
                f"Supply/Demand: {sd.get('active_zone', '—')} ({sd.get('bias', '—')})"
            )
    return "\n".join(lines)


def _render_mtf_panel(mtf: dict) -> None:
    if not mtf or mtf.get("verdict") == "NO SETUP":
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("MTF Verdict", mtf.get("verdict", "—"))
    c2.metric("Alignment", f"{mtf.get('mtf_alignment_pct', 0):.0f}%")
    c3.metric("Confidence", f"{mtf.get('confidence', 0):.0f}%")
    c4.metric("Best TF", mtf.get("best_tf", "—"))
    plan = mtf.get("trade_plan")
    if plan:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Direction", plan.get("direction", "—"))
        p2.metric("SL %", f"-{plan.get('sl_pct', 0):.2f}%")
        p3.metric("TP %", f"+{plan.get('tp_pct', 0):.2f}%")
        p4.metric("R:R", plan.get("rr_ratio", "—"))


def _render_consolidation_supply_demand(
    consolidation: dict,
    supply_demand: dict,
    currency: str,
) -> None:
    st.markdown("#### Consolidation & supply/demand")
    st.caption(
        "Consolidation **under resistance → bullish** (breakout base). "
        "**Above support → bearish** (breakdown flag). "
        "Zones use historical swing rejections (supply) and bounces (demand)."
    )
    c1, c2 = st.columns(2)
    with c1:
        cons = consolidation or {}
        bias = cons.get("bias", "—")
        delta = f"{cons.get('range_pct', '—')}% range" if cons.get("range_pct") is not None else None
        st.metric(
            "Consolidation",
            "Yes" if cons.get("is_consolidating") else "No",
            delta=f"{bias} · near {cons.get('near_level', '—')}" if cons.get("is_consolidating") else delta,
        )
        label = (cons.get("label") or "—").replace("**", "")
        st.caption(label)
    with c2:
        sd = supply_demand or {}
        st.metric(
            "Active zone",
            sd.get("active_zone", "—").replace("_", " ").title(),
            delta=f"{sd.get('bias', '—')} bias",
        )
        st.caption((sd.get("label") or "—").replace("**", ""))

    rows: list[dict[str, str]] = []
    for z in (supply_demand or {}).get("demand_zones") or []:
        rows.append({
            "Zone": "Demand",
            "Range": f"{_fmt(z.get('bottom'), currency)} – {_fmt(z.get('top'), currency)}",
            "Strength": z.get("strength", "—"),
            "Touches": str(z.get("touches", 0)),
            "Dist from LTP": f"{z.get('dist_pct', 0):.2f}% below",
        })
    for z in (supply_demand or {}).get("supply_zones") or []:
        rows.append({
            "Zone": "Supply",
            "Range": f"{_fmt(z.get('bottom'), currency)} – {_fmt(z.get('top'), currency)}",
            "Strength": z.get("strength", "—"),
            "Touches": str(z.get("touches", 0)),
            "Dist from LTP": f"{z.get('dist_pct', 0):.2f}% above",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_leg_detail(symbol: str, tf: str, analysis: dict, currency: str) -> None:
    ctx = analysis.get("sr_context") or {}
    ind = analysis.get("indicators") or {}
    plan = analysis.get("trade_plan") or {}

    st.markdown(f"**{symbol} · {tf}** — {analysis.get('verdict')} ({analysis.get('confidence', 0):.0f}% conf)")
    st.caption(analysis.get("summary", ""))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("S/R Bias", ctx.get("sr_bias", "—"))
    m2.metric("RSI", ind.get("rsi", "—"))
    m3.metric("Vol ×", ind.get("vol_ratio", "—"))
    m4.metric("VWAP", _fmt(ind.get("vwap"), currency))
    m5.metric("ST", "Bull" if ind.get("supertrend_dir") == 1 else "Bear")

    sr_c1, sr_c2 = st.columns(2)
    with sr_c1:
        st.markdown("**Supports (weak → strong by touches)**")
        rows = []
        for s in (ctx.get("supports") or [])[:4]:
            cls = "strong" if int(s.get("touches", 0)) >= 3 else "weak"
            rows.append({
                "Level": s.get("price"),
                "Touches": s.get("touches"),
                "Class": cls,
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.caption("No supports below price.")
    with sr_c2:
        st.markdown("**Resistances**")
        rows = []
        for r in (ctx.get("resistances") or [])[:4]:
            cls = "strong" if int(r.get("touches", 0)) >= 3 else "weak"
            rows.append({
                "Level": r.get("price"),
                "Touches": r.get("touches"),
                "Class": cls,
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.caption("No resistances above price.")

    _render_consolidation_supply_demand(
        analysis.get("consolidation") or {},
        analysis.get("supply_demand") or {},
        currency,
    )

    if plan:
        st.info(
            f"**{plan.get('direction')}** · Entry {_fmt(plan.get('entry'), currency)} · "
            f"SL -{plan.get('sl_pct')}% · TP +{plan.get('tp_pct')}% · "
            f"hold {plan.get('hold_duration', '—')}"
        )

    with st.expander("Signal breakdown", expanded=False):
        for sig in analysis.get("signals") or []:
            st.markdown(f"- {sig}")


def render_weak_strong_sr_tab() -> None:
    """Weak Strong S-R screener — Groww, US, Crypto."""
    st.markdown("<h1>🧱 Weak Strong S-R</h1>", unsafe_allow_html=True)
    st.caption(
        "Institutional S/R framework: **strong support → buy**, **weak support → sell**, "
        "**weak resistance → buy**, **strong resistance → sell** — confirmed with "
        "**VWAP · volume · Supertrend · RSI · consolidation · supply/demand** across multiple timeframes."
    )

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets weak vs strong S/R with MTF alignment and trade plan.",
    )

    m1, m2 = st.columns(2)
    with m1:
        wssr_market = render_market_selectbox(f"{PREFIX}_market")
    with m2:
        wssr_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key=f"{PREFIX}_exchange")
            if is_india_market(wssr_market) else "NSE"
        )

    is_crypto = is_crypto_market(wssr_market)
    currency = market_currency(wssr_market)

    st.markdown("### 📊 Tickers")
    if is_crypto:
        wssr_tickers = render_coindcx_ticker_selection(PREFIX)
    else:
        wssr_tickers = render_equity_index_ticker_selection(wssr_market, PREFIX)

    st.markdown("### ⏱️ Timeframes")
    from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

    tfc1, tfc2, tfc3 = st.columns(3)
    with tfc1:
        wssr_tfs = render_ta_multiselect_timeframes(
            PREFIX,
            ["5m", "15m", "30m", "1h", "4h", "1d"],
            legacy_default=["15m", "1h", "1d"],
            label="Timeframes",
        )
    with tfc2:
        wssr_candles = st.slider("Candle history", 80, 650, 280, 20, key=f"{PREFIX}_candles")
    with tfc3:
        wssr_sr_win = st.slider("S/R swing window", 3, 12, 5, key=f"{PREFIX}_sr_win")

    with st.expander("⚙️ Confluence parameters", expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            wssr_st_p = st.slider("Supertrend period", 7, 21, 10, key=f"{PREFIX}_st_p")
            wssr_st_m = st.slider("Supertrend mult", 1.5, 5.0, 3.0, 0.5, key=f"{PREFIX}_st_m")
        with p2:
            wssr_atr_p = st.slider("ATR period", 7, 21, 14, key=f"{PREFIX}_atr_p")
            wssr_vol_p = st.slider("Volume MA", 10, 50, 20, key=f"{PREFIX}_vol_p")
        with p3:
            wssr_rsi_p = st.slider("RSI period", 7, 21, 14, key=f"{PREFIX}_rsi_p")

    total = len(wssr_tickers) * len(wssr_tfs)
    wssr_actionable = render_ta_screener_options(PREFIX)
    st.caption(f"🧮 **{total}** ticker × timeframe combinations")

    run_btn = st.button(
        "🔎 SCAN WEAK STRONG S-R",
        type="primary",
        width="stretch",
        key=f"{PREFIX}_run",
    )

    if run_btn:
        if not wssr_tickers or not wssr_tfs:
            st.error("Select at least one ticker and timeframe.")
            return

        groww_token = get_active_groww_token()
        results: dict[str, dict] = {}
        bar = st.progress(0, text="Scanning weak/strong S/R…")
        i = 0
        for tick in wssr_tickers:
            legs: list[dict] = []
            for tf in wssr_tfs:
                i += 1
                bar.progress(i / total, text=f"{tick} · {tf}")
                try:
                    df = fetch_wssr_data(
                        tick, tf, wssr_market, groww_token, wssr_exchange, wssr_candles,
                    )
                    if df.empty or len(df) < 45:
                        results[f"{tick}|{tf}"] = {
                            "error": f"Insufficient data ({len(df)} bars).",
                            "symbol": tick,
                            "timeframe": tf,
                        }
                        continue
                    analysis = analyze_weak_strong_sr(
                        df,
                        chart_tf=tf,
                        sr_window=wssr_sr_win,
                        st_period=wssr_st_p,
                        st_mult=wssr_st_m,
                        atr_period=wssr_atr_p,
                        vol_period=wssr_vol_p,
                        rsi_period=wssr_rsi_p,
                        is_crypto=is_crypto,
                    )
                    analysis["symbol"] = tick
                    results[f"{tick}|{tf}"] = {"analysis": analysis, "symbol": tick, "timeframe": tf}
                    legs.append(analysis)
                except Exception as exc:
                    results[f"{tick}|{tf}"] = {
                        "error": str(exc)[:120],
                        "symbol": tick,
                        "timeframe": tf,
                    }

            if legs:
                mtf = aggregate_weak_strong_mtf(legs, wssr_tfs)
                results[f"{tick}|__mtf__"] = {
                    "symbol": tick,
                    "timeframe": "MTF",
                    "mtf": mtf,
                    "legs": legs,
                }

        st.session_state[f"{PREFIX}_results"] = results
        st.session_state[f"{PREFIX}_results_market"] = wssr_market
        st.session_state[f"{PREFIX}_results_exchange"] = wssr_exchange
        st.session_state[f"{PREFIX}_results_is_crypto"] = is_crypto
        st.session_state[f"{PREFIX}_last_scan"] = time.strftime("%H:%M:%S")

    results: dict[str, Any] = st.session_state.get(f"{PREFIX}_results", {})
    if not results:
        st.info("Select market, tickers, and timeframes, then click **SCAN WEAK STRONG S-R**.")
        return

    currency = market_currency(st.session_state.get(f"{PREFIX}_results_market", wssr_market))
    tickers_seen = sorted({v.get("symbol") for v in results.values() if v.get("symbol")})

    digest = []
    for tick in tickers_seen:
        mtf_row = results.get(f"{tick}|__mtf__")
        if mtf_row and mtf_row.get("mtf"):
            digest.append(summarize_weak_strong_sr(mtf_row["mtf"], tick, timeframe="MTF"))
        for key, data in results.items():
            if data.get("symbol") != tick or data.get("timeframe") == "MTF":
                continue
            if "error" in data:
                digest.append(
                    summarize_error(tick, data.get("timeframe", ""), data["error"], tab="Weak Strong S-R")
                )
            elif data.get("analysis"):
                digest.append(
                    summarize_weak_strong_sr(data["analysis"], tick, timeframe=data.get("timeframe", ""))
                )

    if wssr_actionable:
        digest = [
            d for d in digest
            if d.get("verdict") in ("BUY", "STRONG BUY", "SELL", "WATCHLIST", "TOP PICK")
            or d.get("signal_type") in ("trade", "watch")
        ]

    render_ta_screener_results(
        digest,
        title="🧭 Weak Strong S-R Recommendations",
        strategy_label="S/R setup",
        actionable_only=wssr_actionable,
    )

    st.markdown("---")
    st.markdown("### 📋 Per-ticker MTF detail")
    for tick in tickers_seen:
        mtf_row = results.get(f"{tick}|__mtf__")
        if not mtf_row:
            continue
        mtf = mtf_row.get("mtf") or {}
        legs = mtf_row.get("legs") or []
        with st.expander(f"**{tick}** — MTF {mtf.get('verdict', '—')} · {mtf.get('confidence', 0):.0f}%", expanded=False):
            _render_mtf_panel(mtf)
            if api_key and st.button(f"✨ AI View — {tick} MTF", key=f"{PREFIX}_ai_{tick}"):
                prompt = _build_ai_prompt(
                    tick,
                    st.session_state.get(f"{PREFIX}_results_market", ""),
                    mtf,
                    legs,
                    currency,
                )
                raw = call_ai_report(
                    WSSR_AI_SYSTEM,
                    prompt,
                    provider,
                    model,
                    api_key,
                    user_intro="Weak Strong S/R MTF review:",
                )
                show_ai_view_block(raw)
            for leg in legs:
                _render_leg_detail(tick, leg.get("chart_tf", ""), leg, currency)

    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai

    snapshot_section_for_ask_ai(SECTION_ID)
