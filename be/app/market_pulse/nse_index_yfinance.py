"""
Single source of truth for NSE index / compact symbol -> Yahoo Finance tickers.

Update mappings here when Yahoo symbols change. Verified ^ index symbols and
strategy-index ETF proxies are listed first; EQUITY_L.csv (NSE equity master)
is used to validate .NS fallbacks for listed NSE symbols.

EQUITY_L source: https://archives.nseindia.com/content/equities/EQUITY_L.csv
"""

from __future__ import annotations

import csv
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

NSE_EQUITY_L_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
_DEFAULT_EQUITY_L_PATH = Path(__file__).resolve().parent / "data" / "EQUITY_L.csv"

NIFTY50_YF = "^NSEI"

# Yahoo ^CNX* symbols that do not return data (use constituent-proxy OHLC instead)
BROKEN_YF_INDEX_TICKERS: frozenset[str] = frozenset({
    "^CNXCEMENT",
    "^CNXCHEM",
    "^CNXCONSRDURBL",
    "^CNXHEALTH",
    "^CNXDEFENCE",
    "^CNXMOBILITY",
    "^CNXHOUSING",
    "^CNXOILGAS",
    "NIFTYMSL.NS",
    # Only ~1 row of history on Yahoo regardless of period requested
    "^CNXFIN",
    # Invented heuristics — never valid on Yahoo
    "^NIFTYCEMENT",
    "^CNXNIFTYCEMENT",
    "^NSENIFTYCEMENT",
    "^CEMENT",
    "^NSECEMENT",
    "^NIFTYCHEMICALS",
    "^CNXNIFTYCHEMICALS",
    "^NSENIFTYCHEMICALS",
    "^CHEMICALS",
    "^CNXCHEMICALS",
    "^NSECHEMICALS",
    "^NIFTYCONSRDURBL",
    "^CNXNIFTYCONSRDURBL",
    "^NSENIFTYCONSRDURBL",
    "^CONSRDURBL",
    "^NIFTYHEALTHCARE",
    "^NIFTYMOBILITY",
    "^NIFTYHOUSING",
    "^NIFTYINDDEFENCE",
})

# Indices without reliable Yahoo index tickers — prefer constituent proxy OHLC
CONSTITUENT_PROXY_INDICES: frozenset[str] = frozenset({
    "NIFTY CEMENT",
    "NIFTY CHEMICALS",
    "NIFTY CONSUMER DURABLES",
    "NIFTY HEALTHCARE",
    "NIFTY HEALTHCARE INDEX",
    "NIFTY FINANCIAL SERVICES EX-BANK",
    "NIFTY INDIA DEFENCE",
    "NIFTY MOBILITY",
    "NIFTY HOUSING",
    "NIFTY OIL & GAS",
})

# ---------------------------------------------------------------------------
# NSE index display name (UPPER) -> primary Yahoo Finance symbol
# ---------------------------------------------------------------------------

