"""OHLCV frame normalization and alignment for backtests."""

from __future__ import annotations

import pandas as pd

DAILY_INTERVALS = frozenset({"1d", "1wk"})


def normalize_ohlcv_index(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Normalize timestamps so stock and benchmark frames can be joined."""
    if df.empty:
        return df
    out = df.copy()
    idx = pd.to_datetime(out.index, utc=True)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    if interval in DAILY_INTERVALS:
        idx = idx.normalize()
    out.index = idx
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def align_benchmark_close(stock_df: pd.DataFrame, benchmark_df: pd.DataFrame, interval: str) -> pd.Series:
    """Return benchmark close series aligned to the stock index."""
    stock = normalize_ohlcv_index(stock_df, interval)
    bench = normalize_ohlcv_index(benchmark_df, interval)
    close = bench["close"]
    aligned = close.reindex(stock.index).ffill().bfill()
    return aligned
