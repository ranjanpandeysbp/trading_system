"""
confluence_strategy_tab.py
--------------------------
Multi-factor confluence strategy: Fibonacci · Price-Volume · VWAP · Supertrend ·
ATR · Support/Resistance — scored setups with trade suggestions.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from app.market_pulse.ai_view import (
    MTF_AI_SYSTEM,
    STANDARD_REPORT_FORMAT,
    combine_timeframe_sections,
    mtf_ticker_button,
    render_ai_config,
    render_mtf_ai_view_report,
)
from app.market_pulse.demo_trading import render_demo_trade_panel
from app.market_pulse.gap_trading import calculate_two_level_sr, fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.indicators import add_atr, add_obv, add_supertrend, add_vol_sma, add_vwap
from app.market_pulse.price_action import (
    _calc_atr,
    analyze_fibonacci,
    detect_support_resistance,
)
from app.market_pulse.run_summary import (
    make_summary,
    make_trade_plan,
    render_run_summary,
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
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
)


CONFLUENCE_AI_SYSTEM = """You are an expert multi-factor technical analyst for Indian equities and crypto.

The Confluence Engine scores alignment across:
- Fibonacci retracement / golden zone
- VWAP institutional bias
- Supertrend direction
- ATR-based volatility & stop placement
- Price-volume confirmation (volume ratio, OBV)
- Support & resistance (S1/S2, R1/R2)

