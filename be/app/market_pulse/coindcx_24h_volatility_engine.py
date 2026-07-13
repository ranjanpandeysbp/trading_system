"""
coindcx_24h_volatility_engine.py
---------------------------------
CoinDCX derivatives 24h change/high/low/vol for every USDT-margined pair,
sourced from a single call to the instrument endpoint (its `change_24_hour`
payload covers all listed pairs, not just the one queried).

API: https://api.coindcx.com/api/v1/derivatives/futures/data/instrument
     ?pair=B-BTC_USDT&margin_currency_short_name=USDT
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_URL = "https://api.coindcx.com/api/v1/derivatives/futures/data/instrument"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pair_to_display(pair: str) -> str:
    base = (pair or "").replace("B-", "").replace("_USDT", "")
    return f"{base}-USDT"


def fetch_change_24h() -> list[dict[str, Any]]:
    """All CoinDCX USDT-margined pairs' 24h % change, high, low, volume.

    Sorted most-positive-change first, most-negative last.
    """
    try:
        resp = requests.get(
            _URL,
            params={"pair": "B-BTC_USDT", "margin_currency_short_name": "USDT"},
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            logger.warning("CoinDCX change_24_hour HTTP %s", resp.status_code)
            return []
        data = resp.json()
        change_map = data.get("change_24_hour") or {}
    except Exception as exc:
        logger.warning("CoinDCX change_24_hour fetch failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for pair, item in change_map.items():
        if not pair or not isinstance(item, dict):
            continue
        out.append({
            "pair": pair,
            "ticker": _pair_to_display(pair),
            "percent_change": _to_float(item.get("percent_change")),
            "high": _to_float(item.get("high")),
            "low": _to_float(item.get("low")),
            "vol": _to_float(item.get("vol")),
        })
    out.sort(key=lambda r: (r["percent_change"] if r["percent_change"] is not None else -1e18), reverse=True)
    return out


def ranked_display_tickers(limit: int | None = None) -> list[str]:
    """CoinDCX 'XXX-USDT' display tickers ranked by 24h % change, most +ve first."""
    rows = fetch_change_24h()
    out = [r["ticker"] for r in rows if r.get("percent_change") is not None]
    return out if limit is None else out[:limit]