NSE_INDEX_YF_TICKERS: dict[str, str] = {
    # --- Broad market benchmarks (verified ^ symbols) ---
    "SENSEX": "^BSESN",
    "NIFTY 50": "^NSEI",
    "NIFTY NEXT 50": "^NSMIDCP",
    "NIFTY 100": "^CNX100",
    "NIFTY 200": "^CNX200",
    "NIFTY 500": "^CRSLDX",
    "NIFTY MIDCAP 50": "^NSEMDCP50",
    "NIFTY MIDCAP 100": "^CNXMID",
    "NIFTY SMALLCAP 100": "^CNXSML",
    # --- Sectoral indices ---
    "NIFTY BANK": "^NSEBANK",
    "NIFTY AUTO": "^CNXAUTO",
    "NIFTY FMCG": "^CNXFMCG",
    "NIFTY IT": "^CNXIT",
    "NIFTY MEDIA": "^CNXMEDIA",
    "NIFTY METAL": "^CNXMETAL",
    "NIFTY PHARMA": "^CNXPHARMA",
    "NIFTY PSU BANK": "^CNXPSUBANK",
    "NIFTY REALTY": "^CNXREALTY",
    "NIFTY PRIVATE BANK": "NIFTY_PVT_BANK.NS",
    # --- Thematic indices ---
    "NIFTY COMMODITIES": "^CNXCM",
    "NIFTY CONSUMPTION": "^CNXCONSUM",
    "NIFTY INDIA CONSUMPTION": "^CNXCONSUM",
    "NIFTY INFRA": "^CNXINFRA",
    "NIFTY INFRASTRUCTURE": "^CNXINFRA",
    "NIFTY ENERGY": "^CNXENERGY",
    "NIFTY CPSE": "^CNXSE",
    "NIFTY PSE": "^CNXSE",
    # --- Strategy indices (ETF proxies on NSE) ---
    "NIFTY TOTAL MARKET MOMENTUM QUALITY 50": "AONETMMQ50.NS",
    "NIFTY 200 MOMENTUM 30": "MOMENTUM.NS",
    "NIFTY 100 QUALITY 30": "NETFQ30.NS",
    "NIFTY 50 VALUE 20": "NV20.NS",
    "NIFTY ALPHA 50": "ALPHA.NS",
    "NIFTY 50 EQUAL WEIGHT": "50EQUAL.NS",
    "NIFTY DIVIDEND OPPORTUNITIES 50": "DIVOPPBEES.NS",
    # --- Additional indices (ETF / alternate Yahoo symbols) ---
    "NIFTY FINANCIAL SERVICES": "NIFTY_FIN_SERVICE.NS",
    "NIFTY FIN SERVICE": "NIFTY_FIN_SERVICE.NS",
    "NIFTY MIDCAP 150": "NIFTYMIDCAP150.NS",
    # NIFTYMSL.NS 404s on Yahoo (delisted/never existed there) — ^NSEMDCP50
    # (Nifty Midcap 50) is the closest liquid, verified proxy with real volume.
    "NIFTY MIDCAP SELECT": "^NSEMDCP50",
    "NIFTY MID SELECT": "^NSEMDCP50",
    "NIFTY SMALLCAP 50": "NIFTYSMLCAP50.NS",
    "NIFTY SMALLCAP 250": "NIFTYSMALLCAP250.NS",
    "NIFTY LARGEMIDCAP 250": "NIFTYLARGEMID250.NS",
    "NIFTY MIDSML 400": "NIFTYMIDSML400.NS",
    "NIFTY MICROCAP 250": "NIFTYMICROCAP250.NS",
    "NIFTY TOTAL MARKET": "NIFTYTOTALMARKET.NS",
    "NIFTY INDIA MANUFACTURING": "^CNXINDIAMFG",
    "NIFTY INDIA TOURISM": "^CNXTOURISM",
    "NIFTY SERVICES SECTOR": "^CNXSERVICE",
    # Proxy-only (no working Yahoo index ticker) — see CONSTITUENT_PROXY_INDICES
    "NIFTY HEALTHCARE": "",
    "NIFTY HEALTHCARE INDEX": "",
    "NIFTY CEMENT": "",
    "NIFTY CONSUMER DURABLES": "",
    "NIFTY INDIA DEFENCE": "",
    "NIFTY MOBILITY": "",
    "NIFTY OIL & GAS": "",
    "NIFTY CHEMICALS": "",
    "NIFTY HOUSING": "",
    "NIFTY FINANCIAL SERVICES EX-BANK": "",
}

# Aliases -> canonical NSE index name key in NSE_INDEX_YF_TICKERS
# Legacy / compact tickers -> current NSE symbol (post-rename)
NSE_STOCK_ALIASES: dict[str, str] = {
    "TATAMOTORS": "TMPV",
    "TATAMTRDVR": "TMPV",
    "ZOMATO": "ETERNAL",
    "HDFC": "HDFCBANK",
    "SBICARDS": "SBICARD",
    "EQUITAS": "EQUITASBNK",
    "AUTOAX": "AUTOAXLES",
    "KVB": "KARURVYSYA",
    "BAJARIA": "BAJAJFINSV",
}

