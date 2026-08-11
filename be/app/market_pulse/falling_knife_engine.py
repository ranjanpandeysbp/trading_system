"""
falling_knife_engine.py
-----------------------
Scan an asset-class universe for names that have fallen ≥ X% from their
session-window high and/or risen ≥ X% from their session-window low
(live), plus date-range history of threshold rise/fall events with
recovery timing and next-move forecast.

Session hours (regular / primary):
  India      Mon–Fri 09:15–15:30 Asia/Kolkata
  US         Mon–Fri 09:30–16:00 America/New_York
  Crypto     24×7 (UTC)
  Commodity  Nearly 24×5 futures — Sun 18:00 → Fri 17:00 America/New_York
             (CME metals/energy style); gaps during daily maintenance ignored
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytz

from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG, resolve_tickers
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
NY = pytz.timezone("America/New_York")
UTC = pytz.UTC

STRATEGY_ID = "falling_knife"
STRATEGY_NAME = "Falling Knife"


@dataclass(frozen=True)
class SessionSpec:
    tz: Any
    open_t: time | None  # None = 24×7 inside allowed weekdays
    close_t: time | None
    weekdays: frozenset[int]  # Mon=0 … Sun=6
    label: str
    note: str


SESSION_BY_ASSET: dict[str, SessionSpec] = {
    "india": SessionSpec(
        tz=IST,
        open_t=time(9, 15),
        close_t=time(15, 30),
        weekdays=frozenset({0, 1, 2, 3, 4}),
        label="NSE cash · Mon–Fri 09:15–15:30 IST",
        note="Only NSE regular-session bars count toward the lookback window.",
    ),
    "us": SessionSpec(
        tz=NY,
        open_t=time(9, 30),
        close_t=time(16, 0),
        weekdays=frozenset({0, 1, 2, 3, 4}),
        label="US RTH · Mon–Fri 09:30–16:00 America/New_York",
        note="Pre/post-market excluded — regular session only.",
    ),
    "crypto": SessionSpec(
        tz=UTC,
        open_t=None,
        close_t=None,
        weekdays=frozenset({0, 1, 2, 3, 4, 5, 6}),
        label="Crypto 24×7 UTC",
        note="All hours included — crypto trades continuously.",
    ),
    "commodity": SessionSpec(
        tz=NY,
        open_t=None,
        close_t=None,
        weekdays=frozenset({0, 1, 2, 3, 4, 6}),  # Sun–Fri (CME-style)
        label="Futures ~24×5 · Sun–Fri America/New_York",
        note="Nearly continuous futures hours; Saturday mostly closed.",
    ),
}


def _r(x: float, n: int = 4) -> float:
    return round(float(x), n)


def session_info(asset_class: str) -> dict[str, Any]:
    spec = SESSION_BY_ASSET.get(asset_class) or SESSION_BY_ASSET["india"]
    return {
        "asset_class": asset_class,
        "label": spec.label,
        "note": spec.note,
        "timezone": str(spec.tz),
        "open": spec.open_t.strftime("%H:%M") if spec.open_t else "00:00",
        "close": spec.close_t.strftime("%H:%M") if spec.close_t else "24:00",
        "weekdays": sorted(spec.weekdays),
    }


def choose_interval(lookback_hours: float) -> str:
    h = float(lookback_hours)
    if h <= 6:
        return "5m"
    if h <= 48:
        return "15m"
    if h <= 168:
        return "1h"
    return "1d"


def bars_needed(lookback_hours: float, interval: str) -> int:
    """Request enough bars to cover calendar lookback + weekend/holiday gaps."""
    h = max(1.0, float(lookback_hours))
    # Equity sessions need ~3× calendar stretch for weekends
    stretch = 3.2 if interval != "1d" else 1.5
    if interval == "5m":
        n = int(h * 12 * stretch) + 40
    elif interval == "15m":
        n = int(h * 4 * stretch) + 30
    elif interval == "1h":
        n = int(h * stretch) + 24
    else:
        n = int(h / 24 * stretch) + 10
    return int(min(max(n, 40), 800))


def _localize_index(idx: pd.DatetimeIndex, tz) -> pd.DatetimeIndex:
    ts = pd.to_datetime(idx)
    if getattr(ts, "tz", None) is None:
        ts = ts.tz_localize(UTC)
    return ts.tz_convert(tz)


def filter_session_bars(df: pd.DataFrame, asset_class: str, *, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    spec = SESSION_BY_ASSET.get(asset_class) or SESSION_BY_ASSET["india"]
    work = df.copy()
    work.index = _localize_index(work.index, spec.tz)

    start_local = pd.Timestamp(start_utc)
    if start_local.tzinfo is None:
        start_local = UTC.localize(start_local.to_pydatetime())
    start_local = start_local.tz_convert(spec.tz)
    end_local = pd.Timestamp(end_utc)
    if end_local.tzinfo is None:
        end_local = UTC.localize(end_local.to_pydatetime())
    end_local = end_local.tz_convert(spec.tz)

    work = work[(work.index >= start_local) & (work.index <= end_local)]
    if work.empty:
        return work

    wd = work.index.weekday
    work = work[np.isin(wd, list(spec.weekdays))]
    if work.empty:
        return work

    if spec.open_t is not None and spec.close_t is not None:
        t = work.index.time
        mask = np.array([(spec.open_t <= ti <= spec.close_t) for ti in t], dtype=bool)
        work = work[mask]
    return work


def _analyze_symbol(
    symbol: str,
    *,
    asset_class: str,
    market: str,
    drop_pct: float,
    lookback_hours: float,
    interval: str,
    limit: int,
    groww_token: str,
    exchange: str,
    start_utc: datetime,
    end_utc: datetime,
    move_side: str = "both",
) -> dict[str, Any] | None:
    try:
        raw = fetch_data_for_gap_scan(
            symbol,
            interval,
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=limit,
        )
        df = normalize_ohlcv(raw) if raw is not None else pd.DataFrame()
        if df is None or df.empty or len(df) < 3:
            return {
                "ticker": symbol,
                "error": "Insufficient bars",
                "matched": False,
            }

        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["high", "low", "close"])

        sess = filter_session_bars(df, asset_class, start_utc=start_utc, end_utc=end_utc)
        if sess is None or sess.empty or len(sess) < 2:
            return {
                "ticker": symbol,
                "error": "No session bars in lookback window",
                "matched": False,
            }

        high = float(sess["high"].max())
        low = float(sess["low"].min())
        last = float(sess["close"].iloc[-1])
        first = float(sess["close"].iloc[0])
        if high <= 0 or not np.isfinite(high) or low <= 0:
            return {"ticker": symbol, "error": "Invalid high/low", "matched": False}

        fall_from_high = ((high - last) / high) * 100.0
        rise_from_low = ((last - low) / low) * 100.0 if low > 0 else 0.0
        range_from_high = ((high - low) / high) * 100.0
        # Net move over the window: positive = risen, negative = fallen
        change_pct = ((last / first) - 1.0) * 100.0 if first else 0.0
        if change_pct > 0.05:
            direction = "risen"
        elif change_pct < -0.05:
            direction = "fallen"
        else:
            direction = "flat"

        side = (move_side or "both").lower()
        if side not in ("fall", "rise", "both"):
            side = "both"
        thr = float(drop_pct)
        fall_ok = side in ("fall", "both") and fall_from_high >= thr
        rise_ok = side in ("rise", "both") and rise_from_low >= thr
        matched = fall_ok or rise_ok
        if fall_ok and rise_ok:
            match_kind = "both"
        elif fall_ok:
            match_kind = "fall"
        elif rise_ok:
            match_kind = "rise"
        else:
            match_kind = None
        match_score = max(
            fall_from_high if fall_ok else 0.0,
            rise_from_low if rise_ok else 0.0,
        )

        high_ts = sess["high"].idxmax()
        low_ts = sess["low"].idxmin()
        last_ts = sess.index[-1]

        def _fmt_ts(ts) -> str:
            try:
                return pd.Timestamp(ts).isoformat()
            except Exception:
                return str(ts)

        return {
            "ticker": symbol,
            "matched": matched,
            "match_kind": match_kind,
            "match_fall": fall_ok,
            "match_rise": rise_ok,
            "match_score": _r(match_score, 2),
            "last": _r(last, 4),
            "window_open": _r(first, 4),
            "window_high": _r(high, 4),
            "window_low": _r(low, 4),
            "change_pct": _r(change_pct, 2),
            "direction": direction,
            "fallen_pct": _r(abs(change_pct), 2) if change_pct < 0 else 0.0,
            "risen_pct": _r(change_pct, 2) if change_pct > 0 else 0.0,
            "fall_from_high_pct": _r(fall_from_high, 2),
            "rise_from_low_pct": _r(rise_from_low, 2),
            "range_high_to_low_pct": _r(range_from_high, 2),
            "change_from_window_start_pct": _r(change_pct, 2),
            "high_time": _fmt_ts(high_ts),
            "low_time": _fmt_ts(low_ts),
            "last_time": _fmt_ts(last_ts),
            "bars_in_window": int(len(sess)),
            "interval": interval,
            "move_side": side,
            "threshold_pct": thr,
        }
    except Exception as exc:
        logger.debug("Falling knife failed for %s: %s", symbol, exc, exc_info=True)
        return {"ticker": symbol, "error": str(exc)[:180], "matched": False}


def scan_falling_knives(
    *,
    asset_class: str,
    tickers: list[str],
    drop_pct: float = 10.0,
    lookback_hours: float = 24.0,
    move_side: str = "both",
    groww_token: str = "",
    exchange: str = "NSE",
    max_workers: int = 8,
) -> dict[str, Any]:
    ac = (asset_class or "india").strip().lower()
    if ac not in ASSET_CLASS_CONFIG:
        ac = "india"
    cfg = ASSET_CLASS_CONFIG[ac]
    market = str(cfg["market"])
    exchange = exchange or str(cfg.get("exchange") or "NSE")

    symbols = resolve_tickers(ac, tickers)
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in symbols:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    symbols = uniq[:200]

    drop_pct = float(max(0.5, min(drop_pct, 90.0)))
    lookback_hours = float(max(1.0, min(lookback_hours, 24 * 14)))
    side = (move_side or "both").lower()
    if side not in ("fall", "rise", "both"):
        side = "both"
    interval = choose_interval(lookback_hours)
    limit = bars_needed(lookback_hours, interval)

    end_utc = datetime.now(UTC)
    start_utc = end_utc - timedelta(hours=lookback_hours)
    sess = session_info(ac)

    results: list[dict[str, Any]] = []
    if not symbols:
        return {
            "strategy": STRATEGY_ID,
            "strategy_label": STRATEGY_NAME,
            "asset_class": ac,
            "mode": "live",
            "drop_pct": drop_pct,
            "move_side": side,
            "lookback_hours": lookback_hours,
            "interval": interval,
            "session": sess,
            "window_start_utc": start_utc.isoformat(),
            "window_end_utc": end_utc.isoformat(),
            "scanned": 0,
            "matched": 0,
            "matched_falls": 0,
            "matched_rises": 0,
            "results": [],
            "knives": [],
            "errors": 0,
            "plain_english": "No tickers selected.",
            "how_to_read": _how_to(),
        }

    with ThreadPoolExecutor(max_workers=max(2, min(max_workers, 12))) as pool:
        futs = {
            pool.submit(
                _analyze_symbol,
                sym,
                asset_class=ac,
                market=market,
                drop_pct=drop_pct,
                lookback_hours=lookback_hours,
                interval=interval,
                limit=limit,
                groww_token=groww_token,
                exchange=exchange,
                start_utc=start_utc,
                end_utc=end_utc,
                move_side=side,
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                results.append(row)

    knives = [r for r in results if r.get("matched")]
    knives.sort(key=lambda r: float(r.get("match_score") or 0), reverse=True)
    errors = sum(1 for r in results if r.get("error") and not r.get("matched"))
    matched_falls = sum(1 for r in knives if r.get("match_fall"))
    matched_rises = sum(1 for r in knives if r.get("match_rise"))

    if side == "fall":
        thr_label = f">= {drop_pct:g}% off window high"
        side_label = "falls"
    elif side == "rise":
        thr_label = f">= {drop_pct:g}% off window low"
        side_label = "rises"
    else:
        thr_label = f">= {drop_pct:g}% off window high (fall) or low (rise)"
        side_label = "falls & rises"

    top_bits = []
    for r in knives[:8]:
        bits = []
        if r.get("match_fall"):
            bits.append(f"off-high −{r.get('fall_from_high_pct')}%")
        if r.get("match_rise"):
            bits.append(f"off-low +{r.get('rise_from_low_pct')}%")
        chg = r.get("change_pct")
        chg_bit = f"{'+' if (chg or 0) >= 0 else ''}{chg}%" if chg is not None else ""
        top_bits.append(
            f"{r['ticker']} {' · '.join(bits)} · net {chg_bit} "
            f"(H {_r(r['window_high'], 2)} / L {_r(r['window_low'], 2)})"
        )

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "asset_class": ac,
        "asset_label": cfg.get("label"),
        "mode": "live",
        "drop_pct": drop_pct,
        "move_side": side,
        "lookback_hours": lookback_hours,
        "interval": interval,
        "bars_requested": limit,
        "session": sess,
        "window_start_utc": start_utc.isoformat(),
        "window_end_utc": end_utc.isoformat(),
        "scanned": len(results),
        "matched": len(knives),
        "matched_falls": matched_falls,
        "matched_rises": matched_rises,
        "errors": errors,
        "results": sorted(results, key=lambda r: float(r.get("match_score") or -1), reverse=True),
        "knives": knives,
        "summary": {
            "scanned": len(results),
            "matched": len(knives),
            "matched_falls": matched_falls,
            "matched_rises": matched_rises,
            "errors": errors,
            "threshold": thr_label,
            "move_side": side,
            "lookback": f"last {lookback_hours:g}h ({sess['label']})",
        },
        "plain_english": (
            f"Falling Knife · {cfg.get('label')} · live {side_label} · {thr_label} "
            f"in last {lookback_hours:g}h ({sess['label']}). "
            f"Matched {len(knives)} / {len(results)} "
            f"({matched_falls} falls · {matched_rises} rises)."
            + ((" Top: " + " · ".join(top_bits) + ".") if top_bits else "")
        ),
        "how_to_read": _how_to(),
        "disclaimer": "Research / education only — not financial advice. Past drops do not imply recovery.",
    }


def _how_to() -> list[str]:
    return [
        "Pick an asset class and universe (index / custom list).",
        "Live mode: set threshold % + lookback hours + Falls / Rises / Both — only that market’s regular session hours count.",
        "Live match: fall = last ≥ X% below window high · rise = last ≥ X% above window low.",
        "History mode: set a date range + threshold % — counts every rise/fall ≥ X%, gaps, recovery, and next-move forecast.",
        "India: 09:15–15:30 IST · US: 09:30–16:00 ET · Crypto: 24×7 · Commodities: ~24×5 futures.",
        "Fall % off high = (window high - last) / high. Rise % off low = (last - window low) / low.",
        "Net change % = (last - window open) / open (risen + / fallen -).",
        "Recovery = hours/days until price returns to the level where the pump/dump started.",
        "Educational screener only — not a buy/sell signal.",
    ]


def _parse_date_bound(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(raw[:10], fmt)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return UTC.localize(dt)
        except ValueError:
            continue
    try:
        ts = pd.Timestamp(raw)
        if ts.tzinfo is None:
            ts = ts.tz_localize(UTC)
        else:
            ts = ts.tz_convert(UTC)
        if end_of_day and ts.hour == 0 and ts.minute == 0:
            ts = ts + pd.Timedelta(hours=23, minutes=59, seconds=59)
        return ts.to_pydatetime()
    except Exception:
        return None


def _fmt_ts(ts) -> str:
    try:
        return pd.Timestamp(ts).isoformat()
    except Exception:
        return str(ts)


def _hours_between(a, b) -> float | None:
    try:
        ta = pd.Timestamp(a)
        tb = pd.Timestamp(b)
        if ta.tzinfo is None:
            ta = ta.tz_localize(UTC)
        if tb.tzinfo is None:
            tb = tb.tz_localize(UTC)
        return round(float((tb - ta).total_seconds()) / 3600.0, 2)
    except Exception:
        return None


def _duration_label(hours: float | None) -> str | None:
    if hours is None or not np.isfinite(hours):
        return None
    h = abs(float(hours))
    if h < 48:
        return f"{h:.1f} hours"
    days = h / 24.0
    return f"{days:.1f} days ({h:.1f} hours)"


def choose_interval_for_span(span_hours: float) -> str:
    h = max(1.0, float(span_hours))
    if h <= 72:
        return "15m"
    if h <= 24 * 60:
        return "1h"
    return "1d"


def bars_needed_for_span(span_hours: float, interval: str) -> int:
    h = max(24.0, float(span_hours))
    stretch = 2.5 if interval != "1d" else 1.35
    if interval == "5m":
        n = int(h * 12 * stretch) + 80
    elif interval == "15m":
        n = int(h * 4 * stretch) + 60
    elif interval == "1h":
        n = int(h * stretch) + 48
    else:
        n = int(h / 24 * stretch) + 30
    return int(min(max(n, 80), 2500))


def _median(vals: list[float]) -> float | None:
    clean = [float(v) for v in vals if v is not None and np.isfinite(float(v))]
    if not clean:
        return None
    return float(np.median(clean))


def _mean(vals: list[float]) -> float | None:
    clean = [float(v) for v in vals if v is not None and np.isfinite(float(v))]
    if not clean:
        return None
    return float(np.mean(clean))


def _confidence_from_samples(n: int, gaps: list[float]) -> float:
    """Higher with more samples and tighter gap consistency."""
    if n <= 0:
        return 0.0
    base = min(55.0, 18.0 + n * 6.0)
    clean = [float(g) for g in gaps if g is not None and np.isfinite(g) and g > 0]
    if len(clean) >= 2:
        mu = float(np.mean(clean))
        sd = float(np.std(clean))
        cv = (sd / mu) if mu > 1e-9 else 1.5
        consistency = max(0.0, 28.0 * (1.0 - min(cv, 1.4) / 1.4))
        base += consistency
    elif n == 1:
        base = min(base, 28.0)
    return round(float(np.clip(base, 12.0, 88.0)), 1)


def detect_threshold_events(
    df: pd.DataFrame,
    threshold_pct: float,
    *,
    move_side: str = "both",
) -> list[dict[str, Any]]:
    """
    Walk bars and fire a FALL when price is ≥ threshold% below the running peak
    since the last event, or a RISE when ≥ threshold% above the running trough.
    Recovery = time until close returns to the excursion start level.
    """
    if df is None or df.empty or len(df) < 5:
        return []

    thr = float(max(0.5, threshold_pct))
    side = (move_side or "both").lower()
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    closes = df["close"].astype(float).values
    idx = df.index
    n = len(df)

    peak = float(highs[0])
    peak_i = 0
    trough = float(lows[0])
    trough_i = 0
    events: list[dict[str, Any]] = []
    i = 1
    cooldown = max(2, n // 200)  # avoid immediate re-trigger on same move

    while i < n:
        h = float(highs[i])
        l = float(lows[i])
        c = float(closes[i])
        if not np.isfinite(h) or not np.isfinite(l) or not np.isfinite(c) or c <= 0:
            i += 1
            continue

        if h >= peak:
            peak = h
            peak_i = i
        if l <= trough:
            trough = l
            trough_i = i

        fall_pct = ((peak - c) / peak) * 100.0 if peak > 0 else 0.0
        rise_pct = ((c - trough) / trough) * 100.0 if trough > 0 else 0.0

        fired = None
        if side in ("fall", "both") and fall_pct >= thr and peak_i < i:
            fired = "fall"
        elif side in ("rise", "both") and rise_pct >= thr and trough_i < i:
            fired = "rise"
        # If both qualify, take the larger excursion
        if side == "both" and fall_pct >= thr and rise_pct >= thr and peak_i < i and trough_i < i:
            fired = "fall" if fall_pct >= rise_pct else "rise"

        if fired is None:
            i += 1
            continue

        if fired == "fall":
            start_i = peak_i
            start_px = peak
            end_px = c
            move_pct = -fall_pct
            direction = "fall"
        else:
            start_i = trough_i
            start_px = trough
            end_px = c
            move_pct = rise_pct
            direction = "rise"

        # Recovery: return to start level after the event bar
        recovery_i = None
        recovery_hours = None
        recovered = False
        for j in range(i + 1, n):
            cj = float(closes[j])
            if not np.isfinite(cj):
                continue
            if direction == "fall" and cj >= start_px:
                recovery_i = j
                break
            if direction == "rise" and cj <= start_px:
                recovery_i = j
                break
        if recovery_i is not None:
            recovered = True
            recovery_hours = _hours_between(idx[i], idx[recovery_i])

        events.append({
            "direction": direction,
            "move_pct": _r(move_pct, 2),
            "magnitude_pct": _r(abs(move_pct), 2),
            "start_time": _fmt_ts(idx[start_i]),
            "event_time": _fmt_ts(idx[i]),
            "recovery_time": _fmt_ts(idx[recovery_i]) if recovery_i is not None else None,
            "start_price": _r(start_px, 6),
            "event_price": _r(end_px, 6),
            "recovery_hours": recovery_hours,
            "recovery_label": _duration_label(recovery_hours),
            "recovered": recovered,
            "move_hours": _hours_between(idx[start_i], idx[i]),
            "move_label": _duration_label(_hours_between(idx[start_i], idx[i])),
        })

        # Reset extremes from event bar; skip cooldown bars
        peak = float(highs[i])
        peak_i = i
        trough = float(lows[i])
        trough_i = i
        i += 1 + cooldown

    # Annotate gaps to next event (any) and next same-direction
    for k, ev in enumerate(events):
        nxt = events[k + 1] if k + 1 < len(events) else None
        gap_any = _hours_between(ev["event_time"], nxt["event_time"]) if nxt else None
        ev["gap_to_next_hours"] = gap_any
        ev["gap_to_next_label"] = _duration_label(gap_any)
        ev["next_event_time"] = nxt["event_time"] if nxt else None
        ev["next_event_direction"] = nxt["direction"] if nxt else None

        same_next = None
        for m in range(k + 1, len(events)):
            if events[m]["direction"] == ev["direction"]:
                same_next = events[m]
                break
        gap_same = _hours_between(ev["event_time"], same_next["event_time"]) if same_next else None
        ev["gap_to_next_same_hours"] = gap_same
        ev["gap_to_next_same_label"] = _duration_label(gap_same)
        ev["next_same_event_time"] = same_next["event_time"] if same_next else None

    return events


def _as_utc_ts(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(UTC)
    return ts.tz_convert(UTC)


def _fmt_ts_ist(ts) -> str | None:
    try:
        t = _as_utc_ts(ts).tz_convert(IST)
        return t.strftime("%Y-%m-%d %H:%M IST")
    except Exception:
        return None


def _forecast_from_events(
    events: list[dict[str, Any]],
    *,
    direction: str,
    now_utc: datetime,
) -> dict[str, Any] | None:
    subset = [e for e in events if e.get("direction") == direction]
    if not subset:
        return None

    gaps = [float(e["gap_to_next_same_hours"]) for e in subset if e.get("gap_to_next_same_hours")]
    moves = [float(e["magnitude_pct"]) for e in subset if e.get("magnitude_pct") is not None]
    recoveries = [
        float(e["recovery_hours"])
        for e in subset
        if e.get("recovered") and e.get("recovery_hours") is not None
    ]

    med_gap = _median(gaps)
    avg_gap = _mean(gaps)
    med_move = _median(moves)
    avg_move = _mean(moves)
    med_rec = _median(recoveries)
    conf = _confidence_from_samples(len(subset), gaps)

    last = subset[-1]
    last_ts = _as_utc_ts(last["event_time"])
    now_ts = _as_utc_ts(now_utc)

    predicted_ts: pd.Timestamp | None = None
    cycles_skipped = 0
    raw_predicted_ts: pd.Timestamp | None = None
    overdue_hours: float | None = None

    if med_gap is not None and med_gap > 0:
        step = pd.Timedelta(hours=float(med_gap))
        predicted_ts = last_ts + step
        raw_predicted_ts = predicted_ts
        # Roll forward past due slots so the next window is always in the future (IST "now").
        while predicted_ts <= now_ts and cycles_skipped < 120:
            predicted_ts = predicted_ts + step
            cycles_skipped += 1
        if cycles_skipped > 0:
            overdue_hours = _hours_between(raw_predicted_ts, now_ts)
            # Each missed cycle softens confidence (pattern slipped vs calendar).
            conf = round(float(np.clip(conf - min(35.0, cycles_skipped * 4.5), 10.0, 88.0)), 1)

    hours_until = _hours_between(now_ts, predicted_ts) if predicted_ts is not None else None
    signed_move = -float(med_move) if direction == "fall" and med_move is not None else med_move

    predicted_iso = predicted_ts.isoformat() if predicted_ts is not None else None
    predicted_ist = _fmt_ts_ist(predicted_ts) if predicted_ts is not None else None
    roll_note = ""
    if cycles_skipped > 0:
        roll_note = (
            f" Prior slot { _fmt_ts_ist(raw_predicted_ts) or 'n/a' } already passed "
            f"({_duration_label(overdue_hours) or 'overdue'}); rolled forward {cycles_skipped} cycle(s)."
        )

    return {
        "direction": direction,
        "samples": len(subset),
        "confidence_pct": conf,
        "last_event_time": last.get("event_time"),
        "last_event_time_ist": _fmt_ts_ist(last_ts),
        "median_gap_hours": _r(med_gap, 2) if med_gap is not None else None,
        "avg_gap_hours": _r(avg_gap, 2) if avg_gap is not None else None,
        "median_gap_label": _duration_label(med_gap),
        "predicted_next_time": predicted_iso,
        "predicted_next_time_ist": predicted_ist,
        "raw_predicted_next_time": raw_predicted_ts.isoformat() if raw_predicted_ts is not None else None,
        "raw_predicted_next_time_ist": _fmt_ts_ist(raw_predicted_ts) if raw_predicted_ts is not None else None,
        "cycles_skipped": cycles_skipped,
        "overdue_hours": overdue_hours,
        "overdue_label": _duration_label(overdue_hours) if overdue_hours is not None else None,
        "hours_until_predicted": hours_until,
        "hours_until_label": _duration_label(hours_until) if hours_until is not None else None,
        "predicted_move_pct": _r(signed_move, 2) if signed_move is not None else None,
        "predicted_magnitude_pct": _r(med_move, 2) if med_move is not None else None,
        "avg_move_pct": _r(avg_move, 2) if avg_move is not None else None,
        "median_recovery_hours": _r(med_rec, 2) if med_rec is not None else None,
        "median_recovery_label": _duration_label(med_rec),
        "recovery_rate_pct": _r(
            100.0 * sum(1 for e in subset if e.get("recovered")) / len(subset), 1
        ),
        "as_of_ist": _fmt_ts_ist(now_ts),
        "plain_english": (
            f"Based on {len(subset)} historical {direction}(s) ≥ threshold: "
            f"median gap {_duration_label(med_gap) or 'n/a'}, "
            f"next {direction} around {predicted_ist or 'n/a'} "
            f"({conf:.0f}% confidence), "
            f"typical move {('−' if direction == 'fall' else '+')}{med_move or 0:.1f}%, "
            f"median recovery {_duration_label(med_rec) or 'not observed'}."
            f"{roll_note}"
        ),
    }


def analyze_history_ticker(
    symbol: str,
    *,
    asset_class: str,
    market: str,
    threshold_pct: float,
    move_side: str,
    from_utc: datetime,
    to_utc: datetime,
    interval: str,
    limit: int,
    groww_token: str,
    exchange: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ticker": symbol,
        "error": None,
        "events": [],
        "fall_count": 0,
        "rise_count": 0,
        "forecast": {},
    }
    try:
        raw = fetch_data_for_gap_scan(
            symbol,
            interval,
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=limit,
        )
        df = normalize_ohlcv(raw) if raw is not None else pd.DataFrame()
        if df is None or df.empty or len(df) < 8:
            out["error"] = "Insufficient bars for history"
            return out

        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["high", "low", "close"])

        sess = filter_session_bars(df, asset_class, start_utc=from_utc, end_utc=to_utc)
        if sess is None or sess.empty or len(sess) < 8:
            out["error"] = "No session bars in date range"
            return out

        events = detect_threshold_events(sess, threshold_pct, move_side=move_side)
        falls = [e for e in events if e["direction"] == "fall"]
        rises = [e for e in events if e["direction"] == "rise"]
        now_utc = datetime.now(UTC)

        forecast: dict[str, Any] = {}
        if move_side in ("fall", "both"):
            f = _forecast_from_events(events, direction="fall", now_utc=now_utc)
            if f:
                forecast["fall"] = f
        if move_side in ("rise", "both"):
            r = _forecast_from_events(events, direction="rise", now_utc=now_utc)
            if r:
                forecast["rise"] = r

        # Primary next-event pick: soonest future prediction only (never a past slot).
        primary = None
        candidates = [forecast[k] for k in ("fall", "rise") if k in forecast]
        future = []
        now_ts = _as_utc_ts(now_utc)
        for c in candidates:
            pt = c.get("predicted_next_time")
            if not pt:
                continue
            try:
                ts = _as_utc_ts(pt)
                if ts >= now_ts:
                    future.append((ts, c))
            except Exception:
                continue
        if future:
            future.sort(key=lambda x: x[0])
            primary = future[0][1]
        elif candidates:
            # No dated future slot — still surface highest-confidence side without a past datetime.
            primary = max(candidates, key=lambda c: float(c.get("confidence_pct") or 0))
            if primary.get("predicted_next_time"):
                try:
                    if _as_utc_ts(primary["predicted_next_time"]) < now_ts:
                        primary = {
                            **primary,
                            "predicted_next_time": None,
                            "predicted_next_time_ist": None,
                            "hours_until_predicted": None,
                            "hours_until_label": None,
                            "plain_english": (
                                str(primary.get("plain_english") or "")
                                + " Next dated slot is overdue and could not be rolled forward."
                            ).strip(),
                        }
                except Exception:
                    pass

        last = float(sess["close"].iloc[-1])
        out.update({
            "events": events,
            "fall_count": len(falls),
            "rise_count": len(rises),
            "event_count": len(events),
            "forecast": forecast,
            "primary_forecast": primary,
            "bars_in_range": int(len(sess)),
            "interval": interval,
            "last": _r(last, 4),
            "range_start": _fmt_ts(sess.index[0]),
            "range_end": _fmt_ts(sess.index[-1]),
            "avg_fall_pct": _r(_mean([e["magnitude_pct"] for e in falls]) or 0, 2) if falls else None,
            "avg_rise_pct": _r(_mean([e["magnitude_pct"] for e in rises]) or 0, 2) if rises else None,
            "avg_fall_recovery_label": _duration_label(
                _median([e["recovery_hours"] for e in falls if e.get("recovered")])
            ),
            "avg_rise_recovery_label": _duration_label(
                _median([e["recovery_hours"] for e in rises if e.get("recovered")])
            ),
        })
        return out
    except Exception as exc:
        logger.debug("Falling knife history failed for %s: %s", symbol, exc, exc_info=True)
        out["error"] = str(exc)[:180]
        return out


def scan_falling_knife_history(
    *,
    asset_class: str,
    tickers: list[str],
    threshold_pct: float = 10.0,
    move_side: str = "both",
    from_date: str = "",
    to_date: str = "",
    groww_token: str = "",
    exchange: str = "NSE",
    max_workers: int = 6,
) -> dict[str, Any]:
    ac = (asset_class or "india").strip().lower()
    if ac not in ASSET_CLASS_CONFIG:
        ac = "india"
    cfg = ASSET_CLASS_CONFIG[ac]
    market = str(cfg["market"])
    exchange = exchange or str(cfg.get("exchange") or "NSE")

    symbols = resolve_tickers(ac, tickers)
    seen: set[str] = set()
    uniq: list[str] = []
    for s in symbols:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    symbols = uniq[:80]

    thr = float(max(0.5, min(threshold_pct, 90.0)))
    side = (move_side or "both").lower()
    if side not in ("fall", "rise", "both"):
        side = "both"

    to_utc = _parse_date_bound(to_date, end_of_day=True) or datetime.now(UTC)
    from_utc = _parse_date_bound(from_date, end_of_day=False)
    if from_utc is None:
        from_utc = to_utc - timedelta(days=90)
    if from_utc >= to_utc:
        from_utc = to_utc - timedelta(days=30)

    span_hours = max(24.0, (to_utc - from_utc).total_seconds() / 3600.0)
    # Cap very long spans for intraday — force daily if > ~4 months on 15m
    interval = choose_interval_for_span(span_hours)
    limit = bars_needed_for_span(span_hours, interval)
    sess = session_info(ac)

    results: list[dict[str, Any]] = []
    if not symbols:
        return {
            "strategy": STRATEGY_ID,
            "strategy_label": f"{STRATEGY_NAME} · History",
            "mode": "history",
            "asset_class": ac,
            "threshold_pct": thr,
            "move_side": side,
            "from_date": from_utc.date().isoformat(),
            "to_date": to_utc.date().isoformat(),
            "interval": interval,
            "session": sess,
            "scanned": 0,
            "results": [],
            "plain_english": "No tickers selected.",
            "how_to_read": _how_to(),
        }

    with ThreadPoolExecutor(max_workers=max(2, min(max_workers, 10))) as pool:
        futs = {
            pool.submit(
                analyze_history_ticker,
                sym,
                asset_class=ac,
                market=market,
                threshold_pct=thr,
                move_side=side,
                from_utc=from_utc,
                to_utc=to_utc,
                interval=interval,
                limit=limit,
                groww_token=groww_token,
                exchange=exchange,
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                results.append(row)

    results.sort(
        key=lambda r: (
            0 if r.get("primary_forecast") else 1,
            -(float((r.get("primary_forecast") or {}).get("confidence_pct") or 0)),
            -(int(r.get("event_count") or 0)),
            str(r.get("ticker") or ""),
        )
    )

    total_falls = sum(int(r.get("fall_count") or 0) for r in results)
    total_rises = sum(int(r.get("rise_count") or 0) for r in results)
    with_forecast = [r for r in results if r.get("primary_forecast")]

    bits = []
    for r in with_forecast[:6]:
        pf = r["primary_forecast"]
        bits.append(
            f"{r['ticker']}: next {pf.get('direction')} ~{str(pf.get('predicted_next_time') or '')[:16]} "
            f"({pf.get('confidence_pct')}% conf, move {pf.get('predicted_move_pct')}%)"
        )

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": f"{STRATEGY_NAME} · History",
        "mode": "history",
        "asset_class": ac,
        "asset_label": cfg.get("label"),
        "threshold_pct": thr,
        "move_side": side,
        "from_date": from_utc.date().isoformat(),
        "to_date": to_utc.date().isoformat(),
        "window_start_utc": from_utc.isoformat(),
        "window_end_utc": to_utc.isoformat(),
        "interval": interval,
        "bars_requested": limit,
        "session": sess,
        "scanned": len(results),
        "total_fall_events": total_falls,
        "total_rise_events": total_rises,
        "results": results,
        "summary": {
            "scanned": len(results),
            "fall_events": total_falls,
            "rise_events": total_rises,
            "threshold": f">= {thr}% rise/fall excursion",
            "range": f"{from_utc.date().isoformat()} → {to_utc.date().isoformat()}",
            "move_side": side,
        },
        "plain_english": (
            f"Falling Knife History · {cfg.get('label')} · moves ≥{thr:g}% ({side}) "
            f"from {from_utc.date()} to {to_utc.date()} ({sess['label']}). "
            f"{total_falls} falls · {total_rises} rises across {len(results)} tickers."
            + ((" Forecasts: " + " · ".join(bits) + ".") if bits else "")
        ),
        "how_to_read": _how_to(),
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Predicted datetimes and move sizes are historical medians, not guarantees."
        ),
    }
