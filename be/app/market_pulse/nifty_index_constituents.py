"""
NSE index constituent symbols — niftyindices.com CSV + static lists + INDEX_OPTIONS.

NSE equity-stockIndices often 404s for newer sector indices; Yahoo ^CNX* tickers are
missing for several of them. All tabs use these lists when live NSE quotes fail.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from functools import lru_cache
from typing import Iterable

import requests

from app.market_pulse.nse_index_yfinance import INDEX_NAME_ALIASES, normalize_index_name

logger = logging.getLogger(__name__)

_NIFTYINDICES_CSV_BASE = "https://www.niftyindices.com/IndexConstituent"

# Canonical index name (UPPER) -> niftyindices CSV filename
_NIFTYINDICES_CSV_FILES: dict[str, str] = {
    "NIFTY AUTO": "ind_niftyautolist.csv",
    "NIFTY FMCG": "ind_niftyfmcglist.csv",
    "NIFTY IT": "ind_niftyitlist.csv",
    "NIFTY METAL": "ind_niftymetallist.csv",
    "NIFTY ENERGY": "ind_niftyenergylist.csv",
    "NIFTY PHARMA": "ind_niftypharmalist.csv",
    "NIFTY REALTY": "ind_niftyrealtylist.csv",
    "NIFTY MEDIA": "ind_niftymedialist.csv",
    "NIFTY PSU BANK": "ind_niftypsubanklist.csv",
    "NIFTY INFRA": "ind_niftyinfralist.csv",
    "NIFTY INFRASTRUCTURE": "ind_niftyinfralist.csv",
    "NIFTY COMMODITIES": "ind_niftycommoditieslist.csv",
    "NIFTY CONSUMPTION": "ind_niftyconsumptionlist.csv",
    "NIFTY OIL & GAS": "ind_niftyoilgaslist.csv",
    "NIFTY HEALTHCARE": "ind_niftyhealthcarelist.csv",
    "NIFTY HEALTHCARE INDEX": "ind_niftyhealthcarelist.csv",
    "NIFTY CONSUMER DURABLES": "ind_niftyconsumerdurableslist.csv",
}

# Static lists when CSV is not yet published (sources: NSE Indices factsheets, Mar 2026)
NIFTY_CEMENT = [
    "ULTRACEMCO", "GRASIM", "AMBUJACEM", "SHREECEM", "JKCEMENT", "DALBHARAT", "ACC",
    "RAMCOCEM", "JSWCEMENT", "NUVOCO", "INDIACEM", "JKLAKSHMI", "STARCEMENT",
    "BIRLACORPN", "PRSMJOHNSN", "ORIENTCEM",
]

NIFTY_CHEMICALS = [
    "PIDILITIND", "SOLARINDS", "SRF", "LINDEINDIA", "UPL", "TATACHEM", "CHAMBLFERT",
    "AARTIIND", "DEEPAKFERT", "PCBL", "SWANCORP", "COROMANDEL", "DEEPAKNTR",
    "FLUOROCHEM", "HSCL", "NAVINFLUOR", "PIIND", "SUMICHEM", "ATUL", "BAYERCROP",
]

NIFTY_CONSUMER_DURABLES = [
    "AMBER", "BATAINDIA", "BLUESTARCO", "CROMPTON", "DIXON", "HAVELLS", "KAJARIACER",
    "KALYANKJIL", "LGEINDIA", "PGEL", "TITAN", "VOLTAS", "WHIRLPOOL",
]

NIFTY_HEALTHCARE = [
    "ABBOTINDIA", "ALKEM", "APOLLOHOSP", "AUROPHARMA", "BIOCON", "CIPLA", "DIVISLAB",
    "DRREDDY", "FORTIS", "GLENMARK", "IPCALAB", "LAURUSLABS", "LUPIN", "MANKIND",
    "MAXHEALTH", "PPLPHARMA", "SUNPHARMA", "SYNGENE", "TORNTPHARM", "ZYDUSLIFE",
]

NIFTY_FINANCIAL_SERVICES_EX_BANK = [
    "BAJFINANCE", "LICI", "BAJAJFINSV", "SBILIFE", "SHRIRAMFIN", "JIOFIN", "HDFCLIFE",
    "CHOLAFIN", "MUTHOOTFIN", "PFC", "IRFC", "HDFCAMC", "BSE", "ICICIPRULI", "ICICIGI",
    "RECLTD", "ABCAPITAL", "POLICYBZR", "SBICARD", "LTF", "PAYTM", "MCX", "MFSL",
    "360ONE", "LICHSGFIN", "CDSL", "PNBHOUSING", "ANGELONE", "CAMS", "IEX",
]

STATIC_INDEX_CONSTITUENTS: dict[str, list[str]] = {
    "NIFTY CEMENT": NIFTY_CEMENT,
    "NIFTY CHEMICALS": NIFTY_CHEMICALS,
    "NIFTY CONSUMER DURABLES": NIFTY_CONSUMER_DURABLES,
    "NIFTY HEALTHCARE": NIFTY_HEALTHCARE,
    "NIFTY HEALTHCARE INDEX": NIFTY_HEALTHCARE,
    "NIFTY FINANCIAL SERVICES EX-BANK": NIFTY_FINANCIAL_SERVICES_EX_BANK,
}

_DUMMY_SYMBOL_RE = re.compile(r"^DUMMY", re.I)


def _canonical_index_name(index_name: str) -> str:
    name = normalize_index_name(index_name)
    return INDEX_NAME_ALIASES.get(name, name)


def _dedupe_symbols(symbols: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = (raw or "").strip().upper()
        if not sym or sym in seen or _DUMMY_SYMBOL_RE.match(sym):
            continue
        seen.add(sym)
        out.append(sym)
    return out


@lru_cache(maxsize=64)
def _fetch_niftyindices_csv_symbols(csv_filename: str) -> tuple[str, ...]:
    url = f"{_NIFTYINDICES_CSV_BASE}/{csv_filename}"
    try:
        resp = requests.get(
            url,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            return ()
        text = (resp.text or "").strip()
        if not text.startswith("Company"):
            return ()
        rows = csv.DictReader(io.StringIO(text))
        symbols = [
            (row.get("Symbol") or "").strip().upper()
            for row in rows
            if (row.get("Symbol") or "").strip()
        ]
        return tuple(_dedupe_symbols(symbols))
    except Exception as exc:
        logger.debug("niftyindices CSV %s failed: %s", csv_filename, exc)
        return ()


def get_index_constituent_symbols(index_name: str) -> list[str]:
    """Return NSE equity symbols for an index (CSV, static list, then INDEX_OPTIONS)."""
    canonical = _canonical_index_name(index_name)

    csv_file = _NIFTYINDICES_CSV_FILES.get(canonical)
    if csv_file:
        from_csv = list(_fetch_niftyindices_csv_symbols(csv_file))
        if from_csv:
            return from_csv

    static = STATIC_INDEX_CONSTITUENTS.get(canonical)
    if static:
        return list(static)

    key = constituent_key_for_index(index_name)
    if key:
        from app.market_pulse.ticker_utils import INDEX_OPTIONS

        symbols = INDEX_OPTIONS.get(key) or []
        if symbols:
            return list(symbols)
    return []


def constituent_key_for_index(index_name: str) -> str | None:
    """Map NSE index label to INDEX_OPTIONS key."""
    from app.market_pulse.ticker_utils import INDEX_OPTIONS

    name = _canonical_index_name(index_name)
    if name in INDEX_OPTIONS:
        return name
    for key in INDEX_OPTIONS:
        if key != "Default Groww Tickers" and key.upper() == name:
            return key
    return None
