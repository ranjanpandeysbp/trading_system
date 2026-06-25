"""
opposite_hedge_mtf_engine.py
----------------------------
Pair-trade hedge plan from Sector Rotation (intraday + HTF) payloads:
long the leading sector / short the lagging sector — profit the spread delta.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols

# Tradeable NSE symbols — ETF preferred, else liquid sector leader
SECTOR_TRADEABLE: dict[str, str] = {
    "NIFTY 50": "NIFTYBEES",
    "NIFTY BANK": "BANKBEES",
    "NIFTY IT": "ITBEES",
    "NIFTY PSU BANK": "PSUBNKBEES",
    "NIFTY PRIVATE BANK": "HDFCBANK",
    "NIFTY PHARMA": "SUNPHARMA",
    "NIFTY FMCG": "HINDUNILVR",
    "NIFTY AUTO": "MARUTI",
    "NIFTY METAL": "TATASTEEL",
    "NIFTY REALTY": "DLF",
    "NIFTY ENERGY": "RELIANCE",
    "NIFTY OIL & GAS": "RELIANCE",
    "NIFTY MEDIA": "SUNTV",
    "NIFTY INFRA": "LT",
    "NIFTY INFRASTRUCTURE": "LT",
    "NIFTY FINANCIAL SERVICES": "HDFCBANK",
    "NIFTY FINANCIAL SERVICES 25/50": "HDFCBANK",
    "NIFTY FINANCIAL SERVICES EX-BANK": "BAJFINANCE",
    "NIFTY HEALTHCARE": "SUNPHARMA",
    "NIFTY HEALTHCARE INDEX": "SUNPHARMA",
    "NIFTY CONSUMER DURABLES": "TITAN",
    "NIFTY CHEMICALS": "PIDILITIND",
    "NIFTY CEMENT": "ULTRACEMCO",
    "NIFTY PSE": "ONGC",
    "NIFTY SERVICES SECTOR": "INFY",
    "NIFTY MOBILITY": "MARUTI",
    "NIFTY INDIA DIGITAL": "INFY",
    "NIFTY INDIA MANUFACTURING": "LT",
    "NIFTY INDIA NEW AGE CONSUMPTION": "TITAN",
    "NIFTY CORE HOUSING": "DLF",
    "NIFTY HOUSING": "DLF",
    "NIFTY COMMODITIES": "TATASTEEL",
    "NIFTY CONSUMPTION": "HINDUNILVR",
    "NIFTY INDIA DEFENCE": "HAL",
    "NIFTY INDIA TOURISM": "INDIGO",
    "NIFTY CAPITAL MARKETS": "BSE",
}

WINDOW_META: dict[str, dict[str, str]] = {
    "minutes": {
        "set": "Intraday",
        "label": "Minutes (5m bars)",
        "long_duration": "15–90 min",
        "short_duration": "15–90 min",
        "style": "Scalp / opening rotation pair",
    },
    "hours": {
        "set": "Intraday",
        "label": "Hours (1h bars)",
        "long_duration": "2–6 hours",
        "short_duration": "2–6 hours",
        "style": "Session pair — square off EOD if MIS",
    },
    "days": {
        "set": "Intraday",
        "label": "Days (daily bars)",
        "long_duration": "1–3 trading days",
        "short_duration": "1–3 trading days",
        "style": "Short swing sector spread",
    },
    "daily": {
        "set": "HTF",
        "label": "Daily",
        "long_duration": "2–5 trading days",
        "short_duration": "2–5 trading days",
        "style": "Swing pair — cash long + F&O short or ETF pair",
    },
    "weekly": {
        "set": "HTF",
        "label": "Weekly",
        "long_duration": "1–2 weeks",
        "short_duration": "1–2 weeks",
        "style": "Positional sector rotation hedge",
    },
    "monthly": {
        "set": "HTF",
        "label": "Monthly",
        "long_duration": "2–6 weeks",
        "short_duration": "2–6 weeks",
        "style": "HTF pair — rebalance on rotation flip",
    },
}

WINDOW_WEIGHT: dict[str, float] = {
    "minutes": 0.12,
    "hours": 0.15,
    "days": 0.18,
    "daily": 0.18,
    "weekly": 0.20,
    "monthly": 0.17,
}


def resolve_sector_trade_ticker(sector_name: str, *, index_level_only: bool = False) -> tuple[str, str]:
    """Map Nifty sector index name → NSE trade symbol + instrument hint."""
    key = (sector_name or "").strip().upper()
    if key in SECTOR_TRADEABLE:
        sym = SECTOR_TRADEABLE[key]
        kind = "ETF" if sym.endswith("BEES") or "ETF" in sym else "Stock"
        return sym, kind
    if index_level_only:
        from app.market_pulse.nse_index_yfinance import index_name_to_groww_symbols
        syms = index_name_to_groww_symbols(sector_name)
        if syms:
            return syms[0], "Index"
        return sector_name.replace("NIFTY ", ""), "Index"
    constituents = get_index_constituent_symbols(sector_name)
    if constituents:
        from app.market_pulse.nse_index_yfinance import filter_tradeable_nse_symbols
        valid = filter_tradeable_nse_symbols(constituents, limit=1)
        if valid:
            return valid[0], "Stock"
    short = sector_name.replace("NIFTY ", "").replace(" ", "")[:12] or "NIFTYBEES"
    return short, "Proxy"


def _clamp_pct(value: float, lo: float, hi: float) -> float:
    return round(min(max(value, lo), hi), 2)


def _sl_tp_long(last: float | None, sr: dict | None) -> tuple[float, float]:
    sr = sr or {}
    if not last or last <= 0:
        return 1.5, 3.0
    s1, r1 = sr.get("s1"), sr.get("r1")
    sl = abs(last - float(s1)) / last * 100 if s1 else 1.5
    tp = abs(float(r1) - last) / last * 100 if r1 else sl * 2.0
    return _clamp_pct(sl, 0.4, 6.0), _clamp_pct(tp, 0.8, 10.0)


def _sl_tp_short(last: float | None, sr: dict | None) -> tuple[float, float]:
    sr = sr or {}
    if not last or last <= 0:
        return 1.5, 3.0
    s1, r1 = sr.get("s1"), sr.get("r1")
    sl = abs(float(r1) - last) / last * 100 if r1 else 1.5
    tp = abs(last - float(s1)) / last * 100 if s1 else sl * 2.0
    return _clamp_pct(sl, 0.4, 6.0), _clamp_pct(tp, 0.8, 10.0)


def _pair_allocation(long_rel: float, short_rel: float) -> tuple[float, float]:
    """Capital split for long vs short leg (≈ market-neutral, slight tilt to stronger relative)."""
    total = abs(float(long_rel)) + abs(float(short_rel))
    if total <= 0:
        return 50.0, 50.0
    long_pct = 50.0 + ((float(long_rel) / total) - 0.5) * 18.0
    long_pct = min(58.0, max(42.0, long_pct))
    return round(long_pct, 1), round(100.0 - long_pct, 1)


def _window_confidence(long_s: dict, short_s: dict) -> float:
    spread = float(long_s.get("relative", 0)) - float(short_s.get("relative", 0))
    magnitude = (abs(float(long_s.get("pct", 0))) + abs(float(short_s.get("pct", 0)))) / 2
    score = 50.0 + spread * 1.8 + magnitude * 0.75
    return round(min(92.0, max(45.0, score)), 1)


def _leg_from_sector(
    sector: dict,
    side: str,
    sr_map: dict[str, dict],
    window_key: str,
    *,
    index_level_only: bool = False,
) -> dict[str, Any]:
    name = sector.get("name", "")
    ticker, kind = resolve_sector_trade_ticker(name, index_level_only=index_level_only)
    sr = sr_map.get(name, {})
    last = sector.get("last")
    sl, tp = (_sl_tp_long if side == "long" else _sl_tp_short)(last, sr)
    meta = WINDOW_META[window_key]
    return {
        "sector": name.replace("NIFTY ", ""),
        "ticker": ticker,
        "instrument": kind,
        "last": last,
        "return_pct": sector.get("pct"),
        "relative_pct": sector.get("relative"),
        "sl_pct": sl,
        "tp_pct": tp,
        "duration": meta["long_duration" if side == "long" else "short_duration"],
    }


def _build_window_plan(
    window_key: str,
    window: dict | None,
    sr_map: dict[str, dict],
    *,
    index_level_only: bool = False,
    long_stock: dict | None = None,
    short_stock: dict | None = None,
) -> dict[str, Any] | None:
    if not window:
        return None
    inflow = window.get("inflow") or []
    outflow = window.get("outflow") or []
    if not inflow or not outflow:
        return None

    long_s = inflow[0]
    short_s = outflow[0]
    conf = _window_confidence(long_s, short_s)
    long_pct, short_pct = _pair_allocation(long_s.get("relative", 0), short_s.get("relative", 0))

    long_leg = _leg_from_sector(long_s, "long", sr_map, window_key, index_level_only=index_level_only)
    short_leg = _leg_from_sector(short_s, "short", sr_map, window_key, index_level_only=index_level_only)
    if long_stock:
        long_leg["ticker"] = long_stock.get("symbol", long_leg["ticker"])
        long_leg["instrument"] = "Stock"
        long_leg["last"] = long_stock.get("last", long_leg.get("last"))
        long_leg["return_pct"] = long_stock.get("pct", long_leg.get("return_pct"))
    if short_stock:
        short_leg["ticker"] = short_stock.get("symbol", short_leg["ticker"])
        short_leg["instrument"] = "Stock"
        short_leg["last"] = short_stock.get("last", short_leg.get("last"))
        short_leg["return_pct"] = short_stock.get("pct", short_leg.get("return_pct"))
    long_leg["confidence_pct"] = conf
    short_leg["confidence_pct"] = conf
    long_leg["alloc_pct"] = long_pct
    short_leg["alloc_pct"] = short_pct

    spread_edge = round(float(long_s.get("relative", 0)) - float(short_s.get("relative", 0)), 2)
    meta = WINDOW_META[window_key]

    return {
        "window_key": window_key,
        "set": meta["set"],
        "window_label": meta["label"],
        "style": meta["style"],
        "benchmark_pct": window.get("benchmark_pct"),
        "spread_edge_pct": spread_edge,
        "confidence_pct": conf,
        "long": long_leg,
        "short": short_leg,
        "long_alloc_pct": long_pct,
        "short_alloc_pct": short_pct,
        "long_duration": long_leg["duration"],
        "short_duration": short_leg["duration"],
    }


def _consensus_from_plans(plans: list[dict]) -> dict[str, Any]:
    if not plans:
        return {}

    long_votes: Counter[str] = Counter()
    short_votes: Counter[str] = Counter()
    long_conf: dict[str, list[float]] = {}
    short_conf: dict[str, list[float]] = {}
    long_sectors: dict[str, dict] = {}
    short_sectors: dict[str, dict] = {}

    for p in plans:
        w = WINDOW_WEIGHT.get(p["window_key"], 0.15)
        lt = p["long"]["ticker"]
        st = p["short"]["ticker"]
        long_votes[lt] += w
        short_votes[st] += w
        long_conf.setdefault(lt, []).append(p["confidence_pct"] * w)
        short_conf.setdefault(st, []).append(p["confidence_pct"] * w)
        long_sectors.setdefault(lt, p["long"])
        short_sectors.setdefault(st, p["short"])

    best_long = long_votes.most_common(1)[0][0]
    best_short = short_votes.most_common(1)[0][0]
    long_vote = long_votes[best_long]
    short_vote = short_votes[best_short]
    total_w = sum(WINDOW_WEIGHT.values()) or 1.0

    conf_long = sum(long_conf[best_long]) / long_vote if long_vote else 50.0
    conf_short = sum(short_conf[best_short]) / short_vote if short_vote else 50.0
    consensus_conf = round((conf_long + conf_short) / 2, 1)

    long_leg = dict(long_sectors[best_long])
    short_leg = dict(short_sectors[best_short])
    long_pct, short_pct = _pair_allocation(
        long_leg.get("relative_pct", 0) or 0,
        short_leg.get("relative_pct", 0) or 0,
    )
    long_leg["alloc_pct"] = long_pct
    short_leg["alloc_pct"] = short_pct
    long_leg["confidence_pct"] = round(conf_long, 1)
    short_leg["confidence_pct"] = round(conf_short, 1)

    agreeing = sum(
        1 for p in plans
        if p["long"]["ticker"] == best_long and p["short"]["ticker"] == best_short
    )

    return {
        "long_ticker": best_long,
        "short_ticker": best_short,
        "long_sector": long_leg.get("sector"),
        "short_sector": short_leg.get("sector"),
        "long_alloc_pct": long_pct,
        "short_alloc_pct": short_pct,
        "long_confidence_pct": long_leg["confidence_pct"],
        "short_confidence_pct": short_leg["confidence_pct"],
        "consensus_confidence_pct": consensus_conf,
        "long_sl_pct": long_leg.get("sl_pct"),
        "long_tp_pct": long_leg.get("tp_pct"),
        "short_sl_pct": short_leg.get("sl_pct"),
        "short_tp_pct": short_leg.get("tp_pct"),
        "long_duration": "Blend: 1 session – 2 weeks (see per-window table)",
        "short_duration": "Blend: 1 session – 2 weeks (see per-window table)",
        "windows_agreeing": agreeing,
        "windows_total": len(plans),
        "long": long_leg,
        "short": short_leg,
        "vote_long_pct": round(long_vote / total_w * 100, 1),
        "vote_short_pct": round(short_vote / total_w * 100, 1),
    }


def compute_opposite_hedge_mtf(
    intraday_payload: dict | None,
    htf_payload: dict | None,
    sr_map: dict[str, dict] | None = None,
    capital: float = 100_000.0,
    *,
    index_level_only: bool = False,
    long_stock: dict | None = None,
    short_stock: dict | None = None,
    mode: str = "index",
) -> dict[str, Any] | None:
    """
    Build long/short hedge pairs from both sector rotation payloads.
    Returns per-window plans + consensus master pair for delta capture.
    """
    sr_map = sr_map or {}
    plans: list[dict] = []

    intraday_windows = (
        ("minutes", (intraday_payload or {}).get("minutes")),
        ("hours", (intraday_payload or {}).get("hours")),
        ("days", (intraday_payload or {}).get("days")),
    )
    htf_windows = (
        ("daily", (htf_payload or {}).get("daily")),
        ("weekly", (htf_payload or {}).get("weekly")),
        ("monthly", (htf_payload or {}).get("monthly")),
    )

    for key, window in intraday_windows + htf_windows:
        plan = _build_window_plan(
            key, window, sr_map,
            index_level_only=index_level_only,
            long_stock=long_stock,
            short_stock=short_stock,
        )
        if plan:
            plan["long_notional"] = round(capital * plan["long_alloc_pct"] / 100, 0)
            plan["short_notional"] = round(capital * plan["short_alloc_pct"] / 100, 0)
            plans.append(plan)

    if not plans:
        return None

    consensus = _consensus_from_plans(plans)
    if consensus:
        consensus["long_notional"] = round(capital * consensus["long_alloc_pct"] / 100, 0)
        consensus["short_notional"] = round(capital * consensus["short_alloc_pct"] / 100, 0)

    return {
        "capital": capital,
        "plan_count": len(plans),
        "intraday_loaded": intraday_payload is not None,
        "htf_loaded": htf_payload is not None,
        "plans": plans,
        "consensus": consensus,
        "intraday_plans": [p for p in plans if p["set"] == "Intraday"],
        "htf_plans": [p for p in plans if p["set"] == "HTF"],
        "mode": mode,
        "long_stock": long_stock,
        "short_stock": short_stock,
    }
