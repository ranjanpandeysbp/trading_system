"""
oil_dollar_bond_engine.py
-------------------------
Command Center — Oil · Dollar · Bond · Gold · Silver · Indices · Crypto

Modes:
  - daily: history over from_date → to_date (1d bars)
  - intraday: same-session intraday bars for session_date (1m/5m/15m/30m/1h)

Yahoo Finance instruments (first working candidate wins).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

INSTRUMENTS: list[dict[str, Any]] = [
    # ── Global macro ──────────────────────────────────────────────────────────
    {
        "id": "dxy",
        "label": "US Dollar Index",
        "short": "DXY",
        "unit": "index",
        "group": "macro",
        "candidates": ["DX-Y.NYB", "DX=F"],
        "color": "#38bdf8",
    },
    {
        "id": "brent",
        "label": "Brent Crude Oil",
        "short": "Brent",
        "unit": "USD/bbl",
        "group": "macro",
        "candidates": ["BZ=F", "CL=F"],
        "color": "#fbbf24",
    },
    {
        "id": "us2y",
        "label": "US 2Y Bond",
        "short": "US 2Y",
        "unit": "% yield / futures",
        "group": "macro",
        "candidates": ["^UST2Y", "2YY=F", "ZT=F"],
        "color": "#34d399",
    },
    {
        "id": "us10y",
        "label": "US 10Y Bond Yield",
        "short": "US 10Y",
        "unit": "%",
        "group": "macro",
        "candidates": ["^TNX", "ZN=F"],
        "color": "#f472b6",
    },
    {
        "id": "gold",
        "label": "Gold",
        "short": "Gold",
        "unit": "USD/oz",
        "group": "macro",
        "candidates": ["GC=F", "XAUUSD=X"],
        "color": "#f59e0b",
    },
    {
        "id": "silver",
        "label": "Silver",
        "short": "Silver",
        "unit": "USD/oz",
        "group": "macro",
        "candidates": ["SI=F", "XAGUSD=X"],
        "color": "#a8a29e",
    },
    {
        "id": "nifty50",
        "label": "Nifty 50",
        "short": "Nifty 50",
        "unit": "index",
        "group": "macro",
        "candidates": ["^NSEI", "NIFTYBEES.NS"],
        "color": "#818cf8",
    },
    {
        "id": "dow30",
        "label": "Dow Jones 30",
        "short": "Dow 30",
        "unit": "index",
        "group": "macro",
        "candidates": ["^DJI", "DIA"],
        "color": "#22d3ee",
    },
    {
        "id": "nasdaq",
        "label": "Nasdaq Composite",
        "short": "Nasdaq",
        "unit": "index",
        "group": "macro",
        "candidates": ["^IXIC", "^NDX", "QQQ"],
        "color": "#c084fc",
    },
    {
        "id": "bitcoin",
        "label": "Bitcoin",
        "short": "Bitcoin",
        "unit": "USD",
        "group": "macro",
        "candidates": ["BTC-USD", "BTCUSD=X"],
        "color": "#fb923c",
    },
    {
        "id": "ethereum",
        "label": "Ethereum",
        "short": "Ethereum",
        "unit": "USD",
        "group": "macro",
        "candidates": ["ETH-USD", "ETHUSD=X"],
        "color": "#60a5fa",
    },
    # ── India breadth / size ETFs ────────────────────────────────────────────
    {
        "id": "nifty500",
        "label": "Nifty 500 ETF",
        "short": "Nifty 500",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["MONIFTY500.NS", "BSE500IETF.NS", "^CRSLDX"],
        "color": "#67e8f9",
    },
    {
        "id": "juniorbees",
        "label": "Nifty Next 50 (JUNIORBEES)",
        "short": "Next 50",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["JUNIORBEES.NS"],
        "color": "#7dd3fc",
    },
    {
        "id": "midcap150",
        "label": "Nifty Midcap 150 ETF",
        "short": "Midcap 150",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["MIDCAPETF.NS", "MID150BEES.NS", "HDFCMID150.NS", "GROWWMC150.NS"],
        "color": "#38bdf8",
    },
    {
        "id": "smallcap250",
        "label": "Nifty Smallcap 250 ETF",
        "short": "Smallcap 250",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["SMALLCAP.NS", "SMALLIETF.NS"],
        "color": "#0ea5e9",
    },
    # ── India sector ETFs ─────────────────────────────────────────────────────
    {
        "id": "bankbees",
        "label": "Bank (BANKBEES)",
        "short": "Bank",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["BANKBEES.NS", "^NSEBANK"],
        "color": "#4ade80",
    },
    {
        "id": "psubnkbees",
        "label": "PSU Bank (PSUBNKBEES)",
        "short": "PSU Bank",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["PSUBNKBEES.NS"],
        "color": "#86efac",
    },
    {
        "id": "itbees",
        "label": "IT (ITBEES)",
        "short": "IT",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["ITBEES.NS", "^CNXIT"],
        "color": "#a78bfa",
    },
    {
        "id": "autobees",
        "label": "Auto (AUTOBEES)",
        "short": "Auto",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["AUTOBEES.NS"],
        "color": "#f87171",
    },
    {
        "id": "pharmabees",
        "label": "Pharma (PHARMABEES)",
        "short": "Pharma",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["PHARMABEES.NS"],
        "color": "#fb7185",
    },
    {
        "id": "healthbees",
        "label": "Healthcare (HEALTHY)",
        "short": "Healthcare",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["HEALTHY.NS"],
        "color": "#f43f5e",
    },
    {
        "id": "fmcgietf",
        "label": "FMCG (FMCGIETF)",
        "short": "FMCG",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["FMCGIETF.NS"],
        "color": "#fbbf24",
    },
    {
        "id": "consumbees",
        "label": "Consumption (CONSUMBEES)",
        "short": "Consumer",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["CONSUMBEES.NS"],
        "color": "#fcd34d",
    },
    {
        "id": "metalietf",
        "label": "Metal (METALIETF)",
        "short": "Metal",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["METALIETF.NS", "GROWWMETAL.NS", "^CNXMETAL"],
        "color": "#94a3b8",
    },
    {
        "id": "growwpower",
        "label": "Power (GROWWPOWER)",
        "short": "Power",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["GROWWPOWER.NS"],
        "color": "#facc15",
    },
    {
        "id": "energy",
        "label": "Energy (ENERGY)",
        "short": "Energy",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["ENERGY.NS", "OILIETF.NS"],
        "color": "#ea580c",
    },
    {
        "id": "infrabees",
        "label": "Infra (INFRABEES)",
        "short": "Infra",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["INFRABEES.NS"],
        "color": "#78716c",
    },
    {
        "id": "defence",
        "label": "Defence (MODEFENCE)",
        "short": "Defence",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["MODEFENCE.NS", "GROWWDEFNC.NS"],
        "color": "#64748b",
    },
    {
        "id": "realty",
        "label": "Realty (MOREALTY)",
        "short": "Realty",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["MOREALTY.NS"],
        "color": "#d946ef",
    },
    {
        "id": "growwev",
        "label": "EV (GROWWEV)",
        "short": "EV",
        "unit": "₹ ETF",
        "group": "india_etf",
        "candidates": ["GROWWEV.NS", "EVIETF.NS"],
        "color": "#10b981",
    },
]

INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "1h"}
# Yahoo caps: 1m ≈ 7d history; 5m/15m/30m/1h ≈ 60d.
_INTRADAY_MAX_LOOKBACK_DAYS = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 60, "1h": 60}


def _parse_date(value: str) -> datetime:
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")


def _normalize_interval(interval: str, *, intraday: bool) -> str:
    iv = (interval or ("5m" if intraday else "1d")).strip().lower()
    if iv == "60m":
        iv = "1h"
    if intraday:
        return iv if iv in INTRADAY_INTERVALS else "5m"
    return "1d"


def _strip_tz(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    try:
        if getattr(idx, "tz", None) is not None:
            return idx.tz_localize(None)
    except Exception:
        try:
            return idx.tz_convert(None)
        except Exception:
            pass
    return idx


def _download_ohlc(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    interval: str = "1d",
) -> pd.DataFrame:
    """OHLC for one Yahoo symbol over [start, end] (inclusive)."""
    try:
        import yfinance as yf
    except Exception as exc:
        logger.warning("yfinance unavailable: %s", exc)
        return pd.DataFrame()

    end_excl = end + timedelta(days=1)
    try:
        raw = yf.download(
            symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end_excl.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        logger.debug("download failed for %s [%s]: %s", symbol, interval, exc)
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    def _col(name: str) -> pd.Series | None:
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0)
            if name not in level0:
                return None
            block = raw[name]
            s = block.iloc[:, 0] if getattr(block, "ndim", 1) > 1 else block
        else:
            if name not in raw.columns:
                return None
            s = raw[name]
        return pd.to_numeric(s, errors="coerce")

    close = _col("Close")
    if close is None:
        return pd.DataFrame()
    high = _col("High")
    low = _col("Low")
    open_ = _col("Open")
    vol = _col("Volume")
    if high is None:
        high = close
    if low is None:
        low = close
    if open_ is None:
        open_ = close

    out = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol if vol is not None else 0.0,
    }).dropna(subset=["close"])
    if out.empty:
        return pd.DataFrame()
    out.index = _strip_tz(pd.to_datetime(out.index))
    return out


def _pick_ohlc(
    candidates: list[str],
    start: datetime,
    end: datetime,
    *,
    interval: str,
) -> tuple[str | None, pd.DataFrame]:
    min_bars = 2 if interval == "1d" else 3
    for sym in candidates:
        df = _download_ohlc(sym, start, end, interval=interval)
        if len(df) >= min_bars:
            return sym, df
    return None, pd.DataFrame()


def _series_to_points(series: pd.Series, *, intraday: bool) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for ts, val in series.items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN
            continue
        t = pd.Timestamp(ts)
        if intraday:
            label = t.strftime("%H:%M")
            iso = t.isoformat()
        else:
            label = t.strftime("%Y-%m-%d")
            iso = label
        points.append({"t": iso, "label": label, "value": round(v, 4)})
    return points


def _support_resistance(df: pd.DataFrame, *, window: int = 3) -> dict[str, Any]:
    """Nearest S1/S2 and R1/R2 from swing pivots + period extremes."""
    empty = {
        "s1": None, "s2": None, "r1": None, "r2": None,
        "period_low": None, "period_high": None,
        "levels": [],
    }
    if df is None or df.empty or len(df) < 5:
        return empty

    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    closes = df["close"].astype(float).values
    last = float(closes[-1])
    period_low = float(np.nanmin(lows))
    period_high = float(np.nanmax(highs))

    w = max(1, min(window, max(1, len(df) // 10)))
    swing_lows: list[float] = []
    swing_highs: list[float] = []
    for i in range(w, len(df) - w):
        if lows[i] == np.nanmin(lows[i - w:i + w + 1]):
            swing_lows.append(float(lows[i]))
        if highs[i] == np.nanmax(highs[i - w:i + w + 1]):
            swing_highs.append(float(highs[i]))

    # Deduplicate near-identical levels (~0.15% or absolute for tiny prices)
    def _dedupe(levels: list[float], *, prefer: str) -> list[float]:
        if not levels:
            return []
        ordered = sorted(levels, reverse=(prefer == "desc"))
        out: list[float] = []
        for lvl in ordered:
            if not out:
                out.append(lvl)
                continue
            ref = out[-1]
            tol = max(abs(ref) * 0.0015, 1e-6)
            if abs(lvl - ref) > tol:
                out.append(lvl)
        return out

    supports_below = _dedupe([x for x in swing_lows if x < last], prefer="desc")
    resists_above = _dedupe([x for x in swing_highs if x > last], prefer="asc")

    # Fallbacks from percentiles / period extremes
    if not supports_below:
        supports_below = [period_low]
    elif abs(supports_below[0] - period_low) / max(abs(period_low), 1e-9) > 0.002:
        # Keep period low as deeper support if distinct
        pass
    if not resists_above:
        resists_above = [period_high]

    s1 = round(supports_below[0], 4) if supports_below else round(period_low, 4)
    s2 = round(supports_below[1], 4) if len(supports_below) >= 2 else round(period_low, 4)
    if s2 == s1 and period_low < s1:
        s2 = round(period_low, 4)

    r1 = round(resists_above[0], 4) if resists_above else round(period_high, 4)
    r2 = round(resists_above[1], 4) if len(resists_above) >= 2 else round(period_high, 4)
    if r2 == r1 and period_high > r1:
        r2 = round(period_high, 4)

    levels = [
        {"key": "s2", "label": "S2", "kind": "support", "price": s2},
        {"key": "s1", "label": "S1", "kind": "support", "price": s1},
        {"key": "r1", "label": "R1", "kind": "resistance", "price": r1},
        {"key": "r2", "label": "R2", "kind": "resistance", "price": r2},
    ]
    # Drop exact duplicates while keeping order
    seen: set[float] = set()
    unique_levels = []
    for lvl in levels:
        p = float(lvl["price"])
        if p in seen:
            continue
        seen.add(p)
        unique_levels.append(lvl)

    return {
        "s1": s1,
        "s2": s2,
        "r1": r1,
        "r2": r2,
        "period_low": round(period_low, 4),
        "period_high": round(period_high, 4),
        "last": round(last, 4),
        "levels": unique_levels,
    }


def _pct_change_series(series: pd.Series) -> pd.Series:
    base = float(series.iloc[0])
    if not base or base != base:
        return pd.Series(dtype=float)
    return (series / base - 1.0) * 100.0


def _build_overlay(aligned: dict[str, pd.Series], *, intraday: bool) -> list[dict[str, Any]]:
    if not aligned:
        return []
    frame = pd.DataFrame(aligned).sort_index().dropna(how="all")
    pct = pd.DataFrame(index=frame.index)
    for col in frame.columns:
        if frame[col].dropna().empty:
            continue
        pct[col] = _pct_change_series(frame[col].ffill())
    pct = pct.dropna(how="all")
    n = len(pct)
    step = max(1, n // 240) if n > 240 else 1
    chart: list[dict[str, Any]] = []
    for i, (ts, row) in enumerate(pct.iterrows()):
        if i % step != 0 and i != n - 1:
            continue
        t = pd.Timestamp(ts)
        label = t.strftime("%H:%M") if intraday else t.strftime("%Y-%m-%d")
        entry: dict[str, Any] = {"t": t.isoformat() if intraday else label, "label": label}
        for col in pct.columns:
            val = row.get(col)
            if val is not None and val == val:
                entry[col] = round(float(val), 3)
        chart.append(entry)
    return chart


def compute_oil_dollar_bond(
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    mode: str = "daily",
    session_date: str | None = None,
    interval: str = "1d",
) -> dict[str, Any]:
    """Build macro chart payload (FX, oil, bonds, metals, indices, crypto)."""
    mode_norm = (mode or "daily").strip().lower()
    intraday = mode_norm in ("intraday", "same_day", "intraday_same_day")
    iv = _normalize_interval(interval, intraday=intraday)

    try:
        from app.market_pulse.data_source_ctx import note_source

        note_source("yfinance")
    except Exception:
        pass

    if intraday:
        sess = session_date or to_date or from_date
        if not sess:
            return {
                "error": "Pick a session date for same-day intraday charts.",
                "series": [],
                "chart": [],
                "mode": "intraday",
            }
        try:
            day = _parse_date(sess)
        except ValueError:
            return {"error": "Invalid session date — use YYYY-MM-DD.", "series": [], "chart": [], "mode": "intraday"}

        max_days = _INTRADAY_MAX_LOOKBACK_DAYS.get(iv, 60)
        oldest = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=max_days)
        if day < oldest:
            return {
                "error": (
                    f"Yahoo only keeps ~{max_days} days of {iv} history. "
                    f"Pick a session on or after {oldest.strftime('%Y-%m-%d')}."
                ),
                "series": [],
                "chart": [],
                "mode": "intraday",
                "session_date": sess,
                "interval": iv,
            }
        start, end = day, day
        from_date_out, to_date_out = sess, sess
    else:
        if not from_date or not to_date:
            return {"error": "From date and To date are required for daily mode.", "series": [], "chart": []}
        try:
            start = _parse_date(from_date)
            end = _parse_date(to_date)
        except ValueError:
            return {"error": "Invalid date format — use YYYY-MM-DD.", "series": [], "chart": []}
        if start > end:
            return {"error": "From date must be on or before To date.", "series": [], "chart": []}
        if (end - start).days > 3650:
            return {"error": "Date range too long — please keep it under ~10 years.", "series": [], "chart": []}
        from_date_out, to_date_out = from_date, to_date

    series_out: list[dict[str, Any]] = []
    aligned: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}

    for spec in INSTRUMENTS:
        sym, ohlc = _pick_ohlc(list(spec["candidates"]), start, end, interval=iv)
        if sym is None or ohlc.empty:
            errors[str(spec["id"])] = f"No data for {spec['label']} (tried {', '.join(spec['candidates'])})."
            series_out.append({
                "id": spec["id"],
                "label": spec["label"],
                "short": spec["short"],
                "unit": spec["unit"],
                "group": spec.get("group") or "macro",
                "symbol": None,
                "color": spec["color"],
                "points": [],
                "error": errors[str(spec["id"])],
                "last": None,
                "change_pct": None,
                "support_resistance": None,
            })
            continue

        if intraday:
            day_start = pd.Timestamp(start)
            day_end = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            clipped = ohlc[(ohlc.index >= day_start) & (ohlc.index <= day_end)]
        else:
            clipped = ohlc[(ohlc.index >= pd.Timestamp(start)) & (ohlc.index <= pd.Timestamp(end) + pd.Timedelta(days=1))]
        if clipped.empty:
            clipped = ohlc

        close = clipped["close"]
        from app.market_pulse.sr_volume_summary import build_sr_volume_summary, ohlc_to_chart_points

        points = ohlc_to_chart_points(clipped, intraday=intraday)
        if len(points) < 2:
            errors[str(spec["id"])] = f"Insufficient {iv} bars for {spec['label']} on this session."
            series_out.append({
                "id": spec["id"],
                "label": spec["label"],
                "short": spec["short"],
                "unit": spec["unit"],
                "group": spec.get("group") or "macro",
                "symbol": sym,
                "color": spec["color"],
                "points": points,
                "error": errors[str(spec["id"])],
                "last": round(float(close.iloc[-1]), 4) if len(close) else None,
                "change_pct": None,
                "support_resistance": None,
                "volume_sr_summary": None,
            })
            continue

        first = float(close.iloc[0])
        last = float(close.iloc[-1])
        change_pct = ((last / first) - 1.0) * 100.0 if first else None
        sr = _support_resistance(clipped, window=3 if intraday else 5)
        vol_sr = build_sr_volume_summary(clipped, sr, name=str(spec["short"]))
        aligned[str(spec["id"])] = close
        series_out.append({
            "id": spec["id"],
            "label": spec["label"],
            "short": spec["short"],
            "unit": spec["unit"],
            "group": spec.get("group") or "macro",
            "symbol": sym,
            "color": spec["color"],
            "points": points,
            "last": round(last, 4),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "from": points[0]["t"] if points else None,
            "to": points[-1]["t"] if points else None,
            "bars": len(points),
            "support_resistance": sr,
            "volume_sr_summary": vol_sr,
        })

    chart = _build_overlay(aligned, intraday=intraday)
    ok_count = sum(1 for s in series_out if s.get("points") and not s.get("error"))
    summary_bits = []
    for s in series_out:
        if s.get("change_pct") is None:
            continue
        arrow = "↑" if s["change_pct"] >= 0 else "↓"
        summary_bits.append(f"{s['short']} {arrow}{abs(s['change_pct']):.1f}%")

    range_txt = (
        f"intraday {from_date_out} ({iv})"
        if intraday
        else f"{from_date_out} → {to_date_out}"
    )

    return {
        "mode": "intraday" if intraday else "daily",
        "interval": iv,
        "session_date": from_date_out if intraday else None,
        "from_date": from_date_out,
        "to_date": to_date_out,
        "data_source": "yfinance",
        "data_source_label": "yfinance",
        "series": series_out,
        "chart": chart,
        "instruments": [
            {
                "id": s["id"],
                "label": s["label"],
                "short": s["short"],
                "color": s["color"],
                "group": s.get("group") or "macro",
            }
            for s in INSTRUMENTS
        ],
        "groups": {
            "macro": "Global macro (DXY · oil · bonds · metals · Nifty/Dow/Nasdaq · crypto)",
            "india_etf": "India sector & breadth ETFs (Bank · IT · Mid/Small · Pharma · …)",
        },
        "ok_count": ok_count,
        "errors": errors,
        "summary": " · ".join(summary_bits) if summary_bits else None,
        "plain_english": (
            f"Macro + India sector ETF tape — {range_txt}. "
            + ("Normalized % change overlay compares direction across units. " if chart else "")
            + (
                "Loaded: "
                + ", ".join(summary_bits[:14])
                + (f" · +{len(summary_bits) - 14} more" if len(summary_bits) > 14 else "")
                + "."
                if summary_bits
                else "No series loaded."
            )
        ),
        "how_to_read": [
            "Daily mode: pick From / To dates for multi-day history.",
            "Intraday mode: pick one session date + bar size (1m–1h) for same-day charts (Yahoo history window applies).",
            "Filter chips: Global macro vs India sector ETFs (or All).",
            "Dollar Index rising usually pressures commodities; falling DXY often supports oil/gold/silver.",
            "Brent is the global oil benchmark; Gold/Silver are COMEX futures (GC=F / SI=F).",
            "US 2Y and US 10Y track rate expectations — watch 2s10s for risk appetite.",
            "Nifty 50 (^NSEI), Dow 30 (^DJI), Nasdaq (^IXIC) show equity risk appetite across regions.",
            "India ETFs (BANKBEES, ITBEES, Midcap 150, Smallcap 250, METALIETF, …) show sector rotation vs Nifty.",
            "Note: METALBEES does not exist — Metal uses METALIETF / GROWWMETAL.",
            "Bitcoin / Ethereum track crypto risk-on; often move with Nasdaq in risk regimes.",
            "Each panel uses native units with S1/S2 · R1/R2 and volume bars under price.",
            "Green dashed = support · Red dashed = resistance · Period high/low used as deeper levels when needed.",
            "Per-chart summary: approaching S/R + rising volume → higher break odds; fading volume → hold/rejection more likely; flat volume → consolidation.",
            "Break % is an educational heuristic — not a trade signal.",
            "The overlay is % change from the first bar (no S/R — scales differ).",
            "Educational macro context only — not a trade signal.",
        ],
    }
