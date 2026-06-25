"""
intraday_alpha_945_engine.py
----------------------------
9:45 AM Intraday Alpha Scanner — Dhan / relative-strength breakout system.

Scan at 9:45 IST after opening noise settles; trade buy-stop above first 30m candle high.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from typing import Any

import numpy as np
import pandas as pd
import pytz

from app.trading_hubs.session_constants import (
    INDIA_MARKET_CLOSE,
    INDIA_MARKET_OPEN,
    IST_TZ,
    NY_TZ,
    _ist_time_on_date,
)
from app.market_pulse.gap_trading import _yfinance_symbol, fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_supertrend
from app.trading_hubs.intraday_shared import HOLD_ALPHA_945, enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_INTRA_ALPHA_URL = "http://www.youtube.com/watch?v=MfGUybW4O4c"

SCANNER_TIME_IST = time(9, 45)
OPENING_RANGE_MINUTES = 30

ST_COL = "supertrend_10_3.0"
ST_DIR = "supertrend_dir_10_3.0"


@dataclass
class Alpha945Config:
    min_mcap_cr: float = 5000.0
    min_volume: int = 1_000_000
    pct_change_min: float = 0.5
    pct_change_max: float = 1.5
    ema_period: int = 20
    rr_ratio: float = 2.0
    entry_buffer_pct: float = 0.01
    shadow_ratio_threshold: float = 0.45
    take_confidence_threshold: float = 62.0
    require_mcap: bool = True
    daily_lookback: int = 80
    min_daily_bars: int = 25


@dataclass
class ScannerFilters:
    mcap_cr: float | None = None
    volume: float = 0.0
    pct_change: float = 0.0
    above_ema20: bool = False
    above_supertrend: bool = False
    pass_mcap: bool = False
    pass_volume: bool = False
    pass_pct: bool = False
    pass_ema: bool = False
    pass_st: bool = False

    @property
    def all_passed(self) -> bool:
        checks = [self.pass_volume, self.pass_pct, self.pass_ema, self.pass_st]
        if self.pass_mcap is not False:
            checks.append(self.pass_mcap)
        return all(checks)


def _fetch_mcap_cr(ticker: str, market: str) -> float | None:
    try:
        import yfinance as yf

        sym = _yfinance_symbol(ticker, "CoinDCX" in market, market)
        mcap = yf.Ticker(sym).info.get("marketCap")
        if not mcap:
            return None
        return float(mcap) / 1e7
    except Exception as exc:
        logger.debug("mcap fetch %s: %s", ticker, exc)
        return None


def _ensure_ist_index(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV and express timestamps in IST (Groww/yfinance naive = UTC)."""
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    work = work.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(IST_TZ)
        return work
    hours = idx.hour
    max_h = int(hours.max())
    median_h = float(np.median(hours))
    # NSE in UTC is ~03:45–10:00; in IST ~09:15–15:30
    if max_h <= 11 and median_h < 8:
        work.index = idx.tz_localize("UTC").tz_convert(IST_TZ)
    else:
        work.index = idx.tz_localize(IST_TZ)
    return work


def _recent_ist_session_days(work: pd.DataFrame, max_days: int = 12) -> list[pd.Timestamp]:
    """IST dates with at least one bar inside regular NSE hours, most recent first."""
    days: list[pd.Timestamp] = []
    seen: set[object] = set()
    for ts in reversed(work.index):
        t = ts.time()
        if not (INDIA_MARKET_OPEN <= t <= INDIA_MARKET_CLOSE):
            continue
        day = ts.normalize()
        key = day.date()
        if key in seen:
            continue
        seen.add(key)
        days.append(day)
        if len(days) >= max_days:
            break
    return days


def _opening_range_bars(day_bars: pd.DataFrame, open_ts: pd.Timestamp, range_end: pd.Timestamp) -> pd.DataFrame:
    """Bars covering 09:15–09:45 IST (start- or period-end-labeled 30m)."""
    in_window = day_bars[(day_bars.index >= open_ts) & (day_bars.index < range_end)]
    if not in_window.empty:
        return in_window
    end_bar = day_bars[day_bars.index == range_end]
    if not end_bar.empty:
        return end_bar
    start_bar = day_bars[day_bars.index == open_ts]
    if len(start_bar) == 1:
        return start_bar
    return pd.DataFrame()


def _candle_dict_from_bars(
    bars: pd.DataFrame,
    session_day: pd.Timestamp,
    open_ts: pd.Timestamp,
    range_end: pd.Timestamp,
) -> dict[str, Any]:
    o = float(bars.iloc[0]["open"])
    h = float(bars["high"].max())
    l = float(bars["low"].min())
    c = float(bars.iloc[-1]["close"])
    vol = float(bars["volume"].sum()) if "volume" in bars.columns else 0.0
    body_low = min(o, c)
    body_high = max(o, c)
    shadow = body_low - l
    rng = h - l if h > l else 1e-9
    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "body_low": body_low,
        "body_high": body_high,
        "volume": vol,
        "shadow_size": shadow,
        "shadow_ratio": shadow / rng,
        "session_date": str(session_day.date()),
        "range_start": open_ts,
        "range_end": range_end,
    }


