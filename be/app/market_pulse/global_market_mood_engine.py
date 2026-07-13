"""
global_market_mood_engine.py
------------------------------
Regional market mood, sector rotation snapshot, stock movers, and geopolitical headlines
for the Command Center Global Market Mood panel.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

TOP_N = 8
TOP_SECTORS = 5

GEOPOL_KEYWORDS = re.compile(
    r"\b(war|wars|conflict|missile|attack|invasion|sanction|nato|ukraine|russia|"
    r"israel|gaza|hamas|hezbollah|iran|taiwan|tariff|geopolit|military|ceasefire|"
    r"troops|strike|nuclear|pentagon|defense|border|shelling|airstrike|drone|"
    r"cease.?fire|middle east|red sea|houthi|syria|yemen|korea|tension)\b",
    re.I,
)

REGION_CONFIG: dict[str, dict[str, Any]] = {
    "india": {
        "label": "India",
        "emoji": "🇮🇳",
        "keys": [
            "Nifty 50", "Sensex", "Bank Nifty", "Nifty IT", "Nifty Midcap 150",
            "Nifty 100", "Nifty Next 50", "Gift Nifty", "USD/INR",
        ],
        "invert": {"India VIX"},
        "vix_key": "India VIX",
    },
    "asia": {
        "label": "Asia",
        "emoji": "🌏",
        "keys": [
            "Nikkei 225 (Japan)", "Hang Seng (HK)", "Shanghai (China)", "KOSPI (Korea)",
            "Straits Times (SG)", "ASX 200 (Australia)", "Taiwan Weighted",
        ],
        "invert": set(),
    },
    "europe": {
        "label": "Europe",
        "emoji": "🇪🇺",
        "keys": ["FTSE 100 (UK)", "DAX 40 (Germany)", "CAC 40 (France)"],
        "invert": set(),
    },
    "us_stocks": {
        "label": "US Stocks",
        "emoji": "🇺🇸",
        "keys": ["Dow Jones", "S&P 500", "Nasdaq Composite", "Russell 2000"],
        "invert": set(),
    },
    "us_futures": {
        "label": "US Futures",
        "emoji": "📈",
        "keys": ["Dow Futures", "S&P 500 Futures", "Nasdaq Futures"],
        "invert": set(),
    },
    "crypto": {
        "label": "Crypto",
        "emoji": "₿",
        "keys": ["Bitcoin", "Ethereum", "Solana"],
        "invert": set(),
    },
    "commodities": {
        "label": "Commodities",
        "emoji": "🛢️",
        "keys": ["Crude Oil (WTI)", "DXY (Dollar Index)", "US 10Y Bond Yield"],
        "invert": {"US 10Y Bond Yield"},
    },
    "precious_metals": {
        "label": "Gold & Silver",
        "emoji": "🥇",
        "keys": ["Gold", "Silver"],
        "invert": set(),
    },
}


def _mood_from_avg(avg_pct: float) -> str:
    if avg_pct >= 0.55:
        return "STRONG BULLISH"
    if avg_pct >= 0.12:
        return "BULLISH"
    if avg_pct <= -0.55:
        return "STRONG BEARISH"
    if avg_pct <= -0.12:
        return "BEARISH"
    return "NEUTRAL"


def _mood_emoji(mood: str) -> str:
    return {
        "STRONG BULLISH": "🟢🟢",
        "BULLISH": "🟢",
        "NEUTRAL": "🟡",
        "BEARISH": "🔴",
        "STRONG BEARISH": "🔴🔴",
    }.get(mood, "🟡")


def _signed_pct(name: str, pct: float | None, invert_keys: set[str]) -> float | None:
    if pct is None:
        return None
    return -float(pct) if name in invert_keys else float(pct)


def compute_region_mood(
    market_data: dict,
    region_id: str,
) -> dict[str, Any]:
    cfg = REGION_CONFIG[region_id]
    invert = set(cfg.get("invert") or [])
    instruments: list[dict] = []
    signed: list[float] = []

    for key in cfg["keys"]:
        d = market_data.get(key) or {}
        pct = d.get("pct")
        adj = _signed_pct(key, pct, invert)
        if adj is not None:
            signed.append(adj)
        instruments.append({
            "name": key,
            "price": d.get("price"),
            "pct": pct,
            "signed_pct": adj,
            "source": d.get("source", ""),
        })

    vix_key = cfg.get("vix_key")
    if vix_key and market_data.get(vix_key):
        vd = market_data[vix_key]
        vp = vd.get("pct")
        instruments.append({
            "name": vix_key,
            "price": vd.get("price"),
            "pct": vp,
            "signed_pct": _signed_pct(vix_key, vp, invert),
            "source": vd.get("source", ""),
            "note": "fear gauge (inverted in mood)",
        })
        if vp is not None:
            signed.append(_signed_pct(vix_key, vp, invert))

    avg = sum(signed) / len(signed) if signed else 0.0
    green = sum(1 for x in signed if x > 0.05)
    red = sum(1 for x in signed if x < -0.05)
    mood = _mood_from_avg(avg)

    headline = ""
    if region_id == "india" and vix_key:
        vix_pct = (market_data.get(vix_key) or {}).get("pct")
        if vix_pct is not None and vix_pct >= 3:
            headline = "Elevated VIX — risk-off undertone"
        elif mood.startswith("BULL"):
            headline = "Risk-on — indices firm"
        elif mood.startswith("BEAR"):
            headline = "Cautious session — breadth watch"

    return {
        "region_id": region_id,
        "label": cfg["label"],
        "emoji": cfg["emoji"],
        "mood": mood,
        "mood_emoji": _mood_emoji(mood),
        "avg_pct": round(avg, 3),
        "green_count": green,
        "red_count": red,
        "instrument_count": len(signed),
        "instruments": instruments,
        "headline": headline,
    }


def extract_geopolitical_news(
    global_articles: list[dict],
    india_articles: list[dict] | None = None,
    *,
    limit: int = 12,
) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    pool = list(global_articles or []) + list(india_articles or [])
    for art in pool:
        title = (art.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue
        blob = f"{title} {(art.get('summary') or '')}"
        if not GEOPOL_KEYWORDS.search(blob):
            continue
        seen.add(title.lower())
        out.append(art)
        if len(out) >= limit:
            break
    out.sort(key=lambda a: a.get("age_hours", 999))
    return out


def compute_sector_leaders_laggers(breadth_data: dict | None) -> dict[str, Any]:
    """Today's sector leaders/laggers from NSE sectoral index % change."""
    empty = {
        "leading": [],
        "lagging": [],
        "prediction": "Sector data unavailable — refresh during market hours.",
        "benchmark_pct": None,
        "sector_count": 0,
    }
    if not breadth_data:
        return empty

    indices = breadth_data.get("indices") or {}
    groups = breadth_data.get("groups") or {}
    sector_names = groups.get("SECTORAL INDICES") or []
    if not sector_names:
        sector_names = [
            n for n, d in indices.items()
            if (d.get("group") or "") == "SECTORAL INDICES"
        ]

    rows: list[dict] = []
    for name in sector_names:
        d = indices.get(name) or {}
        pct = d.get("pct")
        if pct is None:
            continue
        rows.append({
            "name": name.replace("NIFTY ", ""),
            "full_name": name,
            "pct": float(pct),
            "last": d.get("last"),
            "advances": d.get("advances"),
            "declines": d.get("declines"),
        })

    if not rows:
        return empty

    rows.sort(key=lambda x: x["pct"], reverse=True)
    bench = indices.get("NIFTY 50") or {}
    bench_pct = bench.get("pct")

    leading = rows[:TOP_SECTORS]
    lagging = list(reversed(rows[-TOP_SECTORS:]))

    top = leading[0]["name"] if leading else "—"
    bottom = lagging[0]["name"] if lagging else "—"
    if bench_pct is not None and bench_pct > 0.3:
        prediction = (
            f"Risk-on rotation — **{top}** leading while **{bottom}** lags. "
            f"Money favors cyclicals/growth as Nifty is +{bench_pct:.2f}%."
        )
    elif bench_pct is not None and bench_pct < -0.3:
        prediction = (
            f"Defensive day — **{top}** holds up best; **{bottom}** under pressure. "
            f"Nifty {bench_pct:+.2f}% — consider quality/defensive tilts."
        )
    else:
        prediction = (
            f"Selective rotation — **{top}** leads, **{bottom}** trails. "
            "Leadership is narrow; stock-picking over index beta."
        )

    return {
        "leading": leading,
        "lagging": lagging,
        "prediction": prediction,
        "benchmark_pct": bench_pct,
        "sector_count": len(rows),
    }


