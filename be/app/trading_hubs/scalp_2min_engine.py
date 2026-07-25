"""
scalp_2min_engine.py
----------------------
"2-Minute Scalping Strategy" — a trend-following pullback scalp for Nifty/Bank
Nifty/Sensex ITM options, built on a 2-minute chart.

Rules:
  - Trend: 10 EMA vs 20 EMA + price on the same side of both.
  - Never chase a breakout candle — only enter on a pullback to the 20 EMA
    (a classic stop-loss-hunt trap for early breakout buyers).
  - Trigger: Morning Star / Evening Star (best, 3-candle) or Bullish/Bearish
    Engulfing (good, 2-candle) forming right at that 20 EMA pullback.
  - Time filter: stop taking new trades after ~11:30-12:00 — the morning
    session has the best setups and liquidity.
  - Max 3 entries/day. Stop-loss strictly below/above the pattern, capped at
    15-18 points on the option premium.
  - Trade ITM options (100-200 points deep), target delta ~0.55-0.60.
  - Avoid option buying when India VIX is above ~15-16.

`scan_scalp_2min_signals()` is a direct implementation of the trend + pullback
+ pattern + time-filter + per-day-cap scan (vectorized, run across a full
2-minute OHLC series). `analyze_scalp_2min()` wraps it for live use: fetches
real 2-minute index data (resampled from 1m), checks the real India VIX gate,
and — when there's a fresh signal on the most recent candle — picks a real
NSE ITM option leg near the target delta band.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from typing import Any

import pandas as pd

from app.market_pulse.double_calendar_engine import _norm_cdf
from app.market_pulse.indicators import add_ema
from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval
from app.market_pulse.live_price import get_index_last_traded_price
from app.market_pulse.option_chain_engine import INDEX_CHOICES, fetch_option_chain

logger = logging.getLogger(__name__)

INDEX_NAMES = ["Nifty 50", "Bank Nifty", "Sensex"]
_INDEX_TO_OPTION_SYMBOL = {"Nifty 50": "NIFTY", "Bank Nifty": "BANKNIFTY", "Sensex": ""}  # Sensex is BSE — no NSE chain
_MIN_BARS = 30


@dataclass
class Scalp2MinConfig:
    ema_fast: int = 10
    ema_slow: int = 20
    time_cutoff: str = "11:30"  # stop new entries at/after this IST time
    max_entries_per_day: int = 3
    vix_max_threshold: float = 16.0
    itm_points_min: float = 100.0
    itm_points_max: float = 200.0
    target_delta_min: float = 0.55
    target_delta_max: float = 0.60
    sl_points_option: float = 18.0  # max stop-loss on the option premium
    risk_free_rate: float = 0.065


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def _fetch_2min_ohlcv(index_name: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300) -> pd.DataFrame:
    """1-minute index OHLC resampled to 2-minute bars (no native '2m' feed is wired up)."""
    df_1m = fetch_index_ohlcv_for_interval(
        index_name, "1m", limit=limit * 2 + 60, groww_token=groww_token, exchange=exchange,
    )
    if df_1m is None or df_1m.empty:
        return pd.DataFrame()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df_1m.columns:
        agg["volume"] = "sum"
    resampled = df_1m.resample("2min").agg(agg).dropna(subset=["open", "high", "low", "close"])
    return resampled.tail(limit)


def _fetch_india_vix(cfg: Scalp2MinConfig) -> dict[str, Any]:
    try:
        import yfinance as yf
        hist = yf.Ticker("^INDIAVIX").history(period="5d")
        if hist is None or hist.empty:
            return {"favorable": True, "level": None, "label": "—", "reason": "India VIX unavailable — gate skipped, verify manually before buying options."}
        current = float(hist["Close"].iloc[-1])
        favorable = current <= cfg.vix_max_threshold
        reason = (
            f"India VIX {current:.2f} — {'within' if favorable else 'above'} the {cfg.vix_max_threshold:.0f} "
            f"ceiling recommended for option buying."
        )
        return {"favorable": favorable, "level": round(current, 2), "label": f"{current:.2f}", "reason": reason}
    except Exception as exc:
        logger.debug("India VIX fetch failed: %s", exc)
        return {"favorable": True, "level": None, "label": "—", "reason": "India VIX fetch failed — gate skipped, verify manually before buying options."}


# ---------------------------------------------------------------------------
# Pattern detection — vectorized across the whole series (mirrors the same
# thresholds as price_action.detect_candlestick_patterns, which only scans
# the last ~10 bars and so can't be reused directly for a full-series scan).
# ---------------------------------------------------------------------------

def _detect_patterns(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    candle_range = (h - l).replace(0, pd.NA)
    is_bullish = c > o
    prev_bullish = (c.shift(1) > o.shift(1)).fillna(False)
    prev_body = body.shift(1)

    bullish_engulfing = (
        (~prev_bullish) & is_bullish & (c > o.shift(1)) & (o < c.shift(1)) & (body > prev_body)
    ).fillna(False)
    bearish_engulfing = (
        prev_bullish & (~is_bullish) & (c < o.shift(1)) & (o > c.shift(1)) & (body > prev_body)
    ).fillna(False)

    prev2_bearish = (c.shift(2) < o.shift(2))
    prev2_bullish = (c.shift(2) > o.shift(2))
    prev1_range = (h.shift(1) - l.shift(1)).replace(0, pd.NA)
    prev1_small = (body.shift(1) / prev1_range) < 0.3

    morning_star = (
        prev2_bearish & prev1_small & is_bullish & (c > (o.shift(2) + c.shift(2)) / 2)
    ).fillna(False)
    evening_star = (
        prev2_bullish & prev1_small & (~is_bullish) & (c < (o.shift(2) + c.shift(2)) / 2)
    ).fillna(False)

    out = pd.DataFrame(index=df.index)
    out["bullish_engulfing"] = bullish_engulfing
    out["bearish_engulfing"] = bearish_engulfing
    out["morning_star"] = morning_star
    out["evening_star"] = evening_star
    return out


_PATTERN_LABELS = {
    "morning_star": ("Morning Star", "VERY HIGH"),
    "bullish_engulfing": ("Bullish Engulfing", "HIGH"),
    "evening_star": ("Evening Star", "VERY HIGH"),
    "bearish_engulfing": ("Bearish Engulfing", "HIGH"),
}


# ---------------------------------------------------------------------------
# Core strategy scan
# ---------------------------------------------------------------------------

def scan_scalp_2min_signals(df: pd.DataFrame, cfg: Scalp2MinConfig | None = None) -> list[dict[str, Any]]:
    """Trend + pullback-to-20EMA + reversal-pattern scan across a 2-minute OHLC
    series, with the time filter and max-3-entries-per-day cap."""
    cfg = cfg or Scalp2MinConfig()
    if df is None or df.empty:
        return []

    work = df.copy()
    work = add_ema(work, cfg.ema_fast)
    work = add_ema(work, cfg.ema_slow)
    fast_col, slow_col = f"ema_{cfg.ema_fast}", f"ema_{cfg.ema_slow}"
    work = work.dropna(subset=[fast_col, slow_col])
    if work.empty:
        return []

    patterns = _detect_patterns(work)
    cutoff_time = datetime.strptime(cfg.time_cutoff, "%H:%M").time()

    signals: list[dict[str, Any]] = []
    entries_today: dict[date, int] = {}

    for i in range(2, len(work)):
        ts = work.index[i]
        bar_date = ts.date() if hasattr(ts, "date") else None
        bar_time = ts.time() if hasattr(ts, "time") else None

        # RULE: time filter — only trade before the cutoff
        if bar_time is not None and bar_time >= cutoff_time:
            continue
        # RULE: max entries per day
        if bar_date is not None and entries_today.get(bar_date, 0) >= cfg.max_entries_per_day:
            continue

        row = work.iloc[i]
        ema_fast_v, ema_slow_v = row[fast_col], row[slow_col]
        close_v, low_v, high_v = row["close"], row["low"], row["high"]

        # RULE: trend — 10 EMA vs 20 EMA + price on the same side of both
        uptrend = ema_fast_v > ema_slow_v and close_v > ema_fast_v and close_v > ema_slow_v
        downtrend = ema_fast_v < ema_slow_v and close_v < ema_fast_v and close_v < ema_slow_v

        # RULE: pullback to the 20 EMA (SL-hunt trap), not a breakout chase
        pullback_long = low_v <= ema_slow_v and close_v > ema_slow_v
        pullback_short = high_v >= ema_slow_v and close_v < ema_slow_v

        prow = patterns.iloc[i]
        bullish_pattern = "morning_star" if prow["morning_star"] else ("bullish_engulfing" if prow["bullish_engulfing"] else None)
        bearish_pattern = "evening_star" if prow["evening_star"] else ("bearish_engulfing" if prow["bearish_engulfing"] else None)

        direction = None
        pattern_key = None
        if uptrend and pullback_long and bullish_pattern:
            direction, pattern_key = "LONG", bullish_pattern
        elif downtrend and pullback_short and bearish_pattern:
            direction, pattern_key = "SHORT", bearish_pattern

        if direction:
            name, reliability = _PATTERN_LABELS[pattern_key]
            signals.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "direction": direction,
                "price": round(float(close_v), 4),
                "ema_fast": round(float(ema_fast_v), 4),
                "ema_slow": round(float(ema_slow_v), 4),
                "pattern": name,
                "pattern_reliability": reliability,
            })
            if bar_date is not None:
                entries_today[bar_date] = entries_today.get(bar_date, 0) + 1

    return signals


# ---------------------------------------------------------------------------
# ITM option-leg selection — real NSE chain, delta approximated via Black-Scholes
# ---------------------------------------------------------------------------

def _parse_nse_expiry(s: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def select_itm_option_leg(
    index_name: str, direction: str, spot: float, cfg: Scalp2MinConfig, groww_token: str = "",
) -> dict[str, Any] | None:
    symbol = _INDEX_TO_OPTION_SYMBOL.get(index_name, "")
    if not symbol or symbol not in INDEX_CHOICES:
        return None
    chain = fetch_option_chain(symbol, True, groww_token)
    if not chain:
        return None
    strikes = chain.get("strikes") or []
    if not strikes:
        return None

    expiry = chain.get("current_expiry")
    expiry_date = _parse_nse_expiry(expiry) if expiry else None
    dte = max(((expiry_date - date.today()).days if expiry_date else 7), 1)
    t_years = dte / 365.0

    opt_side = "ce" if direction == "LONG" else "pe"
    candidates = []
    for s in strikes:
        strike = s.get("strike")
        if strike is None:
            continue
        itm_points = (spot - strike) if direction == "LONG" else (strike - spot)
        if not (cfg.itm_points_min <= itm_points <= cfg.itm_points_max):
            continue
        ltp = s.get(f"{opt_side}_ltp") or 0
        if ltp <= 0:
            continue
        iv_raw = s.get(f"{opt_side}_iv") or 0
        vol = max(iv_raw, 1.0) / 100.0
        try:
            d1 = (math.log(spot / strike) + (cfg.risk_free_rate + 0.5 * vol ** 2) * t_years) / (vol * math.sqrt(t_years))
            delta = _norm_cdf(d1) if opt_side == "ce" else _norm_cdf(d1) - 1
        except (ValueError, ZeroDivisionError):
            continue
        candidates.append({
            "strike": strike, "premium": ltp, "iv": iv_raw,
            "delta": round(abs(delta), 3), "itm_points": round(itm_points, 1),
        })

    if not candidates:
        return None

    mid_target = (cfg.target_delta_min + cfg.target_delta_max) / 2
    in_band = [c for c in candidates if cfg.target_delta_min <= c["delta"] <= cfg.target_delta_max]
    pool = in_band or candidates
    best = min(pool, key=lambda c: abs(c["delta"] - mid_target))

    entry = best["premium"]
    return {
        "option_type": "CE" if direction == "LONG" else "PE",
        "strike": best["strike"], "expiry": expiry, "premium": entry,
        "iv": best["iv"], "delta": best["delta"], "itm_points": best["itm_points"],
        "stop_price": round(entry - cfg.sl_points_option, 4),
        "target_price": round(entry + cfg.sl_points_option * 2, 4),
        "sl_points": cfg.sl_points_option,
        "in_target_delta_band": bool(in_band),
        "source": "NSE live chain",
    }


# ---------------------------------------------------------------------------
# Live setup snapshot (fills Conf / SL% / TP% even when not TAKE)
# ---------------------------------------------------------------------------

def _session_signals(signals: list[dict[str, Any]], session_day: date) -> list[dict[str, Any]]:
    """Signals whose timestamp falls on the last bar's calendar session (not wall-clock today)."""
    prefix = session_day.isoformat()
    return [s for s in signals if str(s.get("timestamp", "")).startswith(prefix)]