INDEX_NAME_ALIASES: dict[str, str] = {
    "NIFTY": "NIFTY 50",
    "NIFTY50": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "NIFTY BANK": "NIFTY BANK",
    "MIDCPNIFTY": "NIFTY MIDCAP SELECT",
    "NIFTY FIN SERVICE": "NIFTY FINANCIAL SERVICES",
    "NIFTY FINANCIAL SERVICES 25/50": "NIFTY FINANCIAL SERVICES",
    "NIFTY MIDCAP SELECT": "NIFTY MIDCAP SELECT",
    "NIFTY MID SELECT": "NIFTY MIDCAP SELECT",
    "NIFTY INFRA": "NIFTY INFRASTRUCTURE",
    "NIFTY INDIA CONSUMPTION": "NIFTY CONSUMPTION",
    "NIFTY CPSE": "NIFTY PSE",
    "NIFTY CENTRAL PUBLIC SECTOR ENTERPRISES": "NIFTY PSE",
    "NIFTY HEALTHCARE INDEX": "NIFTY HEALTHCARE",
    "NIFTY CEMENT INDEX": "NIFTY CEMENT",
    "NIFTY CHEMICALS INDEX": "NIFTY CHEMICALS",
    "NIFTY FINANCIAL SERVICES EX-BANK": "NIFTY FINANCIAL SERVICES EX-BANK",
}

# Sector rotation universe when NSE breadth API is unavailable
SECTOR_INDEX_NAMES: tuple[str, ...] = (
    "NIFTY AUTO",
    "NIFTY BANK",
    "NIFTY CEMENT",
    "NIFTY CHEMICALS",
    "NIFTY COMMODITIES",
    "NIFTY CONSUMPTION",
    "NIFTY CONSUMER DURABLES",
    "NIFTY ENERGY",
    "NIFTY FINANCIAL SERVICES",
    "NIFTY FINANCIAL SERVICES EX-BANK",
    "NIFTY FMCG",
    "NIFTY HEALTHCARE",
    "NIFTY HOUSING",
    "NIFTY INDIA DEFENCE",
    "NIFTY INDIA MANUFACTURING",
    "NIFTY INDIA TOURISM",
    "NIFTY INFRASTRUCTURE",
    "NIFTY IT",
    "NIFTY MEDIA",
    "NIFTY METAL",
    "NIFTY MOBILITY",
    "NIFTY OIL & GAS",
    "NIFTY PHARMA",
    "NIFTY PRIVATE BANK",
    "NIFTY PSU BANK",
    "NIFTY PSE",
    "NIFTY REALTY",
    "NIFTY SERVICES SECTOR",
)

# Legacy map: index name -> primary Yahoo symbol (empty = constituent proxy only)
SECTOR_INDEX_YF_TICKERS: dict[str, str] = {
    name: (NSE_INDEX_YF_TICKERS.get(name) or "")
    for name in SECTOR_INDEX_NAMES
}

# Groww / compact index codes -> Yahoo Finance
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
    "NIFTYPVTBANK": "NIFTY_PVT_BANK.NS",
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
}

# Human-readable labels for live market ticker strip (news scanner)
INDIA_MARKET_DISPLAY_YF: dict[str, str] = {
    "Nifty 50": "^NSEI",
    "Sensex": "^BSESN",
    "Bank Nifty": "^NSEBANK",
    "India VIX": "^INDIAVIX",
    "Nifty IT": "^CNXIT",
    "Nifty Next 50": "^NSMIDCP",
    "Nifty 100": "^CNX100",
    "Nifty Midcap 150": "NIFTYMIDCAP150.NS",
}

# Global / macro display labels -> verified Yahoo Finance symbols
GLOBAL_MARKET_DISPLAY_YF: dict[str, str] = {
    "Dow Jones": "^DJI",
    "S&P 500": "^GSPC",
    "Nasdaq Composite": "^IXIC",
    "Russell 2000": "^RUT",
    "Dow Futures": "YM=F",
    "S&P 500 Futures": "ES=F",
    "Nasdaq Futures": "NQ=F",
    "Nikkei 225 (Japan)": "^N225",
    "Hang Seng (HK)": "^HSI",
    "Shanghai (China)": "000001.SS",
    "KOSPI (Korea)": "^KS11",
    "Straits Times (SG)": "^STI",
    "ASX 200 (Australia)": "^AXJO",
    "Taiwan Weighted": "^TWII",
    "FTSE 100 (UK)": "^FTSE",
    "DAX 40 (Germany)": "^GDAXI",
    "CAC 40 (France)": "^FCHI",
    "DXY (Dollar Index)": "DX-Y.NYB",
    "USD/INR": "USDINR=X",
    "EUR/INR": "EURINR=X",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Crude Oil (WTI)": "CL=F",
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
    "Solana": "SOL-USD",
    "US 10Y Bond Yield": "^TNX",
    "US 2Y Bond Yield": "^IRX",
}

