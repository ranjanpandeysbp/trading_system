"""
scalp_ny_open_bias_engine.py
------------------------------
"Stop overcomplicating your trades" — 1-hour NY-open directional bias,
executed on the 1-minute chart. Scarface Trades.

Source: https://www.youtube.com/watch?v=qhF61rJBOyE

Step 1, daily direction (the "1H pattern"): look at the 9:00 AM Eastern
1-hour candle — the hour right before the 9:30 AM NYSE open. If it closes
green, only long setups are considered for the day. If it closes red,
only shorts. A doji (no net change) gives no bias and no trades.

Step 2, entry on the 1-minute chart — three interchangeable entry styles
(the video pairs the 1H bias with "almost any system"; these are its three
worked examples, selectable via `entry_style`):

  - `five_min_break_retest`: mark the first 5 minutes of the session's
    high/low. Break through it in the bias direction, retest that level
    with WEAK (small-bodied) price action, then a continuation candle in
    the bias direction confirms the entry.
  - `pdh_pdl_break_retest`: mark the previous day's high (bull bias) or
    low (bear bias). Break through it on the 1-minute chart, pull back to
    retest with STRONG same-direction price action, entry.
  - `one_candle_rule`: the 5-minute break/retest combined with a key
    structural level — the last opposite-colour ("down close" for a bull
    setup) candle before the breakout. Buyers/sellers must defend that
    level (price holds it, doesn't close back through) after the 5-minute
    break before the entry is taken.

Risk management: stop-loss just beyond the retest/break candle's extreme
(or the one-candle level for that style). Minimum 1:2 risk:reward target.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time as dtime
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.session_constants import NY_TZ

logger = logging.getLogger(__name__)

YOUTUBE_NY_OPEN_BIAS_URL = "https://www.youtube.com/watch?v=qhF61rJBOyE"

ENTRY_STYLE_OPTIONS = ["five_min_break_retest", "pdh_pdl_break_retest", "one_candle_rule"]
ENTRY_STYLE_LABELS = {
    "five_min_break_retest": "First 5-Minute Break & Retest",
    "pdh_pdl_break_retest": "Previous Day High/Low Break & Retest",
    "one_candle_rule": "The One Candle Rule",
}

WEAK_BODY_MAX_PCT = 35.0
STRONG_BODY_MIN_PCT = 55.0


@dataclass
class NyOpenBiasConfig:
    entry_style: str = "five_min_break_retest"
    bias_hour_et: int = 9
    min_rr: float = 2.0
    sl_buffer_pct: float = 0.05
    lookback_1h: int = 60
    lookback_1m: int = 600
    min_1h_bars: int = 15
    min_1m_bars: int = 40


def _ensure_ny_index(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV and express bar timestamps in America/New_York."""
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    work = work.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(NY_TZ)
    else:
        work.index = idx.tz_localize(NY_TZ)
    return work.sort_index()


def _fetch_tf(
    ticker: str, tf: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market))
    return df


def bias_from_1h(df_1h_ny: pd.DataFrame, bias_hour: int) -> tuple[str, dict[str, Any] | None]:
    """The most recent `bias_hour`:00 ET 1-hour candle — green closes -> BULL, red -> BEAR."""
    if df_1h_ny.empty:
        return "NEUTRAL", None
    candidates = df_1h_ny[df_1h_ny.index.hour == bias_hour]
    if candidates.empty:
        return "NEUTRAL", None
    ts = candidates.index[-1]
    row = candidates.iloc[-1]
    o, c = float(row["open"]), float(row["close"])
    bias = "BULL" if c > o else "BEAR" if c < o else "NEUTRAL"
    return bias, {"timestamp": str(ts), "open": o, "close": c}


def _session_bars(df_1m_ny: pd.DataFrame) -> pd.DataFrame:
    """Today's (most recent date present) NYSE session bars, from 09:30 ET."""
    if df_1m_ny.empty:
        return df_1m_ny
    last_date = df_1m_ny.index[-1].date()
    day_bars = df_1m_ny[df_1m_ny.index.date == last_date]
    return day_bars[day_bars.index.time >= dtime(9, 30)]


def _body_pct(o: float, h: float, l: float, c: float) -> float:
    rng = max(h - l, 1e-9)
    return abs(c - o) / rng * 100.0


