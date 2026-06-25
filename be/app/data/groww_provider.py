"""Groww data provider with yfinance fallback (truebacktesting pattern)."""

from __future__ import annotations

import asyncio
import logging

import pandas as pd

from app.data.base import DataProvider
from app.data.groww_client import (
    _period_to_limit,
    fetch_groww_ohlcv,
    interval_to_tf_key,
)
from app.data.nse_symbols import resolve_groww_symbol_candidates
from app.data.yfinance_provider import INTERVAL_PERIOD_MAP, YFinanceProvider, normalize_ticker

logger = logging.getLogger(__name__)

MIN_BARS = 5


class GrowwProvider(DataProvider):
    """
    Groww-first data provider.

    Tries authenticated Groww REST API when token is set, then the public
    Groww charting service, then yfinance — matching truebacktesting flow.
    """

    name = "groww"

    def __init__(self, api_token: str = "", exchange: str = "NSE", fallback_yfinance: bool = True):
        self.api_token = (api_token or "").strip()
        self.exchange = (exchange or "NSE").upper()
        self.fallback_yfinance = fallback_yfinance
        self._yf = YFinanceProvider()

    def _fetch_sync(self, ticker: str, period: str | None, interval: str) -> pd.DataFrame:
        tf_key = interval_to_tf_key(interval)
        limit = _period_to_limit(period or INTERVAL_PERIOD_MAP.get(interval), interval)
        candidates = resolve_groww_symbol_candidates(ticker)

        if not candidates:
            raise ValueError(f"Could not resolve Groww symbol for {ticker}")

        last_error: str | None = None
        for sym in candidates:
            try:
                df = fetch_groww_ohlcv(
                    sym,
                    self.exchange,
                    tf_key,
                    api_token=self.api_token,
                    limit=limit,
                )
                if df is not None and len(df) >= MIN_BARS:
                    logger.info("Groww OHLCV %s via %s [%s] (%d bars)", ticker, sym, tf_key, len(df))
                    return df
                last_error = f"No/insufficient Groww data for {sym}"
            except Exception as exc:
                last_error = str(exc)
                logger.debug("Groww skip %s (%s): %s", ticker, sym, exc)

        if self.fallback_yfinance:
            logger.info("Groww fallback to yfinance for %s [%s]", ticker, interval)
            period = period or INTERVAL_PERIOD_MAP.get(interval, "60d")
            import yfinance as yf

            yf_sym = normalize_ticker(ticker)
            raw = yf.download(yf_sym, period=period, interval=interval, progress=False, auto_adjust=True)
            if raw.empty:
                raise ValueError(last_error or f"No data for {ticker}")
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in raw.columns]
            else:
                raw.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in raw.columns]
            raw = raw.rename(columns={"adj close": "close"})
            return raw[["open", "high", "low", "close", "volume"]].dropna().tail(limit)

        raise ValueError(last_error or f"No Groww data for {ticker}")

    async def fetch_ohlcv(self, ticker: str, period: str | None = None, interval: str = "1d") -> pd.DataFrame:
        return await asyncio.to_thread(self._fetch_sync, ticker, period, interval)

    async def health_check(self) -> dict:
        try:
            df = await self.fetch_ohlcv("RELIANCE", interval="1d", period="5d")
            mode = "authenticated" if self.api_token else "public_charting"
            return {
                "ok": True,
                "provider": self.name,
                "mode": mode,
                "exchange": self.exchange,
                "rows": len(df),
            }
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    async def get_market_price(self, ticker: str) -> float | None:
        from app.data.market_price import fetch_market_price

        try:
            return await fetch_market_price(
                ticker,
                groww_token=self.api_token,
                exchange=self.exchange,
            )
        except Exception:
            return None
