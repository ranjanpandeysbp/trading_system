"""
us_index_constituents.py
------------------------
Full US index constituent lists — Wikipedia + iShares ETF holdings, with static fallbacks.
"""

from __future__ import annotations

import io
import logging
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"

_GITHUB_CSV_SOURCES: dict[str, tuple[str, str]] = {
    # name -> (url, symbol column)
    "sp500": (
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
        "Symbol",
    ),
    "nasdaq100": (
        "https://raw.githubusercontent.com/mhyavas/SP500-NASDAQ100/main/nasdaq100.csv",
        "Symbol",
    ),
    "russell2000": (
        "https://raw.githubusercontent.com/ikoniaris/Russell2000/master/russell_2000_components.csv",
        "Ticker",
    ),
    "sp500_alt": (
        "https://raw.githubusercontent.com/fja05680/sp500/master/sp500.csv",
        "Symbol",
    ),
}

# Yahoo Finance uses hyphen for share classes (BRK.B → BRK-B)
_YF_CLASS_RE = re.compile(r"^([A-Z0-9]+)\.([A-Z])$")


def normalize_us_ticker(raw: str) -> str:
    """Normalize symbol for app display and yfinance (BRK.B → BRK-B)."""
    s = str(raw or "").strip().upper()
    if not s or s in ("NAN", "NONE", "-"):
        return ""
    m = _YF_CLASS_RE.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return s.replace(".", "-")


