"""
Unified run summary — score /10, verdict, action, trade plan (hold, SL, TP, exit).
"""

from __future__ import annotations

import html
import re


# Verdict → single user-facing signal bucket (one label per card, no WAIT + LONG)
TRADE_VERDICTS = frozenset({
    "BUY", "SELL", "STRONG BUY", "TOP PICK", "DEPLOY", "SEASONAL BUY",
    "SELL / AVOID",
})
NO_TRADE_VERDICTS = frozenset({
    "WAIT", "NO MATCH", "SKIP", "AVOID", "REJECT", "WATCH", "NO SETUP",
    "NO EDGE", "MIXED", "NO DATA", "HOLD",
})
WATCH_VERDICTS = frozenset({"LEAN", "WATCHLIST", "OPTIMIZE", "SELECTIVE"})
ERROR_VERDICTS = frozenset({"ERROR"})


def classify_signal(verdict: str) -> str:
    v = (verdict or "").upper().strip()
    if v in ERROR_VERDICTS:
        return "error"
    if v in TRADE_VERDICTS:
        return "trade"
    if v in WATCH_VERDICTS:
        return "watch"
    if v in NO_TRADE_VERDICTS:
        return "no_trade"
    return "no_trade"


def build_recommendation(verdict: str, score: float, tab: str = "", direction: str = "") -> tuple[str, str]:
    """Return (headline, plain-English meaning)."""
    v = (verdict or "").upper().strip()
    d = (direction or "—").upper()
    tab_l = (tab or "").lower()
    if v == "ERROR":
        return (
            "⚠️ Run failed — not a trading signal",
            "This check could not finish (data, token, or API issue). Fix the setup and re-run.",
        )
    if v == "NO MATCH":
        return (
            "➖ No entry signal (screener)",
            "Your screener rules did not match the latest candle. This is normal — it means “no trade”, not an error.",
        )
    if v == "NO SETUP":
        return (
            "➖ No setup detected",
            "The engine found nothing actionable on this ticker/timeframe (e.g. no gap, no pattern).",
        )
    if v in ("REJECT", "SKIP"):
        return (
            "❌ Do not trade this configuration",
            "Backtest or scan quality is below the bar — avoid live capital on this combo.",
        )
    if v == "WAIT":
        return (
            "⏸️ Wait — stay flat",
            "Signals are mixed or weak. No clear entry; wait for a stronger score or aligned engines.",
        )
    if v in ("AVOID", "NO EDGE"):
        return (
            "⛔ No edge — avoid",
            "Not enough statistical or directional support to justify a position.",
        )
    if v == "STRONG BUY":
        return (
            f"✅ Strong buy — go LONG (score {score:.1f}/10)",
            "Multiple engines lean bullish with a solid average score. Use the trade plan below if you enter.",
        )
    if v == "BUY":
        return (
            f"✅ Buy — go LONG (score {score:.1f}/10)",
            "Bullish bias with acceptable risk/reward. Confirm on a higher timeframe before full size.",
        )
    if v in ("SELL", "SELL / AVOID"):
        return (
            f"🔻 Sell / reduce exposure (score {score:.1f}/10)",
            "Bearish bias — consider shorts or trimming longs per the plan below.",
        )
    if v == "DEPLOY":
        return (
            f"✅ Deploy — backtest edge (score {score:.1f}/10)",
            "Historical metrics support this strategy; still use stops and position sizing.",
        )
    if v == "TOP PICK":
        return (
            f"⭐ Top pick — LONG bias (score {score:.1f}/10)",
            "Best-ranked combo in the scan by return/risk metrics.",
        )
    if v == "SEASONAL BUY":
        return (
            f"🗓️ Seasonal long (score {score:.1f}/10)",
            "Calendar seasonality favours a long bias for the active month window.",
        )
    if v == "WATCHLIST":
        return (
            f"👀 Watchlist only (score {score:.1f}/10)",
            "Interesting but not a full-size entry — monitor for confirmation.",
        )
    if v == "OPTIMIZE":
        return (
            f"🔧 Optimize before trading (score {score:.1f}/10)",
            "Promising backtest but tune parameters or filters before going live.",
        )
    if v == "LEAN":
        side = "bullish" if d == "LONG" or score >= 5 else "bearish"
        return (
            f"↗️ Mild {side} lean — not a full signal",
            "Directional hint only; wait for a BUY/SELL verdict or higher confidence.",
        )
    if v == "WATCH":
        return (
            f"👁️ Monitor (score {score:.1f}/10)",
            "Structure forming — watch for trigger; no entry yet.",
        )
    if v == "SELECTIVE":
        return (
            f"🗓️ Selective seasonal exposure (score {score:.1f}/10)",
            "Seasonality is mixed — only small or tactical size if you participate.",
        )
    if "screener" in tab_l and v == "BUY":
        return (
            f"✅ Screener BUY on {d or 'LONG'}",
            "Entry rules fired on the latest bar — confirm volume and higher-TF trend.",
        )
    return (
        f"ℹ️ {verdict} (score {score:.1f}/10)",
        "Review the details below; no automatic trade is implied unless marked as Buy/Sell.",
    )


def enrich_summary(s: dict) -> dict:
    """Back-fill recommendation fields on summaries built before this helper existed."""
    if not s:
        return s
    out = dict(s)
    verdict = out.get("verdict", "HOLD")
    score = float(out.get("score", 5.0) or 5.0)
    plan = out.get("trade_plan") or {}
    sig = out.get("signal_type") or classify_signal(verdict)
    out["signal_type"] = sig
    if not out.get("recommendation"):
        rec, meaning = build_recommendation(
            verdict, score, out.get("tab", ""), plan.get("direction", ""),
        )
        out["recommendation"] = rec
        out["meaning"] = meaning
    if "show_trade_plan" not in out:
        out["show_trade_plan"] = sig == "trade"
    return out


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def _score_color(score: float) -> str:
    if score >= 8:
        return "#10b981"
    if score >= 6:
        return "#34d399"
    if score >= 4:
        return "#f59e0b"
    if score >= 2:
        return "#f97316"
    return "#ef4444"


def holding_period_for_timeframe(timeframe: str, style: str = "") -> str:
    """Expected holding window tied to chart interval."""
    tf = (timeframe or "1d").lower().strip()
    if "seasonal" in tf:
        return "Hold through the favourable calendar month (≈3–5 weeks)"
    if style == "Scalping" or tf == "1m":
        return "15–45 min (scalp; exit before session close)"
    mapping = {
        "5m": "1–3 hours intraday (exit same session)",
        "15m": "2–6 hours intraday (same-day hold)",
        "30m": "4–12 hours (intraday, max overnight)",
        "1h": "1–5 trading days (short swing)",
        "4h": "3–15 trading days (swing)",
        "1d": "2–6 weeks (position swing)",
        "1w": "1–3 months (long swing)",
    }
    return mapping.get(tf, "1–5 trading days (align with chart TF)")


def default_sl_tp_for_timeframe(timeframe: str) -> tuple[float, float]:
    tf = (timeframe or "1d").lower()
    defaults = {
        "1m": (0.4, 0.8), "5m": (0.7, 1.4), "15m": (1.0, 2.0),
        "30m": (1.3, 2.6), "1h": (1.8, 3.6), "4h": (2.5, 5.0), "1d": (3.5, 7.0),
    }
    return defaults.get(tf, (2.0, 4.0))


def make_trade_plan(
    *,
    direction: str = "",
    timeframe: str = "",
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    expected_profit_pct: float | None = None,
    confidence_pct: float | None = None,
    style: str = "",
    exit_rule: str = "",
    max_hold_exit: str = "",
) -> dict:
    holding = holding_period_for_timeframe(timeframe, style)
    dsl, dtp = default_sl_tp_for_timeframe(timeframe)
    sl = float(stop_loss_pct if stop_loss_pct is not None else dsl)
    tp = float(take_profit_pct if take_profit_pct is not None else dtp)
    exp = float(expected_profit_pct if expected_profit_pct is not None else tp)
    if not exit_rule:
        dir_u = (direction or "").upper()
        if dir_u in ("LONG", "BUY"):
            exit_rule = (
                f"Take profit at +{tp:.1f}% (scale 50% at TP1, trail rest). "
                f"Stop loss at -{sl:.1f}%. Exit if thesis breaks (structure/RSI flip)."
            )
        elif dir_u in ("SHORT", "SELL"):
            exit_rule = (
                f"Cover at +{tp:.1f}% profit (lower prices). "
                f"Stop at -{sl:.1f}% (higher prices). Exit on bullish reversal candle."
            )
        else:
            exit_rule = f"Stay flat until directional edge ≥6/10 with defined SL {sl:.1f}% / TP {tp:.1f}%."
    if not max_hold_exit:
        max_hold_exit = f"Close position if TP not reached within {holding.split('(')[0].strip()}."
    return {
        "direction": direction or "—",
        "holding_period": holding,
        "stop_loss_pct": round(sl, 2),
        "take_profit_pct": round(tp, 2),
        "expected_profit_pct": round(exp, 2),
        "confidence_pct": round(confidence_pct, 0) if confidence_pct is not None else None,
        "exit_rule": exit_rule,
        "max_hold_exit": max_hold_exit,
    }


def _minimal_trade_plan(timeframe: str = "") -> dict:
    return make_trade_plan(
        timeframe=timeframe,
        direction="—",
        exit_rule="",
        max_hold_exit="",
    )


def format_action_with_plan(verdict: str, plan: dict, extra: str = "") -> str:
    d = plan.get("direction", "—")
    conf = plan.get("confidence_pct")
    conf_s = f", conf {conf:.0f}%" if conf is not None else ""
    base = (
        f"{verdict}: {d}{conf_s} · Hold {plan.get('holding_period', '—')} · "
        f"SL -{plan.get('stop_loss_pct', 0):.1f}% · TP +{plan.get('take_profit_pct', 0):.1f}% · "
        f"Expected +{plan.get('expected_profit_pct', 0):.1f}%"
    )
    return f"{base}. {extra}".strip().rstrip(".")


def make_summary(
    *,
    ticker: str,
    timeframe: str = "",
    strategy: str = "",
    tab: str = "",
    score: float = 5.0,
    verdict: str = "HOLD",
    action: str = "",
    summary: str = "",
    reasons: list[str] | None = None,
    trade_plan: dict | None = None,
    signal_type: str | None = None,
    recommendation: str | None = None,
    meaning: str | None = None,
    show_trade_plan: bool | None = None,
) -> dict:
    sig = signal_type or classify_signal(verdict)
    score_r = round(_clamp(score), 1)
    if sig == "trade":
        plan = trade_plan or make_trade_plan(timeframe=timeframe)
        if not action:
            action = format_action_with_plan(verdict, plan)
    else:
        plan = trade_plan if trade_plan is not None else _minimal_trade_plan(timeframe)
        if sig == "error" and not action:
            action = "Re-run with a valid ticker, token, or date range."
        elif sig == "no_trade" and not action:
            action = "No position recommended — wait for a clear Buy/Sell signal."
        elif sig == "watch" and not action:
            action = "Monitor only — reduce size or wait for confirmation."
    rec, mean = build_recommendation(
        verdict, score_r, tab, plan.get("direction", ""),
    )
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "strategy": strategy,
        "tab": tab,
        "score": score_r,
        "verdict": verdict,
        "signal_type": sig,
        "recommendation": recommendation or rec,
        "meaning": meaning or mean,
        "show_trade_plan": show_trade_plan if show_trade_plan is not None else (sig == "trade"),
        "action": action,
        "summary": summary,
        "reasons": reasons or [],
        "trade_plan": plan,
    }


def _strip_time_stop_prefix(text: str) -> str:
    return re.sub(r"^time stop:\s*", "", (text or "").strip(), flags=re.IGNORECASE)


def render_run_summary(s: dict, *, compact: bool = False) -> None:
    """Render a single run summary card — one clear recommendation, trade plan only when actionable."""
    if not s:
        return
    s = enrich_summary(s)
    score = float(s.get("score", 5.0) or 5.0)
    ticker = s.get("ticker", "")
    tf = s.get("timeframe", "")
    strat = s.get("strategy", "")
    label = " | ".join(x for x in [ticker, tf, strat] if x)
    tab = s.get("tab", "")
    sig = s.get("signal_type", "no_trade")
    recommendation = s.get("recommendation", "")
    meaning = s.get("meaning", "")
    action = s.get("action", "")
    summary = s.get("summary", "")
    reasons = s.get("reasons", [])
    plan = s.get("trade_plan") or {}
    show_plan = bool(s.get("show_trade_plan")) and sig == "trade"

    with st.container(border=True):
        hdr_l, hdr_r = st.columns([5, 1])
        with hdr_l:
            cap = f"Run Summary · {tab}" if tab else "Run Summary"
            st.caption(cap)
            if label:
                st.markdown(f"**{html.escape(label)}**")
        with hdr_r:
            st.metric("Score", f"{score:.1f}/10")

        if sig == "trade":
            st.success(recommendation)
        elif sig == "error":
            st.error(recommendation)
        elif sig == "watch":
            st.warning(recommendation)
        else:
            st.info(recommendation)

        if meaning:
            st.caption(meaning)

        if summary:
            st.markdown(summary)

        if show_plan:
            hold = (plan.get("holding_period") or "—")[:48]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Hold time", hold)
            c2.metric("Stop loss", f"-{plan.get('stop_loss_pct', 0):.1f}%")
            c3.metric("Take profit", f"+{plan.get('take_profit_pct', 0):.1f}%")
            conf = plan.get("confidence_pct")
            exp = f"+{plan.get('expected_profit_pct', 0):.1f}%"
            if conf is not None:
                c4.metric("Expected profit", exp, delta=f"conf {conf:.0f}%")
            else:
                c4.metric("Expected profit", exp)
            exit_rule = (plan.get("exit_rule") or "").strip()
            if exit_rule:
                st.markdown(f"**Exit rule:** {exit_rule}")
            max_hold = _strip_time_stop_prefix(plan.get("max_hold_exit") or "")
            if max_hold:
                st.markdown(f"**Time stop:** {max_hold}")
            if action:
                st.markdown(f"**Trade plan:** {action}")
        else:
            if action:
                st.markdown(f"**What to do:** {action}")

        if reasons:
            with st.expander("Why this result?", expanded=not compact):
                for r in reasons[:6]:
                    st.markdown(f"- {r}")


