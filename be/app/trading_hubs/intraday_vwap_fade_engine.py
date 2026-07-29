"""
intraday_vwap_fade_engine.py
----------------------------
VWAP Fade Value Area Extremes (Setup #2) — mean reversion at ±1σ bands.

Video: "The Only VWAP Strategy I Use Every Day" — range days only; fade band rejections to VWAP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.trading_hubs.session_constants import IST_TZ
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import HOLD_VWAP_FADE, enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_INTRA_VWAP_FADE_URL = "http://www.youtube.com/watch?v=Z2uJRbkb2pA"

EXEC_1M = "1m"
EXEC_5M = "5m"
EXEC_OPTIONS = [EXEC_1M, EXEC_5M]
MTF_OPTIONS = ["15m", "30m"]

PHASE_TREND = "TRENDING"
PHASE_RANGE = "RANGE_DAY"
PHASE_REJECT = "BAND_REJECTION"
PHASE_ENTRY = "VWAP_FADE_ENTRY"
PHASE_NONE = "NO_SETUP"

INDIA_SESSION_OPEN = (9, 15)

_PANDAS_RESAMPLE_RULE = {
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "4h": "4h", "1d": "1D", "1wk": "1W", "1M": "1ME",
}


def _resample_rule(tf: str) -> str:
    """App timeframe strings ("15m") aren't valid pandas resample offset
    aliases in recent pandas (bare "m" now means month-end, not minutes)."""
    return _PANDAS_RESAMPLE_RULE.get(tf, tf)


@dataclass
class VwapFadeConfig:
    execution_tf: str = EXEC_5M
    bias_tf: str = "15m"
    use_mtf: bool = True
    std_dev_mult: float = 1.0
    skip_open_minutes: int = 15
    time_stop_minutes: int = 60
    sl_buffer_pct: float = 0.05
    range_outside_max_pct: float = 0.25
    take_confidence_threshold: float = 62.0
    min_bars: int = 50


def fetch_exec_data(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market)
        )
    return df


def calculate_vwap_and_bands(df: pd.DataFrame, std_mult: float = 1.0) -> pd.DataFrame:
    """Intraday VWAP and ±1 standard deviation value-area bands (reset daily)."""
    work = normalize_ohlcv(df).copy()
    if work.empty:
        return work

    if work.index.tz is None:
        work.index = work.index.tz_localize(IST_TZ)
    else:
        work.index = work.index.tz_convert(IST_TZ)

    work["_grp_date"] = work.index.date
    tp = (work["high"] + work["low"] + work["close"]) / 3.0
    vol = work["volume"].replace(0, np.nan).fillna(1.0)
    work["tp_vol"] = tp * vol
    work["cum_vol"] = work.groupby("_grp_date")["volume"].transform(
        lambda s: s.replace(0, np.nan).fillna(1).cumsum()
    )
    work["cum_tp_vol"] = work.groupby("_grp_date")["tp_vol"].cumsum()
    work["vwap"] = work["cum_tp_vol"] / work["cum_vol"]

    work["sq_diff"] = (work["close"] - work["vwap"]) ** 2
    work["cum_sq_diff"] = work.groupby("_grp_date")["sq_diff"].cumsum()
    n = work.groupby("_grp_date").cumcount() + 1
    work["std_dev"] = np.sqrt(work["cum_sq_diff"] / n)
    work["upper_band"] = work["vwap"] + std_mult * work["std_dev"]
    work["lower_band"] = work["vwap"] - std_mult * work["std_dev"]
    return work


def _minutes_since_session_open(ts: pd.Timestamp, market: str) -> float:
    ts = ts.tz_convert(IST_TZ) if ts.tz else ts.tz_localize(IST_TZ)
    if "Groww" in market:
        open_h, open_m = INDIA_SESSION_OPEN
        session_open = ts.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
        if ts < session_open:
            return 0.0
        return (ts - session_open).total_seconds() / 60.0
    day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return (ts - day_start).total_seconds() / 60.0


def _is_range_day(work: pd.DataFrame, cfg: VwapFadeConfig) -> tuple[bool, float]:
    """True when price mostly stays inside ±1σ bands (not trending outside)."""
    if work.empty or len(work) < 20:
        return False, 0.0
    recent = work.tail(min(60, len(work)))
    outside = (
        (recent["close"] > recent["upper_band"])
        | (recent["close"] < recent["lower_band"])
    )
    pct_out = float(outside.sum()) / len(recent)
    return pct_out <= cfg.range_outside_max_pct, pct_out


def _wick_rejection(row: pd.Series, side: str) -> bool:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body = abs(c - o)
    if side == "short":
        upper_wick = h - max(o, c)
        return upper_wick > body and body > 0
    lower_wick = min(o, c) - l
    return lower_wick > body and body > 0


def backtest_vwap_fade_strategy(df: pd.DataFrame, cfg: VwapFadeConfig, market: str) -> pd.DataFrame:
    """Annotate bars with VWAP fade signals (simplified state engine)."""
    work = calculate_vwap_and_bands(df, cfg.std_dev_mult)
    if work.empty:
        return work

    work["signal"] = 0
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["in_skip_window"] = False

    in_position = False
    position_type = ""
    entry_idx = 0
    stop_loss_price = take_profit_price = 0.0

    tf_minutes = 1 if cfg.execution_tf == EXEC_1M else 5

    for i in range(1, len(work)):
        ts = work.index[i]
        mins = _minutes_since_session_open(ts, market)
        if mins < cfg.skip_open_minutes:
            work.at[work.index[i], "in_skip_window"] = True
            continue

        if in_position:
            elapsed = (i - entry_idx) * tf_minutes
            h, l = float(work["high"].iloc[i]), float(work["low"].iloc[i])
            exit_sig = 0
            if position_type == "short":
                if h >= stop_loss_price:
                    exit_sig = 2
                elif l <= take_profit_price:
                    exit_sig = 2
                elif elapsed >= cfg.time_stop_minutes:
                    exit_sig = 2
            elif position_type == "long":
                if l <= stop_loss_price:
                    exit_sig = -2
                elif h >= take_profit_price:
                    exit_sig = -2
                elif elapsed >= cfg.time_stop_minutes:
                    exit_sig = -2
            if exit_sig:
                work.at[work.index[i], "signal"] = exit_sig
                in_position = False
            continue

        range_ok, _ = _is_range_day(work.iloc[: i + 1], cfg)
        if not range_ok:
            continue

        row = work.iloc[i]
        ub, lb, vwap = float(row["upper_band"]), float(row["lower_band"]), float(row["vwap"])
        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])

        if h >= ub and c < ub and _wick_rejection(row, "short"):
            in_position = True
            position_type = "short"
            entry_idx = i
            stop_loss_price = h * (1 + cfg.sl_buffer_pct / 100)
            take_profit_price = vwap
            work.at[work.index[i], "signal"] = -1
            work.at[work.index[i], "stop_loss"] = stop_loss_price
            work.at[work.index[i], "take_profit"] = take_profit_price

        elif l <= lb and c > lb and _wick_rejection(row, "long"):
            in_position = True
            position_type = "long"
            entry_idx = i
            stop_loss_price = l * (1 - cfg.sl_buffer_pct / 100)
            take_profit_price = vwap
            work.at[work.index[i], "signal"] = 1
            work.at[work.index[i], "stop_loss"] = stop_loss_price
            work.at[work.index[i], "take_profit"] = take_profit_price

    return work


def _htf_range_ok(
    df_exec: pd.DataFrame,
    cfg: VwapFadeConfig,
    market: str,
) -> dict[str, Any]:
    if not cfg.use_mtf or cfg.bias_tf == cfg.execution_tf:
        return {"range_ok": True, "outside_pct": 0.0}
    work = normalize_ohlcv(df_exec)
    if work.empty:
        return {"range_ok": False, "outside_pct": 1.0}
    if work.index.tz is None:
        work.index = work.index.tz_localize(IST_TZ)
    else:
        work.index = work.index.tz_convert(IST_TZ)
    resampled = work.resample(_resample_rule(cfg.bias_tf)).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()
    if len(resampled) < 10:
        return {"range_ok": True, "outside_pct": 0.0}
    htf = calculate_vwap_and_bands(resampled, cfg.std_dev_mult)
    ok, pct = _is_range_day(htf, cfg)
    return {"range_ok": ok, "outside_pct": pct, "bars": len(htf)}


def evaluate_live_signal(
    work: pd.DataFrame,
    cfg: VwapFadeConfig,
    market: str,
    *,
    htf: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = float(work["close"].iloc[-1])
    row = work.iloc[-1]
    vwap = float(row["vwap"]) if pd.notna(row["vwap"]) else price
    ub = float(row["upper_band"]) if pd.notna(row["upper_band"]) else price * 1.01
    lb = float(row["lower_band"]) if pd.notna(row["lower_band"]) else price * 0.99
    latest_sig = int(row["signal"]) if pd.notna(row["signal"]) else 0

    ts = work.index[-1]
    mins = _minutes_since_session_open(ts, market)
    in_skip = mins < cfg.skip_open_minutes

    range_ok, outside_pct = _is_range_day(work, cfg)
    reasons: list[str] = []
    conf = 24.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    stop = price
    target = vwap

    if in_skip:
        reasons.append(f"Skip window — first {cfg.skip_open_minutes} min after open (no fade trades)")
        phase = PHASE_NONE
    elif not range_ok:
        phase = PHASE_TREND
        verdict = "AVOID"
        reasons.append(f"Trend day filter — {outside_pct:.0%} closes outside ±1σ bands (fade disabled)")
    else:
        phase = PHASE_RANGE
        conf += 18
        reasons.append("Range day — price respecting VWAP value area (±1σ)")
        if htf and cfg.use_mtf:
            if htf.get("range_ok"):
                conf += 12
                reasons.append(f"HTF ({cfg.bias_tf}) also range-bound")
            else:
                conf -= 15
                reasons.append(f"HTF ({cfg.bias_tf}) trending — caution on fades")

        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
        short_reject = h >= ub and c < ub and _wick_rejection(row, "short")
        long_reject = l <= lb and c > lb and _wick_rejection(row, "long")

        if latest_sig == -1 or short_reject:
            direction = "SHORT"
            phase = PHASE_ENTRY if latest_sig == -1 else PHASE_REJECT
            verdict = "TAKE SHORT" if latest_sig == -1 else "WATCH SHORT"
            conf += 28
            stop = h * (1 + cfg.sl_buffer_pct / 100)
            target = vwap
            reasons.append("Upper band rejection — fade short toward VWAP")
            reasons.append("Wick > body at value area extreme")
        elif latest_sig == 1 or long_reject:
            direction = "LONG"
            phase = PHASE_ENTRY if latest_sig == 1 else PHASE_REJECT
            verdict = "TAKE LONG" if latest_sig == 1 else "WATCH LONG"
            conf += 28
            stop = l * (1 - cfg.sl_buffer_pct / 100)
            target = vwap
            reasons.append("Lower band rejection — fade long toward VWAP")
            reasons.append("Wick > body at value area extreme")
        else:
            dist_ub = (ub - price) / price * 100
            dist_lb = (price - lb) / price * 100
            reasons.append(f"VWAP {vwap:,.4g} · upper {ub:,.4g} · lower {lb:,.4g}")
            if dist_ub < 0.35:
                reasons.append("Approaching upper band — watch for rejection")
            elif dist_lb < 0.35:
                reasons.append("Approaching lower band — watch for rejection")

    conf = max(15.0, min(90.0, conf))
    take = (
        not in_skip
        and range_ok
        and phase in (PHASE_ENTRY, PHASE_REJECT)
        and direction in ("LONG", "SHORT")
        and (latest_sig != 0 or phase == PHASE_REJECT)
        and conf >= cfg.take_confidence_threshold
        and (not htf or not cfg.use_mtf or htf.get("range_ok", True))
    )
    if phase == PHASE_REJECT:
        take = False
        verdict = verdict.replace("TAKE", "WATCH")

    if direction == "LONG" and stop < price:
        sl_pct = max(0.2, (price - stop) / price * 100)
        tp_pct = max(0.15, (target - price) / price * 100) if target > price else sl_pct
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.2, (stop - price) / price * 100)
        tp_pct = max(0.15, (price - target) / price * 100) if target < price else sl_pct
    else:
        sl_pct = 0.5
        tp_pct = 0.4

    hold = f"{HOLD_VWAP_FADE} ({cfg.time_stop_minutes} min time stop)"
    plan_dir = direction if take and direction in ("LONG", "SHORT") else "—"
    plan = make_trade_plan(
        direction=plan_dir,
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule=f"Target VWAP mean · SL beyond rejection wick · {cfg.time_stop_minutes}m time stop.",
        max_hold_exit=f"Close at market if target not hit within {cfg.time_stop_minutes} minutes.",
    )

    return enrich_intra_live({
        "signal": "BUY" if latest_sig == 1 or (take and direction == "LONG") else (
            "SELL" if latest_sig == -1 or (take and direction == "SHORT") else "NONE"
        ),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "vwap": round(vwap, 6),
        "upper_band": round(ub, 6),
        "lower_band": round(lb, 6),
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf if cfg.use_mtf else None,
        "range_day": range_ok,
        "outside_band_pct": round(outside_pct * 100, 1),
        "skip_window": in_skip,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: VwapFadeConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or VwapFadeConfig()
    df = fetch_exec_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work = backtest_vwap_fade_strategy(df, cfg, market)
    htf = _htf_range_ok(df, cfg, market)
    live = evaluate_live_signal(work, cfg, market, htf=htf)

    signals = work[work["signal"].isin([1, -1])]
    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf if cfg.use_mtf else None,
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
    cfg: VwapFadeConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or VwapFadeConfig()
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
        and (r.get("live") or {}).get("phase") in (PHASE_RANGE, PHASE_REJECT)
        and (r.get("live") or {}).get("direction") in ("LONG", "SHORT", "WAIT")
    ]
    avoids = [r for r in results if not r.get("error") and (r.get("live") or {}).get("phase") == PHASE_TREND]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "trending": avoids,
        "entry_count": len(entries),
        "watch_count": len(watches),
        "avoid_count": len(avoids),
    }
