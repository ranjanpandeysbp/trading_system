"""
oil_dollar_bond_engine.py
-------------------------
Command Center — Oil · Dollar · Bond · Gold · Silver

Modes:
  - daily: history over from_date → to_date (1d bars)
  - intraday: same-session intraday bars for session_date (1m/5m/15m/30m/1h)

Yahoo Finance instruments (first working candidate wins).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

INSTRUMENTS: list[dict[str, Any]] = [
    {
        "id": "dxy",
        "label": "US Dollar Index",
        "short": "DXY",
        "unit": "index",
        "candidates": ["DX-Y.NYB", "DX=F"],
        "color": "#38bdf8",
    },
    {
        "id": "brent",
        "label": "Brent Crude Oil",
        "short": "Brent",
        "unit": "USD/bbl",
        "candidates": ["BZ=F", "CL=F"],
        "color": "#fbbf24",
    },
    {
        "id": "us2y",
        "label": "US 2Y Bond",
        "short": "US 2Y",
        "unit": "% yield / futures",
        "candidates": ["^UST2Y", "2YY=F", "ZT=F"],
        "color": "#34d399",
    },
    {
        "id": "us10y",
        "label": "US 10Y Bond Yield",
        "short": "US 10Y",
        "unit": "%",
        "candidates": ["^TNX", "ZN=F"],
        "color": "#f472b6",
    },
    {
        "id": "gold",
        "label": "Gold",
        "short": "Gold",
        "unit": "USD/oz",
        "candidates": ["GC=F", "XAUUSD=X"],
        "color": "#f59e0b",
    },
    {
        "id": "silver",
        "label": "Silver",
        "short": "Silver",
        "unit": "USD/oz",
        "candidates": ["SI=F", "XAGUSD=X"],
        "color": "#a8a29e",
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


def _download_close(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    interval: str = "1d",
) -> pd.Series:
    """Adjusted close for one Yahoo symbol over [start, end] (inclusive)."""
    try:
        import yfinance as yf
    except Exception as exc:
        logger.warning("yfinance unavailable: %s", exc)
        return pd.Series(dtype=float)

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
        return pd.Series(dtype=float)

    if raw is None or raw.empty:
        return pd.Series(dtype=float)

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"]
            series = close.iloc[:, 0] if getattr(close, "ndim", 1) > 1 else close
        else:
            series = raw.iloc[:, 0]
    else:
        series = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]

    out = pd.to_numeric(series, errors="coerce").dropna()
    if out.empty:
        return pd.Series(dtype=float)
    idx = pd.to_datetime(out.index)
    try:
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
    except Exception:
        try:
            idx = idx.tz_convert(None)
        except Exception:
            pass
    out.index = idx
    return out


def _pick_series(
    candidates: list[str],
    start: datetime,
    end: datetime,
    *,
    interval: str,
) -> tuple[str | None, pd.Series]:
    min_bars = 2 if interval == "1d" else 3
    for sym in candidates:
        series = _download_close(sym, start, end, interval=interval)
        if len(series) >= min_bars:
            return sym, series
    return None, pd.Series(dtype=float)


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
    """Build Oil / Dollar / Bond / Gold / Silver chart payload."""
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
        sym, raw = _pick_series(list(spec["candidates"]), start, end, interval=iv)
        if sym is None or raw.empty:
            errors[str(spec["id"])] = f"No data for {spec['label']} (tried {', '.join(spec['candidates'])})."
            series_out.append({
                "id": spec["id"],
                "label": spec["label"],
                "short": spec["short"],
                "unit": spec["unit"],
                "symbol": None,
                "color": spec["color"],
                "points": [],
                "error": errors[str(spec["id"])],
                "last": None,
                "change_pct": None,
            })
            continue

        if intraday:
            day_start = pd.Timestamp(start)
            day_end = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            clipped = raw[(raw.index >= day_start) & (raw.index <= day_end)]
        else:
            clipped = raw[(raw.index >= pd.Timestamp(start)) & (raw.index <= pd.Timestamp(end) + pd.Timedelta(days=1))]
        if clipped.empty:
            clipped = raw

        points = _series_to_points(clipped, intraday=intraday)
        if len(points) < 2:
            errors[str(spec["id"])] = f"Insufficient {iv} bars for {spec['label']} on this session."
            series_out.append({
                "id": spec["id"],
                "label": spec["label"],
                "short": spec["short"],
                "unit": spec["unit"],
                "symbol": sym,
                "color": spec["color"],
                "points": points,
                "error": errors[str(spec["id"])],
                "last": round(float(clipped.iloc[-1]), 4) if len(clipped) else None,
                "change_pct": None,
            })
            continue

        first = float(clipped.iloc[0])
        last = float(clipped.iloc[-1])
        change_pct = ((last / first) - 1.0) * 100.0 if first else None
        aligned[str(spec["id"])] = clipped
        series_out.append({
            "id": spec["id"],
            "label": spec["label"],
            "short": spec["short"],
            "unit": spec["unit"],
            "symbol": sym,
            "color": spec["color"],
            "points": points,
            "last": round(last, 4),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "from": points[0]["t"] if points else None,
            "to": points[-1]["t"] if points else None,
            "bars": len(points),
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
            {"id": s["id"], "label": s["label"], "short": s["short"], "color": s["color"]}
            for s in INSTRUMENTS
        ],
        "ok_count": ok_count,
        "errors": errors,
        "summary": " · ".join(summary_bits) if summary_bits else None,
        "plain_english": (
            f"Oil · Dollar · Bond · Gold · Silver — {range_txt}. "
            + ("Normalized % change overlay compares direction across units. " if chart else "")
            + ("Loaded: " + ", ".join(summary_bits) + "." if summary_bits else "No series loaded.")
        ),
        "how_to_read": [
            "Daily mode: pick From / To dates for multi-day history.",
            "Intraday mode: pick one session date + bar size (1m–1h) for same-day charts (Yahoo history window applies).",
            "Dollar Index rising usually pressures commodities; falling DXY often supports oil/gold/silver.",
            "Brent is the global oil benchmark; Gold/Silver are COMEX futures (GC=F / SI=F).",
            "US 2Y and US 10Y track rate expectations — watch 2s10s for risk appetite.",
            "Each panel uses native units; the overlay is % change from the first bar.",
            "Educational macro context only — not a trade signal.",
        ],
    }