def _scan_five_min_break_retest(session: pd.DataFrame, bias: str) -> list[dict[str, Any]]:
    if len(session) < 7:
        return []
    direction = "LONG" if bias == "BULL" else "SHORT"
    five_high = float(session["high"].iloc[:5].max())
    five_low = float(session["low"].iloc[:5].min())

    signals: list[dict[str, Any]] = []
    broke = False
    opens, highs, lows, closes = (session[c].to_numpy() for c in ("open", "high", "low", "close"))

    for i in range(5, len(session)):
        o, h, l, c = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i])
        if not broke:
            if direction == "SHORT" and c < five_low:
                broke = True
            elif direction == "LONG" and c > five_high:
                broke = True
            continue

        level = five_low if direction == "SHORT" else five_high
        touched = h >= level if direction == "SHORT" else l <= level
        weak_retest = touched and _body_pct(o, h, l, c) < WEAK_BODY_MAX_PCT
        if not weak_retest:
            continue
        if i + 1 >= len(session):
            break
        no, nh, nl, nc = float(opens[i + 1]), float(highs[i + 1]), float(lows[i + 1]), float(closes[i + 1])
        continuation = nc < l if direction == "SHORT" else nc > h
        if continuation:
            signals.append({
                "bar_index": i + 1, "timestamp": str(session.index[i + 1]), "direction": direction,
                "entry": nc, "stop_ref": h if direction == "SHORT" else l, "level": level,
            })
            broke = False  # reset — a fresh break could form again later in the session

    return signals


def _scan_pdh_pdl_break_retest(session: pd.DataFrame, bias: str, prev_high: float | None, prev_low: float | None) -> list[dict[str, Any]]:
    direction = "LONG" if bias == "BULL" else "SHORT"
    level = prev_high if direction == "LONG" else prev_low
    if level is None or session.empty:
        return []

    signals: list[dict[str, Any]] = []
    broke = False
    opens, highs, lows, closes = (session[c].to_numpy() for c in ("open", "high", "low", "close"))

    for i in range(len(session)):
        o, h, l, c = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i])
        if not broke:
            if direction == "LONG" and c > level:
                broke = True
            elif direction == "SHORT" and c < level:
                broke = True
            continue

        touched = l <= level if direction == "LONG" else h >= level
        strong_same_direction = (c > o) if direction == "LONG" else (c < o)
        if touched and strong_same_direction and _body_pct(o, h, l, c) > STRONG_BODY_MIN_PCT:
            signals.append({
                "bar_index": i, "timestamp": str(session.index[i]), "direction": direction,
                "entry": c, "stop_ref": l if direction == "LONG" else h, "level": level,
            })
            broke = False

    return signals


def _scan_one_candle_rule(session: pd.DataFrame, bias: str) -> list[dict[str, Any]]:
    if len(session) < 7:
        return []
    direction = "LONG" if bias == "BULL" else "SHORT"
    five_high = float(session["high"].iloc[:5].max())
    five_low = float(session["low"].iloc[:5].min())

    signals: list[dict[str, Any]] = []
    broke = False
    one_candle_level: float | None = None
    opens, highs, lows, closes = (session[c].to_numpy() for c in ("open", "high", "low", "close"))

    for i in range(len(session)):
        o, h, l, c = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i])
        if not broke:
            if direction == "LONG" and c < o:
                one_candle_level = l  # last down-close candle -> support buyers must defend
            elif direction == "SHORT" and c > o:
                one_candle_level = h  # last up-close candle -> resistance sellers must defend
            if i >= 5:
                if direction == "LONG" and c > five_high:
                    broke = True
                elif direction == "SHORT" and c < five_low:
                    broke = True
            continue

        if one_candle_level is None:
            continue
        holds = l > one_candle_level if direction == "LONG" else h < one_candle_level
        if holds:
            signals.append({
                "bar_index": i, "timestamp": str(session.index[i]), "direction": direction,
                "entry": c, "stop_ref": one_candle_level, "level": one_candle_level,
            })
            broke, one_candle_level = False, None

    return signals


