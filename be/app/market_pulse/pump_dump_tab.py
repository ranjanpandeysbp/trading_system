"""
pump_dump_tab.py
----------------
Pump & Dump Predictor — Crypto + India (NSE/BSE) pre-move signals, scorer, trade plans.
"""

from __future__ import annotations

from app.market_pulse.ai_view import (
    STANDARD_REPORT_FORMAT,
    render_ai_config,
    show_ai_view_block,
)
from app.market_pulse.run_summary import make_summary
from app.market_pulse.ta_screener_ui import render_ta_screener_alerts, render_strategy_mtf_panel
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.india_pump_dump_predictor import (
    INDIA_ENTRY_TF_OPTIONS,
    INDIA_MOVE_EXPECTATIONS,
    INDIA_PRE_DUMP,
    INDIA_PRE_PUMP,
    SESSION_WINDOWS,
    IndiaPumpDumpAnalysis,
    analyze_india_ticker,
    current_session_phase,
    scan_india_universe,
)
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_groww_ticker_selection,
)
from app.market_pulse.pump_dump_predictor import (
    CRYPTO_ENTRY_TF_OPTIONS,
    HTF_OPTIONS,
    PRE_DUMP_SIGNALS,
    PRE_PUMP_SIGNALS,
    PumpDumpAnalysis,
    analyze_crypto_pair,
    scan_crypto_universe,
)
from app.market_pulse.pump_dump_guide import (
    MIN_SIGNALS_HELP,
    render_crypto_starter_guide,
    render_india_starter_guide,
)

CRYPTO_MARKET = "CoinDCX Futures"
GROWW_MARKET = "Groww (India Stocks)"


def _fmt_pct_chg(val: float | None) -> str:
    if val is None:
        return "—"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}%"


def _scan_row_display(r: dict, *, market: str) -> dict:
    """Build scan table row with % move columns and descriptive signals."""
    entry_tf = r.get("entry_tf") or "5m"
    htf = r.get("htf") or "15m"
    bars = r.get("momentum_bars") or 6
    price_lbl = f"Price Δ ({bars}×{entry_tf})"
    vol_lbl = f"Vol Δ vs prior ({bars}×{entry_tf})"
    htf_lbl = f"HTF price Δ ({bars}×{htf})"
    row = {
        "Side": r["side"],
        "Score": r["score"],
        "Verdict": r["verdict"],
        price_lbl: _fmt_pct_chg(r.get("price_chg_pct")),
        vol_lbl: _fmt_pct_chg(r.get("vol_chg_pct")),
        htf_lbl: _fmt_pct_chg(r.get("htf_price_chg_pct")),
        "Last bar Δ": _fmt_pct_chg(r.get("price_chg_1bar_pct")),
        "Active signals": r.get("signal_detail") or "—",
        "BB zone": (r.get("bb_zone") or "—").replace("_", " "),
        "HTF trend": r.get("htf_trend"),
    }
    if market == "crypto":
        row = {"Pair": r["symbol"], **row}
    else:
        row = {"Ticker": r["symbol"], **row, "PCR": r.get("pcr"), "Session": r.get("session")}
    return row

CRYPTO_AI = """You are an expert crypto futures trader specializing in pre-pump and pre-dump detection.
Analyze confluences, HTF bias, order book, funding, and scorer. Recommend SKIP if score < 55 or < 3 signals.
""" + STANDARD_REPORT_FORMAT

INDIA_AI = """You are an expert NSE/BSE intraday scalper specializing in pre-pump and pre-dump setups.
Use option chain (PCR, Max Pain, OI), FII/DII, Gift Nifty, ORB, VWAP, and session timing (exit by 15:10 IST).
Recommend SL-Market orders. Warn about MIS square-off, circuit limits, and F&O ban list.
""" + STANDARD_REPORT_FORMAT


def _stance_for_signal(active: bool, side: str) -> tuple[str, str, str]:
    """Return (emoji, stance label, action hint) for a signal card."""
    if not active:
        return "⚪", "NEUTRAL", "Not confirming — wait"
    if side == "long":
        return "🟢", "BULLISH", "Supports LONG entry"
    return "🔴", "BEARISH", "Supports SHORT entry"


def _htf_stance(htf_trend: str) -> tuple[str, str]:
    t = (htf_trend or "neutral").lower()
    if t == "up":
        return "🟢 BULLISH", "Higher TF favors LONG; shorts are counter-trend"
    if t == "down":
        return "🔴 BEARISH", "Higher TF favors SHORT; longs are counter-trend"
    return "⚪ NEUTRAL", "No clear HTF direction — reduce size or wait"


def _bias_stance(bias: str) -> tuple[str, str]:
    b = (bias or "neutral").lower()
    if b == "pump":
        return "🟢 BULLISH", "More pre-pump signals active than pre-dump"
    if b == "dump":
        return "🔴 BEARISH", "More pre-dump signals active than pre-pump"
    return "⚪ NEUTRAL", "Pump and dump signals balanced"


def _funding_stance(funding: float | None) -> tuple[str, str]:
    if funding is None:
        return "⚪ NEUTRAL", "Funding data unavailable"
    if funding < -0.01:
        return "🟢 BULLISH", "Negative funding — shorts pay longs (favors LONG)"
    if funding > 0.02:
        return "🔴 BEARISH", "High positive funding — longs crowded (favors SHORT)"
    return "⚪ NEUTRAL", "Funding near neutral — no strong edge from rates"


def _ob_stance(ratio: float | None, bid_heavy: bool = False, ask_heavy: bool = False) -> tuple[str, str]:
    if ratio is None:
        return "⚪ NEUTRAL", "Order book data unavailable"
    if bid_heavy or (ratio and ratio >= 1.15):
        return "🟢 BULLISH", f"Bid-heavy book ({ratio:.2f}x) — buy pressure"
    if ask_heavy or (ratio and ratio <= 0.87):
        return "🔴 BEARISH", f"Ask-heavy book ({ratio:.2f}x) — sell pressure"
    return "⚪ NEUTRAL", f"Balanced book ({ratio:.2f}x) — no clear imbalance"


