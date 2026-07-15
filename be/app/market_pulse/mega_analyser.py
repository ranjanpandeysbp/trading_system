"""
mega_analyser.py
----------------
One-click multi-ticker × multi-timeframe hub combining all analysis engines,
unified run summaries, and AI View.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import pandas as pd
from backtesting.data_fetcher import get_historical_data
from app.market_pulse.ai_view import (
    MTF_AI_SYSTEM,
    SENTIMENT_AI_SYSTEM,
    STANDARD_REPORT_FORMAT,
    build_gap_ai_prompt,
    build_sentiment_ai_prompt,
    combine_timeframe_sections,
    mtf_ticker_button,
    render_ai_config,
    render_mtf_ai_view_report,
    show_ai_view_block,
)
from app.market_pulse.database import get_strategies_by_mobile
from app.market_pulse.engine import run_true_backtest
from app.market_pulse.fundamentals_combine import combine_with_fundamentals
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, generate_gap_trade_setups
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.indicators import calculate_dynamic_indicators
def _run_find_sr_analysis(df, tf, sr_window=5):
    from app.market_pulse.find_sr_tab import run_find_sr_analysis
    return run_find_sr_analysis(df, tf, sr_window=sr_window)


def _summarize_find_sr(fsr, ticker, tf):
    from app.market_pulse.find_sr_tab import summarize_find_sr
    return summarize_find_sr(fsr, ticker, tf)


def _build_find_sr_ai_prompt(t, tf, m, fsr, c):
    from app.market_pulse.find_sr_tab import build_find_sr_ai_prompt
    return build_find_sr_ai_prompt(t, tf, m, fsr, c)


from app.market_pulse.confluence_strategy_tab import (
    analyze_confluence_strategy,
    build_confluence_ai_prompt,
    summarize_confluence_strategy,
)
from app.market_pulse.pattern_breakout_tab import (
    build_pattern_breakout_ai_prompt,
    run_pattern_breakout_analysis,
)
from app.market_pulse.price_action import (
    analyze_elliott_waves,
    build_price_action_ai_prompt,
    detect_candlestick_patterns,
    detect_chart_patterns,
    detect_support_resistance,
    run_full_analysis,
)
from app.market_pulse.run_summary import (
    enrich_summary,
    make_summary,
    make_trade_plan,
    render_run_digest,
    render_run_summary,
    summarize_backtest_metrics,
    summarize_elliott_wave,
    summarize_error,
    summarize_fakeout_4h,
    summarize_fakeout_15m,
    summarize_gap_setup,
    summarize_kn_smart_rsi,
    summarize_mtf_scanner,
    summarize_pattern_breakout,
    summarize_price_action,
    summarize_pump_dump_mega,
    summarize_screener_match,
    summarize_seasonality,
    summarize_sentiment_row,
    summarize_smc_ticker,
    summarize_top_bottom,
    summarize_top_down_mtf,
    summarize_velez_retracement,
    summarize_weak_strong_sr,
    summarize_smart_wave_crypto,
    summarize_mtf_intraday_bias,
    summarize_weekly_stoch_sweet_spot,
    summarize_crypto_scalping,
    summarize_smc_fake_market_shift,
    _clamp,
)
from app.market_pulse.top_bottom import build_top_bottom_ai_prompt
from app.market_pulse.top_bottom_forecast import compute_top_bottom_forecast
from app.market_pulse.seasonality import (
    compute_seasonality,
    fetch_seasonality_data,
    generate_signals,
    run_seasonal_backtest,
)
from app.market_pulse.top_bottom import calculate_top_bottom_metrics
from app.market_pulse.ticker_utils import (
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
    market_currency,
)
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ta_screener_ui import render_strategy_mtf_panel


def _smc_as_float(val):
    from app.market_pulse.smc_options_tab import _as_float
    return _as_float(val)


def _smc_flatten_ohlc(df):
    from app.market_pulse.smc_options_tab import _flatten_ohlc_dataframe
    return _flatten_ohlc_dataframe(df)


def _smc_analyze_from_ohlcv(df):
    from app.market_pulse.smc_options_tab import analyze_smc_from_ohlcv
    return analyze_smc_from_ohlcv(df)


def _smc_fetch_bhavcopy_lookup():
    from app.market_pulse.smc_options_tab import fetch_bhavcopy_stock_lookup
    return fetch_bhavcopy_stock_lookup()


def _smc_predict_next_move(*args, **kwargs):
    from app.market_pulse.smc_options_tab import predict_next_move
    return predict_next_move(*args, **kwargs)


MEGA_AI_SYSTEM = """You are an elite multi-engine trading analyst synthesizing ALL analysis legs for the SAME ticker.

Engines may include: Strategy Backtest, Saved Strategies, Sentiment, Price Action, Find S/R (S1/S2/R1/R2),
Weak Strong S/R (strong/weak support & resistance + VWAP · Volume · Supertrend · RSI),
Pattern & Breakout, Confluence (Fib · VWAP · Supertrend · ATR · Volume · S/R), Elliott Wave,
Top/Bottom (+ breakout forecast), SMC Flow, Gap Scanner, Pump & Dump Predictor (pre-pump/pre-dump + expert India boosters),
1min–15min Breakout Fakeout, 5min–4h Breakout Fakeout, MTF Scanner (7-component confluence),
Top-Down MTF SMC (HTF→MTF→LTF), Weekly Stochastic Sweet Spot, KN Smart DP SL + RSI MTF + VWMA,
Velez Retracement Scalping (25%/50% retrace), MTF Intraday Session Bias (HTF→ULTF + trade setup),
Smart Wave Crypto (CoinDCX: EMA · SuperTrend · BB · Multi-Bagger),
Crypto Scalping (CoinDCX: EMA9/21 · VWAP pullback · RSI + backtest stats),
SMC Fake Market Shift (Groww/CoinDCX: BOS → POI → liquidity sweep · models A/B),
Screener, Seasonality.

Weight confluence across engines heavily. Pump & Dump scores ≥55 with ≥3 signals are high-conviction pre-move setups.
If engines conflict, verdict MUST be AVOID or WAIT.
Reference specific scores, levels, and verdicts from the blocks below. Be actionable and data-driven.
""" + STANDARD_REPORT_FORMAT

MEGA_TICKER_SCANNER_MODULES = (
    "fakeout_15m",
    "fakeout_4h",
    "mtf_scanner",
    "top_down_mtf",
    "weekly_stoch",
    "kn_smart_rsi",
    "velez_retracement",
    "mtf_intraday_bias",
    "smart_wave_crypto",
    "crypto_scalping",
    "smc_fake_market_shift",
)

MEGA_BATCH_SIZE = 20


def _mega_pick_tf(timeframes: list[str], candidates: tuple[str, ...], fallback: str) -> str:
    for tf in candidates:
        if tf in timeframes:
            return tf
    return fallback


def _df_title_case_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize lowercase OHLC columns for SMC helpers expecting Title case."""
    mapping = {}
    for col in df.columns:
        low = str(col).lower()
        if low == "open":
            mapping[col] = "Open"
        elif low == "high":
            mapping[col] = "High"
        elif low == "low":
            mapping[col] = "Low"
        elif low == "close":
            mapping[col] = "Close"
    return df.rename(columns=mapping) if mapping else df

ALL_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

MEGA_HTF_MAP = {
    "1m": "15m", "5m": "15m", "15m": "1h", "30m": "1h",
    "1h": "4h", "4h": "1d", "1d": "1w", "1w": "1w",
}

