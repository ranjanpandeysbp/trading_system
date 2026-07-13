"""
strategy_scheduler_tab.py
-------------------------
Scheduled preset / saved-strategy scanner — Groww & Crypto side by side.
Suggest trades with SL, TP, hold duration, confidence, and AI View.
"""

from __future__ import annotations

from contextlib import nullcontext

import json
import time
from datetime import date, timedelta
from typing import Callable

import pandas as pd
from backtesting.data_fetcher import POPULAR_NSE_STOCKS, get_historical_data
from app.market_pulse.ai_view import (
    MTF_AI_SYSTEM,
    STANDARD_REPORT_FORMAT,
    combine_timeframe_sections,
    mtf_ticker_button,
    render_ai_config,
    render_mtf_ai_view_report,
    show_ai_view_block,
)
from app.market_pulse.database import (
    get_combo_outcomes_by_mobile,
    get_custom_strategies_by_mobile,
    get_use_later_strategies_by_mobile,
)
from app.market_pulse.demo_trading import render_demo_trade_panel
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.indicators import calculate_dynamic_indicators
from app.market_pulse.multi_combo_saves import resolve_strategy_config
from app.market_pulse.presets import get_presets_for_market
from app.market_pulse.run_summary import (
    make_summary,
    make_trade_plan,
    render_run_summary,
    summarize_error,
)
from app.market_pulse.ta_screener_ui import (
    is_actionable_summary,
    is_approaching_summary,
    render_ta_screener_options,
    render_ta_screener_results,
    render_strategy_mtf_panel,
)
from app.market_pulse.ticker_selection_ui import render_coindcx_ticker_selection
from app.market_pulse.ticker_utils import (
    CRYPTO_MARKET,
    GROWW_MARKET,
    INDEX_OPTIONS,
    get_us_index_options,
    US_MARKET,
    get_coindcx_ticker_list,
    is_crypto_market,
    market_currency,
)

ALL_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

SCHEDULE_OPTIONS: dict[str, int] = {
    "Every 1 min": 1,
    "Every 2 min": 2,
    "Every 3 min": 3,
    "Every 5 min": 5,
    "Every 10 min": 10,
    "Every 15 min": 15,
    "Every 30 min": 30,
    "Every 1 hour": 60,
    "Every 2 hours": 120,
    "Every 3 hours": 180,
    "Every 4 hours": 240,
    "Every 6 hours": 360,
    "Every 8 hours": 480,
    "Every 12 hours": 720,
    "Every 24 hours": 1440,
}

STRATEGY_SCHEDULER_AI_SYSTEM = """You are an expert systematic trader for Indian equities and crypto futures.

The user runs **preset / saved strategies** on a schedule across tickers and timeframes.
Each suggestion includes: strategy name, entry signal, stop-loss %, take-profit %, hold duration, confidence.

Be precise with prices and levels. If confidence is low or signals conflict, recommend WAIT.
For actionable BUY setups, validate R:R ≥ 1:2 and state how long to hold the position.
""" + STANDARD_REPORT_FORMAT


def get_logged_in_mobile() -> str:
    return (st.session_state.get("logged_in_mobile") or "").strip()


