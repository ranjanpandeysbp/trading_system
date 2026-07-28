"""Trading Hubs and Technical Analysis strategies for the backtester."""

from __future__ import annotations

from typing import Any

from app.trading_hubs.registry import HUB_META, HUB_SECTIONS
from app.market_pulse.ta_screener_registry import TA_SCREENERS

ENGINE_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "th_swing": "Swing Trading Hub engines — multi-day ST systems migrated from truebacktesting.",
    "th_intraday": "Intraday Trading Hub engines — session-timed NSE scanners and opening-range setups.",
    "th_scalping": "Scalping Hub engines — 1m rectangle sniper and high-frequency setups.",
    "th_smart_money": "Smart Money Hub engines — SMC liquidity, sweep, and institutional delivery models.",
    "technical_analysis": "Technical Analysis tools — sentiment scoring, MTF confluence, and investigation composites.",
    "ta_screeners": "TA screener engines — S-R, fakeout, SMC, crypto wave, and confluence scanners.",
}

_HUB_CATEGORY_MAP = {
    "swing": "th_swing",
    "intraday": "th_intraday",
    "scalping": "th_scalping",
    "smart_money": "th_smart_money",
}

# Default timeframes per hub section (from engine configs).
_HUB_TIMEFRAMES: dict[str, list[str]] = {
    "swing_trading_st": ["1d"],
    "swing_trading_st_mtf_mss": ["15m"],
    "swing_trading_st_supertrend": ["1d", "1wk"],
    "swing_trading_st_kiss": ["1h", "4h"],
    "swing_trading_st_ha_ema": ["5m", "15m"],
    "intraday_alpha_945": ["5m", "15m"],
    "intraday_fib_945": ["5m", "1m"],
    "intraday_vwap_fade": ["5m", "1m"],
    "scalp_rectangle": ["1m"],
    "smc_cisd": ["15m", "5m"],
    "smc_weekly_sweep_cisd": ["15m"],
    "smc_mtf_day_plan": ["15m", "5m"],
    "smc_golden_bullet": ["15m"],
    "scalp_ichimoku_crash": ["1h", "4h", "1d"],
    "swing_trend_velocity": ["1d"],
    "swing_bb_vwap_reversal": ["5m", "15m"],
    "smc_liquidity_silver_bullet": ["5m", "15m"],
    "scalp_ny_open_bias": ["1m"],
}

_HUB_MIN_BARS: dict[str, int] = {
    "swing_trading_st": 80,
    "swing_trading_st_mtf_mss": 100,
    "swing_trading_st_supertrend": 30,
    "swing_trading_st_kiss": 80,
    "swing_trading_st_ha_ema": 100,
    "intraday_alpha_945": 50,
    "intraday_fib_945": 80,
    "intraday_vwap_fade": 80,
    "scalp_rectangle": 80,
    "smc_cisd": 60,
    "smc_weekly_sweep_cisd": 80,
    "smc_mtf_day_plan": 60,
    "smc_golden_bullet": 80,
    "scalp_ichimoku_crash": 120,
    "swing_trend_velocity": 280,
    "swing_bb_vwap_reversal": 30,
    "smc_liquidity_silver_bullet": 60,
    "scalp_ny_open_bias": 40,
}

TA_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "ta_sentiment_screener",
        "name": "Trend & Sentiment Screener",
        "label": "Trend & Sentiment Screener",
        "description": "Composite multi-indicator sentiment score with ATR-based BUY/SELL signals.",
        "timeframes": ["5m", "15m", "1h", "4h", "1d"],
        "min_bars": 80,
        "runner": "rolling_sentiment",
    },
    {
        "id": "ta_mtf_scanner",
        "name": "MTF Scanner",
        "label": "MTF Scanner",
        "description": "Multi-timeframe confluence — bullish/bearish composite score crossovers.",
        "timeframes": ["5m", "15m", "1h", "4h", "1d"],
        "min_bars": 60,
        "runner": "rolling_mtf",
    },
    {
        "id": "ta_ticker_investigation",
        "name": "Ticker Investigation (Composite)",
        "label": "Ticker Investigation",
        "description": "Rolling composite sentiment proxy aligned with investigation scoring on historical bars.",
        "timeframes": ["1d", "4h", "1h"],
        "min_bars": 80,
        "runner": "rolling_sentiment",
    },
]

