"""
ticker_chart_engine.py
----------------------
Pro Trade — Ticker Chart

Daily date-range or same-session intraday OHLC for India / US / Crypto /
Commodities, with swing S1/S2 · R1/R2 support & resistance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "1h"}
_INTRADAY_MAX_LOOKBACK_DAYS = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 60, "1h": 60}


def _commodity_label(symbol: str, asset_class: str) -> str:
    from app.market_pulse.asset_class_config import ticker_display_label

    return ticker_display_label(symbol, asset_class) or symbol



def _parse_date(value: str) -> datetime:
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")


def _as_utc_ts(dt: datetime) -> float:
    """Naive calendar datetimes are treated as UTC for CoinDCX windows."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.astimezone(timezone.utc).timestamp()


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


def _coindcx_resolution(interval: str) -> str:
    """Map chart interval to a CoinDCX futures candlestick resolution."""
    iv = (interval or "1d").strip().lower()
    if iv in ("60m", "1h"):
        return "1h"
    if iv == "2m":
        return "1m"  # CoinDCX has no 2m — use 1m
    if iv in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"):
        return iv
    return "1d"


def _interval_seconds(interval: str) -> int:
    iv = _coindcx_resolution(interval)
    return {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
        "1w": 604800,
    }.get(iv, 86400)


