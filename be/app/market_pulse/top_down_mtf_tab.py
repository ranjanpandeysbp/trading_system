"""
top_down_mtf_tab.py
-------------------
Top-Down Multi-Timeframe SMC scanner — Groww & CoinDCX.
3-step HTF → MTF → LTF execution with approaching-trade alerts.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import pandas as pd
from app.market_pulse.ai_view import (
    STANDARD_REPORT_FORMAT,
    render_ai_config,
    show_ai_view_block,
)
from app.market_pulse.top_down_mtf_engine import (
    TF_ORDER,
    analyze_top_down,
)
from app.market_pulse.mtf_scanner_engine import TIMEFRAMES
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import (
    render_run_digest,
    render_run_summary,
    summarize_error,
    summarize_top_down_mtf,
)
from app.market_pulse.ta_screener_ui import render_ta_screener_options
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

REF_VIDEO_URL = "https://www.youtube.com/watch?v=5ameUmO4tuc"
PREFIX = "tdmtf"
SECTION_ID = "top_down_mtf"

DEFAULT_HTF = "15m"
DEFAULT_MTF = "5m"
DEFAULT_LTF = "1m"
ALL_TFS = [tf for tf in TF_ORDER if tf in TIMEFRAMES]

PHASE_ICONS = {
    "ENTRY_READY": "🟢",
    "APPROACHING_LTF": "🟡",
    "MTF_SETUP": "🔶",
    "HTF_BIAS": "🔵",
    "NEUTRAL": "⚪",
    "NO_DATA": "⏳",
}

TDMTF_AI_SYSTEM = """You are an expert Smart Money Concepts (SMC) top-down multi-timeframe trader.

The scanner runs a strict 3-step process:
1. **HTF** — swing structure (HH/HL or LH/LL), key levels (PDH/PDL, day high/low, round numbers), directional bias
2. **MTF** — Change of Character (CHoCH) plus Fair Value Gap (FVG) or Order Block (OB) zone
3. **LTF** — price retest into the zone with Marubozu, Hammer/Pin, or Mini CHoCH trigger

Phases:
- **ENTRY_READY** — all three steps confirmed; trade plan with SL/TP is active
- **APPROACHING_LTF** — MTF setup exists; price near/in zone but trigger pending
- **MTF_SETUP** — CHoCH + zone found; waiting for LTF retest
- **HTF_BIAS** — directional bias only; no MTF setup yet

Common mistakes to flag:
1. LTF entry opposing HTF bias
2. Skipping MTF (CHoCH + FVG/OB) and entering on LTF alone
3. HTF resistance/support blocking the path to target

