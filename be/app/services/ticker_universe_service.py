"""Ticker universe metadata for Command Center / TA pickers (truebacktesting parity)."""

from __future__ import annotations

from typing import Any

from app.market_pulse.asset_class_config import (
    ALL_DURATIONS,
    ASSET_CLASS_CONFIG,
    COMMODITY_PICKER,
    resolve_tickers,
    ticker_suggestions,
)
from app.market_pulse.ticker_utils_src import (
    CRYPTO_MARKET,
    GROWW_MARKET,
    US_MARKET,
    get_coindcx_ticker_list,
    get_index_options_for_market,
)

COINDCX_MODES = [
    "All USDT Pairs",
    "Top by Volume",
    "Top By Price",
    "Top Volatile",
    "Bottom by Price",
    "Manual Selection",
    "Custom",
]

CUSTOM_DEFAULTS = {
    "india": "RELIANCE,HDFCBANK,TCS,INFY",
    "us": "AAPL,MSFT,NVDA,AMZN,META",
    "crypto": "BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT",
    "commodity": "CL=F,GC=F,SI=F,HG=F,NG=F",
}


class TickerUniverseService:
    def config(self, asset_class: str) -> dict[str, Any]:
        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        market = str(cfg["market"])

        if asset_class == "crypto":
            return self._crypto_config(cfg)
        if asset_class == "commodity":
            return self._commodity_config(cfg)
        return self._equity_config(asset_class, cfg, market)

    def _equity_config(self, asset_class: str, cfg: dict, market: str) -> dict[str, Any]:
        groups = get_index_options_for_market(market)
        return {
            "asset_class": asset_class,
            "picker_type": "equity_index",
            "label": cfg["label"],
            "scenario": cfg["scenario"],
            "market": market,
            "default_durations": list(cfg["default_durations"]),
            "all_durations": ALL_DURATIONS,
            "index_groups": {k: list(v) for k, v in groups.items()},
            "group_names": list(groups.keys()) + ["Custom"],
            "custom_default": CUSTOM_DEFAULTS.get(asset_class, CUSTOM_DEFAULTS["india"]),
            "default_group": list(groups.keys())[0] if groups else "Custom",
        }

    def _crypto_config(self, cfg: dict) -> dict[str, Any]:
        tickers = get_coindcx_ticker_list()
        return {
            "asset_class": "crypto",
            "picker_type": "crypto",
            "label": cfg["label"],
            "scenario": cfg["scenario"],
            "market": CRYPTO_MARKET,
            "default_durations": list(cfg["default_durations"]),
            "all_durations": ALL_DURATIONS,
            "crypto_modes": COINDCX_MODES,
            "crypto_tickers": tickers,
            "custom_default": CUSTOM_DEFAULTS["crypto"],
            "default_mode": "Manual Selection",
        }

    def _commodity_config(self, cfg: dict) -> dict[str, Any]:
        commodities = [{"symbol": yf, "name": name} for yf, name in COMMODITY_PICKER]
        return {
            "asset_class": "commodity",
            "picker_type": "commodity",
            "label": cfg["label"],
            "scenario": cfg["scenario"],
            "market": str(cfg["market"]),
            "default_durations": list(cfg["default_durations"]),
            "all_durations": ALL_DURATIONS,
            "commodities": commodities,
            "group_names": ["All Commodities", "Custom"],
            "custom_default": CUSTOM_DEFAULTS["commodity"],
            "default_group": "All Commodities",
        }

    def suggest(self, asset_class: str, query: str = "", limit: int = 80) -> list[str]:
        return ticker_suggestions(asset_class, query, limit=limit)

    def resolve(self, asset_class: str, tickers: list[str]) -> list[str]:
        return resolve_tickers(asset_class, tickers)