def _live_ema_state(df: pd.DataFrame, cfg: Scalp2MinConfig) -> dict[str, Any]:
    """Trend / pullback / indicative index risk from the last completed 2m bar."""
    work = add_ema(df.copy(), cfg.ema_fast)
    work = add_ema(work, cfg.ema_slow)
    fast_col, slow_col = f"ema_{cfg.ema_fast}", f"ema_{cfg.ema_slow}"
    work = work.dropna(subset=[fast_col, slow_col])
    if work.empty:
        return {
            "trend": "FLAT", "direction_bias": "WAIT", "near_pullback": False,
            "ema_fast": None, "ema_slow": None, "spot": None,
            "sl_pct": 0.25, "tp_pct": 0.50,
        }

    row = work.iloc[-1]
    spot = float(row["close"])
    ema_fast_v = float(row[fast_col])
    ema_slow_v = float(row[slow_col])
    low_v, high_v = float(row["low"]), float(row["high"])

    uptrend = ema_fast_v > ema_slow_v and spot > ema_fast_v and spot > ema_slow_v
    downtrend = ema_fast_v < ema_slow_v and spot < ema_fast_v and spot < ema_slow_v
    pullback_long = low_v <= ema_slow_v and spot > ema_slow_v
    pullback_short = high_v >= ema_slow_v and spot < ema_slow_v

    if uptrend:
        trend, direction_bias = "UP", "LONG"
        near_pullback = pullback_long
    elif downtrend:
        trend, direction_bias = "DOWN", "SHORT"
        near_pullback = pullback_short
    else:
        trend, direction_bias, near_pullback = "FLAT", "WAIT", False

    # Indicative index SL: invalidate beyond the 20 EMA; TP at 1:2 (mirrors option R:R).
    buffer = max(spot * 0.00025, 2.0)
    if direction_bias == "LONG":
        stop = min(ema_slow_v, spot) - buffer
        risk = max(spot - stop, spot * 0.0004)
        sl_pct = risk / spot * 100
        tp_pct = sl_pct * 2.0
    elif direction_bias == "SHORT":
        stop = max(ema_slow_v, spot) + buffer
        risk = max(stop - spot, spot * 0.0004)
        sl_pct = risk / spot * 100
        tp_pct = sl_pct * 2.0
    else:
        # Flat — show planned option-proxy risk (~18 pts premium ≈ ~36 index pts at ~0.5δ).
        risk_pts = cfg.sl_points_option * 2.0
        sl_pct = risk_pts / spot * 100
        tp_pct = sl_pct * 2.0

    return {
        "trend": trend,
        "direction_bias": direction_bias,
        "near_pullback": near_pullback,
        "ema_fast": round(ema_fast_v, 2),
        "ema_slow": round(ema_slow_v, 2),
        "spot": round(spot, 4),
        "sl_pct": round(max(0.08, sl_pct), 2),
        "tp_pct": round(max(0.16, tp_pct), 2),
    }