def render_run_digest(
    summaries: list[dict],
    *,
    title: str = "📋 Run Summary Digest",
    group_filter: bool = False,
) -> None:
    """Compact table of all run summaries for a multi-ticker / multi-TF scan."""
    if not summaries:
        return
    enriched = [enrich_summary(s) for s in summaries]
    st.markdown(f"### {title}")
    st.caption(
        "One **recommendation** per row — no mixed WAIT + LONG. "
        "Trade plan columns appear only for Buy/Sell signals."
    )

    if group_filter:
        tabs = st.tabs(["✅ Actionable", "⏸️ No signal", "⚠️ Errors", "📋 All"])
        buckets = {
            "✅ Actionable": [s for s in enriched if s.get("signal_type") == "trade"],
            "⏸️ No signal": [s for s in enriched if s.get("signal_type") in ("no_trade", "watch")],
            "⚠️ Errors": [s for s in enriched if s.get("signal_type") == "error"],
            "📋 All": enriched,
        }
        for tab, bucket in zip(tabs, buckets.values()):
            with tab:
                _render_digest_table(bucket)
        actionable = buckets["✅ Actionable"]
        if actionable:
            top = max(actionable, key=lambda x: x.get("score", 0))
            _render_digest_highlight(top)
        else:
            st.info("No actionable Buy/Sell signals in this run — review **No signal** tab for context.")
        return

    _render_digest_table(enriched)
    actionable = [s for s in enriched if s.get("signal_type") == "trade"]
    top = max(actionable or enriched, key=lambda x: x.get("score", 0))
    _render_digest_highlight(top)


def _render_digest_table(summaries: list[dict]) -> None:
    if not summaries:
        st.caption("Nothing in this group.")
        return
    rows = []
    for s in summaries:
        p = s.get("trade_plan") or {}
        trade = s.get("signal_type") == "trade"
        rows.append({
            "Ticker": s.get("ticker", ""),
            "TF": s.get("timeframe", ""),
            "Engine": s.get("tab", "") or "—",
            "Score": s.get("score", 0),
            "Recommendation": (s.get("recommendation") or s.get("verdict", ""))[:55],
            "SL %": p.get("stop_loss_pct") if trade else None,
            "TP %": p.get("take_profit_pct") if trade else None,
            "Exp %": p.get("expected_profit_pct") if trade else None,
        })
    st.dataframe(rows, width='stretch', hide_index=True)


def _render_digest_highlight(top: dict) -> None:
    top = enrich_summary(top)
    tp = top.get("trade_plan") or {}
    if top.get("signal_type") == "trade":
        st.success(
            f"**Best actionable:** {top.get('ticker')} | {top.get('timeframe')} "
            f"({top.get('tab')}) — score **{top.get('score')}/10**. "
            f"{top.get('recommendation', '')} "
            f"SL -{tp.get('stop_loss_pct', 0):.1f}% · TP +{tp.get('take_profit_pct', 0):.1f}% · "
            f"Expected +{tp.get('expected_profit_pct', 0):.1f}%."
        )
    else:
        st.info(
            f"**Highest score (not a trade signal):** {top.get('ticker')} | {top.get('timeframe')} — "
            f"{top.get('recommendation', top.get('verdict', ''))}"
        )


# ── Summarizers ──────────────────────────────────────────────────────────────


def summarize_backtest_metrics(
    metrics: dict, ticker: str, timeframe: str, strategy: str = ""
) -> dict:
    ret = float(metrics.get("total_return_pct", 0) or 0)
    sharpe = float(metrics.get("sharpe_ratio", 0) or 0)
    dd = abs(float(metrics.get("max_drawdown_pct", 0) or 0))
    pf = float(metrics.get("profit_factor", 0) or 0)
    wr = float(metrics.get("win_rate_pct", 0) or 0)
    n = int(metrics.get("n_trades", 0) or 0)
    avg_win = float(metrics.get("avg_win_pct", 0) or 0)

    score = 5.0
    score += _clamp(ret / 8, -2.5, 2.5)
    score += _clamp(sharpe * 1.2, -2, 2)
    score -= _clamp(dd / 18, 0, 2.5)
    score += _clamp((pf - 1) * 1.8, -2, 2)
    score += _clamp((wr - 45) / 25, -1, 1)
    if n < 5:
        score -= 1.5
    elif n < 15:
        score -= 0.5
    score = _clamp(score)

    dsl, dtp = default_sl_tp_for_timeframe(timeframe)
    sl = min(dsl * 1.5, dd / 2) if dd > 0 else dsl
    tp = avg_win if avg_win > 0 else dtp
    exp = min(tp, ret / max(n, 1) * 2) if ret > 0 and n else tp
    direction = "LONG" if ret >= 0 else "SHORT"

    if score >= 7.5 and ret > 0 and sharpe > 0.7 and pf > 1.2:
        verdict = "DEPLOY"
        summary = "Backtest shows solid edge — deploy with plan below."
        action = ""
    elif score >= 5.5:
        verdict = "OPTIMIZE"
        summary = "Promising backtest — optimize parameters before live sizing."
        action = "Paper-trade or reduce size until Sharpe, win rate, and drawdown improve."
    else:
        verdict = "REJECT"
        summary = "Weak backtest — historical metrics do not support live trading."
        action = "Do not deploy — try different rules, timeframe, or filters in Strategy Builder."

    plan = make_trade_plan(
        direction=direction if verdict == "DEPLOY" else "—",
        timeframe=timeframe,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=exp,
        confidence_pct=wr,
        exit_rule=(
            f"Backtest avg win {avg_win:.1f}% — target +{tp:.1f}%, stop -{sl:.1f}%. "
            f"Exit if drawdown exceeds historical max {dd:.1f}%."
        ),
    ) if verdict == "DEPLOY" else None

    return make_summary(
        ticker=ticker, timeframe=timeframe, strategy=strategy, tab="Strategy Backtest",
        score=score, verdict=verdict, action=action, summary=summary, trade_plan=plan,
        reasons=[
            f"Return {ret:.1f}%, Sharpe {sharpe:.2f}, {n} trades, win rate {wr:.0f}%.",
            f"Profit factor {pf:.2f}, max DD {dd:.1f}%.",
        ],
    )


def summarize_multi_combo_row(row: dict) -> dict:
    ticker = str(row.get("Ticker", ""))
    tf = str(row.get("Timeframe", ""))
    strat = str(row.get("Strategy", ""))
    status = str(row.get("Status", ""))
    if status not in ("✅ OK", "✅ SCAN"):
        return summarize_error(ticker, tf, status, tab="Multi-Combo Scanner", strategy=strat)

    ret = float(row.get("Return %", 0) or 0)
    sharpe = float(row.get("Sharpe", 0) or 0)
    dd = abs(float(row.get("Max DD %", 0) or 0))
    pf = float(row.get("Profit Factor", 0) or 0)
    wr = float(row.get("Win Rate %", 0) or 0)
    n = int(row.get("Trades", 0) or 0)
    phase = str(row.get("Phase", "") or "")
    conf = float(row.get("Confidence", 0) or 0)

    score = 5.0 + _clamp(ret / 10, -2, 3) + _clamp(sharpe, -1.5, 2) - _clamp(dd / 20, 0, 2)
    score += _clamp((pf - 1) * 1.5, -1.5, 1.5)
    if status == "✅ SCAN":
        score += _clamp(conf / 25, 0, 2)
        if phase in ("strong_bull", "strong_bear", "ENTRY_READY", "BUY_SIGNAL", "SELL_SIGNAL"):
            score += 1.0
    if n < 3 and status != "✅ SCAN":
        score -= 1
    score = _clamp(score)

    dsl, dtp = default_sl_tp_for_timeframe(tf)
    sl = min(dsl * 1.5, max(dsl, dd / 2))
    tp = dtp if ret <= 0 else min(ret / max(n, 1) * 3, dtp * 2) if n else dtp
    tp = max(tp, dsl * 1.5)
    direction = "LONG" if ret > 0 else "SHORT"

    if score >= 7 and ret > 0:
        verdict = "TOP PICK"
        action = ""
    elif score >= 5:
        verdict = "WATCHLIST"
        action = "Add to watchlist — backtest is decent but not a top-tier pick."
        direction = "—"
    else:
        verdict = "SKIP"
        direction = "—"
        action = "Skip this combo — return or risk metrics are below threshold."

    plan = make_trade_plan(
        direction=direction,
        timeframe=tf,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=tp * 0.85,
        confidence_pct=wr,
    ) if verdict == "TOP PICK" else None
    return make_summary(
        ticker=ticker, timeframe=tf, strategy=strat, tab="Multi-Combo Scanner",
        score=score, verdict=verdict, action=action, trade_plan=plan,
        summary=f"Backtest return {ret:.1f}%, Sharpe {sharpe:.2f}, {n} trades.",
        reasons=[f"Win rate {wr:.0f}%, max DD {dd:.1f}%, PF {pf:.2f}."],
    )


def summarize_sentiment_row(row: dict) -> dict:
    ticker = str(row.get("Ticker", ""))
    tf = str(row.get("Timeframe", ""))
    raw = float(row.get("Score", 0) or 0)
    score = _clamp((raw + 100) / 20)
    sig = str(row.get("Trade Signal", "WAIT"))
    conf = int(row.get("trade_confidence", 0) or 0)
    rating = str(row.get("Rating", ""))
    sl = float(row.get("SL %", 0) or row.get("sl_pct", 0) or 0)
    tp = float(row.get("TP %", 0) or row.get("tp_pct", 0) or 0)
    if sl <= 0 or tp <= 0:
        sl, tp = default_sl_tp_for_timeframe(tf)

    if sig == "BUY" and score >= 6:
        verdict, direction, action = "BUY", "LONG", ""
    elif sig == "SELL" and score <= 4:
        verdict, direction, action = "SELL", "SHORT", ""
    elif abs(raw) < 15:
        verdict, direction = "WAIT", "—"
        action = "Stay flat — sentiment is near neutral; wait for a clearer BUY/SELL signal."
    else:
        verdict, direction = "LEAN", "LONG" if raw > 0 else "SHORT"
        action = (
            f"Mild {'bullish' if raw > 0 else 'bearish'} lean only — "
            "not a full entry; wait for score ≥6 (buy) or ≤4 (sell)."
        )

    plan = make_trade_plan(
        direction=direction,
        timeframe=tf,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=tp * 0.9,
        confidence_pct=conf or None,
        exit_rule=(
            f"ATR-based plan: SL -{sl:.1f}%, TP +{tp:.1f}%. "
            f"Exit if ADX weakens or score crosses zero."
        ),
    ) if verdict in ("BUY", "SELL") else None

    insights = row.get("Insights", [])
    reasons = insights[:3] if isinstance(insights, list) else [str(insights)]

    return make_summary(
        ticker=ticker, timeframe=tf, tab="Sentiment Analyzer",
        score=score, verdict=verdict, action=action, trade_plan=plan,
        summary=f"{rating} (sentiment {raw:+.0f}).",
        reasons=reasons,
    )


