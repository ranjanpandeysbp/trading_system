"""
smb_snp_engine.py
-----------------
SMB — SnP "Fashionably Late" intraday momentum-reversal scalp.

9 EMA crosses up through VWAP after morning LOD grind; 3:1 R:R from LOD unit.
Video: https://www.youtube.com/watch?v=zm4ehSDIr0k&t=98s
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from typing import Any

import numpy as np
import pandas as pd

from app.trading_hubs.session_constants import (
    INDIA_MARKET_CLOSE,
    INDIA_MARKET_OPEN,
    IST_TZ,
    NY_TZ,
)
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_SMB_SNP_URL = "https://www.youtube.com/watch?v=zm4ehSDIr0k&t=98s"

EXEC_1M = "1m"
EXEC_5M = "5m"
EXEC_OPTIONS = [EXEC_1M, EXEC_5M]

PHASE_ENTRY = "CROSS_ENTRY"
PHASE_GRIND = "GRINDING_TO_VWAP"
PHASE_BELOW = "BELOW_VWAP"
PHASE_WINDOW = "OUTSIDE_WINDOW"
PHASE_NO_HTF = "HTF_FILTER_FAIL"
PHASE_NONE = "NO_SETUP"

HOLD_SMB_SNP = "Fashionably Late scalp · exit by session close (~15:15 IST / 4:00 PM ET)"

WINDOW_START = time(10, 0)
WINDOW_MORNING_END = time(10, 45)
WINDOW_MIDDAY_START = time(10, 46)
WINDOW_END = time(13, 30)

US_MARKET_OPEN = time(9, 30)
US_MARKET_CLOSE = time(16, 0)


@dataclass
class SmbSnpConfig:
    execution_tf: str = EXEC_5M
    ema_period: int = 9
    ema_slope_min_pct: float = 0.002
    min_rvol: float = 1.5
    require_htf_sma: bool = True
    take_confidence_threshold: float = 62.0
    chop_bars: int = 10
    chop_target_pct: float = 20.0
    daily_lookback: int = 30
    min_bars: int = 40
    rr_ratio: float = 3.0


def fetch_exec_data(
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


def _session_tz(market: str):
    if "Groww" in market:
        return IST_TZ
    if "CoinDCX" in market:
        return NY_TZ
    return NY_TZ


def _ensure_session_index(df: pd.DataFrame, market: str) -> pd.DataFrame:
    work = normalize_ohlcv(df).copy()
    if work.empty:
        return work
    tz = _session_tz(market)
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(tz)
    else:
        hours = idx.hour
        max_h = int(hours.max())
        median_h = float(np.median(hours))
        if "Groww" in market and max_h <= 11 and median_h < 8:
            work.index = idx.tz_localize("UTC").tz_convert(tz)
        else:
            work.index = idx.tz_localize(tz)
    return work


def _session_open_close(market: str) -> tuple[time, time]:
    if "Groww" in market:
        return INDIA_MARKET_OPEN, INDIA_MARKET_CLOSE
    return US_MARKET_OPEN, US_MARKET_CLOSE


def _in_trade_window(ts: pd.Timestamp, market: str) -> bool:
    ts = ts.tz_convert(_session_tz(market)) if ts.tz else ts.tz_localize(_session_tz(market))
    t = ts.time()
    in_morning = WINDOW_START <= t <= WINDOW_MORNING_END
    in_midday = WINDOW_MIDDAY_START <= t <= WINDOW_END
    return in_morning or in_midday


def _in_regular_session(ts: pd.Timestamp, market: str) -> bool:
    ts = ts.tz_convert(_session_tz(market)) if ts.tz else ts.tz_localize(_session_tz(market))
    open_t, close_t = _session_open_close(market)
    return open_t <= ts.time() <= close_t


def annotate_fashionably_late(df: pd.DataFrame, cfg: SmbSnpConfig, market: str) -> pd.DataFrame:
    """VWAP, 9 EMA, LOD, crossover signals (vectorized per session day)."""
    work = _ensure_session_index(df, market)
    if work.empty:
        return work

    session_dates = pd.Series(work.index.date, index=work.index)
    tp = (work["high"] + work["low"] + work["close"]) / 3.0
    vol = work["volume"].replace(0, np.nan).fillna(1.0)
    work["tp_vol"] = tp * vol
    work["cum_vol"] = work.groupby(session_dates)["volume"].transform(
        lambda s: s.replace(0, np.nan).fillna(1).cumsum(),
    )
    work["cum_tp_vol"] = work.groupby(session_dates)["tp_vol"].cumsum()
    work["vwap"] = work["cum_tp_vol"] / work["cum_vol"]
    work["ema9"] = work["close"].ewm(span=cfg.ema_period, adjust=False).mean()
    work["daily_low"] = work.groupby(session_dates)["low"].cummin()

    work["prev_ema9"] = work["ema9"].shift(1)
    work["prev_vwap"] = work["vwap"].shift(1)
    work["cross_up"] = (work["prev_ema9"] < work["prev_vwap"]) & (work["ema9"] > work["vwap"])
    work["ema_slope"] = work["ema9"].diff()
    slope_min = work["close"] * cfg.ema_slope_min_pct / 100.0
    work["slope_ok"] = work["ema_slope"] > slope_min
    work["in_window"] = work.index.map(lambda ts: _in_trade_window(ts, market))
    work["in_session"] = work.index.map(lambda ts: _in_regular_session(ts, market))
    work["signal"] = work["cross_up"] & work["in_window"] & work["in_session"] & work["slope_ok"]

    unit = np.where(work["signal"], work["vwap"] - work["daily_low"], np.nan)
    work["entry_price"] = np.where(work["signal"], work["vwap"], np.nan)
    work["unit"] = unit
    work["stop_loss"] = work["entry_price"] - (work["unit"] / cfg.rr_ratio)
    work["target"] = work["entry_price"] + work["unit"]
    return work


def _latest_session_day(work: pd.DataFrame, market: str) -> pd.Timestamp | None:
    if work.empty:
        return None
    days: list[pd.Timestamp] = []
    seen: set[object] = set()
    for ts in reversed(work.index):
        if not _in_regular_session(ts, market):
            continue
        day = ts.normalize()
        key = day.date()
        if key in seen:
            continue
        seen.add(key)
        days.append(day)
        if len(days) >= 1:
            break
    return days[0] if days else None


def _htf_context(daily: pd.DataFrame, session_volume: float, cfg: SmbSnpConfig) -> dict[str, Any]:
    if daily.empty or len(daily) < 12:
        return {
            "above_sma5": False,
            "above_sma10": False,
            "rvol": 0.0,
            "pass_htf": False,
            "sma5": None,
            "sma10": None,
            "avg_volume": 0.0,
        }
    close = float(daily["close"].iloc[-1])
    sma5 = float(daily["close"].rolling(5).mean().iloc[-1])
    sma10 = float(daily["close"].rolling(10).mean().iloc[-1])
    avg_vol = float(daily["volume"].tail(20).mean()) if "volume" in daily.columns else 0.0
    rvol = session_volume / avg_vol if avg_vol > 0 else 0.0
    above5 = close > sma5
    above10 = close > sma10
    pass_htf = True
    if cfg.require_htf_sma:
        pass_htf = above5 and above10
    if cfg.min_rvol > 0:
        pass_htf = pass_htf and rvol >= cfg.min_rvol
    return {
        "above_sma5": above5,
        "above_sma10": above10,
        "rvol": round(rvol, 2),
        "pass_htf": pass_htf,
        "sma5": round(sma5, 4),
        "sma10": round(sma10, 4),
        "avg_volume": avg_vol,
        "daily_close": close,
    }


def _chop_warning(work: pd.DataFrame, signal_idx: int, cfg: SmbSnpConfig) -> bool:
    """True when price fails to reach 20% of target within N bars after entry."""
    if signal_idx < 0 or signal_idx >= len(work) - 1:
        return False
    row = work.iloc[signal_idx]
    entry = float(row["entry_price"])
    target = float(row["target"])
    if not np.isfinite(entry) or not np.isfinite(target):
        return False
    dist = target - entry
    if dist <= 0:
        return False
    threshold = entry + dist * (cfg.chop_target_pct / 100.0)
    forward = work.iloc[signal_idx + 1 : signal_idx + 1 + cfg.chop_bars]
    if forward.empty:
        return False
    return float(forward["high"].max()) < threshold


def evaluate_live_signal(
    work: pd.DataFrame,
    cfg: SmbSnpConfig,
    market: str,
    *,
    htf: dict[str, Any] | None = None,
) -> dict[str, Any]:
    htf = htf or {}
    if work.empty:
        return enrich_intra_live({"signal": "NO_DATA", "verdict": "NO DATA", "phase": PHASE_NONE})

    session_day = _latest_session_day(work, market)
    if session_day is None:
        return enrich_intra_live({"signal": "NO_DATA", "verdict": "NO SESSION", "phase": PHASE_NONE})

    day_mask = work.index.normalize() == session_day
    session = work[day_mask & work["in_session"]]
    if session.empty:
        return enrich_intra_live({"signal": "NO_DATA", "verdict": "NO SESSION BARS", "phase": PHASE_NONE})

    last = session.iloc[-1]
    price = float(last["close"])
    vwap = float(last["vwap"])
    ema9 = float(last["ema9"])
    lod = float(last["daily_low"])
    in_window = bool(last["in_window"])

    signals = session[session["signal"]]
    latest_sig = signals.iloc[-1] if not signals.empty else None
    signal_idx = session.index.get_loc(latest_sig.name) if latest_sig is not None else -1

    reasons: list[str] = []
    conf = 35.0
    phase = PHASE_NONE
    take = False
    direction = "LONG"
    entry = stop = target = price
    unit = max(price - lod, 0.0)
    sl_pct = tp_pct = 0.0
    chop = False

    if htf.get("above_sma5"):
        conf += 10
        reasons.append(f"Daily close above 5 SMA ({htf.get('sma5')})")
    if htf.get("above_sma10"):
        conf += 10
        reasons.append(f"Daily close above 10 SMA ({htf.get('sma10')})")
    if htf.get("rvol", 0) >= cfg.min_rvol:
        conf += 12
        reasons.append(f"RVOL {htf.get('rvol')} ≥ {cfg.min_rvol}")
    elif cfg.min_rvol > 0:
        reasons.append(f"RVOL {htf.get('rvol', 0)} below {cfg.min_rvol} threshold")

    if latest_sig is not None:
        entry = float(latest_sig["entry_price"])
        stop = float(latest_sig["stop_loss"])
        target = float(latest_sig["target"])
        unit = float(latest_sig["unit"])
        chop = _chop_warning(session, signal_idx, cfg)
        phase = PHASE_ENTRY
        conf += 25
        reasons.append(
            f"9 EMA crossed up through VWAP at {latest_sig.name.strftime('%H:%M') if hasattr(latest_sig.name, 'strftime') else latest_sig.name}",
        )
        reasons.append(f"Unit (cross − LOD) = {unit:,.4g} · 3:1 R:R model")
        if chop:
            conf -= 15
            reasons.append(f"Chop warning: <{cfg.chop_target_pct}% of target in {cfg.chop_bars} bars")
        take = htf.get("pass_htf", True) and conf >= cfg.take_confidence_threshold and not chop
        verdict = "TAKE LONG" if take else "WATCH LONG"
    elif in_window and price < vwap and ema9 > lod and float(last["ema_slope"] or 0) > 0:
        phase = PHASE_GRIND
        conf += 15
        entry = vwap
        unit = max(vwap - lod, price - lod)
        stop = entry - unit / cfg.rr_ratio
        target = entry + unit
        reasons.append("Grinding up from LOD — awaiting 9 EMA × VWAP cross")
        verdict = "WATCH LONG"
    elif price < vwap:
        phase = PHASE_BELOW
        reasons.append("Below VWAP — morning supply not yet absorbed")
        verdict = "WAIT"
    elif not in_window:
        phase = PHASE_WINDOW
        reasons.append("Outside 10:00–13:30 liquidity window")
        verdict = "WAIT"
    else:
        phase = PHASE_BELOW
        verdict = "WAIT"
        reasons.append("No crossover trigger on latest session")

    if cfg.require_htf_sma and not htf.get("pass_htf"):
        take = False
        if phase == PHASE_ENTRY:
            phase = PHASE_NO_HTF
        verdict = "WAIT" if verdict == "WAIT" else "WATCH LONG"
        reasons.append("HTF filter: need daily 5/10 SMA + RVOL alignment")

    ref = price if price > 0 else 1.0
    risk = max(entry - stop, ref * 0.001)
    sl_pct = risk / ref * 100
    tp_pct = (target - entry) / ref * 100 if target > entry else sl_pct * cfg.rr_ratio
    conf = max(25.0, min(92.0, conf))

    plan = make_trade_plan(
        direction="LONG" if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="3:1 R:R — target = full LOD unit extension; SL = unit/3 below entry.",
        max_hold_exit="Exit by session close if target not hit.",
    )

    return enrich_intra_live({
        "signal": "BUY" if take else ("SETUP" if phase in (PHASE_GRIND, PHASE_ENTRY) else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": HOLD_SMB_SNP,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "vwap": round(vwap, 6),
        "ema9": round(ema9, 6),
        "lod": round(lod, 6),
        "unit": round(unit, 6),
        "in_window": in_window,
        "chop_warning": chop,
        "htf": htf,
        "execution_tf": cfg.execution_tf,
        "session_date": str(session_day.date()),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD_SMB_SNP},
    }, hold_duration=HOLD_SMB_SNP)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: SmbSnpConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SmbSnpConfig()
    is_crypto = "CoinDCX" in market

    df = fetch_exec_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data ({len(df)} bars)."}

    daily = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=cfg.daily_lookback)
    daily = normalize_ohlcv(daily)
    if daily.empty or len(daily) < 12:
        daily = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=cfg.daily_lookback, market=market),
        )

    work = annotate_fashionably_late(df, cfg, market)
    session_day = _latest_session_day(work, market)
    session_vol = 0.0
    if session_day is not None:
        day_bars = work[work.index.normalize() == session_day]
        session_vol = float(day_bars["volume"].sum()) if "volume" in day_bars.columns else 0.0

    htf = _htf_context(daily, session_vol, cfg)
    live = evaluate_live_signal(work, cfg, market, htf=htf)
    signals = work[work["signal"]]

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "signal_count": len(signals),
        "htf": htf,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: SmbSnpConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SmbSnpConfig()
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
        and (r.get("live") or {}).get("phase") in (PHASE_GRIND, PHASE_ENTRY, PHASE_BELOW)
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
