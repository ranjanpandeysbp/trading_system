"""Lightweight asset-class metadata for ticker pickers (no mega_analyser dependency)."""

from __future__ import annotations

from typing import Any

from app.market_pulse.commodity_screener_engine import COMMODITY_META
from app.market_pulse.ticker_utils import CRYPTO_MARKET, GROWW_MARKET, US_MARKET

ALL_DURATIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

ASSET_CLASS_CONFIG: dict[str, dict[str, Any]] = {
    "crypto": {
        "label": "Crypto (CoinDCX)",
        "market": CRYPTO_MARKET,
        "scenario": "Crypto momentum",
        "default_durations": ["15m", "1h", "4h"],
        "default_tickers": ["B-BTCUSDT", "B-ETHUSDT", "B-SOLUSDT"],
        "exchange": "NSE",
    },
    "india": {
        "label": "Indian stocks (NSE)",
        "market": GROWW_MARKET,
        "scenario": "India intraday scalp (expert)",
        "default_durations": ["5m", "15m", "1h"],
        "default_tickers": ["RELIANCE", "TCS", "HDFCBANK", "INFY"],
        "exchange": "NSE",
    },
    "us": {
        "label": "US stocks",
        "market": US_MARKET,
        "scenario": "Swing / positional",
        "default_durations": ["1h", "4h", "1d"],
        "default_tickers": ["AAPL", "MSFT", "NVDA", "SPY"],
        "exchange": "NASDAQ",
    },
    "commodity": {
        "label": "Commodities (Yahoo futures)",
        "market": US_MARKET,
        "scenario": "Swing / positional",
        "default_durations": ["1h", "4h", "1d"],
        "default_tickers": ["CL=F", "GC=F", "SI=F", "HG=F", "NG=F"],
        "exchange": "NASDAQ",
    },
}

COMMODITY_PICKER: list[tuple[str, str]] = [
    (str(meta["yf"]), str(meta["name"]))
    for meta in COMMODITY_META.values()
]


def resolve_tickers(asset_class: str, raw: list[str]) -> list[str]:
    """Normalize user-selected symbols for the data layer."""
    out: list[str] = []
    sym_to_yf = {sym: str(meta["yf"]) for sym, meta in COMMODITY_META.items()}
    name_to_yf = {str(meta["name"]).upper(): str(meta["yf"]) for meta in COMMODITY_META.values()}

    for item in raw:
        t = (item or "").strip()
        if not t:
            continue
        if asset_class == "crypto":
            if t.startswith("B-"):
                out.append(t.replace("_USDT", "USDT") if "_USDT" in t else t)
            else:
                base = t.upper().replace("-USDT", "").replace("USDT", "")
                out.append(f"B-{base}USDT")
        elif asset_class == "commodity":
            key = t.upper()
            if key in sym_to_yf:
                out.append(sym_to_yf[key])
            elif key in name_to_yf:
                out.append(name_to_yf[key])
            elif "=" in t or t.endswith("F"):
                out.append(t.upper())
            else:
                out.append(t.upper())
        else:
            out.append(t.upper().replace(".NS", "").replace(".US", ""))
    return list(dict.fromkeys(out))


def ticker_suggestions(asset_class: str, query: str = "", limit: int = 80) -> list[str]:
    """Autocomplete pool for multiselect."""
    q = (query or "").strip().upper()
    if asset_class == "crypto":
        try:
            from app.market_pulse.ticker_utils import get_coindcx_ticker_list

            pool = [x["symbol"] if isinstance(x, dict) else x for x in get_coindcx_ticker_list()]
            displays = []
            for s in pool:
                disp = s.replace("B-", "").replace("USDT", "-USDT").replace("_", "")
                if not q or q in disp.upper() or q in s.upper():
                    displays.append(s)
            return displays[:limit]
        except Exception:
            return ASSET_CLASS_CONFIG["crypto"]["default_tickers"]
    if asset_class == "commodity":
        pool = [yf for yf, _ in COMMODITY_PICKER]
        if not q:
            return pool
        return [
            yf for yf, name in COMMODITY_PICKER
            if q in yf.upper() or q in name.upper()
        ][:limit]
    if asset_class == "india":
        try:
            from app.market_pulse.ticker_utils import DEFAULT_GROWW_TICKERS

            pool = list(DEFAULT_GROWW_TICKERS)
        except Exception:
            pool = ASSET_CLASS_CONFIG["india"]["default_tickers"]
    else:
        pool = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SPY", "QQQ", "AMD"]
    if not q:
        return pool[:limit]
    return [t for t in pool if q in t.upper()][:limit]
