"""
dhan_indices_engine.py
-----------------------
NSE indices and World/global indices via Dhan.co's server-rendered
__NEXT_DATA__ JSON — same technique as dhan_stock_engine.py.

NSE:    https://dhan.co/all-nse-indices/
Global: https://dhan.co/indices/global-indices/
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)

_NSE_INDICES_URL = "https://dhan.co/all-nse-indices/"
_GLOBAL_INDICES_URL = "https://dhan.co/indices/global-indices/"


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_next_data(url: str) -> dict[str, Any] | None:
    try:
        resp = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            logger.warning("Dhan indices page %s -> HTTP %s", url, resp.status_code)
            return None
        m = _NEXT_DATA_RE.search(resp.text or "")
        if not m:
            return None
        import json
        return json.loads(m.group(1))
    except Exception as exc:
        logger.warning("Dhan indices fetch failed (%s): %s", url, exc)
        return None


def fetch_nse_indices() -> list[dict[str, Any]]:
    """All NSE indices — name, LTP, change %, open, prev close, 52W hi/lo, 1/3/5Y returns."""
    data = _fetch_next_data(_NSE_INDICES_URL)
    if not data:
        return []
    rows = (data.get("props", {}).get("pageProps", {}) or {}).get("listData") or []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("DispSym") or row.get("Sym")
        if not name:
            continue
        ltp = _num(row.get("Ltp"))
        change_abs = _num(row.get("Pchange"))
        change_pct = _num(row.get("PPerchange"))
        # `Close` on this page mirrors Ltp rather than true previous close —
        # derive prev close arithmetically from Ltp - absolute change instead.
        prev_close = (ltp - change_abs) if ltp is not None and change_abs is not None else None
        out.append({
            "name": name,
            "symbol": row.get("Sym"),
            "ltp": ltp,
            "change_pct": change_pct,
            "open": _num(row.get("Open")),
            "prev_close": prev_close,
            "high_52w": _num(row.get("High1Yr")),
            "low_52w": _num(row.get("Low1Yr")),
            "return_1y_pct": _num(row.get("PricePerchng1year")),
            "return_3y_pct": _num(row.get("PricePerchng3year")),
            "return_5y_pct": _num(row.get("PricePerchng5year")),
        })
    return out


def fetch_global_indices() -> list[dict[str, Any]]:
    """World/global indices — name, LTP, change, change %, open, prev close, day hi/lo."""
    data = _fetch_next_data(_GLOBAL_INDICES_URL)
    if not data:
        return []
    rows = (data.get("props", {}).get("pageProps", {}) or {}).get("resdata") or []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("custom_symbol")
        if not name:
            continue
        out.append({
            "name": name,
            "symbol": row.get("custom_symbol") or row.get("symbol"),
            # `ltp` on this page is always 0 — `price` carries the real last traded value.
            "ltp": _num(row.get("price")),
            "change": _num(row.get("change")),
            "change_pct": _num(row.get("changeper")),
            "open": _num(row.get("open")),
            "prev_close": _num(row.get("prevClose")),
            "day_high": _num(row.get("dayHigh")),
            "day_low": _num(row.get("dayLow")),
            "country": row.get("country"),
            "continent": row.get("continent"),
        })
    return out
