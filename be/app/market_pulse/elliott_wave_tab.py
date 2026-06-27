"""
elliott_wave_tab.py
-------------------
Dedicated Elliott Wave analyzer — one or more tickers × one or more timeframes.
"""

import time

import pandas as pd
import plotly.graph_objects as go
from app.market_pulse.ai_view import (
    STANDARD_REPORT_FORMAT,
    render_ai_config,
    show_ai_view_block,
)
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.price_action import analyze_elliott_waves, analyze_ema_crossovers, detect_support_resistance, detect_trendlines
from app.market_pulse.sma_ema_position import analyze_sma_ema_position
from app.market_pulse.sr_breakout import analyze_sr_breakout
from app.market_pulse.ta_structure_chart import render_ta_structure_section
from app.market_pulse.run_summary import (
    render_run_summary,
    summarize_elliott_wave,
    summarize_error,
    summarize_mtf_aggregate,
)
from app.market_pulse.ta_screener_ui import (
    render_ta_screener_options,
    render_ta_screener_results,
    render_strategy_mtf_panel,
    should_show_ticker_in_screener,
)
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    GROWW_MARKET,
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
)
from app.market_pulse.ta_ticker_sections import (
    should_expand_ticker,
    tf_section_label,
    ticker_section_label,
)


_PATTERN_COLORS = {
    "IMPULSE": "#10b981",
    "CORRECTIVE": "#f59e0b",
    "INCOMPLETE": "#94a3b8",
    "NONE": "#64748b",
}


def build_elliott_wave_chart(
    df: pd.DataFrame,
    ew: dict,
    symbol: str,
    timeframe: str,
    currency: str = "₹",
) -> go.Figure:
    """Candlestick chart with Elliott wave labels, connectors, and targets."""
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name=symbol,
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ))

    waves = ew.get("waves") or []
    for w in waves:
        si = min(int(w["start_idx"]), len(df) - 1)
        ei = min(int(w["end_idx"]), len(df) - 1)
        x0, x1 = df.index[si], df.index[ei]
        y0, y1 = w["start_price"], w["end_price"]
        color = "#4caf50" if w.get("direction") == "UP" else "#ef5350"
        fig.add_trace(go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode="lines",
            line=dict(color=color, width=2.5),
            showlegend=False,
            hoverinfo="skip",
        ))
        label = str(w.get("wave_num", ""))
        fig.add_annotation(
            x=x1,
            y=y1,
            text=label,
            showarrow=True,
            arrowhead=2,
            arrowsize=0.9,
            font=dict(size=12, color="#ffeb3b", family="Arial Black"),
            bgcolor="rgba(0,0,0,0.65)",
            bordercolor="#ffeb3b",
            borderwidth=1,
        )

    for name, price in (ew.get("wave_targets") or {}).items():
        fig.add_hline(
            y=price,
            line_dash="dot",
            line_color="rgba(96, 165, 250, 0.7)",
            line_width=1,
            annotation_text=f"{name}: {currency}{price:,.2f}",
            annotation_position="right",
            annotation_font_size=9,
        )

    pattern = ew.get("pattern", "NONE")
    pcolor = _PATTERN_COLORS.get(pattern, "#64748b")
    fig.update_layout(
        title=dict(
            text=f"{symbol} · {timeframe} — Elliott Wave ({pattern})",
            font=dict(size=14, color="#e2e8f0"),
        ),
        height=480,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 41, 0.85)",
        font=dict(color="#94a3b8", size=10),
        xaxis=dict(gridcolor="#1e3a5f", rangeslider=dict(visible=False)),
        yaxis=dict(gridcolor="#1e3a5f", title="Price"),
        margin=dict(l=50, r=80, t=50, b=40),
        showlegend=False,
    )
    fig.add_annotation(
        x=0.01, y=0.98, xref="paper", yref="paper",
        text=f"Pattern: {pattern}",
        showarrow=False,
        font=dict(size=11, color=pcolor),
        bgcolor="rgba(0,0,0,0.5)",
        bordercolor=pcolor,
        borderwidth=1,
        xanchor="left", yanchor="top",
    )
    return fig