MARKET_DISPLAY_YF: dict[str, str] = {
    **INDIA_MARKET_DISPLAY_YF,
    **GLOBAL_MARKET_DISPLAY_YF,
}


# Market Pulse / UI display labels -> canonical NSE index name
DISPLAY_INDEX_ALIASES: dict[str, str] = {
    "BANK NIFTY": "NIFTY BANK",
    "NIFTY MIDCAP 150": "NIFTY MIDCAP 150",
    "SENSEX": "SENSEX",
    "NIFTY 50": "NIFTY 50",
}


def market_display_to_yf(label: str) -> str | None:
    """Map UI display label (e.g. 'Dow Jones', 'Nifty 50') to Yahoo Finance symbol."""
    key = (label or "").strip()
    if not key:
        return None
    if key in MARKET_DISPLAY_YF:
        sym = MARKET_DISPLAY_YF[key]
        return sym if sym else None
    lower = key.lower()
    for display, sym in MARKET_DISPLAY_YF.items():
        if display.lower() == lower:
            return sym if sym else None
    return None


def normalize_index_name(index_name: str) -> str:
    """Return canonical uppercase NSE index name."""
    name = (index_name or "").strip().upper()
    name = DISPLAY_INDEX_ALIASES.get(name, name)
    return INDEX_NAME_ALIASES.get(name, name)


@lru_cache(maxsize=1)
def load_nse_equity_symbols(path: str | None = None) -> frozenset[str]:
    """Load NSE equity SYMBOL values from local EQUITY_L.csv (or given path)."""
    csv_path = Path(path) if path else _DEFAULT_EQUITY_L_PATH
    if not csv_path.is_file():
        logger.debug("NSE EQUITY_L not found at %s", csv_path)
        return frozenset()
    symbols: set[str] = set()
    try:
        with csv_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if row and row[0] and row[0] != "SYMBOL":
                    symbols.add(row[0].strip().upper())
    except OSError as exc:
        logger.warning("Failed reading NSE EQUITY_L (%s): %s", csv_path, exc)
        return frozenset()
    return frozenset(symbols)


def _is_listed_nse_symbol(symbol: str) -> bool:
    base = symbol.removesuffix(".NS").upper()
    listed = load_nse_equity_symbols()
    return not listed or base in listed


def index_requires_constituent_proxy(index_name: str) -> bool:
    """True when index OHLC should be built from constituents, not ^CNX* tickers."""
    return normalize_index_name(index_name) in CONSTITUENT_PROXY_INDICES


def index_name_to_yf(index_name: str) -> str | None:
    """Map NSE index name to primary Yahoo Finance ticker."""
    name = normalize_index_name(index_name)
    primary = NSE_INDEX_YF_TICKERS.get(name)
    if not primary or primary in BROKEN_YF_INDEX_TICKERS:
        return None
    return primary


def is_nse_index_symbol(symbol: str) -> bool:
    """True for Nifty/BankNifty-style index codes (not individual equities)."""
    key = (symbol or "").strip().upper().removesuffix(".NS")
    if key in GROWW_INDEX_SYMBOL_TO_YF:
        return True
    name = normalize_index_name(key)
    return name in NSE_INDEX_YF_TICKERS or name in CONSTITUENT_PROXY_INDICES


def resolve_nse_equity_symbol(symbol: str) -> str:
    """Map legacy ticker to current NSE symbol (e.g. TATAMOTORS -> TMPV)."""
    key = (symbol or "").strip().upper().removesuffix(".NS").removesuffix(".BO")
    return NSE_STOCK_ALIASES.get(key, key)


