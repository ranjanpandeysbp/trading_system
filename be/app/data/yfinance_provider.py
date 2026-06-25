import pandas as pd

from app.data.base import DataProvider

INTERVAL_PERIOD_MAP = {
    "1m": "7d",
    "3m": "60d",
    "5m": "60d",
    "15m": "60d",
    "1d": "2y",
    "1wk": "5y",
}


def normalize_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if t.startswith("^"):
        return t
    if "." not in t:
        return f"{t}.NS"
    return t


class YFinanceProvider(DataProvider):
    name = "yfinance"

    async def fetch_ohlcv(self, ticker: str, period: str | None = None, interval: str = "1d") -> pd.DataFrame:
        import yfinance as yf

        symbol = normalize_ticker(ticker)
        period = period or INTERVAL_PERIOD_MAP.get(interval, "60d")
        raw = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
        if raw.empty:
            raise ValueError(f"No data returned for {symbol} (period={period}, interval={interval})")

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in raw.columns]

        raw = raw.rename(columns={"adj close": "close"})
        required = ["open", "high", "low", "close", "volume"]
        missing = set(required) - set(raw.columns)
        if missing:
            raise ValueError(f"Missing columns from yfinance: {missing}")
        return raw[required].dropna()

    async def get_market_price(self, ticker: str) -> float | None:
        from app.data.market_price import fetch_market_price

        try:
            return await fetch_market_price(ticker)
        except Exception:
            return None

    async def health_check(self) -> dict:
        try:
            df = await self.fetch_ohlcv("^NSEI", period="5d", interval="1d")
            return {"ok": True, "provider": self.name, "rows": len(df)}
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}