def _trigger_closed_from_conf(conf: dict) -> bool:
    for row in conf.get("breakdown", []):
        if "trigger" in row.get("label", "").lower():
            return (row.get("earned") or 0) > 0
    return False


def _entry_blockers(side: str, conf: dict, htf_trend: str, trigger_closed: bool) -> list[str]:
    blockers: list[str] = []
    htf = (htf_trend or "neutral").lower()
    if side == "LONG" and htf == "down":
        blockers.append("HTF trend is DOWN (bearish) — long is counter-trend")
    if side == "SHORT" and htf == "up":
        blockers.append("HTF trend is UP (bullish) — short is counter-trend")
    if not conf.get("min_signals_met"):
        blockers.append(f"Only {conf.get('signal_count', 0)}/3 required signals active")
    if conf.get("total", 0) < 55:
        blockers.append(f"Confluence score {conf.get('total', 0)}/100 — need ≥55 to trade")
    if not trigger_closed:
        blockers.append("Trigger candle not closed — wait for next candle open")
    return blockers


def _pick_primary_side(conf_long: dict, conf_short: dict) -> tuple[str, dict, str]:
    """Best side, its confluence, and action: ENTER | WAIT | SKIP."""
    vl, vs = conf_long.get("verdict", "SKIP"), conf_short.get("verdict", "SKIP")
    tl, ts = conf_long.get("total", 0), conf_short.get("total", 0)
    rank = {"STRONG": 4, "TRADE": 3, "WATCH": 2, "SKIP": 1}

    def better(a_verdict: str, a_total: int, b_verdict: str, b_total: int) -> bool:
        if rank[a_verdict] != rank[b_verdict]:
            return rank[a_verdict] > rank[b_verdict]
        return a_total >= b_total

    if better(vl, tl, vs, ts):
        side, conf, verdict = "LONG", conf_long, vl
    else:
        side, conf, verdict = "SHORT", conf_short, vs

    if verdict in ("STRONG", "TRADE"):
        action = "ENTER"
    elif verdict == "WATCH":
        action = "WAIT"
    else:
        action = "SKIP"
    return side, conf, action


def _render_signal_cards(
    signals: dict,
    catalog: list[tuple[str, str, str]],
    *,
    side: str,
    opposing: dict | None = None,
) -> None:
    cols = st.columns(2)
    for i, (key, title, tag) in enumerate(catalog):
        data = signals.get(key, {})
        active = data.get("active", False)
        emoji, stance, hint = _stance_for_signal(active, side)
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f"{emoji} **{title}** · `{stance}`")
                st.caption(f"{tag} · {hint}")
                st.write(data.get("note", "—"))
    if opposing:
        active_opp = [k for k, v in opposing.items() if v.get("active")]
        if active_opp:
            st.warning(
                f"**Opposing bearish/bullish signals active ({len(active_opp)}):** "
                "these work against this setup — need stronger confluence to override."
            )


def _bb_zone_stance(zone: str) -> tuple[str, str]:
    z = (zone or "").lower()
    if z in ("lower", "below_lower"):
        return "🟢 BULLISH", "At/below lower band — oversold bounce zone for longs"
    if z in ("upper", "above_upper"):
        return "🔴 BEARISH", "At/above upper band — overbought fade zone for shorts"
    if z == "middle":
        return "⚪ NEUTRAL", "At middle band (20 SMA) — equilibrium"
    if z == "upper_half":
        return "⚪ NEUTRAL", "Upper half of bands — bullish bias but not extended"
    if z == "lower_half":
        return "⚪ NEUTRAL", "Lower half of bands — weak but not washed out"
    return "⚪ NEUTRAL", "Bollinger position n/a"


def _render_technical_structure(a) -> None:
    ctx = getattr(a, "technical_context", None) or {}
    if not ctx:
        return
    bb_lbl, bb_hint = _bb_zone_stance(ctx.get("bb_zone", ""))
    st.markdown("##### 📐 EMA · Candles · Bollinger")
    c1, c2, c3 = st.columns(3)
    c1.metric("Bollinger zone", (ctx.get("bb_zone") or "n/a").replace("_", " "))
    c1.caption(f"{bb_lbl} — {ctx.get('bb_note') or bb_hint}")
    c2.metric("%B", f"{ctx.get('bb_pct_b', 0):.0f}%")
    c2.caption("0% = lower band · 50% = middle · 100% = upper")
    cross_txt = " · ".join(ctx.get("golden_crosses") or []) or " · ".join(ctx.get("death_crosses") or []) or "—"
    c3.metric("EMA crosses", cross_txt[:28] + ("…" if len(cross_txt) > 28 else ""))
    c3.caption(ctx.get("ema_stack") or "—")
    ema_brk = ctx.get("ema_breakouts") or ctx.get("ema_breakdowns") or []
    if ema_brk:
        st.caption(
            f"**EMA price breaks:** {', '.join(f'EMA{p}' for p in ema_brk)} · "
            f"Candles: {ctx.get('bullish_candle') or '—'} / {ctx.get('bearish_candle') or '—'}"
        )
    elif ctx.get("bullish_candle") or ctx.get("bearish_candle"):
        st.caption(
            f"**Key candles:** bullish {ctx.get('bullish_candle') or '—'} · "
            f"bearish {ctx.get('bearish_candle') or '—'}"
        )


