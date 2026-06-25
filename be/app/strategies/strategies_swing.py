"""5 swing strategies for daily charts."""

import pandas as pd

from app.strategies.indicators import bollinger_bands, ema, rsi, sma


def golden_death_cross_swing(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], fast)
    out["ema_slow"] = ema(out["close"], slow)
    golden = (out["ema_fast"] > out["ema_slow"]) & (out["ema_fast"].shift(1) <= out["ema_slow"].shift(1))
    death = (out["ema_fast"] < out["ema_slow"]) & (out["ema_fast"].shift(1) >= out["ema_slow"].shift(1))
    vol_confirm = out["volume"] > out["volume"].rolling(20, min_periods=1).mean()
    out["signal"] = 0
    out.loc[golden & vol_confirm, "signal"] = 1
    out.loc[death & vol_confirm, "signal"] = -1
    return out


def weekly_rsi_pullback_swing(
    df: pd.DataFrame, ma_period: int = 200, rsi_period: int = 14, buy_zone=(40, 50), sell_level: float = 70
) -> pd.DataFrame:
    out = df.copy()
    out["ma200"] = sma(out["close"], ma_period)
    out["rsi"] = rsi(out["close"], rsi_period)
    uptrend = out["close"] > out["ma200"]
    in_buy_zone = out["rsi"].between(buy_zone[0], buy_zone[1])
    entering_buy_zone = in_buy_zone & ~in_buy_zone.shift(1).fillna(False)
    overbought = out["rsi"] >= sell_level
    entering_overbought = overbought & ~overbought.shift(1).fillna(False)
    out["signal"] = 0
    out.loc[uptrend & entering_buy_zone, "signal"] = 1
    out.loc[entering_overbought, "signal"] = -1
    return out


def consolidation_breakout_swing(
    df: pd.DataFrame, consolidation_window: int = 25, max_range_pct: float = 0.08, breakout_vol_mult: float = 1.5
) -> pd.DataFrame:
    out = df.copy()
    roll_high = out["high"].rolling(consolidation_window, min_periods=consolidation_window).max()
    roll_low = out["low"].rolling(consolidation_window, min_periods=consolidation_window).min()
    range_pct = (roll_high - roll_low) / roll_low
    is_tight_base = range_pct.shift(1) <= max_range_pct
    vol_avg = out["volume"].rolling(consolidation_window, min_periods=consolidation_window).mean()
    breakout_up = is_tight_base & (out["close"] > roll_high.shift(1)) & (out["volume"] > breakout_vol_mult * vol_avg.shift(1))
    breakout_down = is_tight_base & (out["close"] < roll_low.shift(1)) & (out["volume"] > breakout_vol_mult * vol_avg.shift(1))
    out["base_high"], out["base_low"] = roll_high.shift(1), roll_low.shift(1)
    out["signal"] = 0
    out.loc[breakout_up, "signal"] = 1
    out.loc[breakout_down, "signal"] = -1
    return out


def bollinger_mean_reversion_swing(
    df: pd.DataFrame, window: int = 20, num_std: float = 2.0, trend_filter_period: int = 100, max_adx_proxy: float = 0.04
) -> pd.DataFrame:
    out = df.copy()
    mid, upper, lower, bw = bollinger_bands(out["close"], window, num_std)
    out["bb_mid"], out["bb_upper"], out["bb_lower"] = mid, upper, lower
    trend_ma = sma(out["close"], trend_filter_period)
    trend_slope_pct = trend_ma.diff(10) / trend_ma.shift(10)
    range_bound = trend_slope_pct.abs() <= max_adx_proxy
    touch_lower = out["close"] <= out["bb_lower"]
    touch_upper = out["close"] >= out["bb_upper"]
    out["signal"] = 0
    out.loc[range_bound & touch_lower, "signal"] = 1
    out.loc[range_bound & touch_upper, "signal"] = -1
    return out


def relative_strength_sector_rotation_swing(
    df: pd.DataFrame, benchmark_df: pd.DataFrame, rs_lookback: int = 63, rs_ma_period: int = 20
) -> pd.DataFrame:
    out = df.copy()
    bench = benchmark_df["close"].copy()
    out_idx = pd.to_datetime(out.index, utc=True)
    if out_idx.tz is not None:
        out_idx = out_idx.tz_convert(None)
    out_idx = out_idx.normalize()
    out.index = out_idx
    out = out[~out.index.duplicated(keep="last")].sort_index()

    bench.index = pd.to_datetime(bench.index, utc=True)
    if bench.index.tz is not None:
        bench.index = bench.index.tz_convert(None)
    bench.index = bench.index.normalize()
    bench = bench[~bench.index.duplicated(keep="last")].sort_index()
    bench = bench.reindex(out.index).ffill().bfill()
    rs_line = out["close"] / bench
    rs_ma = sma(rs_line, rs_ma_period)
    rs_high = rs_line.rolling(rs_lookback, min_periods=rs_lookback).max()
    out["rs_line"], out["rs_ma"] = rs_line, rs_ma
    cross_up = (rs_line > rs_ma) & (rs_line.shift(1) <= rs_ma.shift(1))
    cross_down = (rs_line < rs_ma) & (rs_line.shift(1) >= rs_ma.shift(1))
    new_rs_high = rs_line >= rs_high
    out["signal"] = 0
    out.loc[cross_up & new_rs_high, "signal"] = 1
    out.loc[cross_down, "signal"] = -1
    return out


SWING_STRATEGIES = {
    "golden_death_cross_swing": golden_death_cross_swing,
    "weekly_rsi_pullback_swing": weekly_rsi_pullback_swing,
    "consolidation_breakout_swing": consolidation_breakout_swing,
    "bollinger_mean_reversion_swing": bollinger_mean_reversion_swing,
    "relative_strength_sector_rotation_swing": relative_strength_sector_rotation_swing,
}
