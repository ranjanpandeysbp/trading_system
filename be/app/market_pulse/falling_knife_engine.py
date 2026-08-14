"""
falling_knife_engine.py
-----------------------
Scan an asset-class universe for names that have fallen ≥ X% from their
session-window high and/or risen ≥ X% from their session-window low
(live), plus date-range history of threshold rise/fall events with
recovery timing and next-move forecast, plus a from-top mode that finds
names ≥ X% below their high over loop hours with reverse vs
continue odds and confidence.

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


def _session_chart_bars(df: pd.DataFrame, *, max_bars: int = 240) -> list[dict[str, Any]]:
    """OHLCV bars for FE candle/line charts (live Falling Knife)."""
    if df is None or df.empty:
        return []
    work = df.tail(max(20, int(max_bars)))
    rows: list[dict[str, Any]] = []
    for ts, row in work.iterrows():
        try:
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
        except (TypeError, ValueError, KeyError):
            continue
        if any(x != x for x in (o, h, l, c)):
            continue
        t = pd.Timestamp(ts)
        vol = None
        try:
            if "volume" in row and row["volume"] == row["volume"]:
                vol = round(float(row["volume"]), 2)
        except (TypeError, ValueError):
            vol = None
        rows.append({
            "time": t.isoformat(),
            "label": t.strftime("%H:%M") if (t.hour or t.minute) else t.strftime("%Y-%m-%d"),
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": vol,
        })
    return rows


def _live_trade_setup(
    sess: pd.DataFrame,
    *,
    match_kind: str | None,
    matched: bool,
    fall_from_high: float,
    rise_from_low: float,
    thr: float,
    interval: str,
) -> dict[str, Any]:
    """Mean-reversion style setup: fall → long bounce, rise → short fade."""
    from app.market_pulse.pro_trade_shared import (
        ConfidenceScore,
        atr as atr_ind,
        atr_sane_stop_target,
        pack_trade_setup,
    )

    entry = float(sess["close"].iloc[-1])
    high = float(sess["high"].max())
    low = float(sess["low"].min())
    atr_s = atr_ind(sess)
    atr_v = float(atr_s.iloc[-1]) if len(atr_s) and pd.notna(atr_s.iloc[-1]) else None

    if not matched or not match_kind:
        return pack_trade_setup(
            direction="WAIT",
            entry=entry,
            stop=None,
            target=None,
            confidence_pct=15.0,
            reason="No threshold match",
            plain_english="No live fall/rise match — no trade setup.",
            timeframe=interval,
        )

    # Prefer the larger excursion when both matched.
    if match_kind == "both":
        side = "fall" if fall_from_high >= rise_from_low else "rise"
    else:
        side = match_kind

    if side == "fall":
        direction = "LONG"
        stop = low
        # Target mid-range toward the window high (partial bounce).
        mid = low + 0.5 * (high - low)
        target = max(mid, entry + (atr_v or (entry * 0.01)) * 1.5)
        if target <= entry:
            target = entry + abs(entry - stop) * 2.0
        base = f"Fall ≥{thr:g}% off high — mean-reversion long (knife catch)"
    else:
        direction = "SHORT"
        stop = high
        mid = high - 0.5 * (high - low)
        target = min(mid, entry - (atr_v or (entry * 0.01)) * 1.5)
        if target >= entry:
            target = entry - abs(stop - entry) * 2.0
        base = f"Rise ≥{thr:g}% off low — mean-reversion short (fade pump)"

    stop, target, adjusted = atr_sane_stop_target(
        direction, entry, stop, target, atr_v, default_rr=1.8
    )

    excess = (fall_from_high if side == "fall" else rise_from_low) - thr
    score = ConfidenceScore(42.0, base)
    score.add(matched, 10, "Live window matched threshold", "No match")
    score.add(excess >= thr * 0.5, 12, "Move well beyond threshold", "Barely at threshold")
    score.add(excess >= thr, 8, "Move ≥2× threshold — strong extension", None)
    score.add(atr_v is not None, 6, "ATR available for stop sanity", "No ATR")
    score.add(not adjusted, 4, "Stop fits ATR band", "Stop ATR-adjusted")
    if side == "fall":
        score.add(fall_from_high >= thr, 8, f"Off high −{fall_from_high:.1f}%", None)
    else:
        score.add(rise_from_low >= thr, 8, f"Off low +{rise_from_low:.1f}%", None)

    conf, reasons = score.finalize()
    setup = pack_trade_setup(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        confidence_pct=conf,
        confidence_reasons=reasons,
        stop_adjusted=adjusted,
        timeframe=interval,
    )
    setup["reason"] = (
        f"{setup['action']}: {base} · conf {conf:.0f}% · "
        f"SL {setup.get('sl_pct') or 0:.1f}% · TP {setup.get('tp_pct') or 0:.1f}%"
    )
    setup["plain_english"] = (
        f"{'Buy the dip' if direction == 'LONG' else 'Fade the pump'} after a "
        f"{'−' if side == 'fall' else '+'}{(fall_from_high if side == 'fall' else rise_from_low):.1f}% "
        f"window move. Risk {setup.get('sl_pct') or 0:.1f}% · aim {setup.get('tp_pct') or 0:.1f}% · "
        f"confidence {conf:.0f}% (grade {setup.get('grade')})."
    )
    return setup


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

        trade_setup = _live_trade_setup(
            sess,
            match_kind=match_kind,
            matched=matched,
            fall_from_high=fall_from_high,
            rise_from_low=rise_from_low,
            thr=thr,
            interval=interval,
        )

        # Same Fall/Rise next-move forecasts as History (from ~90d daily bars).
        forecast_block = fetch_and_build_move_forecasts(
            symbol,
            asset_class=asset_class,
            market=market,
            threshold_pct=thr,
            move_side=side,
            groww_token=groww_token,
            exchange=exchange,
            lookback_days=90,
            entry=last,
        )

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
            "chart_data": _session_chart_bars(sess, max_bars=240),
            "trade_setup": trade_setup,
            "confidence_pct": trade_setup.get("confidence_pct"),
            "sl_pct": trade_setup.get("sl_pct"),
            "tp_pct": trade_setup.get("tp_pct"),
            "action": trade_setup.get("action"),
            "setup_direction": trade_setup.get("direction"),
            "forecast": forecast_block.get("forecast") or {},
            "primary_forecast": forecast_block.get("primary_forecast"),
            "fall_count": forecast_block.get("fall_count"),
            "rise_count": forecast_block.get("rise_count"),
            "forecast_threshold_pct": forecast_block.get("forecast_threshold_pct"),
            "forecast_error": forecast_block.get("forecast_error"),
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
                from app.market_pulse.asset_class_config import attach_ticker_name

                results.append(attach_ticker_name(row, asset_class=ac))

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
        "Live also builds Fall/Rise next-move forecasts (same as History) from ~90d daily history — Conf %, SL %, TP %.",
        "History mode: set a date range + threshold % — counts every rise/fall ≥ X%, gaps, recovery, and next-move forecast.",
        "From top mode: find names down ≥ X% from their high in the last loop hours; estimate reverse vs continue odds + upside % + confidence.",
        "Runup / Descent mode: last X hours on 1+ timeframes — early major runups still extending, or exhausted tops now descending.",
        "Runup % = rise from swing-low start · Descent % = fall from window peak (toppest point).",
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


def pick_primary_forecast(
    forecast: dict[str, Any],
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any] | None:
    """Soonest future fall/rise slot; else highest-confidence side (never a past datetime)."""
    if not forecast:
        return None
    now = now_utc or datetime.now(UTC)
    candidates = [forecast[k] for k in ("fall", "rise") if k in forecast and forecast[k]]
    if not candidates:
        return None
    future: list[tuple[Any, dict[str, Any]]] = []
    now_ts = _as_utc_ts(now)
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
        return future[0][1]

    primary = max(candidates, key=lambda c: float(c.get("confidence_pct") or 0))
    if primary.get("predicted_next_time"):
        try:
            if _as_utc_ts(primary["predicted_next_time"]) < now_ts:
                return {
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
    return primary


def build_fall_rise_forecasts_from_df(
    df: pd.DataFrame,
    *,
    threshold_pct: float = 10.0,
    move_side: str = "both",
    timeframe: str = "1d",
    now_utc: datetime | None = None,
    entry: float | None = None,
) -> dict[str, Any]:
    """
    Build Fall + Rise next-move forecasts (plain English, conf %, SL %, TP %)
    from OHLC history. Used by Live scan, History, Ticker Chart, BB-RSI-VOL.
    Works for India / US / Crypto / Commodities — same event math on the bars given.
    """
    empty: dict[str, Any] = {
        "forecast": {},
        "primary_forecast": None,
        "events": [],
        "fall_count": 0,
        "rise_count": 0,
        "event_count": 0,
    }
    if df is None or df.empty or len(df) < 8:
        return empty

    work = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["high", "low", "close"])
    if len(work) < 8:
        return empty

    side = (move_side or "both").lower()
    if side not in ("fall", "rise", "both"):
        side = "both"
    thr = float(max(0.5, min(threshold_pct, 90.0)))
    now = now_utc or datetime.now(UTC)

    events = detect_threshold_events(work, thr, move_side=side)
    falls = [e for e in events if e["direction"] == "fall"]
    rises = [e for e in events if e["direction"] == "rise"]

    forecast: dict[str, Any] = {}
    if side in ("fall", "both"):
        f = _forecast_from_events(events, direction="fall", now_utc=now)
        if f:
            forecast["fall"] = f
    if side in ("rise", "both"):
        r = _forecast_from_events(events, direction="rise", now_utc=now)
        if r:
            forecast["rise"] = r

    try:
        last = float(entry) if entry is not None else float(work["close"].iloc[-1])
    except (TypeError, ValueError):
        last = float(work["close"].iloc[-1])

    from app.market_pulse.pro_trade_shared import atr as atr_ind, enrich_forecast_trade_setup

    atr_s = atr_ind(work)
    atr_v = float(atr_s.iloc[-1]) if len(atr_s) and pd.notna(atr_s.iloc[-1]) else None
    for key in ("fall", "rise"):
        if key in forecast:
            enrich_forecast_trade_setup(
                forecast[key],
                entry=last,
                atr_value=atr_v,
                timeframe=timeframe,
            )

    primary = pick_primary_forecast(forecast, now_utc=now)
    return {
        "forecast": forecast,
        "primary_forecast": primary,
        "events": events,
        "fall_count": len(falls),
        "rise_count": len(rises),
        "event_count": len(events),
        "forecast_threshold_pct": thr,
        "forecast_bars": int(len(work)),
        "forecast_interval": timeframe,
    }


def fetch_and_build_move_forecasts(
    symbol: str,
    *,
    asset_class: str,
    market: str,
    threshold_pct: float = 10.0,
    move_side: str = "both",
    groww_token: str = "",
    exchange: str = "NSE",
    lookback_days: int = 90,
    entry: float | None = None,
) -> dict[str, Any]:
    """Fetch ~lookback_days of daily bars and build Fall/Rise forecasts for any asset class."""
    days = int(max(30, min(lookback_days, 365)))
    try:
        raw = fetch_data_for_gap_scan(
            symbol,
            "1d",
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=int(days * 1.5) + 20,
        )
        df = normalize_ohlcv(raw) if raw is not None else pd.DataFrame()
    except Exception as exc:
        logger.debug("Forecast fetch failed for %s: %s", symbol, exc)
        return {
            "forecast": {},
            "primary_forecast": None,
            "events": [],
            "fall_count": 0,
            "rise_count": 0,
            "event_count": 0,
            "forecast_error": str(exc)[:160],
        }

    if df is None or df.empty:
        return {
            "forecast": {},
            "primary_forecast": None,
            "events": [],
            "fall_count": 0,
            "rise_count": 0,
            "event_count": 0,
            "forecast_error": "No daily bars for forecast",
        }

    end_utc = datetime.now(UTC)
    start_utc = end_utc - timedelta(days=days)
    sess = filter_session_bars(df, asset_class, start_utc=start_utc, end_utc=end_utc)
    if sess is None or sess.empty or len(sess) < 8:
        # Crypto / some feeds may already be clean — use raw tail
        sess = df.tail(days + 5)

    return build_fall_rise_forecasts_from_df(
        sess,
        threshold_pct=threshold_pct,
        move_side=move_side,
        timeframe="1d",
        entry=entry,
    )


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

        last = float(sess["close"].iloc[-1])
        block = build_fall_rise_forecasts_from_df(
            sess,
            threshold_pct=threshold_pct,
            move_side=move_side,
            timeframe=interval,
            entry=last,
        )
        forecast = block.get("forecast") or {}
        primary = block.get("primary_forecast")
        trade_setup = (primary or {}).get("trade_setup") if primary else None
        out.update({
            "events": events,
            "fall_count": len(falls),
            "rise_count": len(rises),
            "event_count": len(events),
            "forecast": forecast,
            "primary_forecast": primary,
            "trade_setup": trade_setup,
            "confidence_pct": (
                (trade_setup or {}).get("confidence_pct")
                if trade_setup
                else (primary or {}).get("confidence_pct")
            ),
            "sl_pct": (trade_setup or {}).get("sl_pct") if trade_setup else None,
            "tp_pct": (trade_setup or {}).get("tp_pct") if trade_setup else None,
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
            "chart_data": _session_chart_bars(sess, max_bars=300),
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
                from app.market_pulse.asset_class_config import attach_ticker_name

                results.append(attach_ticker_name(row, asset_class=ac))

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
            f"{r.get('display_label') or r['ticker']}: next {pf.get('direction')} ~{str(pf.get('predicted_next_time') or '')[:16]} "
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


# ---------------------------------------------------------------------------
# From-top mode: peak drawdown ≥ X% over loop hours + reverse / continue odds
# ---------------------------------------------------------------------------

_FROM_TOP_ANALOGUE_SPACING = 8
_FROM_TOP_DD_BAND_PCT = 8.0  # match historical drawdowns within ±8 pp of current


def _from_top_forward_bars(peak_window: int, interval: str) -> int:
    """Outcome window ≈ half the loop (capped) so intraday scans stay responsive."""
    base = max(6, min(int(peak_window * 0.5), 80))
    if interval == "1d":
        return max(10, min(base, 63))
    return base


def _from_top_confidence(n: int, reverse_rate: float | None, continue_rate: float | None) -> float:
    """Sample-size + conviction (how far rates sit from a coin-flip)."""
    if n <= 0:
        return 12.0
    base = min(52.0, 16.0 + n * 4.5)
    r = float(reverse_rate or 50.0)
    c = float(continue_rate or 50.0)
    edge = abs(max(r, c) - 50.0) / 50.0
    base += edge * 28.0
    if n < 3:
        base = min(base, 32.0)
    return round(float(np.clip(base, 12.0, 88.0)), 1)


def _collect_drawdown_analogues(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    *,
    current_dd: float,
    threshold_pct: float,
    peak_window: int,
    forward_bars: int,
    band_pct: float = _FROM_TOP_DD_BAND_PCT,
    spacing: int = _FROM_TOP_ANALOGUE_SPACING,
    min_reverse_pct: float = 1.5,
    min_continue_pct: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Find past bars where rolling-peak drawdown was similar to *current_dd*
    and measure forward max bounce vs further decline.
    """
    n = len(closes)
    if n < peak_window + forward_bars + 10:
        return []

    thr = float(max(0.5, threshold_pct))
    lo = max(thr, current_dd - band_pct)
    hi = current_dd + band_pct
    analogues: list[dict[str, Any]] = []
    last_i = -spacing

    for i in range(peak_window - 1, n - forward_bars):
        if i - last_i < spacing:
            continue
        window_high = float(np.nanmax(highs[i - peak_window + 1 : i + 1]))
        c = float(closes[i])
        if not np.isfinite(window_high) or window_high <= 0 or not np.isfinite(c) or c <= 0:
            continue
        dd = ((window_high - c) / window_high) * 100.0
        if dd < lo or dd > hi:
            continue

        fwd_high = float(np.nanmax(highs[i + 1 : i + 1 + forward_bars]))
        fwd_low = float(np.nanmin(lows[i + 1 : i + 1 + forward_bars]))
        fwd_close = float(closes[i + forward_bars])
        if not all(np.isfinite(x) for x in (fwd_high, fwd_low, fwd_close)):
            continue

        max_up = max(0.0, ((fwd_high - c) / c) * 100.0)
        max_down = max(0.0, ((c - fwd_low) / c) * 100.0)
        end_ret = ((fwd_close - c) / c) * 100.0
        reverse_floor = max(min_reverse_pct, dd * 0.30)
        continue_floor = max(min_continue_pct, dd * 0.20)
        if max_up >= reverse_floor and max_up >= max_down:
            outcome = "reverse"
        elif max_down >= continue_floor and max_down > max_up:
            outcome = "continue"
        else:
            outcome = "mixed"

        room_to_peak = max(0.0, ((window_high - c) / c) * 100.0)
        recovered_to_peak = fwd_high >= window_high * 0.995

        analogues.append({
            "index": i,
            "drawdown_pct": _r(dd, 2),
            "max_up_pct": _r(max_up, 2),
            "max_down_pct": _r(max_down, 2),
            "end_return_pct": _r(end_ret, 2),
            "outcome": outcome,
            "room_to_peak_pct": _r(room_to_peak, 2),
            "recovered_to_peak": recovered_to_peak,
        })
        last_i = i

    return analogues


