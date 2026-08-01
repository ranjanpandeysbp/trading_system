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


PRO_TRADE_SIGNAL_BUILDERS: dict[str, Any] = {
    "volume_spread_next_candle": build_volume_spread_signals,
    "pa_volume_profile": build_pa_volume_profile_signals,
    "volume_profile_poc": build_volume_profile_poc_signals,
    "volume_profile_ce": build_volume_profile_ce_signals,
    "pa_vp_smc": build_pa_vp_smc_signals,
}


def build_pro_trade_signal_frame(strategy_id: str, df: pd.DataFrame, *, cfg: Any = None) -> pd.DataFrame:
    builder = PRO_TRADE_SIGNAL_BUILDERS.get(strategy_id)
    if builder is None:
        raise ValueError(f"No Pro Trade signal builder for {strategy_id}")
    return builder(df, cfg=cfg)