def _download_coindcx_ohlc(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    interval: str = "1d",
) -> pd.DataFrame:
    """OHLCV from CoinDCX USDT-margined futures candlesticks."""
    from app.market_pulse.heatmap import coindcx_ohlcv_indexed

    res = _coindcx_resolution(interval)
    pad_days = 40 if res == "1d" else (3 if res in ("1h", "4h") else 1)
    start_ts = _as_utc_ts(start - timedelta(days=pad_days))
    end_ts = _as_utc_ts(end + timedelta(days=1))
    span = max(end_ts - start_ts, _interval_seconds(res))
    limit = int(span / _interval_seconds(res)) + 80
    limit = max(80, min(limit, 5000))

    df = coindcx_ohlcv_indexed(
        symbol,
        res,
        limit=limit,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    if df.empty:
        return pd.DataFrame()
    df.index = _strip_tz(pd.to_datetime(df.index))
    return df


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


INDICATOR_IDS = (
    "rsi",
    "macd",
    "supertrend",
    "vwap",
    "volume",
    "bollinger",
    "fibonacci",
    "ema_5",
    "ema_9",
    "ema_20",
    "ema_50",
    "ema_200",
)

DEFAULT_INDICATORS = ["volume", "ema_9", "ema_50"]


def _safe_last(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    v = series.iloc[-1]
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _enrich_with_indicators(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    """Compute full indicator suite; return enriched frame, per-id readings, fib levels."""
    from app.market_pulse.indicators import (
        add_bollinger_bands,
        add_ema,
        add_macd,
        add_rsi,
        add_supertrend,
        add_vwap,
    )

    work = df.copy()
    for p in (5, 9, 20, 50, 200):
        work = add_ema(work, p)
    work = add_rsi(work, 14)
    work = add_macd(work, 12, 26, 9)
    work = add_bollinger_bands(work, 20, 2.0)
    work = add_supertrend(work, 10, 3.0)
    if "volume" in work.columns:
        work = add_vwap(work)

    close = work["close"].astype(float)
    last = float(close.iloc[-1])
    hi = float(work["high"].astype(float).max())
    lo = float(work["low"].astype(float).min())
    span = hi - lo if hi > lo else 0.0

    fib_levels: list[dict[str, Any]] = []
    if span > 0:
        for ratio, label in (
            (0.0, "Fib 0%"),
            (0.236, "Fib 23.6%"),
            (0.382, "Fib 38.2%"),
            (0.5, "Fib 50%"),
            (0.618, "Fib 61.8%"),
            (0.786, "Fib 78.6%"),
            (1.0, "Fib 100%"),
        ):
            price = round(hi - ratio * span, 4)
            fib_levels.append({
                "key": f"fib_{ratio}",
                "label": label,
                "ratio": ratio,
                "price": price,
                "kind": "fibonacci",
            })

    rsi_v = _safe_last(work.get("rsi_14"))
    macd_v = _safe_last(work.get("macd_12_26"))
    macd_sig = _safe_last(work.get("macd_signal_12_26_9"))
    macd_hist = _safe_last(work.get("macd_hist_12_26_9"))
    st = _safe_last(work.get("supertrend_10_3.0"))
    st_dir = _safe_last(work.get("supertrend_dir_10_3.0"))
    vwap_v = _safe_last(work.get("vwap")) if "vwap" in work.columns else None
    bb_u = _safe_last(work.get("bb_upper_20_2.0"))
    bb_m = _safe_last(work.get("bb_middle_20_2.0"))
    bb_l = _safe_last(work.get("bb_lower_20_2.0"))

    readings: dict[str, Any] = {}

    # RSI
    if rsi_v is not None:
        if rsi_v >= 70:
            rsi_sig, rsi_bias = "overbought", "bearish"
        elif rsi_v <= 30:
            rsi_sig, rsi_bias = "oversold", "bullish"
        else:
            rsi_sig, rsi_bias = "neutral", "neutral"
        readings["rsi"] = {
            "id": "rsi",
            "label": "RSI(14)",
            "value": round(rsi_v, 2),
            "signal": rsi_sig,
            "bias": rsi_bias,
            "detail": f"RSI {rsi_v:.1f} — {rsi_sig}",
        }

    # MACD
    if macd_v is not None and macd_sig is not None:
        if macd_v > macd_sig and (macd_hist or 0) >= 0:
            macd_sig_txt, macd_bias = "bullish cross / above signal", "bullish"
        elif macd_v < macd_sig and (macd_hist or 0) <= 0:
            macd_sig_txt, macd_bias = "bearish cross / below signal", "bearish"
        else:
            macd_sig_txt, macd_bias = "mixed", "neutral"
        readings["macd"] = {
            "id": "macd",
            "label": "MACD(12,26,9)",
            "value": round(macd_v, 4),
            "signal_line": round(macd_sig, 4),
            "histogram": round(macd_hist, 4) if macd_hist is not None else None,
            "signal": macd_sig_txt,
            "bias": macd_bias,
            "detail": f"MACD {macd_v:.4f} vs signal {macd_sig:.4f} — {macd_sig_txt}",
        }

    # Supertrend
    if st is not None and st_dir is not None:
        bull = int(st_dir) >= 1
        readings["supertrend"] = {
            "id": "supertrend",
            "label": "Supertrend(10,3)",
            "value": round(st, 4),
            "direction": "up" if bull else "down",
            "signal": "price above ST (bullish)" if bull else "price below ST (bearish)",
            "bias": "bullish" if bull else "bearish",
            "detail": (
                f"Supertrend {st:.2f} · trend {'UP' if bull else 'DOWN'} · "
                f"price {'above' if last >= st else 'below'} line"
            ),
        }

    # VWAP
    if vwap_v is not None and vwap_v > 0:
        above = last >= vwap_v
        dist = (last / vwap_v - 1.0) * 100.0
        readings["vwap"] = {
            "id": "vwap",
            "label": "VWAP",
            "value": round(vwap_v, 4),
            "distance_pct": round(dist, 3),
            "signal": "above VWAP" if above else "below VWAP",
            "bias": "bullish" if above else "bearish",
            "detail": f"Price {'above' if above else 'below'} VWAP ({vwap_v:.2f}) by {dist:+.2f}%",
        }

    # Volume
    if "volume" in work.columns:
        vol = work["volume"].astype(float)
        vol_ma = vol.rolling(20, min_periods=5).mean()
        v_now = _safe_last(vol)
        v_ma = _safe_last(vol_ma)
        if v_now is not None and v_ma is not None and v_ma > 0:
            ratio = v_now / v_ma
            if ratio >= 1.5:
                v_sig = "high vs MA20"
            elif ratio <= 0.7:
                v_sig = "low vs MA20"
            else:
                v_sig = "average"
            readings["volume"] = {
                "id": "volume",
                "label": "Volume",
                "value": round(v_now, 2),
                "ma20": round(v_ma, 2),
                "ratio": round(ratio, 2),
                "signal": v_sig,
                "bias": "neutral",
                "detail": f"Volume {v_now:,.0f} vs MA20 {v_ma:,.0f} ({ratio:.2f}×) — {v_sig}",
            }

    # Bollinger
    if bb_u is not None and bb_l is not None and bb_m is not None:
        if last >= bb_u:
            bb_sig, bb_bias = "at/above upper band", "bearish"
        elif last <= bb_l:
            bb_sig, bb_bias = "at/below lower band", "bullish"
        elif last >= bb_m:
            bb_sig, bb_bias = "above mid band", "bullish"
        else:
            bb_sig, bb_bias = "below mid band", "bearish"
        readings["bollinger"] = {
            "id": "bollinger",
            "label": "Bollinger(20,2)",
            "upper": round(bb_u, 4),
            "mid": round(bb_m, 4),
            "lower": round(bb_l, 4),
            "signal": bb_sig,
            "bias": bb_bias,
            "detail": f"BB U {bb_u:.2f} / M {bb_m:.2f} / L {bb_l:.2f} — price {bb_sig}",
        }

    # Fibonacci
    if fib_levels:
        nearest = min(fib_levels, key=lambda lv: abs(float(lv["price"]) - last))
        readings["fibonacci"] = {
            "id": "fibonacci",
            "label": "Fibonacci (range)",
            "high": round(hi, 4),
            "low": round(lo, 4),
            "nearest": nearest["label"],
            "nearest_price": nearest["price"],
            "signal": f"nearest {nearest['label']}",
            "bias": "neutral",
            "detail": (
                f"Range Fib high {hi:.2f} → low {lo:.2f}; price nearest {nearest['label']} "
                f"({nearest['price']:.2f})"
            ),
            "levels": fib_levels,
        }

    # EMAs
    for p in (5, 9, 20, 50, 200):
        key = f"ema_{p}"
        col = f"ema_{p}"
        ev = _safe_last(work.get(col))
        if ev is None or ev <= 0:
            continue
        above = last >= ev
        dist = (last / ev - 1.0) * 100.0
        readings[key] = {
            "id": key,
            "label": f"EMA {p}",
            "value": round(ev, 4),
            "distance_pct": round(dist, 3),
            "signal": "above" if above else "below",
            "bias": "bullish" if above else "bearish",
            "detail": f"Price {'above' if above else 'below'} EMA{p} ({ev:.2f}) by {dist:+.2f}%",
        }

    return work, readings, fib_levels


def _points_with_indicators(df: pd.DataFrame, *, intraday: bool) -> list[dict[str, Any]]:
    """Close/volume points plus overlay / oscillator series for the FE chart."""
    extras = {
        "ema_5": "ema_5",
        "ema_9": "ema_9",
        "ema_20": "ema_20",
        "ema_50": "ema_50",
        "ema_200": "ema_200",
        "vwap": "vwap",
        "bb_upper": "bb_upper_20_2.0",
        "bb_mid": "bb_middle_20_2.0",
        "bb_lower": "bb_lower_20_2.0",
        "supertrend": "supertrend_10_3.0",
        "rsi": "rsi_14",
        "macd": "macd_12_26",
        "macd_signal": "macd_signal_12_26_9",
        "macd_hist": "macd_hist_12_26_9",
    }
    series_maps: dict[str, list[float | None]] = {}
    n = len(df)
    for out_key, col in extras.items():
        if col not in df.columns:
            series_maps[out_key] = [None] * n
            continue
        vals: list[float | None] = []
        for v in df[col].tolist():
            try:
                f = float(v)
                vals.append(round(f, 6) if f == f else None)
            except (TypeError, ValueError):
                vals.append(None)
        series_maps[out_key] = vals

    # base points may skip bad rows — rebuild by iterating df like ohlc_to_chart_points
    points: list[dict[str, Any]] = []
    has_vol = "volume" in df.columns
    i = -1
    for ts, row in df.iterrows():
        i += 1
        try:
            v = float(row["close"])
        except (TypeError, ValueError, KeyError):
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
        vol = None
        if has_vol:
            try:
                raw_vol = float(row["volume"])
                if raw_vol == raw_vol and raw_vol >= 0:
                    vol = round(raw_vol, 2)
            except (TypeError, ValueError):
                vol = None
        pt: dict[str, Any] = {"t": iso, "label": label, "value": round(v, 4), "volume": vol}
        for out_key, vals in series_maps.items():
            if i < len(vals) and vals[i] is not None:
                pt[out_key] = vals[i]
        points.append(pt)
    return points


def _build_signal_description(
    readings: dict[str, Any],
    *,
    selected: list[str],
    ticker: str,
    range_txt: str,
    change_pct: float | None,
    vol_sr_plain: str,
) -> str:
    """Aggregate a readable signal blurb from the selected indicators."""
    parts: list[str] = [
        f"{ticker} · {range_txt}"
        + (f" · Δ {change_pct:+.2f}%" if change_pct is not None else "")
        + "."
    ]
    if vol_sr_plain:
        parts.append(vol_sr_plain)

    selected_set = {s for s in selected if s in INDICATOR_IDS}
    if not selected_set:
        selected_set = set(DEFAULT_INDICATORS)

    bull = bear = 0
    lines: list[str] = []
    order = [
        "ema_5", "ema_9", "ema_20", "ema_50", "ema_200",
        "vwap", "bollinger", "supertrend", "rsi", "macd", "volume", "fibonacci",
    ]
    for key in order:
        if key not in selected_set:
            continue
        r = readings.get(key)
        if not r:
            continue
        lines.append(str(r.get("detail") or r.get("signal") or ""))
        bias = str(r.get("bias") or "neutral")
        if bias == "bullish":
            bull += 1
        elif bias == "bearish":
            bear += 1

    if lines:
        parts.append("Indicators: " + " · ".join(lines))

    if bull or bear:
        if bull > bear + 1:
            tilt = "Overall indicator tilt: bullish"
        elif bear > bull + 1:
            tilt = "Overall indicator tilt: bearish"
        else:
            tilt = "Overall indicator tilt: mixed / neutral"
        parts.append(f"{tilt} ({bull} bullish · {bear} bearish of {bull + bear} scored).")

    parts.append("Educational read only — not a buy/sell signal.")
    return " ".join(p for p in parts if p)


def _normalize_indicators(indicators: list[str] | None) -> list[str]:
    if not indicators:
        return list(DEFAULT_INDICATORS)
    out: list[str] = []
    seen: set[str] = set()
    for raw in indicators:
        key = str(raw or "").strip().lower().replace(" ", "_")
        if key == "bb":
            key = "bollinger"
        if key == "fib":
            key = "fibonacci"
        if key.startswith("ema") and "_" not in key and key[3:].isdigit():
            key = f"ema_{key[3:]}"
        if key in INDICATOR_IDS and key not in seen:
            seen.add(key)
            out.append(key)
    return out or list(DEFAULT_INDICATORS)


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
    indicators: list[str] | None = None,
) -> dict[str, Any]:
    """Build close chart + OHLC candles + S/R + selectable indicators for one ticker."""
    from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG, resolve_tickers
    from app.market_pulse.data_source_ctx import (
        attach_data_source,
        clear_tracking,
        start_tracking,
    )

    selected = _normalize_indicators(indicators)
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
    is_crypto = ac == "crypto"
    yf_sym = _to_yf_symbol(resolved, asset_class=ac, market=mkt) if not is_crypto else ""
    # CoinDCX futures pair (B-BTC_USDT style after API normalize)
    display_sym = resolved if is_crypto else yf_sym

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
        if is_crypto:
            ohlc = _download_coindcx_ohlc(resolved, start, end, interval=iv)
            if ohlc.empty:
                # Last-resort yfinance only if CoinDCX returns nothing
                logger.warning("CoinDCX futures empty for %s — trying yfinance fallback", resolved)
                ohlc = _download_ohlc(
                    _to_yf_symbol(resolved, asset_class=ac, market=mkt),
                    start,
                    end,
                    interval=iv,
                )
                if not ohlc.empty:
                    try:
                        from app.market_pulse.data_source_ctx import mark_source
                        ohlc = mark_source(ohlc, "yfinance")
                    except Exception:
                        pass
        else:
            ohlc = _download_ohlc(yf_sym, start, end, interval=iv)
            try:
                from app.market_pulse.data_source_ctx import mark_source
                if not ohlc.empty:
                    ohlc = mark_source(ohlc, "yfinance")
            except Exception:
                pass

        if ohlc.empty:
            src = "CoinDCX futures" if is_crypto else yf_sym
            return attach_data_source({
                "error": f"No {iv} data for {resolved} ({src}) in this window.",
                "ticker": resolved,
                "yf_symbol": display_sym,
                "source_symbol": display_sym,
                "data_provider": "coindcx" if is_crypto else "yfinance",
                "asset_class": ac,
                "mode": "intraday" if intraday else "daily",
                "interval": iv,
                "points": [],
                "candles": [],
                "support_resistance": None,
                "indicators": selected,
                "available_indicators": list(INDICATOR_IDS),
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
        from app.market_pulse.sr_volume_summary import build_sr_volume_summary

        enriched, readings, fib_levels = _enrich_with_indicators(clipped)
        points = _points_with_indicators(enriched, intraday=intraday)
        candles = _ohlc_to_candles(clipped, intraday=intraday)
        sr = _support_resistance(clipped, window=3 if intraday else 5)
        vol_sr = build_sr_volume_summary(clipped, sr, name=resolved)

        first = float(close.iloc[0]) if len(close) else None
        last = float(close.iloc[-1]) if len(close) else None
        change_pct = ((last / first) - 1.0) * 100.0 if first and last else None

        range_txt = (
            f"{session_date} · {iv}"
            if intraday
            else f"{start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} · {iv}"
        )

        vol_plain = str(vol_sr.get("plain_english") or "")
        signal_description = _build_signal_description(
            readings,
            selected=selected,
            ticker=resolved,
            range_txt=range_txt,
            change_pct=change_pct,
            vol_sr_plain=vol_plain,
        )
        selected_readings = {k: readings[k] for k in selected if k in readings}

        from app.market_pulse.pro_trade_shared import build_bias_sr_trade_setup

        biases = [
            str((readings.get(k) or {}).get("bias") or "neutral")
            for k in selected
            if k in readings
        ]
        trade_setup = build_bias_sr_trade_setup(
            clipped,
            biases=biases,
            support=sr.get("s1") if isinstance(sr, dict) else None,
            resistance=sr.get("r1") if isinstance(sr, dict) else None,
            timeframe=iv,
            base_reason="Ticker Chart selected indicators + S1/R1",
        )

        # Fall / Rise next-move forecasts (same engine as Falling Knife) for all asset classes.
        # Prefer ~90d daily history so short chart windows still produce useful forecasts.
        from app.market_pulse.falling_knife_engine import (
            build_fall_rise_forecasts_from_df,
            fetch_and_build_move_forecasts,
        )

        move_forecasts = fetch_and_build_move_forecasts(
            resolved,
            asset_class=ac,
            market=mkt,
            threshold_pct=10.0,
            move_side="both",
            lookback_days=90,
            entry=last,
        )
        if not (move_forecasts.get("forecast") or {}):
            forecast_src = ohlc if ohlc is not None and len(ohlc) >= 8 else clipped
            move_forecasts = build_fall_rise_forecasts_from_df(
                forecast_src,
                threshold_pct=10.0,
                move_side="both",
                timeframe="1d" if not intraday else iv,
                entry=last,
            )

        how_to = [
            "Daily: pick From / To — chart loads as soon as both dates and a ticker are set.",
            "Intraday: pick session date + bar size (1m–1h).",
            "Toggle indicators (RSI, MACD, Supertrend, VWAP, Volume, Bollinger, Fibonacci, EMAs) — overlays and signal text update together.",
            "Trade setup shows % confidence, %SL, and %TP from selected-indicator tilt + S1/R1 (ATR-sane stops).",
            "Fall / Rise forecast cards use ≥10% historical moves on the loaded bars (Conf · next time · move · SL% · TP%).",
            "Green dashed = support (S1 nearer, S2 deeper) · Red dashed = resistance (R1 nearer, R2 higher).",
            "RSI / MACD appear as sub-panels; EMAs / VWAP / BB / Supertrend / Fib overlay on price.",
            "Educational heuristics — not a trade signal.",
        ]
        if is_crypto:
            how_to.insert(
                1,
                "Crypto uses CoinDCX USDT-margined futures candlesticks (pcode=f) — not Yahoo spot.",
            )
        else:
            how_to.insert(1, "India / US / Commodities use Yahoo Finance OHLC (Groww/IndMoney where wired elsewhere).")

        payload = {
            "ticker": resolved,
            "yf_symbol": display_sym,
            "source_symbol": display_sym,
            "data_provider": "coindcx" if is_crypto else "yfinance",
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
            "volume_sr_summary": vol_sr,
            "indicators": selected,
            "available_indicators": list(INDICATOR_IDS),
            "indicator_readings": readings,
            "selected_indicator_readings": selected_readings,
            "fib_levels": fib_levels,
            "trade_setup": trade_setup,
            "confidence_pct": trade_setup.get("confidence_pct"),
            "sl_pct": trade_setup.get("sl_pct"),
            "tp_pct": trade_setup.get("tp_pct"),
            "direction": trade_setup.get("direction"),
            "action": trade_setup.get("action"),
            "forecast": move_forecasts.get("forecast") or {},
            "primary_forecast": move_forecasts.get("primary_forecast"),
            "fall_count": move_forecasts.get("fall_count"),
            "rise_count": move_forecasts.get("rise_count"),
            "signal_description": signal_description,
            "summary": (
                f"{_commodity_label(resolved, ac)} ({display_sym}"
                + (" · CoinDCX futures" if is_crypto else "")
                + f") · {range_txt}"
                + (f" · Δ {change_pct:+.2f}%" if change_pct is not None else "")
            ),
            "plain_english": signal_description,
            "how_to_read": how_to,
        }
        from app.market_pulse.asset_class_config import attach_ticker_name

        return attach_data_source(attach_ticker_name(payload, asset_class=ac))
    finally:
        clear_tracking()