MEGA_SCENARIOS: dict[str, dict] = {
    "Custom (use controls below)": {},
    "Full analysis (default)": {
        "timeframes": ["1h", "1d"],
        "modules": {
            "backtest": True, "saved_strategies": True, "sentiment": True,
            "price_action": True, "find_sr": True, "weak_strong_sr": True,
            "pattern_breakout": True,
            "confluence": True, "elliott_wave": True, "top_bottom": True,
            "tb_forecast": True, "smc_flow": True, "gap": True,
            "pump_dump": False, "screener": True, "seasonality": True,
            "fakeout_15m": False, "fakeout_4h": False, "mtf_scanner": True,
            "top_down_mtf": True, "weekly_stoch": True, "kn_smart_rsi": False,
            "velez_retracement": True, "mtf_intraday_bias": True, "smart_wave_crypto": False,
            "crypto_scalping": False, "smc_fake_market_shift": False,
        },
    },
    "Pump & Dump pre-move": {
        "timeframes": ["5m", "15m"],
        "modules": {
            "backtest": False, "saved_strategies": False, "sentiment": True,
            "price_action": True, "find_sr": True, "weak_strong_sr": True,
            "pattern_breakout": False,
            "confluence": True, "elliott_wave": False, "top_bottom": False,
            "tb_forecast": False, "smc_flow": False, "gap": False,
            "pump_dump": True, "screener": False, "seasonality": False,
            "fakeout_15m": False, "fakeout_4h": False, "mtf_scanner": True,
            "top_down_mtf": False, "weekly_stoch": False, "kn_smart_rsi": False,
            "velez_retracement": False, "mtf_intraday_bias": True, "smart_wave_crypto": False,
            "crypto_scalping": False, "smc_fake_market_shift": False,
        },
    },
    "India intraday scalp (expert)": {
        "timeframes": ["5m", "15m"],
        "modules": {
            "backtest": False, "saved_strategies": False, "sentiment": True,
            "price_action": True, "find_sr": True, "weak_strong_sr": True,
            "pattern_breakout": True,
            "confluence": True, "elliott_wave": False, "top_bottom": True,
            "tb_forecast": False, "smc_flow": True, "gap": True,
            "pump_dump": True, "screener": False, "seasonality": False,
            "fakeout_15m": True, "fakeout_4h": True, "mtf_scanner": True,
            "top_down_mtf": True, "weekly_stoch": False, "kn_smart_rsi": True,
            "velez_retracement": True, "mtf_intraday_bias": True, "smart_wave_crypto": False,
            "crypto_scalping": False, "smc_fake_market_shift": True,
        },
    },
    "Crypto momentum": {
        "timeframes": ["15m", "1h", "4h"],
        "modules": {
            "backtest": False, "saved_strategies": False, "sentiment": True,
            "price_action": True, "find_sr": True, "weak_strong_sr": True,
            "pattern_breakout": True,
            "confluence": True, "elliott_wave": True, "top_bottom": True,
            "tb_forecast": True, "smc_flow": False, "gap": False,
            "pump_dump": True, "screener": False, "seasonality": False,
            "fakeout_15m": True, "fakeout_4h": True, "mtf_scanner": True,
            "top_down_mtf": True, "weekly_stoch": False, "kn_smart_rsi": True,
            "velez_retracement": True, "mtf_intraday_bias": True, "smart_wave_crypto": True,
            "crypto_scalping": True, "smc_fake_market_shift": True,
        },
    },
    "Swing / positional": {
        "timeframes": ["4h", "1d", "1w"],
        "modules": {
            "backtest": True, "saved_strategies": True, "sentiment": True,
            "price_action": True, "find_sr": True, "weak_strong_sr": True,
            "pattern_breakout": True,
            "confluence": True, "elliott_wave": True, "top_bottom": True,
            "tb_forecast": True, "smc_flow": False, "gap": False,
            "pump_dump": True, "screener": False, "seasonality": True,
            "fakeout_15m": False, "fakeout_4h": False, "mtf_scanner": True,
            "top_down_mtf": True, "weekly_stoch": True, "kn_smart_rsi": False,
            "velez_retracement": False, "mtf_intraday_bias": False, "smart_wave_crypto": False,
            "crypto_scalping": False, "smc_fake_market_shift": False,
        },
    },
}


def _mega_htf_for(entry_tf: str) -> str:
    return MEGA_HTF_MAP.get(entry_tf, "15m")


def _apply_mega_scenario(scenario: str) -> None:
    """Push scenario defaults into session_state widget keys."""
    cfg = MEGA_SCENARIOS.get(scenario) or {}
    if not cfg:
        return
    if cfg.get("timeframes"):
        st.session_state["mega_timeframes"] = cfg["timeframes"]
    mods = cfg.get("modules") or {}
    key_map = {
        "backtest": "mega_mod_bt",
        "saved_strategies": "mega_mod_saved",
        "sentiment": "mega_mod_sent",
        "price_action": "mega_mod_pa",
        "find_sr": "mega_mod_fsr",
        "weak_strong_sr": "mega_mod_wssr",
        "pattern_breakout": "mega_mod_pbo",
        "confluence": "mega_mod_conf",
        "elliott_wave": "mega_mod_ew",
        "top_bottom": "mega_mod_tb",
        "tb_forecast": "mega_mod_tb_fc",
        "smc_flow": "mega_mod_smc",
        "gap": "mega_mod_gap",
        "pump_dump": "mega_mod_pdp",
        "screener": "mega_mod_scr",
        "seasonality": "mega_mod_season",
        "fakeout_15m": "mega_mod_f15",
        "fakeout_4h": "mega_mod_f4h",
        "mtf_scanner": "mega_mod_mtf",
        "top_down_mtf": "mega_mod_tdmtf",
        "weekly_stoch": "mega_mod_wstoch",
        "kn_smart_rsi": "mega_mod_kn",
        "velez_retracement": "mega_mod_velez",
        "mtf_intraday_bias": "mega_mod_mtfbias",
        "smart_wave_crypto": "mega_mod_smartwave",
        "crypto_scalping": "mega_mod_cscalp",
        "smc_fake_market_shift": "mega_mod_smcfms",
    }
    for mod, key in key_map.items():
        if mod in mods:
            st.session_state[key] = mods[mod]


def _analyze_sentiment(df: pd.DataFrame, market: str, timeframe: str) -> dict:
    import app.market_pulse.app as app_mod
    return app_mod.analyze_ticker_sentiment(df, market=market, timeframe=timeframe)


def _eval_screener_signal(df: pd.DataFrame, indicators: list, entry_rules: list, entry_mode: str) -> bool:
    if df.empty or len(df) < 10:
        return False
    df = calculate_dynamic_indicators(df, indicators)
    last_row = df.iloc[-1]
    entry_matched = []
    for r in entry_rules:
        l_val = last_row.get(r["left"])
        r_val = float(r["right_val"]) if r.get("right_type") == "value" else last_row.get(r["right_val"])
        if l_val is None or r_val is None:
            entry_matched.append(False)
            continue
        op = r.get("op", "")
        if op == ">":
            entry_matched.append(l_val > r_val)
        elif op == "<":
            entry_matched.append(l_val < r_val)
        elif op == ">=":
            entry_matched.append(l_val >= r_val)
        elif op == "<=":
            entry_matched.append(l_val <= r_val)
        elif op == "==":
            entry_matched.append(l_val == r_val)
        elif "crosses" in op and len(df) >= 2:
            prev_l = df.iloc[-2].get(r["left"])
            prev_r = float(r["right_val"]) if r.get("right_type") == "value" else df.iloc[-2].get(r["right_val"])
            if prev_l is None or prev_r is None:
                entry_matched.append(False)
            elif op == "crosses above":
                entry_matched.append(prev_l < prev_r and l_val > r_val)
            elif op == "crosses below":
                entry_matched.append(prev_l > prev_r and l_val < r_val)
            else:
                entry_matched.append(False)
        else:
            entry_matched.append(False)
    if not entry_matched:
        return False
    if "ALL" in entry_mode.upper():
        return all(entry_matched)
    return any(entry_matched)


def summarize_mega_ticker(ticker: str, summaries: list[dict]) -> dict:
    enriched = [enrich_summary(s) for s in summaries]
    errors = [s for s in enriched if s.get("signal_type") == "error"]
    actionable = [s for s in enriched if s.get("signal_type") == "trade"]
    informative = [s for s in enriched if s.get("signal_type") in ("no_trade", "watch")]

    if not enriched:
        return make_summary(
            ticker=ticker, timeframe="All engines", tab="Mega Analyser",
            score=0.0, verdict="NO EDGE",
            action="Re-run or change tickers/timeframes.",
            summary="No engine results for this ticker.",
        )

    pool = actionable or informative
    if not pool:
        return make_summary(
            ticker=ticker, timeframe="All engines", tab="Mega Analyser",
            score=0.0, verdict="ERROR",
            action="All engine checks failed for this ticker — fix token/data and re-run.",
            summary=f"{len(errors)} failed run(s); nothing to aggregate into a mega score.",
            reasons=[
                f"{s.get('tab', 'Engine')} ({s.get('timeframe', '')}): "
                f"{(s.get('summary') or 'run failed')[:80]}"
                for s in errors[:6]
            ],
            trade_plan=None,
            signal_type="error",
        )

    avg = sum(s["score"] for s in pool) / len(pool)
    bull_n = sum(
        1 for s in actionable
        if s.get("verdict") in ("BUY", "STRONG BUY", "DEPLOY", "TOP PICK", "SEASONAL BUY", "LEAN")
    )
    bear_n = sum(1 for s in actionable if s.get("verdict") in ("SELL", "SELL / AVOID", "STRONG SELL"))

    pdp_long = [s for s in actionable if s.get("tab") == "Pump & Dump" and "LONG" in str(s.get("strategy", ""))]
    pdp_short = [s for s in actionable if s.get("tab") == "Pump & Dump" and "SHORT" in str(s.get("strategy", ""))]

    if actionable and avg >= 6.5 and bull_n > bear_n:
        verdict = "STRONG BUY"
    elif actionable and avg >= 5.5 and bull_n >= bear_n and bull_n > 0:
        verdict = "BUY"
    elif actionable and avg <= 3.5 and bear_n > bull_n:
        verdict = "SELL / AVOID"
    elif pdp_long and not pdp_short:
        verdict = "BUY"
    elif pdp_short and not pdp_long:
        verdict = "SELL / AVOID"
    else:
        verdict = "WAIT"

    top = max(pool, key=lambda x: x.get("score", 0))
    plan = None
    action = (
        f"No aligned Buy/Sell across engines — {len(actionable)} actionable of "
        f"{len(enriched)} checks. Stay flat or wait for confluence."
    )
    if verdict in ("STRONG BUY", "BUY", "SELL / AVOID"):
        ref = max(actionable, key=lambda x: x.get("score", 0)) if actionable else top
        top_plan = ref.get("trade_plan") or make_trade_plan(timeframe=ref.get("timeframe", "1d"))
        plan = make_trade_plan(
            direction=top_plan.get("direction", "—"),
            timeframe=ref.get("timeframe", "1h"),
            stop_loss_pct=top_plan.get("stop_loss_pct"),
            take_profit_pct=top_plan.get("take_profit_pct"),
            expected_profit_pct=top_plan.get("expected_profit_pct"),
            confidence_pct=top_plan.get("confidence_pct"),
            exit_rule=f"Lead engine {ref.get('tab')}: {top_plan.get('exit_rule', '')}",
            max_hold_exit=top_plan.get("max_hold_exit", ""),
        )
        action = ""

    reason_lines = [
        f"{s.get('tab')} ({s.get('timeframe', '')}): {s.get('score')}/10 — "
        f"{(s.get('recommendation') or s.get('verdict', ''))[:70]}"
        for s in sorted(pool, key=lambda x: -x.get("score", 0))[:6]
    ]
    if errors:
        reason_lines.append(f"{len(errors)} engine run(s) failed (see Errors tab in digest).")

    return make_summary(
        ticker=ticker, timeframe="All engines", tab="Mega Analyser",
        score=_clamp(avg), verdict=verdict, action=action, trade_plan=plan,
        summary=(
            f"{len(actionable)} actionable · {len(informative)} no-signal · "
            f"{len(errors)} error(s) · strongest leg: {top.get('tab')} ({top.get('score')}/10)."
        ),
        reasons=reason_lines,
    )