def build_strategy_catalog(mobile: str, market: str) -> dict[str, dict]:
    """Presets + custom + use-later + saved combo outcomes for one market."""
    catalog = dict(get_presets_for_market(market))
    target = "CoinDCX" if is_crypto_market(market) else "Groww"

    for s in get_custom_strategies_by_mobile(mobile):
        if s["market"] in (target, "Both"):
            key = f"🤖 [CUSTOM] {s['name']}"
            catalog[key] = {
                "description": s.get("description", ""),
                "recommended_timeframe": s.get("recommended_timeframe", "1h"),
                "recommended_sl": float(s.get("recommended_sl") or 0.5),
                "recommended_tp": float(s.get("recommended_tp") or 1.0),
                "indicators": json.loads(s["indicators"]),
                "entry_rules": json.loads(s["entry_rules"]),
                "exit_rules": json.loads(s["exit_rules"]),
            }

    for s in get_use_later_strategies_by_mobile(mobile):
        if s["market"] in (target, "Both"):
            key = f"⏳ [USE LATER] {s['name']}"
            catalog[key] = {
                "description": s.get("description", ""),
                "recommended_timeframe": s.get("recommended_timeframe", "1h"),
                "recommended_sl": float(s.get("recommended_sl") or 0.5),
                "recommended_tp": float(s.get("recommended_tp") or 1.0),
                "indicators": json.loads(s["indicators"]),
                "entry_rules": json.loads(s["entry_rules"]),
                "exit_rules": json.loads(s["exit_rules"]),
            }

    if mobile:
        for o in get_combo_outcomes_by_mobile(mobile, market):
            key = f"⭐ [SAVED] {o['ticker']} | {o['timeframe']} | {o['strategy_name'][:36]}"
            catalog[key] = {
                "description": f"Saved Multi-Combo outcome · Ret {o.get('return_pct') or '—'}%",
                "recommended_timeframe": o["timeframe"],
                "recommended_sl": 0.5,
                "recommended_tp": 1.0,
                "indicators": json.loads(o["indicators"]),
                "entry_rules": json.loads(o["entry_rules"]),
                "exit_rules": json.loads(o["exit_rules"]),
            }

    return catalog


def _entry_confidence(df_ind: pd.DataFrame, entry_rules: list, entry_active: bool) -> int:
    if not entry_rules:
        return 0
    matched = sum(1 for r in entry_rules if _eval_rule_on_row(df_ind, r))
    base = int(100 * matched / len(entry_rules))
    if entry_active:
        return min(92, base + 12)
    return base