def fetch_stock_movers_bundle() -> dict[str, Any]:
    """India Nifty 50, US S&P 500, and crypto top movers (session / 24h)."""
    from app.market_pulse.market_gainers_losers_engine import (
        compute_crypto_movers,
        compute_india_movers,
        compute_us_movers,
    )

    bundle: dict[str, Any] = {"as_of": datetime.now().isoformat(timespec="seconds")}

    try:
        from app.market_pulse.groww_auth import get_active_groww_token

        groww_token = get_active_groww_token()
        india = compute_india_movers(
            "NIFTY 50", "1d", 1, groww_token=groww_token, exchange="NSE",
        )
        gainers = india.get("gainers") or []
        losers = india.get("losers") or []
        if gainers or losers:
            bundle["india"] = {
                "label": "Nifty 50",
                "gainers": gainers,
                "losers": losers,
                "source": india.get("source", "yfinance"),
            }
        else:
            bundle["india"] = {
                "label": "Nifty 50",
                "gainers": [],
                "losers": [],
                "source": "—",
                "error": india.get("error") or (
                    "NSE live movers blocked or unavailable — yfinance fallback returned no data. "
                    "Try again during NSE cash hours or check **Market Pulse → Gainers & Losers**."
                ),
            }
    except Exception as e:
        logger.error("India movers: %s", e)
        bundle["india"] = {"gainers": [], "losers": [], "error": str(e), "source": "—"}

    try:
        us = compute_us_movers("sp500", "1d", 1)
        bundle["us"] = {"label": "S&P 500", **us, "source": us.get("source", "yfinance")}
    except Exception as e:
        logger.error("US movers: %s", e)
        bundle["us"] = {"gainers": [], "losers": [], "error": str(e)}

    try:
        crypto = compute_crypto_movers("Major L1 / Large Cap", "1d", 1)
        bundle["crypto"] = {
            "label": "Crypto (CoinDCX)",
            **crypto,
            "source": crypto.get("source", "CoinDCX"),
        }
    except Exception as e:
        logger.error("Crypto movers: %s", e)
        bundle["crypto"] = {"gainers": [], "losers": [], "error": str(e)}

    return bundle