def filter_tradeable_nse_symbols(symbols: list[str], limit: int = 25) -> list[str]:
    """Drop delisted / unknown symbols before Yahoo or Groww batch fetches."""
    listed = load_nse_equity_symbols()
    out: list[str] = []
    for raw in symbols:
        sym = resolve_nse_equity_symbol((raw or "").strip().upper())
        if not sym or sym in out:
            continue
        if listed and sym not in listed:
            continue
        out.append(sym)
        if len(out) >= limit:
            break
    return out


def index_yf_candidates(index_name: str) -> list[str]:
    """Ordered Yahoo Finance symbols to try for an NSE index or market display label."""
    name = canonical_index_name(index_name)

    display_yf = market_display_to_yf(name)
    if display_yf:
        return [display_yf]

    key = (index_name or "").strip().upper().removesuffix(".NS")
    if key in GROWW_INDEX_SYMBOL_TO_YF:
        sym = GROWW_INDEX_SYMBOL_TO_YF[key]
        if sym and sym not in BROKEN_YF_INDEX_TICKERS:
            return [sym]

    if index_requires_constituent_proxy(name):
        return []

    if name in NSE_INDEX_YF_TICKERS:
        primary = NSE_INDEX_YF_TICKERS[name]
        if not primary:
            return []
        if primary not in BROKEN_YF_INDEX_TICKERS:
            return [primary]
        return []

    out: list[str] = []
    primary = NSE_INDEX_YF_TICKERS.get(name)
    if primary and primary not in BROKEN_YF_INDEX_TICKERS:
        out.append(primary)

    # Only verified NSE-listed .NS symbols — never invent ^CNX/^NSE heuristics
    if name.startswith("NIFTY "):
        slug = name.replace("NIFTY ", "").replace(" ", "").replace("&", "").replace("-", "")
        ns_candidate = f"NIFTY{slug}.NS"
        if _is_listed_nse_symbol(ns_candidate) and ns_candidate not in BROKEN_YF_INDEX_TICKERS:
            out.append(ns_candidate)
        if slug in ("PVTBANK", "PRIVATEBANK"):
            out.append("NIFTY_PVT_BANK.NS")

    deduped: list[str] = []
    for sym in out:
        if sym and sym not in deduped and sym not in BROKEN_YF_INDEX_TICKERS:
            deduped.append(sym)
    return deduped


def sector_fallback_index_names() -> list[str]:
    """Static sector index list when NSE breadth API is unavailable."""
    return sorted(SECTOR_INDEX_NAMES)


# NSE index label → Groww trading_symbol candidates (first match wins)
INDEX_GROWW_SYMBOL_CANDIDATES: dict[str, list[str]] = {
    "NIFTY 50": ["NIFTY"],
    "NIFTY NEXT 50": ["NIFTYJR", "NIFTYNEXT50"],
    "NIFTY BANK": ["BANKNIFTY", "NIFTYBANK"],
    "NIFTY IT": ["NIFTYIT"],
    "NIFTY FINANCIAL SERVICES": ["FINNIFTY", "NIFTYFIN", "NIFTYFINSERVICE"],
    "NIFTY AUTO": ["NIFTYAUTO"],
    "NIFTY FMCG": ["NIFTYFMCG", "CNXFMCG"],
    "NIFTY METAL": ["NIFTYMETAL", "CNXMETAL"],
    "NIFTY REALTY": ["NIFTYREALTY", "CNXREALTY"],
    "NIFTY ENERGY": ["NIFTYENERGY", "CNXENERGY"],
    "NIFTY OIL & GAS": ["NIFTYENERGY", "CNXENERGY"],
    "NIFTY PHARMA": ["NIFTYPHARMA", "CNXPHARMA"],
    "NIFTY PSU BANK": ["NIFTYPSUBANK", "CNXPSUBANK"],
    "NIFTY PRIVATE BANK": ["NIFTYPVTBANK", "NIFTYPRIVATEBANK"],
    "NIFTY MEDIA": ["NIFTYMEDIA", "CNXMEDIA"],
    "NIFTY INFRASTRUCTURE": ["NIFTYINFRA", "CNXINFRA"],
    "NIFTY INFRA": ["NIFTYINFRA", "CNXINFRA"],
    "NIFTY CONSUMPTION": ["NIFTYCONSUMPTION"],
    "NIFTY COMMODITIES": ["NIFTYCOMMODITIES"],
    "NIFTY PSE": ["NIFTYPSE", "CNXPSE"],
    "NIFTY MIDCAP 150": ["NIFTYMIDCAP150", "NIFTYM150", "NIFTYMID150"],
    "NIFTY SMALLCAP 250": ["NIFTYSMALLCAP250", "NIFTYSML250", "NIFTYSMLCAP250"],
    "NIFTY HEALTHCARE": ["NIFTYHEALTHCARE"],
    "NIFTY HEALTHCARE INDEX": ["NIFTYHEALTHCARE"],
    "NIFTY CEMENT": ["NIFTYCEMENT"],
    "NIFTY CHEMICALS": ["NIFTYCHEMICALS"],
    "NIFTY CONSUMER DURABLES": ["NIFTYCONSRDURBL"],
    "NIFTY FINANCIAL SERVICES EX-BANK": ["NIFTYFINSERVEXBNK"],
    "NIFTY SERVICES SECTOR": ["NIFTYSERVSECTOR"],
    "NIFTY MOBILITY": ["NIFTYMOBILITY"],
    "NIFTY HOUSING": ["NIFTYHOUSING"],
    "NIFTY INDIA DEFENCE": ["NIFTYINDDEFENCE"],
    "NIFTY INDIA MANUFACTURING": ["NIFTYINDMFG"],
    "NIFTY INDIA TOURISM": ["NIFTYINDTOURISM"],
    "SENSEX": ["SENSEX"],
}


