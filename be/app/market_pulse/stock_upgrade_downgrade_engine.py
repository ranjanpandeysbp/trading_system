"""
stock_upgrade_downgrade_engine.py
----------------------------------
Multi-site scan for block deals, mergers/acquisitions, upgrades, downgrades, and
analyst recommendations for a ticker.

India checklist: Trendlyne, Moneycontrol, ET Markets, Tickertape, CNBC-TV18.
US / Global / Crypto checklist: TipRanks, Investing.com, Bloomberg, MarketWatch, Reuters.

Each site is checked via its own RSS feed where a stable public one exists
(Moneycontrol, ET Markets), and via Google News `site:` scoped search otherwise —
this covers every named site even where no public RSS is published (Trendlyne,
Tickertape, TipRanks, Bloomberg).
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from collections import Counter
from typing import Any

from app.market_pulse.market_pulse_feeds import (
    CRYPTO_ANALYST_FEEDS,
    _collect_rss_articles,
    enrich_analyst_article,
    summarize_analyst_consensus,
)
from app.market_pulse.ticker_investigation_engine import _TICKER_ALIASES

logger = logging.getLogger(__name__)

MAX_ITEM_AGE_DAYS = 21

# (display name, domain used for `site:` scoping)
INDIA_SITES: list[tuple[str, str]] = [
    ("Trendlyne", "trendlyne.com"),
    ("Moneycontrol", "moneycontrol.com"),
    ("ET Markets", "economictimes.indiatimes.com"),
    ("Tickertape", "tickertape.in"),
    ("CNBC-TV18", "cnbctv18.com"),
    # Enriched from https://tradebrains.in/newspapers-stock-market/
    ("Business Standard", "business-standard.com"),
    ("LiveMint", "livemint.com"),
    ("The Hindu BusinessLine", "thehindubusinessline.com"),
    ("NDTV Profit", "ndtvprofit.com"),
]

GLOBAL_SITES: list[tuple[str, str]] = [
    ("TipRanks", "tipranks.com"),
    ("Investing.com", "investing.com"),
    ("Bloomberg", "bloomberg.com"),
    ("MarketWatch", "marketwatch.com"),
    ("Reuters", "reuters.com"),
    # Enriched from https://tradebrains.in/newspapers-stock-market/
    ("Yahoo Finance", "finance.yahoo.com"),
]

# Known-good direct RSS feeds, layered on top of the site-scoped Google News queries
# for extra depth/freshness on the two India sites that publish stable public feeds.
_DIRECT_INDIA_FEEDS: list[tuple[str, str, int]] = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/brokeragerecos.xml", 40),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/buzzingstocks.xml", 25),
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", 25),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss", 20),
    ("LiveMint", "https://www.livemint.com/rss/markets", 20),
    ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest", 20),
]

_STOCK_CATEGORY_QUERY = (
    'upgrade OR downgrade OR "block deal" OR "bulk deal" OR merger OR acquisition '
    'OR "analyst rating" OR "price target"'
)
_CRYPTO_CATEGORY_QUERY = (
    'upgrade OR downgrade OR listing OR partnership OR acquisition OR merger '
    'OR "price target" OR rating'
)

_CATEGORY_LABELS: dict[str, str] = {
    "BLOCK_DEAL": "🧱 Block Deal",
    "MERGER_ACQUISITION": "🤝 Merger / Acquisition",
    "UPGRADE": "⬆️ Upgrade",
    "DOWNGRADE": "⬇️ Downgrade",
    "TARGET_RAISE": "🎯 Target Raise",
    "TARGET_CUT": "🎯 Target Cut",
    "RERATING": "🔁 Re-rating",
    "INITIATE": "🆕 Coverage Initiated",
    "REITERATE": "🔂 Reiterated",
    "RECOMMENDATION": "📋 Analyst Recommendation",
}

_CATEGORY_RANK = {
    "BLOCK_DEAL": 8, "MERGER_ACQUISITION": 8,
    "UPGRADE": 7, "DOWNGRADE": 7,
    "TARGET_RAISE": 6, "TARGET_CUT": 6, "RERATING": 6,
    "INITIATE": 4, "REITERATE": 3, "RECOMMENDATION": 2,
}


def _sites_for_market(market: str) -> list[tuple[str, str]]:
    return INDIA_SITES if market == "india" else GLOBAL_SITES


def _primary_term(ticker: str, market: str) -> str:
    """Best single human-readable search term for the site-scoped query."""
    aliases = _TICKER_ALIASES.get(ticker.upper(), [])
    for alias in aliases:
        if " " in alias:
            return alias
    if market == "crypto":
        return ticker.upper().replace("B-", "").replace("USDT", "").replace("_", "").replace("-", "")
    return ticker.upper().replace(".NS", "").replace(".US", "")


def search_terms(ticker: str, market: str) -> list[str]:
    t = ticker.upper().replace("B-", "").replace("USDT", "").replace("-", "").replace("_", "")
    terms = {ticker.upper(), t}
    if market == "crypto":
        base = ticker.upper().replace("B-", "").replace("USDT", "").replace("_", "").replace("-", "")
        terms.update({base, f"{base}USDT", f"{base}-USDT"})
    else:
        sym = ticker.upper().replace(".NS", "").replace(".US", "")
        terms.add(sym)
    for alias in _TICKER_ALIASES.get(ticker.upper(), []):
        terms.add(alias.upper())
    return [x for x in terms if len(x) >= 2]


def _matches_terms(text: str, terms: list[str]) -> bool:
    blob = text.upper()
    for term in terms:
        if len(term) >= 4 and term in blob:
            return True
        if len(term) <= 5 and re.search(rf"\b{re.escape(term)}\b", blob):
            return True
    return False


def _google_site_feed(
    site_label: str, domain: str, term: str, *, category_query: str,
    hl: str, gl: str, ceid: str, limit: int = 15,
) -> tuple[str, str, int]:
    q = f'site:{domain} {term} ({category_query})'
    enc = urllib.parse.quote_plus(q)
    url = f"https://news.google.com/rss/search?q={enc}&hl={hl}&gl={gl}&ceid={ceid}"
    return (site_label, url, limit)


def build_site_feeds(ticker: str, market: str) -> tuple[list[tuple[str, str, int]], list[str]]:
    """Return (feed list, site display names checked) for a ticker/market."""
    term = _primary_term(ticker, market)
    sites = _sites_for_market(market)
    site_names = [name for name, _ in sites]

    if market == "india":
        hl, gl, ceid = "en-IN", "IN", "IN:en"
        category_query = _STOCK_CATEGORY_QUERY
    elif market == "crypto":
        hl, gl, ceid = "en-US", "US", "US:en"
        category_query = _CRYPTO_CATEGORY_QUERY
    else:
        hl, gl, ceid = "en-US", "US", "US:en"
        category_query = _STOCK_CATEGORY_QUERY

    feeds = [
        _google_site_feed(name, domain, term, category_query=category_query, hl=hl, gl=gl, ceid=ceid)
        for name, domain in sites
    ]

    if market == "india":
        feeds.extend(_DIRECT_INDIA_FEEDS)
    elif market == "crypto":
        feeds.extend(CRYPTO_ANALYST_FEEDS)

    return feeds, site_names


def _dedup(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = re.sub(r"\W+", "", it.get("title", "").lower())[:110]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def scan_ticker(ticker: str, market: str, *, max_items: int = 30) -> dict[str, Any]:
    """Scan the site checklist for a single ticker; classify and rank results."""
    feeds, site_names = build_site_feeds(ticker, market)
    terms = search_terms(ticker, market)

    raw = _collect_rss_articles(feeds, max_hours=MAX_ITEM_AGE_DAYS * 24, max_total=200)
    matched = [a for a in raw if _matches_terms(f"{a.get('title', '')} {a.get('summary', '')}", terms)]

    items = []
    for art in matched:
        enriched = enrich_analyst_article(art)
        enriched["ticker"] = ticker
        enriched["category_label"] = _CATEGORY_LABELS.get(enriched["call_type"], enriched["call_type"])
        items.append(enriched)

    items = _dedup(items)
    items.sort(
        key=lambda i: (_CATEGORY_RANK.get(i.get("call_type"), 0), i.get("published_dt", "")),
        reverse=True,
    )

    counts = Counter(i["call_type"] for i in items)
    category_counts = {k: counts.get(k, 0) for k in _CATEGORY_LABELS}

    return {
        "ticker": ticker,
        "market": market,
        "sites_checked": site_names,
        "items": items[:max_items],
        "item_count": len(items),
        "category_counts": category_counts,
        "block_deal_or_ma_count": category_counts["BLOCK_DEAL"] + category_counts["MERGER_ACQUISITION"],
        "upgrade_downgrade_count": category_counts["UPGRADE"] + category_counts["DOWNGRADE"],
        "consensus": summarize_analyst_consensus(items),
    }


def scan_tickers(tickers: list[str], market: str, *, max_items: int = 30) -> list[dict[str, Any]]:
    results = []
    for ticker in tickers:
        try:
            results.append(scan_ticker(ticker, market, max_items=max_items))
        except Exception as exc:
            logger.debug("upgrade/downgrade scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})
    return results


# ---------------------------------------------------------------------------
# AI View
# ---------------------------------------------------------------------------

UPGRADE_DOWNGRADE_AI_SYSTEM = """You are an equity research analyst reading a feed of block deals, mergers/acquisitions, analyst upgrades/downgrades, price-target changes, and brokerage recommendations for one ticker, sourced from a fixed checklist of financial news sites.

