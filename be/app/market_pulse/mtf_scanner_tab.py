"""
mtf_scanner_tab.py
------------------
Institutional Multi-Timeframe Scanner — Groww & CoinDCX.
7-component confluence engine with cross-TF alignment summary.
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
from app.market_pulse.env_config import api_key_env_hint
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.mtf_scanner_engine import (
    TF_ORDER,
    TIMEFRAMES,
    analyze_ticker,
)
from app.market_pulse.run_summary import (
    render_run_digest,
    render_run_summary,
    summarize_error,
    summarize_mtf_scanner,
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


MTF_AI_SYSTEM = """You are an institutional multi-timeframe (MTF) scanner analyst.

The engine scores 7 components per timeframe (Trend 25%, Momentum 20%, Price Action 15%,
S/R 15%, Volume 10%, Volatility 10%, Structure 5%) into a composite 0–100 score.

Confluence rules:
- ≥65% TFs bullish (score ≥60) → STRONG BULLISH CONFLUENCE
- ≥65% TFs bearish (score ≤40) → STRONG BEARISH CONFLUENCE
- Confidence <40% → indicators split; stay out or size down
- Confidence >70% + Composite >65% → high-conviction setup

Recommend top-down: align daily/4h bias before scalping lower TFs.
""" + STANDARD_REPORT_FORMAT

DEFAULT_TFS = ["15m", "1h", "4h", "1d"]
ALL_TFS = [tf for tf in TF_ORDER if tf in TIMEFRAMES]


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _score_bar_html(val: float, width: int = 18) -> str:
    filled = max(0, min(width, round(val / 100 * width)))
    color = "#22c55e" if val >= 60 else "#ef4444" if val <= 40 else "#eab308"
    return (
        f'<span style="font-family:monospace;color:{color}">'
        f'{"█" * filled}<span style="color:#475569">{"░" * (width - filled)}</span>'
        f"</span>"
    )


def build_mtf_ai_prompt(symbol: str, market: str, analysis: dict, currency: str) -> str:
    conf = analysis.get("confluence") or {}
    lines = [
        "=== INSTITUTIONAL MTF SCANNER ===",
        f"Symbol: {symbol}",
        f"Market: {market}",
        f"MTF Verdict: {conf.get('verdict', 'N/A')}",
        f"Average Score: {conf.get('avg_score', '—')}/100",
        f"Average Confidence: {conf.get('avg_confidence', '—')}%",
        f"Ready setups: {conf.get('ready_setup_count', 0)} · Watch: {conf.get('watch_setup_count', 0)}",
        f"Alignment: Bull {conf.get('bull_count', 0)} · Neutral {conf.get('neutral_count', 0)} · Bear {conf.get('bear_count', 0)}",
        "",
        "=== TRADING SETUPS BY TIMEFRAME ===",
    ]

    for su in analysis.get("trade_setups") or []:
        lines.append(
            f"  [{su.get('status')}] {su.get('label')} ({su.get('style')}) — "
            f"{su.get('direction')} · setup conf {su.get('setup_confidence', 0):.0f}% · "
            f"hold {su.get('hold_duration', '—')}"
        )
        if su.get("sl_pct") is not None:
            lines.append(
                f"     SL -{su['sl_pct']:.2f}% · TP1 +{su.get('tp1_pct', 0):.2f}% · "
                f"TP2 +{su.get('tp2_pct', 0):.2f}% · {su.get('hint', '')}"
            )

    for play in conf.get("suggested_play") or []:
        lines.append(f"  • {play}")

    tf_results = analysis.get("timeframes") or {}
    for tf in TF_ORDER:
        if tf not in tf_results:
            continue
        r = tf_results[tf]
        su = r.get("trade_setup") or {}
        lines.extend([
            "",
            f"--- {r.get('label', tf)} ---",
            f"Composite: {r.get('composite')}/100 · Confidence: {r.get('confidence')}%",
            f"Setup: {su.get('status', '—')} · Setup confidence: {su.get('setup_confidence', 0):.0f}%",
            f"Bias: {r.get('bias')} · Direction: {r.get('direction')}",
            f"Hold: {su.get('hold_duration', '—')}",
            f"Price: {currency}{r.get('price', 0):,.4f} ({r.get('change_pct', 0):+.2f}%)",
        ])
        if su.get("sl_pct") is not None:
            lines.append(
                f"Plan: SL -{su['sl_pct']:.2f}% · TP1 +{su.get('tp1_pct', 0):.2f}% · "
                f"TP2 +{su.get('tp2_pct', 0):.2f}%"
            )

    return "\n".join(lines)


SETUP_ICONS = {
    "READY": "🟢",
    "WATCH": "🟡",
    "LOW CONFIDENCE": "🟠",
    "NO SETUP": "⚪",
}


def _fmt_pct(val: float | None, *, sign: str = "+") -> str:
    if val is None:
        return "—"
    if sign == "-":
        return f"-{val:.2f}%"
    return f"+{val:.2f}%"


def _render_trade_setups_table(analysis: dict, currency: str) -> None:
    setups = analysis.get("trade_setups") or []
    if not setups:
        return

    rows = []
    for su in setups:
        rows.append({
            "TF": su.get("label", su.get("timeframe", "—")),
            "Style": su.get("style", "—"),
            "Status": su.get("status", "—"),
            "Direction": su.get("direction", "—"),
            "Setup Conf.": f"{su.get('setup_confidence', 0):.0f}%",
            "Ind. Conf.": f"{su.get('indicator_confidence', 0):.0f}%",
            "Score": f"{su.get('composite', 0):.0f}",
            "SL %": _fmt_pct(su.get("sl_pct"), sign="-") if su.get("sl_pct") is not None else "—",
            "TP1 %": _fmt_pct(su.get("tp1_pct")) if su.get("tp1_pct") is not None else "—",
            "TP2 %": _fmt_pct(su.get("tp2_pct")) if su.get("tp2_pct") is not None else "—",
            "Hold": su.get("hold_duration", "—"),
            "_priority": su.get("priority", 0),
        })

    st.markdown("#### 🎯 Trading Setups by Timeframe")
    st.caption(
        "Each row is a possible trade on that TF — **Setup Conf.** blends indicator agreement + directional edge. "
        "**Hold** = suggested time in trade for that timeframe style."
    )
    df = pd.DataFrame(rows).sort_values("_priority", ascending=False)
    st.dataframe(df.drop(columns=["_priority"]), width='stretch', hide_index=True)


def _render_setup_cards(analysis: dict, currency: str) -> None:
    setups = [s for s in (analysis.get("trade_setups") or []) if s.get("status") in ("READY", "WATCH")]
    if not setups:
        st.info("No READY or WATCH setups — neutral or low-confidence across selected timeframes.")
        return

    for su in setups:
        icon = SETUP_ICONS.get(su.get("status", ""), "•")
        with st.container(border=True):
            st.markdown(
                f"**{icon} {su.get('label')}** · {su.get('style')} · **{su.get('status')}** · "
                f"{su.get('direction', '—')}"
            )
            st.caption(su.get("hint", ""))
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Setup Conf.", f"{su.get('setup_confidence', 0):.0f}%")
            c2.metric("Ind. Conf.", f"{su.get('indicator_confidence', 0):.0f}%")
            c3.metric("SL", _fmt_pct(su.get("sl_pct"), sign="-"))
            c4.metric("TP1", _fmt_pct(su.get("tp1_pct")))
            c5.metric("TP2", _fmt_pct(su.get("tp2_pct")))
            c6.metric("Hold", su.get("hold_duration", "—"))
            if su.get("entry"):
                st.caption(
                    f"Entry {currency}{su['entry']:,.4f} · "
                    f"SL {currency}{su.get('sl', 0):,.4f} · "
                    f"TP1 {currency}{su.get('tp1', 0):,.4f} · "
                    f"TP2 {currency}{su.get('tp2', 0):,.4f} · "
                    f"R:R {su.get('rr1', 1):.0f}:1 / {su.get('rr2', 2):.0f}:1"
                )


def _render_style_setup_summary(analysis: dict) -> None:
    style_setups = analysis.get("style_setups") or {}
    rows = []
    for style in ("Scalp", "Intraday", "Swing", "Position"):
        su = style_setups.get(style)
        if not su:
            rows.append({"Style": style, "Best TF": "—", "Setup": "—", "Direction": "—",
                         "Conf.": "—", "SL %": "—", "TP2 %": "—", "Hold": "—"})
            continue
        rows.append({
            "Style": style,
            "Best TF": su.get("label", su.get("timeframe", "—")),
            "Setup": su.get("status", "—"),
            "Direction": su.get("direction", "—"),
            "Conf.": f"{su.get('setup_confidence', 0):.0f}%",
            "SL %": _fmt_pct(su.get("sl_pct"), sign="-") if su.get("sl_pct") is not None else "—",
            "TP2 %": _fmt_pct(su.get("tp2_pct")) if su.get("tp2_pct") is not None else "—",
            "Hold": su.get("hold_duration", "—"),
        })
    st.markdown("#### ⏱️ Best Setup per Trading Style")
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


def _render_setup_alerts(results: dict) -> None:
    ready, watch = [], []
    for tick, d in results.items():
        if d.get("error"):
            continue
        for su in d.get("trade_setups") or []:
            if su.get("status") == "READY":
                ready.append((tick, su))
            elif su.get("status") == "WATCH":
                watch.append((tick, su))
    if ready:
        st.success(
            "**{} READY setup(s):** ".format(len(ready))
            + ", ".join(
                f"**{t}** {s.get('timeframe')} {s.get('direction')} "
                f"(conf {s.get('setup_confidence', 0):.0f}%, hold {s.get('hold_duration', '—')})"
                for t, s in ready[:8]
            )
        )
    if watch:
        st.warning(
            "**{} WATCH setup(s):** ".format(len(watch))
            + ", ".join(
                f"**{t}** {s.get('timeframe')} {s.get('direction')}"
                for t, s in watch[:8]
            )
        )


def _render_confluence_banner(analysis: dict) -> None:
    conf = analysis.get("confluence") or {}
    verdict = conf.get("verdict", "—")
    vtype = conf.get("verdict_type", "")
    if vtype == "strong_bull":
        st.success(f"**{verdict}** — {conf.get('bull_count', 0)}/{conf.get('total_tfs', 0)} TFs bullish · avg {conf.get('avg_score', 0):.1f}/100")
    elif vtype == "strong_bear":
        st.error(f"**{verdict}** — {conf.get('bear_count', 0)}/{conf.get('total_tfs', 0)} TFs bearish · avg {conf.get('avg_score', 0):.1f}/100")
    elif vtype in ("mild_bull", "mild_bear"):
        st.warning(f"**{verdict}** — watch for confirmation · confidence {conf.get('avg_confidence', 0):.1f}%")
    else:
        st.info(f"**{verdict}** — mixed alignment; wait for clarity")


def _render_mtf_summary_table(analysis: dict) -> None:
    tf_results = analysis.get("timeframes") or {}
    if not tf_results:
        return
    rows = []
    for tf in TF_ORDER:
        if tf not in tf_results:
            continue
        r = tf_results[tf]
        rows.append({
            "Timeframe": r.get("label", tf),
            "Score": f"{r.get('composite', 0):.1f}",
            "Setup": (r.get("trade_setup") or {}).get("status", "—"),
            "Setup Conf.": f"{(r.get('trade_setup') or {}).get('setup_confidence', 0):.0f}%",
            "Bias": r.get("bias_arrow", r.get("bias", "—")),
            "Direction": r.get("direction", "—"),
            "SL %": _fmt_pct((r.get("trade_setup") or {}).get("sl_pct"), sign="-")
                    if (r.get("trade_setup") or {}).get("sl_pct") is not None else "—",
            "TP2 %": _fmt_pct((r.get("trade_setup") or {}).get("tp2_pct"))
                    if (r.get("trade_setup") or {}).get("tp2_pct") is not None else "—",
            "Hold": (r.get("trade_setup") or {}).get("hold_duration", "—"),
        })
    conf = analysis.get("confluence") or {}
    if rows:
        rows.append({
            "Timeframe": "MTF AVERAGE",
            "Score": f"{conf.get('avg_score', 0):.1f}",
            "Setup": f"{conf.get('ready_setup_count', 0)} ready / {conf.get('watch_setup_count', 0)} watch",
            "Setup Conf.": f"{conf.get('avg_confidence', 0):.1f}%",
            "Bias": conf.get("bias_arrow", conf.get("bias", "—")),
            "Direction": "—",
            "SL %": "—",
            "TP2 %": "—",
            "Hold": "—",
        })
    st.markdown("#### MTF Confluence Table")
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


def _render_tf_detail(tf: str, result: dict, currency: str) -> None:
    composite = result.get("composite", 50)
    conf = result.get("confidence", 0)
    su = result.get("trade_setup") or {}
    st.markdown(
        f"**{result.get('label', tf)}** · "
        f"Score **{composite:.1f}**/100 · "
        f"Setup **{su.get('status', '—')}** · "
        f"Setup Conf. **{su.get('setup_confidence', 0):.0f}%**"
    )
    st.markdown(_score_bar_html(composite), unsafe_allow_html=True)
    st.caption(su.get("hint", ""))

    if su.get("direction") in ("LONG", "SHORT"):
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Entry", f"{currency}{su.get('entry', 0):,.4f}")
        c2.metric("Stop Loss", _fmt_pct(su.get("sl_pct"), sign="-"))
        c3.metric("TP1", _fmt_pct(su.get("tp1_pct")))
        c4.metric("TP2", _fmt_pct(su.get("tp2_pct")))
        c5.metric("Hold", su.get("hold_duration", "—"))
        c6.metric("Ind. Conf.", f"{su.get('indicator_confidence', 0):.0f}%")
        st.caption(
            f"ATR={su.get('atr', 0):.4f} · R:R {su.get('rr1', 1):.0f}:1 / {su.get('rr2', 2):.0f}:1 · "
            f"Style: {su.get('style', '—')}"
        )

    comp_rows = []
    for name, comp in (result.get("components") or {}).items():
        sc = comp.get("score", 0)
        comp_rows.append({
            "Component": name,
            "Score": f"{sc:.0f}%",
            "Weight": f"{comp.get('weight', 0)}%",
            "Signals": (comp.get("signals") or "")[:120],
        })
    if comp_rows:
        st.dataframe(pd.DataFrame(comp_rows), width='stretch', hide_index=True)


def _render_screener_grid(results: dict, is_crypto: bool) -> None:
    currency = "$" if is_crypto else "₹"
    rows = []
    for tick, data in results.items():
        if data.get("error"):
            rows.append({
                "Ticker": tick, "Verdict": "ERROR", "Best Setup": "—", "Direction": "—",
                "Setup Conf.": "—", "SL %": "—", "TP2 %": "—", "Hold": "—", "Priority": 0,
            })
            continue
        conf = data.get("confluence") or {}
        best = data.get("best_setup") or {}
        rows.append({
            "Ticker": tick,
            "Verdict": conf.get("verdict", "—"),
            "Best Setup": f"{best.get('status', '—')} ({best.get('timeframe', '—')})" if best else "—",
            "Direction": best.get("direction", "—"),
            "Setup Conf.": f"{best.get('setup_confidence', 0):.0f}%" if best else "—",
            "SL %": _fmt_pct(best.get("sl_pct"), sign="-") if best.get("sl_pct") is not None else "—",
            "TP2 %": _fmt_pct(best.get("tp2_pct")) if best.get("tp2_pct") is not None else "—",
            "Hold": best.get("hold_duration", "—"),
            "Priority": best.get("priority", 0) + best.get("setup_confidence", 0) * 0.1,
        })
    if not rows:
        return
    df = pd.DataFrame(rows).sort_values("Priority", ascending=False)
    st.markdown("### 📋 MTF Screener Grid")
    st.dataframe(df.drop(columns=["Priority"]), width='stretch', hide_index=True)


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

    render_run_summary(summarize_mtf_scanner(data, ticker))
    _render_confluence_banner(data)
    _render_trade_setups_table(data, currency)
    _render_style_setup_summary(data)
    _render_setup_cards(data, currency)
    _render_mtf_summary_table(data)

    conf = data.get("confluence") or {}
    if conf.get("suggested_play"):
        st.markdown("#### Suggested Play")
        for line in conf["suggested_play"]:
            st.markdown(f"- {line}")

    tf_results = data.get("timeframes") or {}
    if tf_results:
        st.markdown("#### Per-Timeframe Breakdown")
        for tf in TF_ORDER:
            if tf not in tf_results:
                continue
            with st.expander(f"{TIMEFRAMES.get(tf, {}).get('label', tf)} — {tf_results[tf].get('composite', 0):.0f}/100", expanded=False):
                _render_tf_detail(tf, tf_results[tf], currency)

    errors = data.get("errors") or {}
    if errors:
        st.caption("Skipped: " + ", ".join(f"{tf}: {msg}" for tf, msg in errors.items()))

    st.markdown("### 🤖 AI View")
    if not api_key:
        st.info(f"💡 Set API keys in `.env` to enable AI View. {api_key_env_hint(provider)}")
    else:
        show_ai_view_block(
            session_prefix="mtf",
            result_key=_safe_key(ticker),
            symbol=ticker,
            timeframe_label="MTF",
            build_prompt_fn=lambda t=ticker, m=market, a=data, c=currency: build_mtf_ai_prompt(t, m, a, c),
            system_prompt=MTF_AI_SYSTEM,
            provider=provider,
            model=model,
            api_key=api_key,
            button_in_column=False,
        )


def render_mtf_scanner_tab():
    """Institutional MTF Scanner — Groww & CoinDCX."""
    st.markdown("<h1>📊 MTF Scanner</h1>", unsafe_allow_html=True)
    st.write(
        "Institutional **multi-timeframe confluence** scanner. Scores **7 components** per timeframe "
        "and surfaces cross-TF alignment for scalp and swing setups on **Groww** and **CoinDCX**."
    )

    provider, model, api_key = render_ai_config(
        "mtf_scanner",
        caption="AI View interprets MTF confluence and component breakdown per ticker.",
    )

    st.markdown("---")

    m1, m2 = st.columns(2)
    with m1:
        mtf_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            key="mtf_market",
        )
    with m2:
        mtf_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="mtf_exchange")
            if is_india_market(mtf_market) else "NSE"
        )

    st.markdown("### 📊 Tickers")
    mtf_tickers: list[str] = []
    is_crypto = is_crypto_market(mtf_market)

    if is_crypto:
        mtf_tickers = render_coindcx_ticker_selection("mtf")
    else:
        mtf_tickers = render_equity_index_ticker_selection(mtf_market, "mtf")

    st.markdown("### ⏱️ Timeframes & History")
    tfc1, tfc2 = st.columns(2)
    with tfc1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        mtf_timeframes = render_ta_multiselect_timeframes(
            "mtf",
            ALL_TFS,
            legacy_default=[tf for tf in DEFAULT_TFS if tf in ALL_TFS],
            label="Timeframes",
            help_text="Hub LTF·MTF·HTF mapped to scanner TFs when hub mode is on.",
        )
    with tfc2:
        mtf_bars = st.slider(
            "Candle History (bars per TF)",
            min_value=80,
            max_value=600,
            value=300,
            step=20,
            key="mtf_bars",
            help="More bars improve SMA200 and structure detection (min 30 required).",
        )

    mtf_actionable_only = render_ta_screener_options("mtf")
    total = len(mtf_tickers) * len(mtf_timeframes)
    st.caption(f"🧮 **{len(mtf_tickers)}** ticker(s) × **{len(mtf_timeframes)}** TF(s) = **{total}** analyses")

    col_run, col_time = st.columns([3, 1])
    with col_run:
        run_btn = st.button(
            "🔎 RUN MTF SCAN",
            type="primary",
            width='stretch',
            key="mtf_run",
        )
    with col_time:
        st.caption(f"Last scan: {st.session_state.get('mtf_last_scan', '—')}")

    if run_btn:
        if not mtf_tickers:
            st.error("Select at least one ticker.")
            return
        if not mtf_timeframes:
            st.error("Select at least one timeframe.")
            return

        bar = st.progress(0, text="Scanning MTF confluence…")
        groww_token = get_active_groww_token()
        results: dict[str, dict] = {}
        n = len(mtf_tickers)

        for i, tick in enumerate(mtf_tickers):
            bar.progress((i + 1) / n, text=f"{tick} — analyzing {len(mtf_timeframes)} TF(s)…")
            try:
                analysis = analyze_ticker(
                    tick, mtf_timeframes, mtf_market, groww_token, mtf_exchange, mtf_bars,
                )
                if not analysis.get("timeframes"):
                    results[tick] = {
                        "error": "No timeframe had sufficient data.",
                        "symbol": tick,
                    }
                else:
                    results[tick] = analysis
            except Exception as exc:
                results[tick] = {"error": str(exc)[:200], "symbol": tick}
            time.sleep(0.04)

        bar.empty()
        st.session_state.mtf_results = results
        st.session_state.mtf_results_market = mtf_market
        st.session_state.mtf_is_crypto = is_crypto
        st.session_state.mtf_results_exchange = mtf_exchange
        st.session_state.mtf_last_scan = datetime.now().strftime("%H:%M:%S")

    results = st.session_state.get("mtf_results", {})
    market_disp = st.session_state.get("mtf_results_market", mtf_market)
    is_crypto = st.session_state.get("mtf_is_crypto", is_crypto)

    if not results:
        st.info("Select tickers & timeframes, then click **RUN MTF SCAN**.")
        return

    st.markdown("---")
    _render_setup_alerts(results)
    _render_screener_grid(results, is_crypto)

    digest = []
    for tick, d in results.items():
        if d.get("error"):
            digest.append(summarize_error(tick, "MTF", d["error"], tab="MTF Scanner"))
        else:
            digest.append(summarize_mtf_scanner(d, tick))

    if mtf_actionable_only:
        digest = [s for s in digest if s.get("verdict") in ("BUY", "SELL", "WATCHLIST")]

    render_run_digest(digest, title="🧭 MTF Recommendations", group_filter=True)

    tickers_sorted = sorted(
        results.keys(),
        key=lambda t: (
            (results[t].get("confluence") or {}).get("avg_score", 0)
            if not results[t].get("error") else -1
        ),
        reverse=True,
    )

    for ti, ticker in enumerate(tickers_sorted):
        data = results[ticker]
        if mtf_actionable_only and not data.get("error"):
            if not (data.get("confluence") or {}).get("actionable"):
                conf = data.get("confluence") or {}
                if conf.get("verdict_type") not in ("strong_bull", "strong_bear", "mild_bull", "mild_bear"):
                    continue

        summary = next((s for s in digest if s.get("ticker") == ticker), None)
        summaries = [summary] if summary else []

        with st.expander(
            ticker_section_label(ticker, summaries),
            expanded=should_expand_ticker(ti) and not data.get("error") and (
                (data.get("confluence") or {}).get("actionable", False)
            ),
        ):
            _render_result_block(ticker, data, is_crypto, market_disp, provider, model, api_key)

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("mtf_scanner")

    st.caption("⚠️ MTF confluence flags alignment — always confirm on lower TF before entry.")
