"""Groww symbol resolution for NSE equities and indices."""

from __future__ import annotations

# Yahoo ^ tickers -> Groww CASH segment symbols (from truebacktesting/nse_index_yfinance.py)
GROWW_INDEX_SYMBOL_TO_YF: dict[str, str] = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYJR": "^NSMIDCP",
    "NIFTYNEXT50": "^NSMIDCP",
    "NIFTYIT": "^CNXIT",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "NIFTYFIN": "NIFTY_FIN_SERVICE.NS",
    "NIFTYFINSERVICE": "NIFTY_FIN_SERVICE.NS",
    "NIFTYAUTO": "^CNXAUTO",
    "NIFTYFMCG": "^CNXFMCG",
    "NIFTYMETAL": "^CNXMETAL",
    "NIFTYREALTY": "^CNXREALTY",
    "NIFTYENERGY": "^CNXENERGY",
    "NIFTYPHARMA": "^CNXPHARMA",
    "NIFTYPSUBANK": "^CNXPSUBANK",
    "NIFTYMEDIA": "^CNXMEDIA",
    "NIFTY100": "^CNX100",
    "NIFTY200": "^CNX200",
    "NIFTY500": "^CRSLDX",
    "NIFTYMID50": "^NSEMDCP50",
    "NIFTYMID100": "^CNXMID",
    "NIFTYSML100": "^CNXSML",
    "NIFTYMIDCAP150": "NIFTYMIDCAP150.NS",
    "NIFTYM150": "NIFTYMIDCAP150.NS",
    "NIFTYMID150": "NIFTYMIDCAP150.NS",
    "NIFTYSMALLCAP250": "NIFTYSMALLCAP250.NS",
    "NIFTYSML250": "NIFTYSMALLCAP250.NS",
    "NIFTYSMLCAP250": "NIFTYSMALLCAP250.NS",
    "MIDCPNIFTY": "^NSEMDCP50",
    "MIDCP": "^NSEMDCP50",
    "SENSEX": "^BSESN",
}

YF_TO_GROWW_INDEX: dict[str, list[str]] = {}
for groww_sym, yf_sym in GROWW_INDEX_SYMBOL_TO_YF.items():
    YF_TO_GROWW_INDEX.setdefault(yf_sym, []).append(groww_sym)

INDEX_GROWW_SYMBOL_CANDIDATES: dict[str, list[str]] = {
    "NIFTY 50": ["NIFTY"],
    "NIFTY NEXT 50": ["NIFTYJR", "NIFTYNEXT50"],
    "NIFTY BANK": ["BANKNIFTY", "NIFTYBANK"],
    "NIFTY IT": ["NIFTYIT"],
    "NIFTY FINANCIAL SERVICES": ["FINNIFTY", "NIFTYFIN", "NIFTYFINSERVICE"],
    "NIFTY AUTO": ["NIFTYAUTO"],
    "NIFTY FMCG": ["NIFTYFMCG"],
    "NIFTY METAL": ["NIFTYMETAL"],
    "NIFTY REALTY": ["NIFTYREALTY"],
    "NIFTY ENERGY": ["NIFTYENERGY"],
    "NIFTY PHARMA": ["NIFTYPHARMA"],
    "NIFTY PSU BANK": ["NIFTYPSUBANK"],
    "NIFTY MEDIA": ["NIFTYMEDIA"],
    "NIFTY MIDCAP 150": ["NIFTYMIDCAP150", "NIFTYM150", "NIFTYMID150"],
    "NIFTY SMALLCAP 250": ["NIFTYSMALLCAP250", "NIFTYSML250", "NIFTYSMLCAP250"],
    "SENSEX": ["SENSEX"],
}

INDEX_ALIASES: dict[str, str] = {
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "NIFTY BANK",
    "^NSMIDCP": "NIFTY NEXT 50",
    "^CNXIT": "NIFTY IT",
    "^CNXFIN": "NIFTY FINANCIAL SERVICES",
    "^BSESN": "SENSEX",
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
}


def normalize_index_name(label: str) -> str:
    key = (label or "").strip().upper()
    if key in INDEX_ALIASES:
        return INDEX_ALIASES[key]
    if key.startswith("^"):
        return key
    return key


def index_name_to_groww_symbols(index_name: str) -> list[str]:
    """Ordered Groww CASH segment symbols for an NSE index label."""
    raw = (index_name or "").strip()
    name = normalize_index_name(raw)
    if name in INDEX_GROWW_SYMBOL_CANDIDATES:
        return list(INDEX_GROWW_SYMBOL_CANDIDATES[name])

    key = raw.upper().removesuffix(".NS")
    if key in GROWW_INDEX_SYMBOL_TO_YF:
        return [key]
    if raw in YF_TO_GROWW_INDEX:
        return list(YF_TO_GROWW_INDEX[raw])

    if key.startswith("NIFTY "):
        slug = "NIFTY" + key[6:].replace(" ", "").replace("&", "AND").replace("-", "")
        return [slug]

    compact = key.replace(" ", "")
    return [compact] if compact else []


def resolve_groww_symbol_candidates(ticker: str) -> list[str]:
    """Return ordered Groww symbols to try for a user ticker."""
    raw = (ticker or "").strip()
    if not raw:
        return []

    if raw.startswith("^") or raw.upper() in INDEX_ALIASES or normalize_index_name(raw) in INDEX_GROWW_SYMBOL_CANDIDATES:
        return index_name_to_groww_symbols(raw)

    sym = raw.upper().removesuffix(".NS").removesuffix(".BO")
    return [sym]