def analyze_from_top_ticker(
    symbol: str,
    *,
    asset_class: str,
    market: str,
    drop_pct: float,
    lookback_hours: float,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """One ticker: peak drawdown in last loop hours + reverse/continue forecast."""
    hours = float(max(1.0, min(lookback_hours, 336.0)))
    thr = float(max(0.5, min(drop_pct, 90.0)))
    interval = choose_interval(hours)
    # Extra history so analogues can form before the current loop window
    hist_hours = min(336.0 * 3, max(hours * 12, hours + 72.0))
    limit = bars_needed(hist_hours, interval)
    end_utc = datetime.now(UTC)
    start_utc = end_utc - timedelta(hours=hours)
    hist_start = end_utc - timedelta(hours=hist_hours)

    out: dict[str, Any] = {
        "ticker": symbol,
        "matched": False,
        "lookback_hours": hours,
        "loop_hours": hours,
        "threshold_pct": thr,
        "interval": interval,
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
            out["error"] = "Insufficient bars"
            return out

        work = df.copy()
        for col in ("open", "high", "low", "close"):
            if col in work.columns:
                work[col] = pd.to_numeric(work[col], errors="coerce")
        work = work.dropna(subset=["high", "low", "close"])
        if len(work) < 8:
            out["error"] = "Insufficient clean bars"
            return out

        hist = filter_session_bars(work, asset_class, start_utc=hist_start, end_utc=end_utc)
        if hist is None or hist.empty or len(hist) < 8:
            hist = work.tail(min(len(work), limit))

        win = filter_session_bars(hist, asset_class, start_utc=start_utc, end_utc=end_utc)
        if win is None or win.empty or len(win) < 2:
            # Fall back to last N bars approximating the loop length
            approx = max(4, min(len(hist), bars_needed(hours, interval) // 2))
            win = hist.tail(approx)

        peak_high = float(win["high"].max())
        peak_ts = win["high"].idxmax()
        last = float(hist["close"].iloc[-1])
        last_ts = hist.index[-1]
        if peak_high <= 0 or last <= 0:
            out["error"] = "Invalid peak/last"
            return out

        fall_from_top = ((peak_high - last) / peak_high) * 100.0
        matched = fall_from_top >= thr
        hours_since_peak = _hours_between(peak_ts, last_ts)

        peak_window = max(4, len(win))
        forward_bars = _from_top_forward_bars(peak_window, interval)
        # Need enough history for rolling peak + forward outcomes
        min_hist = peak_window + forward_bars + 15
        if len(hist) < min_hist:
            # Use whatever we have; analogues may be sparse
            pass

        highs = hist["high"].astype(float).values
        lows = hist["low"].astype(float).values
        closes = hist["close"].astype(float).values
        analogue_peak_win = min(peak_window, max(4, len(hist) // 3))
        min_rev = 5.0 if interval == "1d" else 1.5
        min_cont = 4.0 if interval == "1d" else 1.0
        analogues = _collect_drawdown_analogues(
            highs,
            lows,
            closes,
            current_dd=fall_from_top,
            threshold_pct=thr,
            peak_window=analogue_peak_win,
            forward_bars=forward_bars,
            min_reverse_pct=min_rev,
            min_continue_pct=min_cont,
        )

        n = len(analogues)
        rev_n = sum(1 for a in analogues if a["outcome"] == "reverse")
        cont_n = sum(1 for a in analogues if a["outcome"] == "continue")
        mix_n = n - rev_n - cont_n
        reverse_pct = (100.0 * rev_n / n) if n else None
        continue_pct = (100.0 * cont_n / n) if n else None
        mixed_pct = (100.0 * mix_n / n) if n else None

        rev_ups = [float(a["max_up_pct"]) for a in analogues if a["outcome"] == "reverse"]
        all_ups = [float(a["max_up_pct"]) for a in analogues]
        cont_downs = [float(a["max_down_pct"]) for a in analogues if a["outcome"] == "continue"]
        all_downs = [float(a["max_down_pct"]) for a in analogues]
        end_rets = [float(a["end_return_pct"]) for a in analogues]
        peak_hits = sum(1 for a in analogues if a.get("recovered_to_peak"))

        upside_if_reverse = _median(rev_ups) if rev_ups else _median(all_ups)
        further_fall_if_continue = _median(cont_downs) if cont_downs else _median(all_downs)
        typical_end_return = _median(end_rets)
        room_to_peak = ((peak_high - last) / last) * 100.0 if last > 0 else None
        if upside_if_reverse is not None and room_to_peak is not None:
            upside_to_peak = min(float(upside_if_reverse), float(room_to_peak))
        else:
            upside_to_peak = upside_if_reverse

        conf = _from_top_confidence(n, reverse_pct, continue_pct)

        if n == 0:
            bias = "unknown"
            bias_label = "Insufficient analogues"
        elif (reverse_pct or 0) >= (continue_pct or 0) + 5:
            bias = "reverse"
            bias_label = "Likely reverse / bounce"
        elif (continue_pct or 0) >= (reverse_pct or 0) + 5:
            bias = "continue"
            bias_label = "Likely continued fall"
        else:
            bias = "mixed"
            bias_label = "Mixed / no clear edge"

        fwd_label = _duration_label(forward_bars * (hours / max(peak_window, 1))) or f"{forward_bars} bars"
        plain = (
            f"{symbol} is −{fall_from_top:.1f}% from its {hours:g}h loop high "
            f"({_fmt_ts(peak_ts)[:16]} @ {_r(peak_high, 4)}). "
        )
        if n:
            plain += (
                f"At similar −{thr:g}%+ drawdowns historically ({n} analogues, ~{fwd_label} forward): "
                f"reverse {reverse_pct:.0f}% · continue {continue_pct:.0f}%"
                + (f" · mixed {mixed_pct:.0f}%" if mix_n else "")
                + f". If reverse, typical bounce ~{upside_if_reverse or 0:.1f}% "
                f"(~{upside_to_peak or 0:.1f}% toward peak room). "
                f"If continue, typical further decline ~{further_fall_if_continue or 0:.1f}%. "
                f"Bias: {bias_label} · confidence {conf:.0f}%."
            )
        else:
            plain += "Not enough similar historical drawdowns to score reverse vs continue odds."

        from app.market_pulse.pro_trade_shared import atr as atr_ind, pack_trade_setup, atr_sane_stop_target

        atr_s = atr_ind(hist)
        atr_v = float(atr_s.iloc[-1]) if len(atr_s) and pd.notna(atr_s.iloc[-1]) else None
        tail_n = min(20, len(hist))
        if matched and bias == "reverse" and upside_to_peak and upside_to_peak > 0:
            stop = float(hist["low"].tail(tail_n).min())
            target = last * (1.0 + float(upside_to_peak) / 100.0)
            stop, target, adjusted = atr_sane_stop_target(
                "LONG", last, stop, target, atr_v, default_rr=1.6
            )
            trade_setup = pack_trade_setup(
                direction="LONG",
                entry=last,
                stop=stop,
                target=target,
                confidence_pct=conf,
                reason=f"From-top bounce bias · −{fall_from_top:.1f}% off {hours:g}h high",
                plain_english=plain,
                timeframe=interval,
                stop_adjusted=adjusted,
            )
        elif matched and bias == "continue" and further_fall_if_continue and further_fall_if_continue > 0:
            stop = float(hist["high"].tail(tail_n).max())
            target = last * (1.0 - float(further_fall_if_continue) / 100.0)
            stop, target, adjusted = atr_sane_stop_target(
                "SHORT", last, stop, target, atr_v, default_rr=1.6
            )
            trade_setup = pack_trade_setup(
                direction="SHORT",
                entry=last,
                stop=stop,
                target=target,
                confidence_pct=conf,
                reason=f"From-top continuation bias · −{fall_from_top:.1f}% off {hours:g}h high",
                plain_english=plain,
                timeframe=interval,
                stop_adjusted=adjusted,
            )
        else:
            trade_setup = pack_trade_setup(
                direction="WAIT",
                entry=last,
                stop=None,
                target=None,
                confidence_pct=conf if matched else 15.0,
                reason="No clear from-top trade bias" if matched else "Below threshold / not matched",
                plain_english=plain,
                timeframe=interval,
            )

        out.update({
            "matched": matched,
            "last": _r(last, 4),
            "peak_high": _r(peak_high, 4),
            "peak_time": _fmt_ts(peak_ts),
            "peak_time_ist": _fmt_ts_ist(peak_ts),
            "as_of": _fmt_ts(last_ts),
            "as_of_ist": _fmt_ts_ist(last_ts),
            "hours_since_peak": hours_since_peak,
            "hours_since_peak_label": _duration_label(hours_since_peak),
            "fall_from_top_pct": _r(fall_from_top, 2),
            "room_to_peak_pct": _r(room_to_peak, 2) if room_to_peak is not None else None,
            "bars_used": int(len(hist)),
            "bars_in_loop": int(len(win)),
            "peak_window_bars": analogue_peak_win,
            "forward_bars": forward_bars,
            "analogues": n,
            "reverse_count": rev_n,
            "continue_count": cont_n,
            "mixed_count": mix_n,
            "reverse_chance_pct": _r(reverse_pct, 1) if reverse_pct is not None else None,
            "continue_chance_pct": _r(continue_pct, 1) if continue_pct is not None else None,
            "mixed_chance_pct": _r(mixed_pct, 1) if mixed_pct is not None else None,
            "upside_if_reverse_pct": _r(upside_if_reverse, 2) if upside_if_reverse is not None else None,
            "upside_toward_peak_pct": _r(upside_to_peak, 2) if upside_to_peak is not None else None,
            "further_fall_if_continue_pct": (
                _r(further_fall_if_continue, 2) if further_fall_if_continue is not None else None
            ),
            "typical_end_return_pct": _r(typical_end_return, 2) if typical_end_return is not None else None,
            "recovered_to_peak_rate_pct": _r(100.0 * peak_hits / n, 1) if n else None,
            "bias": bias,
            "bias_label": bias_label,
            "confidence_pct": conf,
            "plain_english": plain,
            "trade_setup": trade_setup,
            "chart_data": _session_chart_bars(win, max_bars=300),
            "recent_analogues": analogues[-8:],
        })
        return out
    except Exception as exc:
        logger.debug("From-top scan failed for %s: %s", symbol, exc, exc_info=True)
        out["error"] = str(exc)[:180]
        return out


def scan_falling_knife_from_top(
    *,
    asset_class: str,
    tickers: list[str],
    drop_pct: float = 20.0,
    lookback_hours: float = 24.0,
    groww_token: str = "",
    exchange: str = "NSE",
    max_workers: int = 6,
) -> dict[str, Any]:
    """Universe scan: names ≥ X% below their high in the last loop hours."""
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

    thr = float(max(0.5, min(drop_pct, 90.0)))
    hours = float(max(1.0, min(lookback_hours, 336.0)))
    interval = choose_interval(hours)
    sess = session_info(ac)

    results: list[dict[str, Any]] = []
    if not symbols:
        return {
            "strategy": STRATEGY_ID,
            "strategy_label": f"{STRATEGY_NAME} · From top",
            "mode": "from_top",
            "asset_class": ac,
            "drop_pct": thr,
            "lookback_hours": hours,
            "loop_hours": hours,
            "interval": interval,
            "session": sess,
            "scanned": 0,
            "matched": 0,
            "results": [],
            "knives": [],
            "plain_english": "No tickers selected.",
            "how_to_read": _how_to(),
        }

    with ThreadPoolExecutor(max_workers=max(2, min(max_workers, 10))) as pool:
        futs = {
            pool.submit(
                analyze_from_top_ticker,
                sym,
                asset_class=ac,
                market=market,
                drop_pct=thr,
                lookback_hours=hours,
                groww_token=groww_token,
                exchange=exchange,
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                from app.market_pulse.asset_class_config import attach_ticker_name

                results.append(attach_ticker_name(row, asset_class=ac))

    results.sort(
        key=lambda r: (
            0 if r.get("matched") else 1,
            -(float(r.get("fall_from_top_pct") or 0)),
            -(float(r.get("confidence_pct") or 0)),
            str(r.get("ticker") or ""),
        )
    )
    knives = [r for r in results if r.get("matched")]
    errors = sum(1 for r in results if r.get("error"))

    bits = []
    for r in knives[:6]:
        bits.append(
            f"{r.get('display_label') or r['ticker']}: −{r.get('fall_from_top_pct')}% off top · "
            f"rev {r.get('reverse_chance_pct')}% / cont {r.get('continue_chance_pct')}% · "
            f"conf {r.get('confidence_pct')}%"
            + (
                f" · upside ~{r.get('upside_if_reverse_pct')}%"
                if r.get("upside_if_reverse_pct") is not None
                else ""
            )
        )

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": f"{STRATEGY_NAME} · From top",
        "mode": "from_top",
        "asset_class": ac,
        "asset_label": cfg.get("label"),
        "drop_pct": thr,
        "threshold_pct": thr,
        "lookback_hours": hours,
        "loop_hours": hours,
        "interval": interval,
        "session": sess,
        "scanned": len(results),
        "matched": len(knives),
        "errors": errors,
        "results": results,
        "knives": knives,
        "summary": {
            "scanned": len(results),
            "matched": len(knives),
            "errors": errors,
            "threshold": f">= {thr:g}% below {hours:g}h high",
            "lookback": f"last {hours:g}h (loop)",
            "interval": interval,
        },
        "plain_english": (
            f"Falling Knife · From top · {cfg.get('label')} · "
            f"≥{thr:g}% below high in last {hours:g}h loop. "
            f"Matched {len(knives)} / {len(results)}."
            + ((" Top: " + " · ".join(bits) + ".") if bits else "")
        ),
        "how_to_read": _how_to(),
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Reverse/continue odds are historical analogue rates, not guarantees."
        ),
    }


# ---------------------------------------------------------------------------
# Runup / Descent mode — early major runups + exhausted tops descending
# ---------------------------------------------------------------------------

RUNUP_DESCENT_TFS = ("5m", "15m", "30m", "1h", "4h", "1d")


def _fmt_bar_ts(ts) -> str:
    try:
        return pd.Timestamp(ts).isoformat()
    except Exception:
        return str(ts)


def _recent_change_pct(closes: pd.Series, frac: float = 0.2) -> float:
    n = len(closes)
    if n < 3:
        return 0.0
    start = max(0, n - max(2, int(n * frac)))
    a = float(closes.iloc[start])
    b = float(closes.iloc[-1])
    if a <= 0 or not np.isfinite(a) or not np.isfinite(b):
        return 0.0
    return ((b / a) - 1.0) * 100.0


def _classify_runup_descent(
    sess: pd.DataFrame,
    *,
    thr_pct: float,
    interval: str,
) -> dict[str, Any] | None:
    """Classify one timeframe window as early runup, continuing descent, or neither."""
    if sess is None or sess.empty or len(sess) < 8:
        return None

    work = sess.copy()
    for col in ("open", "high", "low", "close"):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["high", "low", "close"])
    if len(work) < 8:
        return None

    highs = work["high"]
    lows = work["low"]
    closes = work["close"]
    n = len(work)
    last = float(closes.iloc[-1])
    if last <= 0 or not np.isfinite(last):
        return None

    trough_i = int(lows.values.argmin())
    after = highs.iloc[trough_i:]
    if after.empty:
        return None
    peak_rel = int(after.values.argmax())
    peak_i = trough_i + peak_rel
    global_peak_i = int(highs.values.argmax())
    if global_peak_i >= trough_i and float(highs.iloc[global_peak_i]) >= float(highs.iloc[peak_i]):
        peak_i = global_peak_i

    trough = float(lows.iloc[trough_i])
    peak = float(highs.iloc[peak_i])
    if trough <= 0 or peak <= 0:
        return None

    rise_from_start = ((last - trough) / trough) * 100.0
    fall_from_top = ((peak - last) / peak) * 100.0
    trough_pos = trough_i / max(n - 1, 1)
    peak_pos = peak_i / max(n - 1, 1)
    recent_chg = _recent_change_pct(closes, 0.22)
    near_high = fall_from_top <= max(1.0, thr_pct * 0.35)
    topped = peak_pos <= 0.85
    early_leg = trough_pos <= 0.75 and (n - 1 - trough_i) >= 3

    phase = None
    continue_score = 0.0
    reason = ""

    if (
        early_leg
        and rise_from_start >= thr_pct
        and recent_chg > 0.15
        and near_high
        and peak_pos >= 0.55
    ):
        phase = "runup"
        continue_score = (
            min(40.0, rise_from_start) * 0.55
            + max(0.0, recent_chg) * 1.4
            + max(0.0, 12.0 - fall_from_top) * 1.2
            + (1.0 - trough_pos) * 8.0
        )
        reason = (
            f"Early runup on {interval}: +{rise_from_start:.1f}% from swing-low start, "
            f"still near highs (−{fall_from_top:.1f}% off peak), recent momentum +{recent_chg:.1f}%."
        )
    elif (
        topped
        and fall_from_top >= thr_pct
        and recent_chg < -0.15
        and peak_i < n - 2
        and peak_pos >= 0.15
    ):
        phase = "descent"
        continue_score = (
            min(40.0, fall_from_top) * 0.6
            + abs(min(0.0, recent_chg)) * 1.5
            + max(0.0, peak_pos - 0.2) * 10.0
            + max(0.0, rise_from_start) * 0.08
        )
        reason = (
            f"Descent on {interval}: −{fall_from_top:.1f}% from toppest point, "
            f"prior leg was +{rise_from_start:.1f}% off the low, recent momentum {recent_chg:.1f}%."
        )

    if phase is None:
        return {
            "interval": interval,
            "phase": None,
            "matched": False,
            "rise_from_start_pct": _r(rise_from_start, 2),
            "fall_from_top_pct": _r(fall_from_top, 2),
            "recent_change_pct": _r(recent_chg, 2),
            "last": _r(last, 4),
            "runup_start": _r(trough, 4),
            "peak": _r(peak, 4),
            "runup_start_time": _fmt_bar_ts(work.index[trough_i]),
            "peak_time": _fmt_bar_ts(work.index[peak_i]),
            "bars": n,
        }

    return {
        "interval": interval,
        "phase": phase,
        "matched": True,
        "continue_score": _r(continue_score, 2),
        "rise_from_start_pct": _r(rise_from_start, 2),
        "fall_from_top_pct": _r(fall_from_top, 2),
        "recent_change_pct": _r(recent_chg, 2),
        "last": _r(last, 4),
        "runup_start": _r(trough, 4),
        "peak": _r(peak, 4),
        "runup_start_time": _fmt_bar_ts(work.index[trough_i]),
        "peak_time": _fmt_bar_ts(work.index[peak_i]),
        "trough_pos": _r(trough_pos, 3),
        "peak_pos": _r(peak_pos, 3),
        "bars": n,
        "reason": reason,
        "will_continue": True,
    }


def _analyze_runup_descent_symbol(
    symbol: str,
    *,
    asset_class: str,
    market: str,
    thr_pct: float,
    lookback_hours: float,
    timeframes: list[str],
    move_side: str,
    groww_token: str,
    exchange: str,
    start_utc: datetime,
    end_utc: datetime,
    include_charts: bool,
) -> dict[str, Any] | None:
    side = (move_side or "both").lower()
    if side not in ("runup", "descent", "both", "rise", "fall"):
        side = "both"
    if side == "rise":
        side = "runup"
    if side == "fall":
        side = "descent"

    tf_rows: list[dict[str, Any]] = []
    chart_by_tf: dict[str, list[dict[str, Any]]] = {}

    for interval in timeframes:
        try:
            limit = bars_needed(lookback_hours, interval if interval != "4h" else "1h")
            if interval == "4h":
                limit = max(limit, 120)
            raw = fetch_data_for_gap_scan(
                symbol,
                interval,
                market,
                groww_token=groww_token,
                exchange=exchange,
                limit=limit,
            )
            df = normalize_ohlcv(raw) if raw is not None else pd.DataFrame()
            if df is None or df.empty:
                tf_rows.append({"interval": interval, "matched": False, "error": "No bars"})
                continue
            sess = filter_session_bars(df, asset_class, start_utc=start_utc, end_utc=end_utc)
            hit = _classify_runup_descent(sess, thr_pct=thr_pct, interval=interval)
            if hit is None:
                tf_rows.append({"interval": interval, "matched": False, "error": "Insufficient session bars"})
                continue
            tf_rows.append(hit)
            if include_charts and not sess.empty:
                chart_by_tf[interval] = _session_chart_bars(sess, max_bars=220)
        except Exception as exc:
            logger.debug("Runup/descent TF %s failed for %s: %s", interval, symbol, exc)
            tf_rows.append({"interval": interval, "matched": False, "error": str(exc)[:120]})

    runups = [r for r in tf_rows if r.get("matched") and r.get("phase") == "runup"]
    descents = [r for r in tf_rows if r.get("matched") and r.get("phase") == "descent"]

    want_runup = side in ("runup", "both")
    want_descent = side in ("descent", "both")
    match_runup = want_runup and bool(runups)
    match_descent = want_descent and bool(descents)
    matched = match_runup or match_descent

    best_runup = max(runups, key=lambda r: float(r.get("continue_score") or 0)) if runups else None
    best_descent = max(descents, key=lambda r: float(r.get("continue_score") or 0)) if descents else None

    if match_runup and match_descent:
        br = float((best_runup or {}).get("continue_score") or 0)
        bd = float((best_descent or {}).get("continue_score") or 0)
        primary = best_runup if br >= bd else best_descent
        match_kind = "both"
    elif match_runup:
        primary = best_runup
        match_kind = "runup"
    elif match_descent:
        primary = best_descent
        match_kind = "descent"
    else:
        primary = None
        match_kind = None

    primary_tf = str((primary or {}).get("interval") or (timeframes[0] if timeframes else "15m"))
    chart_data = chart_by_tf.get(primary_tf) if include_charts else []

    trade_setup = None
    if matched and primary:
        if primary.get("phase") == "runup":
            conf = min(88.0, 45.0 + float(primary.get("continue_score") or 0) * 0.35)
            trade_setup = {
                "action": "BUY",
                "direction": "long",
                "confidence_pct": _r(conf, 1),
                "sl_pct": _r(max(1.2, min(8.0, float(primary.get("rise_from_start_pct") or 5) * 0.25)), 2),
                "tp_pct": _r(max(1.5, min(12.0, float(primary.get("rise_from_start_pct") or 5) * 0.35)), 2),
                "reason": primary.get("reason") or "Runup continuation",
                "timeframe": primary_tf,
                "plain_english": primary.get("reason"),
            }
        else:
            conf = min(88.0, 45.0 + float(primary.get("continue_score") or 0) * 0.35)
            trade_setup = {
                "action": "SELL",
                "direction": "short",
                "confidence_pct": _r(conf, 1),
                "sl_pct": _r(max(1.2, min(8.0, float(primary.get("fall_from_top_pct") or 5) * 0.25)), 2),
                "tp_pct": _r(max(1.5, min(12.0, float(primary.get("fall_from_top_pct") or 5) * 0.35)), 2),
                "reason": primary.get("reason") or "Descent continuation",
                "timeframe": primary_tf,
                "plain_english": primary.get("reason"),
            }

    score = 0.0
    if best_runup and match_runup:
        score = max(score, float(best_runup.get("continue_score") or 0))
    if best_descent and match_descent:
        score = max(score, float(best_descent.get("continue_score") or 0))

    return {
        "ticker": symbol,
        "matched": matched,
        "match_kind": match_kind,
        "match_runup": match_runup,
        "match_descent": match_descent,
        "match_score": _r(score, 2),
        "rise_from_start_pct": (best_runup or primary or {}).get("rise_from_start_pct"),
        "fall_from_top_pct": (best_descent or primary or {}).get("fall_from_top_pct"),
        "runup_start": (best_runup or primary or {}).get("runup_start"),
        "peak": (best_descent or primary or {}).get("peak"),
        "runup_start_time": (best_runup or primary or {}).get("runup_start_time"),
        "peak_time": (best_descent or primary or {}).get("peak_time"),
        "last": (primary or {}).get("last"),
        "primary_phase": (primary or {}).get("phase"),
        "primary_interval": primary_tf,
        "timeframes_matched": [r["interval"] for r in tf_rows if r.get("matched")],
        "runup_timeframes": [r["interval"] for r in runups],
        "descent_timeframes": [r["interval"] for r in descents],
        "tf_details": tf_rows,
        "best_runup": best_runup,
        "best_descent": best_descent,
        "reason": (primary or {}).get("reason"),
        "will_continue": bool(matched),
        "chart_data": chart_data or [],
        "trade_setup": trade_setup,
        "confidence_pct": (trade_setup or {}).get("confidence_pct"),
        "sl_pct": (trade_setup or {}).get("sl_pct"),
        "tp_pct": (trade_setup or {}).get("tp_pct"),
        "action": (trade_setup or {}).get("action"),
        "setup_direction": (trade_setup or {}).get("direction"),
        "lookback_hours": lookback_hours,
        "threshold_pct": thr_pct,
    }


def scan_runup_descent(
    *,
    asset_class: str,
    tickers: list[str],
    drop_pct: float = 5.0,
    lookback_hours: float = 24.0,
    timeframes: list[str] | None = None,
    move_side: str = "both",
    groww_token: str = "",
    exchange: str = "NSE",
    include_charts: bool = False,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Scan for early major runups and exhausted tops now in descent across TFs."""
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
    symbols = uniq[:200]

    thr = float(max(0.5, min(float(drop_pct), 90.0)))
    hours = float(max(1.0, min(float(lookback_hours), 24 * 14)))
    raw_tfs = timeframes or ["15m", "1h"]
    tfs: list[str] = []
    for t in raw_tfs:
        key = str(t).strip().lower()
        if key in RUNUP_DESCENT_TFS and key not in tfs:
            tfs.append(key)
    if not tfs:
        tfs = ["15m", "1h"]

    side = (move_side or "both").lower()
    end_utc = datetime.now(UTC)
    start_utc = end_utc - timedelta(hours=hours)
    sess = session_info(ac)

    results: list[dict[str, Any]] = []
    if not symbols:
        return {
            "strategy": STRATEGY_ID,
            "strategy_label": STRATEGY_NAME,
            "asset_class": ac,
            "mode": "runup_descent",
            "drop_pct": thr,
            "lookback_hours": hours,
            "timeframes": tfs,
            "move_side": side,
            "session": sess,
            "scanned": 0,
            "matched": 0,
            "matched_runups": 0,
            "matched_descents": 0,
            "results": [],
            "knives": [],
            "runups": [],
            "descents": [],
            "plain_english": "No tickers selected.",
            "how_to_read": _how_to(),
        }

    with ThreadPoolExecutor(max_workers=max(2, min(max_workers, 10))) as pool:
        futs = {
            pool.submit(
                _analyze_runup_descent_symbol,
                sym,
                asset_class=ac,
                market=market,
                thr_pct=thr,
                lookback_hours=hours,
                timeframes=tfs,
                move_side=side,
                groww_token=groww_token,
                exchange=exchange,
                start_utc=start_utc,
                end_utc=end_utc,
                include_charts=include_charts,
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                from app.market_pulse.asset_class_config import attach_ticker_name

                results.append(attach_ticker_name(row, asset_class=ac))

    knives = [r for r in results if r.get("matched")]
    knives.sort(key=lambda r: float(r.get("match_score") or 0), reverse=True)
    runups = [r for r in knives if r.get("match_runup")]
    descents = [r for r in knives if r.get("match_descent")]
    errors = sum(1 for r in results if r.get("error") and not r.get("matched"))

    top_bits = []
    for r in knives[:8]:
        bits = []
        if r.get("match_runup"):
            bits.append(
                f"runup +{r.get('rise_from_start_pct')}% ({','.join(r.get('runup_timeframes') or [])})"
            )
        if r.get("match_descent"):
            bits.append(
                f"descent −{r.get('fall_from_top_pct')}% ({','.join(r.get('descent_timeframes') or [])})"
            )
        top_bits.append(f"{r.get('display_label') or r['ticker']}: {' · '.join(bits)}")

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "asset_class": ac,
        "asset_label": cfg.get("label"),
        "mode": "runup_descent",
        "drop_pct": thr,
        "threshold_pct": thr,
        "lookback_hours": hours,
        "timeframes": tfs,
        "move_side": side,
        "include_charts": include_charts,
        "session": sess,
        "window_start_utc": start_utc.isoformat(),
        "window_end_utc": end_utc.isoformat(),
        "scanned": len(results),
        "matched": len(knives),
        "matched_runups": len(runups),
        "matched_descents": len(descents),
        "errors": errors,
        "results": sorted(results, key=lambda r: float(r.get("match_score") or -1), reverse=True),
        "knives": knives,
        "runups": runups,
        "descents": descents,
        "summary": {
            "scanned": len(results),
            "matched": len(knives),
            "matched_runups": len(runups),
            "matched_descents": len(descents),
            "errors": errors,
            "threshold": f">= {thr:g}% runup from start or descent from peak",
            "lookback": f"last {hours:g}h",
            "timeframes": tfs,
        },
        "plain_english": (
            f"Falling Knife · Runup/Descent · {cfg.get('label')} · last {hours:g}h · "
            f"TFs {', '.join(tfs)} · ≥{thr:g}% move. "
            f"Matched {len(knives)} / {len(results)} "
            f"({len(runups)} early runups · {len(descents)} descents)."
            + ((" Top: " + " · ".join(top_bits) + ".") if top_bits else "")
        ),
        "how_to_read": _how_to(),
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Continuation labels are momentum heuristics, not guarantees."
        ),
    }