_MEGA_VERDICT_TO_DIRECTION = {
    "STRONG BUY": "LONG", "BUY": "LONG", "TOP PICK": "LONG", "DEPLOY": "LONG",
    "SELL / AVOID": "SHORT", "STRONG SELL": "SHORT",
}


def _apply_fundamentals_mega(summary: dict, ticker: str) -> None:
    """Combine a Mega Analyser ticker summary's verdict/score with Fundamental
    Analysis for the same ticker, in place — India only, opt-in via checkbox."""
    direction = _MEGA_VERDICT_TO_DIRECTION.get(summary.get("verdict", ""))
    if direction is None:
        return
    technical_score = summary.get("score", 5.0)
    confidence = technical_score * 10.0
    combo = combine_with_fundamentals(ticker, direction, confidence)
    summary["fundamentals_combo"] = combo
    summary["technical_score"] = technical_score
    if not combo.get("available"):
        return
    new_score = round(combo["combined_confidence_pct"] / 10.0, 1)
    summary["score"] = new_score
    if combo["combined_direction"] == "WAIT":
        summary["verdict"] = "WAIT"
        summary["recommendation"] = "WAIT (fundamentals disagree)" if combo.get("conflict") else "WAIT"
    plan = summary.get("trade_plan") or {}
    if plan:
        plan["direction"] = combo["combined_direction"] if combo["combined_direction"] != "WAIT" else plan.get("direction", "—")
        plan["confidence_pct"] = combo["combined_confidence_pct"]
        summary["trade_plan"] = plan


def build_mega_ai_prompt(ticker: str, market: str, summaries: list[dict], currency: str) -> str:
    lines = [
        "=== MEGA ANALYSER — UNIFIED MULTI-ENGINE REPORT ===",
        f"Ticker: {ticker}",
        f"Market: {market}",
        f"Currency: {currency}",
        f"Total analysis legs: {len(summaries)}",
        "",
    ]
    for s in sorted(summaries, key=lambda x: (-x.get("score", 0), x.get("tab", ""))):
        lines.append("─" * 48)
        lines.append(f"ENGINE: {s.get('tab', '')} | TF: {s.get('timeframe', '')} | Strategy: {s.get('strategy', '') or '—'}")
        lines.append(f"Score: {s.get('score', 0)}/10 | Verdict: {s.get('verdict', '')}")
        p = s.get("trade_plan") or {}
        if p:
            lines.append(
                f"Trade plan: {p.get('direction')} | Hold {p.get('holding_period')} | "
                f"SL -{p.get('stop_loss_pct')}% | TP +{p.get('take_profit_pct')}% | "
                f"Expected +{p.get('expected_profit_pct')}%"
            )
            lines.append(f"Exit: {p.get('exit_rule', '')}")
            lines.append(f"Time stop: {p.get('max_hold_exit', '')}")
        lines.append(f"Summary: {s.get('summary', '')}")
        lines.append(f"Action: {s.get('action', '')}")
        for r in s.get("reasons", [])[:3]:
            lines.append(f"  • {r}")
        lines.append("")
    return "\n".join(lines)


