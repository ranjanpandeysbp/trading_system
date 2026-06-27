"""
us_market_yfinance.py
---------------------
Yahoo Finance symbol mapping for US equities and benchmark indices.
"""

from __future__ import annotations

# Benchmark indices (for quotes / index-level charts)
US_INDEX_YF_TICKERS: dict[str, str] = {
    "DOW 30": "^DJI",
    "DOW JONES": "^DJI",
    "S&P 500": "^GSPC",
    "SP 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "NASDAQ COMPOSITE": "^IXIC",
    "NASDAQ 100": "^NDX",
    "RUSSELL 2000": "^RUT",
    "RUSSELL": "^RUT",
}

# Liquid index ETFs (optional scan targets)
US_INDEX_ETF_YF: dict[str, str] = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "DIA": "DIA",
    "IWM": "IWM",
}


def us_symbol_to_yf(symbol: str) -> str:
    """Map a US equity or index label to a Yahoo Finance ticker."""
    raw = (symbol or "").strip().upper()
    if not raw:
        return raw
    if raw in US_INDEX_YF_TICKERS:
        return US_INDEX_YF_TICKERS[raw]
    if raw in US_INDEX_ETF_YF:
        return US_INDEX_ETF_YF[raw]
    if raw.startswith("^") or raw.endswith("=F"):
        return raw
    # Already a Yahoo ticker (e.g. BRK-B, BF-B)
    if "." in raw or "-" in raw:
        return raw
    return raw


def is_us_index_symbol(symbol: str) -> bool:
    key = (symbol or "").strip().upper()
    return key in US_INDEX_YF_TICKERS or key in US_INDEX_ETF_YF