def summarize_price_action(analysis: dict, symbol: str, timeframe: str) -> dict:
    bias = str(analysis.get("overall_bias", "NEUTRAL"))
    bias_score = float(analysis.get("bias_score", 0) or 0)
    setups = analysis.get("trade_setups", []) or []
    best_conf = max((s.get("confidence", 0) for s in setups), default=0)
    rsi = float(analysis.get("rsi", {}).get("current_rsi", 50) or 50)
    vol = analysis.get("volume") or (analysis.get("adv_indicators") or {}).get("volume", {})
    vwap = (analysis.get("adv_indicators") or {}).get("vwap", {})
    approaching = analysis.get("approaching", {})

    score = 5.0 + _clamp(bias_score / 15, -3, 3) + _clamp((best_conf - 50) / 20, -1, 2)
    if vol.get("spike"):
        score += 0.3
    if approaching.get("count", 0) > 0 and not setups:
        score = max(score, 6.2)
    if "STRONG BULLISH" in bias:
        score += 1
    elif "STRONG BEARISH" in bias:
        score -= 1
    score = _clamp(score)

    top = max(setups, key=lambda s: s.get("confidence", 0)) if setups else None
    if top and best_conf >= 60:
        direction = top.get("direction", "LONG")
        sl = float(top.get("sl_pct", 0) or 0)
        tp = float(top.get("tp1_pct", 0) or top.get("tp2_pct", 0) or 0)
        style = top.get("style", "")
        if sl <= 0 or tp <= 0:
            sl, tp = default_sl_tp_for_timeframe(timeframe)
        if direction == "LONG" and score >= 6:
            verdict = "BUY"
        elif direction == "SHORT" and score <= 4:
            verdict = "SELL"
        else:
            verdict = "WAIT"
            direction = "—"
    else:
        direction = "LONG" if score >= 6.5 else "SHORT" if score <= 3.5 else "—"
        sl, tp = default_sl_tp_for_timeframe(timeframe)
        style = ""
        verdict = "BUY" if score >= 6.5 else "SELL" if score <= 3.5 else "AVOID"

    plan = make_trade_plan(
        direction=direction,
        timeframe=timeframe,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=tp * (best_conf / 100) if best_conf else tp * 0.8,
        confidence_pct=best_conf or None,
        style=style,
        exit_rule=(
            f"TP1 +{tp:.1f}% (book partial), trail to TP2 if offered. "
            f"SL -{sl:.1f}%. Invalidate on bias flip to {bias}."
        ) if top else None,
    )

    pa_action = ""
    if verdict in ("AVOID", "WAIT"):
        pa_action = (
            "No trade — price action lacks a high-confidence setup on this timeframe."
            if verdict == "WAIT"
            else "Avoid — bias does not support a directional entry."
        )
        plan = None

    if verdict in ("AVOID", "WAIT") and approaching.get("count", 0) > 0:
        verdict = "WATCHLIST"
        pa_action = approaching["alerts"][0]
        plan = None

    reasons = [
        f"Best setup confidence {best_conf}%." if setups else "No setup — using TF defaults.",
        f"RSI {rsi:.0f}.",
    ]
    if vol:
        reasons.append(f"Volume {vol.get('ratio', 1)}× avg ({vol.get('label', 'NORMAL')}).")
    if vwap.get("level") is not None:
        reasons.append(
            f"VWAP {vwap.get('position', 'NEUTRAL').split('(')[0].strip()} "
            f"({vwap.get('distance_pct', 0):+.2f}%)."
        )
    if approaching.get("alerts") and verdict == "WATCHLIST":
        reasons.append(approaching["alerts"][0])

    return make_summary(
        ticker=symbol, timeframe=timeframe, tab="Price Action",
        score=score, verdict=verdict, action=pa_action, trade_plan=plan,
        summary=f"Bias {bias} on {timeframe}.",
        reasons=reasons,
    )


def summarize_fakeout_4h(analysis: dict, symbol: str) -> dict:
    """Score card for 5min–4hr Breakout-Fakeout screener."""
    sc = analysis.get("screener") or analysis.get("live_setup") or {}
    phase = sc.get("primary_phase", "NO_DATA")
    label = sc.get("primary_label", "")
    setups = sc.get("setups") or []
    plan = sc.get("trade_plan")

    score = 5.0
    priority = sc.get("priority", 0)
    score += min(3.0, priority / 30)

    if phase == "ENTRY_READY" and plan:
        score += 2.0
        verdict = "BUY" if plan.get("direction", "").lower() == "long" else "SELL"
        direction = "LONG" if verdict == "BUY" else "SHORT"
        risk = plan.get("risk_pct") or (
            round(abs(plan["entry"] - plan["stop_loss"]) / plan["entry"] * 100, 2)
            if plan.get("entry") else 0
        )
        reward = plan.get("reward_pct") or (
            round(abs(plan["take_profit"] - plan["entry"]) / plan["entry"] * 100, 2)
            if plan.get("entry") else 0
        )
        action = (
            f"FAKEOUT {plan['direction'].upper()} ready — "
            f"SL -{risk:.2f}% · TP +{reward:.2f}% · R:R {plan.get('rr_ratio', 2):.1f}"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan["entry"],
            "stop_loss": plan["stop_loss"],
            "take_profit": plan["take_profit"],
            "stop_loss_pct": risk,
            "take_profit_pct": reward,
            "expected_profit_pct": reward,
            "hold_duration": "1–3 hours (intraday fakeout)",
        }
    elif phase == "BREAKOUT_ACTIVE":
        verdict, direction = "WATCHLIST", setups[0].get("direction", "—") if setups else "—"
        action = sc.get("message", "Breakout active — fakeout re-entry approaching.")
        score += 1.0
        trade_plan = None
        if plan:
            risk = plan.get("risk_pct") or (
                round(abs(plan["entry"] - plan["stop_loss"]) / plan["entry"] * 100, 2)
                if plan.get("entry") else 0
            )
            reward = plan.get("reward_pct") or (
                round(abs(plan["take_profit"] - plan["entry"]) / plan["entry"] * 100, 2)
                if plan.get("entry") else 0
            )
            trade_plan = {
                "direction": plan.get("direction", "").upper(),
                "entry_price": plan["entry"],
                "stop_loss": plan["stop_loss"],
                "take_profit": plan["take_profit"],
                "stop_loss_pct": risk,
                "take_profit_pct": reward,
                "expected_profit_pct": reward,
                "hold_duration": "Pending fakeout re-entry",
            }
    elif phase in ("APPROACHING_HIGH", "APPROACHING_LOW"):
        verdict, direction = "WATCHLIST", setups[0].get("direction", "—") if setups else "—"
        action = setups[0].get("hint", "Price approaching range edge — breakout watch.") if setups else label
        score += 0.8
        trade_plan = None
    elif phase == "MONITORING":
        verdict, direction = "WAIT", "—"
        action = "Inside range — no approaching setup yet."
        trade_plan = None
    elif phase in ("WAIT_RANGE", "NO_RANGE"):
        verdict, direction = "WAIT", "—"
        action = sc.get("message", "Range not ready — scan again later.")
        trade_plan = None
    elif phase == "SESSION_CLOSED":
        verdict, direction = "WAIT", "—"
        action = "Market session closed."
        trade_plan = None
    else:
        verdict, direction = "NO SETUP", "—"
        action = sc.get("message", "No setup detected.")
        trade_plan = None

    score = _clamp(score)
    reasons = [
        f"Phase: {phase} — {label}",
        f"Price vs range: {sc.get('price_vs_range', 'N/A')}.",
        f"{len(setups)} setup(s) detected.",
    ]
    if sc.get("range_high") is not None:
        range_note = (
            "4H IST range (09:15–13:15)"
            if sc.get("session_mode") == "india"
            else "4H NY range"
        )
        reasons.append(f"{range_note}: {sc['range_low']:.2f} – {sc['range_high']:.2f}.")

    return make_summary(
        ticker=symbol,
        timeframe="5m",
        tab="5min-4hr Screener",
        score=score,
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {label}",
        reasons=reasons,
    )


def summarize_fakeout_15m(analysis: dict, symbol: str) -> dict:
    """Score card for 1min–15min Breakout-Fakeout screener."""
    sc = analysis.get("screener") or analysis.get("live_setup") or {}
    phase = sc.get("primary_phase", "NO_DATA")
    label = sc.get("primary_label", "")
    setups = sc.get("setups") or []
    plan = sc.get("trade_plan")

    score = 5.0
    priority = sc.get("priority", 0)
    score += min(3.0, priority / 30)

    if phase == "ENTRY_READY" and plan:
        score += 2.0
        verdict = "BUY" if plan.get("direction", "").lower() == "long" else "SELL"
        direction = "LONG" if verdict == "BUY" else "SHORT"
        risk = plan.get("risk_pct") or (
            round(abs(plan["entry"] - plan["stop_loss"]) / plan["entry"] * 100, 2)
            if plan.get("entry") else 0
        )
        reward = plan.get("reward_pct") or (
            round(abs(plan["take_profit"] - plan["entry"]) / plan["entry"] * 100, 2)
            if plan.get("entry") else 0
        )
        action = (
            f"FAKEOUT {plan['direction'].upper()} ready — "
            f"SL -{risk:.2f}% · TP +{reward:.2f}% · R:R {plan.get('rr_ratio', 2):.1f}"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan["entry"],
            "stop_loss": plan["stop_loss"],
            "take_profit": plan["take_profit"],
            "stop_loss_pct": risk,
            "take_profit_pct": reward,
            "expected_profit_pct": reward,
            "hold_duration": "15–60 min (scalp fakeout)",
        }
    elif phase == "BREAKOUT_ACTIVE":
        verdict, direction = "WATCHLIST", setups[0].get("direction", "—") if setups else "—"
        action = sc.get("message", "Breakout active — fakeout re-entry approaching.")
        score += 1.0
        trade_plan = None
        if plan:
            risk = plan.get("risk_pct") or (
                round(abs(plan["entry"] - plan["stop_loss"]) / plan["entry"] * 100, 2)
                if plan.get("entry") else 0
            )
            reward = plan.get("reward_pct") or (
                round(abs(plan["take_profit"] - plan["entry"]) / plan["entry"] * 100, 2)
                if plan.get("entry") else 0
            )
            trade_plan = {
                "direction": plan.get("direction", "").upper(),
                "entry_price": plan["entry"],
                "stop_loss": plan["stop_loss"],
                "take_profit": plan["take_profit"],
                "stop_loss_pct": risk,
                "take_profit_pct": reward,
                "expected_profit_pct": reward,
                "hold_duration": "Pending fakeout re-entry",
            }
    elif phase in ("APPROACHING_HIGH", "APPROACHING_LOW"):
        verdict, direction = "WATCHLIST", setups[0].get("direction", "—") if setups else "—"
        action = setups[0].get("hint", "Price approaching range edge — breakout watch.") if setups else label
        score += 0.8
        trade_plan = None
    elif phase == "MONITORING":
        verdict, direction = "WAIT", "—"
        action = "Inside range — no approaching setup yet."
        trade_plan = None
    elif phase in ("WAIT_RANGE", "NO_RANGE"):
        verdict, direction = "WAIT", "—"
        action = sc.get("message", "Range not ready — scan again later.")
        trade_plan = None
    elif phase == "SESSION_CLOSED":
        verdict, direction = "WAIT", "—"
        action = "Market session closed."
        trade_plan = None
    else:
        verdict, direction = "NO SETUP", "—"
        action = sc.get("message", "No setup detected.")
        trade_plan = None

    score = _clamp(score)
    reasons = [
        f"Phase: {phase} — {label}",
        f"Price vs range: {sc.get('price_vs_range', 'N/A')}.",
        f"{len(setups)} setup(s) detected.",
    ]
    if sc.get("range_high") is not None:
        range_note = (
            "15M IST range (09:15–09:30)"
            if sc.get("session_mode") == "india"
            else "15M NY range"
        )
        reasons.append(f"{range_note}: {sc['range_low']:.2f} – {sc['range_high']:.2f}.")

    return make_summary(
        ticker=symbol,
        timeframe="1m",
        tab="1min-15min Breakout scanner",
        score=score,
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {label}",
        reasons=reasons,
    )


def summarize_mtf_scanner(analysis: dict, symbol: str) -> dict:
    """Score card for Institutional MTF Scanner."""
    conf = analysis.get("confluence") or {}
    tf_results = analysis.get("timeframes") or {}
    avg_score = float(conf.get("avg_score", 50) or 50)
    avg_conf = float(conf.get("avg_confidence", 0) or 0)
    verdict_type = conf.get("verdict_type", "mixed")
    verdict_text = conf.get("verdict", "NO DATA")

    best = analysis.get("best_setup") or {}
    levels = best if best.get("sl_pct") is not None else {}

    score = 4.0 + min(3.0, avg_score / 25)
    score += min(2.0, avg_conf / 35)
    if best.get("setup_confidence"):
        score += min(1.5, float(best["setup_confidence"]) / 50)

    if verdict_type == "strong_bull":
        verdict = "BUY"
        direction = "LONG"
        score += 2.0
        action = f"STRONG BULLISH MTF — {conf.get('bull_count', 0)}/{conf.get('total_tfs', 0)} TFs aligned · avg {avg_score:.1f}/100"
    elif verdict_type == "strong_bear":
        verdict = "SELL"
        direction = "SHORT"
        score += 2.0
        action = f"STRONG BEARISH MTF — {conf.get('bear_count', 0)}/{conf.get('total_tfs', 0)} TFs aligned · avg {avg_score:.1f}/100"
    elif verdict_type == "mild_bull":
        verdict, direction = "WATCHLIST", "LONG"
        score += 1.0
        action = conf.get("suggested_play", ["Mild bullish bias — wait for lower-TF confirmation"])[0]
    elif verdict_type == "mild_bear":
        verdict, direction = "WATCHLIST", "SHORT"
        score += 1.0
        action = conf.get("suggested_play", ["Mild bearish bias — wait for lower-TF confirmation"])[0]
    else:
        verdict, direction = "WAIT", "—"
        action = "Mixed/neutral MTF alignment — wait for clarity across timeframes."
        score = min(score, 6.0)

    trade_plan = None
    if best.get("direction") in ("LONG", "SHORT") and best.get("entry"):
        direction = best["direction"]
        if best.get("status") == "READY":
            verdict = "BUY" if direction == "LONG" else "SELL"
        hold = best.get("hold_duration", "Varies by TF")
        setup_conf = best.get("setup_confidence", 0)
        sl_p = best.get("sl_pct")
        tp_p = best.get("tp2_pct") or best.get("tp1_pct")
        action = (
            f"{best.get('status', 'SETUP')} {direction} on {best.get('timeframe', 'MTF')} "
            f"({best.get('style', '')}) · conf {setup_conf:.0f}% · hold {hold}"
        )
        if sl_p is not None and tp_p is not None:
            action += f" · SL -{sl_p:.2f}% · TP +{tp_p:.2f}%"
        trade_plan = {
            "direction": direction,
            "entry_price": best.get("entry"),
            "stop_loss": best.get("sl"),
            "take_profit": best.get("tp2") or best.get("tp1"),
            "stop_loss_pct": sl_p,
            "take_profit_pct": tp_p,
            "expected_profit_pct": tp_p,
            "hold_duration": hold,
            "setup_confidence_pct": setup_conf,
        }
    elif verdict in ("BUY", "SELL") and levels.get("sl_pct"):
        trade_plan = {
            "direction": direction,
            "entry_price": levels.get("entry"),
            "stop_loss": levels.get("sl"),
            "take_profit": levels.get("tp2") or levels.get("tp1"),
            "stop_loss_pct": levels.get("sl_pct"),
            "take_profit_pct": levels.get("tp2_pct") or levels.get("tp1_pct"),
            "expected_profit_pct": levels.get("tp2_pct") or levels.get("tp1_pct"),
            "hold_duration": levels.get("hold_duration", "Varies by TF"),
        }

    score = _clamp(score)
    ready = conf.get("ready_setup_count", 0)
    watch = conf.get("watch_setup_count", 0)
    reasons = [
        f"MTF verdict: {verdict_text}",
        f"Avg composite {avg_score:.1f}/100 · confidence {avg_conf:.1f}%.",
        f"Setups: {ready} READY · {watch} WATCH across {len(tf_results)} TF(s).",
        f"Alignment: {conf.get('bull_count', 0)} bull · {conf.get('neutral_count', 0)} neutral · {conf.get('bear_count', 0)} bear.",
    ]
    if best.get("timeframe"):
        reasons.append(
            f"Best setup: {best.get('status')} {best.get('direction')} on {best.get('timeframe')} "
            f"— conf {best.get('setup_confidence', 0):.0f}%, hold {best.get('hold_duration', '—')}."
        )

    return make_summary(
        ticker=symbol,
        timeframe="MTF",
        tab="MTF Scanner",
        score=score,
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{verdict_text} · {ready} ready setup(s)",
        reasons=reasons,
    )