def _run_per_ticker_ta_scanners(
    ticker: str,
    *,
    market: str,
    timeframes: list[str],
    exchange: str,
    groww_token: str,
    modules: dict[str, bool],
    all_summaries: list[dict],
    by_ticker: dict,
    progress_callback,
    step: int,
    total_steps: int,
) -> int:
    """Run once-per-ticker TA hub scanners (fakeout, MTF, top-down, weekly stoch, KN Smart)."""
    from app.market_pulse.fakeout_15m_engine import (
        normalize_ohlcv,
        run_fakeout_screener as run_fakeout_15m,
        session_mode_for_market,
    )
    from app.market_pulse.fakeout_4h_engine import run_fakeout_screener as run_fakeout_4h
    from app.market_pulse.gap_trading import fetch_data_for_gap_scan
    from app.market_pulse.kn_smart_rsi_engine import MTF_DEFAULT, analyze_kn_smart
    from app.market_pulse.mtf_scanner_engine import TIMEFRAMES, analyze_ticker as analyze_mtf_ticker
    from app.market_pulse.top_down_mtf_engine import analyze_top_down
    from app.market_pulse.weekly_stoch_sweet_spot_engine import analyze_weekly_stoch

    session_mode = session_mode_for_market(market)

    def _tick(label: str) -> None:
        nonlocal step
        step += 1
        if progress_callback:
            progress_callback(step / max(total_steps, 1), label)

    def _store(summ: dict, key: str | None = None, payload: dict | None = None) -> None:
        all_summaries.append(summ)
        by_ticker[ticker]["summaries"].append(summ)
        if key is not None and payload is not None:
            by_ticker[ticker][key] = payload

    if modules.get("fakeout_15m"):
        _tick(f"Fakeout 15m: {ticker}")
        try:
            df = normalize_ohlcv(
                fetch_data_for_gap_scan(ticker, "1m", market, groww_token, exchange, limit=400),
            )
            if df.empty or len(df) < 25:
                _store(summarize_error(ticker, "1m", f"Insufficient 1M data ({len(df)} bars)", tab="1min-15min Breakout"))
            else:
                analysis = run_fakeout_15m(df, session_mode=session_mode)
                analysis["session_mode"] = session_mode
                summ = summarize_fakeout_15m(analysis, ticker)
                summ["tab"] = "1min-15min Breakout"
                _store(summ, "fakeout_15m", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "1m", str(ex)[:80], tab="1min-15min Breakout"))

    if modules.get("fakeout_4h"):
        _tick(f"Fakeout 4h: {ticker}")
        try:
            df = normalize_ohlcv(
                fetch_data_for_gap_scan(ticker, "5m", market, groww_token, exchange, limit=400),
            )
            if df.empty or len(df) < 25:
                _store(summarize_error(ticker, "5m", f"Insufficient 5M data ({len(df)} bars)", tab="5min-4h Breakout"))
            else:
                analysis = run_fakeout_4h(df, session_mode=session_mode)
                analysis["session_mode"] = session_mode
                summ = summarize_fakeout_4h(analysis, ticker)
                summ["tab"] = "5min-4h Breakout"
                _store(summ, "fakeout_4h", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "5m", str(ex)[:80], tab="5min-4h Breakout"))

    if modules.get("mtf_scanner"):
        _tick(f"MTF Scanner: {ticker}")
        try:
            mtf_tfs = [tf for tf in timeframes if tf in TIMEFRAMES] or ["15m", "1h", "4h", "1d"]
            analysis = analyze_mtf_ticker(ticker, mtf_tfs, market, groww_token, exchange, 300)
            if not analysis.get("timeframes"):
                _store(summarize_error(ticker, "MTF", "No timeframe had sufficient data.", tab="MTF Scanner"))
            else:
                summ = summarize_mtf_scanner(analysis, ticker)
                summ["tab"] = "MTF Scanner"
                _store(summ, "mtf_scanner", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "MTF", str(ex)[:80], tab="MTF Scanner"))

    if modules.get("top_down_mtf"):
        _tick(f"Top-Down MTF: {ticker}")
        try:
            from app.market_pulse.ta_mtf_hub_ui import get_ta_hub_mtf, ta_hub_mtf_applies

            if ta_hub_mtf_applies():
                hub = get_ta_hub_mtf()
                htf, mtf, ltf = hub["HTF"], hub["MTF"], hub["LTF"]
            else:
                htf = "15m" if "15m" in timeframes else (timeframes[0] if timeframes else "15m")
                mtf = "5m" if "5m" in timeframes else htf
                ltf = "1m" if "1m" in timeframes else mtf
            analysis = analyze_top_down(ticker, htf, mtf, ltf, market, groww_token, exchange, 300)
            if analysis.get("error"):
                _store(summarize_error(ticker, "Top-Down MTF", analysis["error"], tab="Top Down MTF"))
            else:
                summ = summarize_top_down_mtf(analysis, ticker)
                summ["tab"] = "Top Down MTF"
                _store(summ, "top_down_mtf", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "Top-Down MTF", str(ex)[:80], tab="Top Down MTF"))

    if modules.get("weekly_stoch"):
        _tick(f"Weekly Stoch: {ticker}")
        try:
            analysis = analyze_weekly_stoch(ticker, market, groww_token, exchange, period="5y")
            if analysis.get("error"):
                _store(summarize_error(ticker, "Weekly", analysis["error"], tab="Weekly Stoch Sweet Spot"))
            else:
                summ = summarize_weekly_stoch_sweet_spot(analysis, ticker)
                summ["tab"] = "Weekly Stoch Sweet Spot"
                _store(summ, "weekly_stoch", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "Weekly", str(ex)[:80], tab="Weekly Stoch Sweet Spot"))

    if modules.get("kn_smart_rsi"):
        _tick(f"KN Smart: {ticker}")
        try:
            intraday_tf = "5m" if "5m" in timeframes else ("3m" if "3m" in timeframes else "5m")
            mtf_tfs = [tf for tf in ("1m", "5m", "15m", "1h") if tf in timeframes] or list(MTF_DEFAULT)
            analysis = analyze_kn_smart(
                ticker, market, intraday_tf, mtf_tfs, groww_token, exchange, 400,
            )
            if analysis.get("error"):
                _store(summarize_error(ticker, intraday_tf, analysis["error"], tab="KN Smart RSI MTF"))
            else:
                summ = summarize_kn_smart_rsi(analysis, ticker)
                summ["tab"] = "KN Smart RSI MTF"
                _store(summ, "kn_smart_rsi", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "5m", str(ex)[:80], tab="KN Smart RSI MTF"))

    if modules.get("velez_retracement"):
        _tick(f"Velez Retracement: {ticker}")
        try:
            from app.market_pulse.velez_retracement_engine import analyze_velez, fetch_velez_data

            velez_tf = "5m" if "5m" in timeframes else ("2m" if "1m" in timeframes else "5m")
            df = fetch_velez_data(ticker, velez_tf, market, groww_token, exchange, limit=600)
            if df.empty or len(df) < 220:
                _store(summarize_error(
                    ticker, velez_tf,
                    f"Insufficient data ({len(df)} bars) for Velez SMA 20/200",
                    tab="Velez Retracement",
                ))
            else:
                analysis = analyze_velez(df, chart_tf=velez_tf)
                summ = summarize_velez_retracement(analysis, ticker)
                summ["tab"] = "Velez Retracement"
                _store(summ, "velez_retracement", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "5m", str(ex)[:80], tab="Velez Retracement"))

    if modules.get("mtf_intraday_bias"):
        _tick(f"MTF Intraday Bias: {ticker}")
        try:
            from app.market_pulse.mtf_intraday_bias_engine import analyze_ticker as analyze_mtf_bias

            is_crypto = is_crypto_market(market)
            analysis = analyze_ticker(ticker, is_crypto=is_crypto)
            if analysis.get("error"):
                _store(summarize_error(ticker, "Session", analysis["error"], tab="MTF Intraday Bias"))
            else:
                summ = summarize_mtf_intraday_bias(analysis, ticker)
                summ["tab"] = "MTF Intraday Bias"
                _store(summ, "mtf_intraday_bias", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "Session", str(ex)[:80], tab="MTF Intraday Bias"))

    if modules.get("smart_wave_crypto") and is_crypto_market(market):
        _tick(f"Smart Wave Crypto: {ticker}")
        try:
            from app.market_pulse.smart_wave_crypto_engine import (
                STRATEGY_KEYS,
                analyze_smart_wave,
            )

            sw_tf = "30m" if "30m" in timeframes else ("1h" if "1h" in timeframes else "30m")
            analysis = analyze_smart_wave(
                ticker,
                market=market,
                strategies=list(STRATEGY_KEYS),
                primary_tf=sw_tf,
                groww_token=groww_token,
                exchange=exchange,
            )
            if analysis.get("error"):
                _store(summarize_error(ticker, sw_tf, analysis["error"], tab="Smart Wave Crypto"))
            else:
                summ = summarize_smart_wave_crypto(analysis, ticker)
                summ["tab"] = "Smart Wave Crypto"
                _store(summ, "smart_wave_crypto", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "30m", str(ex)[:80], tab="Smart Wave Crypto"))

    if modules.get("crypto_scalping") and is_crypto_market(market):
        _tick(f"Crypto Scalping: {ticker}")
        try:
            from app.market_pulse.crypto_scalping_engine import (
                analyze_crypto_scalping,
                fetch_scalping_data,
            )

            scalp_tf = "5m" if "5m" in timeframes else ("1m" if "1m" in timeframes else "5m")
            df = fetch_scalping_data(
                ticker, scalp_tf, market, groww_token, exchange, limit=800,
            )
            analysis = analyze_crypto_scalping(df, chart_tf=scalp_tf)
            if analysis.get("phase") == "NO_DATA":
                _store(summarize_error(
                    ticker, scalp_tf,
                    analysis.get("primary_label", "Insufficient scalping data"),
                    tab="Crypto Scalping",
                ))
            else:
                summ = summarize_crypto_scalping(analysis, ticker)
                summ["tab"] = "Crypto Scalping"
                _store(summ, "crypto_scalping", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "5m", str(ex)[:80], tab="Crypto Scalping"))

    if modules.get("smc_fake_market_shift") and (
        is_crypto_market(market) or is_india_market(market)
    ):
        _tick(f"SMC Fake Market Shift: {ticker}")
        try:
            from app.market_pulse.smc_fake_market_shift_engine import (
                analyze_smc_fake_market_shift,
                fetch_fms_data,
            )

            fms_tf = next(
                (tf for tf in ("15m", "5m", "30m", "1h", "4h", "1d") if tf in timeframes),
                "15m",
            )
            df = fetch_fms_data(
                ticker, fms_tf, market, groww_token, exchange, limit=600,
            )
            analysis = analyze_smc_fake_market_shift(df, chart_tf=fms_tf)
            if analysis.get("phase") == "NO_DATA":
                _store(summarize_error(
                    ticker, fms_tf,
                    analysis.get("primary_label", "Insufficient FMS data"),
                    tab="SMC Fake Market Shift",
                ))
            else:
                summ = summarize_smc_fake_market_shift(analysis, ticker)
                summ["tab"] = "SMC Fake Market Shift"
                _store(summ, "smc_fake_market_shift", analysis)
        except Exception as ex:
            _store(summarize_error(ticker, "15m", str(ex)[:80], tab="SMC Fake Market Shift"))

    return step


