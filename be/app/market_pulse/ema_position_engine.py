"""
ema_position_engine.py
-----------------------
EMA Position scanner — for one or more tickers, on one or more timeframes, across a
user-picked date range: which EMAs (5/9/20/50/200) did price cross above or below,
what's its status at each end of the range, plus the next support/resistance level.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd

from backtesting.data_fetcher import get_historical_data
from app.market_pulse.indicators import add_ema
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import _calc_atr, detect_support_resistance

logger = logging.getLogger(__name__)

EMA_PERIOD_OPTIONS = [5, 9, 20, 50, 200]
TIMEFRAME_OPTIONS = ["15m", "1h", "4h", "1d", "1w"]
DEFAULT_TIMEFRAMES = ["1d"]

# Bars of warm-up history fetched *before* from_date so the largest EMA is actually
# meaningful at the very start of the analysis window, not a cold-start value. Sized to
# the largest EMA actually requested (capped at 400) rather than a flat 400 always,
# since padding out to 400 bars for e.g. EMA-5/9/20 only pushes the fetch window further
# back than needed — worsening the odds of hitting Yahoo Finance's intraday lookback
# caps (15m/30m: ~60 days, 1h: ~730 days without a Groww API token).
_MAX_WARMUP_BARS = 400
_APPROX_CAL_DAYS_PER_BAR = {
    "15m": 1 / 26, "1h": 1 / 6, "4h": 2 / 3, "1d": 1.5, "1w": 10,
}
_YF_INTRADAY_LOOKBACK_DAYS = {"15m": 60, "1h": 730, "4h": 730}

_VERDICT_LABELS = {
    "CROSSED_ABOVE": "Crossed Above",
    "CROSSED_BELOW": "Crossed Below",
    "STAYED_ABOVE": "Stayed Above",
    "STAYED_BELOW": "Stayed Below",
}


@dataclass
class EmaPositionConfig:
    ema_periods: list[int] = field(default_factory=lambda: list(EMA_PERIOD_OPTIONS))
    timeframes: list[str] = field(default_factory=lambda: list(DEFAULT_TIMEFRAMES))


def _warmup_start(from_date: date, timeframe: str, ema_periods: list[int] | None = None) -> date:
    days_per_bar = _APPROX_CAL_DAYS_PER_BAR.get(timeframe, 1.5)
    max_period = max(ema_periods) if ema_periods else 200
    warmup_bars = min(_MAX_WARMUP_BARS, max_period * 3)
    return from_date - timedelta(days=int(warmup_bars * days_per_bar) + 5)


def fetch_ticker_history(
    ticker: str, market: str, timeframe: str, from_date: date, to_date: date,
    *, groww_token: str = "", exchange: str = "NSE", ema_periods: list[int] | None = None,
) -> tuple[pd.DataFrame, bool]:
    """OHLCV from warm-up-start through to_date (inclusive) for one ticker/timeframe.
    Returns (df, was_clamped) — was_clamped is True when the data actually available
    starts later than the requested warm-up start (e.g. a Yahoo Finance intraday
    lookback cap without a Groww API token), so the caller can surface that plainly."""
    warm_start = _warmup_start(from_date, timeframe, ema_periods)
    df = get_historical_data(
        symbol=ticker,
        start_date=str(warm_start),
        end_date=str(to_date + timedelta(days=1)),
        market=market,
        timeframe=timeframe,
        groww_token=groww_token,
        groww_exchange=exchange,
    )
    df = normalize_ohlcv(df)
    was_clamped = False
    if not df.empty and not (groww_token and groww_token.strip()):
        actual_start = pd.to_datetime(df.index[0]).date()
        was_clamped = actual_start > warm_start + timedelta(days=2)
    return df, was_clamped


def _crossovers(df: pd.DataFrame, ema_col: str, from_date: date, to_date: date) -> list[dict]:
    """Close-vs-EMA sign flips whose bar date falls within [from_date, to_date]."""
    events: list[dict] = []
    diff = df["close"] - df[ema_col]
    sign = np.sign(diff)
    idx_dates = pd.to_datetime(df.index)
    for i in range(1, len(df)):
        d_date = idx_dates[i].date()
        if d_date < from_date or d_date > to_date:
            continue
        prev_sign, cur_sign = sign.iloc[i - 1], sign.iloc[i]
        if pd.isna(prev_sign) or pd.isna(cur_sign) or cur_sign == 0:
            continue
        if prev_sign < 0 and cur_sign > 0:
            events.append({
                "date": df.index[i], "direction": "UP",
                "price": float(df["close"].iloc[i]), "ema": float(df[ema_col].iloc[i]),
            })
        elif prev_sign > 0 and cur_sign < 0:
            events.append({
                "date": df.index[i], "direction": "DOWN",
                "price": float(df["close"].iloc[i]), "ema": float(df[ema_col].iloc[i]),
            })
    return events


# Experienced swing traders don't average across every EMA on the chart — they pick ONE
# reference EMA for the actual entry trigger (classically the 50, sometimes the 20 for a
# faster read) and use the 200 as major-trend context, not a second vote. Averaging
# crossing counts across periods was tried and rejected: a 20 EMA naturally crosses far
# more often than a 50 or 200 over the same window, so the average was almost always
# dragged into "choppy" territory by the fastest EMA alone, even when the actual trend
# (50/200) was clean.
_PRIMARY_EMA_PREFERENCE = [50, 20, 9, 5]  # first one present in the scan is the signal EMA
_TREND_CONTEXT_EMA = 200
# Choppiness is judged as crossings *per 100 bars in range*, not a flat count — a flat
# count unfairly penalizes a long date range (naturally more crossings) and under-
# penalizes a short one. >=6 crossings per 100 bars means the primary EMA flips more
# than roughly once every ~17 bars on average, which is genuine whipsaw rather than
# a couple of real trend changes spread across a multi-month window.
_CHOPPY_CROSSINGS_PER_100_BARS = 6.0
_MIN_BARS_FOR_CHOP_CHECK = 20  # too few bars to meaningfully judge frequency
_MIN_ROOM_PCT = 1.5  # need at least this much room to the next S/R level to call it actionable
# `detect_support_resistance` returns a single price per level, not a zone — this
# draws a thin band around that price so the chart's shared ReferenceArea styling
# (used everywhere else in the app for S/R) still has something visible to shade.
_CHART_ZONE_BUFFER_PCT = 0.15


def _chart_zone(level: dict | None) -> list[float] | None:
    if not level:
        return None
    price = float(level["price"])
    buf = price * (_CHART_ZONE_BUFFER_PCT / 100)
    return [round(price - buf, 6), round(price + buf, 6)]


_BUCKET_BASE_CONFIDENCE = {"ACTIONABLE": 78.0, "WATCH": 58.0, "NO_TRADE": 25.0}


def _classify_actionability(
    ema_summary: list[dict[str, Any]], next_support: dict | None, next_resistance: dict | None,
    last_price: float, bars_in_range: int = 0,
) -> dict[str, Any]:
    """Thin wrapper around `_classify_actionability_core` that attaches a numeric
    confidence % (base value per bucket) so this section's actionability can be
    combined with Fundamental Analysis the same way Momentum's is."""
    result = _classify_actionability_core(ema_summary, next_support, next_resistance, last_price, bars_in_range)
    result["confidence_pct"] = _BUCKET_BASE_CONFIDENCE.get(result["bucket"], 40.0)
    return result


