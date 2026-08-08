"""IndMoney / INDstocks DataProvider with yfinance fallback."""

from __future__ import annotations

import asyncio
import logging

import pandas as pd

from app.data.base import DataProvider
from app.data.indmoney_client import fetch_indmoney_ohlcv, fetch_indmoney_quote, health_check
from app.data.yfinance_provider import INTERVAL_PERIOD_MAP, YFinanceProvider, normalize_ticker

logger = logging.getLogger(__name__)
MIN_BARS = 5


class IndMoneyProvider(DataProvider):
    name = "indmoney"

    def __init__(self, access_token: str = "", exchange: str = "NSE", fallback_yfinance: bool = True):
        self.access_token = (access_token or "").strip()
        self.exchange = (exchange or "NSE").upper()
        self.fallback_yfinance = fallback_yfinance
        self._yf = YFinanceProvider()

    def _fetch_sync(self, ticker: str, period: str | None, interval: str) -> pd.DataFrame:
        from app.data.groww_client import _period_to_limit, interval_to_tf_key

        tf_key = interval_to_tf_key(interval)
        limit = _period_to_limit(period or INTERVAL_PERIOD_MAP.get(interval), interval)
        if self.access_token:
            df = fetch_indmoney_ohlcv(
                ticker, tf_key, self.access_token, exchange=self.exchange, limit=limit,
            )
            if df is not None and len(df) >= MIN_BARS:
                return df

        if self.fallback_yfinance:
            logger.info("IndMoney fallback to yfinance for %s [%s]", ticker, interval)
            return self._yf_sync(ticker, period, interval, limit)

        raise ValueError(f"No IndMoney data for {ticker}")

    def _yf_sync(self, ticker: str, period: str | None, interval: str, limit: int) -> pd.DataFrame:
        import yfinance as yf

        period = period or INTERVAL_PERIOD_MAP.get(interval, "60d")
        yf_sym = normalize_ticker(ticker)
        raw = yf.download(yf_sym, period=period, interval=interval, progress=False, auto_adjust=True)
        if raw.empty:
            raise ValueError(f"No data for {ticker}")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in raw.columns]
        raw = raw.rename(columns={"adj close": "close"})
        return raw[["open", "high", "low", "close", "volume"]].dropna().tail(limit)

    async def fetch_ohlcv(self, ticker: str, period: str | None = None, interval: str = "1d") -> pd.DataFrame:
        return await asyncio.to_thread(self._fetch_sync, ticker, period, interval)

    async def get_market_price(self, ticker: str) -> float | None:
        if self.access_token:
            q = await asyncio.to_thread(fetch_indmoney_quote, ticker, self.access_token, exchange=self.exchange)
            if q and q.get("ltp"):
                return float(q["ltp"])
        return await self._yf.get_market_price(ticker)

    async def health_check(self) -> dict:
        if not self.access_token:
            return {"ok": False, "provider": self.name, "error": "No IndMoney access token — configure TOTP credentials"}
        return await asyncio.to_thread(health_check, self.access_token)
