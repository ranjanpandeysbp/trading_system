"""5 scalping strategies for 1-min / 3-min charts."""

import numpy as np
import pandas as pd

from app.strategies.indicators import atr, bollinger_bands, ema, vwap


def vwap_bounce_scalp(df: pd.DataFrame, atr_period: int = 14, atr_mult: float = 0.25) -> pd.DataFrame:
    out = df.copy()
    out["vwap"] = vwap(out)
    out["vwap_slope"] = out["vwap"].diff()
    out["atr"] = atr(out, atr_period)
    dist_to_vwap = (out["close"] - out["vwap"]).abs()
    near_vwap = dist_to_vwap <= (atr_mult * out["atr"])
    long_cond = (out["vwap_slope"] > 0) & near_vwap & (out["close"] >= out["vwap"])
    short_cond = (out["vwap_slope"] < 0) & near_vwap & (out["close"] <= out["vwap"])
    out["signal"] = 0
    out.loc[long_cond, "signal"] = 1
    out.loc[short_cond, "signal"] = -1
    return out


def orb_1min_scalp(df: pd.DataFrame, range_minutes: int = 5) -> pd.DataFrame:
    out = df.copy()
    # Named "_grp_date", not "date" — the incoming index is itself named
    # "date" (normalize_ohlcv), and a same-named column makes every
    # groupby("date") below ambiguous (pandas can't tell index vs column).
    out["_grp_date"] = out.index.date
    or_high = out.groupby("_grp_date")["high"].transform(lambda s: s.iloc[:range_minutes].max())
    or_low = out.groupby("_grp_date")["low"].transform(lambda s: s.iloc[:range_minutes].min())
    out["or_high"], out["or_low"] = or_high, or_low
    vol_avg = out["volume"].rolling(20, min_periods=1).mean()
    vol_confirm = out["volume"] > vol_avg
    bar_number = out.groupby("_grp_date").cumcount()
    breakout_up = (out["close"] > out["or_high"]) & vol_confirm & (bar_number >= range_minutes)
    breakout_down = (out["close"] < out["or_low"]) & vol_confirm & (bar_number >= range_minutes)
    first_up = breakout_up & ~breakout_up.groupby(out["_grp_date"]).shift(1).fillna(False)
    first_down = breakout_down & ~breakout_down.groupby(out["_grp_date"]).shift(1).fillna(False)
    out["signal"] = 0
    out.loc[first_up, "signal"] = 1
    out.loc[first_down, "signal"] = -1
    out.drop(columns=["_grp_date"], inplace=True)
    return out


def orderflow_imbalance_scalp(df: pd.DataFrame, window: int = 10, z_thresh: float = 1.5) -> pd.DataFrame:
    out = df.copy()
    rng = (out["high"] - out["low"]).replace(0, np.nan)
    close_pos = (out["close"] - out["low"]) / rng
    buy_vol = np.where(close_pos >= 2 / 3, out["volume"], 0)
    sell_vol = np.where(close_pos <= 1 / 3, out["volume"], 0)
    delta = pd.Series(buy_vol - sell_vol, index=out.index)
    delta_roll = delta.rolling(window).sum()
    z = (delta_roll - delta_roll.rolling(50, min_periods=window).mean()) / delta_roll.rolling(
        50, min_periods=window
    ).std()
    out["delta_zscore"] = z
    out["signal"] = 0
    out.loc[z > z_thresh, "signal"] = 1
    out.loc[z < -z_thresh, "signal"] = -1
    return out


def ema_crossover_scalp(df: pd.DataFrame, fast: int = 5, slow: int = 9) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], fast)
    out["ema_slow"] = ema(out["close"], slow)
    cross_up = (out["ema_fast"] > out["ema_slow"]) & (out["ema_fast"].shift(1) <= out["ema_slow"].shift(1))
    cross_down = (out["ema_fast"] < out["ema_slow"]) & (out["ema_fast"].shift(1) >= out["ema_slow"].shift(1))
    vol_rising = out["volume"] > out["volume"].rolling(10, min_periods=1).mean()
    out["signal"] = 0
    out.loc[cross_up & vol_rising, "signal"] = 1
    out.loc[cross_down & vol_rising, "signal"] = -1
    return out


def bollinger_squeeze_breakout_scalp(df: pd.DataFrame, window: int = 20, squeeze_pct: float = 0.15) -> pd.DataFrame:
    out = df.copy()
    mid, upper, lower, bw = bollinger_bands(out["close"], window)
    out["bb_mid"], out["bb_upper"], out["bb_lower"], out["bb_bw"] = mid, upper, lower, bw
    bw_rank = out["bb_bw"].rolling(100, min_periods=window).apply(
        lambda x: (x.rank(pct=True).iloc[-1]) if x.notna().sum() > 1 else np.nan
    )
    squeeze = bw_rank <= squeeze_pct
    was_squeezed = squeeze.shift(1).fillna(False)
    breakout_up = was_squeezed & (out["close"] > out["bb_upper"])
    breakout_down = was_squeezed & (out["close"] < out["bb_lower"])
    out["signal"] = 0
    out.loc[breakout_up, "signal"] = 1
    out.loc[breakout_down, "signal"] = -1
    return out


SCALPING_STRATEGIES = {
    "vwap_bounce_scalp": vwap_bounce_scalp,
    "orb_1min_scalp": orb_1min_scalp,
    "orderflow_imbalance_scalp": orderflow_imbalance_scalp,
    "ema_crossover_scalp": ema_crossover_scalp,
    "bollinger_squeeze_breakout_scalp": bollinger_squeeze_breakout_scalp,
}