Be data-driven — cite exact prices. If factors conflict, verdict must be WAIT or AVOID.
For BUY/SELL specify entry, stop, targets, R:R, and hold duration.
""" + STANDARD_REPORT_FORMAT

_HOLD_BY_TF = {
    "1m": "15–45 min scalp",
    "5m": "1–3 hours intraday",
    "15m": "2–6 hours intraday",
    "30m": "4–12 hours intraday",
    "1h": "1–3 trading days",
    "4h": "3–10 trading days",
    "1d": "1–4 weeks swing",
}


def _fmt(price: float | None, currency: str = "₹") -> str:
    if price is None or (isinstance(price, float) and np.isnan(price)):
        return "—"
    if currency == "$":
        return f"${price:,.4f}" if price < 1000 else f"${price:,.2f}"
    return f"{currency}{price:,.2f}"


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["open", "high", "low", "close"], how="any")


def _nearest_level(price: float, levels: list[float]) -> tuple[float | None, float]:
    if not levels:
        return None, float("inf")
    best = min(levels, key=lambda x: abs(x - price))
    return best, abs(best - price)


def _obv_trend(obv: pd.Series, bars: int = 5) -> str:
    if obv is None or len(obv) < bars + 1:
        return "FLAT"
    slope = float(obv.iloc[-1] - obv.iloc[-1 - bars])
    if slope > 0:
        return "RISING"
    if slope < 0:
        return "FALLING"
    return "FLAT"


def _price_volume_bias(df: pd.DataFrame, vol_ratio: float) -> dict[str, Any]:
    close = df["close"].values.astype(float)
    open_ = df["open"].values.astype(float)
    last_green = close[-1] >= open_[-1]
    prev_green = close[-2] >= open_[-2] if len(close) > 1 else last_green
    rising_vol = vol_ratio >= 1.15
    if last_green and rising_vol:
        bias, note = "BULLISH", "Up bar on above-average volume — buying pressure."
    elif not last_green and rising_vol:
        bias, note = "BEARISH", "Down bar on above-average volume — selling pressure."
    elif last_green and prev_green:
        bias, note = "MILD BULLISH", "Consecutive up closes — momentum intact."
    elif not last_green and not prev_green:
        bias, note = "MILD BEARISH", "Consecutive down closes — weak tape."
    else:
        bias, note = "NEUTRAL", "Mixed price-volume — no clear confirmation."
    return {"bias": bias, "vol_ratio": round(vol_ratio, 2), "note": note}


def analyze_confluence_strategy(
    df: pd.DataFrame,
    *,
    sr_window: int = 5,
    fib_lookback: int = 100,
    st_period: int = 10,
    st_mult: float = 3.0,
    atr_period: int = 14,
    vol_period: int = 20,
    is_crypto: bool = False,
) -> dict[str, Any]:
    """Score Fib + VWAP + Supertrend + ATR + volume + S/R confluence."""
    empty: dict[str, Any] = {
        "verdict": "NO SETUP",
        "direction": "—",
        "confidence": 0,
        "bull_score": 0,
        "bear_score": 0,
        "signals": [],
        "trade_plan": None,
        "fibonacci": {},
        "sr": {"supports": [], "resistances": []},
        "sr_levels": {},
        "vwap": {},
        "supertrend": {},
        "atr": {},
        "volume": {},
        "summary": "Insufficient data.",
    }
    if df is None or df.empty or len(df) < 40:
        empty["summary"] = f"Need ≥40 bars (have {len(df) if df is not None else 0})."
        return empty

    work = _normalize_df(df)
    if "volume" not in work.columns:
        work["volume"] = 1.0

    work = add_atr(work, atr_period)
    work = add_vwap(work)
    work = add_vol_sma(work, vol_period)
    work = add_obv(work)
    work = add_supertrend(work, st_period, st_mult)

    atr_col = f"atr_{atr_period}"
    st_col = f"supertrend_{st_period}_{st_mult}"
    st_dir_col = f"supertrend_dir_{st_period}_{st_mult}"
    vol_ratio_col = f"vol_ratio_{vol_period}"

    price = float(work["close"].iloc[-1])
    atr = float(work[atr_col].iloc[-1]) if atr_col in work.columns else _calc_atr(work, atr_period)
    vwap_val = float(work["vwap"].iloc[-1]) if "vwap" in work.columns else price
    st_line = float(work[st_col].iloc[-1])
    st_dir = int(work[st_dir_col].iloc[-1]) if st_dir_col in work.columns else 0
    vol_ratio = float(work[vol_ratio_col].iloc[-1]) if vol_ratio_col in work.columns else 1.0
    obv_tr = _obv_trend(work["obv"])

    fib = analyze_fibonacci(work, lookback=fib_lookback)
    sr = detect_support_resistance(work, window=sr_window, num_levels=3)
    sr2 = calculate_two_level_sr(work)

    supports = [float(x["price"]) for x in sr.get("supports", []) if x.get("price")]
    resistances = [float(x["price"]) for x in sr.get("resistances", []) if x.get("price")]
    s1, s2 = sr2.get("s1"), sr2.get("s2")
    r1, r2 = sr2.get("r1"), sr2.get("r2")
    if s1:
        supports.append(float(s1))
    if s2:
        supports.append(float(s2))
    if r1:
        resistances.append(float(r1))
    if r2:
        resistances.append(float(r2))
    supports = sorted(set(p for p in supports if p < price), reverse=True)
    resistances = sorted(set(p for p in resistances if p > price))

    pv = _price_volume_bias(work, vol_ratio)
    bull_pts: list[tuple[str, int]] = []
    bear_pts: list[tuple[str, int]] = []

    # Supertrend
    if st_dir == 1:
        bull_pts.append((f"Supertrend bullish (line {st_line:.2f})", 22))
    elif st_dir == -1:
        bear_pts.append((f"Supertrend bearish (line {st_line:.2f})", 22))

    # VWAP
    if price > vwap_val * 1.001:
        bull_pts.append((f"Price above VWAP ({vwap_val:.2f})", 16))
    elif price < vwap_val * 0.999:
        bear_pts.append((f"Price below VWAP ({vwap_val:.2f})", 16))

    # Volume / OBV
    if pv["bias"] in ("BULLISH", "MILD BULLISH"):
        bull_pts.append((f"Price-volume: {pv['note']}", 14 if pv["bias"] == "BULLISH" else 8))
    elif pv["bias"] in ("BEARISH", "MILD BEARISH"):
        bear_pts.append((f"Price-volume: {pv['note']}", 14 if pv["bias"] == "BEARISH" else 8))
    if obv_tr == "RISING":
        bull_pts.append(("OBV rising — accumulation", 10))
    elif obv_tr == "FALLING":
        bear_pts.append(("OBV falling — distribution", 10))

    # Fibonacci
    if fib.get("price_in_golden_zone"):
        if fib.get("direction") == "DOWN":
            bull_pts.append(("Fib golden zone (38.2–61.8%) — bounce zone", 20))
        else:
            bear_pts.append(("Fib golden zone — rejection / pullback risk", 18))
    gz = fib.get("golden_zone") or {}
    if gz.get("lower") and gz.get("upper"):
        mid = (float(gz["lower"]) + float(gz["upper"])) / 2
        if price >= float(gz["lower"]) and fib.get("direction") == "UP":
            bull_pts.append((f"Price holding above Fib 50% ({mid:.2f})", 12))

    # S/R proximity
    near_sup, sup_dist = _nearest_level(price, supports)
    near_res, res_dist = _nearest_level(price, resistances)
    if near_sup and sup_dist <= atr * 0.8:
        bull_pts.append((f"Bouncing near support {near_sup:.2f}", 15))
    if near_res and res_dist <= atr * 0.8:
        bear_pts.append((f"Rejecting near resistance {near_res:.2f}", 15))
    if supports and price > supports[0]:
        bull_pts.append((f"Above nearest support {supports[0]:.2f}", 8))
    if resistances and price < resistances[0]:
        bear_pts.append((f"Below nearest resistance {resistances[0]:.2f}", 8))

    bull_score = sum(w for _, w in bull_pts)
    bear_score = sum(w for _, w in bear_pts)
    net = bull_score - bear_score
    confidence = min(95, max(35, 50 + abs(net) * 0.6))

    currency = "$" if is_crypto else "₹"
    trade_plan: dict[str, Any] | None = None
    verdict = "WAIT"
    direction = "—"

    if net >= 25 and bull_score >= 45:
        verdict = "STRONG BUY" if net >= 40 else "BUY"
        direction = "LONG"
    elif net <= -25 and bear_score >= 45:
        verdict = "SELL"
        direction = "SHORT"
    elif net >= 15 and bull_score >= 35:
        verdict = "WATCHLIST"
        direction = "LONG"
    elif net <= -15 and bear_score >= 35:
        verdict = "WATCHLIST"
        direction = "SHORT"
    else:
        verdict = "NO SETUP"

    if verdict in ("BUY", "STRONG BUY", "SELL", "WATCHLIST"):
        if direction == "LONG":
            entry = price
            sl = min(
                supports[0] if supports else entry - atr * 1.5,
                entry - atr * 1.5,
            )
            tp1 = resistances[0] if resistances else entry + atr * 2
            ext = fib.get("extensions") or {}
            if ext.get("127.2%") and float(ext["127.2%"]) > entry:
                tp1 = float(ext["127.2%"])
            tp2 = resistances[1] if len(resistances) > 1 else (
                float(ext.get("161.8%", tp1 + atr))
            )
            risk = max(entry - sl, atr * 0.25)
            reward = tp1 - entry
            rr = reward / risk if risk > 0 else 0
        else:
            entry = price
            sl = max(
                resistances[0] if resistances else entry + atr * 1.5,
                entry + atr * 1.5,
            )
            tp1 = supports[0] if supports else entry - atr * 2
            ext = fib.get("extensions") or {}
            if ext.get("127.2%") and float(ext["127.2%"]) < entry:
                tp1 = float(ext["127.2%"])
            tp2 = supports[1] if len(supports) > 1 else entry - atr * 3
            risk = max(sl - entry, atr * 0.25)
            reward = entry - tp1
            rr = reward / risk if risk > 0 else 0

        sl_pct = abs(entry - sl) / entry * 100
        tp_pct = abs(tp1 - entry) / entry * 100
        trade_plan = {
            "direction": direction,
            "entry": round(entry, 4),
            "stop_loss": round(sl, 4),
            "take_profit_1": round(tp1, 4),
            "take_profit_2": round(tp2, 4),
            "risk_reward": round(rr, 2),
            "atr": round(atr, 4),
            "confidence": round(confidence, 1),
            "explanation": (
                f"{verdict}: {direction} confluence — "
                f"bull {bull_score} vs bear {bear_score} pts. "
                f"Entry {_fmt(entry, currency)}, SL {_fmt(sl, currency)}, "
                f"TP1 {_fmt(tp1, currency)} (R:R {rr:.1f})."
            ),
            "hold_duration": _HOLD_BY_TF.get("1d", "2–10 bars"),
            "stay_in": [
                "Supertrend remains aligned with trade direction",
                "Price holds above VWAP (long) or below VWAP (short)",
                "Volume stays supportive on impulse bars",
            ],
            "exit_flags": [
                f"Close beyond SL ({_fmt(sl, currency)})",
                "Supertrend flips against position",
                "Rejection at R1 with rising sell volume (longs)",
            ],
            "summary_plan": make_trade_plan(
                direction=direction,
                timeframe="",
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                expected_profit_pct=tp_pct * 0.85,
                confidence_pct=confidence,
            ),
        }

    signals = [
        {"side": "BULL", "text": t, "weight": w} for t, w in bull_pts
    ] + [
        {"side": "BEAR", "text": t, "weight": w} for t, w in bear_pts
    ]
    signals.sort(key=lambda x: x["weight"], reverse=True)

    summary = (
        f"{verdict} — bull {bull_score} / bear {bear_score} "
        f"(net {net:+d}). ST {'↑' if st_dir == 1 else '↓'}, "
        f"VWAP {'above' if price > vwap_val else 'below'}, vol×{vol_ratio:.2f}."
    )

    return {
        "verdict": verdict,
        "direction": direction,
        "confidence": round(confidence, 1),
        "bull_score": bull_score,
        "bear_score": bear_score,
        "net_score": net,
        "signals": signals,
        "trade_plan": trade_plan,
        "fibonacci": fib,
        "sr": sr,
        "sr_levels": sr2,
        "vwap": {"value": round(vwap_val, 4), "above": price > vwap_val},
        "supertrend": {"line": round(st_line, 4), "direction": st_dir},
        "atr": {"value": round(atr, 4), "pct_of_price": round(atr / price * 100, 2)},
        "volume": {**pv, "obv_trend": obv_tr},
        "price": round(price, 4),
        "summary": summary,
        "indicator_df": work,
    }


def build_confluence_chart(
    df: pd.DataFrame,
    analysis: dict,
    *,
    symbol: str = "",
    timeframe: str = "",
    currency: str = "₹",
) -> go.Figure:
    """Candlestick + VWAP + Supertrend + Fib + S/R."""
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    work = _normalize_df(df)
    ind = analysis.get("indicator_df")
    if isinstance(ind, pd.DataFrame) and not ind.empty:
        work = ind

    fig.add_trace(go.Candlestick(
        x=work.index,
        open=work["open"], high=work["high"],
        low=work["low"], close=work["close"],
        name="Price",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ))

    if "vwap" in work.columns:
        fig.add_trace(go.Scatter(
            x=work.index, y=work["vwap"],
            name="VWAP", line=dict(color="#fbbf24", width=1.5),
        ))

    st_cols = [c for c in work.columns if c.startswith("supertrend_") and "dir" not in c]
    if st_cols:
        fig.add_trace(go.Scatter(
            x=work.index, y=work[st_cols[0]],
            name="Supertrend", line=dict(color="#22d3ee", width=1.5),
        ))

    fib = analysis.get("fibonacci") or {}
    fib_colors = {
        "0.0% (High)": "#ef4444", "0.0% (Low)": "#22c55e",
        "38.2%": "#a78bfa", "50.0%": "#f59e0b",
        "61.8% (Golden)": "#fbbf24", "78.6%": "#94a3b8",
        "100.0% (Low)": "#22c55e", "100.0% (High)": "#ef4444",
    }
    for name, lvl in (fib.get("levels") or {}).items():
        fig.add_hline(
            y=float(lvl), line_dash="dot", line_color=fib_colors.get(name, "#64748b"),
            opacity=0.55,
            annotation_text=name, annotation_position="right",
        )

    sr2 = analysis.get("sr_levels") or {}
    for key, color in (("s1", "#34d399"), ("s2", "#10b981"), ("r1", "#f87171"), ("r2", "#ef4444")):
        val = sr2.get(key)
        if val:
            fig.add_hline(y=float(val), line_color=color, line_width=1, opacity=0.8)

    price = analysis.get("price")
    if price:
        fig.add_hline(
            y=float(price), line_color="#e2e8f0", line_dash="dash",
            annotation_text=f"Last {_fmt(float(price), currency)}",
        )

    title = f"{symbol} · {timeframe} — Confluence" if symbol else "Confluence Strategy"
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#cbd5e1")),
        height=460,
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,41,0.85)",
        font=dict(color="#94a3b8", size=10),
        legend=dict(orientation="h", y=1.02),
        margin=dict(l=40, r=40, t=50, b=30),
    )
    return fig


def summarize_confluence_strategy(analysis: dict, symbol: str, timeframe: str) -> dict:
    """Run-summary card for confluence tab."""
    verdict = analysis.get("verdict", "WAIT")
    conf = float(analysis.get("confidence", 0) or 0)
    bull = int(analysis.get("bull_score", 0) or 0)
    bear = int(analysis.get("bear_score", 0) or 0)
    plan = analysis.get("trade_plan")
    score = min(10.0, max(1.0, 5.0 + (bull - bear) / 18.0 + (conf - 50) / 25.0))

    action = analysis.get("summary", "")
    if plan:
        action = plan.get("explanation", action)

    reasons = [
        f"Bull {bull} pts · Bear {bear} pts.",
        f"VWAP: {'above' if (analysis.get('vwap') or {}).get('above') else 'below'}.",
        f"Supertrend: {'bullish' if (analysis.get('supertrend') or {}).get('direction') == 1 else 'bearish'}.",
        f"Vol ratio: {(analysis.get('volume') or {}).get('vol_ratio', '—')}.",
    ]
    return make_summary(
        ticker=symbol,
        timeframe=timeframe,
        tab="Confluence Strategy",
        score=score,
        verdict=verdict,
        action=action[:220],
        trade_plan=plan.get("summary_plan") if plan else None,
        summary=analysis.get("summary", "")[:120],
        reasons=reasons,
    )


def build_confluence_ai_prompt(
    symbol: str,
    timeframe: str,
    market: str,
    analysis: dict,
    currency: str = "₹",
) -> str:
    plan = analysis.get("trade_plan") or {}
    lines = [
        f"CONFLUENCE STRATEGY — {symbol} · {timeframe} · {market}",
        f"Verdict: {analysis.get('verdict')} · Direction: {analysis.get('direction')} · "
        f"Confidence: {analysis.get('confidence')}%",
        f"Bull score: {analysis.get('bull_score')} · Bear score: {analysis.get('bear_score')}",
        analysis.get("summary", ""),
        "",
        "Active signals:",
    ]
    for sig in (analysis.get("signals") or [])[:12]:
        lines.append(f"  [{sig['side']}] ({sig['weight']}) {sig['text']}")
    lines.append("")
    fib = analysis.get("fibonacci") or {}
    if fib.get("levels"):
        lines.append("Fibonacci:")
        for k, v in fib["levels"].items():
            lines.append(f"  {k}: {currency}{v}")
    sr2 = analysis.get("sr_levels") or {}
    lines.append(
        f"S/R: S1={sr2.get('s1')} S2={sr2.get('s2')} R1={sr2.get('r1')} R2={sr2.get('r2')}"
    )
    if plan:
        lines.extend([
            "",
            f"Trade: {plan.get('direction')} @ {currency}{plan.get('entry')}",
            f"SL {currency}{plan.get('stop_loss')} · TP1 {currency}{plan.get('take_profit_1')} · "
            f"TP2 {currency}{plan.get('take_profit_2')} · R:R {plan.get('risk_reward')}",
        ])
    return "\n".join(lines)


def _render_analysis_block(
    data: dict,
    is_crypto: bool,
    market: str,
    provider: str,
    model: str,
    api_key: str,
    *,
    nested: bool = False,
) -> None:
    if "error" in data:
        st.error(data["error"])
        return

    analysis = data["analysis"]
    df = data["df"]
    symbol = data.get("symbol", "?")
    tf = data.get("timeframe", "?")
    currency = "$" if is_crypto else "₹"
    verdict = analysis.get("verdict", "WAIT")
    icon = verdict_icon(verdict)

    st.markdown(f"### {icon} {verdict} · {analysis.get('direction', '—')} "
                f"({analysis.get('confidence', 0):.0f}% conf)")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bull score", analysis.get("bull_score", 0))
    c2.metric("Bear score", analysis.get("bear_score", 0))
    c3.metric("Net", analysis.get("net_score", 0))
    atr_info = analysis.get("atr") or {}
    c4.metric("ATR", f"{currency}{atr_info.get('value', 0):,.2f}",
              delta=f"{atr_info.get('pct_of_price', 0):.2f}% of price")

    st.plotly_chart(
        build_confluence_chart(df, analysis, symbol=symbol, timeframe=tf, currency=currency),
        width='stretch',
    )

    plan = analysis.get("trade_plan")
    if plan:
        st.markdown("#### 📋 Suggested trade")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Entry", _fmt(plan.get("entry"), currency))
        t2.metric("Stop loss", _fmt(plan.get("stop_loss"), currency))
        t3.metric("Target 1", _fmt(plan.get("take_profit_1"), currency))
        t4.metric("R:R", f"{plan.get('risk_reward', 0):.2f}")
        st.caption(plan.get("explanation", ""))
        hc1, hc2 = st.columns(2)
        with hc1:
            st.markdown("**Stay in while**")
            for item in plan.get("stay_in") or []:
                st.markdown(f"- {item}")
        with hc2:
            st.markdown("**Exit if**")
            for item in plan.get("exit_flags") or []:
                st.markdown(f"- {item}")
        if not is_crypto:
            safe_key = f"{symbol}|{tf}".replace(" ", "_")
            render_demo_trade_panel(
                "conf",
                safe_key,
                symbol,
                tf,
                market,
                f"Confluence · {plan.get('direction', 'LONG')}",
                current_price=plan.get("entry"),
                source_tab="Confluence Strategy",
                groww_token=get_active_groww_token(),
                exchange=st.session_state.get("conf_results_exchange", "NSE"),
            )

    render_strategy_mtf_panel(
        symbol=symbol,
        market=market,
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("conf_results_exchange", "NSE"),
        primary_tf=tf,
        strategy_direction=(plan or {}).get("direction") or analysis.get("direction"),
    )

    with st.expander("Signal breakdown", expanded=False):
        sig_df = pd.DataFrame(analysis.get("signals") or [])
        if not sig_df.empty:
            st.dataframe(sig_df, hide_index=True, width='stretch')

    with st.expander("Fibonacci & S/R levels", expanded=False):
        fib = analysis.get("fibonacci") or {}
        if fib.get("levels"):
            st.dataframe(
                pd.DataFrame([
                    {"Level": k, "Price": _fmt(v, currency)}
                    for k, v in fib["levels"].items()
                ]),
                hide_index=True,
                width='stretch',
            )
        sr2 = analysis.get("sr_levels") or {}
        st.write(
            f"**S1** {_fmt(sr2.get('s1'), currency)} · "
            f"**S2** {_fmt(sr2.get('s2'), currency)} · "
            f"**R1** {_fmt(sr2.get('r1'), currency)} · "
            f"**R2** {_fmt(sr2.get('r2'), currency)}"
        )

    if api_key and not nested:
        from app.market_pulse.ai_view import call_ai_report, show_ai_view_block
        prompt = build_confluence_ai_prompt(symbol, tf, market, analysis, currency)
        if st.button(f"✨ AI View — {symbol} {tf}", key=f"conf_ai_{symbol}_{tf}"):
            raw = call_ai_report(
                CONFLUENCE_AI_SYSTEM, prompt, provider, model, api_key,
                user_intro="Confluence strategy review:",
            )
            show_ai_view_block(raw)


def render_confluence_strategy_tab():
    """Fib · Volume · VWAP · Supertrend · ATR · S/R confluence analyzer."""
    st.markdown("<h1>🎯 Confluence Strategy Engine</h1>", unsafe_allow_html=True)
    st.write(
        "Multi-factor **confluence scoring** across **Fibonacci**, **price-volume**, "
        "**VWAP**, **Supertrend**, **ATR** stops, and **support/resistance** — "
        "with ranked signals and a suggested trade plan."
    )

    provider, model, api_key = render_ai_config(
        "confluence_strategy",
        caption="Optional AI View refines the confluence verdict and trade plan.",
    )

    st.markdown("---")
    m1, m2 = st.columns(2)
    with m1:
        conf_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            key="conf_market",
        )
    with m2:
        conf_exchange = (
            st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="conf_exchange")
            if is_india_market(conf_market) else "NSE"
        )

    st.markdown("### 📊 Tickers")
    conf_tickers: list[str] = []
    is_crypto = is_crypto_market(conf_market)

    if is_crypto:
        conf_tickers = render_coindcx_ticker_selection("conf")
    else:
        conf_tickers = render_equity_index_ticker_selection(conf_market, "conf")

    st.markdown("### ⏱️ Timeframes")
    tfc1, tfc2, tfc3 = st.columns(3)
    with tfc1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        conf_tfs = render_ta_multiselect_timeframes(
            "conf",
            ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            legacy_default=["15m", "1h", "1d"],
            label="Timeframes",
        )
    with tfc2:
        conf_candles = st.slider("Candle history", 80, 650, 250, 50, key="conf_candles")
    with tfc3:
        conf_sr_win = st.slider("S/R swing window", 3, 12, 5, key="conf_sr_win")

    with st.expander("⚙️ Indicator parameters", expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            conf_fib_lb = st.slider("Fib lookback", 30, 300, 100, 10, key="conf_fib_lb")
            conf_st_p = st.slider("Supertrend period", 7, 21, 10, key="conf_st_p")
        with p2:
            conf_st_m = st.slider("Supertrend multiplier", 1.5, 5.0, 3.0, 0.5, key="conf_st_m")
            conf_atr_p = st.slider("ATR period", 7, 21, 14, key="conf_atr_p")
        with p3:
            conf_vol_p = st.slider("Volume SMA period", 10, 50, 20, key="conf_vol_p")

    total = len(conf_tickers) * len(conf_tfs)
    conf_actionable_only = render_ta_screener_options("conf")
    st.caption(f"🧮 **{total}** combinations")
    run_btn = st.button(
        "🔎 SCAN CONFLUENCE SETUPS",
        type="primary",
        width='stretch',
        key="conf_run",
    )

    if run_btn:
        if not conf_tickers or not conf_tfs:
            st.error("Select at least one ticker and timeframe.")
            return
        results: dict[str, dict] = {}
        bar = st.progress(0, text="Scanning…")
        groww_token = get_active_groww_token()
        i = 0
        for tick in conf_tickers:
            for tf in conf_tfs:
                i += 1
                bar.progress(i / total, text=f"{tick} | {tf}")
                try:
                    df = fetch_data_for_gap_scan(
                        tick, tf, conf_market, groww_token, conf_exchange, limit=conf_candles,
                    )
                    if df.empty or len(df) < 40:
                        results[f"{tick}|{tf}"] = {
                            "error": f"Insufficient data ({len(df)} bars, need 40+).",
                            "symbol": tick, "timeframe": tf,
                        }
                        continue
                    analysis = analyze_confluence_strategy(
                        df,
                        sr_window=conf_sr_win,
                        fib_lookback=conf_fib_lb,
                        st_period=conf_st_p,
                        st_mult=conf_st_m,
                        atr_period=conf_atr_p,
                        vol_period=conf_vol_p,
                        is_crypto=is_crypto,
                    )
                    analysis["trade_plan"] = analysis.get("trade_plan") or None
                    if analysis.get("trade_plan"):
                        analysis["trade_plan"]["hold_duration"] = _HOLD_BY_TF.get(tf, "2–10 bars")
                    results[f"{tick}|{tf}"] = {
                        "df": df, "analysis": analysis,
                        "symbol": tick, "timeframe": tf,
                    }
                except Exception as exc:
                    results[f"{tick}|{tf}"] = {
                        "error": str(exc)[:180],
                        "symbol": tick, "timeframe": tf,
                    }
                time.sleep(0.04)
        bar.empty()
        st.session_state.conf_results = results
        st.session_state.conf_results_market = conf_market
        st.session_state.conf_is_crypto = is_crypto
        st.session_state.conf_results_exchange = conf_exchange

    results = st.session_state.get("conf_results", {})
    market_disp = st.session_state.get("conf_results_market", conf_market)
    is_crypto = st.session_state.get("conf_is_crypto", is_crypto)

    if not results:
        st.info("Configure tickers & timeframes, then run the confluence scan.")
        return

    st.markdown("---")
    digest = []
    for d in results.values():
        if "error" in d:
            digest.append(summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Confluence"))
        else:
            digest.append(summarize_confluence_strategy(d["analysis"], d["symbol"], d["timeframe"]))
    digest = render_ta_screener_results(
        digest,
        title="🧭 Confluence Screener",
        strategy_label="confluence",
        actionable_only=conf_actionable_only,
    )

    if not api_key:
        st.info("💡 Add API keys in `.env` for **AI View** on each result.")

    tickers: list[str] = []
    for d in results.values():
        s = d.get("symbol")
        if s and s not in tickers:
            tickers.append(s)

    for ti, ticker in enumerate(tickers):
        if not should_show_ticker_in_screener(ticker, digest, actionable_only=conf_actionable_only):
            continue
        items = [(k, v) for k, v in results.items() if v.get("symbol") == ticker]
        summaries = [
            summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Confluence")
            if "error" in d
            else summarize_confluence_strategy(d["analysis"], d["symbol"], d["timeframe"])
            for _, d in items
        ]
        with st.expander(
            ticker_section_label(ticker, summaries),
            expanded=should_expand_ticker(ti),
        ):
            if api_key and len(items) > 1:
                mtf_ticker_button("conf", ticker)

                def _mtf_prompt(items=items, m=market_disp, t=ticker, cur="$" if is_crypto else "₹"):
                    sections = []
                    for _, d in items:
                        if "error" in d:
                            sections.append(f"{d['timeframe']}: ERROR — {d['error']}")
                        else:
                            sections.append(build_confluence_ai_prompt(
                                t, d["timeframe"], m, d["analysis"], cur,
                            ))
                    return combine_timeframe_sections(
                        f"CONFLUENCE — {t}", t, sections, market=m,
                    )

                render_mtf_ai_view_report(
                    "conf", ticker, _mtf_prompt, CONFLUENCE_AI_SYSTEM,
                    provider, model, api_key, len(items),
                )
            if len(items) > 1:
                render_run_summary(summarize_mtf_aggregate(summaries, ticker, "Confluence"))
            for _, data in items:
                tf = data.get("timeframe", "?")
                summary = next((s for s in summaries if s.get("timeframe") == tf), None)
                with st.expander(
                    tf_section_label(tf, summary),
                    expanded=(len(items) == 1),
                ):
                    _render_analysis_block(
                        data, is_crypto, market_disp, provider, model, api_key, nested=True,
                    )

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("confluence_strategy")

    st.caption(
        "⚠️ Confluence scoring is rules-based. Confirm with higher-timeframe trend and risk limits before trading."
    )