def _run_mega_scan(
    *,
    market: str,
    tickers: list[str],
    timeframes: list[str],
    start_date: date,
    end_date: date,
    exchange: str,
    groww_token: str,
    capital: float,
    commission: float,
    slippage: float,
    tb_candles: int,
    gap_min_pct: float,
    seasonality_years: int,
    conf_fib_lb: int,
    conf_st_period: int,
    conf_st_mult: float,
    modules: dict[str, bool],
    mobile: str,
    progress_callback=None,
) -> dict:
    is_crypto = is_crypto_market(market)
    if not is_crypto:
        modules = {**modules, "smart_wave_crypto": False, "crypto_scalping": False}
    if not is_crypto and not is_india_market(market):
        modules = {**modules, "smc_fake_market_shift": False}
    all_summaries: list[dict] = []
    by_ticker: dict = {}
    ticker_scanner_count = sum(1 for m in MEGA_TICKER_SCANNER_MODULES if modules.get(m))
    total_steps = (
        len(tickers) * len(timeframes)
        + (len(tickers) if modules.get("seasonality") else 0)
        + len(tickers) * ticker_scanner_count
    )
    step = 0

    indicators: list = []
    entry_rules: list = []
    exit_rules: list = []
    entry_mode = "ALL (AND)"

    saved_strats = []
    if modules.get("saved_strategies") and mobile:
        saved_strats = get_strategies_by_mobile(mobile)[:5]

    season_data = {}
    if modules.get("seasonality"):
        season_data = fetch_seasonality_data(tickers, years=seasonality_years)

    stock_lookup: dict = {}
    if modules.get("smc_flow"):
        try:
            stock_lookup = _smc_fetch_bhavcopy_lookup()
        except Exception:
            stock_lookup = {}

    for ticker in tickers:
        by_ticker[ticker] = {"by_tf": {}, "seasonality": None, "summaries": []}

        if modules.get("seasonality") and ticker in season_data:
            step += 1
            if progress_callback:
                progress_callback(step / max(total_steps, 1), f"Seasonality: {ticker}")
            try:
                df_s = season_data[ticker].copy()
                if isinstance(df_s.columns, pd.MultiIndex):
                    df_s.columns = df_s.columns.get_level_values(0)
                pivot, stats_df = compute_seasonality(df_s)
                if stats_df is not None and not stats_df.empty:
                    signals_df = generate_signals(stats_df)
                    bt_metrics = run_seasonal_backtest(df_s, signals_df)
                    summ = summarize_seasonality(bt_metrics, ticker)
                    summ["tab"] = "Seasonality"
                    all_summaries.append(summ)
                    by_ticker[ticker]["seasonality"] = summ
                    by_ticker[ticker]["summaries"].append(summ)
            except Exception as ex:
                err = summarize_error(ticker, "Seasonal", str(ex)[:80], tab="Seasonality")
                all_summaries.append(err)
                by_ticker[ticker]["summaries"].append(err)

        for tf in timeframes:
            step += 1
            if progress_callback:
                progress_callback(step / max(total_steps, 1), f"{ticker} | {tf}")
            tf_block = {"summaries": [], "df": None}
            by_ticker[ticker]["by_tf"][tf] = tf_block

            try:
                df = get_historical_data(
                    symbol=ticker,
                    start_date=str(start_date),
                    end_date=str(end_date),
                    market=market,
                    timeframe=tf,
                    groww_token=groww_token,
                    groww_exchange=exchange,
                )
            except Exception as ex:
                err = summarize_error(ticker, tf, str(ex)[:100], tab="Data")
                all_summaries.append(err)
                tf_block["summaries"].append(err)
                by_ticker[ticker]["summaries"].append(err)
                continue

            if df.empty or len(df) < 20:
                err = summarize_error(ticker, tf, f"Insufficient data ({len(df)} bars)", tab="Data")
                all_summaries.append(err)
                tf_block["summaries"].append(err)
                by_ticker[ticker]["summaries"].append(err)
                continue

            tf_block["df"] = df

            if modules.get("backtest"):
                try:
                    df_ind = calculate_dynamic_indicators(df, indicators)
                    res = run_true_backtest(
                        df=df_ind,
                        entry_rules=entry_rules,
                        exit_rules=exit_rules,
                        entry_mode="AND" if "ALL" in entry_mode.upper() else "OR",
                        exit_mode="AND",
                        initial_capital=capital,
                        commission=commission,
                        slippage=slippage,
                        sl_pct=0.0,
                        tp_pct=0.0,
                    )
                    summ = summarize_backtest_metrics(
                        res["metrics"], ticker, tf, "Current Custom Strategy",
                    )
                    summ["tab"] = "Strategy Builder"
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Strategy Builder")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("saved_strategies"):
                for strat in saved_strats:
                    try:
                        s_ind = json.loads(strat["indicators"])
                        s_ent = json.loads(strat["entry_rules"])
                        s_ext = json.loads(strat["exit_rules"])
                        df_ind = calculate_dynamic_indicators(df, s_ind)
                        res = run_true_backtest(
                            df=df_ind, entry_rules=s_ent, exit_rules=s_ext,
                            entry_mode="AND", exit_mode="AND",
                            initial_capital=capital, commission=commission, slippage=slippage,
                            sl_pct=0.0, tp_pct=0.0,
                        )
                        summ = summarize_backtest_metrics(
                            res["metrics"], ticker, tf, f"Saved: {strat['name']}",
                        )
                        summ["tab"] = "Saved Strategy"
                        all_summaries.append(summ)
                        tf_block["summaries"].append(summ)
                        by_ticker[ticker]["summaries"].append(summ)
                    except Exception:
                        pass

            if modules.get("sentiment"):
                try:
                    analysis = _analyze_sentiment(df, market, tf)
                    row = {
                        "Ticker": ticker, "Timeframe": tf,
                        "Score": analysis["score"], "Rating": analysis["rating"],
                        "Insights": analysis["insights"],
                        "Trade Signal": analysis.get("trade_signal", "WAIT"),
                        "trade_confidence": analysis.get("trade_confidence", 0),
                        "SL %": analysis.get("sl_pct", 0.0),
                        "TP %": analysis.get("tp_pct", 0.0),
                    }
                    summ = summarize_sentiment_row(row)
                    summ["tab"] = "Sentiment"
                    tf_block["sentiment_row"] = row
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Sentiment")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("price_action"):
                try:
                    pa = run_full_analysis(df, is_crypto=is_crypto)
                    summ = summarize_price_action(pa, ticker, tf)
                    summ["tab"] = "Price Action"
                    tf_block["price_action"] = pa
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Price Action")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("top_bottom"):
                try:
                    metrics = calculate_top_bottom_metrics(df, window=tb_candles)
                    if metrics:
                        if modules.get("tb_forecast"):
                            try:
                                sr_tb = detect_support_resistance(df, window=5, num_levels=3)
                                supports = [s["price"] for s in sr_tb.get("supports", [])]
                                resistances = [r["price"] for r in sr_tb.get("resistances", [])]
                                candles_tb = detect_candlestick_patterns(df)
                                charts_tb = detect_chart_patterns(df)
                                metrics["forecast"] = compute_top_bottom_forecast(
                                    df,
                                    metrics,
                                    ticker,
                                    market,
                                    exchange,
                                    groww_token,
                                    candle_patterns=candles_tb,
                                    chart_patterns=charts_tb,
                                    supports=supports,
                                    resistances=resistances,
                                    lookback=tb_candles,
                                    timeframe=tf,
                                )
                            except Exception as fc_ex:
                                metrics["forecast_error"] = str(fc_ex)[:80]
                        summ = summarize_top_bottom(metrics, ticker, tf)
                        summ["tab"] = "Top/Bottom"
                        tf_block["top_bottom"] = metrics
                        all_summaries.append(summ)
                        tf_block["summaries"].append(summ)
                        by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Top/Bottom")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("find_sr"):
                try:
                    fsr = _run_find_sr_analysis(df, tf, sr_window=5)
                    summ = _summarize_find_sr(fsr, ticker, tf)
                    summ["tab"] = "Find S/R"
                    tf_block["find_sr"] = fsr
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Find S/R")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("weak_strong_sr"):
                try:
                    if len(df) < 45:
                        summ = make_summary(
                            ticker=ticker, timeframe=tf, tab="Weak Strong S-R",
                            score=3.0, verdict="NO SETUP",
                            action="Need at least 45 bars for weak/strong S/R scoring.",
                            summary=f"Only {len(df)} bars available.",
                            trade_plan=None,
                        )
                    else:
                        from app.market_pulse.weak_strong_sr_engine import analyze_weak_strong_sr

                        wssr = analyze_weak_strong_sr(
                            df,
                            chart_tf=tf,
                            sr_window=5,
                            st_period=conf_st_period,
                            st_mult=conf_st_mult,
                            is_crypto=is_crypto,
                        )
                        summ = summarize_weak_strong_sr(wssr, ticker, timeframe=tf)
                        summ["tab"] = "Weak Strong S-R"
                        tf_block["weak_strong_sr"] = wssr
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Weak Strong S-R")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("pattern_breakout"):
                try:
                    pbo = run_pattern_breakout_analysis(df, tf, is_crypto=is_crypto)
                    summ = summarize_pattern_breakout(pbo, ticker, tf)
                    summ["tab"] = "Pattern & Breakout"
                    tf_block["pattern_breakout"] = pbo
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Pattern & Breakout")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("confluence"):
                try:
                    if len(df) < 40:
                        summ = make_summary(
                            ticker=ticker, timeframe=tf, tab="Confluence Strategy",
                            score=3.0, verdict="NO SETUP",
                            action="Need at least 40 bars for confluence scoring.",
                            summary=f"Only {len(df)} bars available.",
                            trade_plan=None,
                        )
                    else:
                        conf = analyze_confluence_strategy(
                            df,
                            sr_window=5,
                            fib_lookback=conf_fib_lb,
                            st_period=conf_st_period,
                            st_mult=conf_st_mult,
                            is_crypto=is_crypto,
                        )
                        summ = summarize_confluence_strategy(conf, ticker, tf)
                        summ["tab"] = "Confluence Strategy"
                        tf_block["confluence"] = conf
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Confluence Strategy")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("elliott_wave"):
                try:
                    ew = analyze_elliott_waves(df, zigzag_pct=3.0)
                    summ = summarize_elliott_wave(ew, ticker, tf)
                    summ["tab"] = "Elliott Wave"
                    tf_block["elliott_wave"] = ew
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Elliott Wave")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("smc_flow"):
                try:
                    df_smc = _smc_flatten_ohlc(df) or _df_title_case_ohlc(df)
                    smc = _smc_analyze_from_ohlcv(df_smc)
                    close_col = "Close" if "Close" in df_smc.columns else "close"
                    smc["last_close"] = _smc_as_float(df_smc[close_col].iloc[-1])
                    sym = ticker.upper().split("-")[0]
                    flow = stock_lookup.get(sym, {})
                    med_del = flow.get("delivery_pct", 0)
                    med_turn = flow.get("turnover_cr", 0)
                    pct_chg = None
                    if len(df_smc) >= 2:
                        prev = _smc_as_float(df_smc[close_col].iloc[-2])
                        if prev > 0:
                            pct_chg = (_smc_as_float(df_smc[close_col].iloc[-1]) / prev - 1) * 100
                    pred = _smc_predict_next_move(
                        smc=smc,
                        flow=flow or None,
                        pcr_data=None,
                        pct_chg=pct_chg,
                        median_delivery=med_del,
                        median_turnover=med_turn,
                        is_index=False,
                    )
                    summ = summarize_smc_ticker(ticker, tf, smc, pred, flow)
                    summ["tab"] = "SMC Flow"
                    tf_block["smc_flow"] = {"smc": smc, "prediction": pred, "flow": flow}
                    all_summaries.append(summ)
                    tf_block["summaries"].append(summ)
                    by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="SMC Flow")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("pump_dump"):
                try:
                    htf = _mega_htf_for(tf)
                    if is_crypto:
                        from app.market_pulse.pump_dump_predictor import analyze_crypto_pair
                        pdp = analyze_crypto_pair(ticker, tf, htf)
                    else:
                        from app.market_pulse.india_pump_dump_predictor import analyze_india_ticker
                        pdp = analyze_india_ticker(ticker, tf, htf, groww_token, exchange)
                    if pdp.error:
                        err = summarize_error(ticker, tf, pdp.error[:100], tab="Pump & Dump")
                        all_summaries.append(err)
                        tf_block["summaries"].append(err)
                    else:
                        cl, cs = pdp.confluence_long, pdp.confluence_short
                        if (cl.get("total", 0) or 0) >= (cs.get("total", 0) or 0):
                            side, conf = "LONG", cl
                        else:
                            side, conf = "SHORT", cs
                        summ = summarize_pump_dump_mega(
                            pdp, side, conf, ticker, tf, is_crypto=is_crypto,
                        )
                        summ["tab"] = "Pump & Dump"
                        tf_block["pump_dump"] = {"analysis": pdp, "side": side, "conf": conf}
                        all_summaries.append(summ)
                        tf_block["summaries"].append(summ)
                        by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Pump & Dump")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("gap"):
                try:
                    gap_df = fetch_data_for_gap_scan(
                        ticker, tf, market, groww_token=groww_token, exchange=exchange, limit=120,
                    )
                    setups = generate_gap_trade_setups(
                        gap_df if not gap_df.empty else df,
                        ticker, tf, is_crypto=is_crypto, min_gap_pct=gap_min_pct, mode="both",
                    )
                    if setups:
                        best = max(setups, key=lambda s: float(s.get("rr_ratio", 0) or 0))
                        summ = summarize_gap_setup(best)
                        summ["tab"] = "Gap Scanner"
                        tf_block["gap_setup"] = best
                        all_summaries.append(summ)
                        tf_block["summaries"].append(summ)
                        by_ticker[ticker]["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Gap Scanner")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            if modules.get("screener"):
                try:
                    matched = _eval_screener_signal(df, indicators, entry_rules, entry_mode)
                    if matched:
                        summ = summarize_screener_match(ticker, tf, "BUY")
                        summ["tab"] = "Screener"
                        all_summaries.append(summ)
                        tf_block["summaries"].append(summ)
                        by_ticker[ticker]["summaries"].append(summ)
                    else:
                        summ = make_summary(
                            ticker=ticker, timeframe=tf, tab="Screener",
                            score=3.0, verdict="NO MATCH",
                            action="No trade — open Strategy Builder to adjust entry rules if you expected a signal.",
                            summary="Latest candle did not satisfy your screener entry formula.",
                            reasons=[
                                "This is not an error — it means no buy/sell trigger fired.",
                                "Tune indicators or thresholds in Strategy Builder, or try another timeframe.",
                            ],
                            trade_plan=None,
                        )
                        all_summaries.append(summ)
                        tf_block["summaries"].append(summ)
                except Exception as ex:
                    err = summarize_error(ticker, tf, str(ex)[:80], tab="Screener")
                    all_summaries.append(err)
                    tf_block["summaries"].append(err)

            time.sleep(0.03)

        step = _run_per_ticker_ta_scanners(
            ticker,
            market=market,
            timeframes=timeframes,
            exchange=exchange,
            groww_token=groww_token,
            modules=modules,
            all_summaries=all_summaries,
            by_ticker=by_ticker,
            progress_callback=progress_callback,
            step=step,
            total_steps=total_steps,
        )

    return {
        "summaries": all_summaries,
        "by_ticker": by_ticker,
        "market": market,
        "tickers": tickers,
        "timeframes": timeframes,
        "tb_candles": tb_candles,
    }