Give concrete entry, SL, TP, hold time, green signs, and red flags from the supplied data.
""" + STANDARD_REPORT_FORMAT


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _fmt_pct(val: float | None, *, sign: str = "+") -> str:
    if val is None:
        return "—"
    if sign == "-":
        return f"-{val:.2f}%"
    return f"+{val:.2f}%"


def build_tdmtf_ai_prompt(symbol: str, market: str, analysis: dict, currency: str) -> str:
    s1 = analysis.get("step1") or {}
    s2 = analysis.get("step2") or {}
    s3 = analysis.get("step3") or {}
    plan = analysis.get("trade_plan") or {}
    lines = [
        "=== TOP-DOWN MTF SMC SCANNER ===",
        f"Symbol: {symbol}",
        f"Market: {market}",
        f"Phase: {analysis.get('phase', 'N/A')} — {analysis.get('primary_label', '')}",
        f"Confidence: {analysis.get('confidence', 0):.0f}%",
        f"HTF: {analysis.get('htf_label', '—')} · MTF: {analysis.get('mtf_label', '—')} · LTF: {analysis.get('ltf_label', '—')}",
        f"Price: {currency}{analysis.get('price', 0):,.4f} · LTF: {currency}{analysis.get('ltf_price', 0):,.4f}",
        "",
        "=== STEP 1 — HTF BIAS ===",
        f"Trend: {s1.get('trend', '—')} · Bias: {s1.get('bias', '—')}",
        "Key levels:",
    ]
    for kl in s1.get("key_levels") or []:
        lines.append(f"  - {kl.get('label')}: {currency}{kl.get('price', 0):,.4f}")

    lines.extend([
        "",
        "=== STEP 2 — MTF SETUP ===",
        f"CHoCH: {s2.get('choch', False)}",
        f"FVG: {s2.get('fvg')}",
        f"Order Block: {s2.get('order_block')}",
        f"Active zone: {s2.get('zone')}",
        f"Distance to zone: {s2.get('zone_distance_pct', '—')}%",
        "",
        "=== STEP 3 — LTF ENTRY ===",
        f"In zone: {s3.get('in_zone', False)}",
        f"Trigger: {s3.get('trigger', 'None')}",
    ])

    if plan:
        lines.extend([
            "",
            "=== TRADE PLAN ===",
            f"Direction: {plan.get('direction', '—')}",
            f"Entry: {currency}{plan.get('entry', 0):,.4f}",
            f"Stop Loss: {currency}{plan.get('stop_loss', 0):,.4f} ({_fmt_pct(plan.get('sl_pct'), sign='-')})",
            f"Take Profit: {currency}{plan.get('take_profit', 0):,.4f} ({_fmt_pct(plan.get('tp_pct'))})",
            f"R:R: 1:{plan.get('rr_ratio', 0):.1f}",
            f"Hold: {plan.get('hold_duration', '—')}",
            f"Projected: {plan.get('projected', False)}",
        ])
    return "\n".join(lines)


def _render_setup_alerts(results: dict) -> None:
    ready, approaching, mtf = [], [], []
    for tick, d in results.items():
        if d.get("error"):
            continue
        phase = d.get("phase", "")
        plan = d.get("trade_plan") or {}
        if phase == "ENTRY_READY":
            ready.append((tick, d, plan))
        elif phase == "APPROACHING_LTF":
            approaching.append((tick, d, plan))
        elif phase == "MTF_SETUP":
            mtf.append((tick, d, plan))

    if ready:
        st.success(
            f"**{len(ready)} ENTRY READY:** "
            + ", ".join(
                f"**{t}** {p.get('direction', '—')} conf {d.get('confidence', 0):.0f}% "
                f"SL -{p.get('sl_pct', 0):.2f}% TP +{p.get('tp_pct', 0):.2f}%"
                for t, d, p in ready[:8]
            )
        )
    if approaching:
        st.warning(
            f"**{len(approaching)} APPROACHING LTF:** "
            + ", ".join(
                f"**{t}** {d.get('primary_label', '')[:40]}"
                for t, d, _ in approaching[:8]
            )
        )
    if mtf:
        st.info(
            f"**{len(mtf)} MTF SETUP(S):** "
            + ", ".join(f"**{t}**" for t, _, _ in mtf[:8])
        )


def _render_screener_grid(results: dict, is_crypto: bool) -> None:
    rows = []
    for tick, d in results.items():
        if d.get("error"):
            rows.append({
                "Ticker": tick,
                "Phase": "ERROR",
                "Bias": "—",
                "Conf.": "—",
                "Trigger": "—",
                "SL %": "—",
                "TP %": "—",
                "Hold": "—",
                "_priority": -1,
            })
            continue
        plan = d.get("trade_plan") or {}
        s1 = d.get("step1") or {}
        s3 = d.get("step3") or {}
        rows.append({
            "Ticker": tick,
            "Phase": d.get("phase", "—"),
            "Bias": s1.get("bias", "—"),
            "Conf.": f"{d.get('confidence', 0):.0f}%",
            "Trigger": s3.get("trigger", "—"),
            "SL %": _fmt_pct(plan.get("sl_pct"), sign="-") if plan.get("sl_pct") is not None else "—",
            "TP %": _fmt_pct(plan.get("tp_pct")) if plan.get("tp_pct") is not None else "—",
            "Hold": plan.get("hold_duration", "—"),
            "_priority": d.get("priority", 0),
        })

    if not rows:
        return
    st.markdown("#### 📋 Screener Grid")
    df = pd.DataFrame(rows).sort_values("_priority", ascending=False)
    st.dataframe(df.drop(columns=["_priority"]), width='stretch', hide_index=True)


def _render_step_cards(analysis: dict, currency: str) -> None:
    s1 = analysis.get("step1") or {}
    s2 = analysis.get("step2") or {}
    s3 = analysis.get("step3") or {}
    c1, c2, c3 = st.columns(3)

    with c1:
        with st.container(border=True):
            st.markdown(f"**Step 1 — HTF** ({analysis.get('htf_label', '—')})")
            st.caption(f"Trend: **{s1.get('trend', '—')}** · Bias: **{s1.get('bias', '—')}**")
            levels = s1.get("key_levels") or []
            if levels:
                st.caption(
                    " · ".join(f"{kl['label']} {currency}{kl['price']:,.2f}" for kl in levels[:5])
                )

    with c2:
        with st.container(border=True):
            st.markdown(f"**Step 2 — MTF** ({analysis.get('mtf_label', '—')})")
            st.caption(f"CHoCH: **{'✅' if s2.get('choch') else '❌'}**")
            zone = s2.get("zone")
            if zone:
                st.caption(
                    f"{zone.get('type')} zone {currency}{zone.get('low', 0):,.2f} – "
                    f"{currency}{zone.get('high', 0):,.2f} · "
                    f"dist {s2.get('zone_distance_pct', 0):.2f}%"
                )
            else:
                st.caption("No FVG/OB zone detected")

    with c3:
        with st.container(border=True):
            st.markdown(f"**Step 3 — LTF** ({analysis.get('ltf_label', '—')})")
            st.caption(
                f"In zone: **{'✅' if s3.get('in_zone') else '❌'}** · "
                f"Trigger: **{s3.get('trigger', 'None')}**"
            )


def _render_trade_plan(analysis: dict, currency: str) -> None:
    plan = analysis.get("trade_plan")
    if not plan:
        return
    phase = analysis.get("phase", "")
    icon = PHASE_ICONS.get(phase, "•")
    projected = plan.get("projected", False)
    st.markdown(f"#### {icon} Trade Plan{' (projected)' if projected else ''}")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Direction", plan.get("direction", "—"))
    c2.metric("Confidence", f"{analysis.get('confidence', 0):.0f}%")
    c3.metric("SL", _fmt_pct(plan.get("sl_pct"), sign="-"))
    c4.metric("TP", _fmt_pct(plan.get("tp_pct")))
    c5.metric("R:R", f"1:{plan.get('rr_ratio', 0):.1f}")
    c6.metric("Hold", plan.get("hold_duration", "—"))
    st.caption(
        f"Entry {currency}{plan.get('entry', 0):,.4f} · "
        f"SL {currency}{plan.get('stop_loss', 0):,.4f} · "
        f"TP {currency}{plan.get('take_profit', 0):,.4f} · "
        f"Trigger: {plan.get('trigger', '—')}"
    )


def _render_result_block(
    ticker: str,
    data: dict,
    is_crypto: bool,
    market: str,
    provider: str,
    model: str,
    api_key: str,
) -> None:
    currency = "₹" if not is_crypto else "$"

    if data.get("error"):
        st.error(data["error"])
        return

    phase = data.get("phase", "NEUTRAL")
    icon = PHASE_ICONS.get(phase, "📊")
    st.markdown(f"### {icon} {data.get('primary_label', phase)}")
    st.caption(
        f"HTF **{data.get('htf_label', '—')}** → MTF **{data.get('mtf_label', '—')}** → "
        f"LTF **{data.get('ltf_label', '—')}** · Confidence **{data.get('confidence', 0):.0f}%**"
    )

    _render_step_cards(data, currency)
    _render_trade_plan(data, currency)

    summary = summarize_top_down_mtf(data, ticker)
    render_run_summary(summary)

    show_ai_view_block(
        session_prefix=PREFIX,
        result_key=f"{ticker}_{data.get('htf_tf', '')}_{data.get('mtf_tf', '')}_{data.get('ltf_tf', '')}",
        symbol=ticker,
        timeframe_label="Top-Down MTF",
        build_prompt_fn=lambda t=ticker, m=market, a=data, c=currency: build_tdmtf_ai_prompt(t, m, a, c),
        system_prompt=TDMTF_AI_SYSTEM,
        provider=provider,
        model=model,
        api_key=api_key,
        button_in_column=False,
    )


def render_top_down_mtf_tab():
    """Top-Down MTF SMC scanner — Groww & CoinDCX."""
    st.markdown("<h1>🔝 Top Down MTF Scanner</h1>", unsafe_allow_html=True)
    st.write(
        "SMC-based **top-down multi-timeframe** scanner: **HTF bias** → **MTF CHoCH + FVG/OB** → "
        "**LTF entry trigger**. Surfaces **approaching** and **ready** setups across **Groww** and **CoinDCX**."
    )

    provider, model, api_key = render_ai_config(
        PREFIX,
        caption="AI View interprets the 3-step SMC pipeline and trade plan per ticker.",
    )

    st.markdown("---")

    m1, m2 = st.columns(2)
    with m1:
        tdmtf_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            key="tdmtf_market",
        )
    with m2:
        tdmtf_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="tdmtf_exchange")
            if is_india_market(tdmtf_market) else "NSE"
        )

    st.markdown("### 📊 Tickers")
    tdmtf_tickers: list[str] = []
    is_crypto = is_crypto_market(tdmtf_market)

    if is_crypto:
        tdmtf_tickers = render_coindcx_ticker_selection("tdmtf")
    else:
        tdmtf_tickers = render_equity_index_ticker_selection(tdmtf_market, "tdmtf")

    st.markdown("### ⏱️ Timeframe Hierarchy")
    st.caption("Choose HTF (bias), MTF (setup), and LTF (entry). Uses hub LTF·MTF·HTF when enabled.")
    from app.market_pulse.ta_mtf_hub_ui import render_ta_role_selectboxes

    tf_labels = {tf: TIMEFRAMES.get(tf, {}).get("label", tf) for tf in ALL_TFS}
    role_tfs = render_ta_role_selectboxes(
        "tdmtf",
        ALL_TFS,
        role_order=("HTF", "MTF", "LTF"),
        labels={
            "HTF": "HTF (Step 1 — Bias)",
            "MTF": "MTF (Step 2 — CHoCH + Zone)",
            "LTF": "LTF (Step 3 — Entry)",
        },
        format_func=lambda tf: tf_labels.get(tf, tf),
    )
    htf_tf = role_tfs["HTF"]
    mtf_tf = role_tfs["MTF"]
    ltf_tf = role_tfs["LTF"]

    tdmtf_bars = st.slider(
            "Bars per TF",
            min_value=80,
            max_value=600,
            value=300,
            step=20,
            key="tdmtf_bars",
        )

    tdmtf_actionable_only = render_ta_screener_options("tdmtf")
    st.caption(
        f"🧮 **{len(tdmtf_tickers)}** ticker(s) · "
        f"**{htf_tf}** → **{mtf_tf}** → **{ltf_tf}** · {tdmtf_bars} bars each"
    )

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button(
            "🔎 RUN TOP-DOWN MTF SCAN",
            type="primary",
            width='stretch',
            key="tdmtf_run",
        )
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('tdmtf_last_scan', '—')}")

    if run_btn:
        if not tdmtf_tickers:
            st.error("Select at least one ticker.")
            return

        bar = st.progress(0, text="Running top-down MTF scan…")
        groww_token = get_active_groww_token()
        results: dict[str, dict] = {}
        n = len(tdmtf_tickers)

        for i, tick in enumerate(tdmtf_tickers):
            bar.progress((i + 1) / n, text=f"{tick} — HTF/MTF/LTF analysis…")
            try:
                results[tick] = analyze_top_down(
                    tick,
                    htf_tf,
                    mtf_tf,
                    ltf_tf,
                    tdmtf_market,
                    groww_token,
                    tdmtf_exchange,
                    tdmtf_bars,
                )
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)

        bar.empty()
        st.session_state.tdmtf_results = results
        st.session_state.tdmtf_results_market = tdmtf_market
        st.session_state.tdmtf_is_crypto = is_crypto
        st.session_state.tdmtf_results_exchange = tdmtf_exchange
        st.session_state.tdmtf_htf_tf = htf_tf
        st.session_state.tdmtf_mtf_tf = mtf_tf
        st.session_state.tdmtf_ltf_tf = ltf_tf
        st.session_state.tdmtf_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("tdmtf_results", {})
    market_disp = st.session_state.get("tdmtf_results_market", tdmtf_market)
    is_crypto = st.session_state.get("tdmtf_is_crypto", is_crypto)

    if not results:
        st.info("Select tickers and timeframes, then click **RUN TOP-DOWN MTF SCAN**.")
        return

    st.markdown("---")
    _render_setup_alerts(results)
    _render_screener_grid(results, is_crypto)

    digest = []
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, "Top-Down MTF", d["error"], tab="Top Down MTF"))
        else:
            digest.append(summarize_top_down_mtf(d, tick))

    if tdmtf_actionable_only:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 Top-Down MTF Recommendations", group_filter=True)

    tickers_sorted = sorted(
        results.keys(),
        key=lambda t: results[t].get("priority", 0) if not results[t].get("error") else -1,
        reverse=True,
    )

    for ti, ticker in enumerate(tickers_sorted):
        data = results[ticker]
        if tdmtf_actionable_only and not data.get("error"):
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

    st.caption("⚠️ Top-down SMC flags alignment — always confirm MTF zone retest before entry.")
