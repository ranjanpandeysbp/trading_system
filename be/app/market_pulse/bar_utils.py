"""
bar_utils.py
------------
Shared "closed-bar gate" — every scanning engine in this app eventually reads
`df.iloc[-1]` to score the "current" signal. For intraday timeframes that row
can be a still-forming candle, which means the signal (and its confidence %)
can appear and flip before the bar it's based on has actually finished — a
silent gap between backtested and live behavior that nobody notices until
live win-rate quietly runs below what the backtest showed.

`last_closed_bar()` drops that final row when it isn't closed yet, so any
engine that fetches through `gap_trading.fetch_data_for_gap_scan` (or calls
this directly) scores only confirmed bars. It's deliberately conservative:
unknown timeframes, or frames too short to safely trim, are passed through
unchanged rather than guessed at.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

# Bar duration in minutes for every intraday timeframe this app fetches.
# 1d/1w/1M are handled separately below (see `is_bar_closed`) since their
# "close time" is a calendar boundary, not a fixed duration from bar open.
_INTRADAY_MINUTES = {
    "1m": 1, "2m": 2, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240,
}
_COARSE_TFS = ("1d", "1w", "1M")


def is_bar_closed(bar_open, timeframe: str, *, now: datetime | None = None) -> bool:
    """True if the bar starting at `bar_open` has finished as of `now`.

    For 1d/1w/1M, bars are labeled by their start date — a bar dated
    strictly before today (this week / this month) is necessarily already
    complete, since the fetch could not have returned a bar for a period
    that hasn't started yet. Only the bar dated *today* can still be
    forming. For intraday timeframes, closure is a fixed duration from the
    bar's open time.
    """
    if bar_open is None:
        return True
    now = now or datetime.now()
    bo = pd.Timestamp(bar_open)
    if bo.tzinfo is not None:
        bo = bo.tz_localize(None)
    bo = bo.to_pydatetime()

    if timeframe == "1d":
        return bo.date() < now.date()
    if timeframe == "1w":
        return bo.isocalendar()[:2] < now.isocalendar()[:2]
    if timeframe == "1M":
        return (bo.year, bo.month) < (now.year, now.month)

    minutes = _INTRADAY_MINUTES.get(timeframe)
    if minutes is None:
        return True  # unknown timeframe — don't guess, assume closed
    return now >= bo + timedelta(minutes=minutes)


def last_closed_bar(df: pd.DataFrame, timeframe: str, *, now: datetime | None = None) -> pd.DataFrame:
    """Drop the final row of `df` if it's still-forming for `timeframe`.

    No-op when `df` is empty/too short to safely trim, or when `timeframe`
    isn't one we know how to judge — callers should never see this raise or
    return an empty frame as a side effect of the gate itself.
    """
    if df is None or df.empty or len(df) < 2:
        return df
    if timeframe not in _INTRADAY_MINUTES and timeframe not in _COARSE_TFS:
        return df
    try:
        source = None
        try:
            source = df.attrs.get("data_source")
        except Exception:
            source = None
        if is_bar_closed(df.index[-1], timeframe, now=now):
            return df
        out = df.iloc[:-1]
        if source:
            try:
                out.attrs["data_source"] = source
            except Exception:
                pass
        return out
    except Exception:
        return df