def _build_opening_range_for_day(work: pd.DataFrame, session_day: pd.Timestamp) -> dict[str, Any] | None:
    open_ts = _ist_time_on_date(session_day, INDIA_MARKET_OPEN)
    range_end = open_ts + pd.Timedelta(minutes=OPENING_RANGE_MINUTES)
    day_bars = work[work.index.normalize() == session_day.normalize()]
    if day_bars.empty:
        return None

    bars = _opening_range_bars(day_bars, open_ts, range_end)
    if not bars.empty:
        return _candle_dict_from_bars(bars, session_day, open_ts, range_end)

    # Resample finer intraday bars aligned to 09:15 IST session open
    resampled = (
        day_bars.resample(
            "30min",
            origin="start_day",
            offset=pd.Timedelta(hours=9, minutes=15),
        )
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    bars = _opening_range_bars(resampled, open_ts, range_end)
    if bars.empty:
        return None
    return _candle_dict_from_bars(bars, session_day, open_ts, range_end)


def _build_30m_from_intraday(df: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_ist_index(df)
    if work.empty:
        return work
    return work.resample(
        "30min",
        origin="start_day",
        offset=pd.Timedelta(hours=9, minutes=15),
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()


def get_opening_30m_candle(
    df_intraday: pd.DataFrame,
    session_day: pd.Timestamp | None = None,
) -> dict[str, Any] | None:
    """First 30-minute candle 09:15–09:45 IST (or aggregated from 5m/15m/30m)."""
    work = _ensure_ist_index(df_intraday)
    if work.empty:
        return None

    if session_day is not None:
        day = session_day.tz_convert(IST_TZ).normalize() if session_day.tzinfo else session_day.tz_localize(IST_TZ).normalize()
        return _build_opening_range_for_day(work, day)

    for day in _recent_ist_session_days(work):
        candle = _build_opening_range_for_day(work, day)
        if candle:
            return candle
    return None


def fetch_intraday_for_opening_range(
    ticker: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    """Fetch finest available intraday OHLCV for opening-range construction."""
    is_crypto = "CoinDCX" in market
    tf_priority = ("5m", "15m", "30m")
    best_tf = ""
    best_df = pd.DataFrame()
    for tf in tf_priority:
        df = normalize_ohlcv(
            fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=500 if tf == "5m" else 300),
        )
        if df.empty or len(df) < 3:
            df = normalize_ohlcv(
                fetch_ohlcv_yfinance(
                    ticker, tf, is_crypto=is_crypto, limit=500 if tf == "5m" else 300, market=market,
                ),
            )
        if df.empty:
            continue
        if not best_df.empty and tf_priority.index(tf) > tf_priority.index(best_tf):
            if get_opening_30m_candle(df):
                return df
            continue
        if best_df.empty or len(df) >= len(best_df):
            best_tf, best_df = tf, df
        if get_opening_30m_candle(df):
            return df
    return best_df


def _daily_indicators(daily: pd.DataFrame, cfg: Alpha945Config) -> pd.DataFrame:
    work = normalize_ohlcv(daily)
    work[f"ema_{cfg.ema_period}"] = work["close"].ewm(span=cfg.ema_period, adjust=False).mean()
    work = add_supertrend(work, period=10, multiplier=3.0)
    work["prev_close"] = work["close"].shift(1)
    return work


def run_scanner_filters(
    daily: pd.DataFrame,
    cfg: Alpha945Config,
    *,
    mcap_cr: float | None,
    session_volume: float | None = None,
) -> tuple[ScannerFilters, pd.Series]:
    work = _daily_indicators(daily, cfg)
    if work.empty:
        return ScannerFilters(), pd.Series(dtype=float)

    latest = work.iloc[-1]
    prev_close = float(latest["prev_close"]) if pd.notna(latest["prev_close"]) else float(latest["close"])
    close = float(latest["close"])
    vol = float(session_volume if session_volume is not None else latest.get("volume", 0))
    pct = (close - prev_close) / prev_close * 100 if prev_close else 0.0
    ema_col = f"ema_{cfg.ema_period}"
    ema_val = float(latest[ema_col]) if pd.notna(latest.get(ema_col)) else close
    st_val = float(latest[ST_COL]) if pd.notna(latest.get(ST_COL)) else close

    filt = ScannerFilters(
        mcap_cr=mcap_cr,
        volume=vol,
        pct_change=round(pct, 2),
        above_ema20=close > ema_val,
        above_supertrend=close >= st_val,
        pass_mcap=(mcap_cr is not None and mcap_cr > cfg.min_mcap_cr) if cfg.require_mcap else True,
        pass_volume=vol >= cfg.min_volume,
        pass_pct=cfg.pct_change_min <= pct <= cfg.pct_change_max,
        pass_ema=close > ema_val,
        pass_st=close >= st_val,
    )
    if not cfg.require_mcap and mcap_cr is None:
        filt.pass_mcap = True

    return filt, latest


def build_trade_plan_from_candle(
    candle: dict[str, Any],
    cfg: Alpha945Config,
    *,
    filters: ScannerFilters,
    reference_price: float,
) -> dict[str, Any]:
    high = float(candle["high"])
    low = float(candle["low"])
    body_low = float(candle["body_low"])
    shadow_ratio = float(candle.get("shadow_ratio", 0))

    entry = high * (1 + cfg.entry_buffer_pct / 100)
    if shadow_ratio > cfg.shadow_ratio_threshold:
        stop = body_low
        sl_type = "Body low (wide lower shadow)"
    else:
        stop = low
        sl_type = "Candle low (standard)"

    risk = entry - stop
    if risk <= 0:
        risk = entry * 0.008
        stop = entry - risk

    target = entry + risk * cfg.rr_ratio
    sl_pct = risk / reference_price * 100 if reference_price > 0 else 1.0
    tp_pct = (target - entry) / reference_price * 100 if reference_price > 0 else sl_pct * cfg.rr_ratio

    conf = 30.0
    reasons: list[str] = []
    if filters.pass_mcap:
        conf += 12
        reasons.append(f"Market cap ₹{filters.mcap_cr:,.0f} Cr > {cfg.min_mcap_cr:,.0f} Cr")
    if filters.pass_volume:
        conf += 15
        reasons.append(f"Volume {filters.volume:,.0f} ≥ {cfg.min_volume:,}")
    if filters.pass_pct:
        conf += 18
        reasons.append(f"Day change {filters.pct_change:+.2f}% in {cfg.pct_change_min}–{cfg.pct_change_max}% band")
    if filters.pass_ema:
        conf += 14
        reasons.append(f"Price above {cfg.ema_period} EMA (daily)")
    if filters.pass_st:
        conf += 14
        reasons.append("Price ≥ SuperTrend (10,3) — bullish")
    reasons.append(f"Buy stop above 9:15–9:45 high · SL: {sl_type}")

    conf = max(25.0, min(92.0, conf))
    take = filters.all_passed and conf >= cfg.take_confidence_threshold
    verdict = "TAKE LONG" if take else ("WATCH LONG" if filters.pass_ema and filters.pass_st else "WAIT")

    plan = make_trade_plan(
        direction="LONG" if take else "—",
        timeframe="30m",
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Trail after T1 (1:2); optional 1:3–1:4. Close before session end.",
        max_hold_exit="Exit remaining position by ~15:15 IST (avoid overnight gap risk).",
    )

    return enrich_intra_live({
        "signal": "BUY_STOP" if take else ("SETUP" if filters.pass_pct else "NONE"),
        "direction": "LONG",
        "take_trade": take,
        "verdict": verdict,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": HOLD_ALPHA_945,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "sl_type": sl_type,
        "opening_range": candle,
        "filters": {
            "mcap_cr": filters.mcap_cr,
            "volume": filters.volume,
            "pct_change": filters.pct_change,
            "pass_mcap": filters.pass_mcap,
            "pass_volume": filters.pass_volume,
            "pass_pct": filters.pass_pct,
            "pass_ema": filters.pass_ema,
            "pass_st": filters.pass_st,
            "all_passed": filters.all_passed,
        },
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD_ALPHA_945},
    }, hold_duration=HOLD_ALPHA_945)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: Alpha945Config | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Alpha945Config()
    is_crypto = "CoinDCX" in market
    is_india = "Groww" in market

    daily = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=cfg.daily_lookback)
    daily = normalize_ohlcv(daily)
    if daily.empty or len(daily) < cfg.min_daily_bars:
        daily = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=cfg.daily_lookback, market=market),
        )
    if daily.empty:
        return {"ticker": ticker, "error": "Insufficient daily OHLCV."}

    mcap_cr = _fetch_mcap_cr(ticker, market) if cfg.require_mcap or is_india else None

    intra = fetch_intraday_for_opening_range(
        ticker, market, groww_token=groww_token, exchange=exchange,
    )

    candle = get_opening_30m_candle(intra)
    if not candle:
        return {"ticker": ticker, "error": "Could not build 9:15–9:45 opening range candle."}

    filt, _ = run_scanner_filters(
        daily, cfg, mcap_cr=mcap_cr, session_volume=candle.get("volume"),
    )
    ref_price = float(daily["close"].iloc[-1])
    live = build_trade_plan_from_candle(candle, cfg, filters=filt, reference_price=ref_price)

    return {
        "ticker": ticker,
        "market": market,
        "last_close": ref_price,
        "mcap_cr": mcap_cr,
        "scanner_passed": filt.all_passed,
        "opening_candle": candle,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: Alpha945Config | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Alpha945Config()
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
        and r.get("scanner_passed")
    ]
    near = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and not r.get("scanner_passed")
        and sum(1 for k in ("pass_ema", "pass_st", "pass_pct") if (r.get("live") or {}).get("filters", {}).get(k)) >= 2
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "scan_time_ist": "09:45",
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "near_miss": near,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