def evaluate_live_signal(
    session: pd.DataFrame, signals: list[dict[str, Any]], cfg: NyOpenBiasConfig,
    bias: str, bias_candle: dict[str, Any] | None,
) -> dict[str, Any]:
    if session.empty:
        return {"signal": "NO_DATA", "verdict": "NO DATA", "take_trade": False}

    price = float(session["close"].iloc[-1])
    style_label = ENTRY_STYLE_LABELS.get(cfg.entry_style, cfg.entry_style)
    reasons: list[str] = []
    if bias_candle:
        reasons.append(
            f"{cfg.bias_hour_et}:00 ET 1H candle closed {'green' if bias == 'BULL' else 'red' if bias == 'BEAR' else 'flat'} "
            f"(open {bias_candle['open']:,.4g} -> close {bias_candle['close']:,.4g}) -> "
            + (f"only **long** setups today." if bias == "BULL" else f"only **short** setups today." if bias == "BEAR" else "no bias, no trades today.")
        )
    else:
        reasons.append(f"No {cfg.bias_hour_et}:00 ET 1H candle found yet in the fetched window.")
    reasons.append(f"Entry style: **{style_label}**.")

    last_idx = len(session) - 1
    last_signal = signals[-1] if signals else None
    is_fresh = bool(last_signal and last_signal["bar_index"] == last_idx)

    verdict, direction, take = "WAIT", "WAIT", False
    entry = stop = target = price
    confidence = 0.0

    if bias == "NEUTRAL":
        reasons.append("Bias candle was flat (open == close) — the video calls for no trades on a neutral day.")
    elif is_fresh and last_signal:
        direction = last_signal["direction"]
        entry = last_signal["entry"]
        buffer = entry * (cfg.sl_buffer_pct / 100.0)
        stop = last_signal["stop_ref"] - buffer if direction == "LONG" else last_signal["stop_ref"] + buffer
        risk = abs(entry - stop)
        target = entry + risk * cfg.min_rr if direction == "LONG" else entry - risk * cfg.min_rr

        confidence = 65.0
        take = True
        verdict = ("BUY" if direction == "LONG" else "SELL") + f" — {style_label} confirmed"
        if cfg.entry_style == "five_min_break_retest":
            reasons.append(
                f"Broke the first-5-minute {'low' if direction == 'SHORT' else 'high'} ({last_signal['level']:,.4g}), "
                "retested it with weak (small-bodied) price action, then a continuation candle confirmed the entry."
            )
        elif cfg.entry_style == "pdh_pdl_break_retest":
            reasons.append(
                f"Broke the previous day's {'high' if direction == 'LONG' else 'low'} ({last_signal['level']:,.4g}), "
                "pulled back to retest it with strong same-direction price action, entry confirmed."
            )
        else:
            reasons.append(
                f"Broke the first-5-minute {'high' if direction == 'LONG' else 'low'}, then held the one-candle "
                f"{'support' if direction == 'LONG' else 'resistance'} level ({last_signal['level']:,.4g}) — buyers/sellers defended it."
            )
        reasons.append(f"Stop just beyond the retest/break candle's extreme ({stop:,.4g}).")
        reasons.append(f"Target set for a minimum 1:{cfg.min_rr:.0f} risk:reward ({target:,.4g}).")
    elif last_signal:
        reasons.append(
            f"Most recent qualifying {last_signal['direction']} setup was {last_signal['timestamp']} — "
            "not the current candle, so no fresh trigger right now."
        )
    else:
        reasons.append(f"No {style_label} setup found in today's session yet.")

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if take and entry else None
    tp_pct = round(abs(target - entry) / entry * 100, 2) if take and entry else None
    hold_duration = "Intraday — flat by the close (1-minute execution off a 1H NY-open bias candle)"

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe="1m", stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="scalp",
        exit_rule=f"Target a minimum 1:{cfg.min_rr:.0f} R:R; invalidate if price closes back beyond the stop reference.",
        max_hold_exit="Flat intraday — this bias resets each new session's 1H candle.",
    )

    live = enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction if take else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": bias,
        "confidence_pct": confidence if take else 0.0,
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6) if take else None,
        "stop_price": round(stop, 6) if take else None,
        "target_price": round(target, 6) if take else None,
        "entry_style": cfg.entry_style,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration} if take else None,
    }, hold_duration=hold_duration)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: NyOpenBiasConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or NyOpenBiasConfig()

    df_1h = _fetch_tf(ticker, "1h", market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_1h)
    if df_1h.empty or len(df_1h) < cfg.min_1h_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient 1h data ({len(df_1h)} bars) for the bias candle."}
    df_1h_ny = _ensure_ny_index(df_1h)
    bias, bias_candle = bias_from_1h(df_1h_ny, cfg.bias_hour_et)

    df_1m = _fetch_tf(ticker, "1m", market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_1m)
    if df_1m.empty or len(df_1m) < cfg.min_1m_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient 1m data ({len(df_1m)} bars)."}
    df_1m_ny = _ensure_ny_index(df_1m)
    session = _session_bars(df_1m_ny)
    if session.empty:
        return {"ticker": ticker, "market": market, "error": "No NYSE session (09:30 ET onward) bars in the fetched window."}

    prev_high = prev_low = None
    if cfg.entry_style == "pdh_pdl_break_retest":
        daily = _fetch_tf(ticker, "1d", market, groww_token=groww_token, exchange=exchange, limit=5)
        if not daily.empty:
            prev_high, prev_low = float(daily["high"].iloc[-1]), float(daily["low"].iloc[-1])

    if bias == "NEUTRAL":
        signals: list[dict[str, Any]] = []
    elif cfg.entry_style == "pdh_pdl_break_retest":
        signals = _scan_pdh_pdl_break_retest(session, bias, prev_high, prev_low)
    elif cfg.entry_style == "one_candle_rule":
        signals = _scan_one_candle_rule(session, bias)
    else:
        signals = _scan_five_min_break_retest(session, bias)

    live = evaluate_live_signal(session, signals, cfg, bias, bias_candle)

    return {
        "ticker": ticker, "market": market, "execution_tf": "1m",
        "bars": len(session), "last_close": float(session["close"].iloc[-1]),
        "signal_history": signals[-8:], "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: NyOpenBiasConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or NyOpenBiasConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("NY Open Bias scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "execution_tf": "1m", "results": results,
        "entries": entries, "entry_count": len(entries),
    }
