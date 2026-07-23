"""
sma_20_200_engine.py
------------------------
200SMA-20SMA — a trend-following bounce/rejection strategy built on just two
Simple Moving Averages, designed to be mechanical enough to remove emotional
and revenge trading from the decision.

Rules:
  - 200 SMA — baseline trend filter (floor in an uptrend, ceiling in a downtrend).
  - 20 SMA — dynamic support/resistance, direction given by its own slope.

  Long (Bounce): price above the 200 SMA, 20 SMA sloping up, and the current
  candle's Low dips to/below the 20 SMA while its Close finishes above it
  (rejected the touch, treating the average as support).

  Short (Rejection): price below the 200 SMA, 20 SMA sloping down, and the
  current candle's High pokes to/above the 20 SMA while its Close finishes
  below it (rejected the touch, treating the average as resistance).

  Stop-loss just beyond the 20 SMA; take-profit at a fixed 1:2 risk/reward
  (2R).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_sma
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

TIMEFRAME_OPTIONS = ["15m", "1h", "4h", "1d", "1w"]
_MIN_BARS = 220  # 200 SMA warmup + a working margin


@dataclass
class Sma20200Config:
    fast_period: int = 20
    slow_period: int = 200
    slope_lookback: int = 1
    rr_ratio: float = 2.0
    sl_buffer_pct: float = 0.1  # % beyond the 20 SMA, so the stop isn't glued to the exact average
    take_confidence_threshold: float = 55.0
    lookback_bars: int = 300
    recent_bars: int = 3  # a signal must be within this many bars of "now" to count as fresh


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market))
    return df


# ---------------------------------------------------------------------------
# Core scan — vectorized port of the video's mechanical bounce/rejection rules
# ---------------------------------------------------------------------------

def scan_sma_signals(df: pd.DataFrame, cfg: Sma20200Config | None = None) -> pd.DataFrame:
    """Adds sma_{fast}, sma_{slow}, sma_slope, and a signal column (1=LONG
    bounce, -1=SHORT rejection, 0=none) to a copy of df."""
    cfg = cfg or Sma20200Config()
    work = df.copy()
    work = add_sma(work, cfg.fast_period)
    work = add_sma(work, cfg.slow_period)
    fast_col, slow_col = f"sma_{cfg.fast_period}", f"sma_{cfg.slow_period}"
    work["sma_slope"] = work[fast_col] - work[fast_col].shift(cfg.slope_lookback)

    long_cond = (
        (work["close"] > work[slow_col]) & (work["sma_slope"] > 0)
        & (work["low"] <= work[fast_col]) & (work["close"] > work[fast_col])
    )
    short_cond = (
        (work["close"] < work[slow_col]) & (work["sma_slope"] < 0)
        & (work["high"] >= work[fast_col]) & (work["close"] < work[fast_col])
    )

    work["signal"] = 0
    work.loc[long_cond.fillna(False), "signal"] = 1
    work.loc[short_cond.fillna(False), "signal"] = -1
    return work


def _extract_signals(work: pd.DataFrame, cfg: Sma20200Config) -> list[dict[str, Any]]:
    fast_col, slow_col = f"sma_{cfg.fast_period}", f"sma_{cfg.slow_period}"
    signal_arr = work["signal"].to_numpy()
    positions = signal_arr.nonzero()[0]
    signals = []
    for pos in positions:
        row = work.iloc[pos]
        signals.append({
            "bar_index": int(pos),
            "timestamp": str(work.index[pos]),
            "direction": "LONG" if signal_arr[pos] == 1 else "SHORT",
            "close": float(row["close"]),
            "sma_fast": float(row[fast_col]),
            "sma_slow": float(row[slow_col]),
        })
    return signals


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_ticker(
    ticker: str, market: str, timeframe: str, *, cfg: Sma20200Config | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Sma20200Config()
    df = _fetch_ohlcv(ticker, market, timeframe, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars)
    if df is None or df.empty or len(df) < _MIN_BARS:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "error": f"Insufficient {timeframe} data ({0 if df is None else len(df)} bars, need {_MIN_BARS}+).",
        }

    work = scan_sma_signals(df, cfg)
    fast_col, slow_col = f"sma_{cfg.fast_period}", f"sma_{cfg.slow_period}"
    work_valid = work.dropna(subset=[slow_col, "sma_slope"])
    if work_valid.empty:
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "error": "Not enough clean SMA data after warmup."}

    all_signals = _extract_signals(work, cfg)
    last_idx = len(work) - 1
    last_row = work.iloc[-1]
    price = float(last_row["close"])
    sma_fast = float(last_row[fast_col]) if pd.notna(last_row[fast_col]) else None
    sma_slow = float(last_row[slow_col]) if pd.notna(last_row[slow_col]) else None
    slope = float(last_row["sma_slope"]) if pd.notna(last_row["sma_slope"]) else None

    trend_state = "—"
    if sma_slow is not None and slope is not None:
        if price > sma_slow and slope > 0:
            trend_state = f"Above {cfg.slow_period} SMA, {cfg.fast_period} SMA rising — bullish trend filter open"
        elif price < sma_slow and slope < 0:
            trend_state = f"Below {cfg.slow_period} SMA, {cfg.fast_period} SMA falling — bearish trend filter open"
        else:
            trend_state = f"Price/{cfg.fast_period} SMA slope disagree with the {cfg.slow_period} SMA baseline — no trade filter open"

    fresh_signals = [s for s in all_signals if last_idx - s["bar_index"] <= cfg.recent_bars]
    last_signal = fresh_signals[-1] if fresh_signals else None
    is_fresh = bool(last_signal and last_signal["bar_index"] == last_idx)

    reasons = [trend_state]
    verdict = "WAIT"
    direction = "WAIT"
    entry = stop = target = price
    confidence = 30.0

    if is_fresh:
        direction = last_signal["direction"]
        entry = last_signal["close"]
        sig_sma_fast = last_signal["sma_fast"]
        buf = sig_sma_fast * (cfg.sl_buffer_pct / 100.0)
        stop = sig_sma_fast - buf if direction == "LONG" else sig_sma_fast + buf
        risk = abs(entry - stop)
        target = entry + risk * cfg.rr_ratio if direction == "LONG" else entry - risk * cfg.rr_ratio
        confidence = 68.0
        verdict = direction
        reasons.append(
            f"{'Bounce' if direction == 'LONG' else 'Rejection'} off the {cfg.fast_period} SMA "
            f"({sig_sma_fast:.6g}) on the last completed candle — {'low dipped to it, closed above' if direction == 'LONG' else 'high poked it, closed below'}, "
            f"treating it as dynamic {'support' if direction == 'LONG' else 'resistance'}."
        )
        reasons.append(f"Stop just {'below' if direction == 'LONG' else 'above'} the {cfg.fast_period} SMA, target at a fixed 1:{cfg.rr_ratio:.0f} R:R.")
    elif last_signal:
        reasons.append(
            f"Most recent qualifying {last_signal['direction']} setup was {last_signal['timestamp']} "
            "— not the current candle, so no fresh trigger right now."
        )
    else:
        reasons.append(f"No {cfg.fast_period}/{cfg.slow_period} SMA bounce/rejection setup found in the fetched window.")

    take = is_fresh and confidence >= cfg.take_confidence_threshold
    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else sl_pct * cfg.rr_ratio

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=timeframe, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="swing" if timeframe in ("1d", "1w") else "intraday",
        exit_rule=f"Exit at the fixed 1:{cfg.rr_ratio:.0f} target, or on a close back through the {cfg.fast_period} SMA against the trade.",
        max_hold_exit=f"Trend-based — exit if price closes back through the {cfg.slow_period} SMA against the trade.",
    )
    hold = "Multiple bars — hold until 2R target or SMA invalidation"

    live = enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction, "take_trade": take, "verdict": verdict,
        "confidence_pct": confidence, "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "sma_fast": round(sma_fast, 6) if sma_fast is not None else None,
        "sma_slow": round(sma_slow, 6) if sma_slow is not None else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)

    day_high = day_low = day_bias = None
    try:
        from app.market_pulse.day_bias import ohlcv_bias
        from app.market_pulse.live_price import get_last_traded_price

        quote = get_last_traded_price(ticker, market, groww_token=groww_token, exchange=exchange)
        day_high, day_low = quote.get("day_high"), quote.get("day_low")
        day_bias = ohlcv_bias(df, price, day_high, day_low)
    except Exception:
        logger.debug("Day-range bias fetch failed for %s %s", ticker, timeframe, exc_info=True)

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe,
        "price": price, "signal_count": len(all_signals),
        "recent_signals": all_signals[-8:],
        "live": live,
        "day_high": day_high, "day_low": day_low, "day_bias": day_bias,
    }


def scan_universe(
    tickers: list[str], timeframes: list[str], market: str, *, cfg: Sma20200Config | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cfg = cfg or Sma20200Config()
    long_list: list[dict] = []
    short_list: list[dict] = []
    wait_list: list[dict] = []
    errors: list[dict] = []

    pairs = [(ticker, tf) for ticker in tickers for tf in timeframes]
    results: dict[tuple[str, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(analyze_ticker, ticker, market, tf, cfg=cfg, groww_token=groww_token, exchange=exchange): (ticker, tf)
            for ticker, tf in pairs
        }
        for future in as_completed(futures):
            ticker, tf = futures[future]
            try:
                results[(ticker, tf)] = future.result()
            except Exception as e:
                errors.append({"ticker": ticker, "timeframe": tf, "error": str(e)})

    for ticker, tf in pairs:
        res = results.get((ticker, tf))
        if res is None:
            continue
        if res.get("error"):
            errors.append({"ticker": ticker, "timeframe": tf, "error": res["error"]})
            continue
        live = res.get("live") or {}
        if live.get("take_trade") and live.get("direction") == "LONG":
            long_list.append(res)
        elif live.get("take_trade") and live.get("direction") == "SHORT":
            short_list.append(res)
        else:
            wait_list.append(res)

    long_list.sort(key=lambda r: -(r.get("live") or {}).get("confidence_pct", 0))
    short_list.sort(key=lambda r: -(r.get("live") or {}).get("confidence_pct", 0))
    return {"long": long_list, "short": short_list, "wait": wait_list, "errors": errors}