def _render_context_metrics_crypto(a: PumpDumpAnalysis) -> None:
    htf_lbl, htf_note = _htf_stance(a.htf_trend)
    bias_lbl, bias_note = _bias_stance(a.bias)
    fund_lbl, fund_note = _funding_stance(a.funding)
    ob = a.order_book or {}
    ob_lbl, ob_note = _ob_stance(
        ob.get("ratio"), ob.get("bid_heavy", False), ob.get("ask_heavy", False),
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("HTF trend", a.htf_trend.upper())
    c1.caption(f"{htf_lbl} — {htf_note}")
    c2.metric("Bias", a.bias.upper())
    c2.caption(f"{bias_lbl} — {bias_note}")
    c3.metric("Funding", f"{a.funding:+.4f}%" if a.funding is not None else "n/a")
    c3.caption(f"{fund_lbl} — {fund_note}")
    c4.metric("Bid/Ask", f"{ob.get('ratio', 1):.2f}x")
    c4.caption(f"{ob_lbl} — {ob_note}")


def _render_expert_accuracy_panel(a: IndiaPumpDumpAnalysis) -> None:
    tb = a.expert_time_bias or {}
    action = tb.get("action", "—")
    colors = {
        "PRIME": "#10b981", "GOOD": "#34d399", "OK": "#6b7280",
        "CAUTION": "#f59e0b", "WAIT": "#f59e0b", "AVOID": "#ef4444", "CLOSED": "#6b7280",
    }
    color = colors.get(action, "#6b7280")
    st.markdown(
        f"<div style='padding:10px 12px;border-radius:8px;border-left:4px solid {color};"
        f"background:#1f2937;margin:6px 0;'>"
        f"<b>Expert time window:</b> {action} — {tb.get('note', '—')}"
        f"</div>",
        unsafe_allow_html=True,
    )
    for w in a.expert_warnings or []:
        st.warning(w)
    sym_deals = [d for d in (a.bulk_deals or []) if (d.get("symbol") or "").upper() == a.symbol]
    if sym_deals:
        lines = [
            f"₹{float(d.get('price') or 0):,.2f} {d.get('side', '')} ({d.get('deal_type', 'deal')})"
            for d in sym_deals[:4]
        ]
        st.caption("**Institutional footprints (today):** " + " · ".join(lines))
    cl, cs = a.confluence_long or {}, a.confluence_short or {}
    if cl.get("expert_adj") or cs.get("expert_adj"):
        st.caption(
            f"Expert score adj — LONG **{cl.get('expert_adj', 0):+d}** · "
            f"SHORT **{cs.get('expert_adj', 0):+d}** (time traps, boosters, OI matrix)"
        )


def _render_context_metrics_india(a: IndiaPumpDumpAnalysis) -> None:
    htf_lbl, htf_note = _htf_stance(a.htf_trend)
    pcr = a.option_chain.get("pcr_oi")
    if pcr is not None and pcr >= 1.2:
        pcr_lbl, pcr_note = "🟢 BULLISH", f"PCR {pcr:.2f} — put writing / oversold bounce bias"
    elif pcr is not None and pcr < 0.8:
        pcr_lbl, pcr_note = "🔴 BEARISH", f"PCR {pcr:.2f} — crowded calls / fade risk"
    else:
        pcr_lbl, pcr_note = "⚪ NEUTRAL", f"PCR {pcr:.2f}" if pcr else "PCR n/a"
    gift = a.gift_nifty_chg
    if gift is not None and gift > 0.15:
        gift_lbl, gift_note = "🟢 BULLISH", f"Gift Nifty {gift:+.2f}% — gap-up bias"
    elif gift is not None and gift < -0.15:
        gift_lbl, gift_note = "🔴 BEARISH", f"Gift Nifty {gift:+.2f}% — gap-down bias"
    else:
        gift_lbl, gift_note = "⚪ NEUTRAL", (
            f"Gift Nifty {gift:+.2f}%" if gift is not None else "Gift Nifty n/a"
        )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("HTF trend", a.htf_trend.upper())
    c1.caption(f"{htf_lbl} — {htf_note}")
    c2.metric("PCR (OI)", f"{pcr:.2f}" if pcr else "n/a")
    c2.caption(f"{pcr_lbl} — {pcr_note}")
    c3.metric("Session", a.session_phase)
    c3.caption(a.session_note or "—")
    c4.metric("Gift Nifty", f"{gift:+.2f}%" if gift is not None else "n/a")
    c4.caption(f"{gift_lbl} — {gift_note}")


def _render_entry_decision_banner(
    *,
    side: str,
    action: str,
    conf: dict,
    plan: dict | None,
    blockers: list[str],
    currency: str,
) -> None:
    verdict = conf.get("verdict", "SKIP")
    total = conf.get("total", 0)
    sigs = conf.get("signal_count", 0)

    if action == "ENTER":
        bg, border, headline = "#064e3b", "#10b981", f"✅ ENTER {side} — {verdict}"
        sub = f"Score **{total}/100** · **{sigs}** active signals · confluence threshold met."
    elif action == "WAIT":
        bg, border, headline = "#78350f", "#f59e0b", f"⏳ WAIT — do not enter {side} yet"
        sub = f"Setup forming (**{verdict}**, {total}/100, {sigs} signals). Monitor until ≥3 signals and score ≥55."
    else:
        bg, border, headline = "#7f1d1d", "#ef4444", "🚫 DO NOT ENTER — skip this setup"
        sub = f"Best side {side} scores **{total}/100** ({verdict}) with **{sigs}** signals — below trade threshold."

    st.markdown(
        f"<div style='padding:14px 16px;border-radius:10px;background:{bg};"
        f"border:2px solid {border};margin:8px 0 12px 0;'>"
        f"<h3 style='margin:0;color:#fff;'>{headline}</h3>"
        f"<p style='margin:6px 0 0 0;color:#e5e7eb;'>{sub}</p></div>",
        unsafe_allow_html=True,
    )

    if blockers:
        st.markdown("**Why not enter (or what’s missing):**")
        for b in blockers:
            st.markdown(f"- {b}")

    if plan:
        st.markdown("#### Trade plan (reference levels)")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Entry", f"{currency}{plan['entry']:,.4f}" if currency == "$" else f"{currency}{plan['entry']:,.2f}")
        c2.metric("Stop loss", f"{currency}{plan['stop_loss']:,.4f}" if currency == "$" else f"{currency}{plan['stop_loss']:,.2f}")
        c3.metric("TP1", f"{currency}{plan['tp1']:,.4f}" if currency == "$" else f"{currency}{plan['tp1']:,.2f}")
        c4.metric("TP2", f"{currency}{plan['tp2']:,.4f}" if currency == "$" else f"{currency}{plan['tp2']:,.2f}")
        if plan.get("tp3"):
            c5.metric("TP3", f"{currency}{plan['tp3']:,.4f}" if currency == "$" else f"{currency}{plan['tp3']:,.2f}")
        st.info(
            f"**Hold:** {plan.get('hold_duration', '—')} · "
            f"**Expected move:** {plan.get('expected_move', '—')} · "
            f"**RR:** {plan.get('rr_ratio', 2.5)}:1"
        )
        st.caption(
            f"{plan.get('entry_rule', '')}"
            + (f" · {plan['hard_exit']}" if plan.get("hard_exit") else "")
        )
        st.markdown(
            f"- {plan.get('tp1_action', '')}\n"
            f"- {plan.get('tp2_action', '')}\n"
            f"- {plan.get('tp3_action', '')}\n"
            f"- {plan.get('breakeven_rule', '')}"
        )
        if not plan.get("actionable"):
            st.warning("Levels shown for planning only — **do not enter** until verdict is TRADE or STRONG.")


def _render_scorer(conf: dict) -> None:
    total = conf.get("total", 0)
    verdict = conf.get("verdict", "SKIP")
    color = "#10b981" if total >= 75 else "#34d399" if total >= 55 else "#f59e0b" if total >= 38 else "#ef4444"
    st.markdown(
        f"<div style='padding:12px;border-radius:8px;border:1px solid {color};'>"
        f"<h4 style='margin:0;color:{color};'>Confluence score — {total} / 100</h4>"
        f"<p style='margin:4px 0 0 0;'>{verdict} · "
        f"{'≥3 signals ✓' if conf.get('min_signals_met') else '&lt;3 signals — wait'}</p></div>",
        unsafe_allow_html=True,
    )
    for row in conf.get("breakdown", []):
        mx = row.get("max") or 1
        st.progress(row["earned"] / mx if mx else 0, text=f"{row['label']} (+{row['earned']}/{mx})")
    st.caption(
        "**STRONG** ≥75 + ≥3 signals · **TRADE** ≥55 + ≥3 · **WATCH** 38–54 · **SKIP** else. "
        "Score includes **signal stack** (more green rules = more points). Trade plan on TRADE/STRONG."
    )


def _render_trade_plan(plan: dict | None, currency: str = "₹") -> None:
    if not plan:
        st.info("Trade plan unavailable — insufficient data.")
        return
    def _px(v: float) -> str:
        return f"{currency}{v:,.4f}" if currency == "$" else f"{currency}{v:,.2f}"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Entry", _px(plan["entry"]))
    c2.metric("Stop loss", _px(plan["stop_loss"]))
    c3.metric("TP1", _px(plan["tp1"]))
    c4.metric("TP2", _px(plan["tp2"]))
    if plan.get("tp3"):
        c5.metric("TP3", _px(plan["tp3"]))
    status = "✅ Actionable" if plan.get("actionable") else "⏳ Reference only — not actionable yet"
    extra = f" · Hard exit: {plan['hard_exit']}" if plan.get("hard_exit") else ""
    st.caption(
        f"**{plan['direction']}** · {status} · RR {plan['rr_ratio']}:1 · "
        f"Expected {plan['expected_move']} · Hold: {plan.get('hold_duration', '—')} · "
        f"{plan['entry_rule']}{extra}"
    )
    st.markdown(
        f"- {plan['tp1_action']}\n- {plan['tp2_action']}\n- {plan['tp3_action']}\n- {plan['breakeven_rule']}"
    )


def _crypto_prompt(a: PumpDumpAnalysis, side: str) -> str:
    conf = a.confluence_long if side == "LONG" else a.confluence_short
    signals = a.pump_signals if side == "LONG" else a.dump_signals
    active = [k for k, v in signals.items() if v.get("active")]
    return "\n".join([
        f"CRYPTO PUMP/DUMP — {a.symbol}", f"Side: {side} | TF: {a.entry_tf} | HTF: {a.htf} ({a.htf_trend})",
        f"Price: {a.price} | Funding: {a.funding} | OB: {a.order_book.get('ratio')}",
        f"Score: {conf.get('total')}/100 — {conf.get('verdict')} | Signals: {', '.join(active)}",
    ])


def _india_prompt(a: IndiaPumpDumpAnalysis, side: str) -> str:
    conf = a.confluence_long if side == "LONG" else a.confluence_short
    signals = a.pump_signals if side == "LONG" else a.dump_signals
    active = [k for k, v in signals.items() if v.get("active")]
    pcr = a.option_chain.get("pcr_oi", "—")
    return "\n".join([
        f"INDIA PUMP/DUMP — {a.symbol}", f"Side: {side} | TF: {a.entry_tf} | HTF: {a.htf} ({a.htf_trend})",
        f"Price: ₹{a.price:,.2f} | PCR: {pcr} | Session: {a.session_phase}",
        f"Gift Nifty: {a.gift_nifty_chg}% | Delivery: {a.delivery_pct}%",
        f"Score: {conf.get('total')}/100 — {conf.get('verdict')} | Signals: {', '.join(active)}",
    ])


def _render_crypto_analysis(a: PumpDumpAnalysis, provider: str, model: str, api_key: str) -> None:
    if a.error:
        st.error(a.error)
        return
    st.markdown(f"### {a.symbol} · ${a.price:,.4f}")
    _render_context_metrics_crypto(a)
    _render_technical_structure(a)

    side, conf, action = _pick_primary_side(a.confluence_long, a.confluence_short)
    plan = a.trade_plan_long if side == "LONG" else a.trade_plan_short
    trig_ok = _trigger_closed_from_conf(conf)
    blockers = _entry_blockers(side, conf, a.htf_trend, trig_ok)
    _render_entry_decision_banner(
        side=side, action=action, conf=conf, plan=plan, blockers=blockers, currency="$",
    )
    render_strategy_mtf_panel(
        symbol=a.symbol,
        market=CRYPTO_MARKET,
        groww_token=get_active_groww_token(),
        exchange="NSE",
        primary_tf=a.entry_tf or "15m",
        strategy_direction=side,
    )

    t1, t2, t3, t4 = st.tabs(["🚀 Pre-Pump", "📉 Pre-Dump", "📈 Long", "📉 Short"])
    with t1:
        st.caption("Each card is **BULLISH** when 🟢 active (supports long), **NEUTRAL** when ⚪ inactive.")
        _render_signal_cards(a.pump_signals, PRE_PUMP_SIGNALS, side="long", opposing=a.dump_signals)
    with t2:
        st.caption("Each card is **BEARISH** when 🔴 active (supports short), **NEUTRAL** when ⚪ inactive.")
        _render_signal_cards(a.dump_signals, PRE_DUMP_SIGNALS, side="short", opposing=a.pump_signals)
    with t3:
        _render_scorer(a.confluence_long)
        _render_trade_plan(a.trade_plan_long, "$")
        if api_key:
            show_ai_view_block("pdp", f"c|{a.symbol}|L", a.symbol, a.entry_tf,
                               lambda: _crypto_prompt(a, "LONG"), CRYPTO_AI, provider, model, api_key)
        if a.trade_plan_long and a.trade_plan_long.get("actionable"):
            render_demo_trade_panel("pdp", f"c|{a.symbol}|L", a.symbol, a.entry_tf, CRYPTO_MARKET,
                                    "Pump LONG", source_tab="Pump & Dump Predictor")
    with t4:
        _render_scorer(a.confluence_short)
        _render_trade_plan(a.trade_plan_short, "$")
        if api_key:
            show_ai_view_block("pdp", f"c|{a.symbol}|S", a.symbol, a.entry_tf,
                               lambda: _crypto_prompt(a, "SHORT"), CRYPTO_AI, provider, model, api_key)
        if a.trade_plan_short and a.trade_plan_short.get("actionable"):
            render_demo_trade_panel("pdp", f"c|{a.symbol}|S", a.symbol, a.entry_tf, CRYPTO_MARKET,
                                    "Dump SHORT", source_tab="Pump & Dump Predictor")


def _render_india_analysis(a: IndiaPumpDumpAnalysis, provider: str, model: str, api_key: str) -> None:
    if a.error:
        st.error(a.error)
        return
    st.markdown(f"### {a.symbol} · ₹{a.price:,.2f}")
    _render_context_metrics_india(a)
    _render_technical_structure(a)
    _render_expert_accuracy_panel(a)
    if a.option_chain.get("max_pain"):
        st.caption(f"Max Pain: **{a.option_chain['max_pain']:,.0f}** · Expiry: {a.option_chain.get('current_expiry', '—')}")

    side, conf, action = _pick_primary_side(a.confluence_long, a.confluence_short)
    plan = a.trade_plan_long if side == "LONG" else a.trade_plan_short
    trig_ok = _trigger_closed_from_conf(conf)
    blockers = _entry_blockers(side, conf, a.htf_trend, trig_ok)
    if "Dead zone" in (a.session_note or "") or a.session_phase == "After hours":
        blockers.append(f"Session **{a.session_phase}** — {a.session_note}")
    for w in a.expert_warnings or []:
        if w not in blockers:
            blockers.append(w.replace("⏱ ", "").replace("⚠️ ", ""))
    if not (a.expert_time_bias or {}).get("allow_entry", True):
        blockers.append(f"Expert time filter: **{a.expert_time_bias.get('action')}** — wait for better window")
    _render_entry_decision_banner(
        side=side, action=action, conf=conf, plan=plan, blockers=blockers, currency="₹",
    )
    render_strategy_mtf_panel(
        symbol=a.symbol,
        market=GROWW_MARKET,
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("pdp_india_exchange", "NSE"),
        primary_tf=a.entry_tf or "15m",
        strategy_direction=side,
    )

    t1, t2, t3, t4 = st.tabs(["🚀 Pre-Pump", "📉 Pre-Dump", "📈 Long", "📉 Short"])
    with t1:
        st.caption("🟢 **BULLISH** = active pre-pump rule · ⚪ **NEUTRAL** = not confirming long yet.")
        _render_signal_cards(a.pump_signals, INDIA_PRE_PUMP, side="long", opposing=a.dump_signals)
    with t2:
        st.caption("🔴 **BEARISH** = active pre-dump rule · ⚪ **NEUTRAL** = not confirming short yet.")
        _render_signal_cards(a.dump_signals, INDIA_PRE_DUMP, side="short", opposing=a.pump_signals)
    with t3:
        _render_scorer(a.confluence_long)
        _render_trade_plan(a.trade_plan_long)
        if api_key:
            show_ai_view_block("pdp", f"i|{a.symbol}|L", a.symbol, a.entry_tf,
                               lambda: _india_prompt(a, "LONG"), INDIA_AI, provider, model, api_key)
        if a.trade_plan_long and a.trade_plan_long.get("actionable"):
            render_demo_trade_panel("pdp", f"i|{a.symbol}|L", a.symbol, a.entry_tf, GROWW_MARKET,
                                    "India Pump LONG", source_tab="Pump & Dump Predictor",
                                    groww_token=get_active_groww_token())
    with t4:
        _render_scorer(a.confluence_short)
        _render_trade_plan(a.trade_plan_short)
        if api_key:
            show_ai_view_block("pdp", f"i|{a.symbol}|S", a.symbol, a.entry_tf,
                               lambda: _india_prompt(a, "SHORT"), INDIA_AI, provider, model, api_key)
        if a.trade_plan_short and a.trade_plan_short.get("actionable"):
            render_demo_trade_panel("pdp", f"i|{a.symbol}|S", a.symbol, a.entry_tf, GROWW_MARKET,
                                    "India Dump SHORT", source_tab="Pump & Dump Predictor",
                                    groww_token=get_active_groww_token())


def _render_scan_meta(meta: dict | None, label: str) -> None:
    if not meta:
        return
    st.caption(
        f"**{label}:** scanned {meta.get('scanned', 0)} · "
        f"with data {meta.get('with_data', 0)} · "
        f"results {meta.get('result_count', 0)}"
    )
    errors = meta.get("errors") or []
    if errors:
        with st.expander(f"⚠️ {len(errors)} fetch/analysis issue(s)", expanded=len(errors) <= 3):
            for e in errors[:15]:
                st.caption(e)


def _render_crypto_scan_results(provider: str, model: str, api_key: str) -> None:
    if not st.session_state.get("pdp_crypto_scan_done"):
        return
    st.markdown("---")
    st.markdown("### 📋 Crypto scan results")
    st.caption(
        "**Price Δ / Vol Δ** = % change over recent bars on entry TF (and HTF) · "
        "**Active signals** lists which rules fired (not just a count) · "
        "**Score** = confluence 0–100 · open **Analyze one** for full cards and trade plan."
    )
    _render_scan_meta(st.session_state.get("pdp_crypto_meta"), "Last scan")
    rows = st.session_state.get("pdp_crypto_rows") or []
    if not rows:
        st.warning(
            "No rows matched this scan. Set **Min active signals** to **0** to see every pair, "
            "or use **Analyze one** for full Pre-Pump/Pre-Dump cards. Check fetch errors above."
        )
    else:
        scan_digest = [
            make_summary(
                ticker=r["symbol"],
                timeframe=r.get("entry_tf", "5m"),
                tab="Pump/Dump",
                score=min(10.0, r.get("score", 0) / 10.0),
                verdict=r.get("verdict", "SKIP"),
                summary=f"{r.get('side', '')} — {r.get('active_count', 0)} active signals",
            )
            for r in rows
        ]
        render_ta_screener_alerts(scan_digest, strategy_label="pump/dump")
        st.dataframe(
            [_scan_row_display(r, market="crypto") for r in rows],
            width='stretch',
            hide_index=True,
        )
        pick = st.selectbox(
            "Drill into", ["—"] + [f"{r['symbol']} {r['side']}" for r in rows], key="pdp_c_pick",
        )
        if st.button("Open crypto analysis", key="pdp_c_drill") and pick != "—":
            idx = [f"{r['symbol']} {r['side']}" for r in rows].index(pick)
            st.session_state["pdp_crypto_last"] = rows[idx]["analysis"]
    last = st.session_state.get("pdp_crypto_last")
    if last:
        _render_crypto_analysis(last, provider, model, api_key)


def _render_crypto_section(provider: str, model: str, api_key: str) -> None:
    guide, scanner, process, rules = st.tabs(
        ["🚀 Starter Guide", "🔍 Scanner", "📋 Entry", "🛡️ Risk"],
    )
    with guide:
        render_crypto_starter_guide()
    with process:
        for t in [
            "HTF bias (15m → 1w)", "Key level on 3m/5m", "≥3 confluences", "Trigger closes",
            "SL beyond wick", "TP layers 40/40/20", "Breakeven after TP1",
        ]:
            st.markdown(f"- {t}")
    with rules:
        st.markdown("- Max risk 1% · RR ≥1:2 · Daily stop 3% · Max 2–3 positions")
        for r in ["Never move stop away", "No revenge trading", "No size increase after loss", "Low leverage on alts"]:
            st.warning(f"! {r}")
    with scanner:
        st.markdown("#### 📈 Select assets (same as Trend & Sentiment Analyzer)")
        pairs = render_coindcx_ticker_selection("pdp_c")
        from app.market_pulse.ta_mtf_hub_ui import (
            render_ta_hub_badge,
            resolve_entry_htf_from_hub,
        )

        hub_entry, hub_htf, from_hub = resolve_entry_htf_from_hub(
            "pdp_c", CRYPTO_ENTRY_TF_OPTIONS, HTF_OPTIONS, entry_default="5m", htf_default="15m",
        )
        c1, c2, c3, c4 = st.columns(4)
        mode = c1.selectbox("Mode", ["BOTH", "PUMP", "DUMP"], key="pdp_c_mode")
        if from_hub:
            render_ta_hub_badge("pdp_c")
            with c2:
                st.markdown(f"**Entry TF:** `{hub_entry}`")
            with c3:
                st.markdown(f"**HTF:** `{hub_htf}`")
            with st.expander("Override entry / HTF (crypto)", expanded=False):
                st.checkbox(
                    "Use custom entry & HTF",
                    key="pdp_c_entry_htf_override",
                )
            entry_tf, htf = hub_entry, hub_htf
        else:
            entry_tf = c2.selectbox(
                "Entry TF",
                CRYPTO_ENTRY_TF_OPTIONS,
                index=CRYPTO_ENTRY_TF_OPTIONS.index("5m"),
                key="pdp_c_tf",
                help="Candle timeframe for triggers, SL/TP, and entry signals (1m scalp → 1w swing).",
            )
            htf = c3.selectbox(
                "HTF",
                HTF_OPTIONS,
                index=HTF_OPTIONS.index("15m"),
                key="pdp_c_htf",
                help="Higher timeframe for trend bias — 4h/1d/1w for swing context on scalps.",
            )
        min_sig = c4.selectbox(
            "Min active signals (scan filter)",
            [0, 1, 2, 3],
            index=0,
            key="pdp_c_minsig",
            help="How many 🟢 green Pre-Pump/Pre-Dump rules required to appear in scan table. "
            "Use 0 to see all tickers. For live trades still aim for ≥3 on deep-dive.",
        )
        with st.expander("ℹ️ What are signals & Min active signals?", expanded=False):
            st.markdown(MIN_SIGNALS_HELP)
        single = st.selectbox("Deep dive one pair", ["—"] + pairs, key="pdp_c_one")
        b1, b2 = st.columns(2)
        if b1.button("🔍 Scan crypto", type="primary", key="pdp_c_scan"):
            if not pairs:
                st.error("Select at least one pair.")
            else:
                with st.spinner(f"Scanning {len(pairs)} pair(s)…"):
                    rows, meta = scan_crypto_universe(pairs, entry_tf, htf, mode, min_signals=min_sig)
                    meta["result_count"] = len(rows)
                    st.session_state["pdp_crypto_rows"] = rows
                    st.session_state["pdp_crypto_meta"] = meta
                    st.session_state["pdp_crypto_scan_done"] = True
                    st.session_state["pdp_crypto_last"] = None
                st.toast(f"Crypto scan done — {len(rows)} row(s)", icon="✅")
        if b2.button("🎯 Analyze one", key="pdp_c_one_btn") and single != "—":
            with st.spinner(f"Analyzing {single}…"):
                st.session_state["pdp_crypto_last"] = analyze_crypto_pair(single, entry_tf, htf)
                st.session_state["pdp_crypto_scan_done"] = True
    _render_crypto_scan_results(provider, model, api_key)


def _render_india_section(provider: str, model: str, api_key: str) -> None:
    guide, scanner, process, rules, session = st.tabs(
        ["🚀 Starter Guide", "🔍 Scanner", "📋 Entry", "🛡️ Risk", "🕐 Session"],
    )
    phase, note = current_session_phase()
    with session:
        st.info(f"**Now:** {phase} — {note}")
        for window, action in SESSION_WINDOWS:
            st.markdown(f"- **{window}** — {action}")
        st.caption("Expiry: Nifty/BankNifty Thursday · FinNifty Tuesday · Midcap Monday")
    with guide:
        render_india_starter_guide()
        st.markdown("#### Typical move size by timeframe")
        for k, v in INDIA_MOVE_EXPECTATIONS.items():
            if k != "DEFAULT":
                st.caption(f"**{k}** — " + " · ".join(f"{tf}: {m}" for tf, m in v.items()))
    with process:
        for t in [
            "8:45–9:10: Gift Nifty, FII/DII, mark PDH/PDL",
            "9:15–9:30: Let opening range form (first 15m)",
            "Check NSE option chain: PCR + Max Pain",
            "≥3 signal confluences", "5m trigger closes — enter next open",
            "SL-Market before entry", "50%/30%/20% scale · exit 15:10 IST",
        ]:
            st.markdown(f"- {t}")
    with rules:
        st.markdown("- Risk 0.5–1% · RR ≥1:2 · Daily stop 2% · Max 4–6 trades/day")
        for r in [
            "MIS auto square-off ~15:20 — exit by 15:10",
            "STT trap on expiry ITM options",
            "Circuit breaker trap on mid/small caps",
            "Check F&O ban list daily on nseindia.com",
            "SEBI peak margin — keep 20–30% buffer",
        ]:
            st.warning(f"! {r}")
        st.caption("Best instruments: Nifty, Bank Nifty, Fin Nifty + liquid F&O stocks")
    with scanner:
        groww_token = get_active_groww_token()
        if not groww_token:
            st.warning("Groww API token recommended for intraday data — yfinance fallback used when needed.")
        st.markdown("#### 📈 Select assets (same as Trend & Sentiment Analyzer)")
        tickers, exchange = render_groww_ticker_selection("pdp_i")
        st.markdown("#### Index F&O (optional — for option-chain bias)")
        fno_indices = st.multiselect(
            "Scan index symbols for PCR / Max Pain",
            ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"],
            default=["NIFTY", "BANKNIFTY"],
            key="pdp_i_fno",
            help="Prepended to stock scan when you want Nifty/BankNifty index setups too.",
        )
        scan_tickers = list(dict.fromkeys(fno_indices + tickers))
        from app.market_pulse.ta_mtf_hub_ui import (
            render_ta_hub_badge,
            resolve_entry_htf_from_hub,
        )

        hub_entry, hub_htf, from_hub = resolve_entry_htf_from_hub(
            "pdp_i", INDIA_ENTRY_TF_OPTIONS, HTF_OPTIONS, entry_default="5m", htf_default="15m",
        )
        c1, c2, c3, c4 = st.columns(4)
        mode = c1.selectbox("Mode", ["BOTH", "PUMP", "DUMP"], key="pdp_i_mode")
        if from_hub:
            render_ta_hub_badge("pdp_i")
            with c2:
                st.markdown(f"**Entry TF:** `{hub_entry}`")
            with c3:
                st.markdown(f"**HTF:** `{hub_htf}`")
            with st.expander("Override entry / HTF (India)", expanded=False):
                st.checkbox(
                    "Use custom entry & HTF",
                    key="pdp_i_entry_htf_override",
                )
            entry_tf, htf = hub_entry, hub_htf
        else:
            entry_tf = c2.selectbox(
                "Entry TF",
                INDIA_ENTRY_TF_OPTIONS,
                index=INDIA_ENTRY_TF_OPTIONS.index("5m"),
                key="pdp_i_tf",
                help="Entry candle TF — 3m uses 5m OHLCV; 4h/1d/1w for swing setups.",
            )
            htf = c3.selectbox(
                "HTF bias",
                HTF_OPTIONS,
                index=HTF_OPTIONS.index("15m"),
                key="pdp_i_htf",
                help="Higher timeframe trend — use 4h/1d/1w for positional bias on intraday entries.",
            )
        min_sig = c4.selectbox(
            "Min active signals (scan filter)",
            [0, 1, 2, 3],
            index=0,
            key="pdp_i_minsig",
            help="How many 🟢 green Pre-Pump/Pre-Dump rules required in the scan table. "
            "0 = show all tickers. Live trades: ≥3 green + score ≥55 on Analyze one.",
        )
        with st.expander("ℹ️ What are signals & Min active signals?", expanded=False):
            st.markdown(MIN_SIGNALS_HELP)
        single = st.selectbox("Deep dive one ticker", ["—"] + scan_tickers, key="pdp_i_one")
        b1, b2 = st.columns(2)
        if b1.button("🔍 Scan India", type="primary", key="pdp_i_scan"):
            if not scan_tickers:
                st.error("Select at least one ticker (INDEX or Custom).")
            else:
                with st.spinner(f"Scanning {len(scan_tickers)} ticker(s)…"):
                    rows, meta = scan_india_universe(
                        scan_tickers, entry_tf, htf, groww_token, exchange, mode, min_signals=min_sig,
                    )
                    meta["result_count"] = len(rows)
                    st.session_state["pdp_india_rows"] = rows
                    st.session_state["pdp_india_meta"] = meta
                    st.session_state["pdp_india_scan_done"] = True
                    st.session_state["pdp_india_last"] = None
                st.toast(f"India scan done — {len(rows)} row(s)", icon="✅")
        if b2.button("🎯 Analyze one", key="pdp_i_one_btn") and single != "—":
            with st.spinner(f"Analyzing {single}…"):
                st.session_state["pdp_india_last"] = analyze_india_ticker(
                    single, entry_tf, htf, groww_token, exchange,
                )
                st.session_state["pdp_india_scan_done"] = True
    _render_india_scan_results(provider, model, api_key)


def _render_india_scan_results(provider: str, model: str, api_key: str) -> None:
    if not st.session_state.get("pdp_india_scan_done"):
        return
    st.markdown("---")
    st.markdown("### 📋 India scan results")
    st.caption(
        "Scroll here after scan. **Price Δ / Vol Δ** = % move on scanned timeframes · "
        "**Active signals** = descriptive rule names · **PCR** = option-chain bias. "
        "Trade candidate: **≥3 active signals** and **Score ≥55** — confirm on **Analyze one**."
    )
    _render_scan_meta(st.session_state.get("pdp_india_meta"), "Last scan")
    rows = st.session_state.get("pdp_india_rows") or []
    if not rows:
        st.warning(
            "No rows matched filters. Set **Min active signals** to **0**, or **Analyze one** for full detail."
        )
    else:
        scan_digest = [
            make_summary(
                ticker=r["symbol"],
                timeframe=r.get("entry_tf", "5m"),
                tab="Pump/Dump",
                score=min(10.0, r.get("score", 0) / 10.0),
                verdict=r.get("verdict", "SKIP"),
                summary=f"{r.get('side', '')} — {r.get('active_count', 0)} active signals",
            )
            for r in rows
        ]
        render_ta_screener_alerts(scan_digest, strategy_label="pump/dump")
        st.dataframe(
            [_scan_row_display(r, market="india") for r in rows],
            width='stretch',
            hide_index=True,
        )
        pick = st.selectbox(
            "Drill into", ["—"] + [f"{r['symbol']} {r['side']}" for r in rows], key="pdp_i_pick",
        )
        if st.button("Open India analysis", key="pdp_i_drill") and pick != "—":
            idx = [f"{r['symbol']} {r['side']}" for r in rows].index(pick)
            st.session_state["pdp_india_last"] = rows[idx]["analysis"]
    last = st.session_state.get("pdp_india_last")
    if last:
        _render_india_analysis(last, provider, model, api_key)


def render_pump_dump_tab():
    st.caption(
        "Detect **pre-pump** and **pre-dump** setups before the move. "
        "A **signal** = one rule turning 🟢 green. **Min active signals** filters the scan table; "
        "for trading aim for **≥3 green signals** + **confluence score ≥55**. See **🚀 Starter Guide** tab."
    )
    provider, model, api_key = render_ai_config(
        "pump_dump_predictor",
        caption="AI View validates setups for either market.",
    )
    india_tab, crypto_tab = st.tabs(["🇮🇳 India Scalping System", "🪙 Crypto"])
    with india_tab:
        _render_india_section(provider, model, api_key)
    with crypto_tab:
        _render_crypto_section(provider, model, api_key)

    # Ask AI snapshot
    parts = []
    cl = st.session_state.get("pdp_crypto_last")
    il = st.session_state.get("pdp_india_last")
    if il:
        parts.extend([_india_prompt(il, "LONG"), _india_prompt(il, "SHORT")])
    if cl:
        parts.extend([_crypto_prompt(cl, "LONG"), _crypto_prompt(cl, "SHORT")])
    for r in (st.session_state.get("pdp_india_rows") or [])[:10]:
        parts.append(f"IN {r['symbol']} {r['side']}: {r['score']} — {r['verdict']}")
    for r in (st.session_state.get("pdp_crypto_rows") or [])[:10]:
        parts.append(f"CR {r['symbol']} {r['side']}: {r['score']} — {r['verdict']}")
    if parts:
        st.session_state["pdp_ask_ai_snapshot"] = "\n\n".join(parts)

    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("pump_dump_predictor")
