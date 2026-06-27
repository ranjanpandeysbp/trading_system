"""Technical Analysis screener catalog (truebacktesting parity)."""

from __future__ import annotations

from typing import Any

TA_SCREENERS: list[dict[str, Any]] = [
    {"id": "ticker_investigation", "label": "Ticker Investigation", "markets": ["india", "us", "crypto"], "api": "ticker-investigation"},
    {"id": "sentiment_screener", "label": "Trend & Sentiment Screener", "markets": ["india", "us", "crypto"], "api": "sentiment-screener"},
    {"id": "mtf_scanner", "label": "MTF Scanner", "markets": ["india", "us", "crypto"], "api": "mtf-scanner"},
    {"id": "weak_strong_sr", "label": "Weak / Strong S-R", "markets": ["india", "us", "crypto"], "engine": "weak_strong_sr_engine", "default_tf": "15m"},
    {"id": "fakeout_4h", "label": "Fakeout 5m–4h", "markets": ["india", "us"], "engine": "fakeout_4h_engine", "default_tf": "5m"},
    {"id": "fakeout_15m", "label": "Fakeout 1m–15m", "markets": ["india", "us"], "engine": "fakeout_15m_engine", "default_tf": "1m"},
    {"id": "top_down_mtf", "label": "Top Down MTF", "markets": ["india", "us", "crypto"], "engine": "top_down_mtf_engine", "default_tf": "15m"},
    {"id": "smc_fake_shift", "label": "SMC Fake Market Shift", "markets": ["india", "us", "crypto"], "engine": "smc_fake_market_shift_engine", "default_tf": "15m"},
    {"id": "weekly_stoch", "label": "Weekly Stoch Sweet Spot", "markets": ["india", "us"], "engine": "weekly_stoch_sweet_spot_engine", "default_tf": "1d"},
    {"id": "kn_smart_rsi", "label": "KN Smart RSI MTF", "markets": ["india", "us", "crypto"], "engine": "kn_smart_rsi_engine", "default_tf": "5m"},
    {"id": "velez_retracement", "label": "Velez Retracement", "markets": ["india", "us"], "engine": "velez_retracement_engine", "default_tf": "15m"},
    {"id": "smart_wave_crypto", "label": "Smart Wave Crypto", "markets": ["crypto"], "engine": "smart_wave_crypto_engine", "default_tf": "30m"},
    {"id": "crypto_scalping", "label": "Crypto Scalping", "markets": ["crypto"], "engine": "crypto_scalping_engine", "default_tf": "15m"},
    {"id": "pump_dump_breakout", "label": "Pump/Dump Breakout", "markets": ["india", "crypto"], "engine": "pump_dump_breakout_engine", "default_tf": "15m"},
    {"id": "big_whale", "label": "Big Whale Pump & Dump", "markets": ["crypto"], "engine": "big_whale_pump_dump_engine", "default_tf": "15m"},
    {"id": "zireman_confluence", "label": "Accurate Strategy (OB+FVG+S/R)", "markets": ["india"], "engine": "zireman_confluence_engine", "default_tf": "1d"},
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
