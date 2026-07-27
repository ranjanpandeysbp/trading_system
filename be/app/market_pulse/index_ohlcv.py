"""
Shared index OHLC / close resolution for all tabs.

Tries Yahoo Finance index tickers first; falls back to equal-weight constituent
proxy OHLC when ^CNX* symbols are missing (newer Nifty sector indices).
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pandas as pd
import yfinance as yf

from app.market_pulse.nse_index_yfinance import (
    BROKEN_YF_INDEX_TICKERS,
    canonical_index_name,
    index_requires_constituent_proxy,
    index_yf_candidates,
    market_display_to_yf,
    normalize_index_name,
    resolve_nse_equity_symbol,
    stock_symbol_to_yf,
    filter_tradeable_nse_symbols,
)
from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

_OHLC_COLS = ("open", "high", "low", "close")
_MIN_BARS = 5
_CONSTITUENT_BATCH = 40

# Yahoo interval → Groww TF_INDIA key (weekly/monthly stay on Yahoo)
_YF_INTERVAL_TO_GROWW: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

# Groww/tf_key → (yfinance period, yfinance interval)
_TF_TO_YF: dict[str, tuple[str, str]] = {
    "1m": ("7d", "1m"),
    "5m": ("60d", "5m"),
    "15m": ("60d", "15m"),
    "30m": ("60d", "30m"),
    "1h": ("60d", "1h"),
    "4h": ("730d", "1h"),
    "1d": ("5y", "1d"),
}


def _tf_to_yf_period_interval(tf_key: str) -> tuple[str, str]:
    return _TF_TO_YF.get(tf_key, ("1y", "1d"))


def _period_to_bar_limit(period: str) -> int:
    p = (period or "6mo").strip().lower()
    if p.endswith("mo"):
        try:
            return max(30, int(p[:-2]) * 22 + 15)
        except ValueError:
            return 130
    if p.endswith("d"):
        try:
            return max(20, int(p[:-1]) + 10)
        except ValueError:
            return 60
    if p.endswith("y"):
        try:
            return int(float(p[:-1]) * 252)
        except ValueError:
            return 252
    return 130


def _fetch_index_ohlcv_groww(
    index_name: str,
    tf_key: str,
    groww_token: str,
    exchange: str = "NSE",
    limit: int = 400,
) -> pd.DataFrame | None:
    """Groww historical candles for an NSE index (requires bearer token)."""
    if not (groww_token or "").strip():
        return None
    from app.market_pulse.heatmap import fetch_groww_ohlcv
    from app.market_pulse.nse_index_yfinance import index_name_to_groww_symbols

    for sym in index_name_to_groww_symbols(index_name):
        try:
            raw = fetch_groww_ohlcv(sym, exchange, tf_key, groww_token.strip(), limit=limit)
            df = _normalize_ohlc_df(raw)
            if df is not None and len(df) >= _MIN_BARS:
                logger.debug("Groww index OHLC %s via %s [%s] (%d bars)", index_name, sym, tf_key, len(df))
                return df
        except Exception as exc:
            logger.debug("Groww index OHLC skip %s (%s): %s", index_name, sym, exc)
    return None


def _fetch_index_ohlcv_yfinance_index(
    index_name: str,
    tf_key: str,
    limit: int = 400,
) -> pd.DataFrame | None:
    """yfinance index OHLC using verified tickers only; constituent proxy if none."""
    canonical = canonical_index_name(index_name)
    period, interval = _tf_to_yf_period_interval(tf_key)

    for yf_sym in index_yf_candidates(canonical):
        if not yf_sym or yf_sym in BROKEN_YF_INDEX_TICKERS:
            continue
        df = download_yf_ticker_interval_ohlcv(yf_sym, interval=interval, period=period)
        df = _normalize_ohlc_df(df)
        if df is not None and len(df) >= _MIN_BARS:
            return df.tail(limit)

    return _fetch_constituent_proxy_interval_ohlcv(canonical, interval, period, limit=limit)


def _normalize_ohlc_df(raw: pd.DataFrame | None) -> pd.DataFrame | None:
    if raw is None or raw.empty:
        return None
    sub = raw.dropna(how="all").copy()
    if isinstance(sub.columns, pd.MultiIndex):
        sub.columns = [
            str(c[-1]).lower() if isinstance(c, tuple) else str(c).lower()
            for c in sub.columns
        ]
    else:
        sub.columns = [str(c).lower() for c in sub.columns]
    rename = {"adj close": "close"}
    sub = sub.rename(columns={k: v for k, v in rename.items() if k in sub.columns})
    if sub.columns.duplicated().any():
        sub = sub.loc[:, ~sub.columns.duplicated()]
    if not set(_OHLC_COLS).issubset(set(sub.columns)):
        return None
    for col in _OHLC_COLS:
        sub[col] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=list(_OHLC_COLS), how="any")
    return sub if len(sub) >= _MIN_BARS else None


def yf_ohlcv_from_download(raw: pd.DataFrame, yf_sym: str) -> pd.DataFrame | None:
    """Extract one ticker's OHLCV from a yfinance batch download."""
    if raw is None or raw.empty:
        return None
    sub: pd.DataFrame | None = None
    if isinstance(raw.columns, pd.MultiIndex):
        lv0 = raw.columns.get_level_values(0)
        lv1 = raw.columns.get_level_values(1) if raw.columns.nlevels > 1 else pd.Index([])
        if yf_sym in lv0:
            sub = raw[yf_sym]
        elif yf_sym in lv1:
            sub = raw.xs(yf_sym, axis=1, level=1)
        elif str(lv0[0]).lower() in _OHLC_COLS and len(set(lv1)) == 1:
            sub = raw
    elif "Close" in raw.columns or "close" in [str(c).lower() for c in raw.columns]:
        sub = raw
    return _normalize_ohlc_df(sub)


