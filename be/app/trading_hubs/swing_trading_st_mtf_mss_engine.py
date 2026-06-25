"""
swing_trading_st_mtf_mss_engine.py
----------------------------------
MTF Weekly Fakeout + 15m Market Structure Shift (MSS).

Pipeline:
  1. Weekly PWH / PWL (previous week high/low)
  2. Daily fakeout screen — wick beyond weekly boundary, close back inside
  3. 15m MSS execution — break of preceding swing after liquidity grab
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.swing_trading_st_shared import (
    HOLD_MTF_MSS,
    HOLD_MTF_WATCH,
    enrich_st_live,
)

logger = logging.getLogger(__name__)

YOUTUBE_ST_MTF_URL = "http://www.youtube.com/watch?v=Aq8_xZAFj0Q"

FAKEOUT_BEARISH = "bearish_fakeout"
FAKEOUT_BULLISH = "bullish_fakeout"


@dataclass
class MTFMSSConfig:
    swing_window: int = 3
    stop_buffer_pct: float = 0.001
    rr_ratio: float = 1.0
    max_fakeout_age_days: int = 3
    daily_lookback: int = 504
    min_daily_bars: int = 60
    mss_confidence_threshold: float = 62.0


def calculate_weekly_levels(df_weekly: pd.DataFrame) -> pd.DataFrame:
    """Previous week high/low shifted so the current week references last week's range."""
    w = df_weekly.copy()
    w["pwh"] = w["high"].shift(1)
    w["pwl"] = w["low"].shift(1)
    return w[["pwh", "pwl"]]


def build_weekly_from_daily(df_daily: pd.DataFrame) -> pd.DataFrame:
    if df_daily.empty:
        return pd.DataFrame()
    work = normalize_ohlcv(df_daily)
    return work.resample("W").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()


def screen_daily_fakeouts(df_daily: pd.DataFrame, weekly_levels: pd.DataFrame) -> pd.DataFrame:
    """Merge weekly boundaries and flag bearish/bullish daily fakeouts."""
    daily = normalize_ohlcv(df_daily)
    if daily.empty:
        return daily

    weekly = weekly_levels.copy()
    weekly["week_id"] = weekly.index.to_period("W").astype(str)
    daily = daily.copy()
    daily["week_id"] = daily.index.to_period("W").astype(str)
    levels = weekly.set_index("week_id")[["pwh", "pwl"]]
    df = daily.join(levels, on="week_id")

    pwh = df["pwh"]
    pwl = df["pwl"]
    df["bearish_fakeout"] = (df["high"] > pwh) & (df["close"] < pwh) & pwh.notna()
    df["bullish_fakeout"] = (df["low"] < pwl) & (df["close"] > pwl) & pwl.notna()
    return df


def _preceding_swing_low(df_before: pd.DataFrame, window: int) -> float | None:
    if len(df_before) < window:
        return None
    swings = df_before["low"].rolling(window=window, center=True).min()
    valid = swings.dropna()
    return float(valid.iloc[-1]) if not valid.empty else None


def _preceding_swing_high(df_before: pd.DataFrame, window: int) -> float | None:
    if len(df_before) < window:
        return None
    swings = df_before["high"].rolling(window=window, center=True).max()
    valid = swings.dropna()
    return float(valid.iloc[-1]) if not valid.empty else None


def find_market_structure_shift_short(
    df_15m: pd.DataFrame,
    pwh: float,
    cfg: MTFMSSConfig,
) -> dict[str, Any] | None:
    """15m bearish MSS after liquidity grab above PWH."""
    df = normalize_ohlcv(df_15m)
    if df.empty or not np.isfinite(pwh):
        return None

    outside = df[df["high"] > pwh]
    if outside.empty:
        return None

    peak_idx = outside["high"].idxmax()
    peak_high = float(outside["high"].max())
    df_before = df.loc[:peak_idx]
    swing_low = _preceding_swing_low(df_before, cfg.swing_window)
    if swing_low is None:
        return None

    df_after = df.loc[peak_idx:]
    for idx, row in df_after.iterrows():
        if float(row["close"]) < swing_low:
            entry = float(row["close"])
            stop = peak_high * (1 + cfg.stop_buffer_pct)
            risk = stop - entry
            if risk <= 0:
                continue
            target = entry - risk * cfg.rr_ratio
            return {
                "direction": "SHORT",
                "signal": "MSS_SHORT",
                "entry_price": entry,
                "stop_price": stop,
                "target_price": target,
                "peak_high": peak_high,
                "swing_low": swing_low,
                "pwh": pwh,
                "mss_time": idx,
                "risk": risk,
            }
    return None


