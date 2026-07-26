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


async def fetch_marquee_quotes() -> dict[str, Any]:
    yf_items = [i for i in MARQUEE_UNIVERSE if i.get("source") != "giftnifty"]
    gift_item = next((i for i in MARQUEE_UNIVERSE if i.get("source") == "giftnifty"), None)
    symbols = [i["symbol"] for i in yf_items]

    yf_map_task = asyncio.to_thread(_yf_batch_ltp, symbols)
    gift_task = asyncio.to_thread(_gift_nifty_ltp) if gift_item else None
    if gift_task:
        yf_map, gift_q = await asyncio.gather(yf_map_task, gift_task)
    else:
        yf_map = await yf_map_task
        gift_q = {"price": None, "change_pct": None, "is_live": False}

    rows: list[dict[str, Any]] = []
    for item in MARQUEE_UNIVERSE:
        if item.get("source") == "giftnifty":
            q = gift_q
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