def download_yf_ticker_ohlcv(yf_sym: str, period: str = "6mo") -> pd.DataFrame | None:
    """Download daily OHLC for a single Yahoo Finance symbol."""
    return download_yf_ticker_interval_ohlcv(yf_sym, interval="1d", period=period)


def download_yf_ticker_interval_ohlcv(
    yf_sym: str,
    interval: str = "1d",
    period: str = "6mo",
) -> pd.DataFrame | None:
    """Download OHLC for a single Yahoo Finance symbol at the given interval."""
    if not yf_sym or yf_sym in BROKEN_YF_INDEX_TICKERS:
        return None
    interval = (interval or "1d").strip()
    try:
        raw = yf.download(
            yf_sym,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        df = yf_ohlcv_from_download(raw, yf_sym)
        if df is not None:
            return df
        hist = yf.Ticker(yf_sym).history(period=period, interval=interval, auto_adjust=True)
        return _normalize_ohlc_df(hist)
    except Exception as exc:
        logger.debug("yfinance OHLC skip (%s %s): %s", yf_sym, interval, exc)
        return None


def download_stock_ohlcv_batch(
    symbols: list[str],
    period: str = "6mo",
    limit: int = _CONSTITUENT_BATCH,
) -> dict[str, pd.DataFrame]:
    """Batch-download NSE equity OHLC (.NS) for constituent proxy builds."""
    syms = filter_tradeable_nse_symbols([s.strip().upper() for s in symbols if s], limit=limit)
    if not syms:
        return {}
    tickers = [stock_symbol_to_yf(s) for s in syms]
    out: dict[str, pd.DataFrame] = {}
    chunk_size = 35
    for start in range(0, len(tickers), chunk_size):
        chunk_syms = syms[start:start + chunk_size]
        chunk_tkrs = tickers[start:start + chunk_size]
        try:
            raw = yf.download(
                chunk_tkrs,
                period=period,
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as exc:
            logger.warning("Constituent batch download error: %s", exc)
            continue
        if raw is None or raw.empty:
            continue
        for sym, tkr in zip(chunk_syms, chunk_tkrs):
            df = yf_ohlcv_from_download(raw, tkr)
            if df is not None:
                out[sym] = df
    missing = [s for s in syms if s not in out]
    for sym in missing[:15]:
        df = download_yf_ticker_ohlcv(stock_symbol_to_yf(sym), period=period)
        if df is not None:
            out[sym] = df
    return out


def download_stock_ohlcv_batch_interval(
    symbols: list[str],
    interval: str = "1d",
    period: str = "6mo",
    limit: int = _CONSTITUENT_BATCH,
) -> dict[str, pd.DataFrame]:
    """Batch-download NSE equity OHLC at a given interval for constituent proxies."""
    syms = filter_tradeable_nse_symbols([s.strip().upper() for s in symbols if s], limit=limit)
    if not syms:
        return {}
    tickers = [stock_symbol_to_yf(s) for s in syms]
    out: dict[str, pd.DataFrame] = {}
    chunk_size = 35
    for start in range(0, len(tickers), chunk_size):
        chunk_syms = syms[start:start + chunk_size]
        chunk_tkrs = tickers[start:start + chunk_size]
        try:
            raw = yf.download(
                chunk_tkrs,
                period=period,
                interval=interval,
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as exc:
            logger.debug("Constituent interval batch download error: %s", exc)
            continue
        if raw is None or raw.empty:
            continue
        for sym, tkr in zip(chunk_syms, chunk_tkrs):
            df = yf_ohlcv_from_download(raw, tkr)
            if df is not None:
                out[sym] = df
    missing = [s for s in syms if s not in out]
    for sym in missing[:15]:
        df = download_yf_ticker_interval_ohlcv(stock_symbol_to_yf(sym), interval=interval, period=period)
        if df is not None:
            out[sym] = df
    return out


def _fetch_constituent_proxy_interval_ohlcv(
    index_name: str,
    interval: str = "1d",
    period: str = "6mo",
    limit: int = 400,
) -> pd.DataFrame | None:
    """Equal-weight constituent proxy at any interval (fallback when index ticker missing)."""
    canonical = canonical_index_name(index_name)
    symbols = filter_tradeable_nse_symbols(get_index_constituent_symbols(canonical), limit=15)
    if not symbols:
        return None
    ohlcv_map = download_stock_ohlcv_batch_interval(symbols, interval=interval, period=period)
    proxy = build_constituent_proxy_ohlcv(ohlcv_map)
    if proxy is not None:
        logger.info(
            "Index OHLC proxy (%s) for %s from %d/%d constituents",
            interval, canonical, len(ohlcv_map), len(symbols),
        )
        return proxy.tail(limit)
    return None


def build_constituent_proxy_ohlcv(ohlcv_map: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    """Equal-weight normalized OHLC proxy across index constituents."""
    frames: list[pd.DataFrame] = []
    for df in ohlcv_map.values():
        norm = _normalize_ohlc_df(df)
        if norm is not None:
            frames.append(norm)
    if not frames:
        return None
    aligned: list[pd.DataFrame] = []
    for df in frames:
        sub = df[list(_OHLC_COLS)].astype(float).copy()
        first = sub.iloc[0].replace(0, np.nan)
        sub = sub.div(first, axis=1)
        aligned.append(sub)
    base = aligned[0]
    for other in aligned[1:]:
        base = base.add(other, fill_value=0)
    proxy = base / len(aligned)
    scale = float(np.nanmean([float(df["close"].iloc[-1]) for df in frames]))
    if scale > 0:
        proxy = proxy * scale
    return _normalize_ohlc_df(proxy.dropna(how="all"))


def _fetch_constituent_proxy_ohlcv(index_name: str, period: str) -> pd.DataFrame | None:
    canonical = canonical_index_name(index_name)
    symbols = filter_tradeable_nse_symbols(get_index_constituent_symbols(canonical), limit=15)
    if not symbols:
        return None
    ohlcv_map = download_stock_ohlcv_batch(symbols, period=period)
    proxy = build_constituent_proxy_ohlcv(ohlcv_map)
    if proxy is not None:
        logger.info(
            "Index OHLC proxy for %s from %d/%d constituents",
            canonical,
            len(ohlcv_map),
            len(symbols),
        )
    return proxy


@lru_cache(maxsize=128)
def _fetch_index_daily_ohlcv_cached(index_name: str, period: str) -> pd.DataFrame | None:
    """LRU-cached resolver (call clear_index_ohlcv_cache() after data refresh)."""
    name = (index_name or "").strip()
    if not name:
        return None

    display_yf = market_display_to_yf(name)
    if display_yf:
        df = download_yf_ticker_ohlcv(display_yf, period=period)
        if df is not None:
            return df

    canonical = canonical_index_name(name)
    if index_requires_constituent_proxy(canonical):
        proxy = _fetch_constituent_proxy_ohlcv(canonical, period)
        if proxy is not None:
            return proxy

    for yf_sym in index_yf_candidates(canonical):
        if yf_sym in BROKEN_YF_INDEX_TICKERS:
            continue
        df = download_yf_ticker_ohlcv(yf_sym, period=period)
        if df is not None:
            return df

    return _fetch_constituent_proxy_ohlcv(canonical, period)


def fetch_index_daily_ohlcv(
    index_name: str,
    period: str = "6mo",
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame | None:
    """Daily OHLC — Groww API when token set, else Yahoo / constituent proxy."""
    name = (index_name or "").strip()
    if not name:
        return None
    limit = _period_to_bar_limit(period)
    if groww_token:
        df = _fetch_index_ohlcv_groww(name, "1d", groww_token, exchange, limit=limit)
        if df is not None:
            return df
        df = _fetch_index_ohlcv_yfinance_index(name, "1d", limit=limit)
        if df is not None:
            return df
    df = _fetch_index_daily_ohlcv_cached(name, period)
    if df is not None:
        return df
    return _fetch_constituent_proxy_ohlcv(canonical_index_name(name), period)


def fetch_index_close_series(
    index_name: str,
    period: str = "6mo",
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.Series | None:
    """Daily close series for an NSE index."""
    df = fetch_index_daily_ohlcv(
        index_name, period=period, groww_token=groww_token, exchange=exchange,
    )
    if df is None or df.empty:
        return None
    closes = df["close"].dropna()
    return closes if not closes.empty else None


def fetch_index_interval_close_series(
    index_name: str,
    interval: str = "1d",
    period: str = "5d",
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int | None = None,
) -> pd.Series | None:
    """Close series at 5m / 1h / 1d — Groww when token set, else Yahoo / constituent proxy."""
    name = (index_name or "").strip()
    if not name:
        return None

    canonical = canonical_index_name(name)
    bar_limit = limit if limit is not None else _period_to_bar_limit(period)
    groww_tf = _YF_INTERVAL_TO_GROWW.get(interval)
    yf_period, yf_interval = _tf_to_yf_period_interval(groww_tf or interval)

    if groww_token and groww_tf:
        df = _fetch_index_ohlcv_groww(name, groww_tf, groww_token, exchange, limit=bar_limit)
        if df is None:
            df = _fetch_index_ohlcv_yfinance_index(name, groww_tf, limit=bar_limit)
        if df is not None and not df.empty:
            closes = df["close"].dropna()
            if not closes.empty:
                return closes

    display_yf = market_display_to_yf(canonical)
    if display_yf:
        df = download_yf_ticker_interval_ohlcv(display_yf, interval=interval, period=period)
        if df is not None and not df.empty:
            closes = df["close"].dropna()
            if not closes.empty:
                return closes

    for yf_sym in index_yf_candidates(canonical):
        if yf_sym in BROKEN_YF_INDEX_TICKERS:
            continue
        df = download_yf_ticker_interval_ohlcv(yf_sym, interval=interval, period=period)
        if df is not None and not df.empty:
            closes = df["close"].dropna()
            if not closes.empty:
                return closes

    if interval == "1d":
        return fetch_index_close_series(
            name, period=period, groww_token=groww_token, exchange=exchange,
        )

    proxy = _fetch_constituent_proxy_interval_ohlcv(
        canonical, interval=yf_interval, period=yf_period, limit=bar_limit,
    )
    if proxy is not None and not proxy.empty:
        closes = proxy["close"].dropna()
        return closes if not closes.empty else None

    return None


def fetch_index_daily_ohlcv_title(index_name: str, period: str = "6mo") -> pd.DataFrame | None:
    """OHLC with Title-case columns (Open/High/Low/Close) for SMC-style consumers."""
    df = fetch_index_daily_ohlcv(index_name, period=period)
    if df is None:
        return None
    out = df.copy()
    out.columns = [c.title() for c in out.columns]
    return out


def fetch_index_ohlcv_for_interval(
    index_name: str,
    tf_key: str,
    limit: int = 400,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame | None:
    """Unified index OHLC: Groww → verified Yahoo → constituent proxy. The
    final row is dropped if it's a still-forming candle for `tf_key` (see
    bar_utils.py) — this path previously bypassed that gate entirely, unlike
    every other OHLCV fetcher in the app."""
    from app.market_pulse.bar_utils import last_closed_bar

    df = _fetch_index_ohlcv_for_interval_raw(index_name, tf_key, limit, groww_token=groww_token, exchange=exchange)
    return last_closed_bar(df, tf_key) if df is not None else None


def _fetch_index_ohlcv_for_interval_raw(
    index_name: str,
    tf_key: str,
    limit: int = 400,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame | None:
    name = (index_name or "").strip()
    if not name:
        return None
    groww_tf = _YF_INTERVAL_TO_GROWW.get(tf_key, tf_key)
    if groww_token:
        df = _fetch_index_ohlcv_groww(name, groww_tf, groww_token, exchange, limit=limit)
        if df is not None:
            return df
    return _fetch_index_ohlcv_yfinance_index(name, groww_tf, limit=limit)


def clear_index_ohlcv_cache() -> None:
    _fetch_index_daily_ohlcv_cached.cache_clear()
