"""
falling_knife_engine.py
-----------------------
Scan an asset-class universe for names that have fallen ≥ X% from their
session-aware window high over the last N hours.

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
        matched = fall_from_high >= float(drop_pct)

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
            "drop_pct": drop_pct,
            "lookback_hours": lookback_hours,
            "interval": interval,
            "session": sess,
            "window_start_utc": start_utc.isoformat(),
            "window_end_utc": end_utc.isoformat(),
            "scanned": 0,
            "matched": 0,
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
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            row = fut.result()
            if row:
                results.append(row)

    knives = [r for r in results if r.get("matched")]
    knives.sort(key=lambda r: float(r.get("fall_from_high_pct") or 0), reverse=True)
    errors = sum(1 for r in results if r.get("error") and not r.get("matched"))

    top_bits = []
    for r in knives[:8]:
        chg = r.get("change_pct")
        chg_bit = f"{'+' if (chg or 0) >= 0 else ''}{chg}%" if chg is not None else ""
        top_bits.append(
            f"{r['ticker']} off-high −{r['fall_from_high_pct']}% · net {chg_bit} "
            f"(H {_r(r['window_high'], 2)} / L {_r(r['window_low'], 2)})"
        )

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "asset_class": ac,
        "asset_label": cfg.get("label"),
        "drop_pct": drop_pct,
        "lookback_hours": lookback_hours,
        "interval": interval,
        "bars_requested": limit,
        "session": sess,
        "window_start_utc": start_utc.isoformat(),
        "window_end_utc": end_utc.isoformat(),
        "scanned": len(results),
        "matched": len(knives),
        "errors": errors,
        "results": sorted(results, key=lambda r: float(r.get("fall_from_high_pct") or -1), reverse=True),
        "knives": knives,
        "summary": {
            "scanned": len(results),
            "matched": len(knives),
            "errors": errors,
            "threshold": f">= {drop_pct}% off window high",
            "lookback": f"last {lookback_hours:g}h ({sess['label']})",
        },
        "plain_english": (
            f"Falling Knife · {cfg.get('label')} · >={drop_pct:g}% down from session-window high "
            f"in last {lookback_hours:g}h ({sess['label']}). "
            f"Matched {len(knives)} / {len(results)}."
            + ((" Top: " + " · ".join(top_bits) + ".") if top_bits else "")
        ),
        "how_to_read": _how_to(),
        "disclaimer": "Research / education only — not financial advice. Past drops do not imply recovery.",
    }


def _how_to() -> list[str]:
    return [
        "Pick an asset class and universe (index / custom list).",
        "Set drop % (e.g. 10) and lookback hours (e.g. 24).",
        "Scanner uses only that market’s regular session hours inside the lookback window.",
        "India: 09:15–15:30 IST · US: 09:30–16:00 ET · Crypto: 24×7 · Commodities: ~24×5 futures.",
        "Fall % off high = (window high - last) / high. Net change % = (last - window open) / open (risen + / fallen -).",
        "Also shows rise from window low %. Knife match uses off-high fall >= your threshold.",
        "Educational screener only — not a buy/sell signal.",
    ]
