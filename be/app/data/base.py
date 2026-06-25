from abc import ABC, abstractmethod

import pandas as pd


class DataProvider(ABC):
    name: str

    @abstractmethod
    async def fetch_ohlcv(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        pass

    @abstractmethod
    async def get_market_price(self, ticker: str) -> float | None:
        """Current market price for display / paper trading."""
        pass

    @abstractmethod
    async def health_check(self) -> dict:
        pass
