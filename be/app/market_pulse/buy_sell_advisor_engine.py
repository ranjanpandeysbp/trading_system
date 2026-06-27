"""
buy_sell_advisor_engine.py
--------------------------
Multi-asset Buy / Sell advisor — institutional-grade TA stack per asset class.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.market_pulse.asset_class_config import (
    ALL_DURATIONS,
    ASSET_CLASS_CONFIG,
    COMMODITY_PICKER,
    resolve_tickers,
    ticker_suggestions,
)
from app.market_pulse.run_summary import default_sl_tp_for_timeframe, make_trade_plan

# Re-export for existing imports
__all__ = [
    "ALL_DURATIONS",
    "ASSET_CLASS_CONFIG",
    "COMMODITY_PICKER",
    "resolve_tickers",
    "ticker_suggestions",
    "run_buy_sell_advisor",
    "build_buy_sell_ai_prompt",
]

BUY_SELL_AI_SYSTEM = """You are an elite institutional trading advisor synthesizing multi-engine technical analysis.

Asset-class engines include: Price Action (SMC, structure, patterns), Find S/R, Weak/Strong S/R with VWAP·Volume·Supertrend·RSI,
Pattern & Breakout, Confluence (Fib·VWAP·ATR·Volume), Top/Bottom, Pump & Dump pre-move, Gap setups,
Fakeout scanners (1m–15m & 5m–4h), MTF Scanner, Top-Down MTF SMC, KN Smart RSI MTF, Velez retracement,
MTF Intraday Session Bias, Smart Wave Crypto (crypto only), Crypto Scalping (EMA·VWAP·RSI, crypto only),
SMC Fake Market Shift (India/CoinDCX), SMC Flow (India).

