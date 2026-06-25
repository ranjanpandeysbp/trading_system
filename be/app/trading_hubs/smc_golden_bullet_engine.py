"""
smc_golden_bullet_engine.py
-----------------------------
Golden Bullet Strategy — Liquidity Sweep + Kill-Zone Timing (Smart Money).

HTF BOS → extreme liquidity POI → London / NY-overlap kill zones →
V-shape sweep rejection → LTF structure alignment → 1:3 R:R entry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.trading_hubs.session_constants import NY_TZ
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_GOLDEN_BULLET_URL_1 = "https://www.youtube.com/watch?v=2vrb_LMQeW0"
YOUTUBE_GOLDEN_BULLET_URL_2 = "https://www.youtube.com/watch?v=wFo4UTOPbNo"

TF_OPTIONS = ["5m", "15m", "30m", "1h"]
HTF_OPTIONS = ["1h", "4h", "1d"]

PHASE_NONE = "NO_SETUP"
PHASE_KILLZONE = "IN_KILLZONE"
PHASE_SWEEP = "V_SHAPE_SWEEP"
PHASE_ENTRY = "GOLDEN_BULLET_ENTRY"

SIGNAL_HOLD = "Hold"
SIGNAL_BUY = "Buy"
SIGNAL_SELL = "Sell"

LONDON_OPEN_HOURS = (3, 6)      # 03:00–06:00 EST
NY_OVERLAP_HOURS = (8, 11)      # 08:00–11:00 EST


@dataclass
class GoldenBulletConfig:
    execution_tf: str = "15m"
    htf_tf: str = "1h"
    swing_window: int = 5
    pattern_pct: float = 0.001
    rr_ratio: float = 3.0
    take_confidence_threshold: float = 62.0
    require_htf_alignment: bool = True
    require_killzone: bool = True
    min_bars: int = 80
    lookback_bars: int = 500


@dataclass
class GoldenBulletSetup:
    direction: str
    phase: str
    liquidity_level: float
    entry_price: float
    stop_loss: float
    take_profit: float
    killzone: str
    bar_index: int


def _ensure_ny_index(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV and express bar timestamps in America/New_York (kill-zone clock)."""
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    work = work.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(NY_TZ)
        return work
    hours = idx.hour
    max_h = int(hours.max())
    median_h = float(np.median(hours))
    if max_h <= 11 and median_h < 8:
        work.index = idx.tz_localize("UTC").tz_convert(NY_TZ)
    else:
        work.index = idx.tz_localize(NY_TZ)
    return work


def _in_killzone(ts: pd.Timestamp) -> tuple[bool, str]:
    """London Open or London/NY overlap in EST."""
    local = ts.tz_convert(NY_TZ) if ts.tzinfo else ts.tz_localize(NY_TZ)
    h = local.hour
    if LONDON_OPEN_HOURS[0] <= h < LONDON_OPEN_HOURS[1]:
        return True, "London Open"
    if NY_OVERLAP_HOURS[0] <= h < NY_OVERLAP_HOURS[1]:
        return True, "London/NY Overlap"
    return False, ""


