"""
swing_trading_st_simple_steal_engine.py
---------------------------------------
Little Rizzy — trendline measurement + Bollinger Band "reality" projection.

Descending trendline across bounce highs → measure low-to-line distance → project next leg down.
Inverse for uptrend: ascending trendline across pullback lows → project measured move up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.swing_trading_st_shared import enrich_st_live

logger = logging.getLogger(__name__)

YOUTUBE_ST_SIMPLE_STEAL_URL = "https://www.youtube.com/watch?v=AVVM-FyewLg&t=12s"

EXEC_DAILY = "1d"
EXEC_4H = "4h"

# Not defined in swing_trading_st_shared.py (backend copy) — keep local to avoid
# touching that shared module while it's being wired elsewhere.
HOLD_SIMPLE_STEAL = "3–10 trading days (Little Rizzy measured move)"

PHASE_NONE = "NO_SETUP"
PHASE_BEARISH = "BEARISH_RIZZY"
PHASE_BULLISH = "BULLISH_RIZZY"
PHASE_TARGET_WATCH = "TARGET_WATCH"
PHASE_INVALIDATED = "INVALIDATED"
PHASE_ENTRY = "RIZZY_ENTRY"

SETUP_BEARISH = "bearish"
SETUP_BULLISH = "bullish"


@dataclass
class SimpleStealConfig:
    execution_tf: str = EXEC_DAILY
    bb_window: int = 20
    bb_std: float = 2.0
    swing_order: int = 5
    rr_ratio: float = 1.0
    take_confidence_threshold: float = 58.0
    lookback_bars: int = 400
    min_bars: int = 60
    max_projection_age_bars: int = 40
    prefer_bb_extreme: bool = True


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    return work.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()


def compute_bollinger_bands(df: pd.DataFrame, window: int = 20, std_mult: float = 2.0) -> pd.DataFrame:
    work = normalize_ohlcv(df).copy()
    if work.empty:
        return work
    work["bb_sma"] = work["close"].rolling(window=window).mean()
    work["bb_std"] = work["close"].rolling(window=window).std()
    work["bb_upper"] = work["bb_sma"] + work["bb_std"] * std_mult
    work["bb_lower"] = work["bb_sma"] - work["bb_std"] * std_mult
    work["bb_pct_b"] = (work["close"] - work["bb_lower"]) / (work["bb_upper"] - work["bb_lower"]).replace(0, np.nan)
    return work


def _trendline_price(slope: float, intercept: float, idx: int) -> float:
    return slope * idx + intercept


def get_bearish_projections(df: pd.DataFrame, cfg: SimpleStealConfig) -> list[dict[str, Any]]:
    """Descending trendline across lower highs → project measured move down from lowest low."""
    work = normalize_ohlcv(df)
    if len(work) < cfg.min_bars:
        return []

    highs = work["high"].values
    lows = work["low"].values
    peak_indices = argrelextrema(highs, np.greater_equal, order=cfg.swing_order)[0]
    projections: list[dict[str, Any]] = []

    for i in range(len(peak_indices) - 1):
        idx1, idx2 = int(peak_indices[i]), int(peak_indices[i + 1])
        if highs[idx1] <= highs[idx2]:
            continue

        slope = (highs[idx2] - highs[idx1]) / (idx2 - idx1)
        intercept = highs[idx1] - slope * idx1

        search_end = min(len(work), idx2 + cfg.swing_order + 1)
        search_window = work.iloc[idx1:search_end]
        if search_window.empty:
            continue

        lowest_low_val = float(search_window["low"].min())
        rel = int(search_window["low"].values.argmin())
        lowest_low_idx = idx1 + rel

        tl_at_low = _trendline_price(slope, intercept, lowest_low_idx)
        if tl_at_low <= lowest_low_val:
            continue

        distance = tl_at_low - lowest_low_val
        projected_bottom = lowest_low_val - distance

        projections.append({
            "setup": SETUP_BEARISH,
            "peak_1_date": work.index[idx1],
            "peak_2_date": work.index[idx2],
            "structure_low_date": work.index[lowest_low_idx],
            "structure_price": lowest_low_val,
            "trendline_at_structure": tl_at_low,
            "distance": distance,
            "projected_target": projected_bottom,
            "slope": slope,
            "intercept": intercept,
            "structure_idx": lowest_low_idx,
            "invalidation_level": tl_at_low,
        })

    return projections


def get_bullish_projections(df: pd.DataFrame, cfg: SimpleStealConfig) -> list[dict[str, Any]]:
    """Ascending trendline across higher lows → project measured move up from highest high."""
    work = normalize_ohlcv(df)
    if len(work) < cfg.min_bars:
        return []

    highs = work["high"].values
    lows = work["low"].values
    trough_indices = argrelextrema(lows, np.less_equal, order=cfg.swing_order)[0]
    projections: list[dict[str, Any]] = []

    for i in range(len(trough_indices) - 1):
        idx1, idx2 = int(trough_indices[i]), int(trough_indices[i + 1])
        if lows[idx1] >= lows[idx2]:
            continue

        slope = (lows[idx2] - lows[idx1]) / (idx2 - idx1)
        intercept = lows[idx1] - slope * idx1

        search_end = min(len(work), idx2 + cfg.swing_order + 1)
        search_window = work.iloc[idx1:search_end]
        if search_window.empty:
            continue

        highest_high_val = float(search_window["high"].max())
        rel = int(search_window["high"].values.argmax())
        highest_high_idx = idx1 + rel

        tl_at_high = _trendline_price(slope, intercept, highest_high_idx)
        if tl_at_high >= highest_high_val:
            continue

        distance = highest_high_val - tl_at_high
        projected_top = highest_high_val + distance

        projections.append({
            "setup": SETUP_BULLISH,
            "trough_1_date": work.index[idx1],
            "trough_2_date": work.index[idx2],
            "structure_high_date": work.index[highest_high_idx],
            "structure_price": highest_high_val,
            "trendline_at_structure": tl_at_high,
            "distance": distance,
            "projected_target": projected_top,
            "slope": slope,
            "intercept": intercept,
            "structure_idx": highest_high_idx,
            "invalidation_level": tl_at_high,
        })

    return projections


def _is_invalidated(work: pd.DataFrame, proj: dict[str, Any], from_idx: int) -> bool:
    """Pattern invalid if candle closes across the trendline after structure forms."""
    slope = proj["slope"]
    intercept = proj["intercept"]
    setup = proj["setup"]
    for i in range(from_idx + 1, len(work)):
        tl = _trendline_price(slope, intercept, i)
        close = float(work["close"].iloc[i])
        if setup == SETUP_BEARISH and close > tl:
            return True
        if setup == SETUP_BULLISH and close < tl:
            return True
    return False


def _pick_active_projection(
    work: pd.DataFrame,
    projections: list[dict[str, Any]],
    cfg: SimpleStealConfig,
) -> dict[str, Any] | None:
    if not projections:
        return None
    n = len(work)
    candidates: list[tuple[float, dict[str, Any]]] = []
    close = float(work["close"].iloc[-1])

    for proj in reversed(projections):
        struct_idx = int(proj["structure_idx"])
        age = n - 1 - struct_idx
        if age > cfg.max_projection_age_bars or age < 0:
            continue
        if _is_invalidated(work, proj, struct_idx):
            continue

        target = float(proj["projected_target"])
        setup = proj["setup"]
        if setup == SETUP_BEARISH and close <= target:
            continue
        if setup == SETUP_BULLISH and close >= target:
            continue

        score = 100.0 - age
        candidates.append((score, proj))

    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def implement_simple_steal(df: pd.DataFrame, cfg: SimpleStealConfig) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    work = compute_bollinger_bands(df, cfg.bb_window, cfg.bb_std)
    bearish = get_bearish_projections(work, cfg)
    bullish = get_bullish_projections(work, cfg)
    all_proj = bearish + bullish
    all_proj.sort(key=lambda p: p.get("structure_idx", 0))
    return work, all_proj


def evaluate_live_signal(
    work: pd.DataFrame,
    projections: list[dict[str, Any]],
    cfg: SimpleStealConfig,
) -> dict[str, Any]:
    if work.empty or len(work) < cfg.min_bars:
        return {"signal": "NO_DATA"}

    i = len(work) - 1
    row = work.iloc[i]
    close = float(row["close"])
    active = _pick_active_projection(work, projections, cfg)
    tl_now: float | None = None

    reasons: list[str] = []
    conf = 18.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    phase = PHASE_NONE
    stop = close
    target = close
    setup_type = "—"

    bb_upper = float(row["bb_upper"]) if pd.notna(row.get("bb_upper")) else np.nan
    bb_lower = float(row["bb_lower"]) if pd.notna(row.get("bb_lower")) else np.nan
    bb_mid = float(row["bb_sma"]) if pd.notna(row.get("bb_sma")) else np.nan
    touch_upper = pd.notna(bb_upper) and float(row["high"]) >= bb_upper
    touch_lower = pd.notna(bb_lower) and float(row["low"]) <= bb_lower

    reasons.append(f"Bollinger Bands ({cfg.bb_window}, {cfg.bb_std}σ) — middle band = baseline reality")

    if active is None:
        verdict = "NO SETUP"
        reasons.append("No valid Little Rizzy projection in lookback — need lower-high or higher-low trendline structure")
    else:
        setup_type = active["setup"]
        target = float(active["projected_target"])
        struct_price = float(active["structure_price"])
        distance = float(active["distance"])
        struct_idx = int(active["structure_idx"])
        tl_now = _trendline_price(active["slope"], active["intercept"], i)

        if setup_type == SETUP_BEARISH:
            phase = PHASE_BEARISH
            stop = tl_now
            direction = "SHORT"
            reasons.append("Bearish Little Rizzy — descending trendline across bounce highs")
            reasons.append(
                f"Lowest low **{struct_price:,.4g}** under trendline · measured distance **{distance:,.4g}**"
            )
            reasons.append(f"Projected downside target **{target:,.4g}**")
            if touch_upper:
                conf += 16
                reasons.append("Price at/above upper BB — extended above reality, favors reversion down")
            elif cfg.prefer_bb_extreme and close > bb_mid:
                conf += 8
                reasons.append("Price above BB midline — monitor for fade toward projected target")
            if close > struct_price:
                verdict = "WATCH SHORT"
                conf += 14
                reasons.append("Structure low formed — watch for continuation toward projected bottom")
            else:
                verdict = "TAKE SHORT"
                conf += 24
                reasons.append("Price below structure low — measured-move leg may be active")
        else:
            phase = PHASE_BULLISH
            stop = tl_now
            direction = "LONG"
            reasons.append("Bullish Little Rizzy (inverse) — ascending trendline across pullback lows")
            reasons.append(
                f"Highest high **{struct_price:,.4g}** above trendline · measured distance **{distance:,.4g}**"
            )
            reasons.append(f"Projected upside target **{target:,.4g}**")
            if touch_lower:
                conf += 16
                reasons.append("Price at/below lower BB — stretched below reality, favors reversion up")
            elif cfg.prefer_bb_extreme and close < bb_mid:
                conf += 8
                reasons.append("Price below BB midline — monitor for push toward projected target")
            if close < struct_price:
                verdict = "WATCH LONG"
                conf += 14
                reasons.append("Structure high formed — watch for continuation toward projected top")
            else:
                verdict = "TAKE LONG"
                conf += 24
                reasons.append("Price above structure high — measured-move leg may be active")

        if _is_invalidated(work, active, struct_idx):
            phase = PHASE_INVALIDATED
            verdict = "INVALIDATED"
            direction = "WAIT"
            take = False
            conf = 20.0
            reasons.append("Close crossed trendline — pattern invalidated (use as hard stop reference)")

        remaining_pct = abs(target - close) / close * 100 if close else 0
        if remaining_pct < 1.5 and phase not in (PHASE_INVALIDATED,):
            phase = PHASE_TARGET_WATCH
            conf += 6
            reasons.append("Price near projected target — trim or wait for next structure")

        conf += max(0, 20 - (len(work) - 1 - struct_idx))

    conf = max(12.0, min(92.0, conf))
    take = (
        phase in (PHASE_BEARISH, PHASE_BULLISH)
        and verdict in ("TAKE SHORT", "TAKE LONG")
        and conf >= cfg.take_confidence_threshold
    )
    if take:
        phase = PHASE_ENTRY
    elif verdict in ("TAKE SHORT", "TAKE LONG"):
        # Gate failed (target already near, or confidence below threshold) — don't
        # display a TAKE verdict for a signal that isn't actually being taken.
        verdict = verdict.replace("TAKE", "WATCH")

    if direction == "SHORT" and stop > close:
        sl_pct = max(0.8, (stop - close) / close * 100)
        tp_pct = max(0.8, (close - target) / close * 100) if target < close else sl_pct * cfg.rr_ratio
    elif direction == "LONG" and stop < close:
        sl_pct = max(0.8, (close - stop) / close * 100)
        tp_pct = max(0.8, (target - close) / close * 100) if target > close else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 2.5
        tp_pct = sl_pct * cfg.rr_ratio

    hold = HOLD_SIMPLE_STEAL
    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule="SL on trendline close invalidation · TP at Little Rizzy projected measured-move target.",
        max_hold_exit="Exit within swing window if target not reached.",
    )

    return enrich_st_live({
        "signal": "SELL" if take and direction == "SHORT" else ("BUY" if take and direction == "LONG" else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "setup_type": setup_type,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(close, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "bb_upper": round(bb_upper, 6) if pd.notna(bb_upper) else None,
        "bb_lower": round(bb_lower, 6) if pd.notna(bb_lower) else None,
        "bb_mid": round(bb_mid, 6) if pd.notna(bb_mid) else None,
        "projected_target": round(target, 6) if active else None,
        "measured_distance": round(float(active["distance"]), 6) if active else None,
        "trendline_level": round(tl_now, 6) if active else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def _projection_history(projections: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in reversed(projections[-limit:]):
        ts = p.get("structure_low_date") or p.get("structure_high_date")
        rows.append({
            "Setup": p.get("setup", "—"),
            "Structure date": ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts),
            "Structure price": round(float(p.get("structure_price", 0)), 4),
            "Distance": round(float(p.get("distance", 0)), 4),
            "Projected target": round(float(p.get("projected_target", 0)), 4),
        })
    return rows


def fetch_simple_steal_data(
    ticker: str,
    market: str,
    cfg: SimpleStealConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    tf = cfg.execution_tf
    limit = cfg.lookback_bars

    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market),
        )
    if tf == EXEC_4H and (df.empty or len(df) < cfg.min_bars):
        h1 = fetch_data_for_gap_scan(ticker, "1h", market, groww_token, exchange, limit=limit * 2)
        h1 = normalize_ohlcv(h1)
        if h1.empty:
            h1 = normalize_ohlcv(
                fetch_ohlcv_yfinance(ticker, "1h", is_crypto=is_crypto, limit=limit * 2, market=market),
            )
        df = _resample_4h(h1)
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: SimpleStealConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SimpleStealConfig()
    df = fetch_simple_steal_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work, projections = implement_simple_steal(df, cfg)
    live = evaluate_live_signal(work, projections, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "projection_count": len(projections),
        "projection_history": _projection_history(projections),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: SimpleStealConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SimpleStealConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