def find_market_structure_shift_long(
    df_15m: pd.DataFrame,
    pwl: float,
    cfg: MTFMSSConfig,
) -> dict[str, Any] | None:
    """15m bullish MSS after liquidity grab below PWL."""
    df = normalize_ohlcv(df_15m)
    if df.empty or not np.isfinite(pwl):
        return None

    outside = df[df["low"] < pwl]
    if outside.empty:
        return None

    trough_idx = outside["low"].idxmin()
    trough_low = float(outside["low"].min())
    df_before = df.loc[:trough_idx]
    swing_high = _preceding_swing_high(df_before, cfg.swing_window)
    if swing_high is None:
        return None

    df_after = df.loc[trough_idx:]
    for idx, row in df_after.iterrows():
        if float(row["close"]) > swing_high:
            entry = float(row["close"])
            stop = trough_low * (1 - cfg.stop_buffer_pct)
            risk = entry - stop
            if risk <= 0:
                continue
            target = entry + risk * cfg.rr_ratio
            return {
                "direction": "LONG",
                "signal": "MSS_LONG",
                "entry_price": entry,
                "stop_price": stop,
                "target_price": target,
                "trough_low": trough_low,
                "swing_high": swing_high,
                "pwl": pwl,
                "mss_time": idx,
                "risk": risk,
            }
    return None


def _filter_15m_from_date(df_15m: pd.DataFrame, start_date: pd.Timestamp) -> pd.DataFrame:
    df = normalize_ohlcv(df_15m)
    if df.empty:
        return df
    start = pd.Timestamp(start_date).normalize()
    return df[df.index.normalize() >= start]


def _find_recent_fakeout(screened: pd.DataFrame, max_age: int) -> dict[str, Any] | None:
    if screened.empty:
        return None
    end = len(screened) - 1
    start = max(0, end - max_age)
    for i in range(end, start - 1, -1):
        row = screened.iloc[i]
        ts = screened.index[i]
        if bool(row.get("bearish_fakeout")):
            return {
                "type": FAKEOUT_BEARISH,
                "date": ts,
                "pwh": float(row["pwh"]),
                "pwl": float(row["pwl"]) if pd.notna(row.get("pwl")) else None,
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
            }
        if bool(row.get("bullish_fakeout")):
            return {
                "type": FAKEOUT_BULLISH,
                "date": ts,
                "pwh": float(row["pwh"]) if pd.notna(row.get("pwh")) else None,
                "pwl": float(row["pwl"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
            }
    return None


def _pct_distance(a: float, b: float) -> float:
    if b <= 0:
        return 0.0
    return abs(a - b) / b * 100


def _build_live_payload(
    *,
    fakeout: dict[str, Any] | None,
    mss: dict[str, Any] | None,
    cfg: MTFMSSConfig,
    latest_close: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    conf = 20.0
    direction = "WAIT"
    signal = "NONE"
    take = False
    verdict = "WAIT"

    if fakeout:
        ftype = fakeout["type"]
        fdate = fakeout["date"]
        reasons.append(f"Daily {ftype.replace('_', ' ')} on {fdate.strftime('%Y-%m-%d')}")
        conf += 28
        if ftype == FAKEOUT_BEARISH:
            direction = "SHORT"
            reasons.append(f"Wick above PWH {fakeout['pwh']:.4g} · close back below (trap)")
        else:
            direction = "LONG"
            reasons.append(f"Wick below PWL {fakeout['pwl']:.4g} · close back above (trap)")

    if mss:
        direction = mss["direction"]
        conf += 32
        reasons.append(
            f"15m MSS — close broke {'below swing low' if direction == 'SHORT' else 'above swing high'}"
        )
        if mss.get("mss_time") is not None:
            reasons.append(f"MSS bar: {pd.Timestamp(mss['mss_time']).strftime('%Y-%m-%d %H:%M')}")

    conf = max(20.0, min(92.0, conf))
    entry = latest_close
    stop = None
    target = None
    sl_pct = 3.0
    tp_pct = 3.0

    if mss:
        entry = float(mss["entry_price"])
        stop = float(mss["stop_price"])
        target = float(mss["target_price"])
        sl_pct = _pct_distance(entry, stop)
        tp_pct = _pct_distance(target, entry)
        signal = mss["signal"]
        if conf >= cfg.mss_confidence_threshold:
            take = True
            verdict = f"TAKE {direction}"
        else:
            verdict = f"WATCH {direction}"
    elif fakeout:
        signal = "FAKEOUT_WATCH"
        verdict = f"WATCH {direction}"
        if fakeout["type"] == FAKEOUT_BEARISH and fakeout.get("pwh"):
            stop = float(fakeout["high"]) * (1 + cfg.stop_buffer_pct)
            sl_pct = max(1.0, _pct_distance(entry, stop))
            target = entry - sl_pct * entry / 100 * cfg.rr_ratio
            tp_pct = sl_pct * cfg.rr_ratio
        elif fakeout["type"] == FAKEOUT_BULLISH and fakeout.get("pwl"):
            stop = float(fakeout["low"]) * (1 - cfg.stop_buffer_pct)
            sl_pct = max(1.0, _pct_distance(entry, stop))
            target = entry + sl_pct * entry / 100 * cfg.rr_ratio
            tp_pct = sl_pct * cfg.rr_ratio
        reasons.append("Awaiting 15m MSS on next session (post fakeout day)")

    hold_duration = HOLD_MTF_MSS if mss else HOLD_MTF_WATCH

    plan = make_trade_plan(
        direction=direction if take and direction not in ("EXIT", "WAIT") else "—",
        timeframe="15m",
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="; ".join(reasons[:2]) if reasons else "MTF fakeout MSS",
        max_hold_exit=f"Close if TP not hit within {hold_duration.split('(')[0].strip()}.",
    )

    return enrich_st_live({
        "signal": signal,
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold_duration,
        "rr_ratio": round(tp_pct / sl_pct, 2) if sl_pct > 0 else None,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6) if stop is not None else None,
        "target_price": round(target, 6) if target is not None else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration},
        "fakeout": fakeout,
        "mss": mss,
    }, hold_duration=hold_duration)


def fetch_daily_screened(
    ticker: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: MTFMSSConfig,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    daily = fetch_data_for_gap_scan(
        ticker, "1d", market, groww_token, exchange, limit=cfg.daily_lookback,
    )
    daily = normalize_ohlcv(daily)
    if daily.empty or len(daily) < cfg.min_daily_bars:
        daily = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=cfg.daily_lookback, market=market),
        )
    if daily.empty:
        return pd.DataFrame()

    weekly = build_weekly_from_daily(daily)
    levels = calculate_weekly_levels(weekly)
    return screen_daily_fakeouts(daily, levels)