def _unique_sorted(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        sym = normalize_us_ticker(raw)
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return sorted(out)


def _read_github_csv(name: str) -> list[str]:
    """Load symbols from a curated GitHub raw CSV mirror."""
    spec = _GITHUB_CSV_SOURCES.get(name)
    if not spec:
        return []
    url, col = spec
    headers = {"User-Agent": "TrueBacktester/1.0 (index constituents; contact: local)"}
    resp = requests.get(url, headers=headers, timeout=45)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if col not in df.columns:
        for c in df.columns:
            if str(c).strip().lower() in ("symbol", "ticker"):
                col = c
                break
    return _unique_sorted(df[col].astype(str).tolist())


def _read_wikipedia_symbols(url: str, *, symbol_cols: tuple[str, ...] = ("Symbol", "Ticker")) -> list[str]:
    """Parse first Wikipedia table containing a Symbol/Ticker column."""
    headers = {"User-Agent": "TrueBacktester/1.0 (index constituents; contact: local)"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    for df in tables:
        flat_cols = [str(c[0] if isinstance(c, tuple) else c).strip() for c in df.columns]
        df.columns = flat_cols
        for col in symbol_cols:
            if col in df.columns:
                syms = df[col].astype(str).tolist()
                parsed = _unique_sorted(syms)
                if len(parsed) >= 10:
                    return parsed
        for col in df.columns:
            if "symbol" in col.lower() or col.lower() == "ticker":
                parsed = _unique_sorted(df[col].astype(str).tolist())
                if len(parsed) >= 10:
                    return parsed
    return []


def _read_ishares_holdings_csv(product_id: str, slug: str, etf: str, ajax_id: str = "1467271812596") -> list[str]:
    """Download iShares ETF holdings CSV and extract tickers."""
    url = (
        f"https://www.ishares.com/us/products/{product_id}/{slug}/"
        f"{ajax_id}.ajax?fileType=csv&fileName={etf}_holdings&dataType=fund"
    )
    headers = {"User-Agent": "TrueBacktester/1.0 (ETF holdings; contact: local)"}
    resp = requests.get(url, headers=headers, timeout=45)
    resp.raise_for_status()
    lines = resp.text.splitlines()
    # Find header row containing 'Ticker'
    start = 0
    for i, line in enumerate(lines[:25]):
        if "Ticker" in line and ("Name" in line or "Sector" in line):
            start = i
            break
    csv_text = "\n".join(lines[start:])
    df = pd.read_csv(io.StringIO(csv_text))
    col = None
    for c in df.columns:
        if str(c).strip().lower() == "ticker":
            col = c
            break
    if col is None:
        return []
    tickers = []
    for v in df[col].astype(str):
        v = v.strip()
        if v and v.lower() not in ("-", "nan", "cash", "usd") and not v.startswith("-"):
            tickers.append(v)
    return _unique_sorted(tickers)


def _load_cache(name: str) -> list[str] | None:
    path = _DATA_DIR / f"us_{name}.txt"
    if not path.is_file():
        return None
    lines = [normalize_us_ticker(ln) for ln in path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    return lines if lines else None


def _save_cache(name: str, symbols: list[str]) -> None:
    if not symbols:
        return
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _DATA_DIR / f"us_{name}.txt"
    path.write_text("\n".join(symbols) + "\n", encoding="utf-8")


def _fetch_with_fallback(name: str, fetcher, min_count: int = 10) -> list[str]:
    cached = _load_cache(name)
    fresh: list[str] = []
    try:
        fresh = fetcher()
        if len(fresh) >= min_count:
            _save_cache(name, fresh)
            return fresh
    except Exception as exc:
        logger.warning("US constituents fetch failed for %s: %s", name, exc)
    if cached and len(cached) >= min_count:
        return cached
    return fresh or cached or []


# ---------------------------------------------------------------------------
# Static fallbacks (used only when live fetch + cache both fail)
# ---------------------------------------------------------------------------

DOW_30_STATIC = [
    "AAPL", "AMGN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS",
    "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT",
    "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT", "AMZN",
]

US_INDEX_ETFS = ["SPY", "QQQ", "DIA", "IWM", "IVV", "IJH", "IJR"]


@lru_cache(maxsize=1)
def get_dow_30() -> list[str]:
    def _fetch():
        syms = _read_wikipedia_symbols(
            "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
            symbol_cols=("Symbol",),
        )
        return syms if len(syms) >= 25 else DOW_30_STATIC

    result = _fetch_with_fallback("dow30", _fetch, min_count=25)
    return result or DOW_30_STATIC


@lru_cache(maxsize=1)
def get_nasdaq_100() -> list[str]:
    def _fetch():
        for key in ("nasdaq100",):
            syms = _read_github_csv(key)
            if len(syms) >= 90:
                return syms
        return _read_wikipedia_symbols(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            symbol_cols=("Ticker", "Symbol"),
        )

    return _fetch_with_fallback("nasdaq100", _fetch, min_count=90)


@lru_cache(maxsize=1)
def get_sp_500() -> list[str]:
    def _fetch():
        for key in ("sp500", "sp500_alt"):
            syms = _read_github_csv(key)
            if len(syms) >= 450:
                return syms
        syms = _read_wikipedia_symbols(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            symbol_cols=("Symbol",),
        )
        if len(syms) >= 450:
            return syms
        return _read_ishares_holdings_csv("239726", "ishares-core-sp-500-etf", "IVV")

    return _fetch_with_fallback("sp500", _fetch, min_count=450)


@lru_cache(maxsize=1)
def get_sp_100() -> list[str]:
    """S&P 100 (mega / ultra-large cap proxy)."""

    def _fetch():
        syms = _read_wikipedia_symbols(
            "https://en.wikipedia.org/wiki/S%26P_100",
            symbol_cols=("Symbol", "Ticker"),
        )
        if len(syms) >= 90:
            return syms
        sp = get_sp_500()
        return sp[:100] if sp else syms

    return _fetch_with_fallback("sp100", _fetch, min_count=90)


@lru_cache(maxsize=1)
def get_sp_400_midcap() -> list[str]:
    def _fetch():
        syms = _read_wikipedia_symbols(
            "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
            symbol_cols=("Symbol",),
        )
        if len(syms) >= 350:
            return syms
        return _read_ishares_holdings_csv("239762", "ishares-core-sp-midcap-etf", "IJH")

    return _fetch_with_fallback("sp400", _fetch, min_count=350)


@lru_cache(maxsize=1)
def get_sp_600_smallcap() -> list[str]:
    def _fetch():
        syms = _read_wikipedia_symbols(
            "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
            symbol_cols=("Symbol",),
        )
        if len(syms) >= 550:
            return syms
        return _read_ishares_holdings_csv("239712", "ishares-core-sp-smallcap-etf", "IJR")

    return _fetch_with_fallback("sp600", _fetch, min_count=550)


@lru_cache(maxsize=1)
def get_russell_2000() -> list[str]:
    """Russell 2000 — GitHub mirror + iShares IWM holdings."""

    def _fetch():
        syms = _read_github_csv("russell2000")
        if len(syms) >= 1500:
            return syms
        syms = _read_ishares_holdings_csv("239710", "ishares-russell-2000-etf", "IWM")
        if len(syms) >= 1500:
            return syms
        wiki = _read_wikipedia_symbols(
            "https://en.wikipedia.org/wiki/Russell_2000_Index",
            symbol_cols=("Symbol", "Ticker"),
        )
        return wiki if len(wiki) > len(syms) else syms

    return _fetch_with_fallback("russell2000", _fetch, min_count=1500)


@lru_cache(maxsize=1)
def get_us_index_options() -> dict[str, list[str]]:
    """Full US index / cap-tier universes for ticker pickers."""
    dow = get_dow_30()
    ndx = get_nasdaq_100()
    sp5 = get_sp_500()
    sp1 = get_sp_100()
    sp4 = get_sp_400_midcap()
    sp6 = get_sp_600_smallcap()
    rut = get_russell_2000()

    return {
        "Dow 30": dow,
        f"Nasdaq 100 ({len(ndx)} stocks)": ndx,
        f"S&P 500 ({len(sp5)} stocks)": sp5,
        f"Russell 2000 ({len(rut)} stocks)": rut,
        f"US Megacap - S&P 100 ({len(sp1)} stocks)": sp1,
        f"US Large Cap - S&P 500 ({len(sp5)} stocks)": sp5,
        f"US Mid Cap - S&P 400 ({len(sp4)} stocks)": sp4,
        f"US Small Cap - S&P 600 ({len(sp6)} stocks)": sp6,
        f"US Small Cap - Russell 2000 ({len(rut)} stocks)": rut,
        "US Index ETFs (SPY/QQQ/DIA/IWM)": list(US_INDEX_ETFS),
    }


def refresh_us_constituents() -> dict[str, int]:
    """Clear caches and re-fetch all US lists. Returns symbol counts per key."""
    for fn in (
        get_dow_30, get_nasdaq_100, get_sp_500, get_sp_100,
        get_sp_400_midcap, get_sp_600_smallcap, get_russell_2000, get_us_index_options,
    ):
        fn.cache_clear()
    opts = get_us_index_options()
    return {k: len(v) for k, v in opts.items()}


def constituent_count_label(key: str) -> str:
    """Return human count for a US index key (handles dynamic labels)."""
    opts = get_us_index_options()
    return str(len(opts.get(key, [])))