ENGINE_STRATEGY_META: dict[str, dict[str, Any]] = {}
ENGINE_RUNNER_KIND: dict[str, str] = {}

# These sections are "current-state" evaluators (they return the latest
# signal, not a vectorized full-history series) and are multi-strategy or
# multi-dataframe shaped — none of the existing runner kinds (analyze_bt's
# run_bt flag, signal_df's single-df builder, rolling_sentiment's generic
# composite score) actually exercise their real logic. Showing a backtest
# for them via the generic fallback would silently test the WRONG thing, so
# they're excluded here rather than faked; they still have a proper live
# scan via /trading-hubs/scan.
_NO_GENERIC_BACKTEST: frozenset[str] = frozenset({
    "swing_5_strategies", "scalp_weekly", "swing_trend_breakout",
    "smc_htf_zone_sweep", "weekly_candle_continuation",
})

for section in HUB_SECTIONS:
    sid = section["id"]
    if sid in _NO_GENERIC_BACKTEST:
        continue
    hub = section["hub"]
    cat_id = _HUB_CATEGORY_MAP[hub]
    hub_label = HUB_META[hub]["label"]
    tfs = _HUB_TIMEFRAMES.get(sid, ["1d"])
    min_bars = _HUB_MIN_BARS.get(sid, 60)

    if sid == "swing_trading_st":
        runner = "analyze_bt"
    elif sid in {
        "swing_trading_st_supertrend",
        "swing_trading_st_kiss",
        "swing_trading_st_ha_ema",
        "scalp_ny_open_bias",
    }:
        runner = "analyze_bt"
    elif sid in {
        "intraday_vwap_fade",
        "intraday_fib_945",
        "scalp_rectangle",
        "smc_cisd",
        "smc_weekly_sweep_cisd",
        "smc_golden_bullet",
        "scalp_ichimoku_crash",
        "swing_trend_velocity",
        "swing_bb_vwap_reversal",
        "smc_liquidity_silver_bullet",
    }:
        runner = "signal_df"
    else:
        runner = "rolling_sentiment"

    ENGINE_RUNNER_KIND[sid] = runner
    ENGINE_STRATEGY_META[sid] = {
        "id": sid,
        "name": section["label"],
        "category": cat_id,
        "category_label": f"Trading Hubs — {hub_label}",
        "timeframes": tfs,
        "summary": section["description"],
        "description": section["description"],
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "needs_benchmark": False,
        "min_bars": min_bars,
        "engine": True,
        "hub": hub,
    }

for ta in TA_STRATEGIES:
    ENGINE_RUNNER_KIND[ta["id"]] = ta["runner"]
    ENGINE_STRATEGY_META[ta["id"]] = {
        "id": ta["id"],
        "name": ta["name"],
        "category": "technical_analysis",
        "category_label": "Technical Analysis",
        "timeframes": ta["timeframes"],
        "summary": ta["description"],
        "description": ta["description"],
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "needs_benchmark": False,
        "min_bars": ta["min_bars"],
        "engine": True,
    }

_TA_SCREENER_RUNNERS: dict[str, str] = {
    "zireman_confluence": "ta_native_bt",
    "pump_dump_breakout": "ta_native_bt",
}

