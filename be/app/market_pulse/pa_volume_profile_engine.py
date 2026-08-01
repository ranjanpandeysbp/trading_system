"""
pa_volume_profile_engine.py
---------------------------
PA + Volume Profile — Trader Dale filter for Price Action with institutional volume.

Source: https://www.youtube.com/watch?v=FVoXWlNkdhs

Setups:
  1. Fair Value Gap (FVG) + Volume Profile cluster at/behind the gap entry edge
  2. Support/Resistance flip + volume cluster at the breakout + first retest only

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.pro_trade_shared import ConfidenceScore, atr as _atr_ind, sl_tp_pct
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

_INTRADAY_TFS = {"1m", "3m", "5m", "15m", "30m", "1h"}

YOUTUBE_URL = "https://www.youtube.com/watch?v=FVoXWlNkdhs"
STRATEGY_NAME = "PA - Volume Profile"


@dataclass
class PaVolumeProfileConfig:
    timeframe: str = "15m"
    lookback_bars: int = 200
    vp_lookback: int = 40  # bars of consolidation before FVG / around breakout
    num_bins: int = 40
    poc_tolerance_pct: float = 0.35  # % — POC near FVG entry edge
    cluster_vol_pct: float = 0.65  # HVN = bins ≥ this fraction of max volume
    sr_pivot_left: int = 3
    sr_pivot_right: int = 3
    breakout_buffer_pct: float = 0.15
    max_setups: int = 8


def _build_fixed_range_vp(window: pd.DataFrame, bins: int = 40) -> tuple[float | None, float | None, float | None, pd.DataFrame]:
    """
    Fixed-range VP distributing each candle's volume across overlapping price bins.
    Returns poc, zone_low, zone_high, vp dataframe (Bin_Mid, Volume).
    """
    if window is None or window.empty or len(window) < 3:
        return None, None, None, pd.DataFrame()

    min_price = float(window["low"].min())
    max_price = float(window["high"].max())
    if not np.isfinite(min_price) or not np.isfinite(max_price) or max_price <= min_price:
        return None, None, None, pd.DataFrame()

    price_bins = np.linspace(min_price, max_price, max(bins, 5) + 1)
    volume_profile = np.zeros(len(price_bins) - 1)

    for _, row in window.iterrows():
        low = float(row["low"])
        high = float(row["high"])
        vol = float(row["volume"] or 0)
        candle_range = high - low
        if candle_range <= 0 or vol <= 0:
            # Point volume into nearest mid bin
            mid = (low + high) / 2.0 if high >= low else low
            for b in range(len(price_bins) - 1):
                if price_bins[b] <= mid <= price_bins[b + 1]:
                    volume_profile[b] += vol
                    break
            continue
        for b in range(len(price_bins) - 1):
            bin_low = price_bins[b]
            bin_high = price_bins[b + 1]
            overlap_low = max(low, bin_low)
            overlap_high = min(high, bin_high)
            if overlap_high > overlap_low:
                volume_profile[b] += vol * (overlap_high - overlap_low) / candle_range

    if float(volume_profile.sum()) <= 0:
        return None, None, None, pd.DataFrame()

    max_idx = int(np.argmax(volume_profile))
    poc = float((price_bins[max_idx] + price_bins[max_idx + 1]) / 2.0)
    max_vol = float(volume_profile[max_idx])
    threshold = max_vol * 0.65
    mids = (price_bins[:-1] + price_bins[1:]) / 2.0
    cluster_mids = mids[volume_profile >= threshold]
    zone_low = float(cluster_mids.min()) if len(cluster_mids) else poc
    zone_high = float(cluster_mids.max()) if len(cluster_mids) else poc

    vp = pd.DataFrame({
        "Bin_Mid": mids,
        "Volume": volume_profile,
    })
    return poc, zone_low, zone_high, vp


def _build_chart_data(df: pd.DataFrame, *, max_bars: int = 160) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    tail = df.iloc[-max_bars:]
    return [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        }
        for idx, bar in tail.iterrows()
    ]


def _vp_histogram(vp: pd.DataFrame) -> list[dict[str, Any]]:
    if vp is None or vp.empty:
        return []
    return [
        {"price": round(float(r["Bin_Mid"]), 4), "volume": round(float(r["Volume"]), 2)}
        for _, r in vp.iterrows()
    ]


def detect_fvg_setups(
    df: pd.DataFrame,
    *,
    vp_lookback: int,
    num_bins: int,
    poc_tolerance_pct: float,
    max_setups: int,
    timeframe: str = "15m",
) -> list[dict[str, Any]]:
    """FVG + VP confluence. VP built on consolidation window ending at candle 1 (i-2)."""
    setups: list[dict[str, Any]] = []
    if len(df) < max(vp_lookback + 5, 10):
        return setups

    atr_series = _atr_ind(df, 14)
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    vol_avg = df["volume"].rolling(20, min_periods=5).mean() if "volume" in df.columns else None
    hold = hold_for_tf(timeframe, "intraday" if timeframe in _INTRADAY_TFS else "swing")

    for i in range(2, len(df)):
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]
        # Bullish FVG: gap between high of c1 and low of c3
        bullish = float(c3["low"]) > float(c1["high"])
        # Bearish FVG: gap between low of c1 and high of c3
        bearish = float(c3["high"]) < float(c1["low"])
        if not bullish and not bearish:
            continue

        # Fixed-range VP over consolidation before the impulse (ending at c1)
        start = max(0, i - 2 - vp_lookback)
        window = df.iloc[start : i - 1]  # up to and including c1's prior bars; exclude impulse mid/c3
        if len(window) < 5:
            continue
        poc, zone_low, zone_high, _vp = _build_fixed_range_vp(window, bins=num_bins)
        if poc is None:
            continue

        if bullish:
            entry = float(c1["high"])  # beginning of gap
            gap_top = float(c3["low"])
            gap_bottom = entry
            # Cluster at/behind the FVG (POC near entry or zone overlapping/below entry)
            near_poc = abs(entry - poc) / max(poc, 1e-9) * 100.0 <= poc_tolerance_pct
            behind = zone_high >= entry * 0.998 and zone_low <= entry
            if not (near_poc or behind):
                continue
            # Live status: waiting for pullback to entry, or already filled/invalidated
            last = df.iloc[-1]
            status = "WATCH"
            if float(last["low"]) <= entry <= float(last["high"]):
                status = "BUY"
            elif float(last["close"]) < entry:
                status = "MISSED"  # traded through without us tracking fill — still show setup
            gap_size_pct = (gap_top - gap_bottom) / max(entry, 1e-9) * 100.0
            atr_last = float(atr_series.iloc[i]) if i < len(atr_series) and pd.notna(atr_series.iloc[i]) else None
            trend_up = bool(float(c3["close"]) > float(ema50.iloc[i])) if pd.notna(ema50.iloc[i]) else None
            vol_ratio = None
            if vol_avg is not None and i < len(vol_avg) and pd.notna(vol_avg.iloc[i]) and vol_avg.iloc[i] > 0:
                vol_ratio = float(c3["volume"]) / float(vol_avg.iloc[i])
            row: dict[str, Any] = {
                "setup": "fvg_volume_profile",
                "signal": status if status in ("BUY", "WATCH") else "WAIT",
                "direction": "LONG",
                "entry": round(entry, 4),
                "stop_loss": round(min(zone_low, float(c1["low"])) * 0.998, 4),
                "target_1": round(gap_top + (gap_top - gap_bottom), 4),
                "fvg_top": round(gap_top, 4),
                "fvg_bottom": round(gap_bottom, 4),
                "poc": round(poc, 4),
                "zone_low": round(zone_low, 4),
                "zone_high": round(zone_high, 4),
                "bar_time": str(df.index[i]),
                "logic": (
                    "Bullish FVG with heavy VP cluster at/behind gap start (c1 high). "
                    "Enter on pullback to beginning of gap; institutions defended this shelf."
                ),
            }
            if status == "BUY":
                score = ConfidenceScore(40, "bullish FVG with VP cluster confluence, price back at the gap start")
                score.add(atr_last is not None and (gap_top - gap_bottom) >= atr_last * 0.5, 15, f"gap spans {gap_size_pct:.2f}% of price — a real imbalance, not noise" if atr_last else "")
                score.add(abs(entry - poc) / max(poc, 1e-9) * 100.0 <= poc_tolerance_pct / 2, 15, "POC sits very close to the gap entry, not just within the loose tolerance")
                score.add(bool(trend_up), 15, "price is above its 50 EMA — the pullback trades with the trend, not against it")
                score.add(vol_ratio is not None and vol_ratio >= 1.3, 5, f"impulse candle volume {vol_ratio:.1f}x average" if vol_ratio else "")
                confidence, reasons = score.finalize()
                sl_pct, tp_pct = sl_tp_pct("LONG", row["entry"], row["stop_loss"], row["target_1"])
                row.update({"confidence_pct": confidence, "sl_pct": sl_pct, "tp_pct": tp_pct, "hold_duration": hold, "reasons": reasons})
            setups.append(row)
        else:
            entry = float(c1["low"])
            gap_bottom = float(c3["high"])
            gap_top = entry
            near_poc = abs(entry - poc) / max(poc, 1e-9) * 100.0 <= poc_tolerance_pct
            behind = zone_low <= entry * 1.002 and zone_high >= entry
            if not (near_poc or behind):
                continue
            last = df.iloc[-1]
            status = "WATCH"
            if float(last["low"]) <= entry <= float(last["high"]):
                status = "SELL"
            elif float(last["close"]) > entry:
                status = "MISSED"
            gap_size_pct = (gap_top - gap_bottom) / max(entry, 1e-9) * 100.0
            atr_last = float(atr_series.iloc[i]) if i < len(atr_series) and pd.notna(atr_series.iloc[i]) else None
            trend_down = bool(float(c3["close"]) < float(ema50.iloc[i])) if pd.notna(ema50.iloc[i]) else None
            vol_ratio = None
            if vol_avg is not None and i < len(vol_avg) and pd.notna(vol_avg.iloc[i]) and vol_avg.iloc[i] > 0:
                vol_ratio = float(c3["volume"]) / float(vol_avg.iloc[i])
            row = {
                "setup": "fvg_volume_profile",
                "signal": status if status in ("SELL", "WATCH") else "WAIT",
                "direction": "SHORT",
                "entry": round(entry, 4),
                "stop_loss": round(max(zone_high, float(c1["high"])) * 1.002, 4),
                "target_1": round(gap_bottom - (gap_top - gap_bottom), 4),
                "fvg_top": round(gap_top, 4),
                "fvg_bottom": round(gap_bottom, 4),
                "poc": round(poc, 4),
                "zone_low": round(zone_low, 4),
                "zone_high": round(zone_high, 4),
                "bar_time": str(df.index[i]),
                "logic": (
                    "Bearish FVG with heavy VP cluster at/behind gap start (c1 low). "
                    "Enter on pullback to beginning of gap."
                ),
            }
            if status == "SELL":
                score = ConfidenceScore(40, "bearish FVG with VP cluster confluence, price back at the gap start")
                score.add(atr_last is not None and (gap_top - gap_bottom) >= atr_last * 0.5, 15, f"gap spans {gap_size_pct:.2f}% of price — a real imbalance, not noise" if atr_last else "")
                score.add(abs(entry - poc) / max(poc, 1e-9) * 100.0 <= poc_tolerance_pct / 2, 15, "POC sits very close to the gap entry, not just within the loose tolerance")
                score.add(bool(trend_down), 15, "price is below its 50 EMA — the pullback trades with the trend, not against it")
                score.add(vol_ratio is not None and vol_ratio >= 1.3, 5, f"impulse candle volume {vol_ratio:.1f}x average" if vol_ratio else "")
                confidence, reasons = score.finalize()
                sl_pct, tp_pct = sl_tp_pct("SHORT", row["entry"], row["stop_loss"], row["target_1"])
                row.update({"confidence_pct": confidence, "sl_pct": sl_pct, "tp_pct": tp_pct, "hold_duration": hold, "reasons": reasons})
            setups.append(row)

        if len(setups) >= max_setups * 3:
            break

    # Keep most recent setups
    return setups[-max_setups:]


def _pivot_highs_lows(df: pd.DataFrame, left: int, right: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    n = len(df)
    for i in range(left, n - right):
        h = float(df.iloc[i]["high"])
        l = float(df.iloc[i]["low"])
        window_h = df.iloc[i - left : i + right + 1]["high"]
        window_l = df.iloc[i - left : i + right + 1]["low"]
        if h >= float(window_h.max()) and (window_h == h).sum() == 1:
            highs.append((i, h))
        if l <= float(window_l.min()) and (window_l == l).sum() == 1:
            lows.append((i, l))
    return highs, lows


def detect_sr_flip_setups(
    df: pd.DataFrame,
    *,
    vp_lookback: int,
    num_bins: int,
    left: int,
    right: int,
    breakout_buffer_pct: float,
    max_setups: int,
    timeframe: str = "15m",
) -> list[dict[str, Any]]:
    """
    Support broken → resistance (or resistance broken → support) with VP cluster at breakout,
    trade FIRST retest only.
    """
    setups: list[dict[str, Any]] = []
    if len(df) < max(40, vp_lookback + left + right + 5):
        return setups

    highs, lows = _pivot_highs_lows(df, left, right)
    last_i = len(df) - 1
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    vol_avg = df["volume"].rolling(20, min_periods=5).mean() if "volume" in df.columns else None
    hold = hold_for_tf(timeframe, "intraday" if timeframe in _INTRADAY_TFS else "swing")

    # Resistance flips to support (bullish): break above pivot high, first retest of that high
    for pi, level in highs[-12:]:
        broke = False
        touch_i = None
        break_i = None
        for j in range(pi + right + 1, last_i + 1):
            close = float(df.iloc[j]["close"])
            low = float(df.iloc[j]["low"])
            if not broke and close > level * (1.0 + breakout_buffer_pct / 100.0):
                broke = True
                break_i = j
                continue
            if broke and touch_i is None and low <= level:
                touch_i = j
                break
        if not broke:
            continue

        # VP around breakout
        b_start = max(0, pi - vp_lookback // 2)
        b_end = min(len(df), (touch_i or last_i) + 1)
        window = df.iloc[b_start:b_end]
        poc, zone_low, zone_high, _ = _build_fixed_range_vp(window, bins=num_bins)
        if poc is None:
            continue
        # Cluster must sit at the breakout level
        if not (zone_low <= level <= zone_high or abs(poc - level) / max(level, 1e-9) * 100 <= 0.5):
            continue

        if touch_i is not None and touch_i == last_i:
            signal = "BUY"
            logic = "Support/resistance flip: resistance broken with VP cluster at break — FIRST retest now"
        elif touch_i is not None:
            signal = "WAIT"
            logic = "S/R flip already had first retest earlier — skip subsequent touches"
            continue  # only first touch matters; historical fills not actionable now
        else:
            signal = "WATCH"
            logic = "Resistance broken with VP cluster at breakout — wait for FIRST pullback to flipped support"

        row = {
            "setup": "sr_flip_volume_profile",
            "signal": signal,
            "direction": "LONG",
            "entry": round(level, 4),
            "stop_loss": round(min(zone_low, level) * 0.997, 4),
            "target_1": round(level + (level - min(zone_low, level)) * 2, 4),
            "poc": round(poc, 4),
            "zone_low": round(zone_low, 4),
            "zone_high": round(zone_high, 4),
            "level_time": str(df.index[pi]),
            "logic": logic,
        }
        if signal == "BUY":
            trend_up = bool(float(df.iloc[last_i]["close"]) > float(ema50.iloc[last_i])) if pd.notna(ema50.iloc[last_i]) else None
            vol_ratio = None
            if vol_avg is not None and break_i is not None and pd.notna(vol_avg.iloc[break_i]) and vol_avg.iloc[break_i] > 0:
                vol_ratio = float(df.iloc[break_i]["volume"]) / float(vol_avg.iloc[break_i])
            poc_tightness = abs(poc - level) / max(level, 1e-9) * 100.0
            score = ConfidenceScore(45, "resistance-to-support flip with VP cluster confirming the breakout level")
            score.add(vol_ratio is not None and vol_ratio >= 1.4, 20, f"breakout bar volume {vol_ratio:.1f}x average — real institutional participation" if vol_ratio else "")
            score.add(poc_tightness <= 0.15, 15, "POC sits almost exactly on the flipped level")
            score.add(bool(trend_up), 10, "price still trading above its 50 EMA at the retest — trend intact")
            confidence, reasons = score.finalize()
            sl_pct, tp_pct = sl_tp_pct("LONG", row["entry"], row["stop_loss"], row["target_1"])
            row.update({"confidence_pct": confidence, "sl_pct": sl_pct, "tp_pct": tp_pct, "hold_duration": hold, "reasons": reasons})
        setups.append(row)

    # Support flips to resistance (bearish)
    for pi, level in lows[-12:]:
        broke = False
        touch_i = None
        break_i = None
        for j in range(pi + right + 1, last_i + 1):
            close = float(df.iloc[j]["close"])
            high = float(df.iloc[j]["high"])
            if not broke and close < level * (1.0 - breakout_buffer_pct / 100.0):
                broke = True
                break_i = j
                continue
            if broke and touch_i is None and high >= level:
                touch_i = j
                break
        if not broke:
            continue

        b_start = max(0, pi - vp_lookback // 2)
        b_end = min(len(df), (touch_i or last_i) + 1)
        window = df.iloc[b_start:b_end]
        poc, zone_low, zone_high, _ = _build_fixed_range_vp(window, bins=num_bins)
        if poc is None:
            continue
        if not (zone_low <= level <= zone_high or abs(poc - level) / max(level, 1e-9) * 100 <= 0.5):
            continue

        if touch_i is not None and touch_i == last_i:
            signal = "SELL"
            logic = "S/R flip: support broken with VP cluster at break — FIRST retest now"
        elif touch_i is not None:
            continue
        else:
            signal = "WATCH"
            logic = "Support broken with VP cluster at breakout — wait for FIRST retest of flipped resistance"

        row = {
            "setup": "sr_flip_volume_profile",
            "signal": signal,
            "direction": "SHORT",
            "entry": round(level, 4),
            "stop_loss": round(max(zone_high, level) * 1.003, 4),
            "target_1": round(level - (max(zone_high, level) - level) * 2, 4),
            "poc": round(poc, 4),
            "zone_low": round(zone_low, 4),
            "zone_high": round(zone_high, 4),
            "level_time": str(df.index[pi]),
            "logic": logic,
        }
        if signal == "SELL":
            trend_down = bool(float(df.iloc[last_i]["close"]) < float(ema50.iloc[last_i])) if pd.notna(ema50.iloc[last_i]) else None
            vol_ratio = None
            if vol_avg is not None and break_i is not None and pd.notna(vol_avg.iloc[break_i]) and vol_avg.iloc[break_i] > 0:
                vol_ratio = float(df.iloc[break_i]["volume"]) / float(vol_avg.iloc[break_i])
            poc_tightness = abs(poc - level) / max(level, 1e-9) * 100.0
            score = ConfidenceScore(45, "support-to-resistance flip with VP cluster confirming the breakdown level")
            score.add(vol_ratio is not None and vol_ratio >= 1.4, 20, f"breakdown bar volume {vol_ratio:.1f}x average — real institutional participation" if vol_ratio else "")
            score.add(poc_tightness <= 0.15, 15, "POC sits almost exactly on the flipped level")
            score.add(bool(trend_down), 10, "price still trading below its 50 EMA at the retest — trend intact")
            confidence, reasons = score.finalize()
            sl_pct, tp_pct = sl_tp_pct("SHORT", row["entry"], row["stop_loss"], row["target_1"])
            row.update({"confidence_pct": confidence, "sl_pct": sl_pct, "tp_pct": tp_pct, "hold_duration": hold, "reasons": reasons})
        setups.append(row)

    return setups[-max_setups:]


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: PaVolumeProfileConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "error": None,
        "setups": [],
        "actionable": [],
        "chart_data": [],
        "vp_histogram": [],
        "levels": None,
        "rules": [
            "Only take PA setups when a heavy Volume Profile cluster backs the level.",
            "FVG: enter at the beginning of the gap; VP cluster must sit at/behind that edge.",
            "S/R flip: require VP cluster at the breakout; trade the FIRST retest only.",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker,
            cfg.timeframe,
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    if df is None or df.empty or len(df) < 40:
        out["error"] = "Insufficient OHLCV for PA + Volume Profile"
        return out

    out["ltp"] = round(float(df["close"].iloc[-1]), 4)
    out["chart_data"] = _build_chart_data(df, max_bars=160)

    # Session/recent VP for histogram overlay
    tail_n = min(len(df), max(cfg.vp_lookback, 30))
    _poc, zlo, zhi, vp = _build_fixed_range_vp(df.iloc[-tail_n:], bins=cfg.num_bins)
    out["vp_histogram"] = _vp_histogram(vp)
    if _poc is not None:
        out["levels"] = {
            "poc": round(_poc, 4),
            "zone_low": round(zlo, 4) if zlo is not None else None,
            "zone_high": round(zhi, 4) if zhi is not None else None,
        }

    fvg = detect_fvg_setups(
        df,
        vp_lookback=cfg.vp_lookback,
        num_bins=cfg.num_bins,
        poc_tolerance_pct=cfg.poc_tolerance_pct,
        max_setups=cfg.max_setups,
        timeframe=cfg.timeframe,
    )
    sr = detect_sr_flip_setups(
        df,
        vp_lookback=cfg.vp_lookback,
        num_bins=cfg.num_bins,
        left=cfg.sr_pivot_left,
        right=cfg.sr_pivot_right,
        breakout_buffer_pct=cfg.breakout_buffer_pct,
        max_setups=cfg.max_setups,
        timeframe=cfg.timeframe,
    )
    setups = fvg + sr
    out["setups"] = setups
    actionable = [
        s for s in setups
        if s.get("signal") in ("BUY", "SELL") and s.get("direction")
    ]
    watch = [s for s in setups if s.get("signal") == "WATCH"]
    out["actionable"] = actionable
    out["take_trade"] = bool(actionable)
    out["verdict"] = "TAKE" if actionable else ("WATCH" if watch else "WAIT")
    if actionable:
        best = max(actionable, key=lambda s: float(s.get("confidence_pct") or 0))
        out["direction"] = best.get("direction")
    else:
        out["direction"] = None
    out["profile"] = {
        "tf": cfg.timeframe,
        "bars": int(len(df)),
        "vp_lookback": cfg.vp_lookback,
        "fvg_count": len(fvg),
        "sr_flip_count": len(sr),
    }
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: PaVolumeProfileConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or PaVolumeProfileConfig()
    results = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("PA Volume Profile failed for %s", t)
            results.append({
                "ticker": t,
                "error": str(exc),
                "setups": [],
                "actionable": [],
                "take_trade": False,
                "chart_data": [],
                "vp_histogram": [],
            })

    return {
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "results": results,
        "entry_count": sum(1 for r in results if r.get("take_trade")),
        "scanned": len(results),
        "config": {
            "timeframe": cfg.timeframe,
            "lookback_bars": cfg.lookback_bars,
            "vp_lookback": cfg.vp_lookback,
            "num_bins": cfg.num_bins,
            "poc_tolerance_pct": cfg.poc_tolerance_pct,
        },
        "disclaimer": "Research / education only — not financial advice.",
    }
