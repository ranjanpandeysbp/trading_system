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

    today_str = date.today().isoformat()
    today_signals = [s for s in signals if s["timestamp"].startswith(today_str)]

    last_ts = df.index[-1]
    spot = float(df["close"].iloc[-1])
    last_signal = today_signals[-1] if today_signals else None
    is_fresh = bool(last_signal and last_signal["timestamp"] == (last_ts.isoformat() if hasattr(last_ts, "isoformat") else str(last_ts)))

    cutoff_time = datetime.strptime(cfg.time_cutoff, "%H:%M").time()
    last_bar_time = last_ts.time() if hasattr(last_ts, "time") else dtime(0, 0)
    past_cutoff = last_bar_time >= cutoff_time
    day_cap_hit = len(today_signals) >= cfg.max_entries_per_day and not is_fresh

    reasons: list[str] = [
        vix["reason"],
        f"{len(today_signals)}/{cfg.max_entries_per_day} entries used today — strategy caps at {cfg.max_entries_per_day}/day.",
        f"Time filter: last candle at {last_bar_time.strftime('%H:%M')} — "
        + ("past" if past_cutoff else "before") + f" the {cfg.time_cutoff} cutoff for new entries.",
    ]

    verdict = "WAIT"
    option_leg = None
    entry_ok = is_fresh and vix["favorable"] and not past_cutoff and len(today_signals) <= cfg.max_entries_per_day

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
            reasons.append("No NSE option-chain data available to pick an ITM strike for this index — underlying signal only.")
    elif last_signal:
        reasons.append(
            f"Most recent qualifying setup was {last_signal['direction']} at {last_signal['timestamp']} "
            "— not the current candle, so no fresh trigger right now."
        )
        if not vix["favorable"]:
            reasons.append("Blocked by the VIX gate even though a pattern fired — avoid option buying in this environment.")
        if past_cutoff:
            reasons.append("Blocked by the time filter — outside the morning entry window.")
        if day_cap_hit:
            reasons.append("Blocked by the daily entry cap.")
    else:
        reasons.append("No qualifying trend + pullback + reversal-pattern setup found in the fetched window.")

    return {
        "ticker": index_name, "spot": round(spot, 4), "verdict": verdict,
        "vix": vix, "signals_today": today_signals, "all_signals": signals,
        "option_leg": option_leg, "reasons": reasons,
        "ema_fast": cfg.ema_fast, "ema_slow": cfg.ema_slow,
        "last_bar_time": last_bar_time.strftime("%H:%M"),
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
            reasons.append(f"{len(today_signals)} qualifying setup(s) today.")

        sl_pct = tp_pct = confidence_pct = None
        if leg and leg.get("premium"):
            premium = leg["premium"]
            sl_pct = round(leg["sl_points"] / premium * 100, 2)
            tp_pct = round((leg["target_price"] - premium) / premium * 100, 2)
            confidence_pct = 100.0 if leg.get("in_target_delta_band") else 60.0

        ltp = get_index_last_traded_price(ticker)
        if ltp.get("price") is not None:
            reasons.insert(0, f"LTP {ltp['price']:,.2f} (live index quote) vs {cfg.ema_slow}-EMA candle close {r.get('spot')}.")

        take_trade = verdict in ("LONG", "SHORT")
        results.append({
            "ticker": ticker,
            "last_close": ltp.get("price") if ltp.get("price") is not None else r.get("spot"),
            "ltp": ltp,
            "live": {
                "take_trade": take_trade,
                "verdict": verdict,
                "phase": verdict,
                "confidence_pct": confidence_pct,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "hold_duration": f"Intraday scalp — new entries stop at {cfg.time_cutoff}, exit same session",
                "reasons": reasons,
            },
        })

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    return {
        "market": market,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "strategy": "Scalp-2mins — 2-Minute EMA Pullback Scalp",
    }
