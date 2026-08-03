"""Popular index / asset LTP quotes for the app header marquee."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# India · US · Crypto · Commodities · Futures (Gift Nifty via 5paisa scrape)
MARQUEE_UNIVERSE: list[dict[str, str]] = [
    {"id": "nifty50", "label": "Nifty 50", "symbol": "^NSEI", "market": "india"},
    {"id": "banknifty", "label": "Bank Nifty", "symbol": "^NSEBANK", "market": "india"},
    {"id": "giftnifty", "label": "Gift Nifty", "symbol": "GIFTNIFTY", "market": "india", "source": "giftnifty"},
    {"id": "dow", "label": "Dow Jones", "symbol": "^DJI", "market": "us"},
    {"id": "dow_fut", "label": "Dow Futures", "symbol": "YM=F", "market": "us"},
    {"id": "es_fut", "label": "S&P Futures", "symbol": "ES=F", "market": "us"},
    {"id": "nq_fut", "label": "Nasdaq Futures", "symbol": "NQ=F", "market": "us"},
    {"id": "oil_fut", "label": "Oil Futures", "symbol": "CL=F", "market": "commodity"},
    {"id": "gold", "label": "Gold", "symbol": "GC=F", "market": "commodity"},
    {"id": "btc", "label": "Bitcoin", "symbol": "BTC-USD", "market": "crypto"},
]


def _yf_batch_ltp(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fast batch LTP via yfinance download (avoids slow per-ticker .info)."""
    import yfinance as yf

    out: dict[str, dict[str, Any]] = {s: {"price": None, "change_pct": None, "is_live": False} for s in symbols}
    if not symbols:
        return out
    try:
        df = yf.download(
            symbols,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.debug("Marquee yf.download failed: %s", exc)
        return out

    if df is None or df.empty:
        return out

    # Single symbol → columns are Open/High/Low/Close; multi → MultiIndex
    multi = isinstance(df.columns, type(df.columns)) and getattr(df.columns, "nlevels", 1) > 1

    for sym in symbols:
        try:
            if multi and sym in df.columns.get_level_values(0):
                closes = df[sym]["Close"].dropna()
            elif not multi and "Close" in df.columns:
                closes = df["Close"].dropna()
            else:
                continue
            if closes.empty:
                continue
            price = float(closes.iloc[-1])
            change_pct = None
            if len(closes) >= 2 and float(closes.iloc[-2]):
                prev = float(closes.iloc[-2])
                change_pct = round((price / prev - 1.0) * 100.0, 2)
            out[sym] = {"price": price, "change_pct": change_pct, "is_live": True}
        except Exception as exc:
            logger.debug("Marquee parse failed for %s: %s", sym, exc)
    return out


def _groww_india_ltp(symbol: str, groww_token: str) -> dict[str, Any] | None:
    """India index LTP from Groww's public live feed (no token needed) with
    an authenticated Groww quote as a second attempt — tried before yfinance."""
    from app.data.groww_client import fetch_groww_live_quote, fetch_groww_quote
    from app.data.nse_symbols import resolve_groww_symbol_candidates

    for sym in resolve_groww_symbol_candidates(symbol):
        try:
            live = fetch_groww_live_quote(sym, "NSE", prefer_index=True)
        except Exception as exc:
            logger.debug("Marquee Groww live quote failed for %s (%s): %s", symbol, sym, exc)
            live = None
        if live and live.get("price", 0) > 0:
            price = float(live["price"])
            prev_close = live.get("prev_close")
            change_pct = round((price / float(prev_close) - 1.0) * 100.0, 2) if prev_close else None
            return {"price": price, "change_pct": change_pct, "is_live": True}

    token = (groww_token or "").strip()
    if token:
        for sym in resolve_groww_symbol_candidates(symbol):
            try:
                quote = fetch_groww_quote(sym, "NSE", token)
            except Exception as exc:
                logger.debug("Marquee Groww auth quote failed for %s (%s): %s", symbol, sym, exc)
                quote = None
            if quote:
                price = None
                for key in ("last_price", "ltp", "lastPrice", "close"):
                    val = quote.get(key)
                    if val and float(val) > 0:
                        price = float(val)
                        break
                if price is not None:
                    return {"price": price, "change_pct": None, "is_live": True}
    return None


def _gift_nifty_ltp() -> dict[str, Any]:
    try:
        from app.market_pulse.futures_indices_engine import fetch_gift_nifty

        data = fetch_gift_nifty() or {}
        price = data.get("ltp")
        ch = data.get("change_pct")
        return {
            "price": float(price) if price else None,
            "change_pct": round(float(ch), 2) if ch is not None else None,
            "is_live": bool(price),
        }
    except Exception as exc:
        logger.debug("Marquee Gift Nifty failed: %s", exc)
        return {"price": None, "change_pct": None, "is_live": False}


async def fetch_marquee_quotes(groww_token: str = "") -> dict[str, Any]:
    yf_items = [i for i in MARQUEE_UNIVERSE if i.get("source") != "giftnifty" and i["market"] != "india"]
    india_items = [i for i in MARQUEE_UNIVERSE if i.get("source") != "giftnifty" and i["market"] == "india"]
    gift_item = next((i for i in MARQUEE_UNIVERSE if i.get("source") == "giftnifty"), None)
    symbols = [i["symbol"] for i in yf_items]

    yf_map_task = asyncio.to_thread(_yf_batch_ltp, symbols)
    gift_task = asyncio.to_thread(_gift_nifty_ltp) if gift_item else None
    india_tasks = [asyncio.to_thread(_groww_india_ltp, i["symbol"], groww_token) for i in india_items]

    gathered = await asyncio.gather(yf_map_task, *([gift_task] if gift_task else []), *india_tasks)
    yf_map = gathered[0]
    idx = 1
    if gift_task:
        gift_q = gathered[idx]
        idx += 1
    else:
        gift_q = {"price": None, "change_pct": None, "is_live": False}
    india_results = gathered[idx:]

    # For any India symbol Groww couldn't answer, fall back to yfinance.
    india_map: dict[str, dict[str, Any]] = {}
    fallback_symbols: list[str] = []
    for item, result in zip(india_items, india_results):
        if result:
            india_map[item["symbol"]] = result
        else:
            fallback_symbols.append(item["symbol"])
    if fallback_symbols:
        india_map.update(await asyncio.to_thread(_yf_batch_ltp, fallback_symbols))

    rows: list[dict[str, Any]] = []
    for item in MARQUEE_UNIVERSE:
        if item.get("source") == "giftnifty":
            q = gift_q
        elif item["market"] == "india":
            q = india_map.get(item["symbol"]) or {"price": None, "change_pct": None, "is_live": False}
        else:
            q = yf_map.get(item["symbol"]) or {"price": None, "change_pct": None, "is_live": False}
        rows.append({
            "id": item["id"],
            "label": item["label"],
            "symbol": item["symbol"],
            "market": item["market"],
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "is_live": bool(q.get("is_live")),
        })
    return {"quotes": rows, "refresh_seconds": 20}
