"""
live_price.py
----------------
Best-effort Last Traded Price (LTP) lookup for any ticker or index, reusing
the app's existing live-quote infrastructure (`backtesting.data_fetcher.get_live_quote`
already covers India/US/Crypto priority-ordered live sources with a candle-close
fallback) plus a Yahoo Finance index-quote path for named indices like
"Nifty 50" / "Bank Nifty" / "Sensex" that aren't tradeable tickers themselves.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_last_traded_price(
    ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Best-effort LTP for a tradeable ticker. Returns {"price", "change_pct", "is_live",
    "day_high", "day_low", "day_bias"} where day_bias is a multi-factor
    (range position, candle direction, change vs prev close, order-flow,
    circuit proximity, volume conviction) read of the chance of the next move
    being toward today's high vs today's low — see app.market_pulse.day_bias."""
    from app.market_pulse.day_bias import quote_bias
    from backtesting.data_fetcher import get_live_quote

    try:
        quote = get_live_quote(ticker, market, exchange=exchange, groww_token=groww_token) or {}
    except Exception as exc:
        logger.debug("LTP lookup failed for %s (%s): %s", ticker, market, exc)
        quote = {}
    price = quote.get("ltp")
    if price:
        bias = quote_bias(
            float(price), quote.get("day_high"), quote.get("day_low"),
            open_price=quote.get("open"), prev_close=quote.get("prev_close"),
            volume=quote.get("volume"), avg_volume=quote.get("avg_volume"),
            buy_qty=quote.get("buy_qty"), sell_qty=quote.get("sell_qty"),
            circuit_high=quote.get("circuit_high"), circuit_low=quote.get("circuit_low"),
        )
        return {
            "price": float(price), "change_pct": quote.get("change_pct"), "is_live": True,
            "day_high": quote.get("day_high"), "day_low": quote.get("day_low"), "day_bias": bias,
        }
    return {
        "price": None, "change_pct": None, "is_live": False,
        "day_high": None, "day_low": None, "day_bias": None,
    }


def get_index_last_traded_price(
    index_name: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """LTP for an NSE/BSE index by display name (e.g. 'Nifty 50', 'Bank Nifty',
    'Sensex') — tries Groww's public live-index feed first (works even
    without a token), then a Groww authenticated quote, then a Yahoo Finance
    index ticker (^NSEI / ^NSEBANK / ^BSESN) as the last resort."""
    from app.data.groww_client import fetch_groww_live_quote, fetch_groww_quote
    from app.data.nse_symbols import resolve_groww_symbol_candidates
    from app.market_pulse.nse_index_yfinance import market_display_to_yf

    for sym in resolve_groww_symbol_candidates(index_name):
        try:
            live = fetch_groww_live_quote(sym, exchange, prefer_index=True)
        except Exception as exc:
            logger.debug("Groww index LTP fetch failed for %s (%s): %s", index_name, sym, exc)
            live = None
        if live and live.get("price", 0) > 0:
            return {"price": float(live["price"]), "change_pct": None, "is_live": True}

    token = (groww_token or "").strip()
    if token:
        for sym in resolve_groww_symbol_candidates(index_name):
            try:
                quote = fetch_groww_quote(sym, exchange, token)
            except Exception as exc:
                logger.debug("Groww auth index LTP fetch failed for %s (%s): %s", index_name, sym, exc)
                quote = None
            if quote:
                for key in ("last_price", "ltp", "lastPrice", "close"):
                    val = quote.get(key)
                    if val and float(val) > 0:
                        return {"price": float(val), "change_pct": None, "is_live": True}

    yf_sym = market_display_to_yf(index_name)
    if not yf_sym:
        return {"price": None, "change_pct": None, "is_live": False}
    try:
        import yfinance as yf
        fast = yf.Ticker(yf_sym).fast_info
        try:
            price = fast["lastPrice"]
        except Exception:
            price = getattr(fast, "last_price", None)
        if price:
            return {"price": float(price), "change_pct": None, "is_live": True}
    except Exception as exc:
        logger.debug("Index LTP fetch failed for %s (%s): %s", index_name, yf_sym, exc)
    return {"price": None, "change_pct": None, "is_live": False}