def _detect_swings(work: pd.DataFrame, swing_window: int) -> pd.DataFrame:
    out = work.copy()
    out["swing_high"] = np.nan
    out["swing_low"] = np.nan
    half = max(1, swing_window // 2)
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    for i in range(half, n - half):
        if highs[i] == highs[i - half : i + half + 1].max():
            out.iloc[i, out.columns.get_loc("swing_high")] = highs[i]
        if lows[i] == lows[i - half : i + half + 1].min():
            out.iloc[i, out.columns.get_loc("swing_low")] = lows[i]
    return out


def _htf_bias(df_htf: pd.DataFrame, swing_window: int = 5) -> dict[str, Any]:
    """Map HTF structure direction from recent BOS (break of structure)."""
    work = _detect_swings(normalize_ohlcv(df_htf), swing_window)
    if work.empty:
        return {"bias": "NEUTRAL", "bos": False, "extreme_high": None, "extreme_low": None}

    sh = work["swing_high"].dropna()
    sl = work["swing_low"].dropna()
    bias = "NEUTRAL"
    bos = False
    extreme_high = float(sh.iloc[-1]) if not sh.empty else None
    extreme_low = float(sl.iloc[-1]) if not sl.empty else None

    if len(sh) >= 2 and len(sl) >= 2:
        if sh.iloc[-1] > sh.iloc[-2] and sl.iloc[-1] > sl.iloc[-2]:
            bias = "LONG"
            bos = True
        elif sh.iloc[-1] < sh.iloc[-2] and sl.iloc[-1] < sl.iloc[-2]:
            bias = "SHORT"
            bos = True
        elif sh.iloc[-1] > sh.iloc[-2]:
            bias = "LONG"
        elif sl.iloc[-1] < sl.iloc[-2]:
            bias = "SHORT"

    close = float(work["close"].iloc[-1])
    return {
        "bias": bias,
        "bos": bos,
        "extreme_high": extreme_high,
        "extreme_low": extreme_low,
        "last_close": close,
    }


def _ltf_aligned(work: pd.DataFrame, direction: str, swing_window: int) -> bool:
    """Internal correction structure flips back toward HTF direction."""
    if work.empty or len(work) < swing_window * 3:
        return False
    tail = work.tail(swing_window * 4)
    if direction == "LONG":
        return float(tail["close"].iloc[-1]) > float(tail["close"].iloc[0])
    if direction == "SHORT":
        return float(tail["close"].iloc[-1]) < float(tail["close"].iloc[0])
    return False


def golden_bullet_strategy(
    df: pd.DataFrame,
    *,
    swing_window: int = 5,
    pattern_pct: float = 0.001,
    rr_ratio: float = 3.0,
    require_killzone: bool = True,
    htf_bias: str = "NEUTRAL",
    require_htf_alignment: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Golden Bullet scan on execution timeframe.

    Marks liquidity pools, kill-zone windows, V-shape sweeps, and sniper entries.
    """
    work = _ensure_ny_index(df)
    if work.empty:
        return work, {}

    work = _detect_swings(work, swing_window)
    work["signal"] = SIGNAL_HOLD
    work["entry_price"] = np.nan
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["setup_phase"] = PHASE_NONE
    work["killzone"] = ""
    work["liquidity_level"] = np.nan

    retail_double_tops: list[dict[str, Any]] = []
    retail_double_bottoms: list[dict[str, Any]] = []
    setups: list[GoldenBulletSetup] = []

    highs = work["high"].values
    lows = work["low"].values
    closes = work["close"].values
    swing_hi = work["swing_high"].values
    swing_lo = work["swing_low"].values

    for i in range(len(work)):
        current_idx = work.index[i]
        in_kz, kz_name = _in_killzone(current_idx)
        is_valid_timing = in_kz or not require_killzone

        if in_kz:
            work.at[current_idx, "setup_phase"] = PHASE_KILLZONE
            work.at[current_idx, "killzone"] = kz_name

        high_i = float(highs[i])
        low_i = float(lows[i])
        close_i = float(closes[i])

        # Bearish: V-shape sweep of equal-high liquidity pool
        if is_valid_timing and (not require_htf_alignment or htf_bias in ("SHORT", "NEUTRAL")):
            for top in retail_double_tops[:]:
                lvl = top["price"]
                if high_i > lvl and close_i <= lvl:
                    if require_htf_alignment and htf_bias == "NEUTRAL":
                        continue
                    sl = high_i + lvl * 0.0003
                    risk = sl - close_i
                    tp = close_i - rr_ratio * risk
                    work.at[current_idx, "signal"] = SIGNAL_SELL
                    work.at[current_idx, "entry_price"] = close_i
                    work.at[current_idx, "stop_loss"] = sl
                    work.at[current_idx, "take_profit"] = tp
                    work.at[current_idx, "setup_phase"] = PHASE_ENTRY
                    work.at[current_idx, "liquidity_level"] = lvl
                    setups.append(GoldenBulletSetup(
                        direction="SHORT",
                        phase=PHASE_ENTRY,
                        liquidity_level=lvl,
                        entry_price=close_i,
                        stop_loss=sl,
                        take_profit=tp,
                        killzone=kz_name or "off-session",
                        bar_index=i,
                    ))
                    retail_double_tops.remove(top)
                    break

        # Bullish: V-shape sweep of equal-low liquidity pool
        if is_valid_timing and (not require_htf_alignment or htf_bias in ("LONG", "NEUTRAL")):
            for bottom in retail_double_bottoms[:]:
                lvl = bottom["price"]
                if low_i < lvl and close_i >= lvl:
                    if require_htf_alignment and htf_bias == "NEUTRAL":
                        continue
                    sl = low_i - lvl * 0.0003
                    risk = close_i - sl
                    tp = close_i + rr_ratio * risk
                    work.at[current_idx, "signal"] = SIGNAL_BUY
                    work.at[current_idx, "entry_price"] = close_i
                    work.at[current_idx, "stop_loss"] = sl
                    work.at[current_idx, "take_profit"] = tp
                    work.at[current_idx, "setup_phase"] = PHASE_ENTRY
                    work.at[current_idx, "liquidity_level"] = lvl
                    setups.append(GoldenBulletSetup(
                        direction="LONG",
                        phase=PHASE_ENTRY,
                        liquidity_level=lvl,
                        entry_price=close_i,
                        stop_loss=sl,
                        take_profit=tp,
                        killzone=kz_name or "off-session",
                        bar_index=i,
                    ))
                    retail_double_bottoms.remove(bottom)
                    break

        # Map retail liquidity pools (equal highs / equal lows)
        if not np.isnan(swing_hi[i]):
            past_highs = work["swing_high"].iloc[:i].dropna()
            for val in past_highs.values:
                if abs(val - high_i) / val < pattern_pct:
                    retail_double_tops.append({"price": max(float(val), high_i), "idx": i})
                    if work.at[current_idx, "setup_phase"] == PHASE_NONE and is_valid_timing:
                        work.at[current_idx, "setup_phase"] = PHASE_SWEEP
                    break

        if not np.isnan(swing_lo[i]):
            past_lows = work["swing_low"].iloc[:i].dropna()
            for val in past_lows.values:
                if abs(val - low_i) / val < pattern_pct:
                    retail_double_bottoms.append({"price": min(float(val), low_i), "idx": i})
                    if work.at[current_idx, "setup_phase"] == PHASE_NONE and is_valid_timing:
                        work.at[current_idx, "setup_phase"] = PHASE_SWEEP
                    break

    state = {
        "retail_tops": len(retail_double_tops),
        "retail_bottoms": len(retail_double_bottoms),
        "setups": setups,
        "active_tops": retail_double_tops[-3:],
        "active_bottoms": retail_double_bottoms[-3:],
    }
    return work, state


def _active_live_state(work: pd.DataFrame, state: dict[str, Any]) -> dict[str, Any]:
    if work.empty:
        return {}
    in_kz, kz_name = _in_killzone(work.index[-1])
    phase = str(work["setup_phase"].iloc[-1])
    sig = str(work["signal"].iloc[-1])
    return {
        "in_killzone": in_kz,
        "killzone": kz_name,
        "phase": phase,
        "signal": sig,
        "liquidity_pools": state.get("retail_tops", 0) + state.get("retail_bottoms", 0),
        "active_tops": state.get("active_tops") or [],
        "active_bottoms": state.get("active_bottoms") or [],
    }


def evaluate_live_signal(
    work: pd.DataFrame,
    state: dict[str, Any],
    cfg: GoldenBulletConfig,
    *,
    htf: dict[str, Any] | None = None,
    reference_price: float | None = None,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = reference_price or float(work["close"].iloc[-1])
    live_st = _active_live_state(work, state)
    setups: list[GoldenBulletSetup] = state.get("setups") or []
    latest = setups[-1] if setups else None
    htf = htf or {}
    htf_bias = htf.get("bias", "NEUTRAL")

    reasons: list[str] = []
    conf = 22.0
    direction = "WAIT"
    phase = live_st.get("phase", PHASE_NONE)
    verdict = "WAIT"
    take = False
    stop = price
    target = price
    liq_level = None

    if htf.get("bos"):
        conf += 14
        reasons.append(f"HTF ({cfg.htf_tf}) Break of Structure — bias **{htf_bias}**")
    elif htf_bias != "NEUTRAL":
        conf += 8
        reasons.append(f"HTF ({cfg.htf_tf}) structure bias: **{htf_bias}**")

    if live_st.get("in_killzone"):
        conf += 18
        reasons.append(f"Inside kill zone: **{live_st.get('killzone')}** (institutional timing window)")
    elif not cfg.require_killzone:
        reasons.append("Kill-zone filter disabled — scan all sessions")
    else:
        reasons.append("Outside London / NY-overlap kill zones — execution forbidden by ruleset")

    pools = live_st.get("liquidity_pools", 0)
    if pools > 0:
        conf += 10
        reasons.append(f"Active liquidity pools mapped: **{pools}** equal-high/low inducements")

    if latest and latest.phase == PHASE_ENTRY:
        direction = latest.direction
        phase = PHASE_ENTRY
        verdict = f"TAKE {direction}"
        conf += 32
        stop = latest.stop_loss
        target = latest.take_profit
        liq_level = latest.liquidity_level
        reasons.append("V-shape sweep + close rejection at liquidity pool (Golden Bullet entry)")
        reasons.append(f"Strict **{cfg.rr_ratio}:1** R:R target")
    elif phase == PHASE_SWEEP:
        verdict = "WATCH — sweep forming"
        conf += 12
        reasons.append("Extreme POI trap forming — await V-shape rejection in kill zone")
        if htf_bias == "LONG":
            direction = "LONG"
        elif htf_bias == "SHORT":
            direction = "SHORT"
    elif phase == PHASE_KILLZONE and htf_bias != "NEUTRAL":
        verdict = f"WATCH {htf_bias}"
        direction = htf_bias
        conf += 10
        reasons.append("In kill zone with HTF bias — monitor liquidity sweep")

    if cfg.require_htf_alignment and direction in ("LONG", "SHORT"):
        if _ltf_aligned(work, direction, cfg.swing_window):
            conf += 12
            reasons.append("LTF internal structure aligned with HTF direction")
        elif phase == PHASE_ENTRY:
            conf -= 8
            reasons.append("LTF alignment weak — confirm structure flip on chart")

    conf = max(18.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold
    if cfg.require_killzone and not live_st.get("in_killzone") and phase != PHASE_ENTRY:
        take = False

    if direction == "LONG" and stop < price:
        sl_pct = max(0.35, (price - stop) / price * 100)
        tp_pct = max(0.5, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.35, (stop - price) / price * 100)
        tp_pct = max(0.5, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 1.0
        tp_pct = sl_pct * cfg.rr_ratio

    hold = hold_for_tf(cfg.execution_tf, "intraday" if cfg.execution_tf in ("5m", "15m", "30m") else "swing")
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Exit if sweep extreme is reclaimed or kill-zone thesis invalidates.",
        max_hold_exit=f"Time stop per {cfg.execution_tf} scalp/swing window.",
    )

    return enrich_smc_live({
        "signal": latest.direction if latest else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "liquidity_level": liq_level,
        "killzone": live_st.get("killzone") or "—",
        "in_killzone": live_st.get("in_killzone", False),
        "htf_bias": htf_bias,
        "htf_tf": cfg.htf_tf,
        "execution_tf": cfg.execution_tf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_tf_data(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 500,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: GoldenBulletConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or GoldenBulletConfig()
    ltf = fetch_tf_data(
        ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
    )
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    htf_df = fetch_tf_data(
        ticker, cfg.htf_tf, market, groww_token=groww_token, exchange=exchange, limit=300,
    )
    htf = _htf_bias(htf_df, cfg.swing_window) if not htf_df.empty else {"bias": "NEUTRAL"}

    work, state = golden_bullet_strategy(
        ltf,
        swing_window=cfg.swing_window,
        pattern_pct=cfg.pattern_pct,
        rr_ratio=cfg.rr_ratio,
        require_killzone=cfg.require_killzone,
        htf_bias=htf.get("bias", "NEUTRAL"),
        require_htf_alignment=cfg.require_htf_alignment,
    )
    live = evaluate_live_signal(work, state, cfg, htf=htf)
    entries = [s for s in (state.get("setups") or []) if s.phase == PHASE_ENTRY]

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "htf_tf": cfg.htf_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "entry_signals": len(entries),
        "htf": htf,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: GoldenBulletConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or GoldenBulletConfig()
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
        "htf_tf": cfg.htf_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
