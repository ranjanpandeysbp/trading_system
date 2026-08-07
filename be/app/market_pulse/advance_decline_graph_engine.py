"""
advance_decline_graph_engine.py
--------------------------------
Command Center — Advance Decline Graph.

Reconstructs market-breadth (advances / declines / unchanged) for an NSE
index universe from constituent OHLCV — NSE does not publish a historical A/D
time series API.

Modes
  daily     — for each session date in [from_date, to_date], count how many
              constituents closed up / down / flat vs the prior session close.
  intraday  — for a chosen session date + timeframe, at each bar timestamp
              (truncated to optional as_of HH:MM), count how many constituents
              printed up / down / flat vs their previous bar close.

Also returns a cumulative A/D line (running sum of advances − declines).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols
from app.market_pulse.ticker_utils import GROWW_MARKET, INDEX_OPTIONS

logger = logging.getLogger(__name__)

INTRADAY_TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]
_MAX_WORKERS = 12
# Soft cap — Nifty 500 is allowed but slow; FE warns above this.
_WARN_UNIVERSE = 120
# Cap for charting when declines == 0 (infinite ratio) so the Y-axis stays readable.
_AD_RATIO_CAP = 10.0


def _ad_ratio(advances: int, declines: int) -> float | None:
    """Advances ÷ Declines. Neutral = 1.0. Capped when declines are zero."""
    if advances <= 0 and declines <= 0:
        return None
    if declines <= 0:
        return round(min(_AD_RATIO_CAP, float(max(advances, 1))), 3)
    return round(min(_AD_RATIO_CAP, advances / declines), 3)


def list_index_names() -> list[str]:
    """Prefer INDEX_OPTIONS keys that resolve to equity lists (skip Default/ETF)."""
    skip = {"Default Groww Tickers", "High Vol ETF"}
    names = [k for k in INDEX_OPTIONS.keys() if k not in skip]
    # Friendly display aliases first
    preferred = [
        "NIFTY 50",
        "NIFTY BANK",
        "NIFTY NEXT 50",
        "NIFTY IT",
        "NIFTY FINANCIAL SERVICES",
        "NIFTY MIDCAP 150",
        "NIFTY SMALLCAP 250",
        "NIFTY 500",
    ]
    ordered = [n for n in preferred if n in names]
    ordered += [n for n in names if n not in ordered]
    return ordered


IST = "Asia/Kolkata"


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s.strip()[:10], "%Y-%m-%d")


def _to_ist_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Normalize bar times to Asia/Kolkata (IST), returned as tz-naive IST wall clock."""
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        return idx.tz_convert(IST).tz_localize(None)
    # Naive India feed timestamps are already exchange-local (IST).
    return idx


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"])
            out = out.set_index("date")
        elif "time" in out.columns:
            out["time"] = pd.to_datetime(out["time"])
            out = out.set_index("time")
        else:
            out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out.index = _to_ist_index(out.index)
    cols = {c.lower(): c for c in out.columns}
    if "close" not in cols and "Close" in out.columns:
        out = out.rename(columns={"Close": "close", "Open": "open", "High": "high", "Low": "low"})
    if "close" not in out.columns:
        return pd.DataFrame()
    return out


def _fetch_symbol(
    symbol: str,
    timeframe: str,
    *,
    groww_token: str,
    exchange: str,
    limit: int,
) -> tuple[str, pd.DataFrame]:
    try:
        raw = fetch_data_for_gap_scan(
            symbol, timeframe, GROWW_MARKET, groww_token=groww_token, exchange=exchange, limit=limit,
        )
        return symbol, _normalize_ohlcv(raw)
    except Exception as exc:
        logger.debug("A/D fetch failed for %s %s: %s", symbol, timeframe, exc)
        return symbol, pd.DataFrame()