def summarize_top_down_mtf(analysis: dict, symbol: str) -> dict:
    """Score card for Top-Down MTF SMC scanner."""
    phase = analysis.get("phase", "NEUTRAL")
    confidence = float(analysis.get("confidence", 0) or 0)
    s1 = analysis.get("step1") or {}
    s3 = analysis.get("step3") or {}
    plan = analysis.get("trade_plan") or {}
    bias = s1.get("bias", "NEUTRAL")

    score = 4.0 + min(3.0, confidence / 25)
    priority = analysis.get("priority", 0)
    score += min(2.0, priority / 50)

    if phase == "ENTRY_READY" and plan and not plan.get("projected"):
        direction = plan.get("direction", "LONG")
        verdict = "BUY" if direction == "LONG" else "SELL"
        score += 2.0
        sl_p = plan.get("sl_pct")
        tp_p = plan.get("tp_pct")
        action = (
            f"ENTRY READY {direction} — {s3.get('trigger', 'trigger')} · "
            f"conf {confidence:.0f}% · hold {plan.get('hold_duration', '—')}"
        )
        if sl_p is not None and tp_p is not None:
            action += f" · SL -{sl_p:.2f}% · TP +{tp_p:.2f}%"
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": sl_p,
            "take_profit_pct": tp_p,
            "expected_profit_pct": tp_p,
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif phase in ("APPROACHING_LTF", "MTF_SETUP") and plan:
        direction = plan.get("direction", "—")
        verdict = "WATCHLIST"
        score += 1.0
        sl_p = plan.get("sl_pct")
        tp_p = plan.get("tp_pct")
        action = f"{phase.replace('_', ' ')} — {analysis.get('primary_label', '')[:80]}"
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": sl_p,
            "take_profit_pct": tp_p,
            "expected_profit_pct": tp_p,
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif phase == "HTF_BIAS" and bias in ("BULLISH", "BEARISH"):
        verdict = "WATCHLIST"
        direction = "LONG" if bias == "BULLISH" else "SHORT"
        action = f"HTF {bias} bias — waiting for MTF CHoCH + FVG/OB on {analysis.get('mtf_label', 'MTF')}"
        trade_plan = None
        score += 0.5
    else:
        verdict, direction = "WAIT", "—"
        action = analysis.get("primary_label", "No actionable top-down setup.")
        trade_plan = None
        score = min(score, 6.0)

    reasons = [
        f"Phase: {phase} — {analysis.get('primary_label', '')}",
        f"HTF bias: {bias} · confidence {confidence:.0f}%.",
        f"Pipeline: {analysis.get('htf_label', '—')} → {analysis.get('mtf_label', '—')} → {analysis.get('ltf_label', '—')}.",
    ]
    s2 = analysis.get("step2") or {}
    if s2.get("choch"):
        reasons.append(f"MTF CHoCH confirmed · zone distance {s2.get('zone_distance_pct', '—')}%.")
    if s3.get("trigger") and s3.get("trigger") != "None":
        reasons.append(f"LTF trigger: {s3.get('trigger')}.")

    return make_summary(
        ticker=symbol,
        timeframe="Top-Down MTF",
        tab="Top Down MTF",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · conf {confidence:.0f}%",
        reasons=reasons,
    )


def summarize_topdown_mtf(analysis: dict, symbol: str) -> dict:
    """Score card for TOPDOWN - MTF (Liquidity + Order Blocks) scanner."""
    live = analysis.get("live") or {}
    phase = analysis.get("phase", live.get("phase", "NEUTRAL"))
    confidence = float(analysis.get("confidence") or live.get("confidence_pct") or 0)
    plan = analysis.get("trade_plan") or live.get("trade_plan") or {}
    s_htf = analysis.get("step_htf") or {}
    s_ltf = analysis.get("step_ltf") or {}
    bias = s_htf.get("bias", "NEUTRAL")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if phase == "ENTRY_READY" and plan and live.get("take_trade"):
        direction = plan.get("direction", "LONG")
        verdict = "BUY" if direction == "LONG" else "SELL"
        score += 2.0
        action = (
            f"ENTRY {direction} — HTF/ATF OB + LTF MSS · conf {confidence:.0f}% · "
            f"SL -{plan.get('sl_pct', 0):.2f}% · TP +{plan.get('tp_pct', 0):.2f}%"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif phase in ("IN_OB_ZONE", "ATF_SETUP", "HTF_BIAS"):
        verdict = "WATCHLIST"
        score += 1.0
        action = analysis.get("primary_label", live.get("primary_label", ""))[:100]
        trade_plan = None
    else:
        verdict, action = "WAIT", analysis.get("primary_label", "No TOPDOWN-MTF setup")
        trade_plan = None
        score = min(score, 6.0)

    tf_chain = f"{analysis.get('htf_tf', '—')} → {analysis.get('atf_tf', '—')} → {analysis.get('ltf_tf', '—')}"
    reasons = [
        f"Phase: {phase} — {analysis.get('primary_label', '')}",
        f"HTF bias: {bias} · confidence {confidence:.0f}%.",
        f"Pipeline: {tf_chain}.",
    ]
    if s_ltf.get("mss"):
        reasons.append("LTF Market Structure Shift confirmed.")
    if s_ltf.get("in_zone"):
        reasons.append("Price inside ATF order block zone.")

    return make_summary(
        ticker=symbol,
        timeframe=tf_chain,
        tab="TOPDOWN - MTF",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · conf {confidence:.0f}%",
        reasons=reasons,
    )


def summarize_weekly_stoch_sweet_spot(analysis: dict, symbol: str) -> dict:
    """Score card for Weekly Stochastic Sweet Spot scanner."""
    phase = analysis.get("phase", "NEUTRAL")
    confidence = float(analysis.get("confidence", 0) or 0)
    plan = analysis.get("trade_plan") or {}
    m = analysis.get("metrics") or {}

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)
    if m.get("win_rate_pct", 0) >= 50:
        score += 0.5

    if phase == "ENTRY_SIGNAL":
        verdict = "BUY"
        direction = "LONG"
        score += 2.0
        sl_p, tp_p = plan.get("sl_pct"), plan.get("tp_pct")
        action = f"WEEKLY ENTRY — K crossed D into sweet spot · conf {confidence:.0f}%"
        if sl_p is not None and tp_p is not None:
            action += f" · SL -{sl_p:.2f}% · TP +{tp_p:.2f}%"
    elif phase == "IN_TRADE":
        verdict = "BUY"
        direction = "LONG"
        score += 1.5
        action = f"IN TRADE — hold weekly long · {analysis.get('primary_label', '')[:60]}"
    elif phase == "EXIT_SIGNAL":
        verdict = "SELL"
        direction = "SHORT"
        score += 1.5
        action = "WEEKLY EXIT — K crossed below D under 80%"
    elif phase in ("APPROACHING", "SWEET_WATCH"):
        verdict = "WATCHLIST"
        direction = "LONG"
        score += 1.0
        action = analysis.get("primary_label", "Approaching sweet-spot entry")
    else:
        verdict, direction = "WAIT", "—"
        action = analysis.get("primary_label", "No sweet-spot setup")
        score = min(score, 6.0)

    trade_plan = None
    if plan and verdict in ("BUY", "WATCHLIST"):
        trade_plan = {
            "direction": plan.get("direction", "LONG"),
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration", "1–12 weeks"),
            "setup_confidence_pct": confidence,
        }

    reasons = [
        f"Phase: {phase} — K={analysis.get('k', 0):.1f} D={analysis.get('d', 0):.1f}",
        f"Sweet spot: {'yes' if analysis.get('in_sweet_spot') else 'no'} · "
        f"Vol confirm: {'yes' if analysis.get('vol_confirm') else 'no'}.",
        f"Backtest: {m.get('total_trades', 0)} trades · win {m.get('win_rate_pct', 0):.0f}% · "
        f"return {m.get('strategy_return_pct', 0):+.1f}% vs B&H {m.get('buy_and_hold_ret_pct', 0):+.1f}%.",
    ]

    return make_summary(
        ticker=symbol,
        timeframe="Weekly",
        tab="Weekly Stoch Sweet Spot",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · K {analysis.get('k', 0):.0f} / D {analysis.get('d', 0):.0f}",
        reasons=reasons,
    )


def summarize_kn_smart_rsi(analysis: dict, symbol: str) -> dict:
    """Score card for KN Smart DP SL + RSI MTF + VWMA scanner."""
    phase = analysis.get("phase", "NEUTRAL")
    confidence = float(analysis.get("confidence", 0) or 0)
    live = analysis.get("live") or {}
    plan = analysis.get("trade_plan") or {}
    signal = live.get("signal", "HOLD")
    trend = analysis.get("master_trend", "sideways")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if phase == "BUY_SIGNAL":
        verdict, direction = "BUY", "LONG"
        score += 2.0
        action = live.get("action") or f"KN Smart BUY — master trend {trend}"
    elif phase == "SELL_SIGNAL":
        verdict, direction = "SELL", "SHORT"
        score += 2.0
        action = live.get("action") or f"KN Smart SELL — master trend {trend}"
    elif phase == "EXIT_SIGNAL":
        verdict, direction = "SELL" if trend == "bullish" else "BUY", "—"
        score += 1.0
        action = live.get("action") or "Exit signal on latest bar"
    elif phase in ("APPROACHING_BUY", "APPROACHING_SELL"):
        verdict = "WATCHLIST"
        direction = "LONG" if "BUY" in phase else "SHORT"
        score += 1.0
        action = analysis.get("primary_label", "Approaching full KN Smart setup")
    elif phase == "TREND_ALIGNED":
        verdict, direction = "WATCHLIST", "LONG" if trend == "bullish" else "SHORT"
        action = analysis.get("primary_label", "Partial alignment — wait for entry")
    elif phase == "SIDEWAYS":
        verdict, direction = "WAIT", "—"
        action = "Daily VWMA sideways — avoid new trades"
        score = min(score, 5.5)
    else:
        verdict, direction = "WAIT", "—"
        action = analysis.get("primary_label", "No KN Smart setup")
        score = min(score, 6.0)

    trade_plan = None
    if plan and verdict in ("BUY", "SELL", "WATCHLIST"):
        trade_plan = {
            "direction": plan.get("direction", direction),
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration", "15 min – 3 hours"),
            "setup_confidence_pct": confidence,
        }

    mtf = live.get("mtf") or {}
    reasons = [
        f"Phase: {phase} · signal {signal} · master trend {trend}",
        f"RSI {live.get('rsi', 0):.1f} · confidence {confidence:.0f}%.",
        f"MTF: {mtf.get('bullish_count', 0)} bullish / {mtf.get('bearish_count', 0)} bearish TFs.",
    ]
    sc = analysis.get("signal_counts") or {}
    reasons.append(f"Recent bars: {sc.get('buy', 0)} BUY · {sc.get('sell', 0)} SELL · {sc.get('exit', 0)} EXIT.")

    return make_summary(
        ticker=symbol,
        timeframe=analysis.get("intraday_tf", "5m"),
        tab="KN Smart RSI MTF",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {trend} · RSI {live.get('rsi', 0):.0f}",
        reasons=reasons,
    )