Given the site checklist, category counts, consensus, and the individual headlines/sources/dates:

1. **Corporate actions** — flag any block deal or merger/acquisition item and its likely price impact (dilution, control change, re-rating).
2. **Analyst tone** — synthesize upgrades vs downgrades vs target raises/cuts into a single directional read (bullish / bearish / mixed), citing specific brokerages and targets where present.
3. **Freshness & reliability** — note if signals are stale (>1 week old), thin (few sources), or conflicting across sites.
4. **Trade stance** — TAKE LONG / TAKE SHORT / WATCH / NO SIGNAL, with a confidence % and the single strongest supporting headline.

Cite specific sources, brokerages, and dates from the feed — never invent a price target, deal size, or rating not present in the data. If the feed is empty or thin, say so plainly and recommend waiting for fresh news rather than guessing.
"""


def build_upgrade_downgrade_ai_prompt(result: dict) -> str:
    """Build AI prompt for one ticker's upgrade/downgrade/corporate-action scan."""
    counts = result.get("category_counts") or {}
    consensus = result.get("consensus") or {}
    lines = [
        "=== STOCK UPGRADE/DOWNGRADE & CORPORATE ACTION SCAN ===",
        f"Ticker: {result.get('ticker')}",
        f"Market: {result.get('market')}",
        f"Sites checked: {', '.join(result.get('sites_checked') or [])}",
        f"Items found (last {MAX_ITEM_AGE_DAYS} days): {result.get('item_count', 0)}",
        "",
        "── CATEGORY COUNTS ──",
        f"Block deals: {counts.get('BLOCK_DEAL', 0)} · Mergers/Acquisitions: {counts.get('MERGER_ACQUISITION', 0)} · "
        f"Upgrades: {counts.get('UPGRADE', 0)} · Downgrades: {counts.get('DOWNGRADE', 0)} · "
        f"Target raises: {counts.get('TARGET_RAISE', 0)} · Target cuts: {counts.get('TARGET_CUT', 0)} · "
        f"Re-ratings: {counts.get('RERATING', 0)} · Initiated: {counts.get('INITIATE', 0)} · "
        f"Reiterated: {counts.get('REITERATE', 0)} · Recommendations: {counts.get('RECOMMENDATION', 0)}",
        "",
        "── CONSENSUS ──",
        f"Consensus: {consensus.get('consensus', '—')} · Buy {consensus.get('buy', 0)} / "
        f"Sell {consensus.get('sell', 0)} / Hold {consensus.get('hold', 0)} · "
        f"Latest target: {consensus.get('latest_target', '—')}",
        "",
        "── ITEMS ──",
    ]
    for it in result.get("items") or []:
        lines.append(
            f"• [{it.get('category_label', it.get('call_type', '—'))}] [{it.get('action', '—')}] "
            f"{it.get('brokerage', '—')} — target {it.get('price_target', '—')} "
            f"(was {it.get('prior_target', '—')}) — {it.get('source', '—')} · {it.get('published', '—')}\n"
            f"  {it.get('title', '')[:140]}"
        )
    if not result.get("items"):
        lines.append("(No items found in the lookback window.)")
    return "\n".join(lines)
