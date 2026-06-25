"""Current market price and day range — Groww live feed, never scan candle closes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.data.groww_client import fetch_groww_live_quote, fetch_groww_quote
from app.data.nse_symbols import GROWW_INDEX_SYMBOL_TO_YF, resolve_groww_symbol_candidates
from app.data.yfinance_provider import normalize_ticker

logger = logging.getLogger(__name__)


@dataclass
class MarketQuote:
    price: float
    day_high: float | None = None
    day_low: float | None = None


def _is_index_ticker(ticker: str, groww_symbol: str) -> bool:
    raw = (ticker or "").strip()
    if raw.startswith("^"):
        return True
    return groww_symbol.upper() in GROWW_INDEX_SYMBOL_TO_YF


def _yfinance_quote_sync(symbol: str) -> MarketQuote | None:
    import yfinance as yf

    t = yf.Ticker(symbol)
    price = high = low = None

    try:
        info = t.info
        for key in ("regularMarketPrice", "currentPrice", "previousClose"):
            val = info.get(key)
            if val and float(val) > 0:
                price = float(val)
                break
        for key in ("dayHigh", "regularMarketDayHigh"):
            val = info.get(key)
            if val and float(val) > 0:
                high = float(val)
                break
        for key in ("dayLow", "regularMarketDayLow"):
            val = info.get(key)
            if val and float(val) > 0:
                low = float(val)
                break
    except Exception as exc:
        logger.debug("yfinance info failed for %s: %s", symbol, exc)

    if price is None:
        try:
            fi = t.fast_info
            for key in ("regularMarketPrice", "currentPrice", "lastPrice", "last_price"):
                val = None
                try:
                    val = fi[key]
                except (KeyError, TypeError):
                    val = getattr(fi, key, None)
                if val and float(val) > 0:
                    price = float(val)
                    break
            for key in ("dayHigh", "day_high"):
                try:
                    val = fi[key]
                except (KeyError, TypeError):
                    val = getattr(fi, key, None)
                if val and float(val) > 0:
                    high = float(val)
                    break
            for key in ("dayLow", "day_low"):
                try:
                    val = fi[key]
                except (KeyError, TypeError):
                    val = getattr(fi, key, None)
                if val and float(val) > 0:
                    low = float(val)
                    break
        except Exception as exc:
            logger.debug("yfinance fast_info failed for %s: %s", symbol, exc)

    if price is None or price <= 0:
        return None
    return MarketQuote(price=price, day_high=high, day_low=low)


def _groww_auth_quote_sync(symbol: str, exchange: str, token: str) -> MarketQuote | None:
    quote = fetch_groww_quote(symbol, exchange, token)
    if not quote:
        return None
    price = None
    for key in ("last_price", "ltp", "lastPrice", "close"):
        val = quote.get(key)
        if val and float(val) > 0:
            price = float(val)
            break
    if price is None:
        return None
    high = low = None
    for key in ("high", "day_high", "dayHigh"):
        val = quote.get(key)
        if val and float(val) > 0:
            high = float(val)
            break
    for key in ("low", "day_low", "dayLow"):
        val = quote.get(key)
        if val and float(val) > 0:
            low = float(val)
            break
    return MarketQuote(price=price, day_high=high, day_low=low)


async def fetch_market_quote(
    ticker: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> MarketQuote:
    """
    Fetch current market price and day high/low.

    Priority: Groww public live feed → Groww quote (token) → yfinance.
    """
    token = (groww_token or "").strip()
    candidates = resolve_groww_symbol_candidates(ticker)

    for sym in candidates:
        live = await asyncio.to_thread(
            fetch_groww_live_quote,
            sym,
            exchange,
            prefer_index=_is_index_ticker(ticker, sym),
        )
        if live and live.get("price", 0) > 0:
            return MarketQuote(
                price=float(live["price"]),
                day_high=live.get("day_high"),
                day_low=live.get("day_low"),
            )

    if token:
        for sym in candidates:
            quoted = await asyncio.to_thread(_groww_auth_quote_sync, sym, exchange, token)
            if quoted:
                return quoted

    symbol = normalize_ticker(ticker)
    yf_quote = await asyncio.to_thread(_yfinance_quote_sync, symbol)
    if yf_quote:
        return yf_quote

    raise ValueError(f"Could not fetch current market price for {ticker}")


async def fetch_market_price(
    ticker: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> float:
    quote = await fetch_market_quote(ticker, groww_token=groww_token, exchange=exchange)
    return quote.price
