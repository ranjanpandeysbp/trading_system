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
        "default_tickers": ["CL=F", "GC=F", "SI=F", "HG=F", "NG=F", "ZW=F"],
        "exchange": "NASDAQ",
    },
}

COMMODITY_PICKER: list[tuple[str, str]] = [
    (str(meta["yf"]), str(meta["name"]))
    for meta in COMMODITY_META.values()
]

# Yahoo symbol → friendly name (GC=F → Gold)
_COMMODITY_YF_TO_NAME: dict[str, str] = {
    str(meta["yf"]).upper(): str(meta["name"]) for meta in COMMODITY_META.values()
}
# Short keys too (GOLD → Gold)
_COMMODITY_KEY_TO_NAME: dict[str, str] = {
    key.upper(): str(meta["name"]) for key, meta in COMMODITY_META.items()
}


def commodity_name(symbol: str | None) -> str | None:
    """Human-readable commodity name for a Yahoo futures symbol or short key."""
    key = (symbol or "").strip().upper()
    if not key:
        return None
    if key in _COMMODITY_YF_TO_NAME:
        return _COMMODITY_YF_TO_NAME[key]
    if key in _COMMODITY_KEY_TO_NAME:
        return _COMMODITY_KEY_TO_NAME[key]
    # Strip common suffixes users might type
    bare = key.replace("=F", "").replace(".F", "")
    for sym, name in _COMMODITY_YF_TO_NAME.items():
        if sym.replace("=F", "") == bare:
            return name
    return None


def ticker_display_label(symbol: str | None, asset_class: str = "") -> str:
    """e.g. 'Gold (GC=F)' for commodities; otherwise the symbol alone."""
    sym = (symbol or "").strip()
    if not sym:
        return ""
    ac = (asset_class or "").strip().lower()
    if ac == "commodity" or "=F" in sym.upper() or sym.upper() in _COMMODITY_KEY_TO_NAME:
        name = commodity_name(sym)
        if name:
            # Avoid "Gold (Gold)" if someone already passed the name
            if name.upper() == sym.upper():
                yf = next(
                    (str(m["yf"]) for m in COMMODITY_META.values() if str(m["name"]).upper() == name.upper()),
                    sym,
                )
                return f"{name} ({yf})"
            return f"{name} ({sym})"
    return sym


def attach_ticker_name(row: dict[str, Any], *, asset_class: str = "") -> dict[str, Any]:
    """Add name / display_name / display_label onto a result row (in place)."""
    if not isinstance(row, dict):
        return row
    sym = str(row.get("ticker") or row.get("symbol") or "")
    ac = (asset_class or row.get("asset_class") or "").strip().lower()
    name = commodity_name(sym) if ac == "commodity" or commodity_name(sym) else None
    if name:
        row["name"] = name
        row["display_name"] = name
        row["display_label"] = ticker_display_label(sym, "commodity")
    elif sym and "display_label" not in row:
        row["display_label"] = sym
    return row


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
            elif key in _COMMODITY_YF_TO_NAME:
                out.append(key)
            elif "=" in t or t.endswith("F"):
                out.append(t.upper())
            else:
                # Allow typing "gold", "wheat", "crude", etc.
                hit = next(
                    (
                        yf
                        for yf, name in COMMODITY_PICKER
                        if key in name.upper() or name.upper() in key or key in yf.upper()
                    ),
                    None,
                )
                out.append(hit or t.upper())
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
        pool = list(COMMODITY_PICKER)
        if not q:
            return [yf for yf, _ in pool][:limit]
        return [
            yf for yf, name in pool
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


def ticker_suggestion_items(asset_class: str, query: str = "", limit: int = 80) -> list[dict[str, str]]:
    """Suggestions with optional display names (commodities show Gold, Silver, …)."""
    ac = (asset_class or "india").strip().lower()
    q = (query or "").strip().upper()
    if ac == "commodity":
        items: list[dict[str, str]] = []
        for yf, name in COMMODITY_PICKER:
            if q and q not in yf.upper() and q not in name.upper():
                continue
            items.append({
                "symbol": yf,
                "name": name,
                "label": f"{name} ({yf})",
            })
            if len(items) >= limit:
                break
        return items
    # Fallback: plain symbols
    return [
        {"symbol": t, "name": t, "label": t}
        for t in ticker_suggestions(ac, query, limit=limit)
    ]
