"""
pro_trade_backtest.py
---------------------
Historical signal-frame builders for Pro Trade engines used by EngineBacktestService.

Each builder returns an OHLCV DataFrame with a `signal` column in {-1, 0, 1}.
Approximations of the live scanners — research / education only.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.mtf_scanner_engine import normalize_ohlcv


def _empty_with_signal(df: pd.DataFrame) -> pd.DataFrame:
    work = normalize_ohlcv(df).copy()
    if work.empty:
        return work
    work["signal"] = 0
    return work


def build_volume_spread_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    from app.market_pulse.volume_spread_next_candle_engine import VolumeSpreadConfig, calculate_vsa

    cfg = cfg or VolumeSpreadConfig()
    work = calculate_vsa(df, cfg)
    if work.empty:
        return work
    frame = work.copy()
    frame["signal"] = 0
    sos = frame.get("sos_downthrust", False) | frame.get("sos_no_supply", False)
    sow = frame.get("sow_upthrust", False) | frame.get("sow_no_demand", False)
    # Prefer thrust bars when both fire
    frame.loc[sos & ~sow, "signal"] = 1
    frame.loc[sow & ~sos, "signal"] = -1
    frame.loc[frame.get("sos_downthrust", False) & sow, "signal"] = 1
    frame.loc[frame.get("sow_upthrust", False) & sos & ~frame.get("sos_downthrust", False), "signal"] = -1
    return frame


def build_pa_volume_profile_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    """Historical FVG + nearby POC confluence (formation bar), plus SR-flip first retest."""
    from app.market_pulse.pa_volume_profile_engine import (
        PaVolumeProfileConfig,
        _build_fixed_range_vp,
        detect_sr_flip_setups,
    )

    cfg = cfg or PaVolumeProfileConfig()
    work = _empty_with_signal(df)
    if len(work) < 40:
        return work

    signals = np.zeros(len(work), dtype=int)
    vp_lookback = int(cfg.vp_lookback)
    tol = float(cfg.poc_tolerance_pct)

    for i in range(2, len(work)):
        c1 = work.iloc[i - 2]
        c3 = work.iloc[i]
        bullish = float(c3["low"]) > float(c1["high"])
        bearish = float(c3["high"]) < float(c1["low"])
        if not bullish and not bearish:
            continue
        start = max(0, i - 2 - vp_lookback)
        window = work.iloc[start : i - 1]
        if len(window) < 5:
            continue
        poc, zone_low, zone_high, _vp = _build_fixed_range_vp(window, bins=int(cfg.num_bins))
        if poc is None:
            continue
        if bullish:
            entry = float(c1["high"])
            near_poc = abs(entry - poc) / max(poc, 1e-9) * 100.0 <= tol
            behind = zone_high is not None and zone_low is not None and zone_high >= entry * 0.998 and zone_low <= entry
            if near_poc or behind:
                signals[i] = 1
        else:
            entry = float(c1["low"])
            near_poc = abs(entry - poc) / max(poc, 1e-9) * 100.0 <= tol
            behind = zone_low is not None and zone_high is not None and zone_low <= entry * 1.002 and zone_high >= entry
            if near_poc or behind:
                signals[i] = -1

    # Overlay SR-flip first-retest entries (BUY/SELL only)
    sr = detect_sr_flip_setups(
        work,
        vp_lookback=cfg.vp_lookback,
        num_bins=cfg.num_bins,
        left=cfg.sr_pivot_left,
        right=cfg.sr_pivot_right,
        breakout_buffer_pct=cfg.breakout_buffer_pct,
        max_setups=cfg.max_setups * 4,
    )
    index_str = {str(idx): idx for idx in work.index}
    for s in sr:
        if s.get("signal") not in ("BUY", "SELL"):
            continue
        t = str(s.get("level_time") or "")
        idx = index_str.get(t)
        if idx is None:
            for k, v in index_str.items():
                if t and (k.startswith(t[:16]) or t.startswith(k[:16])):
                    idx = v
                    break
        if idx is None:
            continue
        # Prefer retest bar ≈ when signal fires — use last index as approximation if only level_time
        signals[work.index.get_loc(idx)] = 1 if s["direction"] == "LONG" else -1

    work["signal"] = signals
    return work


def build_volume_profile_poc_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    """Rolling fixed-range VP + first-touch after breakout (simplified historical replay)."""
    from app.market_pulse.volume_profile_poc_engine import (
        VolumeProfilePocConfig,
        calculate_volume_profile,
        identify_key_levels,
    )

    cfg = cfg or VolumeProfilePocConfig()
    work = _empty_with_signal(df)
    n = len(work)
    profile_bars = int(getattr(cfg, "profile_bars", 60))
    if n < profile_bars + 10:
        return work

    signals = np.zeros(n, dtype=int)
    i = profile_bars
    while i < n - 1:
        window = work.iloc[i - profile_bars : i]
        vp = calculate_volume_profile(window, num_bins=int(getattr(cfg, "num_bins", 40)))
        levels = identify_key_levels(vp, cluster_vol_pct=float(getattr(cfg, "cluster_vol_pct", 0.70)))
        if not levels:
            i += 1
            continue

        zone_lo = float(levels["zone_lower"])
        zone_hi = float(levels["zone_upper"])
        buf = float(getattr(cfg, "breakout_buffer_pct", 1.0)) / 100.0
        broke_up = broke_down = False
        for j in range(i, min(n, i + profile_bars)):
            row = work.iloc[j]
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            if not broke_up and not broke_down:
                if close > zone_hi * (1 + buf):
                    broke_up = True
                elif close < zone_lo * (1 - buf):
                    broke_down = True
                continue
            if broke_up and low <= zone_hi:
                signals[j] = 1
                i = j + 1
                break
            if broke_down and high >= zone_lo:
                signals[j] = -1
                i = j + 1
                break
        else:
            i += max(5, profile_bars // 4)
            continue
    work["signal"] = signals
    return work


def build_volume_profile_ce_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    """Session VA edge + rejection candle heuristic (simplified CE Strategy 1)."""
    from app.market_pulse.volume_profile_ce_engine import (
        VolumeProfileCeConfig,
        _is_hammer,
        _is_shooting_star,
        calculate_volume_profile,
    )

    cfg = cfg or VolumeProfileCeConfig()
    work = _empty_with_signal(df)
    if len(work) < 40:
        return work

    lookback = min(80, max(30, len(work) // 3))
    signals = np.zeros(len(work), dtype=int)
    tol = float(getattr(cfg, "val_touch_tol_pct", 0.15)) / 100.0
    wick_mult = 1.5

    for i in range(lookback, len(work)):
        window = work.iloc[i - lookback : i + 1]
        poc, vah, val, _vp = calculate_volume_profile(
            window,
            num_bins=int(getattr(cfg, "num_bins", 50)),
            value_area_pct=float(getattr(cfg, "value_area_pct", 0.70)),
        )
        if val is None or vah is None:
            continue
        row = work.iloc[i]
        close = float(row["close"])
        if abs(close - val) / max(val, 1e-9) <= tol and _is_hammer(row, wick_mult):
            signals[i] = 1
        elif abs(close - vah) / max(vah, 1e-9) <= tol and _is_shooting_star(row, wick_mult):
            signals[i] = -1

    work["signal"] = signals
    return work


def build_pa_vp_smc_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    """
    Simplified confluence proxy on a single TF:
    EMA trend + liquidity sweep wick + low-spread high-volume (VSA thrust) agreement.
    """
    from app.market_pulse.pro_trade_shared import ema
    from app.market_pulse.volume_spread_next_candle_engine import VolumeSpreadConfig, calculate_vsa

    work = calculate_vsa(df, VolumeSpreadConfig(vol_ma_period=20, ultra_vol_lookback=40))
    if work.empty or len(work) < 60:
        return _empty_with_signal(df)

    e21 = ema(work["close"], 21)
    e55 = ema(work["close"], 55)
    bull_trend = e21 > e55
    bear_trend = e21 < e55

    # Sweep: wick beyond prior 5-bar high/low, close back inside
    prior_high = work["high"].rolling(5).max().shift(1)
    prior_low = work["low"].rolling(5).min().shift(1)
    sweep_long = (work["low"] < prior_low) & (work["close"] > prior_low)
    sweep_short = (work["high"] > prior_high) & (work["close"] < prior_high)

    sos = work.get("sos_downthrust", False) | work.get("sos_no_supply", False)
    sow = work.get("sow_upthrust", False) | work.get("sow_no_demand", False)

    frame = work.copy()
    frame["signal"] = 0
    long_ok = bull_trend & (sweep_long | sos)
    short_ok = bear_trend & (sweep_short | sow)
    frame.loc[long_ok & ~short_ok, "signal"] = 1
    frame.loc[short_ok & ~long_ok, "signal"] = -1
    return frame


def build_bb_mean_reversion_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    """Vectorized replay of the core BB Mean Reversion read: %B stretch beyond
    the band, confirmed by a genuinely range-bound market (Kaufman Efficiency
    Ratio) and an echoing RSI extreme — the same three core signals
    `analyze_ticker` scores first, before any of its 13 optional extras."""
    from app.market_pulse.bb_mean_reversion_engine import BbMeanReversionConfig
    from app.market_pulse.pro_trade_shared import kaufman_efficiency_ratio, rsi as _rsi_ind

    cfg = cfg or BbMeanReversionConfig()
    work = _empty_with_signal(df)
    period = int(getattr(cfg, "bb_period", 20))
    std_mult = float(getattr(cfg, "bb_std", 2.0))
    if len(work) < period + 20:
        return work

    closes = work["close"]
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    band_range = (upper - lower).replace(0, np.nan)
    percent_b = (closes - lower) / band_range

    er = kaufman_efficiency_ratio(closes, period=14)
    rsi_val = _rsi_ind(closes, period=14)

    range_bound = er < 0.5
    stretched_high = percent_b >= 1.0
    stretched_low = percent_b <= 0.0
    rsi_confirms_high = rsi_val >= 60
    rsi_confirms_low = rsi_val <= 40

    frame = work.copy()
    frame["signal"] = 0
    long_ok = stretched_low & range_bound & rsi_confirms_low
    short_ok = stretched_high & range_bound & rsi_confirms_high
    frame.loc[long_ok & ~short_ok, "signal"] = 1
    frame.loc[short_ok & ~long_ok, "signal"] = -1
    return frame


def build_bb_rsi_vol_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    """Vectorized BB-RSI-VOL core: band touch + RSI extreme + volume vs MA20
    + close beyond EMA9. S/R / 50 EMA are live-only filters (need swing zones)."""
    from app.market_pulse.bb_rsi_vol_engine import BbRsiVolConfig
    from app.market_pulse.pro_trade_shared import ema as _ema, rsi as _rsi_ind

    cfg = cfg or BbRsiVolConfig()
    work = _empty_with_signal(df)
    period = int(getattr(cfg, "bb_period", 20))
    std_mult = float(getattr(cfg, "bb_std", 2.0))
    rsi_buy = float(getattr(cfg, "rsi_buy", 35.0))
    rsi_sell = float(getattr(cfg, "rsi_sell", 70.0))
    vol_ma_n = int(getattr(cfg, "vol_ma_period", 20))
    ema_n = int(getattr(cfg, "ema_fast", 9))
    if len(work) < period + 25:
        return work

    closes = work["close"]
    highs = work["high"]
    lows = work["low"]
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    rsi_val = _rsi_ind(closes, period=14)
    ema9 = _ema(closes, ema_n)
    if "volume" in work.columns:
        vol = work["volume"]
        vol_ma = vol.rolling(vol_ma_n).mean()
        low_vol = vol < vol_ma
        high_vol = vol > vol_ma
    else:
        low_vol = pd.Series(True, index=work.index)
        high_vol = pd.Series(True, index=work.index)

    touch_low = (lows <= lower) | (closes <= lower)
    touch_high = (highs >= upper) | (closes >= upper)
    long_ok = touch_low & (rsi_val <= rsi_buy) & low_vol & (closes > ema9)
    short_ok = touch_high & (rsi_val >= rsi_sell) & high_vol & (closes < ema9)

    frame = work.copy()
    frame["signal"] = 0
    frame.loc[long_ok & ~short_ok, "signal"] = 1
    frame.loc[short_ok & ~long_ok, "signal"] = -1
    return frame


def build_elliott_wave_signals(df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    """Replays the live engine's own `analyze_elliott_waves` ZigZag wave
    count on an expanding (no-lookahead) window each bar, using the same
    IMPULSE-wave-5 / CORRECTIVE-wave-C entry rule as `analyze_ticker`."""
    from app.market_pulse.elliott_wave_engine import ElliottWaveConfig
    from app.market_pulse.price_action import analyze_elliott_waves

    cfg = cfg or ElliottWaveConfig()
    work = _empty_with_signal(df)
    n = len(work)
    min_bars = max(int(getattr(cfg, "min_bars", 30)), 30)
    if n < min_bars + 10:
        return work

    zigzag_pct = float(getattr(cfg, "zigzag_pct", 3.0))
    signals = np.zeros(n, dtype=int)
    for i in range(min_bars, n):
        window = work.iloc[: i + 1]
        ew = analyze_elliott_waves(window, zigzag_pct=zigzag_pct)
        waves = ew.get("waves") or []
        if not waves:
            continue
        last_wave = waves[-1]
        direction = last_wave.get("direction")
        current_wave = str(ew.get("current_wave"))
        if ew.get("pattern") == "IMPULSE" and ew.get("valid_impulse"):
            signals[i] = -1 if direction == "UP" else 1
        elif ew.get("pattern") == "CORRECTIVE" and current_wave == "C":
            signals[i] = 1 if direction == "DOWN" else -1

    work["signal"] = signals
    return work


def _resample_ohlcv_positional(df: pd.DataFrame, group: int) -> pd.DataFrame:
    """Groups every `group` bars into one synthetic higher-timeframe bar,
    positionally (not calendar-based) so it works for any fetched interval."""
    n = len(df)
    if n < group:
        return df.iloc[0:0]
    usable = n - (n % group)
    trimmed = df.iloc[:usable]
    idx = trimmed.index[group - 1 :: group]
    o = trimmed["open"].to_numpy().reshape(-1, group)[:, 0]
    h = trimmed["high"].to_numpy().reshape(-1, group).max(axis=1)
    lo = trimmed["low"].to_numpy().reshape(-1, group).min(axis=1)
    c = trimmed["close"].to_numpy().reshape(-1, group)[:, -1]
    if "volume" in trimmed:
        v = trimmed["volume"].to_numpy().reshape(-1, group).sum(axis=1)
    else:
        v = np.zeros(len(idx))
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": v}, index=idx)


def build_support_resistance_signals(df: pd.DataFrame, *, cfg: Any = None, htf_group: int = 6) -> pd.DataFrame:
    """Replays the live engine's own `run_sr_pipeline` + `evaluate_live_signal`
    (HTF zone detection + LTF break-and-retest confirmation) bar-by-bar. The
    backtester only fetches one timeframe, so the HTF the live engine needs
    is derived by grouping every `htf_group` fetched bars into one synthetic
    HTF bar — the live engine's own pure zone/tap/structure-break logic is
    reused unchanged, only its HTF input is synthesized."""
    from app.trading_hubs.support_resistance_engine import (
        SupportResistanceConfig,
        evaluate_live_signal,
        run_sr_pipeline,
    )

    cfg = cfg or SupportResistanceConfig()
    work = _empty_with_signal(df)
    n = len(work)
    min_bars = max(int(getattr(cfg, "min_bars", 80)), 80)
    min_htf_bars = max(int(getattr(cfg, "swing_window", 5)) * 4, 20)
    if n < min_bars + (min_htf_bars * htf_group) + 10:
        return work

    signals = np.zeros(n, dtype=int)
    step = max(1, n // 250)
    for i in range(min_bars + min_htf_bars * htf_group, n, step):
        ltf_window = work.iloc[max(0, i - min_bars) : i + 1]
        htf_bars = _resample_ohlcv_positional(work.iloc[: i + 1], htf_group)
        if len(htf_bars) < min_htf_bars:
            continue
        pipeline = run_sr_pipeline(ltf_window, htf_bars, cfg)
        if pipeline.get("error"):
            continue
        live = evaluate_live_signal(pipeline, cfg)
        if live.get("take_trade"):
            signals[i] = 1 if live.get("direction") == "LONG" else -1

    work["signal"] = signals
    return work


PRO_TRADE_SIGNAL_BUILDERS: dict[str, Any] = {
    "volume_spread_next_candle": build_volume_spread_signals,
    "pa_volume_profile": build_pa_volume_profile_signals,
    "volume_profile_poc": build_volume_profile_poc_signals,
    "volume_profile_ce": build_volume_profile_ce_signals,
    "pa_vp_smc": build_pa_vp_smc_signals,
    "bb_mean_reversion": build_bb_mean_reversion_signals,
    "bb_rsi_vol": build_bb_rsi_vol_signals,
    "elliott_wave_pro": build_elliott_wave_signals,
    "support_resistance": build_support_resistance_signals,
}


def build_pro_trade_signal_frame(strategy_id: str, df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    builder = PRO_TRADE_SIGNAL_BUILDERS.get(strategy_id)
    if builder is None:
        raise ValueError(f"No Pro Trade signal builder for {strategy_id}")
    return builder(df, cfg=cfg)
