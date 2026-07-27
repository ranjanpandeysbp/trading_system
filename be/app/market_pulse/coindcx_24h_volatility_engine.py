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

from app.market_pulse.heatmap import fetch_coindcx_futures_snapshot

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
    """All CoinDCX USDT-margined pairs' 24h % change, high, low, volume, plus
    a real `volatility_pct` (24h high-low range as % of price) — signed
    `percent_change` tells you direction, not how much a pair actually
    whipped around; a pair can end the day flat with a 20% high-low swing.
    This tab is named "24Hrs Volatile Crypto", so `volatility_pct` is what a
    volatility-seeking user (vol-selling, breakout, range plays) actually
    wants to rank by — kept as an added field rather than changing the
    default sort, since the existing gainers/losers view is its own
    legitimate use case.

    Sorted most-positive-change first, most-negative last (unchanged).
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

    try:
        rt_prices = {row["sym"]: row["price"] for row in fetch_coindcx_futures_snapshot()}
    except Exception as exc:
        logger.debug("CoinDCX realtime price snapshot failed: %s", exc)
        rt_prices = {}

    from app.market_pulse.day_bias import quote_bias

    out: list[dict[str, Any]] = []
    for pair, item in change_map.items():
        if not pair or not isinstance(item, dict):
            continue
        price = rt_prices.get(pair)
        pct_change = _to_float(item.get("percent_change"))
        high = _to_float(item.get("high"))
        low = _to_float(item.get("low"))
        vol = _to_float(item.get("vol"))
        prev_close = price / (1 + pct_change / 100) if price and pct_change is not None and pct_change != -100 else None
        volatility_pct = (high - low) / price * 100 if price and high is not None and low is not None else None
        out.append({
            "pair": pair,
            "ticker": _pair_to_display(pair),
            "price": price,
            "percent_change": pct_change,
            "high": high,
            "low": low,
            "vol": vol,
            "volatility_pct": round(volatility_pct, 2) if volatility_pct is not None else None,
            "day_bias": quote_bias(price, high, low, prev_close=prev_close, volume=vol),
        })
    out.sort(key=lambda r: (r["percent_change"] if r["percent_change"] is not None else -1e18), reverse=True)
    return out


def ranked_display_tickers(limit: int | None = None) -> list[str]:
    """CoinDCX 'XXX-USDT' display tickers ranked by 24h % change, most +ve first."""
    rows = fetch_change_24h()
    out = [r["ticker"] for r in rows if r.get("percent_change") is not None]
    return out if limit is None else out[:limit]
