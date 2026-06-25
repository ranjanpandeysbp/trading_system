"""Weekly resample helper for swing engines."""

from __future__ import annotations

import pandas as pd


def _resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    work = daily.copy()
    work.columns = [str(c).lower() for c in work.columns]
    weekly = work.resample("W").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return weekly
