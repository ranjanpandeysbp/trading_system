"""
Groww OHLCV client — ported from truebacktesting/heatmap.py.

Uses authenticated REST API when bearer token is set; falls back to the
public Groww charting service (no token required).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

GROWW_BASE = "https://api.groww.in"

# tf_key -> (interval_minutes, max_calendar_days)
TF_INDIA: dict[str, tuple[int, int]] = {
    "1m": (1, 7),
    "3m": (3, 15),
    "5m": (5, 15),
    "10m": (10, 30),
    "15m": (15, 60),
    "30m": (30, 90),
    "1h": (60, 150),
    "4h": (240, 300),
    "1d": (1440, 1080),
    "1w": (10080, 3650),
}

# App interval strings -> Groww tf_key
INTERVAL_TO_TF: dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1wk": "1w",
    "1w": "1w",
}


def interval_to_tf_key(interval: str) -> str:
    return INTERVAL_TO_TF.get(interval, interval)


def _period_to_limit(period: str | None, interval: str, default: int = 300) -> int:
    if not period:
        return default
    p = period.strip().lower()
    if p.endswith("d"):
        try:
            days = int(p[:-1])
            if interval in ("1m", "3m"):
                return min(2000, days * 375)
            if interval in ("5m", "15m"):
                return min(1500, days * 75)
            return min(1000, days + 10)
        except ValueError:
            pass
    if p.endswith("y"):
        try:
            return int(float(p[:-1]) * 252)
        except ValueError:
            pass
    return default


def parse_groww_candles(candles: list) -> pd.DataFrame:
    """Parse Groww candle arrays into OHLCV DataFrame."""
    rows = []
    for c in candles:
        try:
            ts = c[0]
            if isinstance(ts, str):
                ts = int(datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp())
            rows.append({
                "time": int(ts),
                "open": float(c[1]) if len(c) > 1 else 0.0,
                "high": float(c[2]) if len(c) > 2 else 0.0,
                "low": float(c[3]) if len(c) > 3 else 0.0,
                "close": float(c[4]) if len(c) > 4 else 0.0,
                "volume": float(c[5]) if len(c) > 5 else 0.0,
            })
        except (TypeError, ValueError, IndexError):
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("datetime").drop(columns=["time"])
    return df[["open", "high", "low", "close", "volume"]]


def fetch_groww_ohlcv(
    symbol: str,
    exchange: str,
    tf_key: str,
    api_token: str = "",
    limit: int = 300,
) -> pd.DataFrame:
    """
    Fetch OHLCV from Groww authenticated API or public charting service.
    Mirrors truebacktesting/heatmap.fetch_groww_ohlcv.
    """
    if tf_key not in TF_INDIA:
        logger.error("Invalid Groww timeframe '%s'", tf_key)
        return pd.DataFrame()

    minutes, max_days = TF_INDIA[tf_key]
    now = datetime.now()

    trading_days_needed = max(1, (minutes * limit) // 375 + 1)
    calendar_days_needed = trading_days_needed + (trading_days_needed // 5) * 2 + 5
    if tf_key != "1d":
        calendar_days_needed = max(7, calendar_days_needed)

    lookback_min = min(calendar_days_needed * 24 * 60, max_days * 24 * 60)
    start_dt = now - timedelta(minutes=lookback_min)

    token = (api_token or "").strip()
    sym = symbol.upper()
    exch = exchange.upper()

    # 1) Authenticated historical candles API
    if token:
        start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_str = now.strftime("%Y-%m-%d %H:%M:%S")
        groww_symbol = f"{exch}-{sym}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "X-API-VERSION": "1.0",
        }
        params = {
            "exchange": exch,
            "segment": "CASH",
            "groww_symbol": groww_symbol,
            "start_time": start_str,
            "end_time": end_str,
            "candle_interval": f"{minutes}minute",
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(f"{GROWW_BASE}/v1/historical/candles", headers=headers, params=params)
            if r.status_code == 200:
                candles = r.json().get("payload", {}).get("candles", [])
                if candles:
                    df = parse_groww_candles(candles)
                    if not df.empty:
                        return df.tail(limit)
            else:
                logger.debug("Groww historical API %s for %s: %s", r.status_code, sym, r.text[:200])
        except Exception as exc:
            logger.debug("Groww authenticated fetch failed for %s: %s", sym, exc)

    # 2) Public charting service (works without token)
    try:
        url = f"https://groww.in/v1/api/charting_service/v2/chart/exchange/{exch}/segment/CASH/{sym}"
        params = {
            "endTimeInMillis": int(now.timestamp() * 1000),
            "intervalInMinutes": minutes,
            "startTimeInMillis": int(start_dt.timestamp() * 1000),
        }
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, headers={"User-Agent": "Mozilla/5.0"}, params=params)
        if r.status_code == 200:
            candles = r.json().get("candles", [])
            if candles:
                df = parse_groww_candles(candles)
                if not df.empty:
                    return df.tail(limit)
    except Exception as exc:
        logger.debug("Groww charting service failed for %s: %s", sym, exc)

    return pd.DataFrame()


def fetch_groww_quote(symbol: str, exchange: str, api_token: str) -> dict | None:
    """Live quote via Groww API (requires bearer token)."""
    token = (api_token or "").strip()
    if not token:
        return None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-API-VERSION": "1.0",
    }
    params = {
        "exchange": exchange.upper(),
        "segment": "CASH",
        "trading_symbol": symbol.upper(),
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{GROWW_BASE}/v1/live-data/quote", headers=headers, params=params)
        if r.status_code == 200:
            body = r.json()
            if body.get("status") == "SUCCESS":
                return body.get("payload", {})
    except Exception as exc:
        logger.debug("Groww quote failed for %s: %s", symbol, exc)
    return None


GROWW_WEB_API = "https://groww.in/v1/api/stocks_data/v1"
_GROWW_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def fetch_groww_live_quote(
    symbol: str,
    exchange: str = "NSE",
    *,
    prefer_index: bool = False,
) -> dict[str, float] | None:
    """Current market quote from Groww public live feed — price, day high/low,
    plus (best-effort, when the feed populates them) open, previous close,
    volume, order-book buy/sell quantity, and the day's exchange circuit
    band."""
    sym = symbol.upper()
    exch = exchange.upper()
    endpoints: list[tuple[str, str]] = []
    if prefer_index:
        endpoints.append((f"{GROWW_WEB_API}/tr_live_indices/exchange/{exch}/segment/CASH/{sym}/latest", "value"))
        endpoints.append((f"{GROWW_WEB_API}/tr_live_prices/exchange/{exch}/segment/CASH/{sym}/latest", "ltp"))
    else:
        endpoints.append((f"{GROWW_WEB_API}/tr_live_prices/exchange/{exch}/segment/CASH/{sym}/latest", "ltp"))
        endpoints.append((f"{GROWW_WEB_API}/tr_live_indices/exchange/{exch}/segment/CASH/{sym}/latest", "value"))

    for url, price_key in endpoints:
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                r = client.get(url, headers=_GROWW_UA)
            if r.status_code != 200:
                continue
            body = r.json()
            price = None
            for field in (price_key, "ltp", "value"):
                val = body.get(field)
                if val is not None and float(val) > 0:
                    price = float(val)
                    break
            if price is None:
                continue
            quote: dict[str, float] = {"price": price}
            high = body.get("high")
            low = body.get("low")
            if high is not None and float(high) > 0:
                quote["day_high"] = float(high)
            if low is not None and float(low) > 0:
                quote["day_low"] = float(low)
            open_ = body.get("open")
            if open_ is not None and float(open_) > 0:
                quote["open"] = float(open_)
            prev_close = body.get("close")
            if prev_close is not None and float(prev_close) > 0:
                quote["prev_close"] = float(prev_close)
            volume = body.get("volume")
            if volume is not None and float(volume) > 0:
                quote["volume"] = float(volume)
            buy_qty = body.get("totalBuyQty")
            sell_qty = body.get("totalSellQty")
            if buy_qty is not None and sell_qty is not None and (float(buy_qty) + float(sell_qty)) > 0:
                quote["buy_qty"] = float(buy_qty)
                quote["sell_qty"] = float(sell_qty)
            circuit_high = body.get("highPriceRange")
            circuit_low = body.get("lowPriceRange")
            if circuit_high is not None and circuit_low is not None and float(circuit_high) > float(circuit_low) > 0:
                quote["circuit_high"] = float(circuit_high)
                quote["circuit_low"] = float(circuit_low)
            return quote
        except Exception as exc:
            logger.debug("Groww live quote failed %s (%s): %s", sym, url, exc)
    return None


def fetch_groww_live_market_price(
    symbol: str,
    exchange: str = "NSE",
    *,
    prefer_index: bool = False,
) -> float | None:
    """Current market price from Groww public live feed (no token required)."""
    quote = fetch_groww_live_quote(symbol, exchange, prefer_index=prefer_index)
    return quote["price"] if quote else None