def _classify_actionability_core(
    ema_summary: list[dict[str, Any]], next_support: dict | None, next_resistance: dict | None,
    last_price: float, bars_in_range: int = 0,
) -> dict[str, Any]:
    """Experienced-trader-style bucketing: pick the primary signal EMA (50 preferred,
    then 20/9/5, whichever is present), require it to have crossed cleanly (not whipsawed)
    and recently, check the 200 EMA as major-trend context so a signal against the big
    trend is a WATCH not a full entry, and require room to run before the next support/
    resistance. No fresh, clean, trend-aligned signal with room = WATCH; a whipsawing
    primary EMA = NO_TRADE regardless of its current side."""
    if not ema_summary:
        return {"bucket": "NO_TRADE", "direction": None, "reason": "No EMA data available."}

    by_period = {e["ema_period"]: e for e in ema_summary}
    primary = next((by_period[p] for p in _PRIMARY_EMA_PREFERENCE if p in by_period), ema_summary[0])
    p_label = f"EMA {primary['ema_period']}"

    if bars_in_range >= _MIN_BARS_FOR_CHOP_CHECK:
        crossings_per_100 = primary["crossover_count"] / bars_in_range * 100
        if crossings_per_100 >= _CHOPPY_CROSSINGS_PER_100_BARS:
            return {"bucket": "NO_TRADE", "direction": None,
                    "reason": f"{p_label} crossed {primary['crossover_count']} times over {bars_in_range} bars "
                              f"({crossings_per_100:.1f}/100 bars) — too choppy to trust a single crossover."}

    trend_ctx = by_period.get(_TREND_CONTEXT_EMA) if primary["ema_period"] != _TREND_CONTEXT_EMA else None
    verdict = primary["verdict"]
    room_up_pct = ((next_resistance["price"] - last_price) / last_price * 100) if next_resistance else None
    room_down_pct = ((last_price - next_support["price"]) / last_price * 100) if next_support else None

    if verdict == "CROSSED_ABOVE":
        if trend_ctx is not None and trend_ctx["status_to"] == "BELOW":
            return {"bucket": "WATCH", "direction": "LONG",
                    "reason": f"Crossed above {p_label} but still below the 200 EMA major trend — early/counter-trend, watch for confirmation."}
        if room_up_pct is not None and room_up_pct < _MIN_ROOM_PCT:
            return {"bucket": "WATCH", "direction": "LONG",
                    "reason": f"Crossed above {p_label}, but only {room_up_pct:.1f}% room to next resistance."}
        room_note = f"{room_up_pct:.1f}% room to next resistance" if room_up_pct is not None else "no nearby resistance overhead"
        trend_note = " and above the 200 EMA major trend" if trend_ctx is not None and trend_ctx["status_to"] == "ABOVE" else ""
        return {"bucket": "ACTIONABLE", "direction": "LONG",
                "reason": f"Fresh bullish crossover on {p_label}{trend_note}, {room_note}."}

    if verdict == "CROSSED_BELOW":
        if trend_ctx is not None and trend_ctx["status_to"] == "ABOVE":
            return {"bucket": "WATCH", "direction": "SHORT",
                    "reason": f"Crossed below {p_label} but still above the 200 EMA major trend — early/counter-trend, watch for confirmation."}
        if room_down_pct is not None and room_down_pct < _MIN_ROOM_PCT:
            return {"bucket": "WATCH", "direction": "SHORT",
                    "reason": f"Crossed below {p_label}, but only {room_down_pct:.1f}% room to next support."}
        room_note = f"{room_down_pct:.1f}% room to next support" if room_down_pct is not None else "no nearby support underneath"
        trend_note = " and below the 200 EMA major trend" if trend_ctx is not None and trend_ctx["status_to"] == "BELOW" else ""
        return {"bucket": "ACTIONABLE", "direction": "SHORT",
                "reason": f"Fresh bearish crossover on {p_label}{trend_note}, {room_note}."}

    if verdict == "STAYED_ABOVE":
        if trend_ctx is None or trend_ctx["status_to"] == "ABOVE":
            return {"bucket": "WATCH", "direction": "LONG",
                    "reason": f"Already trending above {p_label} — no new entry trigger this range, but the trend is intact."}
        return {"bucket": "NO_TRADE", "direction": None,
                "reason": f"Above {p_label} but below the 200 EMA major trend — no fresh signal and mixed trend context."}

    if verdict == "STAYED_BELOW":
        if trend_ctx is None or trend_ctx["status_to"] == "BELOW":
            return {"bucket": "WATCH", "direction": "SHORT",
                    "reason": f"Already trending below {p_label} — no new entry trigger this range, but the trend is intact."}
        return {"bucket": "NO_TRADE", "direction": None,
                "reason": f"Below {p_label} but above the 200 EMA major trend — no fresh signal and mixed trend context."}

    return {"bucket": "NO_TRADE", "direction": None, "reason": "No clear EMA signal in this range."}


