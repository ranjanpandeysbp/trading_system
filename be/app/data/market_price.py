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


def _coindcx_quote_sync(ticker: str) -> MarketQuote | None:
    """Live CoinDCX USDT futures quote (last / day high / day low)."""
    try:
        from app.market_pulse.heatmap import _coindcx_sym_key, fetch_coindcx_futures_snapshot

        def _base(sym: str) -> str:
            return _coindcx_sym_key(sym).replace("USDT", "").lstrip("B")

        snap = fetch_coindcx_futures_snapshot()
        if not snap:
            return None
        want = _base(ticker)
        if not want:
            return None
        for row in snap:
            if _base(str(row.get("sym") or "")) != want:
                continue
            price = float(row.get("price") or 0)
            if price <= 0:
                continue
            hi = row.get("high")
            lo = row.get("low")
            return MarketQuote(
                price=price,
                day_high=float(hi) if hi not in (None, 0, 0.0) else None,
                day_low=float(lo) if lo not in (None, 0, 0.0) else None,
            )
    except Exception as exc:
        logger.debug("CoinDCX quote failed for %s: %s", ticker, exc)
    return None


def _yf_symbol_for_quote(ticker: str, *, asset_class: str = "india", market: str = "") -> str:
    """Map ticker to a Yahoo symbol appropriate for the asset class."""
    raw = (ticker or "").strip()
    ac = (asset_class or "india").lower()
    if ac == "crypto" or "coindcx" in (market or "").lower() or "crypto" in (market or "").lower():
        sym = raw.upper().replace("B-", "").replace("_USDT", "").replace("-USDT", "").replace("USDT", "")
        return f"{sym}-USD"
    if ac in ("us", "commodity") or "=F" in raw.upper() or raw.startswith("^"):
        from app.market_pulse.us_market_yfinance import us_symbol_to_yf
        return us_symbol_to_yf(raw)
    return normalize_ticker(raw)


async def fetch_market_quote(
    ticker: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    asset_class: str = "india",
    market: str = "",
) -> MarketQuote:
    """
    Fetch current market price and day high/low.

    India: IndMoney (if selected) → Groww (if selected) → yfinance (.NS).
    Crypto: CoinDCX USDT futures snapshot → yfinance fallback.
    US / commodity: yfinance (IndMoney API is India-focused).
    """
    ac = (asset_class or "india").lower()
    token = (groww_token or "").strip()

    if ac == "crypto" or "coindcx" in (market or "").lower() or "crypto" in (market or "").lower():
        q = await asyncio.to_thread(_coindcx_quote_sync, ticker)
        if q:
            return q
        symbol = _yf_symbol_for_quote(ticker, asset_class="crypto", market=market)
        yf_quote = await asyncio.to_thread(_yfinance_quote_sync, symbol)
        if yf_quote:
            return yf_quote
        raise ValueError(f"Could not fetch CoinDCX futures price for {ticker}")

    if ac == "india":
        from app.data.provider_ctx import get_active_data_provider, get_active_indmoney_token

        provider = get_active_data_provider()
        if provider == "indmoney":
            im = get_active_indmoney_token()
            if im:
                from app.data.indmoney_client import fetch_indmoney_quote

                q = await asyncio.to_thread(fetch_indmoney_quote, ticker, im, exchange=exchange)
                if q and q.get("ltp"):
                    return MarketQuote(
                        price=float(q["ltp"]),
                        day_high=q.get("day_high"),
                        day_low=q.get("day_low"),
                    )

        if provider == "groww":
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

    symbol = _yf_symbol_for_quote(ticker, asset_class=ac, market=market)
    yf_quote = await asyncio.to_thread(_yfinance_quote_sync, symbol)
    if yf_quote:
        return yf_quote

    raise ValueError(f"Could not fetch current market price for {ticker}")


async def fetch_market_price(
    ticker: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    asset_class: str = "india",
    market: str = "",
) -> float:
    quote = await fetch_market_quote(
        ticker,
        groww_token=groww_token,
        exchange=exchange,
        asset_class=asset_class,
        market=market,
    )
    return quote.price
