"""Technical Analysis screener catalog (truebacktesting parity)."""

from __future__ import annotations

from typing import Any

TA_SCREENERS: list[dict[str, Any]] = [
    {"id": "ticker_investigation", "label": "Ticker Investigation", "markets": ["india", "us", "crypto", "commodity"], "api": "ticker-investigation"},
    {"id": "sentiment_screener", "label": "Trend & Sentiment Screener", "markets": ["india", "us", "crypto"], "api": "sentiment-screener"},
    {"id": "mtf_scanner", "label": "MTF Scanner", "markets": ["india", "us", "crypto"], "api": "mtf-scanner"},
    {"id": "price_action", "label": "Price Action Screener", "markets": ["india", "us", "crypto"], "engine": "price_action", "default_tf": "15m"},
    {"id": "pump_dump_predictor", "label": "Pump & Dump Screener", "markets": ["india", "crypto"], "engine": "pump_dump_predictor", "default_tf": "5m"},
    {"id": "find_sr", "label": "Find S/R", "markets": ["india", "us", "crypto"], "engine": "find_sr", "default_tf": "15m"},
    {"id": "weak_strong_sr", "label": "Weak / Strong S-R", "markets": ["india", "us", "crypto"], "engine": "weak_strong_sr_engine", "default_tf": "15m"},
    {"id": "pattern_breakout", "label": "Pattern & Breakout Screener", "markets": ["india", "us", "crypto"], "engine": "pattern_engine", "default_tf": "15m"},
    {"id": "fakeout_4h", "label": "Fakeout 5m–4h", "markets": ["india", "us"], "engine": "fakeout_4h_engine", "default_tf": "5m"},
    {"id": "fakeout_15m", "label": "Fakeout 1m–15m", "markets": ["india", "us"], "engine": "fakeout_15m_engine", "default_tf": "1m"},
    {"id": "top_down_mtf", "label": "Top Down MTF", "markets": ["india", "us", "crypto"], "engine": "top_down_mtf_engine", "default_tf": "15m"},
    {"id": "smc_fake_market_shift", "label": "SMC Fake Market Shift", "markets": ["india", "us", "crypto"], "engine": "smc_fake_market_shift_engine", "default_tf": "15m"},
    {"id": "weekly_stoch", "label": "Weekly Stoch Sweet Spot", "markets": ["india", "us"], "engine": "weekly_stoch_sweet_spot_engine", "default_tf": "1d"},
    {"id": "kn_smart_rsi", "label": "KN Smart RSI MTF", "markets": ["india", "us", "crypto"], "engine": "kn_smart_rsi_engine", "default_tf": "5m"},
    {"id": "velez_retracement", "label": "Velez Retracement", "markets": ["india", "us"], "engine": "velez_retracement_engine", "default_tf": "15m"},
    {"id": "smart_wave_crypto", "label": "Smart Wave Crypto", "markets": ["crypto"], "engine": "smart_wave_crypto_engine", "default_tf": "30m"},
    {"id": "crypto_scalping", "label": "Crypto Scalping", "markets": ["crypto"], "engine": "crypto_scalping_engine", "default_tf": "15m"},
    {"id": "confluence_strategy", "label": "Confluence Screener (Fib·VWAP·ST·ATR)", "markets": ["india", "us", "crypto"], "engine": "confluence_strategy", "default_tf": "15m"},
    {"id": "elliott_wave", "label": "Elliott Wave Screener", "markets": ["india", "us", "crypto"], "engine": "price_action", "default_tf": "1h"},
    {"id": "top_bottom", "label": "Top/Bottom Screener", "markets": ["india", "us", "crypto"], "engine": "top_bottom", "default_tf": "1d"},
    {"id": "pump_dump_breakout", "label": "Pump/Dump Breakout", "markets": ["india", "crypto"], "engine": "pump_dump_breakout_engine", "default_tf": "15m"},
    {"id": "big_whale", "label": "Big Whale Pump & Dump", "markets": ["crypto"], "engine": "big_whale_pump_dump_engine", "default_tf": "15m"},
    {"id": "zireman_confluence", "label": "Accurate Strategy (OB+FVG+S/R)", "markets": ["india", "us", "crypto"], "engine": "zireman_confluence_engine", "default_tf": "1d"},
    {"id": "bb_exposed", "label": "BB Exposed (Free Bar + Squeeze)", "markets": ["india", "us", "crypto"], "engine": "bb_exposed_engine", "default_tf": "15m"},
    {"id": "breakout_mtf", "label": "Multi-Period Breakout (10/20/50/90/200D)", "markets": ["india", "us", "crypto"], "engine": "breakout_mtf_engine", "default_tf": "1d"},
    {"id": "box_trading", "label": "Box Trading (Prev-Day Range)", "markets": ["india", "us", "crypto"], "engine": "box_trading_engine", "default_tf": "5m"},
    {"id": "one_ta", "label": "Golden Zone Confluence", "markets": ["india", "us", "crypto"], "engine": "one_ta_engine", "default_tf": "1h"},
    {"id": "topdown_mtf", "label": "TOPDOWN - MTF (Liquidity + Order Blocks)", "markets": ["india", "us", "crypto"], "engine": "topdown_mtf_engine", "default_tf": "15m"},
]


def list_ta_screeners() -> dict[str, Any]:
    return {
        "categories": [
            {"id": "core", "label": "Core TA", "screeners": TA_SCREENERS[:3]},
            {"id": "screeners", "label": "Screeners", "screeners": TA_SCREENERS[3:]},
        ],
        "screeners": TA_SCREENERS,
        "count": len(TA_SCREENERS),
    }