def analyze_strategy_suggestion(
    ticker: str,
    timeframe: str,
    market: str,
    strategy_name: str,
    preset: dict,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict:
    """Run one ticker × TF × strategy and return summary dict."""
    try:
        cfg = {
            "indicators": preset["indicators"],
            "entry_rules": preset["entry_rules"],
            "exit_rules": preset.get("exit_rules", []),
        }
        df = get_historical_data(
            symbol=ticker,
            start_date=str(date.today() - timedelta(days=90)),
            end_date=str(date.today()),
            market=market,
            timeframe=timeframe,
            groww_token=groww_token,
            groww_exchange=exchange,
        )
        if df is None or df.empty or len(df) < 15:
            return summarize_error(ticker, timeframe, "Insufficient OHLCV data", tab="Strategy Scheduler")

        eval_res = evaluate_trade_setup(
            df,
            cfg["indicators"],
            cfg["entry_rules"],
            cfg.get("exit_rules"),
            entry_mode="AND",
        )
        df_ind = calculate_dynamic_indicators(df.copy(), cfg["indicators"])
        conf = _entry_confidence(df_ind, cfg["entry_rules"], eval_res["entry_active"])
        close = eval_res.get("close")
        currency = market_currency(market)

        sl_pct = float(preset.get("recommended_sl") or 0.5)
        tp_pct = float(preset.get("recommended_tp") or 1.0)

        if eval_res["entry_active"]:
            verdict = "BUY"
            direction = "LONG"
            sl_price = close * (1 - sl_pct / 100) if close else None
            tp_price = close * (1 + tp_pct / 100) if close else None
            summary = (
                f"**{strategy_name[:50]}** — entry rules aligned on latest bar. "
                f"Entry {currency}{(close or 0):,.4f} · SL {currency}{(sl_price or 0):,.4f} "
                f"(-{sl_pct:.2f}%) · TP {currency}{(tp_price or 0):,.4f} (+{tp_pct:.2f}%)."
            )
        elif eval_res.get("exit_active"):
            verdict = "WAIT"
            direction = "—"
            summary = "Exit rules active — avoid new long; wait for fresh entry setup."
        else:
            verdict = "NO SETUP"
            direction = "—"
            summary = f"Strategy rules not met ({conf}% rule match). No trade this scan."

        plan = make_trade_plan(
            direction=direction,
            timeframe=timeframe,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
            confidence_pct=float(conf),
            style="scalp" if timeframe in ("1m", "5m", "15m") else "swing",
        )

        out = make_summary(
            ticker=ticker,
            timeframe=timeframe,
            strategy=strategy_name,
            tab="Strategy Scheduler",
            score=min(10.0, conf / 10.0),
            verdict=verdict,
            summary=summary,
            reasons=[
                f"Signal: {eval_res['signal']}",
                f"Rule match: {conf}%",
                f"Bar: {eval_res.get('bar_time', '—')}",
            ],
            trade_plan=plan,
        )
        out["market"] = market
        return out
    except Exception as exc:
        err = summarize_error(ticker, timeframe, str(exc)[:120], tab="Strategy Scheduler")
        err["market"] = market
        return err


def build_strategy_scheduler_ai_prompt(summaries: list[dict], market: str) -> str:
    lines = [f"STRATEGY SCHEDULER — {market}", f"Setups scanned: {len(summaries)}", ""]
    for s in summaries[:25]:
        tp = s.get("trade_plan") or {}
        lines.append(
            f"{s.get('ticker')} | {s.get('timeframe')} | {s.get('strategy', '')[:40]}\n"
            f"  Verdict: {s.get('verdict')} · Score {s.get('score')}/10 · Conf {tp.get('confidence_pct')}%\n"
            f"  {s.get('summary', '')[:200]}"
        )
    return "\n".join(lines)


def _run_scan(
    tickers: list[str],
    timeframes: list[str],
    strategies: list[str],
    catalog: dict[str, dict],
    market: str,
    groww_token: str,
    exchange: str,
) -> list[dict]:
    results: list[dict] = []
    for ticker in tickers:
        for tf in timeframes:
            for strat_name in strategies:
                preset = catalog.get(strat_name)
                if not preset:
                    cfg = resolve_strategy_config(get_logged_in_mobile(), market, strat_name)
                    if not cfg:
                        continue
                    preset = {**cfg, "recommended_sl": 0.5, "recommended_tp": 1.0}
                results.append(
                    analyze_strategy_suggestion(
                        ticker, tf, market, strat_name, preset,
                        groww_token=groww_token, exchange=exchange,
                    )
                )
    return results


def _fragment_decorator() -> Callable:
    """Prefer run_every so auto-poll works while the section is open (Streamlit ≥1.33); no-op outside Streamlit."""
    try:
        return st.fragment(run_every=timedelta(minutes=1))
    except Exception:
        return lambda fn: fn


def _all_scheduler_results() -> list[dict]:
    groww = st.session_state.get("sts_groww_results") or []
    us = st.session_state.get("sts_us_results") or []
    crypto = st.session_state.get("sts_crypto_results") or []
    return groww + us + crypto


def _combo_count(tickers: list, tfs: list, strategies: list) -> int:
    return len(tickers) * len(tfs) * len(strategies)


def _render_market_results(
    market_key: str,
    market_label: str,
    market: str,
    emoji: str,
    provider: str,
    model: str,
    api_key: str,
    *,
    exchange: str = "NSE",
):
    """Results + auto-poll for one market (groww | crypto)."""
    results_key = f"sts_{market_key}_results"
    config_key = f"sts_{market_key}_scan_config"
    force_key = f"sts_{market_key}_force_scan"
    auto_key = f"sts_{market_key}_auto_poll"
    last_ts_key = f"sts_{market_key}_last_poll_ts"
    last_run_key = f"sts_{market_key}_last_run"
    poll_key = f"sts_{market_key}_poll_minutes"

    results = st.session_state.get(results_key) or []
    poll_minutes = int(st.session_state.get(poll_key) or 5)
    last_ts = st.session_state.get(last_ts_key, 0.0)
    force = bool(st.session_state.pop(force_key, False))
    auto = st.session_state.get(auto_key, False)

    due = force or (auto and poll_minutes and (time.time() - last_ts >= poll_minutes * 60))
    if due and st.session_state.get(config_key):
        cfg = st.session_state[config_key]
        with nullcontext():
            token = get_active_groww_token()
            ex = exchange if market_key == "groww" else "NSE"
            scanned = _run_scan(
                cfg["tickers"], cfg["tfs"], cfg["strategies"],
                cfg["catalog"], market, token, ex,
            )
            st.session_state[results_key] = scanned
            st.session_state[last_ts_key] = time.time()
            st.session_state[last_run_key] = time.strftime("%H:%M:%S")
        results = scanned

    st.markdown(f"### {emoji} {market_label} — results")
    st.caption(f"Last run: **{st.session_state.get(last_run_key, '—')}**")

    if not results:
        st.info(f"Configure {market_label} above, then click **Suggest Trades** or **Run now**.")
        return

    trades = [r for r in results if r.get("signal_type") == "trade"]
    st.markdown(f"**{len(trades)}** trade suggestion(s) · **{len(results)}** combos scanned")

    sched_actionable_only = render_ta_screener_options(f"sched_{market_key}")
    render_ta_screener_results(
        results,
        title=f"🧭 {market_label} Screener",
        strategy_label="scheduled strategy",
        actionable_only=sched_actionable_only,
    )

    by_ticker: dict[str, list[dict]] = {}
    for r in results:
        by_ticker.setdefault(r["ticker"], []).append(r)

    for ticker, rows in by_ticker.items():
        if sched_actionable_only and not any(
            is_actionable_summary(r) or is_approaching_summary(r) for r in rows
        ):
            continue
        trade_rows = [r for r in rows if r.get("signal_type") == "trade"]
        with st.expander(
            f"{'🟢' if trade_rows else '⚪'} **{ticker}** — {len(trade_rows)} setup(s)",
            expanded=bool(trade_rows),
        ):
            _, ai_btn = st.columns([4, 1])
            with ai_btn:
                mtf_ticker_button("strategy_scheduler", f"{market_key}_{ticker}")
            sched_tf = (trade_rows[0].get("timeframe") if trade_rows else rows[0].get("timeframe")) or "1h"
            sched_dir = trade_rows[0].get("direction") if trade_rows else None
            render_strategy_mtf_panel(
                symbol=ticker,
                market=market_label,
                groww_token=get_active_groww_token(),
                exchange=st.session_state.get(f"sched_{market_key}_exchange", "NSE"),
                primary_tf=sched_tf,
                strategy_direction=sched_dir,
            )
            for row in rows:
                render_run_summary(row, compact=True)
                row_key = f"{market_key}|{ticker}|{row.get('timeframe')}|{row.get('strategy', '')}"
                if row.get("signal_type") == "trade" and api_key:
                    show_ai_view_block(
                        "sts",
                        row_key,
                        ticker,
                        row.get("timeframe", ""),
                        lambda r=row, m=market_label: build_strategy_scheduler_ai_prompt([r], m),
                        STRATEGY_SCHEDULER_AI_SYSTEM,
                        provider,
                        model,
                        api_key,
                        button_in_column=False,
                    )
                if row.get("signal_type") == "trade":
                    render_demo_trade_panel(
                        "sts",
                        row_key,
                        ticker,
                        row.get("timeframe", "1h"),
                        row.get("market", market),
                        row.get("strategy", "Preset"),
                        source_tab="Strategy Scheduler",
                        groww_token=get_active_groww_token(),
                        exchange=exchange if market_key == "groww" else "NSE",
                    )

    if api_key and results:
        render_mtf_ai_view_report(
            "strategy_scheduler",
            market_key.upper(),
            lambda r=results, m=market_label: combine_timeframe_sections(
                f"STRATEGY SCHEDULER — {m}",
                market_key.upper(),
                [build_strategy_scheduler_ai_prompt(r, m)],
            ),
            STRATEGY_SCHEDULER_AI_SYSTEM,
            provider,
            model,
            api_key,
            len(results),
        )


@_fragment_decorator()
def _render_groww_results_fragment(provider: str, model: str, api_key: str):
    auto = st.session_state.get("sts_groww_auto_poll", False)
    c1, c2 = st.columns([2, 1])
    with c1:
        st.session_state["sts_groww_auto_poll"] = st.checkbox(
            "🇮🇳 Auto-run Groww on schedule while open",
            value=auto,
            key="sts_groww_auto_poll_cb",
        )
    with c2:
        if st.button("🔄 Run now (Groww)", key="sts_groww_run_now", width='stretch'):
            st.session_state["sts_groww_force_scan"] = True
            st.rerun(scope="fragment")
    _render_market_results(
        "groww", "Groww", GROWW_MARKET, "🇮🇳",
        provider, model, api_key,
        exchange=st.session_state.get("sts_exchange", "NSE"),
    )


@_fragment_decorator()
def _render_us_results_fragment(provider: str, model: str, api_key: str):
    auto = st.session_state.get("sts_us_auto_poll", False)
    c1, c2 = st.columns([2, 1])
    with c1:
        st.session_state["sts_us_auto_poll"] = st.checkbox(
            "🇺🇸 Auto-run US on schedule while open",
            value=auto,
            key="sts_us_auto_poll_cb",
        )
    with c2:
        if st.button("🔄 Run now (US)", key="sts_us_run_now", width='stretch'):
            st.session_state["sts_us_force_scan"] = True
            st.rerun(scope="fragment")
    _render_market_results(
        "us", "US Stocks", US_MARKET, "🇺🇸",
        provider, model, api_key,
    )


@_fragment_decorator()
def _render_crypto_results_fragment(provider: str, model: str, api_key: str):
    auto = st.session_state.get("sts_crypto_auto_poll", False)
    c1, c2 = st.columns([2, 1])
    with c1:
        st.session_state["sts_crypto_auto_poll"] = st.checkbox(
            "🪙 Auto-run Crypto on schedule while open",
            value=auto,
            key="sts_crypto_auto_poll_cb",
        )
    with c2:
        if st.button("🔄 Run now (Crypto)", key="sts_crypto_run_now", width='stretch'):
            st.session_state["sts_crypto_force_scan"] = True
            st.rerun(scope="fragment")
    _render_market_results(
        "crypto", "Crypto", CRYPTO_MARKET, "🪙",
        provider, model, api_key,
    )


def _save_scan_config(
    market_key: str,
    tickers: list[str],
    tfs: list[str],
    strategies: list[str],
    catalog: dict,
    poll_minutes: int,
) -> bool:
    n = _combo_count(tickers, tfs, strategies)
    if n == 0:
        return False
    st.session_state[f"sts_{market_key}_scan_config"] = {
        "tickers": tickers,
        "tfs": tfs,
        "strategies": strategies,
        "catalog": catalog,
    }
    st.session_state[f"sts_{market_key}_poll_minutes"] = poll_minutes
    st.session_state[f"sts_{market_key}_force_scan"] = True
    # Keep merged list for Ask AI
    st.session_state["sts_results"] = _all_scheduler_results()
    return True


def render_strategy_scheduler_tab():
    st.caption(
        "Configure **Groww**, **US**, and **Crypto** independently — each has its own tickers, schedule, "
        "**Suggest Trades**, and **Run now**. Results appear in separate sections below."
    )

    mobile = get_logged_in_mobile()
    provider, model, api_key = render_ai_config(
        "strategy_scheduler",
        caption="AI View reviews suggested trades and hold plans.",
    )

    groww_catalog = build_strategy_catalog(mobile, GROWW_MARKET) if mobile else get_presets_for_market(GROWW_MARKET)
    us_catalog = build_strategy_catalog(mobile, US_MARKET) if mobile else get_presets_for_market(US_MARKET)
    crypto_catalog = build_strategy_catalog(mobile, CRYPTO_MARKET) if mobile else get_presets_for_market(CRYPTO_MARKET)

    col_g, col_u, col_c = st.columns(3)
    from app.market_pulse.ta_mtf_hub_ui import render_ta_hub_badge, render_ta_multiselect_timeframes

    render_ta_hub_badge("sts")

    with col_g:
        st.markdown("#### 🇮🇳 Groww")
        g_idx = st.selectbox(
            "Ticker source", list(INDEX_OPTIONS.keys()) + ["Custom", "Popular NSE"], key="sts_g_idx",
        )
        if g_idx == "Custom":
            g_txt = st.text_area("Tickers (comma-separated)", "RELIANCE,HDFCBANK,TCS", height=56, key="sts_g_txt")
            groww_tickers = [t.strip().upper() for t in g_txt.split(",") if t.strip()]
        elif g_idx == "Popular NSE":
            groww_tickers = st.multiselect(
                "Tickers", POPULAR_NSE_STOCKS[:40], default=["RELIANCE", "TCS", "HDFCBANK"], key="sts_g_pop",
            )
        else:
            opts = INDEX_OPTIONS.get(g_idx, [])
            groww_tickers = st.multiselect("Tickers", opts, default=opts[:3] if opts else [], key="sts_g_ms")

        groww_tfs = render_ta_multiselect_timeframes(
            "sts_g",
            ALL_TIMEFRAMES,
            legacy_default=["5m", "15m", "1h"],
            label="Timeframes",
            show_hub_note=False,
        )
        groww_strategies = st.multiselect(
            "Preset & saved strategies",
            list(groww_catalog.keys()),
            default=list(groww_catalog.keys())[:2] if groww_catalog else [],
            key="sts_g_strat",
        )

        st.markdown("**Groww schedule & actions**")
        g_sched_label = st.selectbox(
            "Run every", list(SCHEDULE_OPTIONS.keys()), index=4, key="sts_g_sched",
        )
        groww_poll = SCHEDULE_OPTIONS[g_sched_label]
        g_ex_col, g_met_col = st.columns(2)
        with g_ex_col:
            st.selectbox("Exchange", ["NSE", "BSE"], key="sts_exchange")
        with g_met_col:
            g_n = _combo_count(groww_tickers, groww_tfs, groww_strategies)
            st.metric("Combinations", g_n)

        g_btn1, g_btn2 = st.columns(2)
        with g_btn1:
            if st.button("🎯 Suggest Trades (Groww)", type="primary", width='stretch', key="sts_g_suggest"):
                if _save_scan_config("groww", groww_tickers, groww_tfs, groww_strategies, groww_catalog, groww_poll):
                    st.toast("Scanning Groww setups…", icon="🇮🇳")
                else:
                    st.error("Select at least one Groww ticker, timeframe, and strategy.")
        with g_btn2:
            if st.button("🔄 Run now (Groww)", width='stretch', key="sts_g_run_cfg"):
                if _save_scan_config("groww", groww_tickers, groww_tfs, groww_strategies, groww_catalog, groww_poll):
                    st.toast("Running Groww scan…", icon="🔄")

    with col_u:
        st.markdown("#### 🇺🇸 US")
        us_opts = get_us_index_options()
        u_idx = st.selectbox(
            "Ticker source", list(us_opts.keys()) + ["Custom"], key="sts_u_idx",
        )
        if u_idx == "Custom":
            u_txt = st.text_area("Tickers (comma-separated)", "AAPL,MSFT,NVDA", height=56, key="sts_u_txt")
            us_tickers = [t.strip().upper() for t in u_txt.split(",") if t.strip()]
        else:
            u_opts = us_opts.get(u_idx, [])
            us_tickers = st.multiselect("Tickers", u_opts, default=u_opts[:3] if u_opts else [], key="sts_u_ms")

        us_tfs = render_ta_multiselect_timeframes(
            "sts_u",
            ALL_TIMEFRAMES,
            legacy_default=["5m", "15m", "1h"],
            label="Timeframes",
            show_hub_note=False,
        )
        us_strategies = st.multiselect(
            "Preset & saved strategies",
            list(us_catalog.keys()),
            default=list(us_catalog.keys())[:2] if us_catalog else [],
            key="sts_u_strat",
        )

        st.markdown("**US schedule & actions**")
        u_sched_label = st.selectbox(
            "Run every", list(SCHEDULE_OPTIONS.keys()), index=4, key="sts_u_sched",
        )
        us_poll = SCHEDULE_OPTIONS[u_sched_label]
        u_n = _combo_count(us_tickers, us_tfs, us_strategies)
        st.metric("Combinations", u_n)

        u_btn1, u_btn2 = st.columns(2)
        with u_btn1:
            if st.button("🎯 Suggest Trades (US)", type="primary", width='stretch', key="sts_u_suggest"):
                if _save_scan_config("us", us_tickers, us_tfs, us_strategies, us_catalog, us_poll):
                    st.toast("Scanning US setups…", icon="🇺🇸")
                else:
                    st.error("Select at least one US ticker, timeframe, and strategy.")
        with u_btn2:
            if st.button("🔄 Run now (US)", width='stretch', key="sts_u_run_cfg"):
                if _save_scan_config("us", us_tickers, us_tfs, us_strategies, us_catalog, us_poll):
                    st.toast("Running US scan…", icon="🔄")

    with col_c:
        st.markdown("#### 🪙 Crypto")
        crypto_tickers = render_coindcx_ticker_selection("sts_c")

        crypto_tfs = render_ta_multiselect_timeframes(
            "sts_c",
            ALL_TIMEFRAMES,
            legacy_default=["5m", "15m", "1h"],
            label="Timeframes",
            show_hub_note=False,
        )
        crypto_strategies = st.multiselect(
            "Preset & saved strategies",
            list(crypto_catalog.keys()),
            default=list(crypto_catalog.keys())[:2] if crypto_catalog else [],
            key="sts_c_strat",
        )

        st.markdown("**Crypto schedule & actions**")
        c_sched_label = st.selectbox(
            "Run every", list(SCHEDULE_OPTIONS.keys()), index=4, key="sts_c_sched",
        )
        crypto_poll = SCHEDULE_OPTIONS[c_sched_label]
        c_n = _combo_count(crypto_tickers, crypto_tfs, crypto_strategies)
        st.metric("Combinations", c_n)

        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("🎯 Suggest Trades (Crypto)", type="primary", width='stretch', key="sts_c_suggest"):
                if _save_scan_config("crypto", crypto_tickers, crypto_tfs, crypto_strategies, crypto_catalog, crypto_poll):
                    st.toast("Scanning Crypto setups…", icon="🪙")
                else:
                    st.error("Select at least one Crypto pair, timeframe, and strategy.")
        with c_btn2:
            if st.button("🔄 Run now (Crypto)", width='stretch', key="sts_c_run_cfg"):
                if _save_scan_config("crypto", crypto_tickers, crypto_tfs, crypto_strategies, crypto_catalog, crypto_poll):
                    st.toast("Running Crypto scan…", icon="🔄")

    st.divider()
    _render_groww_results_fragment(provider, model, api_key)
    st.divider()
    _render_us_results_fragment(provider, model, api_key)
    st.divider()
    _render_crypto_results_fragment(provider, model, api_key)

    st.session_state["sts_results"] = _all_scheduler_results()

    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("strategy_scheduler")