def analyze_ticker_timeframe(
    ticker: str, market: str, timeframe: str, cfg: EmaPositionConfig,
    from_date: date, to_date: date, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    df, was_clamped = fetch_ticker_history(
        ticker, market, timeframe, from_date, to_date,
        groww_token=groww_token, exchange=exchange, ema_periods=cfg.ema_periods,
    )
    if df.empty or len(df) < 30:
        hint = ""
        if timeframe in _YF_INTRADAY_LOOKBACK_DAYS and not (groww_token and groww_token.strip()):
            cap = _YF_INTRADAY_LOOKBACK_DAYS[timeframe]
            hint = (f" Without a Groww API token, Yahoo Finance only provides ~{cap} days of "
                    f"{timeframe} history — try a shorter date range or a daily/weekly timeframe.")
        return {"ticker": ticker, "timeframe": timeframe, "error": f"Insufficient {timeframe} data for {ticker}.{hint}"}

    for p in cfg.ema_periods:
        df = add_ema(df, p)

    idx_dates = pd.to_datetime(df.index)
    in_range = (idx_dates.date >= from_date) & (idx_dates.date <= to_date)
    range_df = df.loc[in_range]
    note = None
    if range_df.empty:
        data_start = idx_dates[0].date()
        if was_clamped and to_date >= data_start:
            # Requested from_date is further back than Yahoo Finance's intraday lookback
            # allows, but to_date still overlaps the data that IS available — fall back
            # to the earliest available bars rather than erroring out entirely.
            range_df = df
            from_date = data_start
            cap = _YF_INTRADAY_LOOKBACK_DAYS.get(timeframe)
            note = (
                f"⚠️ Your requested start date was before what Yahoo Finance provides for "
                f"{timeframe} without a Groww API token"
                + (f" (~{cap} days)" if cap else "")
                + f" — showing the earliest available window instead, from {from_date}."
            )
        elif was_clamped:
            # The entire requested [from_date, to_date] window predates what's available —
            # showing "recent" data would silently answer a different question than asked.
            cap = _YF_INTRADAY_LOOKBACK_DAYS.get(timeframe)
            hint = (f" Without a Groww API token, Yahoo Finance only provides ~{cap} days of "
                    f"{timeframe} history (from {data_start} onward) — your selected range "
                    f"predates that entirely.") if cap else ""
            return {"ticker": ticker, "timeframe": timeframe, "error": f"No {timeframe} bars for {ticker} in the selected date range.{hint}"}
        else:
            return {"ticker": ticker, "timeframe": timeframe, "error": f"No {timeframe} bars for {ticker} in the selected date range."}

    first_row, last_row = range_df.iloc[0], range_df.iloc[-1]
    last_price = float(last_row["close"])

    ema_summary: list[dict[str, Any]] = []
    for p in cfg.ema_periods:
        col = f"ema_{p}"
        if col not in df.columns or pd.isna(first_row.get(col)) or pd.isna(last_row.get(col)):
            continue
        status_from = "ABOVE" if first_row["close"] > first_row[col] else "BELOW"
        status_to = "ABOVE" if last_row["close"] > last_row[col] else "BELOW"
        events = _crossovers(df, col, from_date, to_date)
        if status_from != status_to:
            verdict = "CROSSED_ABOVE" if status_to == "ABOVE" else "CROSSED_BELOW"
        else:
            verdict = "STAYED_ABOVE" if status_to == "ABOVE" else "STAYED_BELOW"
        ema_summary.append({
            "ema_period": p,
            "status_from": status_from,
            "status_to": status_to,
            "verdict": verdict,
            "verdict_label": _VERDICT_LABELS[verdict],
            "crossover_count": len(events),
            "crossovers": events,
            "last_crossover": events[-1] if events else None,
            "ema_value_now": round(float(last_row[col]), 4),
            "distance_pct": round((last_price - float(last_row[col])) / last_price * 100, 2),
        })

    sr = detect_support_resistance(df)
    supports = [s for s in (sr.get("supports") or []) if s["price"] < last_price]
    resistances = [r for r in (sr.get("resistances") or []) if r["price"] > last_price]
    next_support = max(supports, key=lambda s: s["price"]) if supports else None
    next_resistance = min(resistances, key=lambda r: r["price"]) if resistances else None

    actionability = _classify_actionability(ema_summary, next_support, next_resistance, last_price, len(range_df))

    period_cols = [(p, f"ema_{p}") for p in cfg.ema_periods if f"ema_{p}" in df.columns]
    chart_data = [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
        }
        for idx, bar in range_df.iterrows()
    ]
    emas_out = {
        str(p): [
            {"time": str(idx), "value": round(float(bar[col]), 6)}
            for idx, bar in range_df.iterrows()
            if pd.notna(bar[col])
        ]
        for p, col in period_cols
    }
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "from_date": from_date,
        "to_date": to_date,
        "last_price": last_price,
        "last_date": last_row.name,
        "ema_summary": ema_summary,
        "next_support": next_support,
        "next_resistance": next_resistance,
        "chart_data": chart_data,
        "emas": emas_out,
        "support_zone": _chart_zone(next_support),
        "resistance_zone": _chart_zone(next_resistance),
        "note": note,
        "actionability": actionability,
    }