def _fetch_many(
    symbols: list[str],
    timeframe: str,
    *,
    groww_token: str,
    exchange: str,
    limit: int,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    workers = min(_MAX_WORKERS, max(1, len(symbols)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [
            pool.submit(_fetch_symbol, sym, timeframe, groww_token=groww_token, exchange=exchange, limit=limit)
            for sym in symbols
        ]
        for fut in as_completed(futs):
            sym, df = fut.result()
            if not df.empty:
                out[sym] = df
    return out


def _daily_series(
    frames: dict[str, pd.DataFrame],
    from_dt: datetime,
    to_dt: datetime,
) -> list[dict[str, Any]]:
    # date(str) -> advances/declines/unchanged
    buckets: dict[str, dict[str, int]] = {}
    for _sym, df in frames.items():
        if "close" not in df.columns or len(df) < 2:
            continue
        closes = df["close"].astype(float)
        # Pair each bar with previous close
        prev = closes.shift(1)
        for ts, close, pclose in zip(closes.index, closes.values, prev.values):
            if pd.isna(pclose):
                continue
            d = pd.Timestamp(ts).to_pydatetime().date()
            if d < from_dt.date() or d > to_dt.date():
                continue
            key = d.isoformat()
            bucket = buckets.setdefault(key, {"advances": 0, "declines": 0, "unchanged": 0})
            if close > pclose:
                bucket["advances"] += 1
            elif close < pclose:
                bucket["declines"] += 1
            else:
                bucket["unchanged"] += 1

    series: list[dict[str, Any]] = []
    ad_line = 0
    for key in sorted(buckets.keys()):
        b = buckets[key]
        net = b["advances"] - b["declines"]
        ad_line += net
        total = b["advances"] + b["declines"] + b["unchanged"]
        ratio = _ad_ratio(b["advances"], b["declines"])
        series.append({
            "date": key,
            "label": key,
            "advances": b["advances"],
            "declines": b["declines"],
            "unchanged": b["unchanged"],
            "net": net,
            "total": total,
            "ad_ratio": ratio,
            "ad_line": ad_line,
        })
    return series


def _intraday_series(
    frames: dict[str, pd.DataFrame],
    session_date: datetime,
    *,
    as_of: time | None,
) -> list[dict[str, Any]]:
    day = session_date.date()
    # Per timestamp: list of +1 / -1 / 0 from each stock's bar at that stamp
    # Use floor to minute string for alignment across stocks
    by_ts: dict[str, list[int]] = {}

    for _sym, df in frames.items():
        if "close" not in df.columns or len(df) < 2:
            continue
        day_df = df[df.index.normalize() == pd.Timestamp(day)]
        if day_df.empty:
            # Some feeds are tz-naive but date match via .date()
            day_df = df[[pd.Timestamp(i).date() == day for i in df.index]]
        if len(day_df) < 1:
            continue

        # Need previous close: last bar before session, else first prior bar overall
        prior = df[df.index < day_df.index[0]]
        prev_close = float(prior["close"].iloc[-1]) if len(prior) else None

        closes = day_df["close"].astype(float)
        for i, (ts, close) in enumerate(zip(closes.index, closes.values)):
            t = pd.Timestamp(ts).to_pydatetime().time()
            if as_of is not None and t > as_of:
                break
            if i == 0:
                pclose = prev_close if prev_close is not None else close
            else:
                pclose = float(closes.iloc[i - 1])
            if close > pclose:
                sig = 1
            elif close < pclose:
                sig = -1
            else:
                sig = 0
            key = pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")
            by_ts.setdefault(key, []).append(sig)

    series: list[dict[str, Any]] = []
    ad_line = 0
    for key in sorted(by_ts.keys()):
        sigs = by_ts[key]
        adv = sum(1 for s in sigs if s > 0)
        dec = sum(1 for s in sigs if s < 0)
        unc = sum(1 for s in sigs if s == 0)
        net = adv - dec
        ad_line += net
        ratio = _ad_ratio(adv, dec)
        hhmm = key[11:] if len(key) >= 16 else key
        series.append({
            "date": key,
            "label": f"{hhmm} IST",
            "timestamp": key,
            "timestamp_ist": key,
            "timezone": "IST",
            "advances": adv,
            "declines": dec,
            "unchanged": unc,
            "net": net,
            "total": adv + dec + unc,
            "ad_ratio": ratio,
            "ad_line": ad_line,
        })
    return series


def _parse_as_of(as_of_time: str | None) -> time | None:
    """Parse HH:MM as IST wall-clock (NSE session time)."""
    if not as_of_time or not str(as_of_time).strip():
        return None
    raw = str(as_of_time).strip().replace(" IST", "").replace("ist", "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _breadth_mood(advances: int, declines: int, unchanged: int = 0) -> tuple[str, str]:
    """Return (mood_label, one_line) for layman copy."""
    total = advances + declines + unchanged
    if total <= 0:
        return "NO DATA", "Not enough stock closes to read breadth yet."
    if declines == 0 and advances > 0:
        return "VERY BULLISH BREADTH", "Almost everything in the basket finished higher — broad participation."
    if advances == 0 and declines > 0:
        return "VERY BEARISH BREADTH", "Almost everything finished lower — selling is widespread."
    ratio = advances / max(declines, 1)
    net = advances - declines
    share_up = advances / total
    if share_up >= 0.65 or ratio >= 2.0:
        return "BULLISH BREADTH", "More stocks rose than fell by a clear margin — buyers had the upper hand."
    if share_up <= 0.35 or ratio <= 0.5:
        return "BEARISH BREADTH", "More stocks fell than rose — selling pressure was broader than buying."
    if abs(net) <= max(2, int(total * 0.05)):
        return "MIXED / CHOPPY", "Advances and declines are nearly tied — the index move may be led by a few heavyweights."
    if net > 0:
        return "MILDLY BULLISH", "Slightly more stocks rose than fell — positive but not a stampede."
    return "MILDLY BEARISH", "Slightly more stocks fell than rose — soft under the surface."


def _build_outcome_layman(
    *,
    index_name: str,
    from_date: str,
    to_date: str,
    daily: list[dict[str, Any]],
    intraday: list[dict[str, Any]],
    is_intraday: bool,
    timeframe: str,
    session_date: str | None,
    as_of: time | None,
    universe_size: int,
) -> dict[str, Any]:
    last = daily[-1] if daily else None
    mood, mood_line = ("NO DATA", "No daily points yet.")
    if last:
        mood, mood_line = _breadth_mood(
            int(last.get("advances") or 0),
            int(last.get("declines") or 0),
            int(last.get("unchanged") or 0),
        )

    # Trend of A/D line over the window
    ad_trend = "flat"
    ad_note = "The running A/D line did not move much across the period."
    if len(daily) >= 2:
        start_line = float(daily[0].get("ad_line") or 0)
        end_line = float(daily[-1].get("ad_line") or 0)
        delta = end_line - start_line
        if delta > 5:
            ad_trend = "rising"
            ad_note = (
                f"Over {from_date} → {to_date}, the cumulative A/D line rose "
                f"(net +{int(delta)}). Breadth improved — more days of winners than losers stacked up."
            )
        elif delta < -5:
            ad_trend = "falling"
            ad_note = (
                f"Over {from_date} → {to_date}, the cumulative A/D line fell "
                f"(net {int(delta)}). Breadth weakened — losers piled up more than winners."
            )
        else:
            ad_note = (
                f"Over {from_date} → {to_date}, the cumulative A/D line stayed roughly flat "
                f"(net {int(delta):+d}). Breadth did not clearly improve or deteriorate."
            )

    intra_mood = None
    intra_line = None
    if is_intraday and intraday:
        last_i = intraday[-1]
        intra_mood, intra_line = _breadth_mood(
            int(last_i.get("advances") or 0),
            int(last_i.get("declines") or 0),
            int(last_i.get("unchanged") or 0),
        )
        until = f" until {as_of.strftime('%H:%M')} IST" if as_of else ""
        intra_line = (
            f"On {session_date} ({timeframe} bars{until}): {intra_line} "
            f"Last bar — {last_i.get('advances')} up / {last_i.get('declines')} down / "
            f"{last_i.get('unchanged')} flat."
        )

    headline = f"{index_name}: {mood}"
    summary_parts = [
        f"We checked about {universe_size} stocks that make up {index_name}.",
        "The graph shows the Advance/Decline ratio (ups ÷ downs). Above 1 means more stocks rose; below 1 means more fell.",
        "Green bars = ratio ≥ 1 (bullish breadth). Red bars = ratio < 1 (bearish breadth). The dashed line at 1.0 is even.",
    ]
    if last:
        ratio = last.get("ad_ratio")
        summary_parts.append(
            f"On the latest day ({last.get('date')}): "
            f"{last.get('advances')} stocks advanced, {last.get('declines')} declined "
            f"(A/D ratio {ratio if ratio is not None else '—'}). Verdict: {mood_line}"
        )
    summary_parts.append(ad_note)
    if intra_line:
        summary_parts.append(intra_line)

    what_it_means = (
        "Think of this as a crowd count, not a price tip. "
        "If the index is up but most stocks are red, a few big names may be carrying the move — fragile rally. "
        "If the index is flat/down but most stocks are green, selling may be concentrated — healthier under the hood. "
        "Use it with price, not instead of it."
    )

    return {
        "headline": headline,
        "mood": mood,
        "mood_line": mood_line,
        "ad_trend": ad_trend,
        "ad_trend_line": ad_note,
        "intraday_mood": intra_mood,
        "intraday_line": intra_line,
        "summary": " ".join(summary_parts),
        "what_it_means": what_it_means,
        "how_to_read": [
            "A/D ratio = Advances ÷ Declines (main graph).",
            "Ratio above 1 (green) — more stocks rose than fell that period.",
            "Ratio below 1 (red) — more stocks fell than rose.",
            "Dashed line at 1.0 — even breadth (same number up and down).",
            "Daily chart — one ratio per trading day across your date range.",
            "Intraday chart — ratio at each bar that day (IST) up to your as-of time.",
        ],
    }


def compute_advance_decline_graph(
    index_name: str,
    *,
    from_date: str,
    to_date: str,
    timeframe: str = "1d",
    session_date: str | None = None,
    as_of_time: str | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Build daily and/or intraday advance–decline series for an index."""
    symbols = get_index_constituent_symbols(index_name)
    if not symbols:
        return {
            "error": f"No constituents found for index '{index_name}'.",
            "index_name": index_name,
        }

    try:
        from_dt = _parse_date(from_date)
        to_dt = _parse_date(to_date)
    except ValueError:
        return {"error": "Invalid from_date / to_date — use YYYY-MM-DD.", "index_name": index_name}

    if to_dt < from_dt:
        return {"error": "to_date must be on or after from_date.", "index_name": index_name}

    tf = (timeframe or "1d").strip().lower()
    if tf in ("", "daily", "day"):
        tf = "1d"

    is_intraday = tf in INTRADAY_TIMEFRAMES
    sess = session_date or to_date
    try:
        sess_dt = _parse_date(sess)
    except ValueError:
        return {"error": "Invalid session_date — use YYYY-MM-DD.", "index_name": index_name}

    as_of = _parse_as_of(as_of_time)

    # --- Daily series (always, for the chosen range) ---
    day_span = (to_dt - from_dt).days + 8  # buffer for prior close
    daily_limit = max(min(day_span + 15, 400), 40)
    daily_frames = _fetch_many(
        symbols, "1d", groww_token=groww_token, exchange=exchange, limit=daily_limit,
    )
    daily = _daily_series(daily_frames, from_dt, to_dt)

    intraday: list[dict[str, Any]] = []
    if is_intraday:
        # Enough bars to cover one session with prior bar context
        if tf == "5m":
            limit = 120
        elif tf in ("10m", "15m"):
            limit = 80
        elif tf == "30m":
            limit = 50
        else:
            limit = 40
        # Widen fetch window: need prior day for first-bar comparison
        intra_frames = _fetch_many(
            symbols, tf, groww_token=groww_token, exchange=exchange, limit=limit,
        )
        intraday = _intraday_series(intra_frames, sess_dt, as_of=as_of)

    last_daily = daily[-1] if daily else None
    outcome = _build_outcome_layman(
        index_name=index_name,
        from_date=from_date,
        to_date=to_date,
        daily=daily,
        intraday=intraday,
        is_intraday=is_intraday,
        timeframe=tf,
        session_date=sess_dt.date().isoformat() if is_intraday else None,
        as_of=as_of,
        universe_size=len(symbols),
    )
    plain = outcome["summary"]

    return {
        "index_name": index_name,
        "from_date": from_date,
        "to_date": to_date,
        "timeframe": tf,
        "session_date": sess_dt.date().isoformat() if is_intraday else None,
        "as_of_time": as_of.strftime("%H:%M") if as_of else None,
        "timezone": "IST",
        "mode": "intraday" if is_intraday else "daily",
        "universe_size": len(symbols),
        "scanned_daily": len(daily_frames),
        "warning": (
            f"Large universe ({len(symbols)} names) — fetch may be slow."
            if len(symbols) > _WARN_UNIVERSE else None
        ),
        "daily": daily,
        "intraday": intraday,
        "latest": last_daily,
        "outcome_layman": outcome,
        "plain_english": plain,
        "currency": "₹",
        "market": GROWW_MARKET,
    }