EW_AI_SYSTEM = """You are an expert Elliott Wave analyst for Indian equities and crypto futures.
Use the supplied wave count, pattern, targets, and structure context.
Recommend BUY/SELL/AVOID only when wave position and structure support a clear trade.
""" + STANDARD_REPORT_FORMAT


def build_elliott_ai_prompt(symbol: str, tf: str, ew: dict, price: float, currency: str) -> str:
    lines = [
        "=== ELLIOTT WAVE ===",
        f"Ticker: {symbol} | Timeframe: {tf}",
        f"Pattern: {ew.get('pattern', '—')} | Current wave: {ew.get('current_wave', '—')}",
        f"Price: {currency}{price:,.4f}",
        f"Notes: {ew.get('notes', '—')}",
    ]
    if ew.get("wave_targets"):
        lines.append("Targets:")
        for name, tgt in ew["wave_targets"].items():
            lines.append(f"  - {name}: {currency}{tgt:,.4f}")
    return "\n".join(lines)


def _render_elliott_result_block(
    key: str,
    data: dict,
    is_crypto: bool,
    zigzag_pct: float,
    *,
    nested: bool = False,
) -> None:
    """Render one ticker × timeframe Elliott wave result."""
    currency = "$" if is_crypto else "₹"
    symbol = data.get("symbol", "")
    tf = data.get("timeframe", "")

    if "error" in data:
        st.error(f"**{symbol} | {tf}** — {data['error']}")
        return

    df = data["df"]
    ew = data["elliott_wave"]
    pattern = ew.get("pattern", "NONE")
    current = ew.get("current_wave", "—")
    price = float(df["close"].iloc[-1])

    pattern_icon = {
        "IMPULSE": "🌊",
        "CORRECTIVE": "🔄",
        "INCOMPLETE": "⏳",
        "NONE": "❓",
    }.get(pattern, "📊")

    if not nested:
        with st.expander(
            f"{pattern_icon} **{symbol}** · `{tf}` — {pattern} (Wave {current})",
            expanded=False,
        ):
            _render_elliott_result_body(
                symbol, tf, df, ew, pattern, current, price, currency, zigzag_pct,
            )
        return

    _render_elliott_result_body(
        symbol, tf, df, ew, pattern, current, price, currency, zigzag_pct,
    )