_TA_SCREENER_MIN_BARS: dict[str, int] = {
    "weak_strong_sr": 100,
    "fakeout_4h": 120,
    "fakeout_15m": 150,
    "top_down_mtf": 80,
    "smc_fake_shift": 100,
    "weekly_stoch": 60,
    "kn_smart_rsi": 100,
    "velez_retracement": 100,
    "smart_wave_crypto": 80,
    "crypto_scalping": 100,
    "pump_dump_breakout": 80,
    "big_whale": 60,
    "zireman_confluence": 80,
}

for screener in TA_SCREENERS:
    sid = screener["id"]
    if sid in {"ticker_investigation", "sentiment_screener", "mtf_scanner"}:
        continue
    if not screener.get("engine"):
        continue
    default_tf = screener.get("default_tf", "15m")
    tfs = [default_tf]
    if default_tf == "15m":
        tfs = ["5m", "15m", "30m", "1h"]
    elif default_tf == "5m":
        tfs = ["5m", "15m"]
    elif default_tf == "1m":
        tfs = ["1m", "5m"]
    elif default_tf == "1d":
        tfs = ["1d", "4h"]
    elif default_tf == "30m":
        tfs = ["30m", "1h", "4h"]

    runner = _TA_SCREENER_RUNNERS.get(sid, "rolling_ta_screener")
    ENGINE_RUNNER_KIND[sid] = runner
    ENGINE_STRATEGY_META[sid] = {
        "id": sid,
        "name": screener["label"],
        "category": "ta_screeners",
        "category_label": "TA Screeners",
        "timeframes": tfs,
        "summary": f"{screener['label']} — migrated TA screener engine.",
        "description": f"{screener['label']} screener backtest (rolling replay).",
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "needs_benchmark": False,
        "min_bars": _TA_SCREENER_MIN_BARS.get(sid, 80),
        "engine": True,
        "screener": True,
        "default_tf": default_tf,
    }

ENGINE_STRATEGY_CATEGORIES: dict[str, dict[str, Any]] = {
    "th_swing": {
        "label": "Trading Hubs — Swing Trading",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_swing"],
        "timeframes": ["1d", "1wk", "4h", "1h", "15m", "5m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "swing"],
    },
    "th_intraday": {
        "label": "Trading Hubs — Intraday",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_intraday"],
        "timeframes": ["5m", "15m", "1m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "intraday"],
    },
    "th_scalping": {
        "label": "Trading Hubs — Scalping",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_scalping"],
        "timeframes": ["1m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "scalping"],
    },
    "th_smart_money": {
        "label": "Trading Hubs — Smart Money",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_smart_money"],
        "timeframes": ["15m", "5m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "smart_money"],
    },
    "technical_analysis": {
        "label": "Technical Analysis",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["technical_analysis"],
        "timeframes": ["5m", "15m", "1h", "4h", "1d"],
        "strategy_ids": [t["id"] for t in TA_STRATEGIES],
    },
    "ta_screeners": {
        "label": "TA Screeners",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["ta_screeners"],
        "timeframes": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        "strategy_ids": [
            s["id"] for s in TA_SCREENERS
            if s.get("engine") and s["id"] not in {"ticker_investigation", "sentiment_screener", "mtf_scanner"}
        ],
    },
}


def is_engine_strategy(name: str) -> bool:
    return name in ENGINE_STRATEGY_META


def engine_min_bars(name: str) -> int:
    return int(ENGINE_STRATEGY_META.get(name, {}).get("min_bars", 60))


def engine_runner_kind(name: str) -> str:
    return ENGINE_RUNNER_KIND.get(name, "rolling_sentiment")


def list_engine_categories() -> list[dict[str, Any]]:
    categories = []
    for cat_id, info in ENGINE_STRATEGY_CATEGORIES.items():
        strategies = [ENGINE_STRATEGY_META[sid] for sid in info["strategy_ids"] if sid in ENGINE_STRATEGY_META]
        categories.append({
            "id": cat_id,
            "label": info["label"],
            "description": info["description"],
            "timeframes": info["timeframes"],
            "strategy_count": len(strategies),
            "strategies": strategies,
        })
    return categories