def _apply_htf_gate(results: list[dict[str, Any]]) -> None:
    """Downgrade ACTIONABLE to WATCH when a strictly higher timeframe's
    primary EMA disagrees — EMA crosses are the classic whipsaw trap in
    chop, and a 1h breakout fighting the 1d EMA stack is a much weaker
    signal than the single-timeframe bucket alone would suggest. Only
    applies when the scan actually covers more than one timeframe for the
    ticker (mutates `results` in place; no-op otherwise)."""
    tf_rank = {tf: i for i, tf in enumerate(TIMEFRAME_OPTIONS)}
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        if not r.get("error"):
            by_ticker.setdefault(r["ticker"], []).append(r)

    for rows in by_ticker.values():
        if len(rows) < 2:
            continue
        for r in rows:
            act = r.get("actionability") or {}
            if act.get("bucket") != "ACTIONABLE" or act.get("direction") not in ("LONG", "SHORT"):
                continue
            my_rank = tf_rank.get(r["timeframe"])
            if my_rank is None:
                continue
            by_period = {e["ema_period"]: e for e in (r.get("ema_summary") or [])}
            primary = next((by_period[p] for p in _PRIMARY_EMA_PREFERENCE if p in by_period), None)
            if not primary:
                continue
            primary_period = primary["ema_period"]

            for other in rows:
                other_rank = tf_rank.get(other["timeframe"])
                if other_rank is None or other_rank <= my_rank:
                    continue  # not a strictly higher timeframe than this signal
                other_primary = {e["ema_period"]: e for e in (other.get("ema_summary") or [])}.get(primary_period)
                if not other_primary:
                    continue
                htf_status = other_primary["status_to"]
                conflict = (
                    (act["direction"] == "LONG" and htf_status == "BELOW")
                    or (act["direction"] == "SHORT" and htf_status == "ABOVE")
                )
                if conflict:
                    act["bucket"] = "WATCH"
                    act["confidence_pct"] = _BUCKET_BASE_CONFIDENCE["WATCH"]
                    act["reason"] = (
                        f"{act.get('reason', '')} Downgraded from ACTIONABLE: the higher {other['timeframe']} "
                        f"timeframe's EMA {primary_period} is still {htf_status.lower()} price — this cross is "
                        "fighting the bigger trend, a classic whipsaw setup."
                    )
                    break  # one higher-timeframe conflict is enough to downgrade