def _mega_build_run_config(
    *,
    market: str,
    timeframes: list[str],
    start_date: date,
    end_date: date,
    exchange: str,
    capital: float,
    tb_candles: int,
    gap_min_pct: float,
    seasonality_years: int,
    conf_fib_lb: int,
    conf_st_period: int,
    conf_st_mult: float,
    modules: dict[str, bool],
    mobile: str,
) -> dict:
    """Serializable scan settings for batch continuation."""
    return {
        "market": market,
        "timeframes": list(timeframes),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "exchange": exchange,
        "capital": capital,
        "commission": 0.001,
        "slippage": 0.0005,
        "tb_candles": tb_candles,
        "gap_min_pct": gap_min_pct,
        "seasonality_years": seasonality_years,
        "conf_fib_lb": conf_fib_lb,
        "conf_st_period": conf_st_period,
        "conf_st_mult": conf_st_mult,
        "modules": dict(modules),
        "mobile": mobile or "",
    }


def _mega_run_batch(
    tickers: list[str],
    run_config: dict,
    *,
    progress_callback=None,
) -> dict:
    """Run mega scan for one ticker batch using stored config."""
    groww_token = get_active_groww_token()
    return _run_mega_scan(
        market=run_config["market"],
        tickers=tickers,
        timeframes=run_config["timeframes"],
        start_date=date.fromisoformat(run_config["start_date"]),
        end_date=date.fromisoformat(run_config["end_date"]),
        exchange=run_config["exchange"],
        groww_token=groww_token,
        capital=float(run_config["capital"]),
        commission=float(run_config.get("commission", 0.001)),
        slippage=float(run_config.get("slippage", 0.0005)),
        tb_candles=int(run_config["tb_candles"]),
        gap_min_pct=float(run_config["gap_min_pct"]),
        seasonality_years=int(run_config["seasonality_years"]),
        conf_fib_lb=int(run_config["conf_fib_lb"]),
        conf_st_period=int(run_config["conf_st_period"]),
        conf_st_mult=float(run_config["conf_st_mult"]),
        modules=run_config["modules"],
        mobile=run_config.get("mobile", ""),
        progress_callback=progress_callback,
    )


def _mega_start_batched_run(all_tickers: list[str], run_config: dict, *, progress_callback=None) -> dict:
    """Run first batch and initialize lazy-load session state."""
    batch_tickers = all_tickers[:MEGA_BATCH_SIZE]
    batch_result = _mega_run_batch(batch_tickers, run_config, progress_callback=progress_callback)
    return {
        "batches": [batch_result],
        "all_tickers": list(all_tickers),
        "next_index": len(batch_tickers),
        "run_config": run_config,
        "batch_size": MEGA_BATCH_SIZE,
    }


def _mega_append_next_batch(mega_state: dict, *, progress_callback=None) -> dict:
    """Run and append the next ticker batch to an in-progress mega run."""
    all_tickers = mega_state.get("all_tickers") or []
    next_index = int(mega_state.get("next_index", 0))
    run_config = mega_state.get("run_config") or {}
    if next_index >= len(all_tickers):
        return mega_state

    batch_tickers = all_tickers[next_index: next_index + MEGA_BATCH_SIZE]
    batch_result = _mega_run_batch(batch_tickers, run_config, progress_callback=progress_callback)
    batches = list(mega_state.get("batches") or [])
    batches.append(batch_result)
    return {
        **mega_state,
        "batches": batches,
        "next_index": next_index + len(batch_tickers),
    }


def _mega_batches_pending(mega_state: dict | None) -> bool:
    if not mega_state:
        return False
    all_tickers = mega_state.get("all_tickers") or []
    return int(mega_state.get("next_index", 0)) < len(all_tickers)


def _mega_pending_count(mega_state: dict | None) -> int:
    if not mega_state:
        return 0
    all_tickers = mega_state.get("all_tickers") or []
    return max(0, len(all_tickers) - int(mega_state.get("next_index", 0)))


