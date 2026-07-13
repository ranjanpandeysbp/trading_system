"""Bridge app OHLCV (lowercase) to SMC engine (Open/High/Low/Close)."""

from __future__ import annotations

import pandas as pd

from app.market_pulse.mtf_scanner_engine import normalize_ohlcv


def to_smc_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    return pd.DataFrame(
        {
            "Open": work["open"].astype(float),
            "High": work["high"].astype(float),
            "Low": work["low"].astype(float),
            "Close": work["close"].astype(float),
        },
        index=work.index,
    )
