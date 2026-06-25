"""5 intraday strategies for 5-min / 15-min charts."""

import pandas as pd

from app.strategies.indicators import (
    atr,
    ema,
    macd,
    rolling_pivot_high,
    rolling_pivot_low,
    rsi,
    vwap,
)


def orb_15min_with_retest(df: pd.DataFrame, range_minutes: int = 15, retest_tolerance: float = 0.001) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out.index.date
    or_high = out.groupby("date")["high"].transform(lambda s: s.iloc[:range_minutes].max())
    or_low = out.groupby("date")["low"].transform(lambda s: s.iloc[:range_minutes].min())
    out["or_high"], out["or_low"] = or_high, or_low
    bar_number = out.groupby("date").cumcount()
    after_range = bar_number >= range_minutes
    broke_up = ((out["close"] > out["or_high"]) & after_range).groupby(out["date"]).cumsum() > 0
    broke_down = ((out["close"] < out["or_low"]) & after_range).groupby(out["date"]).cumsum() > 0
    retest_up = broke_up & (out["low"] <= out["or_high"] * (1 + retest_tolerance)) & (out["close"] > out["or_high"])
    retest_down = broke_down & (out["high"] >= out["or_low"] * (1 - retest_tolerance)) & (out["close"] < out["or_low"])
    first_retest_up = retest_up & ~retest_up.groupby(out["date"]).shift(1).fillna(False)
    first_retest_down = retest_down & ~retest_down.groupby(out["date"]).shift(1).fillna(False)
    out["signal"] = 0
    out.loc[first_retest_up, "signal"] = 1
    out.loc[first_retest_down, "signal"] = -1
    out.drop(columns=["date"], inplace=True)
    return out


def vwap_trend_intraday(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["vwap"] = vwap(out)
    above = out["close"] > out["vwap"]
    cross_up = above & ~above.shift(1).fillna(False)
    cross_down = (~above) & above.shift(1).fillna(False)
    out["signal"] = 0
    out.loc[cross_up, "signal"] = 1
    out.loc[cross_down, "signal"] = -1
    return out


def rsi_divergence_intraday(df: pd.DataFrame, rsi_period: int = 14, pivot_window: int = 5) -> pd.DataFrame:
    out = df.copy()
    out["rsi"] = rsi(out["close"], rsi_period)
    piv_low = rolling_pivot_low(out["low"], pivot_window)
    piv_high = rolling_pivot_high(out["high"], pivot_window)
    out["signal"] = 0
    low_idx = out.index[piv_low]
    for i in range(1, len(low_idx)):
        t0, t1 = low_idx[i - 1], low_idx[i]
        if out.loc[t1, "low"] < out.loc[t0, "low"] and out.loc[t1, "rsi"] > out.loc[t0, "rsi"]:
            out.loc[t1, "signal"] = 1
    high_idx = out.index[piv_high]
    for i in range(1, len(high_idx)):
        t0, t1 = high_idx[i - 1], high_idx[i]
        if out.loc[t1, "high"] > out.loc[t0, "high"] and out.loc[t1, "rsi"] < out.loc[t0, "rsi"]:
            out.loc[t1, "signal"] = -1
    return out


def macd_volume_confirm_intraday(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    macd_line, signal_line, hist = macd(out["close"])
    out["macd"], out["macd_signal"], out["macd_hist"] = macd_line, signal_line, hist
    cross_up = (out["macd"] > out["macd_signal"]) & (out["macd"].shift(1) <= out["macd_signal"].shift(1))
    cross_down = (out["macd"] < out["macd_signal"]) & (out["macd"].shift(1) >= out["macd_signal"].shift(1))
    vol_confirm = out["volume"] > out["volume"].rolling(20, min_periods=1).mean()
    out["signal"] = 0
    out.loc[cross_up & vol_confirm, "signal"] = 1
    out.loc[cross_down & vol_confirm, "signal"] = -1
    return out


def sr_breakout_pullback_intraday(df: pd.DataFrame, lookback: int = 20, pullback_tolerance: float = 0.0015) -> pd.DataFrame:
    out = df.copy()
    resistance = out["high"].rolling(lookback, min_periods=lookback).max().shift(1)
    support = out["low"].rolling(lookback, min_periods=lookback).min().shift(1)
    out["resistance"], out["support"] = resistance, support
    broke_res = out["close"] > out["resistance"]
    broke_sup = out["close"] < out["support"]
    above_broke_res = broke_res.cumsum() > 0
    above_broke_sup = broke_sup.cumsum() > 0
    pullback_long = above_broke_res & (out["low"] <= out["resistance"] * (1 + pullback_tolerance)) & (
        out["close"] > out["resistance"]
    )
    pullback_short = above_broke_sup & (out["high"] >= out["support"] * (1 - pullback_tolerance)) & (
        out["close"] < out["support"]
    )
    out["signal"] = 0
    out.loc[pullback_long & ~pullback_long.shift(1).fillna(False), "signal"] = 1
    out.loc[pullback_short & ~pullback_short.shift(1).fillna(False), "signal"] = -1
    return out


INTRADAY_STRATEGIES = {
    "orb_15min_with_retest": orb_15min_with_retest,
    "vwap_trend_intraday": vwap_trend_intraday,
    "rsi_divergence_intraday": rsi_divergence_intraday,
    "macd_volume_confirm_intraday": macd_volume_confirm_intraday,
    "sr_breakout_pullback_intraday": sr_breakout_pullback_intraday,
}