def _render_mega_analyser_results(
    results: dict,
    *,
    provider: str,
    model: str,
    api_key: str,
) -> None:
    """Digest + per-ticker breakdown (shown above settings when a run exists)."""
    market_display = results.get("market", st.session_state.get("mega_market", ""))
    currency = market_currency(market_display)
    all_summaries = results.get("summaries", [])
    by_ticker = results.get("by_ticker", {})
    stored_tb_candles = results.get("tb_candles", st.session_state.get("mega_tb_candles", 100))

    st.markdown("## 📋 Mega Analysis Results")
    st.caption(
        f"**{len(results.get('tickers', []))}** tickers · "
        f"**{', '.join(results.get('timeframes', []))}** · {market_display}"
    )
    render_run_digest(
        all_summaries,
        title="🧭 Mega Digest — Every Engine · Every Run",
        group_filter=True,
    )

    st.markdown("### 📊 Per-Ticker Breakdown")

    if not api_key:
        st.info("Set `GROQ_API_KEY` or `GEMINI_API_KEY` in `.env` for **AI View**.")

    for ti, ticker in enumerate(results.get("tickers", [])):
        tdata = by_ticker.get(ticker, {})
        t_summaries = tdata.get("summaries", [])
        if not t_summaries:
            continue

        mega_ticker_summary = summarize_mega_ticker(ticker, t_summaries)
        mega_rec = mega_ticker_summary.get("recommendation") or mega_ticker_summary.get("verdict", "")
        with st.expander(
            f"**{ticker}** — {mega_rec[:72]}",
            expanded=(ti == 0),
        ):
            render_run_summary(mega_ticker_summary)
            primary_tf = (results.get("timeframes") or ["1d"])[0]
            render_strategy_mtf_panel(
                symbol=ticker,
                market=market_display,
                groww_token=get_active_groww_token(),
                exchange=st.session_state.get("mega_exchange", "NSE"),
                primary_tf=primary_tf,
                strategy_direction=mega_ticker_summary.get("direction"),
            )

            if api_key:
                mtf_ticker_button("mega", ticker, button_in_column=False)
                render_mtf_ai_view_report(
                    "mega",
                    ticker,
                    lambda t=ticker, s=t_summaries, m=market_display, c=currency: build_mega_ai_prompt(t, m, s, c),
                    MEGA_AI_SYSTEM,
                    provider, model, api_key,
                    len(t_summaries),
                )

            if tdata.get("seasonality"):
                st.markdown("##### 🗓️ Seasonality")
                render_run_summary(tdata["seasonality"], compact=True)

            for tf in results.get("timeframes", []):
                tf_data = tdata.get("by_tf", {}).get(tf)
                if not tf_data or not tf_data.get("summaries"):
                    continue
                st.markdown(f"##### ⏱️ {tf}")
                for summ in tf_data["summaries"]:
                    render_run_summary(summ, compact=True)

                if api_key and tf_data.get("summaries"):
                    ai_key = f"{ticker}|{tf}"
                    pa = tf_data.get("price_action")
                    sent_row = tf_data.get("sentiment_row")
                    gap_setup = tf_data.get("gap_setup")
                    find_sr = tf_data.get("find_sr")
                    pbo = tf_data.get("pattern_breakout")
                    confluence = tf_data.get("confluence")
                    tb_metrics = tf_data.get("top_bottom")
                    smc_block = tf_data.get("smc_flow")
                    pdp_block = tf_data.get("pump_dump")
                    tf_df = tf_data.get("df")

                    def _build_tf_ai(
                        _pa=pa, _sent=sent_row, _gap=gap_setup,
                        _fsr=find_sr, _pbo=pbo, _conf=confluence,
                        _tb=tb_metrics, _smc=smc_block, _pdp=pdp_block,
                        _df=tf_df, _t=ticker, _tf=tf, _m=market_display, _c=currency,
                        _tb_lb=stored_tb_candles,
                    ):
                        sections = []
                        if _sent:
                            sections.append(build_sentiment_ai_prompt(_sent, _m))
                        if _fsr:
                            sections.append(_build_find_sr_ai_prompt(_t, _tf, _m, _fsr, _c))
                        if _pbo:
                            sections.append(build_pattern_breakout_ai_prompt(_t, _tf, _m, _pbo, _c))
                        if _conf:
                            sections.append(build_confluence_ai_prompt(_t, _tf, _m, _conf, _c))
                        if _pa:
                            sections.append(build_price_action_ai_prompt(_t, _tf, _m, _pa, _c))
                        if _tb and _df is not None and not _df.empty:
                            sr_tb = detect_support_resistance(_df, window=5, num_levels=3)
                            sections.append(build_top_bottom_ai_prompt(
                                _t, _tf, _m, _tb,
                                detect_candlestick_patterns(_df),
                                detect_chart_patterns(_df),
                                [s["price"] for s in sr_tb.get("supports", [])],
                                [r["price"] for r in sr_tb.get("resistances", [])],
                                _tb_lb, _c,
                            ))
                        if _smc:
                            sections.append(
                                f"=== SMC FLOW ===\n{_t} {_tf}\n"
                                f"SMC: {json.dumps(_smc.get('smc', {}), indent=2)[:1200]}\n"
                                f"Prediction: {json.dumps(_smc.get('prediction', {}), indent=2)[:800]}"
                            )
                        if _gap:
                            sections.append(build_gap_ai_prompt(_gap, _m, _c))
                        if _pdp:
                            pa_obj = _pdp.get("analysis")
                            side = _pdp.get("side", "")
                            conf = _pdp.get("conf") or {}
                            if pa_obj:
                                sections.append(
                                    f"=== PUMP & DUMP ({side}) ===\n"
                                    f"{_t} entry {_tf} HTF {getattr(pa_obj, 'htf', '')} "
                                    f"({getattr(pa_obj, 'htf_trend', '')})\n"
                                    f"Score {conf.get('total')}/100 · {conf.get('verdict')} · "
                                    f"signals {conf.get('signal_count')}\n"
                                    f"Bias {getattr(pa_obj, 'bias', '')} · "
                                    f"warnings {getattr(pa_obj, 'expert_warnings', [])}\n"
                                )
                        if not sections:
                            return f"No detailed AI blocks for {_t} {_tf}"
                        return combine_timeframe_sections(
                            f"MEGA ANALYSER — {_t} {_tf}", _t, sections, market=_m,
                        )

                    show_ai_view_block(
                        "mega_tf", ai_key, ticker, tf,
                        _build_tf_ai, MTF_AI_SYSTEM,
                        provider, model, api_key,
                        button_in_column=False,
                    )