def _build_groww_symbol_to_canonical() -> dict[str, str]:
    rev: dict[str, str] = {}
    for idx_name, syms in INDEX_GROWW_SYMBOL_CANDIDATES.items():
        canonical = INDEX_NAME_ALIASES.get(normalize_index_name(idx_name), idx_name)
        for sym in syms:
            rev[sym.upper()] = canonical
    for compact, yf_sym in GROWW_INDEX_SYMBOL_TO_YF.items():
        if compact.upper() not in rev:
            rev[compact.upper()] = INDEX_NAME_ALIASES.get(
                normalize_index_name(compact), normalize_index_name(compact),
            )
    return rev


GROWW_SYMBOL_TO_CANONICAL: dict[str, str] = _build_groww_symbol_to_canonical()


def canonical_index_name(label: str) -> str:
    """Resolve Groww compact symbol or alias to canonical NSE index name."""
    key = (label or "").strip().upper().removesuffix(".NS")
    if not key:
        return ""
    if key in GROWW_SYMBOL_TO_CANONICAL:
        return GROWW_SYMBOL_TO_CANONICAL[key]
    name = normalize_index_name(label)
    return INDEX_NAME_ALIASES.get(name, name)


def index_name_to_groww_symbols(index_name: str) -> list[str]:
    """Ordered Groww CASH segment symbols for an NSE index / sector label."""
    name = normalize_index_name((index_name or "").strip())
    name = INDEX_NAME_ALIASES.get(name, name)
    if name in INDEX_GROWW_SYMBOL_CANDIDATES:
        return list(INDEX_GROWW_SYMBOL_CANDIDATES[name])

    key = (index_name or "").strip().upper().removesuffix(".NS")
    if key in GROWW_INDEX_SYMBOL_TO_YF:
        return [key]

    if name.startswith("NIFTY "):
        slug = "NIFTY" + name[6:].replace(" ", "").replace("&", "AND").replace("-", "")
        return [slug]

    compact = name.replace(" ", "")
    return [compact] if compact else []


def groww_symbol_to_yf(symbol: str) -> str:
    """Map compact index symbol (e.g. BANKNIFTY, NIFTYIT) to Yahoo Finance."""
    key = (symbol or "").strip().upper()
    if key in GROWW_INDEX_SYMBOL_TO_YF:
        return GROWW_INDEX_SYMBOL_TO_YF[key]
    cands = index_yf_candidates(canonical_index_name(key))
    return cands[0] if cands else ""


def stock_symbol_to_yf(symbol: str) -> str:
    """Map NSE equity symbol to Yahoo Finance (.NS suffix)."""
    sym = resolve_nse_equity_symbol(symbol)
    if not sym:
        return sym
    if sym.endswith(".NS") or sym.endswith(".BO"):
        return sym
    return f"{sym}.NS"