def _score_confidence(
    *,
    vix_ok: bool,
    past_cutoff: bool,
    trend: str,
    near_pullback: bool,
    is_fresh: bool,
    session_signal_count: int,
    pattern_reliability: str | None,
) -> float:
    conf = 18.0
    if vix_ok:
        conf += 12.0
    if not past_cutoff:
        conf += 14.0
    else:
        conf += 2.0  # after cutoff still show mild setup quality, not a zero row
    if trend in ("UP", "DOWN"):
        conf += 18.0
    if near_pullback:
        conf += 12.0
    if session_signal_count > 0:
        conf += 8.0
    if is_fresh:
        conf += 18.0
        if pattern_reliability == "VERY HIGH":
            conf += 6.0
        elif pattern_reliability == "HIGH":
            conf += 3.0
    return round(max(15.0, min(92.0, conf)), 1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_scalp_2min(
    index_name: str, *, cfg: Scalp2MinConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Scalp2MinConfig()
    df = _fetch_2min_ohlcv(index_name, groww_token=groww_token, exchange=exchange)
    if df is None or df.empty or len(df) < _MIN_BARS:
        return {"ticker": index_name, "error": f"Insufficient 2-minute data ({0 if df is None else len(df)} bars, need {_MIN_BARS}+)."}

    signals = scan_scalp_2min_signals(df, cfg)
    vix = _fetch_india_vix(cfg)
    ema_state = _live_ema_state(df, cfg)

    last_ts = df.index[-1]
    session_day = last_ts.date() if hasattr(last_ts, "date") else date.today()
    session_signals = _session_signals(signals, session_day)
    spot = float(ema_state["spot"] if ema_state.get("spot") is not None else df["close"].iloc[-1])

    last_signal = session_signals[-1] if session_signals else None
    last_iso = last_ts.isoformat() if hasattr(last_ts, "isoformat") else str(last_ts)
    is_fresh = bool(last_signal and last_signal["timestamp"] == last_iso)

    cutoff_time = datetime.strptime(cfg.time_cutoff, "%H:%M").time()
    last_bar_time = last_ts.time() if hasattr(last_ts, "time") else dtime(0, 0)
    past_cutoff = last_bar_time >= cutoff_time
    day_cap_hit = len(session_signals) >= cfg.max_entries_per_day and not is_fresh

    calendar_today = date.today()
    session_note = (
        f"Session day {session_day.isoformat()}"
        + (f" (calendar today is {calendar_today.isoformat()} — using last bar's session)" if session_day != calendar_today else "")
    )

    reasons: list[str] = [
        vix["reason"],
        session_note,
        f"{len(session_signals)}/{cfg.max_entries_per_day} entries used this session — strategy caps at {cfg.max_entries_per_day}/day.",
        f"Time filter: last candle at {last_bar_time.strftime('%H:%M')} — "
        + ("past" if past_cutoff else "before") + f" the {cfg.time_cutoff} cutoff for new entries.",
        (
            f"EMA state: {cfg.ema_fast}/{cfg.ema_slow} trend **{ema_state['trend']}** "
            f"(fast {ema_state['ema_fast']}, slow {ema_state['ema_slow']})"
            + (", price tagging the 20 EMA pullback zone" if ema_state["near_pullback"] else "")
        ),
    ]

    verdict = "WAIT"
    option_leg = None
    entry_ok = is_fresh and vix["favorable"] and not past_cutoff and len(session_signals) <= cfg.max_entries_per_day
    pattern_rel = last_signal.get("pattern_reliability") if last_signal else None

    if entry_ok and last_signal:
        verdict = last_signal["direction"]
        reasons.append(
            f"Trigger: {last_signal['pattern']} ({last_signal['pattern_reliability']}) at the "
            f"{cfg.ema_slow} EMA pullback, {cfg.ema_fast}/{cfg.ema_slow} EMA trend aligned — "
            f"{verdict} setup on the last completed 2-min candle."
        )
        try:
            option_leg = select_itm_option_leg(index_name, verdict, spot, cfg, groww_token)
        except Exception as exc:
            logger.debug("Option leg selection failed for %s: %s", index_name, exc)
        if option_leg is None:
            reasons.append("No NSE option-chain data available to pick an ITM strike for this index — showing underlying indicative SL/TP.")
    elif last_signal:
        bias = last_signal["direction"]
        verdict = f"WATCH {bias}" if not past_cutoff else "WAIT"
        reasons.append(
            f"Most recent qualifying setup was {bias} at {last_signal['timestamp']} "
            "— not the current candle, so no fresh trigger right now."
        )
        if not vix["favorable"]:
            reasons.append("Blocked by the VIX gate even though a pattern fired — avoid option buying in this environment.")
        if past_cutoff:
            reasons.append("Blocked by the time filter — outside the morning entry window.")
        if day_cap_hit:
            reasons.append("Blocked by the daily entry cap.")
    elif ema_state["direction_bias"] in ("LONG", "SHORT") and not past_cutoff:
        verdict = f"WATCH {ema_state['direction_bias']}"
        reasons.append(
            "Trend aligned on EMAs — waiting for a Morning/Evening Star or Engulfing at the 20 EMA pullback."
            if not ema_state["near_pullback"]
            else "Trend + 20 EMA pullback present — waiting for a reversal candle pattern to fire."
        )
    else:
        if past_cutoff:
            reasons.append("Outside the morning entry window — no new Scalp-2mins entries until next session.")
        if ema_state["trend"] == "FLAT":
            reasons.append("No clear 10/20 EMA trend — strategy only trades with EMA alignment.")
        if not session_signals and not signals:
            reasons.append("No qualifying trend + pullback + reversal-pattern setup found in the fetched window.")
        elif not session_signals and signals:
            reasons.append(
                f"{len(signals)} historical setup(s) in the lookback, but none on session {session_day.isoformat()}."
            )

    confidence_pct = _score_confidence(
        vix_ok=bool(vix.get("favorable")),
        past_cutoff=past_cutoff,
        trend=str(ema_state["trend"]),
        near_pullback=bool(ema_state["near_pullback"]),
        is_fresh=is_fresh,
        session_signal_count=len(session_signals),
        pattern_reliability=pattern_rel,
    )

    sl_pct = float(ema_state["sl_pct"])
    tp_pct = float(ema_state["tp_pct"])
    if option_leg and option_leg.get("premium"):
        premium = float(option_leg["premium"])
        if premium > 0:
            sl_pct = round(option_leg["sl_points"] / premium * 100, 2)
            tp_pct = round((option_leg["target_price"] - premium) / premium * 100, 2)
            confidence_pct = max(confidence_pct, 100.0 if option_leg.get("in_target_delta_band") else 70.0)

    return {
        "ticker": index_name,
        "spot": round(spot, 4),
        "verdict": verdict,
        "vix": vix,
        "signals_today": session_signals,  # session-day signals (name kept for tab compatibility)
        "all_signals": signals,
        "option_leg": option_leg,
        "reasons": reasons,
        "ema_fast": cfg.ema_fast,
        "ema_slow": cfg.ema_slow,
        "last_bar_time": last_bar_time.strftime("%H:%M"),
        "session_date": session_day.isoformat(),
        "trend": ema_state["trend"],
        "near_pullback": ema_state["near_pullback"],
        "direction_bias": ema_state["direction_bias"],
        "confidence_pct": confidence_pct,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "take_trade": verdict in ("LONG", "SHORT"),
    }


def analyze_scalp_2min_many(
    index_names: list[str], *, cfg: Scalp2MinConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results = []
    for name in index_names:
        try:
            results.append(analyze_scalp_2min(name, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Scalp 2min failed for %s: %s", name, exc)
            results.append({"ticker": name, "error": str(exc)[:200]})
    return results


# ---------------------------------------------------------------------------
# Trading Hubs registry adapter
# ---------------------------------------------------------------------------
# This strategy always trades Nifty 50 / Bank Nifty / Sensex — it does not
# operate on an arbitrary ticker universe like the other hub sections, so
# `tickers`/`market` are accepted (for signature compatibility with
# app.trading_hubs.registry.run_section_scan) but not used.

def scan_universe(
    tickers: list[str], market: str, *,
    cfg: Scalp2MinConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Scalp2MinConfig()
    raw = analyze_scalp_2min_many(INDEX_NAMES, cfg=cfg, groww_token=groww_token, exchange=exchange)

    results: list[dict[str, Any]] = []
    for r in raw:
        ticker = r.get("ticker", "?")
        if r.get("error"):
            results.append({"ticker": ticker, "error": r["error"]})
            continue

        verdict = r.get("verdict", "WAIT")
        leg = r.get("option_leg")
        reasons = list(r.get("reasons") or [])
        if leg:
            reasons.append(
                f"Suggested leg: {leg['option_type']} {leg['strike']} (expiry {leg.get('expiry', '—')}) · "
                f"premium {leg['premium']} · IV {leg.get('iv', '—')}% · delta {leg['delta']} · "
                f"{leg.get('itm_points')} pts ITM · stop {leg['stop_price']} · target {leg['target_price']}"
            )
        today_signals = r.get("signals_today") or []
        if today_signals:
            reasons.append(f"{len(today_signals)} qualifying setup(s) this session.")

        take_trade = bool(r.get("take_trade")) or verdict in ("LONG", "SHORT")
        confidence_pct = float(r.get("confidence_pct") or 0.0)
        sl_pct = r.get("sl_pct")
        tp_pct = r.get("tp_pct")
        if sl_pct is None or tp_pct is None:
            sl_pct, tp_pct = 0.25, 0.50
        if leg and leg.get("premium"):
            reasons.append(
                f"SL/TP % from ITM option premium (max SL {cfg.sl_points_option:g} pts, 1:2 R:R)."
            )
        else:
            reasons.append(
                f"Indicative index SL/TP from 20 EMA invalidation (1:2). "
                f"Option pricing fills when a fresh LONG/SHORT fires with NSE chain data "
                f"(max SL {cfg.sl_points_option:g} pts on premium)."
            )

        ltp = get_index_last_traded_price(ticker)
        if ltp.get("price") is not None:
            reasons.insert(0, f"LTP {ltp['price']:,.2f} (live index quote) vs {cfg.ema_slow}-EMA candle close {r.get('spot')}.")

        results.append({
            "ticker": ticker,
            "last_close": ltp.get("price") if ltp.get("price") is not None else r.get("spot"),
            "ltp": ltp,
            "live": {
                "take_trade": take_trade,
                "verdict": verdict,
                "phase": verdict,
                "direction": r.get("direction_bias") or "WAIT",
                "confidence_pct": confidence_pct,
                "sl_pct": round(float(sl_pct), 2),
                "tp_pct": round(float(tp_pct), 2),
                "hold_duration": f"Intraday scalp — new entries stop at {cfg.time_cutoff}, exit same session",
                "reasons": reasons,
                "trend": r.get("trend"),
                "near_pullback": r.get("near_pullback"),
                "session_date": r.get("session_date"),
            },
        })

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and str((r.get("live") or {}).get("verdict", "")).startswith("WATCH")
    ]
    return {
        "market": market,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
        "strategy": "Scalp-2mins — 2-Minute EMA Pullback Scalp",
    }