def _render_mega_analyser_settings(get_logged_in_mobile) -> None:
    """Configuration widgets and run handler (inside collapsed expander when results exist)."""

    def _mega_scenario_changed() -> None:
        sel = st.session_state.get("mega_scenario", "")
        if sel and sel != "Custom (use controls below)":
            _apply_mega_scenario(sel)

    scenario = st.selectbox(
        "Analysis scenario",
        list(MEGA_SCENARIOS.keys()),
        index=1,
        key="mega_scenario",
        help="Presets tune timeframes and engines. Choose Custom to use checkboxes below.",
        on_change=_mega_scenario_changed,
    )
    if "mega_scenario_boot" not in st.session_state:
        _apply_mega_scenario(scenario)
        st.session_state["mega_scenario_boot"] = True
    if scenario != "Custom (use controls below)":
        st.caption(
            f"**{scenario}** — suggested TFs: "
            f"{', '.join(MEGA_SCENARIOS[scenario].get('timeframes', []))} "
            "(change scenario to re-apply; use Custom for full control)"
        )

    col_m, col_t = st.columns([1, 2])
    with col_m:
        market = st.selectbox(
            "Market",
            MARKET_OPTIONS,
            key="mega_market",
        )
    with col_t:
        if is_crypto_market(market):
            tickers = render_coindcx_ticker_selection("mega")
            exchange = "NSE"
        else:
            if is_india_market(market):
                exchange = st.selectbox("Exchange", ["NSE", "BSE"], key="mega_exchange")
            else:
                exchange = "NSE"
            tickers = render_equity_index_ticker_selection(market, "mega")

    if "mega_timeframes" not in st.session_state:
        st.session_state["mega_timeframes"] = ["1h", "1d"]
    timeframes = st.multiselect(
        "Timeframes", ALL_TIMEFRAMES, key="mega_timeframes",
    )
    if "1m" in timeframes:
        st.caption(
            "ℹ️ **1m** data is limited to ~7 days of history — set **From** date accordingly for best results."
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        start_date = st.date_input("From", value=date.today() - timedelta(days=365), key="mega_start")
    with c2:
        end_date = st.date_input("To", value=date.today(), key="mega_end")
    with c3:
        capital = st.number_input("Capital", value=100000.0, step=10000.0, key="mega_capital")

    st.markdown("#### Analysis engines (all run per ticker × timeframe)")
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    with mc1:
        st.caption("**Strategy Lab**")
        mod_backtest = st.checkbox("Strategy Builder", value=True, key="mega_mod_bt")
        mod_saved = st.checkbox("Saved Strategies", value=True, key="mega_mod_saved")
        mod_scr = st.checkbox("Screener rules", value=True, key="mega_mod_scr")
        mod_season = st.checkbox("Seasonality", value=True, key="mega_mod_season")
    with mc2:
        st.caption("**Core TA**")
        mod_sentiment = st.checkbox("Trend & Sentiment", value=True, key="mega_mod_sent")
        mod_pa = st.checkbox("Price Action", value=True, key="mega_mod_pa")
        mod_find_sr = st.checkbox("Find S/R (S1/S2/R1/R2)", value=True, key="mega_mod_fsr")
        mod_wssr = st.checkbox(
            "Weak Strong S-R (VWAP·Vol·ST·RSI)",
            value=True,
            key="mega_mod_wssr",
            help="Strong support→buy · weak support→sell · weak resistance→buy · strong resistance→sell.",
        )
    with mc3:
        st.caption("**Patterns & confluence**")
        mod_pbo = st.checkbox("Pattern & Breakout", value=True, key="mega_mod_pbo")
        mod_confluence = st.checkbox(
            "Confluence (Fib·VWAP·ST·ATR·Vol·S/R)",
            value=True,
            key="mega_mod_conf",
        )
        mod_ew = st.checkbox("Elliott Wave", value=True, key="mega_mod_ew")
    with mc4:
        st.caption("**Structure & flow**")
        mod_tb = st.checkbox("Top/Bottom", value=True, key="mega_mod_tb")
        mod_smc = st.checkbox("SMC Flow (stock)", value=True, key="mega_mod_smc")
        mod_gap = st.checkbox("Gap Scanner", value=True, key="mega_mod_gap")
        mod_pdp = st.checkbox(
            "Pump & Dump Predictor",
            value=False,
            key="mega_mod_pdp",
            help="Pre-pump/pre-dump confluence + India expert boosters (RS, OI matrix, bulk deals, time traps).",
        )
    with mc5:
        st.caption("**Confluence params**")
        conf_fib_lb = st.slider("Fib lookback", 30, 200, 100, 10, key="mega_conf_fib")
        conf_st_p = st.slider("Supertrend period", 7, 21, 10, key="mega_conf_st_p")
        conf_st_m = st.slider("ST multiplier", 1.5, 5.0, 3.0, 0.5, key="mega_conf_st_m")

    st.markdown("#### TA hub scanners (once per ticker)")
    ns1, ns2, ns3, ns4, ns5 = st.columns(5)
    with ns1:
        mod_f15 = st.checkbox("1min–15min Breakout Fakeout", value=False, key="mega_mod_f15")
        mod_f4h = st.checkbox("5min–4h Breakout Fakeout", value=False, key="mega_mod_f4h")
    with ns2:
        mod_mtf = st.checkbox("MTF Scanner (7-component)", value=True, key="mega_mod_mtf")
        mod_tdmtf = st.checkbox("Top-Down MTF SMC", value=True, key="mega_mod_tdmtf")
    with ns3:
        mod_wstoch = st.checkbox("Weekly Stoch Sweet Spot", value=True, key="mega_mod_wstoch")
        mod_kn = st.checkbox("KN Smart DP SL + RSI MTF + VWMA", value=False, key="mega_mod_kn")
    with ns4:
        mod_velez = st.checkbox("Velez Retracement Scalping", value=False, key="mega_mod_velez")
        mod_mtfbias = st.checkbox("MTF Intraday Session Bias", value=True, key="mega_mod_mtfbias")
    with ns5:
        mod_smartwave = st.checkbox(
            "Smart Wave Crypto (CoinDCX only)",
            value=False,
            key="mega_mod_smartwave",
            disabled=not is_crypto_market(market),
            help="EMA · SuperTrend · BB · Multi-Bagger — CoinDCX Futures only.",
        )
        mod_cscalp = st.checkbox(
            "Crypto Scalping (EMA·VWAP·RSI)",
            value=False,
            key="mega_mod_cscalp",
            disabled=not is_crypto_market(market),
            help="1m/5m EMA9/21 trend + VWAP pullback + RSI — CoinDCX only.",
        )
        mod_smcfms = st.checkbox(
            "SMC Fake Market Shift",
            value=False,
            key="mega_mod_smcfms",
            disabled=not (is_crypto_market(market) or is_india_market(market)),
            help="BOS → POI → liquidity sweep · models A/B — Groww NSE/BSE or CoinDCX.",
        )

    p1, p2, p3, p4 = st.columns(4)
    with p1:
        tb_candles = st.slider("Top/Bottom lookback", 50, 500, 100, key="mega_tb_candles")
    with p2:
        mod_tb_forecast = st.checkbox(
            "Top/Bottom breakout forecast",
            value=True,
            key="mega_mod_tb_fc",
            help="ATH/ATL & swing break probabilities (slower — uses yfinance for extremes).",
        )
    with p3:
        gap_min = st.slider("Min gap %", 0.1, 3.0, 0.3, 0.1, key="mega_gap_min")
    with p4:
        season_years = st.slider("Seasonality years", 3, 15, 10, key="mega_season_years")

    n_combos = len(tickers) * len(timeframes) if tickers and timeframes else 0
    n_ticker_scanners = sum(
        1 for k in (
            "mega_mod_f15", "mega_mod_f4h", "mega_mod_mtf", "mega_mod_tdmtf",
            "mega_mod_wstoch", "mega_mod_kn", "mega_mod_velez", "mega_mod_mtfbias",
            "mega_mod_smartwave", "mega_mod_cscalp", "mega_mod_smcfms",
        )
        if st.session_state.get(k, False)
    )
    st.caption(
        f"**{n_combos}** ticker×timeframe runs "
        f"+ **{len(tickers) * n_ticker_scanners if tickers else 0}** per-ticker TA scanner runs "
        f"+ seasonality per ticker · uses sidebar Groww token & Strategy Builder rules"
    )

    run_btn = st.button("🚀 RUN MEGA ANALYSIS", type="primary", width='stretch', key="mega_run_btn")

    if not run_btn:
        return

    if not tickers:
        st.error("Select at least one ticker.")
        return
    if not timeframes:
        st.error("Select at least one timeframe.")
        return

    groww_token = get_active_groww_token()
    mobile = get_logged_in_mobile() if callable(get_logged_in_mobile) else ""
    progress_slot = st.empty()
    bar = progress_slot.progress(0, text="Starting mega scan…")
    results = _run_mega_scan(
        market=market,
        tickers=tickers,
        timeframes=timeframes,
        start_date=start_date,
        end_date=end_date,
        exchange=exchange,
        groww_token=groww_token,
        capital=capital,
        commission=0.001,
        slippage=0.0005,
        tb_candles=tb_candles,
        gap_min_pct=gap_min,
        seasonality_years=season_years,
        conf_fib_lb=conf_fib_lb,
        conf_st_period=conf_st_p,
        conf_st_mult=conf_st_m,
        modules={
            "backtest": mod_backtest,
            "saved_strategies": mod_saved,
            "sentiment": mod_sentiment,
            "price_action": mod_pa,
            "find_sr": mod_find_sr,
            "weak_strong_sr": mod_wssr,
            "pattern_breakout": mod_pbo,
            "confluence": mod_confluence,
            "elliott_wave": mod_ew,
            "top_bottom": mod_tb,
            "tb_forecast": mod_tb_forecast and mod_tb,
            "smc_flow": mod_smc,
            "gap": mod_gap,
            "pump_dump": mod_pdp,
            "screener": mod_scr,
            "seasonality": mod_season,
            "fakeout_15m": mod_f15,
            "fakeout_4h": mod_f4h,
            "mtf_scanner": mod_mtf,
            "top_down_mtf": mod_tdmtf,
            "weekly_stoch": mod_wstoch,
            "kn_smart_rsi": mod_kn,
            "velez_retracement": mod_velez,
            "mtf_intraday_bias": mod_mtfbias,
            "smart_wave_crypto": mod_smartwave,
            "crypto_scalping": mod_cscalp,
            "smc_fake_market_shift": mod_smcfms,
        },
        mobile=mobile,
        progress_callback=lambda p, t: bar.progress(min(p, 1.0), text=t),
    )
    progress_slot.empty()
    st.session_state.mega_results = results
    st.rerun()


def render_mega_analyser_tab(get_logged_in_mobile) -> None:
    st.markdown(
        '<div style="background:linear-gradient(135deg,#1e1b4b,#312e81);padding:22px;border-radius:14px;'
        'border:1px solid #6366f1;margin-bottom:20px;">'
        '<h1 style="margin:0;color:#e0e7ff;font-size:1.8rem;">🚀 Mega Analyser</h1>'
        '<p style="color:#a5b4fc;margin:8px 0 0 0;">One click · multi-ticker · multi-timeframe · '
        'all TA engines + MTF · Top-Down SMC · Weekly Stoch · KN Smart · Velez · Weak Strong S-R · '
        'MTF Session Bias · Smart Wave · <b>Crypto Scalping</b> · <b>SMC Fake Market Shift</b> · '
        'Fakeout scanners · <b>Pump &amp; Dump pre-move</b> · scenario presets · AI View</p></div>',
        unsafe_allow_html=True,
    )

    provider, model, api_key = render_ai_config(
        "mega",
        caption="AI View synthesizes every engine into one trade plan per ticker.",
    )

    existing_results = st.session_state.get("mega_results")
    if existing_results:
        _render_mega_analyser_results(
            existing_results,
            provider=provider,
            model=model,
            api_key=api_key,
        )
        st.markdown("---")

    with st.expander(
        "⚙️ Configure & run Mega Analysis",
        expanded=existing_results is None,
    ):
        _render_mega_analyser_settings(get_logged_in_mobile)

    if not st.session_state.get("mega_results"):
        st.info("Configure tickers & timeframes above, then click **RUN MEGA ANALYSIS**.")

    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai("mega_analyser")