def evaluate_mtf_mss(
    screened: pd.DataFrame,
    df_15m: pd.DataFrame,
    cfg: MTFMSSConfig,
) -> dict[str, Any]:
    fakeout = _find_recent_fakeout(screened, cfg.max_fakeout_age_days)
    mss = None

    if fakeout:
        window_15m = _filter_15m_from_date(df_15m, fakeout["date"])
        if fakeout["type"] == FAKEOUT_BEARISH:
            mss = find_market_structure_shift_short(window_15m, fakeout["pwh"], cfg)
        else:
            mss = find_market_structure_shift_long(window_15m, fakeout["pwl"], cfg)

    latest_close = float(screened["close"].iloc[-1]) if not screened.empty else 0.0
    return _build_live_payload(fakeout=fakeout, mss=mss, cfg=cfg, latest_close=latest_close)


def _fakeout_history(screened: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(len(screened) - 1, -1, -1):
        row = screened.iloc[i]
        ts = screened.index[i]
        kind = None
        if bool(row.get("bearish_fakeout")):
            kind = "Bearish"
        elif bool(row.get("bullish_fakeout")):
            kind = "Bullish"
        if kind:
            rows.append({
                "date": ts.strftime("%Y-%m-%d"),
                "type": kind,
                "pwh": round(float(row["pwh"]), 4) if pd.notna(row.get("pwh")) else None,
                "pwl": round(float(row["pwl"]), 4) if pd.notna(row.get("pwl")) else None,
                "close": round(float(row["close"]), 4),
            })
        if len(rows) >= limit:
            break
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: MTFMSSConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MTFMSSConfig()
    screened = fetch_daily_screened(ticker, market, groww_token=groww_token, exchange=exchange, cfg=cfg)
    if screened.empty or len(screened) < cfg.min_daily_bars:
        return {"ticker": ticker, "error": "Insufficient daily OHLCV for weekly fakeout screen."}

    df_15m = fetch_data_for_gap_scan(ticker, "15m", market, groww_token, exchange, limit=300)
    df_15m = normalize_ohlcv(df_15m)

    live = evaluate_mtf_mss(screened, df_15m, cfg)
    latest = screened.iloc[-1]

    return {
        "ticker": ticker,
        "market": market,
        "bars_daily": len(screened),
        "bars_15m": len(df_15m),
        "last_close": float(latest["close"]),
        "current_pwh": float(latest["pwh"]) if pd.notna(latest.get("pwh")) else None,
        "current_pwl": float(latest["pwl"]) if pd.notna(latest.get("pwl")) else None,
        "latest_bearish_fakeout": bool(latest.get("bearish_fakeout")),
        "latest_bullish_fakeout": bool(latest.get("bullish_fakeout")),
        "fakeout_history": _fakeout_history(screened),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: MTFMSSConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MTFMSSConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [
        r for r in results
        if not r.get("error") and (r.get("live") or {}).get("take_trade")
    ]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (
            (r.get("live") or {}).get("fakeout")
            or (r.get("live") or {}).get("signal") == "FAKEOUT_WATCH"
        )
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
