"""
futures_indices_engine.py
----------------------------
Command Center — NSE and World Indices → Load Futures.

- US index futures + Europe/Asia cash indices + Commodities/Crypto futures +
  USD Index: Yahoo Finance via `yfinance` (already a proven dependency
  elsewhere in this app). investing.com — the original source for this
  section — now Cloudflare-gates both its "in." and "www." subdomains with a
  JS bot-challenge that a plain HTTP request can't solve, so it no longer
  returns usable data. Yahoo has no free continuous futures contracts for
  the major European/Asian indices, so those are shown as their cash index
  instead (DAX/FTSE/CAC/Euro Stoxx 50/Hang Seng/Shanghai Composite/KOSPI) —
  still a genuine overnight pre-market read, just not technically a "future".
- GIFT Nifty (formerly SGX Nifty): 5paisa's server-rendered stock page.
  Source: https://www.5paisa.com/share-market-today/gift-nifty
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

__all__ = ["fetch_futures_indices", "fetch_gift_nifty"]

_GIFT_NIFTY_URL = "https://www.5paisa.com/share-market-today/gift-nifty"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# (yfinance symbol, display name, country, region, is_future)
_YF_INSTRUMENTS: list[tuple[str, str, str, str, bool]] = [
    ("ES=F", "S&P 500 Futures", "United States", "US", True),
    ("YM=F", "Dow Jones Futures", "United States", "US", True),
    ("NQ=F", "Nasdaq 100 Futures", "United States", "US", True),
    ("RTY=F", "Russell 2000 Futures", "United States", "US", True),
    ("^GDAXI", "DAX Index", "Germany", "Europe", False),
    ("^FTSE", "FTSE 100 Index", "United Kingdom", "Europe", False),
    ("^FCHI", "CAC 40 Index", "France", "Europe", False),
    ("^STOXX50E", "Euro Stoxx 50 Index", "Euro Zone", "Europe", False),
    ("NIY=F", "Nikkei 225 Futures", "Japan", "Asia", True),
    ("^HSI", "Hang Seng Index", "Hong Kong", "Asia", False),
    ("000001.SS", "Shanghai Composite Index", "China", "Asia", False),
    ("^KS11", "KOSPI Index", "South Korea", "Asia", False),
    ("GC=F", "Gold Futures", "Global", "Commodities", True),
    ("SI=F", "Silver Futures", "Global", "Commodities", True),
    ("CL=F", "WTI Crude Oil Futures", "Global", "Commodities", True),
    ("BZ=F", "Brent Crude Oil Futures", "Global", "Commodities", True),
    ("NG=F", "Natural Gas Futures", "Global", "Commodities", True),
    ("HG=F", "Copper Futures", "Global", "Commodities", True),
    ("BTC=F", "Bitcoin Futures", "Global", "Crypto", True),
    ("ETH=F", "Ether Futures", "Global", "Crypto", True),
    ("DX-Y.NYB", "US Dollar Index", "Global", "Currency", False),
]


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_num(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[₹,%\s]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_futures_indices() -> list[dict[str, Any]]:
    """US index futures + Europe/Asia cash indices + Commodities/Crypto futures
    + USD Index from Yahoo Finance, each tagged with a region and whether it's
    a genuine future."""
    import yfinance as yf

    out: list[dict[str, Any]] = []
    for symbol, name, country, region, is_future in _YF_INSTRUMENTS:
        try:
            fi = yf.Ticker(symbol).fast_info
            last = _num(fi.get("lastPrice"))
            prev_close = _num(fi.get("previousClose"))
            if last is None or prev_close is None:
                logger.warning("Yahoo Finance fast_info missing price for %s", symbol)
                continue
            change = last - prev_close
            change_pct = (change / prev_close * 100.0) if prev_close else None
            out.append({
                "name": name,
                "symbol": symbol,
                "country": country,
                "region": region,
                "is_future": is_future,
                "last": round(last, 4),
                "high": round(_num(fi.get("dayHigh")) or last, 4),
                "low": round(_num(fi.get("dayLow")) or last, 4),
                "change": round(change, 4),
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "time": None,
                "is_open": None,
            })
        except Exception as exc:
            logger.warning("Yahoo Finance fetch failed for %s: %s", symbol, exc)
            continue
    return out


def _parse_return_text(text: str | None) -> dict[str, float | None]:
    """Parse a '-92.5 (-0.38%)' style string into {'abs': ..., 'pct': ...}."""
    if not text:
        return {"abs": None, "pct": None}
    m = re.match(r"\s*([\-\d.,]+)\s*\(([\-\d.]+)%\)\s*", text)
    if not m:
        return {"abs": None, "pct": None}
    return {"abs": _clean_num(m.group(1)), "pct": _clean_num(m.group(2))}


def fetch_gift_nifty() -> dict[str, Any] | None:
    """GIFT Nifty (formerly SGX Nifty) live snapshot scraped from 5paisa's
    server-rendered stock page — LTP, change, day/52-week range, open, prev
    close, and 1W/1M/1Y returns."""
    try:
        resp = requests.get(_GIFT_NIFTY_URL, headers=_HEADERS, timeout=25)
        if resp.status_code != 200:
            logger.warning("5paisa GIFT Nifty page -> HTTP %s", resp.status_code)
            return None
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as exc:
        logger.warning("5paisa GIFT Nifty fetch failed: %s", exc)
        return None

    prc = soup.select_one(".market--prc")
    if not prc:
        return None

    big = prc.select_one(".prc-bigtext")
    small = prc.select_one(".prc-smalltext")
    ltp = _clean_num((big.get_text(strip=True) if big else "") + (small.get_text(strip=True) if small else ""))

    change = change_pct = None
    pct_label = prc.select_one(".prc--percentage")
    if pct_label:
        spans = [s.get_text(strip=True) for s in pct_label.find_all("span")]
        if len(spans) >= 3:
            sign = -1 if spans[0].strip() == "-" else 1
            change = sign * (_clean_num(spans[1]) or 0.0)
            change_pct = sign * (_clean_num(spans[2]) or 0.0)

    date_el = prc.select_one(".market--prc--date")
    as_of = re.sub(r"^As on\s*", "", date_el.get_text(" ", strip=True)) if date_el else None

    def _range_num(container, css_class: str) -> float | None:
        el = container.select_one(css_class)
        return _clean_num(el.get_text(strip=True)) if el else None

    day_low = day_high = week52_low = week52_high = None
    ranges = soup.select(".stock-page__range")
    if len(ranges) >= 1:
        day_low = _range_num(ranges[0], ".day_low")
        day_high = _range_num(ranges[0], ".day_high")
    if len(ranges) >= 2:
        week52_low = _range_num(ranges[1], ".day_low")
        week52_high = _range_num(ranges[1], ".day_high")

    open_price = prev_close = None
    return_1w = return_1m = return_1y = {"abs": None, "pct": None}
    vol_block = soup.select_one(".stock-page__valume")
    if vol_block:
        lis = vol_block.select("li")
        # Fixed order on the page: Open Price, Previous Close, 1W, 1M, 1Y Returns.
        if len(lis) >= 1:
            open_price = _clean_num(lis[0].get_text(strip=True).replace("Open Price", ""))
        if len(lis) >= 2:
            prev_close = _clean_num(lis[1].get_text(strip=True).replace("Previous Close", ""))
        if len(lis) >= 3:
            return_1w = _parse_return_text(lis[2].get_text(strip=True).replace("1W Returns", ""))
        if len(lis) >= 4:
            return_1m = _parse_return_text(lis[3].get_text(strip=True).replace("1M Returns", ""))
        if len(lis) >= 5:
            return_1y = _parse_return_text(lis[4].get_text(strip=True).replace("1Y Returns", ""))

    return {
        "name": "Gift Nifty",
        "ltp": ltp,
        "change": change,
        "change_pct": change_pct,
        "as_of": as_of,
        "day_low": day_low,
        "day_high": day_high,
        "week52_low": week52_low,
        "week52_high": week52_high,
        "open": open_price,
        "prev_close": prev_close,
        "return_1w": return_1w,
        "return_1m": return_1m,
        "return_1y": return_1y,
    }
