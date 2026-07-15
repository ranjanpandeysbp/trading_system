"""
data_fetcher.py
----------------
Historical OHLCV and live-quote fetching for market_pulse, routed across
India (Groww), crypto (CoinDCX), and US equities (yfinance), with a
yfinance fallback chain when the primary source has nothing.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

from app.data.groww_client import fetch_groww_live_quote, fetch_groww_ohlcv, interval_to_tf_key
from app.market_pulse.heatmap import fetch_coindcx_futures_snapshot, fetch_coindcx_ohlcv
from app.market_pulse.index_ohlcv import download_yf_ticker_interval_ohlcv
from app.market_pulse.nse_index_yfinance import stock_symbol_to_yf
from app.market_pulse.ticker_utils import is_crypto_market, is_us_market
from app.market_pulse.us_market_yfinance import us_symbol_to_yf

logger = logging.getLogger(__name__)

# A curated list of liquid NSE large/mid-caps for "Popular NSE" pickers.
# Matches backtesting/data_fetcher.py's POPULAR_NSE_STOCKS in the original app.
POPULAR_NSE_STOCKS: list[str] = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "HINDUNILVR", "BAJFINANCE", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "ITC", "ASIANPAINT", "AXISBANK", "DMART",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "NESTLEIND", "WIPRO",
    "ONGC", "NTPC", "POWERGRID", "COALINDIA", "TECHM",
    "MARUTI", "TATAMOTORS", "M&M", "HCLTECH", "ADANIENT",
    "TATASTEEL", "JSWSTEEL", "HINDALCO", "CIPLA", "DRREDDY",
    "EICHERMOT", "BAJAJFINSV", "GRASIM", "BPCL", "SHREECEM",
]

_YF_INTERVAL = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "4h": "60m", "1d": "1d", "1w": "1wk", "1wk": "1wk",
}
_YF_PERIOD = {
    "1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "2mo",
    "1h": "2mo", "4h": "6mo", "1d": "1y", "1w": "5y", "1wk": "5y",
}
_BARS_PER_DAY = {
    "1m": 375, "5m": 75, "15m": 25, "30m": 13,
    "1h": 7, "4h": 2, "1d": 1, "1w": 1, "1wk": 1,
}


def _crypto_symbol_to_yf(symbol: str) -> str:
    base = (
        (symbol or "").upper()
        .replace("B-", "").replace("-USDT", "").replace("_USDT", "").replace("USDT", "")
        .replace("-", "").replace("_", "")
    )
    return f"{base}-USD" if base else ""


def _crypto_key(symbol: str) -> str:
    return (symbol or "").upper().replace("_", "").replace("-", "")


def _bars_for_range(start_date: str, end_date: str, timeframe: str) -> int:
    try:
        days = max(1, (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days + 1)
    except (ValueError, TypeError):
        days = 30
    bars = days * _BARS_PER_DAY.get(timeframe, 1)
    return max(30, min(bars + 20, 2000))


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    try:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        return df.resample("4h").agg(agg).dropna(subset=["open", "high", "low", "close"])
    except Exception:
        return df


def _historical_yfinance(yf_sym: str, timeframe: str) -> pd.DataFrame:
    if not yf_sym:
        return pd.DataFrame()
    interval = _YF_INTERVAL.get(timeframe, "1d")
    period = _YF_PERIOD.get(timeframe, "1y")
    df = download_yf_ticker_interval_ohlcv(yf_sym, interval=interval, period=period)
    if df is None or df.empty:
        return pd.DataFrame()
    if timeframe == "4h":
        df = _resample_4h(df)
    return df


def _historical_india(symbol: str, exchange: str, timeframe: str, groww_token: str, limit: int) -> pd.DataFrame:
    tf_key = interval_to_tf_key(timeframe)
    try:
        df = fetch_groww_ohlcv(symbol, exchange or "NSE", tf_key, api_token=groww_token, limit=limit)
    except Exception:
        logger.debug("Groww OHLCV fetch failed for %s", symbol, exc_info=True)
        df = pd.DataFrame()
    if df is not None and not df.empty:
        return df
    return _historical_yfinance(stock_symbol_to_yf(symbol), timeframe)


def _historical_crypto(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    try:
        raw = fetch_coindcx_ohlcv(symbol, timeframe, limit=limit)
    except Exception:
        logger.debug("CoinDCX OHLCV fetch failed for %s", symbol, exc_info=True)
        raw = pd.DataFrame()
    if raw is None or raw.empty:
        return _historical_yfinance(_crypto_symbol_to_yf(symbol), timeframe)
    df = raw.copy()
    df["datetime"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("datetime").drop(columns=["time"])
    return df[["open", "high", "low", "close", "volume"]]


def get_historical_data(
    symbol: str,
    start_date: str,
    end_date: str,
    market: str = "",
    timeframe: str = "1d",
    groww_token: str = "",
    groww_exchange: str = "NSE",
) -> pd.DataFrame:
    """Fetch OHLCV for symbol/market/timeframe, trimmed to [start_date, end_date]."""
    if not symbol:
        return pd.DataFrame()

    limit = _bars_for_range(start_date, end_date, timeframe)
    try:
        if is_crypto_market(market):
            df = _historical_crypto(symbol, timeframe, limit)
        elif is_us_market(market):
            df = _historical_yfinance(us_symbol_to_yf(symbol), timeframe)
        else:
            df = _historical_india(symbol, groww_exchange, timeframe, groww_token, limit)
    except Exception:
        logger.debug("get_historical_data failed for %s (%s)", symbol, market, exc_info=True)
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    try:
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date) + timedelta(days=1)
        df = df[(df.index >= start_ts) & (df.index <= end_ts)]
    except (ValueError, TypeError):
        pass

    return df


def _live_quote_yfinance(yf_sym: str) -> dict:
    if not yf_sym:
        return {}
    try:
        import yfinance as yf

        ticker = yf.Ticker(yf_sym)
        fast = ticker.fast_info
        price = None
        prev_close = None
        try:
            price = fast["lastPrice"]
        except Exception:
            price = getattr(fast, "last_price", None)
        try:
            prev_close = fast["previousClose"]
        except Exception:
            prev_close = getattr(fast, "previous_close", None)

        if not price:
            hist = ticker.history(period="5d", interval="1d", auto_adjust=True)
            if hist is None or hist.empty:
                return {}
            price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else None

        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else None
        return {"ltp": float(price), "change_pct": change_pct}
    except Exception:
        logger.debug("yfinance live quote failed for %s", yf_sym, exc_info=True)
        return {}


def _live_quote_india(symbol: str, exchange: str) -> dict:
    quote = fetch_groww_live_quote(symbol, exchange)
    if quote and quote.get("price"):
        ltp = float(quote["price"])
        change_pct = None
        try:
            import yfinance as yf

            fast = yf.Ticker(stock_symbol_to_yf(symbol)).fast_info
            try:
                prev_close = fast["previousClose"]
            except Exception:
                prev_close = getattr(fast, "previous_close", None)
            if prev_close:
                change_pct = (ltp - float(prev_close)) / float(prev_close) * 100
        except Exception:
            logger.debug("prevClose lookup failed for %s", symbol, exc_info=True)
        return {"ltp": ltp, "change_pct": change_pct}
    return _live_quote_yfinance(stock_symbol_to_yf(symbol))


def _live_quote_crypto(symbol: str) -> dict:
    key = _crypto_key(symbol)
    try:
        snapshot = fetch_coindcx_futures_snapshot()
    except Exception:
        snapshot = []
    for row in snapshot:
        if _crypto_key(row.get("sym", "")) == key:
            return {"ltp": row["price"], "change_pct": row.get("change")}
    return _live_quote_yfinance(_crypto_symbol_to_yf(symbol))


def get_live_quote(symbol: str, market: str = "", *, exchange: str = "NSE", groww_token: str = "") -> dict:
    """Return {"ltp": float, "change_pct": float|None} for symbol/market, or {} if unavailable."""
    if not symbol:
        return {}
    try:
        if is_crypto_market(market):
            return _live_quote_crypto(symbol)
        if is_us_market(market):
            return _live_quote_yfinance(us_symbol_to_yf(symbol))
        return _live_quote_india(symbol, exchange or "NSE")
    except Exception:
        logger.debug("get_live_quote failed for %s (%s)", symbol, market, exc_info=True)
        return {}