def fetch_market_mood_inputs(*, include_news: bool = True) -> dict[str, Any]:
    """Pull the raw datasets build_global_market_mood_payload() needs — live global
    market quotes, India/global news headlines, and NSE sectoral breadth — straight
    from news_scanner.py's data-fetch functions (no streamlit dependency).

    Mirrors what the original Streamlit tab got from
    news_scanner._load_news_scanner_payload(include_index_sr=False), but calls the
    underlying fetchers directly so this module has no UI-layer dependency.
    """
    from app.market_pulse.news_scanner import (
        fetch_all_market_data,
        fetch_global_news,
        fetch_news,
        fetch_nse_market_breadth,
    )

    market_data = fetch_all_market_data()
    if include_news:
        news_articles = fetch_news()
        global_news_articles = fetch_global_news()
    else:
        news_articles = []
        global_news_articles = []
    breadth_data = fetch_nse_market_breadth()

    return {
        "market_data": market_data,
        "news_articles": news_articles,
        "global_news_articles": global_news_articles,
        "breadth_data": breadth_data,
    }


def build_global_market_mood_payload(
    market_data: dict,
    *,
    global_news: list[dict] | None = None,
    india_news: list[dict] | None = None,
    breadth_data: dict | None = None,
    market_sentiment: dict | None = None,
    include_movers: bool = True,
) -> dict[str, Any]:
    """Aggregate regional moods, sectors, movers, and geopolitical headlines."""
    regions = {
        rid: compute_region_mood(market_data, rid)
        for rid in REGION_CONFIG
    }

    geopolitical = extract_geopolitical_news(global_news or [], india_news)
    sectors = compute_sector_leaders_laggers(breadth_data)
    movers = fetch_stock_movers_bundle() if include_movers else {}

    # Global composite: average regional signed pct (exclude precious as subset of commodities mood)
    composite_signed = [
        r["avg_pct"] for r in regions.values()
        if r["instrument_count"] > 0 and r["region_id"] not in ("precious_metals",)
    ]
    composite_avg = sum(composite_signed) / len(composite_signed) if composite_signed else 0.0
    composite_mood = _mood_from_avg(composite_avg)

    return {
        "regions": regions,
        "composite": {
            "mood": composite_mood,
            "mood_emoji": _mood_emoji(composite_mood),
            "avg_pct": round(composite_avg, 3),
        },
        "geopolitical_news": geopolitical,
        "sectors": sectors,
        "stock_movers": movers,
        "india_sentiment": market_sentiment,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }


def scan_global_market_mood(*, include_news: bool = True, include_movers: bool = True) -> dict[str, Any]:
    """One-call entry point: fetch live inputs and build the full mood payload.

    This is the "scan_universe"-equivalent for the global mood engine — there's no
    per-ticker loop since the underlying data (index/sector/news feeds) is inherently
    market-wide, so a single fetch-and-aggregate call is the natural shape here.
    """
    try:
        inputs = fetch_market_mood_inputs(include_news=include_news)
    except Exception as exc:
        logger.error("Global market mood input fetch failed: %s", exc)
        return {"error": str(exc)[:300]}

    return build_global_market_mood_payload(
        inputs["market_data"],
        global_news=inputs.get("global_news_articles"),
        india_news=inputs.get("news_articles"),
        breadth_data=inputs.get("breadth_data"),
        market_sentiment=None,
        include_movers=include_movers,
    )