def summarize_velez_retracement(analysis: dict, symbol: str) -> dict:
    """Score card for Velez Retracement Scalping scanner."""
    phase = analysis.get("phase", "NO_SETUP")
    confidence = float(analysis.get("confidence", 0) or 0)
    plan = analysis.get("trade_plan") or {}
    chart_tf = analysis.get("chart_tf", "5m")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if phase == "ENTRY_READY" and plan:
        direction = plan.get("direction", "LONG")
        verdict = "BUY" if direction == "LONG" else "SELL"
        score += 2.0
        scenario = plan.get("scenario", "SCALP")
        action = (
            f"Velez {scenario} {direction} @ {chart_tf} — "
            f"SL -{plan.get('sl_pct', 0):.2f}% · TP +{plan.get('tp_pct', 0):.2f}% · "
            f"hold {plan.get('hold_duration', '—')}"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif phase == "WATCH":
        verdict, direction = "WATCHLIST", "—"
        action = analysis.get("primary_label", "Sharp move — watch retracement zone")
        score += 1.0
        trade_plan = None
    else:
        verdict, direction = "WAIT", "—"
        action = analysis.get("primary_label", "No Velez setup")
        score = min(score, 6.0)
        trade_plan = None

    mv = analysis.get("recent_move") or {}
    reasons = [
        f"Phase: {phase} · chart {chart_tf} · confidence {confidence:.0f}%.",
        analysis.get("primary_label", ""),
    ]
    if mv:
        reasons.append(
            f"Sharp {mv.get('direction')} move {mv.get('magnitude_pct', 0):.2f}% detected."
        )
    bt = analysis.get("backtest_summary") or {}
    if bt.get("closed"):
        reasons.append(
            f"Loaded-window backtest: {bt.get('win_rate', 0):.0f}% win · "
            f"{bt.get('scalps', 0)} scalps · {bt.get('trends', 0)} trends."
        )

    return make_summary(
        ticker=symbol,
        timeframe=chart_tf,
        tab="Velez Retracement",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {plan.get('scenario', '—') if plan else '—'} · {chart_tf}",
        reasons=reasons,
    )


def summarize_bb_exposed(analysis: dict, symbol: str) -> dict:
    """Score card for BB Exposed (Free Bar + Squeeze) scanner."""
    if analysis.get("error"):
        return summarize_error(symbol, analysis.get("chart_tf", "—"), analysis["error"], tab="BB Exposed")

    phase = analysis.get("phase", "NO_SETUP")
    confidence = float(analysis.get("confidence", 0) or 0)
    plan = analysis.get("trade_plan") or {}
    chart_tf = analysis.get("chart_tf", "15m")
    strategy = analysis.get("strategy", "—")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if analysis.get("actionable") and plan.get("direction") in ("LONG", "SHORT"):
        direction = plan["direction"]
        verdict = "BUY" if direction == "LONG" else "SELL"
        score += 2.0
        action = (
            f"{strategy} {direction} @ {chart_tf} — BB({analysis.get('bb_length')},{analysis.get('bb_std')}) · "
            f"SL -{plan.get('sl_pct', 0):.2f}% · TP +{plan.get('tp_pct', 0):.2f}%"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif (analysis.get("verdict") or "").startswith("WATCH"):
        verdict, direction = "WATCHLIST", "—"
        action = analysis.get("primary_label", f"Watch {strategy}")
        score += 1.0
        trade_plan = None
    else:
        verdict, direction = "WAIT", "—"
        action = analysis.get("primary_label", "No BB Exposed setup")
        score = min(score, 6.0)
        trade_plan = None

    reasons = list(analysis.get("reasons") or [])
    reasons.insert(0, f"Phase: {phase} · {strategy} · confidence {confidence:.0f}%.")

    return make_summary(
        ticker=symbol,
        timeframe=chart_tf,
        tab="BB Exposed",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {strategy} · {chart_tf}",
        reasons=reasons,
    )


def summarize_box_trading(analysis: dict, symbol: str) -> dict:
    """Score card for Box Trading (TradingLab) scanner."""
    if analysis.get("error"):
        return summarize_error(
            symbol, analysis.get("execution_tf", "5m"), analysis["error"], tab="Box Trading",
        )

    live = analysis.get("live") or {}
    phase = live.get("phase", "NO_SETUP")
    confidence = float(live.get("confidence_pct") or 0)
    box = analysis.get("box") or {}
    tf = analysis.get("execution_tf", "5m")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if live.get("take_trade"):
        direction = live.get("direction", "LONG")
        verdict = "BUY" if direction == "LONG" else "SELL"
        score += 2.0
        action = (
            f"{phase.replace('_', ' ')} {direction} · conf {confidence:.0f}% · "
            f"SL -{live.get('sl_pct', 0):.2f}% · TP +{live.get('tp_pct', 0):.2f}%"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": live.get("entry_price"),
            "stop_loss": live.get("stop_price"),
            "take_profit": live.get("target_price"),
            "stop_loss_pct": live.get("sl_pct"),
            "take_profit_pct": live.get("tp_pct"),
            "expected_profit_pct": live.get("tp_pct"),
            "hold_duration": live.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif live.get("phase") in (
        "WATCH_BOX_BOTTOM", "WATCH_BOX_TOP",
        "LONG_REVERSAL", "SHORT_REVERSAL",
        "BREAKOUT_RETEST_LONG", "BREAKOUT_RETEST_SHORT",
    ):
        verdict, direction = "WATCHLIST", live.get("direction", "—")
        action = live.get("verdict", phase)
        score += 1.0
        trade_plan = None
    elif phase == "NO_TRADE_ZONE":
        verdict, action = "WAIT", "In box midpoint no-trade zone"
        trade_plan = None
        score = min(score, 5.0)
    else:
        verdict, action = "WAIT", live.get("verdict", "No box setup")
        trade_plan = None
        score = min(score, 6.0)

    reasons = list(live.get("reasons") or [])
    if box.get("box_top") is not None:
        reasons.insert(0, f"Box top {box.get('box_top')} · bottom {box.get('box_bottom')}")

    return make_summary(
        ticker=symbol,
        timeframe=tf,
        tab="Box Trading",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · conf {confidence:.0f}%",
        reasons=reasons,
    )


def summarize_hub_scanner(
    analysis: dict,
    symbol: str,
    *,
    tab: str,
    default_tf: str = "15m",
) -> dict:
    """Generic score card for hub scanner engines (flat or live-nested payload)."""
    if analysis.get("error"):
        tf = (
            analysis.get("chart_tf")
            or analysis.get("execution_tf")
            or default_tf
        )
        return summarize_error(symbol, tf, analysis["error"], tab=tab)

    live = analysis.get("live") or {}
    phase = live.get("phase") or analysis.get("phase", "NO_SETUP")
    confidence = float(
        live.get("confidence_pct")
        or live.get("confidence")
        or analysis.get("confidence")
        or analysis.get("confidence_pct")
        or 0
    )
    plan = live.get("trade_plan") or analysis.get("trade_plan") or {}
    chart_tf = (
        analysis.get("chart_tf")
        or analysis.get("execution_tf")
        or live.get("execution_tf")
        or default_tf
    )
    strategy = (
        analysis.get("strategy")
        or live.get("strategy")
        or tab
    )
    priority = float(analysis.get("priority") or live.get("priority") or 15)
    actionable = bool(
        live.get("take_trade")
        or analysis.get("actionable")
        or analysis.get("take_trade")
    )
    verdict_raw = str(
        live.get("verdict")
        or analysis.get("verdict")
        or analysis.get("primary_label")
        or ""
    )
    primary_label = (
        live.get("primary_label")
        or analysis.get("primary_label")
        or verdict_raw
        or f"{phase} — {tab}"
    )
    reasons_src = list(analysis.get("reasons") or live.get("reasons") or [])

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, priority / 50)

    direction_plan = plan.get("direction") if plan else None
    if actionable and direction_plan in ("LONG", "SHORT"):
        direction = direction_plan
        verdict = "BUY" if direction == "LONG" else "SELL"
        score += 2.0
        action = (
            f"{strategy} {direction} @ {chart_tf} — "
            f"SL -{plan.get('sl_pct', 0):.2f}% · TP +{plan.get('tp_pct', 0):.2f}%"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration") or plan.get("holding_period"),
            "setup_confidence_pct": confidence,
        }
    elif verdict_raw.upper().startswith("WATCH") or "WATCH" in str(phase).upper():
        verdict, direction = "WATCHLIST", "—"
        action = primary_label
        score += 1.0
        trade_plan = None
    else:
        verdict, direction = "WAIT", "—"
        action = primary_label
        score = min(score, 6.0)
        trade_plan = None

    reasons = reasons_src[:8]
    reasons.insert(0, f"Phase: {phase} · {strategy} · confidence {confidence:.0f}%.")

    return make_summary(
        ticker=symbol,
        timeframe=chart_tf,
        tab=tab,
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {strategy} · {chart_tf}",
        reasons=reasons,
        strategy=strategy if strategy != tab else "",
    )


def summarize_crypto_scalping(analysis: dict, symbol: str) -> dict:
    """Score card for Crypto Scalping (EMA + VWAP + RSI) scanner."""
    phase = analysis.get("phase", "NO_SIGNAL")
    confidence = float(analysis.get("confidence", 0) or 0)
    plan = analysis.get("trade_plan") or {}
    chart_tf = analysis.get("chart_tf", "5m")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if phase == "ENTRY_LONG" and plan:
        verdict, direction = "BUY", "LONG"
        score += 2.0
        action = (
            f"Scalp LONG @ {chart_tf} — VWAP pullback · RSI {analysis.get('rsi', '—')} · "
            f"SL -{plan.get('sl_pct', 0):.3f}% · TP +{plan.get('tp_pct', 0):.3f}%"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif phase == "ENTRY_SHORT" and plan:
        verdict, direction = "SELL", "SHORT"
        score += 2.0
        action = (
            f"Scalp SHORT @ {chart_tf} — VWAP rejection · RSI {analysis.get('rsi', '—')} · "
            f"SL -{plan.get('sl_pct', 0):.3f}% · TP +{plan.get('tp_pct', 0):.3f}%"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif phase in ("WATCH_LONG", "WATCH_SHORT"):
        verdict, direction = "WATCHLIST", "—"
        score += 1.0
        action = analysis.get("primary_label", "Trend aligned — wait for VWAP trigger")
        trade_plan = None
    else:
        verdict, direction = "WAIT", "—"
        action = analysis.get("primary_label", "No scalping setup")
        score = min(score, 6.0)
        trade_plan = None

    reasons = [
        f"Phase: {phase} · {chart_tf} · trend {analysis.get('trend', '—')} · RSI {analysis.get('rsi', '—')}.",
        analysis.get("primary_label", ""),
    ]
    bt = analysis.get("backtest_metrics") or {}
    if bt.get("total_trades"):
        reasons.append(
            f"Backtest: {bt.get('total_trades')} trades · {bt.get('win_rate', 0):.0f}% win · "
            f"PF {bt.get('profit_factor', 0):.2f} · return {bt.get('total_return_pct', 0):.2f}%."
        )

    return make_summary(
        ticker=symbol,
        timeframe=chart_tf,
        tab="Crypto Scalping",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        reasons=reasons,
    )


def summarize_smc_fake_market_shift(analysis: dict, symbol: str) -> dict:
    """Score card for SMC Fake Market Shift scanner."""
    phase = analysis.get("phase", "NO_SETUP")
    confidence = float(analysis.get("confidence", 0) or 0)
    plan = analysis.get("trade_plan") or {}
    chart_tf = analysis.get("chart_tf", "15m")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if phase == "ENTRY_READY" and plan:
        direction = plan.get("direction", "LONG")
        verdict = "BUY" if direction == "LONG" else "SELL"
        score += 2.0
        model = plan.get("model", "—")
        action = (
            f"SMC FMS {model} {direction} @ {chart_tf} — fake market shift · "
            f"SL -{plan.get('sl_pct', 0):.3f}% · TP +{plan.get('tp_pct', 0):.3f}% · "
            f"R:R 1:{plan.get('rr_ratio', '—')}"
        )
        trade_plan = {
            "direction": direction,
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }
    elif phase == "WATCH_SWEEP":
        verdict, direction = "WATCHLIST", "—"
        score += 1.0
        action = analysis.get("primary_label", "Liquidity sweep — await MSS / flip zone")
        trade_plan = None
    elif phase == "STRUCTURE_ONLY":
        verdict, direction = "WATCHLIST", "—"
        action = analysis.get("primary_label", "BOS/POI mapped — no recent sweep")
        trade_plan = None
    else:
        verdict, direction = "WAIT", "—"
        action = analysis.get("primary_label", "No SMC fake market shift setup")
        score = min(score, 6.0)
        trade_plan = None

    reasons = [
        f"Phase: {phase} · bias {analysis.get('trend_bias', '—')} · {chart_tf} · confidence {confidence:.0f}%.",
        analysis.get("primary_label", ""),
        f"BOS: {analysis.get('bos_count', 0)} · POI: {analysis.get('poi_count', 0)} · "
        f"sweeps: {analysis.get('sweep_count', 0)} · signals: {analysis.get('signal_count', 0)}.",
    ]
    bt = analysis.get("backtest_summary") or {}
    if bt.get("closed_trades"):
        reasons.append(
            f"Backtest: {bt.get('closed_trades')} closed · {bt.get('win_rate', 0):.0f}% win · "
            f"total R {bt.get('total_R', 0):.2f} · avg R {bt.get('avg_R', 0):.2f}."
        )

    return make_summary(
        ticker=symbol,
        timeframe=chart_tf,
        tab="SMC Fake Market Shift",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {analysis.get('trend_bias', '—')} · {chart_tf}",
        reasons=reasons,
    )


def summarize_weak_strong_sr(analysis: dict, symbol: str, *, timeframe: str = "") -> dict:
    """Score card for Weak Strong S-R screener (single TF or MTF aggregate)."""
    tf = timeframe or analysis.get("chart_tf") or analysis.get("best_tf") or "MTF"
    confidence = float(analysis.get("confidence", 0) or 0)
    verdict_raw = (analysis.get("verdict") or "NO SETUP").upper()
    direction = analysis.get("direction") or "—"
    plan = analysis.get("trade_plan") or {}
    ctx = analysis.get("sr_context") or {}
    sr_bias = ctx.get("sr_bias") or analysis.get("sr_bias") or "—"

    score = 4.5 + min(3.5, confidence / 22)
    if verdict_raw in ("STRONG BUY", "BUY"):
        verdict = "BUY" if verdict_raw == "BUY" else "STRONG BUY"
        score += 2.0
    elif verdict_raw == "SELL":
        verdict = "SELL"
        score += 2.0
    elif verdict_raw in ("WATCHLIST", "MIXED"):
        verdict = "WATCHLIST"
        score += 1.0
    else:
        verdict = "WAIT"
        score = min(score, 6.0)

    if plan:
        action = (
            f"Weak/Strong S/R {plan.get('direction', direction)} @ {tf} — "
            f"SL -{plan.get('sl_pct', 0):.2f}% · TP +{plan.get('tp_pct', 0):.2f}% · "
            f"conf {plan.get('confidence_pct', confidence):.0f}% · "
            f"hold {plan.get('hold_duration', '—')}"
        )
        trade_plan = make_trade_plan(
            direction=plan.get("direction", direction),
            timeframe=tf,
            stop_loss_pct=plan.get("sl_pct"),
            take_profit_pct=plan.get("tp_pct"),
            expected_profit_pct=plan.get("tp_pct"),
            confidence_pct=plan.get("confidence_pct", confidence),
            style="swing" if tf in ("1d", "4h") else "scalp",
        )
        trade_plan["entry_price"] = plan.get("entry")
        trade_plan["stop_loss"] = plan.get("stop_loss")
        trade_plan["take_profit"] = plan.get("take_profit")
        trade_plan["rr_ratio"] = plan.get("rr_ratio")
    else:
        action = analysis.get("summary", f"S/R bias {sr_bias} — no trade plan")
        trade_plan = None

    align = analysis.get("mtf_alignment_pct")
    cons = analysis.get("consolidation") or {}
    sd = analysis.get("supply_demand") or {}
    reasons = [
        f"S/R bias: {sr_bias} · confidence {confidence:.0f}%.",
        analysis.get("summary", "")[:200],
    ]
    if cons.get("is_consolidating"):
        reasons.append((cons.get("label") or f"Consolidation {cons.get('bias', '—')} near {cons.get('near_level', 'S/R')}")[:120])
    if sd.get("active_zone") not in ("none", None, ""):
        reasons.append((sd.get("label") or f"Active {sd.get('active_zone')} zone · {sd.get('bias', '—')} bias")[:120])
    if align is not None:
        reasons.append(f"MTF alignment {align:.0f}% · {analysis.get('long_votes', 0)} long / {analysis.get('short_votes', 0)} short legs.")
    for sig in (analysis.get("signals") or [])[:4]:
        reasons.append(sig[:120])

    return make_summary(
        ticker=symbol,
        timeframe=tf,
        tab="Weak Strong S-R",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{verdict} · {sr_bias} · {tf} · conf {confidence:.0f}%",
        reasons=[r for r in reasons if r],
    )


def summarize_stf_shop(
    recommendation: dict,
    portfolio: list[dict],
    analyses: list[dict] | None = None,
) -> dict:
    """Score card for ETF Shop 4.0 daily rotation + SIP tracker."""
    buy = recommendation.get("buy_recommendation") or {}
    sell = recommendation.get("primary_sell")
    slot = float(recommendation.get("slot_size") or 0)
    deployed = float(recommendation.get("deployed_capital") or 0)
    pct_dep = float(recommendation.get("pct_deployed") or 0)

    verdict = "WAIT"
    score = 5.0
    action_parts: list[str] = []

    if buy.get("action") == "BUY" and not buy.get("blocked"):
        verdict = "BUY"
        score = 7.5
        buy_kind = buy.get("buy_type", "standard")
        if buy_kind == "sip":
            action_parts.append(
                f"SIP #{buy.get('sip_rank')} BUY {buy.get('symbol')} "
                f"· ₹{buy.get('sip_amount', slot):,.0f} @ ~{_fmt_inr_short(buy.get('price'))}"
            )
        else:
            action_parts.append(
                f"Rank {buy.get('rank')} BUY {buy.get('symbol')} "
                f"· slot {_fmt_inr_short(slot)} @ ~{_fmt_inr_short(buy.get('price'))}"
            )
    elif buy.get("blocked"):
        verdict = "WATCHLIST"
        score = 6.0
        action_parts.append(f"Buy blocked: {buy.get('block_reason', '')[:80]}")

    if sell:
        if verdict == "BUY":
            verdict = "WATCHLIST"
            score = 7.0
        elif verdict == "WAIT":
            verdict = "SELL"
            score = 7.5
        if sell.get("sell_mode") == "combined":
            sell_label = f"+{sell.get('profit_pct')}% · +₹{sell.get('profit_inr', 0):,.0f}"
        elif sell.get("sell_mode") == "percentage":
            sell_label = f"+{sell.get('profit_pct')}%"
        else:
            sell_label = f"+₹{sell.get('profit_inr', 0):,.0f}"
        action_parts.append(
            f"SELL {sell.get('symbol')} {sell_label} (FIFO lot, max 1/day)"
        )

    if not action_parts:
        action_parts.append(
            f"No action · deployed {pct_dep:.0f}% · "
            f"{len([s for s in portfolio if (s.get('status') or 'open') == 'open'])} open lots"
        )

    ranked = recommendation.get("ranked_all") or recommendation.get("ranked_below_dma") or []
    top = ranked[0] if ranked else {}
    sip_top = (recommendation.get("sip_candidates") or [{}])[0] if recommendation.get("sip_candidates") else {}
    reasons = [
        f"ETF Shop 4.0 · effective ₹{recommendation.get('effective_capital', slot):,.0f} · "
        f"slot ₹{slot:,.0f} · deployed {pct_dep:.0f}%.",
        buy.get("reason", "")[:160],
    ]
    if top:
        reasons.append(
            f"Rank #1 vs 20 DMA: {top.get('symbol')} ({top.get('pct_from_dma'):.2f}%)."
        )
    if sip_top:
        reasons.append(
            f"Top SIP fall: {sip_top.get('symbol')} ({sip_top.get('fall_from_last_buy_pct'):.2f}% from last buy)."
        )
    if sell:
        reasons.append(sell.get("reason", "")[:120])

    return make_summary(
        ticker="ETF Shop 4.0",
        timeframe="Daily",
        tab="ETF Shop 4.0",
        score=_clamp(score),
        verdict=verdict,
        action=" · ".join(action_parts),
        summary=f"{verdict} · {pct_dep:.0f}% deployed · slot ₹{slot:,.0f}",
        reasons=[r for r in reasons if r],
    )


def _fmt_inr_short(val: float | None) -> str:
    if val is None:
        return "—"
    return f"₹{float(val):,.2f}"


def summarize_smart_wave_crypto(analysis: dict, symbol: str) -> dict:
    """Score card for Smart Wave Academy crypto scanner."""
    phase = analysis.get("phase", "NO_SIGNAL")
    confidence = float(analysis.get("confidence", 0) or 0)
    plan = analysis.get("trade_plan") or {}
    best_key = analysis.get("best_strategy", "")
    best_label = analysis.get("primary_label", "")

    score = 4.0 + min(3.0, confidence / 25)
    score += min(2.0, analysis.get("priority", 0) / 50)

    if phase in ("ENTRY_LONG", "MB_READY"):
        verdict, direction = "BUY", "LONG"
        score += 2.0
        action = best_label or "Smart Wave LONG entry"
    elif phase == "ENTRY_SHORT":
        verdict, direction = "SELL", "SHORT"
        score += 2.0
        action = best_label or "Smart Wave SHORT entry"
    elif phase in ("TREND_LONG", "TREND_SHORT", "WATCH"):
        verdict = "WATCHLIST"
        direction = "LONG" if "LONG" in phase else ("SHORT" if "SHORT" in phase else "—")
        score += 1.0
        action = best_label or "Approaching Smart Wave setup"
    elif phase == "MB_SKIP":
        verdict, direction = "WAIT", "—"
        action = "Multi-Bagger needs 40%+ daily move — skip for now"
        score = min(score, 5.0)
    else:
        verdict, direction = "WAIT", "—"
        action = best_label or "No Smart Wave setup"
        score = min(score, 6.0)

    if plan.get("within_risk_limit") is False:
        action += " · ⚠️ Risk exceeds ₹200/trade — reduce size or tighten SL"
        score = min(score, 6.5)

    trade_plan = None
    if plan and verdict in ("BUY", "SELL", "WATCHLIST"):
        trade_plan = {
            "direction": plan.get("direction", direction),
            "entry_price": plan.get("entry"),
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "stop_loss_pct": plan.get("sl_pct"),
            "take_profit_pct": plan.get("tp_pct"),
            "expected_profit_pct": plan.get("tp_pct"),
            "hold_duration": plan.get("hold_duration", "30m–1h"),
            "setup_confidence_pct": confidence,
        }

    reasons = [
        f"Phase: {phase} · best {best_key or '—'}",
        f"Confidence {confidence:.0f}% · leverage {analysis.get('leverage', 5)}X",
        f"MB eligible: {'yes' if analysis.get('mb_eligible') else 'no'}",
    ]
    for key, res in list((analysis.get("strategies") or {}).items())[:4]:
        reasons.append(f"{key}: {res.get('phase', '—')} @ {res.get('timeframe', '—')}")

    return make_summary(
        ticker=symbol,
        timeframe=analysis.get("primary_tf", "30m"),
        tab="Smart Wave Crypto",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{phase} · {best_label[:60]}",
        reasons=reasons,
    )


def summarize_mtf_intraday_bias(analysis: dict, symbol: str) -> dict:
    """Score card for MTF Intraday Bullish/Bearish session bias engine."""
    if analysis.get("error"):
        return summarize_error(
            symbol, "Session", str(analysis["error"])[:120], tab="MTF Intraday Bias",
        )

    direction = analysis.get("direction", "NEUTRAL")
    bias = analysis.get("bias", "neutral")
    confidence = float(analysis.get("confidence", 0) or 0)
    setup = analysis.get("trade_setup") or {}
    close_bias = analysis.get("close_bias", "")

    score = 4.5 + min(2.5, confidence / 40)
    if direction == "BULLISH":
        base_verdict = "BUY"
    elif direction == "BEARISH":
        base_verdict = "SELL"
    else:
        base_verdict = "WAIT"
        score = min(score, 5.5)

    status = setup.get("status", "NO SETUP")
    if status == "READY":
        verdict = base_verdict
        score += 2.0
    elif status == "WATCH":
        verdict = "WATCHLIST"
        score += 1.0
    elif status == "LOW CONFIDENCE":
        verdict = "WAIT"
        score = min(score, 6.0)
    else:
        verdict = base_verdict if direction != "NEUTRAL" else "WAIT"

    action_parts = [f"Session {direction.lower()} · {close_bias}"]
    if setup.get("entry_timeframe_label"):
        action_parts.append(f"Entry TF: {setup.get('entry_timeframe_label')}")
    if setup.get("sl_pct") is not None:
        action_parts.append(
            f"SL -{setup['sl_pct']:.2f}% · TP +{setup.get('tp_pct', 0):.2f}% · "
            f"hold {setup.get('hold_duration', '—')}"
        )
    action = " · ".join(action_parts)

    trade_plan = None
    if setup.get("sl_pct") and setup.get("direction") not in (None, "—"):
        trade_plan = {
            "direction": setup.get("direction"),
            "entry_price": setup.get("entry"),
            "stop_loss": setup.get("stop_loss"),
            "take_profit": setup.get("take_profit"),
            "stop_loss_pct": setup.get("sl_pct"),
            "take_profit_pct": setup.get("tp_pct"),
            "expected_profit_pct": setup.get("tp_pct"),
            "hold_duration": setup.get("hold_duration"),
            "setup_confidence_pct": confidence,
        }

    tf_bits = []
    for role, res in (analysis.get("timeframes") or {}).items():
        tf_bits.append(f"{role} {res.get('display', role)}: {res.get('score_label', '—')}")
    reasons = [
        f"Weighted score {analysis.get('weighted_score', 0):.2f} · confidence {confidence:.0f}%.",
        f"PCR: {analysis.get('pcr', '—')}",
        setup.get("note", "")[:120],
    ] + tf_bits[:4]

    market_tag = "crypto" if analysis.get("is_crypto") else "equity"
    return make_summary(
        ticker=symbol,
        timeframe="HTF→ULTF",
        tab="MTF Intraday Bias",
        score=_clamp(score),
        verdict=verdict,
        action=action,
        trade_plan=trade_plan,
        summary=f"{direction} · {status} · {market_tag} session",
        reasons=reasons,
    )


def summarize_intra_hwp(analysis: dict, symbol: str) -> dict:
    """Score card for Intra HWP — Two-Sided Gap Fill + 21 EMA (always fixed 5m)."""
    if analysis.get("error"):
        return summarize_error(symbol, "5m", str(analysis["error"])[:120], tab="Intra HWP")

    live = analysis.get("live") or {}
    direction = live.get("direction", "WAIT")
    confidence = float(live.get("confidence_pct", 0) or 0)
    take = bool(live.get("take_trade"))
    verdict_raw = str(live.get("verdict", "WAIT"))
    phase = analysis.get("phase", "—")

    if take and direction == "LONG":
        verdict = "BUY"
    elif take and direction == "SHORT":
        verdict = "SELL"
    elif direction in ("LONG", "SHORT"):
        verdict = "WATCHLIST"
    else:
        verdict = "WAIT"

    score = _clamp(4.5 + confidence / 100 * 4.5)
    action = f"{verdict_raw} · phase {phase} · gap {float(analysis.get('gap_pct', 0) or 0):+.2f}%"
    trade_plan = live.get("trade_plan") if take else None
    reasons = list(live.get("reasons") or [])

    return make_summary(
        ticker=symbol, timeframe="5m", tab="Intra HWP",
        score=score, verdict=verdict, action=action, trade_plan=trade_plan,
        summary=f"{verdict_raw} · {phase}", reasons=reasons,
    )


def summarize_weak_strong_rs(analysis: dict, symbol: str, *, timeframe: str = "") -> dict:
    """Score card for Weak / Strong — Relative Strength & Trend Classifier."""
    if analysis.get("error"):
        return summarize_error(symbol, timeframe, str(analysis["error"])[:120], tab="Weak / Strong")

    verdict_label = str(analysis.get("verdict", "NEUTRAL"))
    score_raw = float(analysis.get("score", 0) or 0)
    live = analysis.get("live") or {}
    take = bool(live.get("take_trade"))
    rel_pct = analysis.get("rel_pct")
    vol_ratio = analysis.get("vol_ratio")

    if take and verdict_label == "STRONG":
        verdict = "BUY"
    elif take and verdict_label == "WEAK":
        verdict = "SELL"
    elif verdict_label in ("STRONG", "WEAK"):
        verdict = "WATCHLIST"
    else:
        verdict = "WAIT"

    score = _clamp(5.0 + score_raw / 100 * 5.0)
    trade_plan = live.get("trade_plan") if take else None
    reasons = list(analysis.get("reasons") or [])
    summary = (
        f"{verdict_label} · score {score_raw:+.0f}"
        + (f" · RS {rel_pct:+.1f}%" if rel_pct is not None else "")
        + (f" · vol {vol_ratio:.1f}x" if vol_ratio is not None else "")
    )

    return make_summary(
        ticker=symbol, timeframe=timeframe, tab="Weak / Strong",
        score=score, verdict=verdict, action=str(live.get("verdict", verdict_label)),
        trade_plan=trade_plan, summary=summary, reasons=reasons,
    )


def summarize_pattern_breakout(analysis: dict, symbol: str, timeframe: str) -> dict:
    """Score card for Pattern & Breakout analyzer tab."""
    sr_ev = analysis.get("sr_breakout") or {}
    event = sr_ev.get("event", "RANGE")
    conf = int(sr_ev.get("confidence", 0))
    plans = analysis.get("trade_plans") or []
    best = plans[0] if plans else None
    n_charts = len(analysis.get("chart_patterns") or [])
    n_candles = len(analysis.get("candlestick_patterns") or [])

    score = 5.0
    if event == "BREAKOUT":
        score += 2.0
    elif event == "BREAKDOWN":
        score += 1.5
    elif event == "FAKEOUT":
        score += 1.0
    elif event == "REVERSAL":
        score += 1.8
    score += min(1.5, n_charts * 0.4)
    score += min(1.0, n_candles * 0.15)
    if best:
        score += (best.get("confidence", 50) - 50) / 25
    score = _clamp(score)

    if best and best.get("confidence", 0) >= 65:
        verdict = "BUY" if best["direction"] == "LONG" else "SELL"
        direction = best["direction"]
        action = best.get("explanation", "")[:200]
    elif sr_ev.get("trade_suggestion") in ("BUY", "SELL") and conf >= 50:
        verdict = sr_ev["trade_suggestion"]
        direction = "LONG" if verdict == "BUY" else "SHORT"
        action = sr_ev.get("event_label", "")
    elif event in ("BREAKOUT", "REVERSAL") and sr_ev.get("bias") == "BULLISH":
        verdict, direction = "WATCHLIST", "LONG"
        action = f"{sr_ev.get('event_label', '')} — wait for confirmation entry."
    elif event in ("BREAKDOWN", "FAKEOUT") and sr_ev.get("bias") == "BEARISH":
        verdict, direction = "WATCHLIST", "SHORT"
        action = sr_ev.get("event_label", "")
    else:
        verdict, direction = "WAIT", "—"
        action = "No clear pattern or S/R event — stay flat."

    reasons = [
        f"S/R event: {sr_ev.get('event_label', 'N/A')} ({conf}% conf).",
        f"Chart patterns: {n_charts} · Candlesticks: {n_candles}.",
        f"Trend: {analysis.get('trendlines', {}).get('trend_direction', 'N/A')}.",
    ]
    if best:
        reasons.append(
            f"Top plan: {best['direction']} hold ~{best.get('hold_duration', 'N/A')}."
        )

    return make_summary(
        ticker=symbol,
        timeframe=timeframe,
        tab="Pattern & Breakout",
        score=score,
        verdict=verdict,
        action=action,
        trade_plan=None,
        summary=f"{event} · {n_charts} chart pattern(s) on {timeframe}.",
        reasons=reasons,
    )


def summarize_elliott_wave(ew: dict, symbol: str, timeframe: str) -> dict:
    """Score card for dedicated Elliott Wave tab."""
    pattern = str(ew.get("pattern", "NONE"))
    current = ew.get("current_wave", "—")
    notes = str(ew.get("notes", ""))
    n_waves = len(ew.get("waves") or [])
    targets = ew.get("wave_targets") or {}

    score = 5.0
    if pattern == "IMPULSE":
        score += 1.5
        if current == 5:
            score -= 0.5
    elif pattern == "CORRECTIVE":
        score += 0.5
        if str(current) == "C":
            score += 0.5
    elif pattern == "INCOMPLETE":
        score -= 0.5
    else:
        score -= 1.5
    score = _clamp(score)

    if pattern == "IMPULSE" and current == 5:
        verdict, direction = "WATCH", "—"
        action = "Wave 5 may be completing — watch for ABC correction before new entry."
    elif pattern == "IMPULSE":
        last_dir = (ew.get("waves") or [{}])[-1].get("direction", "UP")
        if last_dir == "UP" and score >= 6:
            verdict, direction = "LEAN", "LONG"
            action = f"Valid impulse — currently wave {current}; trend leg favors longs with confirmation."
        elif last_dir == "DOWN" and score <= 4:
            verdict, direction = "LEAN", "SHORT"
            action = f"Valid bearish impulse — wave {current}; favor shorts with confirmation."
        else:
            verdict, direction = "WATCH", "—"
            action = f"Impulse detected (wave {current}) — wait for clearer entry trigger."
    elif pattern == "CORRECTIVE" and str(current) == "C":
        verdict, direction = "WATCHLIST", "—"
        action = "ABC correction near completion — watch for reversal into new impulse."
    elif pattern == "INCOMPLETE":
        verdict, direction = "NO SETUP", "—"
        action = "Wave structure incomplete — try another timeframe or adjust ZigZag %."
    else:
        verdict, direction = "NO SETUP", "—"
        action = "No valid Elliott pattern on this timeframe."

    reasons = [f"Pattern: {pattern}."]
    if n_waves:
        reasons.append(f"{n_waves} wave leg(s) mapped.")
    if targets:
        reasons.append(f"{len(targets)} projection target(s).")
    if notes:
        reasons.append(notes[:120])

    if direction and direction != "—":
        reasons.insert(0, f"Bias leg: {direction}.")

    return make_summary(
        ticker=symbol,
        timeframe=timeframe,
        tab="Elliott Wave",
        score=score,
        verdict=verdict,
        action=action,
        trade_plan=None,
        summary=f"{pattern} · Wave {current} on {timeframe}.",
        reasons=reasons,
    )


def summarize_top_bottom(metrics: dict, symbol: str, timeframe: str) -> dict:
    top_s = str(metrics.get("top_status", ""))
    bot_s = str(metrics.get("bottom_status", ""))
    bias = str(metrics.get("bias", "NEUTRAL"))
    dist_top = float(metrics.get("dist_top", 50) or 50)
    dist_bot = float(metrics.get("dist_bottom", 50) or 50)
    rsi = float(metrics.get("rsi", 50) or 50)
    sl = float(metrics.get("sl_pct", 0) or 0)
    tp = float(metrics.get("tp_pct", 0) or 0)
    forecast = metrics.get("forecast") if isinstance(metrics.get("forecast"), dict) else None
    if sl <= 0 or tp <= 0:
        sl, tp = default_sl_tp_for_timeframe(timeframe)

    score = 5.0
    if "TROUGH" in bot_s or "PEAK" in top_s:
        score += 2
    elif "AT BOTTOM" in bot_s or "AT TOP" in top_s:
        score += 1
    if "LONG" in bias:
        score += 1.5
    elif "SHORT" in bias:
        score -= 1.5
    if forecast:
        fc_conf = float(forecast.get("composite_confidence", 50) or 50)
        score += (fc_conf - 50) / 25
    score = _clamp(score)

    if "TROUGH" in bot_s or ("LONG" in bias and dist_bot < 3):
        verdict, direction = "BUY", "LONG"
    elif "PEAK" in top_s or ("SHORT" in bias and dist_top < 3):
        verdict, direction = "SELL", "SHORT"
    elif dist_top < dist_bot:
        verdict, direction = "WAIT", "—"
    else:
        verdict, direction = "WATCH", "LONG" if "LONG" in bias else "SHORT"

    plan = make_trade_plan(
        direction=direction,
        timeframe=timeframe,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=tp * 0.85,
        exit_rule=(
            f"Range trade: target +{tp:.1f}% toward fib/mid-range, stop -{sl:.1f}%. "
            f"Exit early if {top_s} / {bot_s} status reverses."
        ),
    )

    tb_action = ""
    if verdict in ("WAIT", "WATCH"):
        tb_action = (
            "Wait — price is mid-range; no clear top/bottom trigger."
            if verdict == "WAIT"
            else "Monitor for reversal at fib levels — no full entry yet."
        )
        plan = None

    reasons = [
        f"{dist_top:.1f}% from peak, {dist_bot:.1f}% from trough, RSI {rsi:.0f}.",
    ]
    if forecast:
        reasons.append(
            f"Forecast conf {forecast.get('composite_confidence', 0):.0f}% · "
            f"P(ATH) {forecast.get('ath_cross_prob', 0):.0f}% · "
            f"P(swing H break) {forecast.get('swing_high_break_prob', 0):.0f}% · "
            f"P(swing L break) {forecast.get('swing_low_break_prob', 0):.0f}%."
        )

    return make_summary(
        ticker=symbol, timeframe=timeframe, tab="Top/Bottom",
        score=score, verdict=verdict, action=tb_action, trade_plan=plan,
        summary=f"{top_s} / {bot_s} — bias {bias}.",
        reasons=reasons,
    )


def summarize_seasonality(bt_metrics: dict, ticker: str) -> dict:
    cagr = float(bt_metrics.get("CAGR", 0) or 0)
    sharpe = float(bt_metrics.get("Sharpe", 0) or 0)
    mdd = abs(float(bt_metrics.get("Max Drawdown", 0) or 0))
    total_ret = float(bt_metrics.get("Total Return", 0) or 0)

    score = 5.0 + _clamp(cagr * 40, -2, 3) + _clamp(sharpe * 1.5, -2, 2) - _clamp(mdd * 15, 0, 2)
    score = _clamp(score)

    monthly_exp = abs(cagr) / 12 * 100 if cagr else 2.0
    sl, tp = 4.0, max(monthly_exp * 1.5, 3.0)

    if score >= 7 and cagr > 0:
        verdict, direction = "SEASONAL BUY", "LONG"
    elif score >= 5:
        verdict, direction = "SELECTIVE", "LONG"
    else:
        verdict, direction = "AVOID", "—"

    plan = make_trade_plan(
        direction=direction,
        timeframe="Seasonal",
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=monthly_exp,
        exit_rule=(
            f"Seasonal month play: target +{tp:.1f}% over the favourable month, "
            f"stop -{sl:.1f}%. Exit at month-end regardless."
        ),
        max_hold_exit="Close by last trading day of the active seasonal month.",
    ) if verdict == "SEASONAL BUY" else None

    seas_action = ""
    if verdict == "AVOID":
        seas_action = "Avoid seasonal long — model CAGR or drawdown is unfavourable."
    elif verdict == "SELECTIVE":
        seas_action = "Seasonality is mixed — only tactical size if you already follow calendar plays."

    return make_summary(
        ticker=ticker, timeframe="Seasonal", tab="Seasonality",
        score=score, verdict=verdict, action=seas_action, trade_plan=plan,
        summary=f"CAGR {cagr:.1%}, Sharpe {sharpe:.2f}, total return {total_ret:.1%}.",
        reasons=[f"Max drawdown {mdd:.1%} on seasonal model."],
    )


def summarize_screener_match(ticker: str, timeframe: str, signal: str = "BUY") -> dict:
    score = 7.0 if signal == "BUY" else 4.0
    sl, tp = default_sl_tp_for_timeframe(timeframe)
    plan = make_trade_plan(
        direction="LONG" if signal == "BUY" else "—",
        timeframe=timeframe,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=tp * 0.75,
        confidence_pct=70.0 if signal == "BUY" else None,
        exit_rule="Screener entry fired — confirm with volume; exit on rule invalidation or TP/SL.",
    )
    return make_summary(
        ticker=ticker, timeframe=timeframe, tab="Screener",
        score=score, verdict=signal,
        action=format_action_with_plan(signal, plan),
        summary=f"Screener matched on {ticker} {timeframe}.",
        reasons=["Entry rules satisfied on latest candle.", "Confirm on higher TF before full size."],
        trade_plan=plan,
    )


def summarize_pump_dump_mega(
    analysis: object,
    side: str,
    conf: dict,
    ticker: str,
    timeframe: str,
    *,
    is_crypto: bool = False,
) -> dict:
    """Mega Analyser card for Pump & Dump Predictor (India or crypto)."""
    verdict_raw = str(conf.get("verdict", "SKIP"))
    total = int(conf.get("total", 0) or 0)
    sig_n = int(conf.get("signal_count", 0) or 0)
    score = _clamp(total / 10.0)

    if side == "LONG":
        verdict = {
            "STRONG": "STRONG BUY", "TRADE": "BUY", "WATCH": "WAIT",
        }.get(verdict_raw, "NO SETUP")
    else:
        verdict = {
            "STRONG": "STRONG SELL", "TRADE": "SELL", "WATCH": "WAIT",
        }.get(verdict_raw, "NO SETUP")

    plan_src = (
        getattr(analysis, "trade_plan_long", None)
        if side == "LONG"
        else getattr(analysis, "trade_plan_short", None)
    ) or {}
    entry = float(plan_src.get("entry") or getattr(analysis, "price", 0) or 0)
    sl = float(plan_src.get("stop_loss") or 0)
    tp1 = float(plan_src.get("tp1") or 0)
    if entry > 0 and sl > 0:
        sl_pct = abs(entry - sl) / entry * 100
    else:
        sl_pct, _ = default_sl_tp_for_timeframe(timeframe)
    if entry > 0 and tp1 > 0:
        tp_pct = abs(tp1 - entry) / entry * 100
    else:
        _, tp_pct = default_sl_tp_for_timeframe(timeframe)

    sigs = (
        getattr(analysis, "pump_signals", {})
        if side == "LONG"
        else getattr(analysis, "dump_signals", {})
    )
    active = [k for k, v in sigs.items() if v.get("active")]

    reasons = [
        f"Confluence {total}/100 · {sig_n} active rule(s) · engine {verdict_raw}",
        f"HTF trend {getattr(analysis, 'htf_trend', 'n/a')} · bias {getattr(analysis, 'bias', 'n/a')}",
    ]
    expert_adj = conf.get("expert_adj")
    if expert_adj:
        reasons.append(f"Expert accuracy adj {expert_adj:+d} pts")
    for w in (getattr(analysis, "expert_warnings", None) or [])[:2]:
        reasons.append(w.replace("⏱ ", "").replace("⚠️ ", ""))
    if active:
        reasons.append(f"Active: {', '.join(active[:6])}")

    style = "Scalping" if timeframe in ("1m", "5m", "15m", "30m") else "Swing"
    if not is_crypto and timeframe in ("4h", "1d", "1w"):
        style = "Swing"

    plan = make_trade_plan(
        direction=side if side in ("LONG", "SHORT") else "LONG",
        timeframe=timeframe,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        expected_profit_pct=round(tp_pct * 0.85, 2),
        style=style,
        exit_rule=plan_src.get("entry_rule", "Enter on trigger close · use planned SL/TP"),
        max_hold_exit=plan_src.get("hold_duration") or plan_src.get("hard_exit", ""),
    )
    if not plan_src.get("actionable", True) and verdict_raw in ("TRADE", "STRONG"):
        verdict = "WAIT"

    market_lbl = "Crypto" if is_crypto else "India"
    summary = (
        f"{market_lbl} pre-{'pump' if side == 'LONG' else 'dump'} · "
        f"{verdict_raw} ({total}/100) · {len(active)} signals"
    )
    if getattr(analysis, "price_chg_pct", None) is not None:
        summary += f" · price Δ {analysis.price_chg_pct:+.2f}%"

    return make_summary(
        ticker=ticker,
        timeframe=timeframe,
        strategy=f"Pump&Dump {side}",
        tab="Pump & Dump",
        score=score,
        verdict=verdict,
        action=format_action_with_plan(verdict, plan),
        summary=summary,
        reasons=reasons,
        trade_plan=plan,
    )


def summarize_gap_setup(setup: dict) -> dict:
    ticker = str(setup.get("symbol", ""))
    tf = str(setup.get("timeframe", ""))
    strat = str(setup.get("strategy", ""))
    gt = str(setup.get("gap_type", ""))
    rr = float(setup.get("rr_ratio", 0) or 0)
    fill = float(setup.get("fill_probability", 0) or 0)
    quality = str(setup.get("signal_quality", ""))
    sl = float(setup.get("sl_pct", 0) or 0)
    tp = float(setup.get("tp_pct", 0) or 0)

    if gt in ("no_gap", "data_error", "error", ""):
        return make_summary(
            ticker=ticker, timeframe=tf, strategy=strat, tab="Gap Scanner",
            score=3.0, verdict="NO SETUP", action="Skip — no actionable gap.",
            summary=setup.get("notes", "No gap detected."),
            reasons=[],
            trade_plan=make_trade_plan(timeframe=tf, direction="—"),
        )

    if sl <= 0 or tp <= 0:
        sl, tp = default_sl_tp_for_timeframe(tf)
        if rr > 0:
            tp = sl * rr

    score = 5.0 + _clamp(rr * 1.5, 0, 3) + _clamp(fill / 30, 0, 1.5)
    if "PREMIUM" in quality.upper():
        score += 1.5
    elif "HIGH" in quality.upper():
        score += 1
    score = _clamp(score)

    if "Long" in strat and score >= 6:
        verdict, direction = "BUY", "LONG"
    elif "Short" in strat and score >= 6:
        verdict, direction = "SELL", "SHORT"
    else:
        verdict, direction = "WAIT", "—"

    plan = make_trade_plan(
        direction=direction,
        timeframe=tf,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        expected_profit_pct=tp * 0.9,
        style="Scalping",
        exit_rule=(
            f"Gap trade ({strat}): intraday target +{tp:.1f}%, stop -{sl:.1f}%. "
            f"Exit by session close if gap does not resolve."
        ),
        max_hold_exit="Mandatory exit same trading session (gap trades are intraday).",
    )

    return make_summary(
        ticker=ticker, timeframe=tf, strategy=strat, tab="Gap Scanner",
        score=score, verdict=verdict,
        action=format_action_with_plan(verdict, plan),
        summary=f"{strat} on {gt.replace('_', ' ')} {setup.get('gap_pct', 0):+.2f}%.",
        reasons=[f"R:R {rr:.1f}, fill prob {fill:.0f}%, quality {quality}."],
        trade_plan=plan,
    )


def summarize_error(
    ticker: str, timeframe: str, error: str, *, tab: str = "", strategy: str = ""
) -> dict:
    return make_summary(
        ticker=ticker, timeframe=timeframe, strategy=strategy, tab=tab,
        score=0.0, verdict="ERROR",
        action="Re-run with valid ticker, token, or date range.",
        summary=str(error)[:120],
        reasons=["Data or execution failed for this combination — this is not a sell/buy signal."],
        trade_plan=None,
        signal_type="error",
    )


def summarize_smc_flow(row: dict, timeframe: str = "1-5 sessions") -> dict:
    """Run digest card for SMC · PCR · Delivery/Turnover index scan."""
    idx = row.get("index", "?")
    pred = row.get("index_prediction") or {}
    pcr = row.get("pcr") or {}
    verdict = pred.get("verdict", "HOLD")
    conf = float(pred.get("confidence") or 50)
    score = 5.0 + (conf - 50) / 10
    if verdict == "BUY":
        score += 1.0
    elif verdict == "SELL":
        score -= 0.5
    score = _clamp(score)

    smc = row.get("index_smc") or {}
    reasons = list(pred.get("reasons") or [])[:3]
    if pcr.get("pcr"):
        reasons.insert(0, f"Index PCR {pcr['pcr']:.2f}")
    reasons.append(f"SMC: {smc.get('bias', '—')} · {smc.get('zone', '—')}")

    bull_n = sum(1 for t in row.get("tickers") or [] if (t.get("prediction") or {}).get("verdict") == "BUY")
    bear_n = sum(1 for t in row.get("tickers") or [] if (t.get("prediction") or {}).get("verdict") == "SELL")
    reasons.append(f"Constituents: {bull_n} BUY / {bear_n} SELL")

    action = pred.get("next_move", "")[:220]
    return make_summary(
        ticker=idx,
        timeframe=timeframe,
        tab="SMC Flow",
        score=score,
        verdict=verdict,
        action=action,
        summary=f"{pred.get('direction', '—')} ({conf:.0f}% conf) — smart money + PCR + delivery view.",
        reasons=reasons,
    )


def summarize_smc_ticker(
    symbol: str,
    timeframe: str,
    smc: dict,
    prediction: dict,
    flow: dict | None = None,
) -> dict:
    """Per-stock SMC flow leg for Mega Analyser."""
    verdict = prediction.get("verdict", "HOLD")
    conf = float(prediction.get("confidence") or 50)
    score = 5.0 + (conf - 50) / 12
    if verdict == "BUY":
        score += 1.0
    elif verdict == "SELL":
        score -= 0.8
    score = _clamp(score)
    reasons = list(prediction.get("reasons") or [])[:3]
    reasons.insert(0, f"SMC {smc.get('bias', '—')} · {smc.get('zone', '—')}")
    if flow and flow.get("delivery_pct"):
        reasons.append(f"Delivery {flow['delivery_pct']:.1f}% · turnover {flow.get('turnover_cr', 0):.1f} Cr")
    return make_summary(
        ticker=symbol,
        timeframe=timeframe,
        tab="SMC Flow",
        score=score,
        verdict=verdict,
        action=(prediction.get("next_move") or "")[:220],
        summary=f"{prediction.get('direction', '—')} ({conf:.0f}% conf) — SMC + delivery view.",
        reasons=reasons,
    )


def summarize_mtf_aggregate(summaries: list[dict], ticker: str, tab: str = "") -> dict:
    valid = [s for s in summaries if s.get("verdict") not in ("ERROR", "NO SETUP")]
    if not valid:
        return summarize_error(ticker, "MTF", "No valid timeframe results", tab=tab)
    avg = sum(s["score"] for s in valid) / len(valid)
    best = max(valid, key=lambda x: x.get("score", 0))
    best_plan = best.get("trade_plan") or make_trade_plan(timeframe=best.get("timeframe", "1d"))
    buys = sum(1 for s in valid if s.get("verdict") in ("BUY", "TOP PICK", "DEPLOY", "SEASONAL BUY"))
    sells = sum(1 for s in valid if s.get("verdict") in ("SELL",))
    if buys >= len(valid) * 0.6 and avg >= 6:
        verdict = "BUY"
    elif sells >= len(valid) * 0.6 and avg <= 4:
        verdict = "SELL"
    else:
        verdict = "MIXED"
    plan = make_trade_plan(
        direction=best_plan.get("direction", "—"),
        timeframe=best.get("timeframe", "Multi-TF"),
        stop_loss_pct=best_plan.get("stop_loss_pct"),
        take_profit_pct=best_plan.get("take_profit_pct"),
        expected_profit_pct=best_plan.get("expected_profit_pct"),
        exit_rule=f"Trade best TF ({best.get('timeframe')}): {best_plan.get('exit_rule', '')}",
    )
    return make_summary(
        ticker=ticker, timeframe="Multi-TF", tab=tab,
        score=_clamp(avg), verdict=verdict,
        action=format_action_with_plan(verdict, plan, f"Best leg: {best.get('tab')} @ {best.get('timeframe')}."),
        summary=f"Avg {avg:.1f}/10 across {len(valid)} legs.",
        reasons=[
            f"{s.get('timeframe')}: {s.get('score')}/10 {s.get('verdict')} "
            f"(TP +{(s.get('trade_plan') or {}).get('take_profit_pct', 0):.1f}%)"
            for s in valid[:4]
        ],
        trade_plan=plan,
    )
