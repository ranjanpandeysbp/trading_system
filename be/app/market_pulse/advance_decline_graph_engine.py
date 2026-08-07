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
NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 30)


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s.strip()[:10], "%Y-%m-%d")


def _to_ist_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Normalize bar times to Asia/Kolkata (IST), returned as tz-naive IST wall clock.

    Groww candles use unix seconds → pandas builds a *naive UTC* index
    (`pd.to_datetime(..., unit='s')`). Treating that as IST left the chart at
    04:00–08:00 instead of the real 09:30–15:30 session. Always map naive
    stamps through UTC → IST.
    """
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        return idx.tz_convert(IST).tz_localize(None)
    return idx.tz_localize("UTC").tz_convert(IST).tz_localize(None)


def _in_nse_session(ts: pd.Timestamp) -> bool:
    t = pd.Timestamp(ts).to_pydatetime().time()
    return NSE_OPEN <= t <= NSE_CLOSE


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
    # date(str) -> advances/declines + volume_up/volume_down
    buckets: dict[str, dict[str, int]] = {}
    for _sym, df in frames.items():
        if "close" not in df.columns or len(df) < 2:
            continue
        closes = df["close"].astype(float)
        has_vol = "volume" in df.columns
        vols = df["volume"].astype(float) if has_vol else None
        prev_c = closes.shift(1)
        prev_v = vols.shift(1) if vols is not None else None
        for i, (ts, close, pclose) in enumerate(zip(closes.index, closes.values, prev_c.values)):
            if pd.isna(pclose):
                continue
            d = pd.Timestamp(ts).to_pydatetime().date()
            if d < from_dt.date() or d > to_dt.date():
                continue
            key = d.isoformat()
            bucket = buckets.setdefault(
                key,
                {
                    "advances": 0, "declines": 0, "unchanged": 0,
                    "volume_up": 0, "volume_down": 0, "volume_flat": 0,
                },
            )
            if close > pclose:
                bucket["advances"] += 1
            elif close < pclose:
                bucket["declines"] += 1
            else:
                bucket["unchanged"] += 1
            if vols is not None and prev_v is not None:
                vol = float(vols.iloc[i])
                pvol = float(prev_v.iloc[i]) if not pd.isna(prev_v.iloc[i]) else None
                if pvol is not None and pvol >= 0:
                    if vol > pvol:
                        bucket["volume_up"] += 1
                    elif vol < pvol:
                        bucket["volume_down"] += 1
                    else:
                        bucket["volume_flat"] += 1

    series: list[dict[str, Any]] = []
    ad_line = 0
    vol_line = 0
    for key in sorted(buckets.keys()):
        b = buckets[key]
        net = b["advances"] - b["declines"]
        ad_line += net
        v_net = b["volume_up"] - b["volume_down"]
        vol_line += v_net
        total = b["advances"] + b["declines"] + b["unchanged"]
        series.append({
            "date": key,
            "label": key,
            "advances": b["advances"],
            "declines": b["declines"],
            "unchanged": b["unchanged"],
            "net": net,
            "total": total,
            "ad_ratio": _ad_ratio(b["advances"], b["declines"]),
            "ad_line": ad_line,
            "volume_up": b["volume_up"],
            "volume_down": b["volume_down"],
            "volume_flat": b["volume_flat"],
            "vol_net": v_net,
            "vol_ratio": _ad_ratio(b["volume_up"], b["volume_down"]),
            "vol_line": vol_line,
        })
    return series


def _intraday_series(
    frames: dict[str, pd.DataFrame],
    session_date: datetime,
    *,
    as_of: time | None,
) -> list[dict[str, Any]]:
    day = session_date.date()
    # timestamp -> list of price signals (+1/-1/0) and volume signals
    by_ts_px: dict[str, list[int]] = {}
    by_ts_vol: dict[str, list[int]] = {}

    for _sym, df in frames.items():
        if "close" not in df.columns or len(df) < 2:
            continue
        day_df = df[df.index.normalize() == pd.Timestamp(day)]
        if day_df.empty:
            day_df = df[[pd.Timestamp(i).date() == day for i in df.index]]
        if len(day_df) < 1:
            continue

        prior = df[df.index < day_df.index[0]]
        prev_close = float(prior["close"].iloc[-1]) if len(prior) else None
        has_vol = "volume" in day_df.columns
        prev_vol = float(prior["volume"].iloc[-1]) if has_vol and len(prior) and "volume" in prior.columns else None

        closes = day_df["close"].astype(float)
        vols = day_df["volume"].astype(float) if has_vol else None
        for i, (ts, close) in enumerate(zip(closes.index, closes.values)):
            if not _in_nse_session(ts):
                continue
            t = pd.Timestamp(ts).to_pydatetime().time()
            if as_of is not None and t > as_of:
                break
            prev_in_session_i = None
            for j in range(i - 1, -1, -1):
                if _in_nse_session(closes.index[j]):
                    prev_in_session_i = j
                    break
            if prev_in_session_i is not None:
                pclose = float(closes.iloc[prev_in_session_i])
                pvol = float(vols.iloc[prev_in_session_i]) if vols is not None else None
            else:
                pclose = prev_close if prev_close is not None else close
                pvol = prev_vol

            if close > pclose:
                psig = 1
            elif close < pclose:
                psig = -1
            else:
                psig = 0

            vsig = 0
            if vols is not None and pvol is not None:
                vol = float(vols.iloc[i])
                if vol > pvol:
                    vsig = 1
                elif vol < pvol:
                    vsig = -1

            key = pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")
            by_ts_px.setdefault(key, []).append(psig)
            by_ts_vol.setdefault(key, []).append(vsig)

    series: list[dict[str, Any]] = []
    ad_line = 0
    vol_line = 0
    for key in sorted(by_ts_px.keys()):
        psigs = by_ts_px[key]
        vsigs = by_ts_vol.get(key, [])
        adv = sum(1 for s in psigs if s > 0)
        dec = sum(1 for s in psigs if s < 0)
        unc = sum(1 for s in psigs if s == 0)
        v_up = sum(1 for s in vsigs if s > 0)
        v_dn = sum(1 for s in vsigs if s < 0)
        v_flat = sum(1 for s in vsigs if s == 0)
        net = adv - dec
        ad_line += net
        v_net = v_up - v_dn
        vol_line += v_net
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
            "ad_ratio": _ad_ratio(adv, dec),
            "ad_line": ad_line,
            "volume_up": v_up,
            "volume_down": v_dn,
            "volume_flat": v_flat,
            "vol_net": v_net,
            "vol_ratio": _ad_ratio(v_up, v_dn),
            "vol_line": vol_line,
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


def _volume_mood(volume_up: int, volume_down: int, volume_flat: int = 0) -> tuple[str, str]:
    """Return (mood_label, one_line) for volume-breadth layman copy."""
    total = volume_up + volume_down + volume_flat
    if total <= 0:
        return "NO VOLUME DATA", "Volume comparison was not available for enough stocks."
    if volume_down == 0 and volume_up > 0:
        return "VOLUME EXPANDING", "Almost every stock traded more than the prior period — activity is heating up."
    if volume_up == 0 and volume_down > 0:
        return "VOLUME DRYING UP", "Almost every stock traded less than the prior period — activity is fading."
    ratio = volume_up / max(volume_down, 1)
    net = volume_up - volume_down
    share_up = volume_up / total
    if share_up >= 0.65 or ratio >= 2.0:
        return "VOLUME EXPANDING", "More stocks saw higher volume than lower — participation/interest is rising."
    if share_up <= 0.35 or ratio <= 0.5:
        return "VOLUME DRYING UP", "More stocks saw lower volume — the move may lack fuel."
    if abs(net) <= max(2, int(total * 0.05)):
        return "VOLUME MIXED", "Volume up and volume down are nearly tied — no clear activity skew."
    if net > 0:
        return "VOLUME SLIGHTLY UP", "Slightly more stocks traded heavier than lighter."
    return "VOLUME SLIGHTLY DOWN", "Slightly more stocks traded lighter than heavier."


def _combine_price_volume(ad_mood: str, vol_mood: str) -> str:
    """Plain-English combo of price breadth + volume breadth."""
    bullish_px = "BULLISH" in ad_mood or ad_mood.startswith("MILDLY BULLISH")
    bearish_px = "BEARISH" in ad_mood or ad_mood.startswith("MILDLY BEARISH")
    vol_up = "EXPANDING" in vol_mood or "SLIGHTLY UP" in vol_mood
    vol_dn = "DRYING" in vol_mood or "SLIGHTLY DOWN" in vol_mood
    if bullish_px and vol_up:
        return (
            "Price breadth and volume are both expanding — a healthier, better-confirmed advance "
            "(more stocks rising on rising activity)."
        )
    if bullish_px and vol_dn:
        return (
            "Prices are advancing but volume is drying up — a softer / hollow rally that can fade "
            "(ups without growing interest)."
        )
    if bearish_px and vol_up:
        return (
            "Prices are falling with expanding volume — more aggressive selling "
            "(downs on rising activity)."
        )
    if bearish_px and vol_dn:
        return (
            "Prices are soft but volume is quiet — a drift lower rather than a panic "
            "(selling without a surge in activity)."
        )
    return (
        "Price breadth and volume breadth are mixed — wait for them to line up before trusting the move."
    )


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
    vol_mood, vol_line = ("NO VOLUME DATA", "No volume points yet.")
    if last:
        mood, mood_line = _breadth_mood(
            int(last.get("advances") or 0),
            int(last.get("declines") or 0),
            int(last.get("unchanged") or 0),
        )
        vol_mood, vol_line = _volume_mood(
            int(last.get("volume_up") or 0),
            int(last.get("volume_down") or 0),
            int(last.get("volume_flat") or 0),
        )

    combo = _combine_price_volume(mood, vol_mood)

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

    vol_trend_note = ""
    if len(daily) >= 2 and daily[-1].get("vol_line") is not None:
        v0 = float(daily[0].get("vol_line") or 0)
        v1 = float(daily[-1].get("vol_line") or 0)
        vd = v1 - v0
        if vd > 5:
            vol_trend_note = (
                f"Cumulative volume-breadth also rose (net +{int(vd)}) — activity expanded across the window."
            )
        elif vd < -5:
            vol_trend_note = (
                f"Cumulative volume-breadth fell (net {int(vd)}) — activity faded across the window."
            )
        else:
            vol_trend_note = "Cumulative volume-breadth stayed roughly flat across the window."

    intra_mood = None
    intra_line = None
    intra_vol_line = None
    if is_intraday and intraday:
        last_i = intraday[-1]
        intra_mood, intra_line = _breadth_mood(
            int(last_i.get("advances") or 0),
            int(last_i.get("declines") or 0),
            int(last_i.get("unchanged") or 0),
        )
        _vm, vline = _volume_mood(
            int(last_i.get("volume_up") or 0),
            int(last_i.get("volume_down") or 0),
            int(last_i.get("volume_flat") or 0),
        )
        until = f" until {as_of.strftime('%H:%M')} IST" if as_of else ""
        intra_line = (
            f"On {session_date} ({timeframe} bars{until}): {intra_line} "
            f"Last bar — {last_i.get('advances')} up / {last_i.get('declines')} down / "
            f"{last_i.get('unchanged')} flat (A/D ratio {last_i.get('ad_ratio', '—')})."
        )
        intra_vol_line = (
            f"Same session volume: {vline} "
            f"Last bar — {last_i.get('volume_up')} volume-up / {last_i.get('volume_down')} volume-down "
            f"(vol ratio {last_i.get('vol_ratio', '—')})."
        )

    headline = f"{index_name}: {mood} · {vol_mood}"
    summary_parts = [
        f"We checked about {universe_size} stocks that make up {index_name}.",
        "Top chart: Advance/Decline ratio (stocks up ÷ stocks down). Above 1 = more winners.",
        "Same chart also shows Volume ratio (stocks with higher volume ÷ stocks with lower volume). Above 1 = activity expanding.",
    ]
    if last:
        summary_parts.append(
            f"Latest day ({last.get('date')}): "
            f"A/D {last.get('advances')}/{last.get('declines')} (ratio {last.get('ad_ratio', '—')}) — {mood_line} "
            f"Volume-up {last.get('volume_up')}/{last.get('volume_down')} (ratio {last.get('vol_ratio', '—')}) — {vol_line}"
        )
    summary_parts.append(combo)
    summary_parts.append(ad_note)
    if vol_trend_note:
        summary_parts.append(vol_trend_note)
    if intra_line:
        summary_parts.append(intra_line)
    if intra_vol_line:
        summary_parts.append(intra_vol_line)

    what_it_means = (
        "Price breadth answers “how many stocks moved which way?” "
        "Volume breadth answers “are more stocks getting busier or quieter?” "
        "Best bullish confirmation: A/D ratio > 1 and volume ratio > 1. "
        "Best bearish confirmation: A/D ratio < 1 and volume ratio > 1 (selling with activity). "
        "A rise on falling volume is often less trustworthy. Use with price, not instead of it."
    )

    return {
        "headline": headline,
        "mood": mood,
        "mood_line": mood_line,
        "volume_mood": vol_mood,
        "volume_mood_line": vol_line,
        "combo_line": combo,
        "ad_trend": ad_trend,
        "ad_trend_line": ad_note,
        "intraday_mood": intra_mood,
        "intraday_line": intra_line,
        "intraday_volume_line": intra_vol_line,
        "summary": " ".join(summary_parts),
        "what_it_means": what_it_means,
        "how_to_read": [
            "A/D ratio (green/red bars + violet line) = Advances ÷ Declines. Above 1 = more stocks rose.",
            "Volume ratio (amber line) = Volume-up ÷ Volume-down. Above 1 = more stocks got busier.",
            "Dashed line at 1.0 = even for both ratios.",
            "A/D > 1 + Vol > 1 → healthier advance. A/D > 1 + Vol < 1 → hollow rally.",
            "A/D < 1 + Vol > 1 → aggressive selling. A/D < 1 + Vol < 1 → quiet drift lower.",
            "Daily chart = one reading per session. Intraday = each bar in IST session hours.",
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
