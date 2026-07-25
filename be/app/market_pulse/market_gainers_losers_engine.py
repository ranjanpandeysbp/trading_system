"""
market_gainers_losers_engine.py
---------------------------------
Multi-market top-10 gainers & losers for selected indices and timeframes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.commodity_screener_engine import (
    COMMODITY_META,
    NIFTY_CORRELATIONS,
    US_CORRELATIONS,
    fetch_commodity_close_series,
    fetch_commodity_intraday_series,
)
from app.market_pulse.heatmap import fetch_coindcx_futures_snapshot
from app.market_pulse.news_scanner import (
    _MARKET_PULSE_LAZY_BATCH_SIZE,
    _fetch_nse_index_constituent_symbols,
    _pct_return_over_bars,
    fetch_nse_index_stock_movers,
)
from app.market_pulse.sector_rotation_markets import (
    CRYPTO_SECTOR_FILTER_GROUPS,
    CRYPTO_SECTOR_SYMBOLS,
    _load_crypto_closes,
    _load_yf_closes,
)
from app.market_pulse.stock_price_rotation import (
    _tf_yf_interval,
    _tf_yf_period,
    compute_stock_price_rotation,
)
from app.market_pulse.stock_price_rotation_markets import _US_INDEX_CATALOG

logger = logging.getLogger(__name__)

LAZY_BATCH_SIZE = _MARKET_PULSE_LAZY_BATCH_SIZE
TOP_N: int | None = None  # no ticker count limit — return full ranked lists

MARKET_INDIA = "india"
MARKET_US = "us"
MARKET_CRYPTO = "crypto"
MARKET_COMMODITY = "commodity"

TIMEFRAME_OPTIONS: tuple[tuple[str, str, int], ...] = (
    ("5 minutes (1 bar)", "5m", 1),
    ("15 minutes (1 bar)", "15m", 1),
    ("30 minutes (1 bar)", "30m", 1),
    ("1 hour (1 bar)", "1h", 1),
    ("4 hours (1 bar)", "4h", 1),
    ("1 day / session", "1d", 1),
    ("1 week", "1w", 1),
    ("1 month", "1M", 1),
)

CRYPTO_UNIVERSE_OPTIONS: dict[str, list[str]] = {
    "All CoinDCX USDT": list(CRYPTO_SECTOR_SYMBOLS.values()),
    **{label: [CRYPTO_SECTOR_SYMBOLS[n] for n in names if n in CRYPTO_SECTOR_SYMBOLS]
       for label, names in CRYPTO_SECTOR_FILTER_GROUPS.items()},
}

COMMODITY_UNIVERSE_OPTIONS: dict[str, str] = {
    "All Commodities": "__ALL__",
    **{meta["name"]: key for key, meta in COMMODITY_META.items()},
}


@dataclass
class GLConfig:
    markets: tuple[str, ...] = (MARKET_INDIA,)
    india_indices: tuple[str, ...] = ("NIFTY 50",)
    us_indices: tuple[str, ...] = ("sp500",)
    crypto_groups: tuple[str, ...] = ("Major L1 / Large Cap",)
    commodity_keys: tuple[str, ...] = ("All Commodities",)
    timeframes: tuple[tuple[str, str, int], ...] = (TIMEFRAME_OPTIONS[5],)


def _rows_to_movers(rows: list[dict], *, name_key: str = "symbol") -> dict[str, list[dict]]:
    if not rows:
        return {"gainers": [], "losers": []}
    sorted_rows = sorted(rows, key=lambda x: x.get("pct", 0), reverse=True)
    gainers_src = sorted_rows if TOP_N is None or TOP_N <= 0 else sorted_rows[:TOP_N]
    losers_src = (
        sorted(sorted_rows, key=lambda x: x.get("pct", 0))
        if TOP_N is None or TOP_N <= 0
        else sorted(sorted_rows, key=lambda x: x.get("pct", 0))[:TOP_N]
    )
    gainers = [
        {name_key: r.get(name_key, r.get("name", "")), "pct": r["pct"], "last": r.get("last", 0)}
        for r in gainers_src
    ]
    losers = [
        {name_key: r.get(name_key, r.get("name", "")), "pct": r["pct"], "last": r.get("last", 0)}
        for r in losers_src
    ]
    return {"gainers": gainers, "losers": losers}


def _rotation_to_movers(payload: dict | None) -> dict[str, list[dict]]:
    if not payload:
        return {"gainers": [], "losers": []}
    gainers = [
        {"symbol": r["symbol"], "pct": r["pct"], "last": r.get("last", 0)}
        for r in (payload.get("inflow") or [])
    ]
    losers = [
        {"symbol": r["symbol"], "pct": r["pct"], "last": r.get("last", 0)}
        for r in (payload.get("outflow") or [])
    ]
    return {"gainers": gainers, "losers": losers}


def compute_india_movers(
    index_name: str,
    tf_key: str,
    lookback_bars: int,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    if tf_key == "1d" and lookback_bars == 1:
        live = fetch_nse_index_stock_movers(index_name, top_n=TOP_N)
        if live:
            return {
                "gainers": live.get("gainers", []),
                "losers": live.get("losers", []),
                "source": "NSE live",
            }

    symbols = _fetch_nse_index_constituent_symbols(index_name)
    if not symbols:
        return {"error": f"No constituents for {index_name}"}

    payload = compute_stock_price_rotation(
        index_name,
        tuple(symbols),
        tf_key,
        lookback_bars,
        use_groww=bool(groww_token),
        exchange=exchange,
    )
    if not payload:
        return {"error": f"No price data for {index_name} @ {tf_key}"}
    movers = _rotation_to_movers(payload)
    movers["source"] = payload.get("data_feed", "yfinance")
    return movers


def compute_us_movers(
    index_id: str,
    tf_key: str,
    lookback_bars: int,
) -> dict[str, Any]:
    entry = next((e for e in _US_INDEX_CATALOG if e["id"] == index_id), None)
    if not entry:
        return {"error": f"Unknown US index {index_id}"}

    symbols = list(entry["fetch"]())
    interval = _tf_yf_interval(tf_key)
    period = _tf_yf_period(tf_key, lookback_bars)
    closes = _load_yf_closes(symbols, period, interval)
    bench_closes = _load_yf_closes([entry["benchmark"]], period, interval).get(entry["benchmark"])

    rows: list[dict] = []
    for sym in symbols:
        series = closes.get(sym)
        if series is None:
            continue
        pct = _pct_return_over_bars(series, lookback_bars)
        if pct is None:
            continue
        clean = series.dropna()
        rows.append({
            "symbol": sym,
            "pct": pct,
            "last": float(clean.iloc[-1]) if len(clean) else 0,
        })

    if not rows:
        return {"error": f"No US data for {entry['label_fn']()} @ {tf_key}"}

    movers = _rows_to_movers(rows)
    movers["source"] = "yfinance"
    movers["benchmark"] = entry["benchmark_label"]
    if bench_closes is not None:
        movers["benchmark_pct"] = _pct_return_over_bars(bench_closes, lookback_bars)
    return movers


def compute_crypto_movers(
    group_label: str,
    tf_key: str,
    lookback_bars: int,
) -> dict[str, Any]:
    symbols = CRYPTO_UNIVERSE_OPTIONS.get(group_label, [])
    if not symbols:
        return {"error": f"Unknown crypto group {group_label}"}

    if tf_key == "1d" and lookback_bars == 1:
        snap = fetch_coindcx_futures_snapshot()
        if not snap:
            return {"error": "CoinDCX snapshot unavailable"}
        sym_set = set(symbols)
        rows = [
            {
                "symbol": x["sym"].replace("B-", ""),
                "pct": float(x["change"]),
                "last": float(x["price"]),
            }
            for x in snap if x["sym"] in sym_set
        ]
        if not rows:
            rows = [
                {
                    "symbol": x["sym"].replace("B-", ""),
                    "pct": float(x["change"]),
                    "last": float(x["price"]),
                }
                for x in snap
            ]
        movers = _rows_to_movers(rows)
        movers["source"] = "CoinDCX 24h"
        return movers

    interval = tf_key if tf_key in ("1m", "5m", "15m", "30m", "1h", "4h", "1d") else "1d"
    limit = max(lookback_bars + 30, 60)
    closes = _load_crypto_closes(list(symbols), interval, limit)
    rows: list[dict] = []
    for sym, series in closes.items():
        pct = _pct_return_over_bars(series, lookback_bars)
        if pct is None:
            continue
        clean = series.dropna()
        rows.append({
            "symbol": sym.replace("B-", ""),
            "pct": pct,
            "last": float(clean.iloc[-1]) if len(clean) else 0,
        })
    if not rows:
        return {"error": f"No crypto OHLCV for {group_label} @ {tf_key}"}
    movers = _rows_to_movers(rows)
    movers["source"] = "CoinDCX OHLCV"
    return movers


def _commodity_related_tickers(commodity_key: str) -> list[tuple[str, str]]:
    """Return (display_name, yahoo_ticker) pairs for ranking."""
    if commodity_key == "__ALL__":
        return [(meta["name"], str(meta["yf"])) for meta in COMMODITY_META.values()]

    meta = COMMODITY_META.get(commodity_key)
    if not meta:
        return []
    items: list[tuple[str, str]] = [(str(meta["name"]), str(meta["yf"]))]
    for row in US_CORRELATIONS.get(commodity_key, []):
        items.append((row["ticker"], row["ticker"]))
    for row in NIFTY_CORRELATIONS.get(commodity_key, []):
        # Nifty index names — ranked via NSE live when possible; skip for yf batch here
        items.append((row["ticker"], ""))
    return items


def compute_commodity_movers(
    commodity_label: str,
    tf_key: str,
    lookback_bars: int,
) -> dict[str, Any]:
    commodity_key = COMMODITY_UNIVERSE_OPTIONS.get(commodity_label, commodity_label)
    tickers = _commodity_related_tickers(commodity_key)
    if not tickers:
        return {"error": f"Unknown commodity universe {commodity_label}"}

    rows: list[dict] = []

    # Futures-only universe (all commodities)
    if commodity_key == "__ALL__":
        if tf_key in ("5m", "15m", "30m", "1h", "4h"):
            interval = "15m" if tf_key in ("5m", "15m", "30m") else "1h"
            period = "5d" if interval == "15m" else "1mo"
            close_map = fetch_commodity_intraday_series(interval, period)
        else:
            close_map = fetch_commodity_close_series()
        for key, meta in COMMODITY_META.items():
            series = close_map.get(key)
            if series is None or series.dropna().empty:
                continue
            pct = _pct_return_over_bars(series, lookback_bars)
            if pct is None:
                continue
            clean = series.dropna()
            rows.append({"symbol": meta["name"], "pct": pct, "last": float(clean.iloc[-1])})
    else:
        # Single commodity future + correlated US equities
        yf_syms = [yf for _, yf in tickers if yf]
        interval = _tf_yf_interval(tf_key)
        period = _tf_yf_period(tf_key, lookback_bars)
        if tf_key in ("5m", "15m", "30m", "1h", "4h"):
            interval = "15m" if tf_key in ("5m", "15m", "30m") else "1h"
            period = "5d" if interval == "15m" else "1mo"
            fut_map = fetch_commodity_intraday_series(interval, period)
            fut_series = fut_map.get(commodity_key)
            if fut_series is not None and not fut_series.dropna().empty:
                pct = _pct_return_over_bars(fut_series, lookback_bars)
                if pct is not None:
                    clean = fut_series.dropna()
                    rows.append({
                        "symbol": COMMODITY_META[commodity_key]["name"],
                        "pct": pct,
                        "last": float(clean.iloc[-1]),
                    })
        else:
            fut_map = fetch_commodity_close_series()
            fut_series = fut_map.get(commodity_key)
            if fut_series is not None and not fut_series.dropna().empty:
                pct = _pct_return_over_bars(fut_series, lookback_bars)
                if pct is not None:
                    clean = fut_series.dropna()
                    rows.append({
                        "symbol": COMMODITY_META[commodity_key]["name"],
                        "pct": pct,
                        "last": float(clean.iloc[-1]),
                    })

        loaded = _load_yf_closes(yf_syms[1:], period, interval) if len(yf_syms) > 1 else {}
        for display, yf in tickers[1:]:
            if not yf:
                continue
            series = loaded.get(yf)
            if series is None or series.dropna().empty:
                continue
            pct = _pct_return_over_bars(series, lookback_bars)
            if pct is None:
                continue
            clean = series.dropna()
            rows.append({"symbol": display, "pct": pct, "last": float(clean.iloc[-1])})

        # Nifty index names from correlation map — session % via NSE when 1d
        for display, yf in tickers:
            if yf:
                continue
            if tf_key == "1d" and lookback_bars == 1:
                live = fetch_nse_index_stock_movers(display, top_n=TOP_N)
                if live:
                    for side in ("gainers", "losers"):
                        for item in live.get(side, []):
                            rows.append({
                                "symbol": item.get("symbol", display),
                                "pct": item.get("pct", 0),
                                "last": item.get("last", 0),
                            })

    if not rows:
        return {"error": f"No commodity data for {commodity_label} @ {tf_key}"}
    movers = _rows_to_movers(rows)
    movers["source"] = "yfinance / NSE"
    return movers


def build_work_units(cfg: GLConfig) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for tf_label, tf_key, lb in cfg.timeframes:
        if MARKET_INDIA in cfg.markets:
            for idx in cfg.india_indices:
                units.append({
                    "market": MARKET_INDIA,
                    "index": idx,
                    "tf_key": tf_key,
                    "tf_label": tf_label,
                    "lookback_bars": lb,
                    "label": f"🇮🇳 {idx} · {tf_label}",
                })
        if MARKET_US in cfg.markets:
            for idx_id in cfg.us_indices:
                entry = next((e for e in _US_INDEX_CATALOG if e["id"] == idx_id), None)
                lbl = entry["label_fn"]() if entry else idx_id
                units.append({
                    "market": MARKET_US,
                    "index": idx_id,
                    "tf_key": tf_key,
                    "tf_label": tf_label,
                    "lookback_bars": lb,
                    "label": f"🇺🇸 {lbl} · {tf_label}",
                })
        if MARKET_CRYPTO in cfg.markets:
            for grp in cfg.crypto_groups:
                units.append({
                    "market": MARKET_CRYPTO,
                    "index": grp,
                    "tf_key": tf_key,
                    "tf_label": tf_label,
                    "lookback_bars": lb,
                    "label": f"₿ {grp} · {tf_label}",
                })
        if MARKET_COMMODITY in cfg.markets:
            for cmd in cfg.commodity_keys:
                units.append({
                    "market": MARKET_COMMODITY,
                    "index": cmd,
                    "tf_key": tf_key,
                    "tf_label": tf_label,
                    "lookback_bars": lb,
                    "label": f"🛢️ {cmd} · {tf_label}",
                })
    return units


def load_work_unit(
    unit: dict[str, Any],
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    market = unit["market"]
    tf_key = unit["tf_key"]
    lb = unit["lookback_bars"]
    idx = unit["index"]

    if market == MARKET_INDIA:
        movers = compute_india_movers(idx, tf_key, lb, groww_token=groww_token, exchange=exchange)
    elif market == MARKET_US:
        movers = compute_us_movers(idx, tf_key, lb)
    elif market == MARKET_CRYPTO:
        movers = compute_crypto_movers(idx, tf_key, lb)
    else:
        movers = compute_commodity_movers(idx, tf_key, lb)

    return {
        **unit,
        "movers": movers,
        "error": movers.get("error"),
    }


def scan_batch(
    units: list[dict[str, Any]],
    start: int,
    end: int,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results = []
    for unit in units[start:end]:
        try:
            results.append(load_work_unit(unit, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({**unit, "error": str(exc)[:200], "movers": {}})
    return results