Rules:
- Only recommend TAKE TRADE when multiple engines align (confluence ≥ 6/10 average).
- If engines conflict → NO TRADE / WAIT — cite psychology: avoid FOMO and revenge trading.
- Always specify direction, confidence %, stop-loss %, take-profit %, and max hold.
- Reference concrete levels, scores, and engine names from the data below.
- Emphasize risk management: position size, never move stop away, respect invalidation.
"""


def _scenario_modules(scenario_name: str) -> tuple[list[str], dict[str, bool]]:
    from app.market_pulse.mega_analyser import MEGA_SCENARIOS

    scenario = MEGA_SCENARIOS.get(scenario_name) or MEGA_SCENARIOS["Full analysis (default)"]
    tfs = list(scenario.get("timeframes") or ["1h", "1d"])
    modules = dict(scenario.get("modules") or {})
    # Focus on TA — skip heavy backtest / screener for responsiveness
    for key in ("backtest", "saved_strategies", "seasonality", "screener"):
        modules[key] = False
    return tfs, modules


def _build_recommendation(ticker: str, mega: dict, summaries: list[dict], asset_class: str) -> dict:
    verdict = str(mega.get("verdict") or "WAIT")
    score = float(mega.get("score") or 0)
    plan = mega.get("trade_plan") or {}
    primary_tf = (mega.get("timeframe") or "1h").split(",")[0].strip() or "1h"

    if verdict in ("STRONG BUY", "BUY"):
        direction = "LONG"
        take_trade = score >= 5.5
    elif verdict in ("SELL / AVOID", "SELL", "STRONG SELL"):
        direction = "SHORT"
        take_trade = score >= 5.0
    else:
        direction = "WAIT"
        take_trade = False

    conf = plan.get("confidence_pct")
    if conf is None:
        conf = min(92.0, max(20.0, score * 10))

    sl = plan.get("stop_loss_pct")
    tp = plan.get("take_profit_pct")
    if sl is None or tp is None:
        dsl, dtp = default_sl_tp_for_timeframe(primary_tf)
        sl = sl if sl is not None else dsl
        tp = tp if tp is not None else dtp

    if not take_trade:
        plan = make_trade_plan(
            timeframe=primary_tf,
            direction="—",
            exit_rule="No trade — wait for multi-engine confluence and defined risk.",
        )
    else:
        plan = make_trade_plan(
            direction=direction,
            timeframe=primary_tf,
            stop_loss_pct=float(sl),
            take_profit_pct=float(tp),
            confidence_pct=float(conf),
            exit_rule=plan.get("exit_rule") or mega.get("action", ""),
        )

    return {
        "ticker": ticker,
        "asset_class": asset_class,
        "take_trade": take_trade,
        "direction": direction,
        "verdict": verdict,
        "score": round(score, 1),
        "confidence_pct": round(float(conf), 1),
        "sl_pct": round(float(sl), 2),
        "tp_pct": round(float(tp), 2),
        "action": mega.get("action") or "",
        "summary": mega.get("summary") or "",
        "reasons": list(mega.get("reasons") or [])[:10],
        "trade_plan": plan,
        "engine_count": len(summaries),
        "timeframe": mega.get("timeframe") or primary_tf,
    }


def run_buy_sell_advisor(
    asset_class: str,
    tickers: list[str],
    durations: list[str],
    *,
    groww_token: str = "",
    mobile: str = "",
    progress_callback=None,
) -> dict | None:
    """Run full TA stack and return buy/sell recommendations."""
    cfg = ASSET_CLASS_CONFIG.get(asset_class)
    if not cfg or not tickers or not durations:
        return None

    _, modules = _scenario_modules(str(cfg["scenario"]))
    if asset_class == "crypto":
        modules["smart_wave_crypto"] = True
        modules["crypto_scalping"] = True
        modules["smc_fake_market_shift"] = True
        modules["smc_flow"] = False
        modules["gap"] = False
    elif asset_class == "commodity":
        modules["smc_flow"] = False
        modules["gap"] = False
        modules["pump_dump"] = False
        modules["fakeout_15m"] = False
        modules["fakeout_4h"] = False
        modules["crypto_scalping"] = False
        modules["smc_fake_market_shift"] = False
    elif asset_class == "india":
        modules["smc_fake_market_shift"] = True
        modules["crypto_scalping"] = False

    from app.market_pulse.mega_analyser import _run_mega_scan, summarize_mega_ticker

    end_date = date.today()
    start_date = end_date - timedelta(days=120)

    results = _run_mega_scan(
        market=str(cfg["market"]),
        tickers=tickers,
        timeframes=durations,
        start_date=start_date,
        end_date=end_date,
        exchange=str(cfg.get("exchange") or "NSE"),
        groww_token=groww_token,
        capital=100_000.0,
        commission=0.001,
        slippage=0.0005,
        tb_candles=100,
        gap_min_pct=0.5,
        seasonality_years=5,
        conf_fib_lb=20,
        conf_st_period=10,
        conf_st_mult=3.0,
        modules=modules,
        mobile=mobile,
        progress_callback=progress_callback,
    )

    recommendations: list[dict] = []
    for ticker in tickers:
        t_summaries = [s for s in results.get("summaries", []) if s.get("ticker") == ticker]
        mega = summarize_mega_ticker(ticker, t_summaries)
        recommendations.append(_build_recommendation(ticker, mega, t_summaries, asset_class))

    return {
        "asset_class": asset_class,
        "market": cfg["market"],
        "tickers": tickers,
        "durations": durations,
        "recommendations": recommendations,
        "by_ticker": results.get("by_ticker", {}),
        "summaries": results.get("summaries", []),
        "scenario": cfg["scenario"],
    }


def build_buy_sell_ai_prompt(result: dict, ticker: str, currency: str = "$") -> str:
    from app.market_pulse.mega_analyser import build_mega_ai_prompt

    summaries = [s for s in result.get("summaries", []) if s.get("ticker") == ticker]
    return build_mega_ai_prompt(ticker, result.get("market", ""), summaries, currency)