def _render_elliott_result_body(
    symbol, tf, df, ew, pattern, current, price, currency, zigzag_pct,
) -> None:
    render_run_summary(summarize_elliott_wave(ew, symbol, tf))
    render_strategy_mtf_panel(
        symbol=symbol,
        market=st.session_state.get("ew_market", GROWW_MARKET),
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("ew_exchange", "NSE"),
        primary_tf=tf,
        strategy_direction=ew.get("direction"),
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pattern", pattern)
    m2.metric("Current Wave", str(current))
    m3.metric("Last Price", f"{currency}{price:,.2f}")
    m4.metric("ZigZag %", f"{zigzag_pct:.1f}")

    st.caption(ew.get("notes") or "No additional notes.")

    sma_ema = analyze_sma_ema_position(df, timeframe=tf)
    render_ta_structure_section(
        df, symbol, tf, currency,
        compact=True,
        sr=detect_support_resistance(df),
        trendlines=detect_trendlines(df),
        ema=analyze_ema_crossovers(df),
        sma_ema=sma_ema,
        ema_ladder=sma_ema.get("ema_ladder"),
        sr_breakout=analyze_sr_breakout(df, timeframe=tf),
        chart_height=360,
    )
    st.markdown("---")

    if ew.get("wave_targets"):
        tgt_cols = st.columns(min(3, len(ew["wave_targets"])))
        for i, (name, tgt) in enumerate(ew["wave_targets"].items()):
            with tgt_cols[i % len(tgt_cols)]:
                st.metric(name, f"{currency}{tgt:,.2f}")

    st.plotly_chart(
        build_elliott_wave_chart(df, ew, symbol, tf, currency),
        width="stretch",
        config={"displayModeBar": True},
    )

    if waves := ew.get("waves"):
        wave_rows = [{
            "Wave": w.get("wave_num"),
            "Direction": w.get("direction"),
            "Start": f"{currency}{w['start_price']:,.2f}",
            "End": f"{currency}{w['end_price']:,.2f}",
            "Move %": (
                f"{((w['end_price'] - w['start_price']) / w['start_price'] * 100):+.2f}%"
                if w["start_price"] else "—"
            ),
        } for w in waves]
        st.markdown("**Wave Legs**")
        st.dataframe(pd.DataFrame(wave_rows), hide_index=True, width='stretch')

    st.markdown("### 🤖 AI View")
    show_ai_view_block(
        "ew",
        f"{symbol}|{tf}",
        symbol,
        tf,
        lambda s=symbol, t=tf, e=ew, p=price, c=currency: build_elliott_ai_prompt(s, t, e, p, c),
        EW_AI_SYSTEM,
        button_in_column=False,
    )


def render_elliott_wave_tab():
    """Elliott Wave analysis for multiple tickers and timeframes."""
    st.markdown("<h1>🌊 Elliott Wave Analyzer</h1>", unsafe_allow_html=True)
    st.write(
        "Detect impulse (1–5) and corrective (ABC) wave structures using a ZigZag pivot filter. "
        "Scan **one or more tickers** across **one or more timeframes** for approaching wave setups."
    )

    render_ai_config(
        "elliott_wave",
        caption="AI View uses Gemini or Groq — choose provider & model inside each AI View block.",
    )

    st.markdown("---")

    ew_col1, ew_col2 = st.columns(2)
    with ew_col1:
        ew_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            index=0,
            key="ew_market",
        )
    with ew_col2:
        if is_india_market(ew_market):
            ew_exchange = st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="ew_exchange")
        else:
            ew_exchange = "NSE"

    st.markdown("### 📊 Select Tickers")
    ew_tickers: list[str] = []
    if is_crypto_market(ew_market):
        ew_tickers = render_coindcx_ticker_selection("ew")
    else:
        ew_tickers = render_equity_index_ticker_selection(ew_market, "ew")

    is_crypto = is_crypto_market(ew_market)

    st.markdown("### ⏱️ Timeframes & History")
    tf_col, hist_col, zz_col = st.columns(3)
    with tf_col:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        ew_timeframes = render_ta_multiselect_timeframes(
            "ew",
            ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            legacy_default=["1h", "1d"],
            label="Timeframes",
        )
    with hist_col:
        ew_candles = st.slider(
            "Candle History",
            min_value=50,
            max_value=650,
            value=250,
            step=50,
            key="ew_candle_count",
            help="More bars improve wave structure detection (min ~30 required).",
        )
    with zz_col:
        ew_zigzag = st.slider(
            "ZigZag Sensitivity %",
            min_value=1.0,
            max_value=10.0,
            value=3.0,
            step=0.5,
            key="ew_zigzag_pct",
            help="Lower = more pivots (noisier). Higher = fewer, larger swings.",
        )

    st.markdown("---")
    total = len(ew_tickers) * len(ew_timeframes)
    ew_actionable_only = render_ta_screener_options("ew")
    if total > 0:
        st.caption(f"🧮 **{total}** runs ({len(ew_tickers)} tickers × {len(ew_timeframes)} timeframes)")

    run_ew = st.button("🔎 SCAN ELLIOTT WAVE SETUPS", type="primary", width='stretch', key="ew_run_btn")

    if run_ew:
        if not ew_tickers:
            st.error("Select at least one ticker.")
            return
        if not ew_timeframes:
            st.error("Select at least one timeframe.")
            return

        all_results = {}
        progress = st.progress(0, text="Starting Elliott Wave scan…")
        scan_i = 0
        groww_token = get_active_groww_token()

        for tick in ew_tickers:
            for tf in ew_timeframes:
                scan_i += 1
                progress.progress(
                    scan_i / total,
                    text=f"Wave scan {tick} | {tf} ({scan_i}/{total})…",
                )
                try:
                    df = fetch_data_for_gap_scan(
                        symbol=tick,
                        timeframe=tf,
                        market=ew_market,
                        groww_token=groww_token,
                        exchange=ew_exchange,
                        limit=ew_candles,
                    )
                    if df.empty or len(df) < 30:
                        all_results[f"{tick}|{tf}"] = {
                            "error": f"Insufficient data ({len(df)} bars, need ≥30).",
                            "symbol": tick,
                            "timeframe": tf,
                        }
                        continue

                    ew = analyze_elliott_waves(df, zigzag_pct=ew_zigzag)
                    all_results[f"{tick}|{tf}"] = {
                        "df": df,
                        "elliott_wave": ew,
                        "symbol": tick,
                        "timeframe": tf,
                    }
                except Exception as exc:
                    all_results[f"{tick}|{tf}"] = {
                        "error": str(exc)[:200],
                        "symbol": tick,
                        "timeframe": tf,
                    }
                time.sleep(0.04)

        progress.empty()
        st.session_state.ew_all_results = all_results
        st.session_state.ew_is_crypto = is_crypto
        st.session_state.ew_results_zigzag_pct = ew_zigzag

    all_results = st.session_state.get("ew_all_results", {})
    is_crypto = st.session_state.get("ew_is_crypto", is_crypto)
    zigzag_pct = st.session_state.get("ew_results_zigzag_pct", ew_zigzag)

    if not all_results:
        st.info("Select tickers and timeframes, then click **RUN ELLIOTT WAVE ANALYSIS**.")
        return

    st.markdown("---")
    st.markdown("## 📋 Elliott Wave Results")

    digest = []
    for k, d in all_results.items():
        if "error" in d:
            digest.append(summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Elliott Wave"))
        else:
            digest.append(summarize_elliott_wave(d["elliott_wave"], d["symbol"], d["timeframe"]))
    digest = render_ta_screener_results(
        digest,
        title="🧭 Elliott Wave Screener",
        strategy_label="Elliott Wave",
        actionable_only=ew_actionable_only,
    )

    tickers_seen = []
    for d in all_results.values():
        sym = d.get("symbol")
        if sym and sym not in tickers_seen:
            tickers_seen.append(sym)

    for ti, ticker in enumerate(tickers_seen):
        if not should_show_ticker_in_screener(ticker, digest, actionable_only=ew_actionable_only):
            continue
        items = [(k, v) for k, v in all_results.items() if v.get("symbol") == ticker]
        summaries = [
            summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Elliott Wave")
            if "error" in d
            else summarize_elliott_wave(d["elliott_wave"], d["symbol"], d["timeframe"])
            for _, d in items
        ]
        with st.expander(
            ticker_section_label(ticker, summaries),
            expanded=should_expand_ticker(ti),
        ):
            if len(items) > 1:
                render_run_summary(summarize_mtf_aggregate(summaries, ticker, "Elliott Wave"))
            for key, data in items:
                tf = data.get("timeframe", "?")
                summary = next((s for s in summaries if s.get("timeframe") == tf), None)
                ew = data.get("elliott_wave") or {}
                extra = f"{ew.get('pattern', '—')} · Wave {ew.get('current_wave', '—')}" if "error" not in data else ""
                with st.expander(
                    tf_section_label(tf, summary, extra=extra),
                    expanded=(len(items) == 1),
                ):
                    _render_elliott_result_block(
                        key, data, is_crypto, zigzag_pct, nested=True,
                    )

    if all_results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("elliott_wave")

    st.caption(
        "⚠️ Elliott Wave labels are algorithmic estimates, not certified wave counts. "
        "Always confirm with price action and risk management."
    )