def analyze_scan(
    tickers: list[str], market: str, cfg: EmaPositionConfig,
    from_date: date, to_date: date, *, groww_token: str = "", exchange: str = "NSE",
    progress_callback: Callable[[float, str], None] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    combos = [(t, tf) for t in tickers for tf in cfg.timeframes]
    total = max(len(combos), 1)
    for i, (ticker, tf) in enumerate(combos, start=1):
        try:
            results.append(analyze_ticker_timeframe(ticker, market, tf, cfg, from_date, to_date, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("EMA position analysis failed for %s %s: %s", ticker, tf, exc)
            results.append({"ticker": ticker, "timeframe": tf, "error": str(exc)[:200]})
        if progress_callback:
            progress_callback(i / total, f"{ticker} · {tf}")
    _apply_htf_gate(results)
    return results


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: EmaPositionConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    """market_pulse-house-style entry point mirroring the other engines'
    scan_universe(tickers, market, ...) signature. Defaults the date range to the
    trailing 90 days ending today when not supplied, since the original Streamlit
    tool always took an explicit user-picked range via analyze_scan()."""
    cfg = cfg or EmaPositionConfig()
    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=90))
    return analyze_scan(
        tickers, market, cfg, from_date, to_date,
        groww_token=groww_token, exchange=exchange,
    )


def build_summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten per-ticker-per-timeframe EMA summaries into one scanner table."""
    rows: list[dict[str, Any]] = []
    for r in results:
        if r.get("error"):
            continue
        for e in r.get("ema_summary") or []:
            last_cross = e.get("last_crossover")
            rows.append({
                "ticker": r["ticker"],
                "timeframe": r["timeframe"],
                "ema": e["ema_period"],
                "status_from": e["status_from"],
                "status_to": e["status_to"],
                "verdict": e["verdict"],
                "verdict_label": e["verdict_label"],
                "crossover_count": e["crossover_count"],
                "last_crossover_date": last_cross["date"] if last_cross else None,
                "last_crossover_direction": last_cross["direction"] if last_cross else None,
                "distance_pct": e["distance_pct"],
            })
    return rows
