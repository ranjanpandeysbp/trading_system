"""
ticker_chart_engine.py
----------------------
Pro Trade — Ticker Chart

Daily date-range or same-session intraday OHLC for India / US / Crypto /
Commodities, with swing S1/S2 · R1/R2 support & resistance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "1h"}
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


def _to_yf_symbol(ticker: str, *, asset_class: str, market: str) -> str:
    from app.market_pulse.gap_trading import _yfinance_symbol

    is_crypto = asset_class == "crypto"
    return _yfinance_symbol(ticker, is_crypto=is_crypto, market=market)


def _download_ohlc(
    yf_symbol: str,
    start: datetime,
    end: datetime,
    *,
    interval: str = "1d",
) -> pd.DataFrame:
    try:
        import yfinance as yf
    except Exception as exc:
        logger.warning("yfinance unavailable: %s", exc)
        return pd.DataFrame()

    end_excl = end + timedelta(days=1)
    try:
        raw = yf.download(
            yf_symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end_excl.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        logger.debug("download failed for %s [%s]: %s", yf_symbol, interval, exc)
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
        "volume": vol if vol is not None else 0,
    }).dropna(subset=["close"])
    if out.empty:
        return pd.DataFrame()
    out.index = _strip_tz(pd.to_datetime(out.index))
    return out


def _series_to_points(series: pd.Series, *, intraday: bool) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for ts, val in series.items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v != v:
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


def _ohlc_to_candles(df: pd.DataFrame, *, intraday: bool) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        try:
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        except (TypeError, ValueError, KeyError):
            continue
        if any(x != x for x in (o, h, l, c)):
            continue
        t = pd.Timestamp(ts)
        if intraday:
            label = t.strftime("%H:%M")
            iso = t.isoformat()
        else:
            label = t.strftime("%Y-%m-%d")
            iso = label
        vol = None
        try:
            vol = float(row["volume"]) if "volume" in row and row["volume"] == row["volume"] else None
        except (TypeError, ValueError):
            vol = None
        candles.append({
            "t": iso,
            "label": label,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": round(vol, 2) if vol is not None else None,
        })
    return candles


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

    if not supports_below:
        supports_below = [period_low]
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


def compute_ticker_chart(
    *,
    ticker: str,
    asset_class: str = "india",
    mode: str = "daily",
    from_date: str | None = None,
    to_date: str | None = None,
    session_date: str | None = None,
    interval: str = "1d",
    market: str = "",
) -> dict[str, Any]:
    """Build close chart + OHLC candles + S/R for one ticker."""
    from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG, resolve_tickers
    from app.market_pulse.data_source_ctx import (
        attach_data_source,
        clear_tracking,
        start_tracking,
    )

    ac = (asset_class or "india").strip().lower()
    if ac not in ASSET_CLASS_CONFIG:
        ac = "india"
    cfg = ASSET_CLASS_CONFIG[ac]
    mkt = market or str(cfg.get("market") or "")

    raw_ticker = (ticker or "").strip()
    if not raw_ticker:
        return {"error": "Enter a ticker", "points": [], "candles": [], "support_resistance": None}

    resolved_list = resolve_tickers(ac, [raw_ticker])
    resolved = resolved_list[0] if resolved_list else raw_ticker.upper()
    yf_sym = _to_yf_symbol(resolved, asset_class=ac, market=mkt)

    intraday = (mode or "daily").strip().lower() == "intraday"
    iv = _normalize_interval(interval, intraday=intraday)

    if intraday:
        if not session_date:
            return {"error": "Pick a session date for intraday", "points": [], "candles": [], "support_resistance": None}
        day = _parse_date(session_date)
        max_lb = _INTRADAY_MAX_LOOKBACK_DAYS.get(iv, 60)
        # Yahoo needs a short lookback window that includes the session
        start = day - timedelta(days=min(max_lb - 1, 5))
        end = day
    else:
        if not from_date or not to_date:
            return {"error": "Pick from and to dates", "points": [], "candles": [], "support_resistance": None}
        start = _parse_date(from_date)
        end = _parse_date(to_date)
        if end < start:
            start, end = end, start

    start_tracking()
    try:
        ohlc = _download_ohlc(yf_sym, start, end, interval=iv)
        # Prefer marking source even on empty so FE can show badge consistently
        try:
            from app.market_pulse.data_source_ctx import mark_source
            if not ohlc.empty:
                ohlc = mark_source(ohlc, "yfinance")
        except Exception:
            pass

        if ohlc.empty:
            return attach_data_source({
                "error": f"No {iv} data for {resolved} ({yf_sym}) in this window.",
                "ticker": resolved,
                "yf_symbol": yf_sym,
                "asset_class": ac,
                "mode": "intraday" if intraday else "daily",
                "interval": iv,
                "points": [],
                "candles": [],
                "support_resistance": None,
            })

        if intraday:
            day_start = pd.Timestamp(_parse_date(session_date or start.strftime("%Y-%m-%d")))
            day_end = day_start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            clipped = ohlc[(ohlc.index >= day_start) & (ohlc.index <= day_end)]
        else:
            clipped = ohlc[
                (ohlc.index >= pd.Timestamp(start))
                & (ohlc.index <= pd.Timestamp(end) + pd.Timedelta(days=1))
            ]
        if clipped.empty:
            clipped = ohlc

        close = clipped["close"]
        points = _series_to_points(close, intraday=intraday)
        candles = _ohlc_to_candles(clipped, intraday=intraday)
        sr = _support_resistance(clipped, window=3 if intraday else 5)

        first = float(close.iloc[0]) if len(close) else None
        last = float(close.iloc[-1]) if len(close) else None
        change_pct = ((last / first) - 1.0) * 100.0 if first and last else None

        range_txt = (
            f"{session_date} · {iv}"
            if intraday
            else f"{start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} · {iv}"
        )

        return attach_data_source({
            "ticker": resolved,
            "yf_symbol": yf_sym,
            "asset_class": ac,
            "mode": "intraday" if intraday else "daily",
            "interval": iv,
            "from": points[0]["t"] if points else None,
            "to": points[-1]["t"] if points else None,
            "bars": len(points),
            "last": round(last, 4) if last is not None else None,
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "points": points,
            "candles": candles,
            "support_resistance": sr,
            "summary": f"{resolved} ({yf_sym}) · {range_txt} · Δ {change_pct:+.2f}%" if change_pct is not None else f"{resolved} · {range_txt}",
            "plain_english": (
                f"Ticker chart for {resolved} over {range_txt}. "
                f"Green S1/S2 = support · Red R1/R2 = resistance from swing pivots in this window."
            ),
            "how_to_read": [
                "Daily: pick From / To — chart loads as soon as both dates and a ticker are set.",
                "Intraday: pick session date + bar size (1m–1h). Yahoo keeps a limited intraday history window.",
                "Green dashed = support (S1 nearer, S2 deeper) · Red dashed = resistance (R1 nearer, R2 higher).",
                "Educational chart only — not a trade signal.",
            ],
        })
    finally:
        clear_tracking()
