"""
intraday_7_wasted_engine.py
----------------------------
5-Minute Opening Range Breakout & Retest — Break and Retest framework.

Direction (liquidity) + Location (MTF): Daily bias · 1m execution on 5m OR high retest.
Video: https://www.youtube.com/watch?v=Bl0CQnhSbgo
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.session_constants import (
    INDIA_MARKET_CLOSE,
    INDIA_MARKET_OPEN,
    IST_TZ,
    NY_TZ,
)

logger = logging.getLogger(__name__)

YOUTUBE_INTRA_7_WASTED_URL = "https://www.youtube.com/watch?v=Bl0CQnhSbgo&t=12s"

EXEC_TF = "1m"
OR_MINUTES_DEFAULT = 5

PHASE_NONE = "NO_SETUP"
PHASE_WAIT_OR = "WAIT_OPENING_RANGE"
PHASE_OR_DEFINED = "OR_DEFINED"
PHASE_BREAKOUT = "BREAKOUT"
PHASE_RETEST = "RETEST_ARMED"
PHASE_ENTRY = "OR_RETEST_ENTRY"

SIGNAL_BUY = 1

HOLD_7_WASTED = "5m OR breakout-retest · 1:2 R:R · exit by session end"

# Local copies of truebacktesting.scalp_sr_mss_engine session helpers (and
# fakeout_4h_engine.session_mode_for_market) — those modules have not been
# ported/available to this backend build, so these are kept self-contained
# here rather than editing shared modules.


def session_mode_for_market(market: str) -> str:
    """Groww India stocks -> IST session; CoinDCX / others -> NY session."""
    if "Groww" in market or "India" in market:
        return "india"
    return "ny"


SESSION_OPEN_BY_MODE: dict[str, time] = {
    "india": INDIA_MARKET_OPEN,  # 09:15 IST
    "ny": time(9, 30),           # 09:30 US/Eastern (Groww US-style / CoinDCX NY)
}

SESSION_CLOSE_BY_MODE: dict[str, time] = {
    "india": INDIA_MARKET_CLOSE,
    "ny": time(16, 0),
}


def _session_tz(mode: str):
    return IST_TZ if mode == "india" else NY_TZ


def _ensure_market_tz(df: pd.DataFrame, market: str) -> pd.DataFrame:
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    mode = session_mode_for_market(market)
    tz = _session_tz(mode)
    work = work.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(tz)
    else:
        hours = idx.hour
        max_h = int(hours.max())
        median_h = float(np.median(hours))
        if mode == "india" and max_h <= 11 and median_h < 8:
            work.index = idx.tz_localize("UTC").tz_convert(tz)
        else:
            work.index = idx.tz_localize(tz)
    return work


@dataclass
class Intra7WastedConfig:
    or_minutes: int = OR_MINUTES_DEFAULT
    rr_ratio: float = 2.0
    sl_buffer: float = 0.02
    take_confidence_threshold: float = 58.0
    require_daily_bullish: bool = True
    lookback_bars: int = 500
    min_bars: int = 30


def _session_open_time(market: str) -> time:
    mode = session_mode_for_market(market)
    return SESSION_OPEN_BY_MODE.get(mode, time(9, 30))


def _session_close_time(market: str) -> time:
    mode = session_mode_for_market(market)
    return SESSION_CLOSE_BY_MODE.get(mode, time(16, 0))


def _in_regular_session(ts: pd.Timestamp, market: str) -> bool:
    mode = session_mode_for_market(market)
    tz = _session_tz(mode)
    ts = ts.tz_convert(tz) if ts.tz else ts.tz_localize(tz)
    open_t = _session_open_time(market)
    close_t = _session_close_time(market)
    return open_t <= ts.time() <= close_t


def _daily_trend_and_prev_levels(df_1d: pd.DataFrame) -> tuple[str, float | None, float | None]:
    if df_1d is None or df_1d.empty:
        return "neutral", None, None
    work = normalize_ohlcv(df_1d)
    if len(work) < 2:
        last = work.iloc[-1]
        o, c = float(last["open"]), float(last["close"])
        trend = "bullish" if c > o else ("bearish" if c < o else "neutral")
        return trend, None, None
    prev = work.iloc[-2]
    last = work.iloc[-1]
    o, c = float(last["open"]), float(last["close"])
    if c > o:
        trend = "bullish"
    elif c < o:
        trend = "bearish"
    else:
        trend = "neutral"
    return trend, float(prev["high"]), float(prev["low"])


def _opening_range_levels(
    day_bars: pd.DataFrame,
    market: str,
    or_minutes: int,
) -> tuple[float, float] | None:
    """High/low of the first `or_minutes` session bars."""
    if day_bars.empty:
        return None
    mode = session_mode_for_market(market)
    tz = _session_tz(mode)
    first_ts = day_bars.index[0]
    if first_ts.tz is None:
        first_ts = first_ts.tz_localize(tz)
    else:
        first_ts = first_ts.tz_convert(tz)
    open_t = _session_open_time(market)
    session_open = first_ts.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
    or_end = session_open + timedelta(minutes=or_minutes)
    or_bars = day_bars[(day_bars.index >= session_open) & (day_bars.index < or_end)]
    if len(or_bars) < max(1, or_minutes // 2):
        or_bars = day_bars.head(or_minutes)
    if or_bars.empty:
        return None
    return float(or_bars["high"].max()), float(or_bars["low"].min())


def _session_date_series(work: pd.DataFrame) -> pd.Series:
    """Per-bar session date without adding a 'date' column (avoids Groww index/column clash)."""
    return pd.Series(work.index.date, index=work.index, name="_session_day")


def _drop_ambiguous_date_column(work: pd.DataFrame) -> pd.DataFrame:
    """Groww/yfinance frames may name the index 'date' and still carry a date column."""
    out = work.copy()
    if out.index.name == "date":
        out.index.name = None
    if "date" in out.columns:
        out = out.drop(columns=["date"])
    return out


def generate_trade_signals(
    df_1m: pd.DataFrame,
    market: str,
    *,
    cfg: Intra7WastedConfig | None = None,
) -> pd.DataFrame:
    """
    5-Minute Opening Range Breakout & Retest on 1m OHLCV.

    Returns a DataFrame of triggered LONG setups (one per session day max).
    """
    cfg = cfg or Intra7WastedConfig()
    work = _drop_ambiguous_date_column(_ensure_market_tz(df_1m, market))
    if work.empty:
        return pd.DataFrame()

    session_dates = _session_date_series(work)
    trade_signals: list[dict[str, Any]] = []

    for day in sorted(session_dates.unique()):
        daily_data = work.loc[session_dates == day]
        session = daily_data[daily_data.index.map(lambda ts: _in_regular_session(ts, market))]
        if len(session) < cfg.or_minutes + 2:
            continue

        levels = _opening_range_levels(session, market, cfg.or_minutes)
        if levels is None:
            continue
        or_high, or_low = levels

        post_or = session.iloc[cfg.or_minutes:]
        if post_or.empty:
            continue

        breakout_occurred = False
        for current_time, candle in post_or.iterrows():
            if not breakout_occurred:
                if float(candle["close"]) > or_high:
                    breakout_occurred = True
                continue

            low = float(candle["low"])
            close = float(candle["close"])
            if low <= or_high and close > or_high:
                entry_price = close
                stop_loss = low - cfg.sl_buffer
                risk = entry_price - stop_loss
                if risk <= 0:
                    continue
                target_price = entry_price + risk * cfg.rr_ratio
                trade_signals.append({
                    "Datetime": current_time,
                    "Entry_Price": round(entry_price, 4),
                    "OR_High_Level": round(or_high, 4),
                    "OR_Low_Level": round(or_low, 4),
                    "Stop_Loss": round(stop_loss, 4),
                    "Target_Price": round(target_price, 4),
                    "Direction": "LONG",
                    "Risk": round(risk, 4),
                })
                break

    return pd.DataFrame(trade_signals)


def _evaluate_today_phase(
    session_bars: pd.DataFrame,
    market: str,
    cfg: Intra7WastedConfig,
) -> dict[str, Any]:
    """Live phase for the most recent session day."""
    state: dict[str, Any] = {
        "phase": PHASE_NONE,
        "or_high": np.nan,
        "or_low": np.nan,
        "breakout_occurred": False,
        "entry": None,
    }
    if session_bars.empty:
        return state

    mode = session_mode_for_market(market)
    tz = _session_tz(mode)
    now_ts = session_bars.index[-1]
    if now_ts.tz is None:
        now_ts = now_ts.tz_localize(tz)
    else:
        now_ts = now_ts.tz_convert(tz)

    open_t = _session_open_time(market)
    session_open = now_ts.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
    or_end = session_open + timedelta(minutes=cfg.or_minutes)

    if now_ts < or_end:
        state["phase"] = PHASE_WAIT_OR
        return state

    levels = _opening_range_levels(session_bars, market, cfg.or_minutes)
    if levels is None:
        state["phase"] = PHASE_WAIT_OR
        return state

    or_high, or_low = levels
    state["or_high"] = or_high
    state["or_low"] = or_low

    post_or = session_bars[session_bars.index >= or_end]
    if post_or.empty:
        state["phase"] = PHASE_OR_DEFINED
        return state

    breakout_occurred = False
    pending_retest = False
    for current_time, candle in post_or.iterrows():
        if not breakout_occurred:
            if float(candle["close"]) > or_high:
                breakout_occurred = True
                state["breakout_occurred"] = True
                state["phase"] = PHASE_BREAKOUT
            continue

        low = float(candle["low"])
        close = float(candle["close"])
        if low <= or_high and close > or_high:
            entry_price = close
            stop_loss = low - cfg.sl_buffer
            risk = entry_price - stop_loss
            if risk > 0:
                state["phase"] = PHASE_ENTRY
                state["entry"] = {
                    "time": current_time,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "target_price": entry_price + risk * cfg.rr_ratio,
                    "or_high": or_high,
                }
                return state
        if breakout_occurred:
            pending_retest = True
            state["phase"] = PHASE_RETEST

    if not breakout_occurred:
        state["phase"] = PHASE_OR_DEFINED
    elif pending_retest:
        state["phase"] = PHASE_RETEST

    return state


def evaluate_live_signal(
    df_1m: pd.DataFrame,
    market: str,
    *,
    daily_trend: str,
    prev_day_high: float | None,
    prev_day_low: float | None,
    cfg: Intra7WastedConfig | None = None,
    signals: pd.DataFrame | None = None,
) -> dict[str, Any]:
    cfg = cfg or Intra7WastedConfig()
    work = _drop_ambiguous_date_column(_ensure_market_tz(df_1m, market))
    if work.empty:
        return {"signal": "NO_DATA"}

    price = float(work["close"].iloc[-1])
    session_bars = work[work.index.map(lambda ts: _in_regular_session(ts, market))]
    if session_bars.empty:
        session_bars = work.tail(120)

    today_state = _evaluate_today_phase(session_bars, market, cfg)
    phase = today_state["phase"]
    or_high = today_state.get("or_high", np.nan)
    or_low = today_state.get("or_low", np.nan)
    entry_info = today_state.get("entry")

    reasons: list[str] = []
    conf = 15.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    stop = price
    target = price

    reasons.append(f"Daily bias: **{daily_trend.upper()}** (HTF summary filter)")
    if prev_day_high is not None and prev_day_low is not None:
        reasons.append(
            f"Prev-day location — high **{prev_day_high:,.4g}** · low **{prev_day_low:,.4g}**"
        )

    bias_ok = not (cfg.require_daily_bullish and daily_trend != "bullish")
    if not bias_ok:
        verdict = "NO BIAS"
        conf = 12.0
        reasons.append("Bullish daily required for long OR breakout-retest — skip bearish/neutral days")
    else:
        conf += 12
        if daily_trend == "bullish":
            conf += 10
            reasons.append("Daily bullish — aligned with long-only OR retest framework")

    if not np.isnan(or_high):
        reasons.append(f"5m opening range — high **{or_high:,.4g}** (external → internal liquidity) · low **{or_low:,.4g}**")

    if phase == PHASE_WAIT_OR:
        verdict = "WAIT — opening range forming"
        conf += 5
        reasons.append(f"First **{cfg.or_minutes}** session minutes define OR high/low — no entry yet")
    elif phase == PHASE_OR_DEFINED:
        verdict = "WATCH — OR defined"
        conf += 10
        reasons.append("Await 1m **close above** OR high (breakout — external liquidity swept)")
    elif phase == PHASE_BREAKOUT:
        verdict = "WATCH — breakout"
        conf += 18
        reasons.append("Breakout closed above OR high — do **not** chase; wait for retest of OR high")
    elif phase == PHASE_RETEST:
        verdict = "WATCH — retest armed"
        conf += 22
        reasons.append("Price pulling back to OR high (internal liquidity) — watch for buyer support")
    elif phase == PHASE_ENTRY and entry_info:
        entry_price = float(entry_info["entry_price"])
        stop = float(entry_info["stop_loss"])
        target = float(entry_info["target_price"])
        reasons.append("Retest: low touched OR high · close reclaimed above — buyers defended level")
        reasons.append(f"SL below entry candle low · TP **{cfg.rr_ratio}:1** R:R minimum")
        if bias_ok:
            direction = "LONG"
            verdict = "TAKE LONG"
            conf += 32
        else:
            verdict = "NO BIAS — retest fired but daily bias blocks entry"
            reasons.append("Bullish daily bias required — entry trigger ignored on bearish/neutral day")

    if signals is not None and not signals.empty:
        last_sig = signals.iloc[-1]
        sig_time = last_sig.get("Datetime")
        if sig_time is not None and phase != PHASE_ENTRY:
            reasons.append(f"Historical signal on session: {sig_time}")

    conf = max(10.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.15, (price - stop) / price * 100)
        tp_pct = max(0.25, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.4
        tp_pct = sl_pct * cfg.rr_ratio

    hold = HOLD_7_WASTED
    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=EXEC_TF,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule=f"Minimum **{cfg.rr_ratio}:1** R:R · SL below entry candle low.",
        max_hold_exit="Close remaining position before session end.",
    )

    return enrich_intra_live({
        "signal": "BUY" if take else "NONE",
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
        "or_high": or_high,
        "or_low": or_low,
        "daily_trend": daily_trend,
        "prev_day_high": prev_day_high,
        "prev_day_low": prev_day_low,
        "execution_tf": EXEC_TF,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_data(
    ticker: str,
    market: str,
    cfg: Intra7WastedConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    out: dict[str, pd.DataFrame] = {}

    df_1m = fetch_data_for_gap_scan(
        ticker, EXEC_TF, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df_1m = normalize_ohlcv(df_1m)
    if df_1m.empty or len(df_1m) < cfg.min_bars:
        df_1m = normalize_ohlcv(
            fetch_ohlcv_yfinance(
                ticker, EXEC_TF, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market,
            ),
        )
    out[EXEC_TF] = _drop_ambiguous_date_column(_ensure_market_tz(df_1m, market))

    df_1d = fetch_data_for_gap_scan(
        ticker, "1d", market, groww_token, exchange, limit=30,
    )
    df_1d = normalize_ohlcv(df_1d)
    if df_1d.empty:
        df_1d = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=30, market=market),
        )
    out["1d"] = df_1d

    return out


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: Intra7WastedConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Intra7WastedConfig()
    data = fetch_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    df_1m = data.get(EXEC_TF, pd.DataFrame())

    if df_1m.empty or len(df_1m) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {EXEC_TF} data."}

    daily_trend, prev_high, prev_low = _daily_trend_and_prev_levels(data.get("1d", pd.DataFrame()))
    signals = generate_trade_signals(df_1m, market, cfg=cfg)
    live = evaluate_live_signal(
        df_1m,
        market,
        daily_trend=daily_trend,
        prev_day_high=prev_high,
        prev_day_low=prev_low,
        cfg=cfg,
        signals=signals,
    )

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": EXEC_TF,
        "daily_trend": daily_trend,
        "prev_day_high": prev_high,
        "prev_day_low": prev_low,
        "bars": len(df_1m),
        "last_close": float(df_1m["close"].iloc[-1]),
        "signal_count": len(signals),
        "signals": signals,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: Intra7WastedConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Intra7WastedConfig()
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
        and (r.get("live") or {}).get("phase") in (
            PHASE_OR_DEFINED, PHASE_BREAKOUT, PHASE_RETEST, PHASE_WAIT_OR,
        )
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": EXEC_TF,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
