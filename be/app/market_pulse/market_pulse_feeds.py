"""
market_pulse_feeds.py
---------------------
News, analyst calls, and economic-event feeds for Market Pulse / News Scanner.
Freshness-filtered RSS (Moneycontrol-heavy) + future-only event calendar.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import pytz
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")
_UTC = pytz.UTC
_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

MAX_NEWS_AGE_HOURS = 96
MAX_ANALYST_AGE_DAYS = 14

# (source label, url, max entries per feed)
INDIA_NEWS_FEEDS: list[tuple[str, str, int]] = [
    ("Moneycontrol Latest", "https://www.moneycontrol.com/rss/latestnews.xml", 18),
    ("Moneycontrol Markets", "https://www.moneycontrol.com/rss/marketreports.xml", 14),
    ("Moneycontrol Buzzing Stocks", "https://www.moneycontrol.com/rss/buzzingstocks.xml", 12),
    ("Moneycontrol Economy", "https://www.moneycontrol.com/rss/economy.xml", 10),
    ("Moneycontrol Results", "https://www.moneycontrol.com/rss/results.xml", 10),
    ("Moneycontrol IPO", "https://www.moneycontrol.com/rss/iponews.xml", 8),
    ("Moneycontrol Global", "https://www.moneycontrol.com/rss/internationalmarkets.xml", 8),
    ("Moneycontrol Commodities", "https://www.moneycontrol.com/rss/commodities.xml", 8),
    ("Economic Times Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", 10),
    ("Business Standard Markets", "https://www.business-standard.com/rss/markets-106.rss", 8),
    ("LiveMint Markets", "https://www.livemint.com/rss/markets", 8),
    ("Financial Express Markets", "https://www.financialexpress.com/market/feed/", 8),
    ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest", 8),
]

GLOBAL_NEWS_FEEDS: list[tuple[str, str, int]] = [
    ("Yahoo Finance US", "https://finance.yahoo.com/rss/topstories", 10),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html", 10),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", 8),
    ("Google Geopolitics", "https://news.google.com/rss/search?q=war+geopolitics&hl=en-US&gl=US&ceid=US:en", 8),
]

ANALYST_FEEDS: list[tuple[str, str, int]] = [
    ("Moneycontrol Brokerage Recos", "https://www.moneycontrol.com/rss/brokeragerecos.xml", 30),
    ("Moneycontrol Stock Ideas", "https://www.moneycontrol.com/rss/marketoutlook.xml", 15),
]

US_ANALYST_FEEDS: list[tuple[str, str, int]] = [
    ("Seeking Alpha Market Currents", "https://seekingalpha.com/market_currents.xml", 20),
    ("Benzinga", "https://www.benzinga.com/feed", 15),
    ("Yahoo Finance US", "https://finance.yahoo.com/rss/topstories", 12),
    ("MarketWatch Top", "https://feeds.marketwatch.com/marketwatch/topstories/", 12),
]

CRYPTO_ANALYST_FEEDS: list[tuple[str, str, int]] = [
    ("CoinTelegraph", "https://cointelegraph.com/rss", 10),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", 10),
]

_BUY_WORDS = ("buy", "accumulate", "overweight", "outperform", "upgrade", "add", "positive")
_SELL_WORDS = ("sell", "underweight", "underperform", "downgrade", "reduce", "avoid", "negative")
_HOLD_WORDS = ("hold", "neutral", "maintain", "equal-weight", "market perform")


def _parse_entry_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, attr, None)
        if tp:
            try:
                return _UTC.localize(datetime(*tp[:6]))
            except Exception:
                pass
    for field in ("published", "updated"):
        raw = entry.get(field)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = _UTC.localize(dt)
            return dt
        except Exception:
            continue
    return None


def _format_pub_display(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    local = dt.astimezone(_IST)
    return local.strftime("%d %b %Y %H:%M IST")


def _is_fresh(dt: datetime | None, *, max_hours: int = MAX_NEWS_AGE_HOURS) -> bool:
    if dt is None:
        return False
    now = datetime.now(_UTC)
    age_h = (now - dt.astimezone(_UTC)).total_seconds() / 3600
    return age_h <= max_hours


def _clean_summary(html: str, limit: int = 220) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:limit]


def _collect_rss_articles(
    feeds: list[tuple[str, str, int]],
    *,
    max_hours: int = MAX_NEWS_AGE_HOURS,
    max_total: int = 80,
) -> list[dict]:
    articles: list[dict] = []
    seen: set[str] = set()

    for source, url, per_feed in feeds:
        try:
            feed = feedparser.parse(url, request_headers=_RSS_HEADERS)
            if getattr(feed, "bozo", False) and not feed.entries:
                logger.debug("RSS parse issue %s: %s", source, getattr(feed, "bozo_exception", ""))
                continue
            for entry in feed.entries[:per_feed]:
                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                key = re.sub(r"\W+", "", title.lower())[:120]
                if key in seen:
                    continue
                pub_dt = _parse_entry_datetime(entry)
                if not _is_fresh(pub_dt, max_hours=max_hours):
                    continue
                seen.add(key)
                link = entry.get("link") or "#"
                summary = _clean_summary(entry.get("summary", ""))
                articles.append({
                    "source": source,
                    "title": title,
                    "link": link,
                    "published": _format_pub_display(pub_dt),
                    "published_dt": pub_dt.isoformat() if pub_dt else "",
                    "summary": summary,
                    "age_hours": round((datetime.now(_UTC) - pub_dt.astimezone(_UTC)).total_seconds() / 3600, 1) if pub_dt else None,
                })
        except Exception as exc:
            logger.debug("RSS fetch failed %s: %s", source, exc)

    articles.sort(
        key=lambda a: a.get("published_dt") or "",
        reverse=True,
    )
    return articles[:max_total]


def _infer_call_action(text: str) -> str:
    low = text.lower()
    for w in _SELL_WORDS:
        if w in low:
            return "SELL"
    for w in _BUY_WORDS:
        if w in low:
            return "BUY"
    for w in _HOLD_WORDS:
        if w in low:
            return "HOLD"
    return "—"


def _infer_brokerage(title: str) -> str:
    m = re.match(r"^([A-Za-z0-9 &\.\-]+?)\s+(?:recommends|maintains|upgrades|downgrades|initiates)", title, re.I)
    if m:
        return m.group(1).strip()[:40]
    for broker in (
        "Motilal Oswal", "ICICI Securities", "HDFC Securities", "Kotak", "Emkay",
        "Axis Capital", "Jefferies", "CLSA", "Goldman Sachs", "Macquarie", "Nomura",
        "Edelweiss", "Sharekhan", "Prabhudas Lilladher", "Nirmal Bang", "Angel One",
        "Morgan Stanley", "Barclays", "JPMorgan", "Bank of America", "Wells Fargo",
        "UBS", "Credit Suisse", "Deutsche Bank", "Citi", "BofA", "RBC", "Wedbush",
    ):
        if broker.lower() in title.lower():
            return broker
    return "—"


def _infer_stock(title: str) -> str:
    patterns = [
        r"(?:on|for|in)\s+([A-Z][A-Za-z0-9&\-\. ]{2,40}?)(?:\s*[;,\|]|with target|at target|\s+target|\s+TP|\s+at Rs|\s+@)",
        r"([A-Z][A-Za-z0-9&\-\. ]{2,35}?)\s*:\s*(?:Buy|Sell|Hold|Accumulate|Reduce)",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.I)
        if m:
            return m.group(1).strip()[:35]
    return "—"


def _infer_call_type(text: str) -> str:
    """Classify brokerage action: upgrade, downgrade, target change, etc."""
    low = text.lower()
    if re.search(r"\bdowngrade[sd]?\b", low):
        return "DOWNGRADE"
    if re.search(r"\bupgrade[sd]?\b", low):
        return "UPGRADE"
    if "initiat" in low and any(k in low for k in ("coverage", "rating", "buy", "sell", "hold")):
        return "INITIATE"
    if re.search(r"(raises?|lifts?|hikes?|bumps?)\s+(?:price\s+)?target", low):
        return "TARGET_RAISE"
    if re.search(r"(cuts?|lowers?|reduces?|slashes?|trims?)\s+(?:price\s+)?target", low):
        return "TARGET_CUT"
    if "re-rat" in low or "rerat" in low:
        return "RERATING"
    if re.search(r"\breiterat", low) or "maintains" in low:
        return "REITERATE"
    return "RECOMMENDATION"


def _fmt_target(val: str, *, currency_hint: str = "") -> str:
    raw = (val or "").replace(",", "").strip()
    if not raw:
        return ""
    try:
        num = float(raw)
    except ValueError:
        return val
    if currency_hint == "INR" or (num > 50 and "$" not in currency_hint):
        return f"₹{num:,.0f}" if num >= 100 else f"₹{num:,.2f}"
    return f"${num:,.2f}" if num >= 1 else f"${num:.4f}"


def _parse_price_targets(text: str) -> tuple[str, str]:
    """Extract (price_target, prior_target) from headline/summary."""
    prior_s = target_s = ""

    m = re.search(
        r"(?:from|vs\.?)\s*(?:Rs\.?|INR|₹|\$|USD)?\s*([\d,]+(?:\.\d+)?)\s+(?:to|→)\s*"
        r"(?:Rs\.?|INR|₹|\$|USD)?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.I,
    )
    if m:
        prior_s = _fmt_target(m.group(1), currency_hint=text)
        target_s = _fmt_target(m.group(2), currency_hint=text)
        return target_s, prior_s

    patterns = [
        r"(?:target|tp|price target)(?:\s+of|\s+to|\s+at)?\s*(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)",
        r"(?:target|tp|price target)(?:\s+of|\s+to|\s+at)?\s*\$\s*([\d,]+(?:\.\d+)?)",
        r"(?:raises?|lifts?|cuts?|lowers?)\s+target\s+to\s*(?:Rs\.?|INR|₹|\$)?\s*([\d,]+(?:\.\d+)?)",
        r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:target|tp)",
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:target|price target)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            target_s = _fmt_target(m.group(1), currency_hint=text)
            break
    return target_s, prior_s


def enrich_analyst_article(art: dict) -> dict:
    """Parse brokerage headline into structured analyst call."""
    title = art.get("title", "")
    summary = art.get("summary", "")
    blob = f"{title} {summary}"
    action = _infer_call_action(blob)
    call_type = _infer_call_type(blob)
    price_target, prior_target = _parse_price_targets(blob)
    return {
        "source": art.get("source", ""),
        "title": title,
        "link": art.get("link", "#"),
        "published": art.get("published", ""),
        "published_dt": art.get("published_dt", ""),
        "summary": summary,
        "stock": _infer_stock(title),
        "brokerage": _infer_brokerage(title),
        "action": action,
        "call_type": call_type,
        "price_target": price_target or "—",
        "prior_target": prior_target or "—",
        "age_hours": art.get("age_hours"),
    }


def _collect_analyst_calls() -> list[dict]:
    raw = _collect_rss_articles(
        ANALYST_FEEDS,
        max_hours=MAX_ANALYST_AGE_DAYS * 24,
        max_total=50,
    )
    calls: list[dict] = []
    for art in raw:
        calls.append(enrich_analyst_article(art))
    # Prefer actionable BUY/SELL first, then recency
    action_rank = {"BUY": 3, "SELL": 2, "HOLD": 1, "—": 0}
    calls.sort(
        key=lambda c: (action_rank.get(c["action"], 0), c.get("published_dt", "")),
        reverse=True,
    )
    return calls


def fetch_analyst_calls_pool(asset_class: str = "india") -> list[dict]:
    """Fetch brokerage / analyst RSS pool for an asset class."""
    import urllib.parse

    feeds: list[tuple[str, str, int]] = list(ANALYST_FEEDS)
    google_queries: list[str] = []

    if asset_class == "us":
        feeds.extend(US_ANALYST_FEEDS)
        google_queries.append("analyst upgrade downgrade price target stock")
    elif asset_class == "crypto":
        feeds.extend(CRYPTO_ANALYST_FEEDS)
        google_queries.append("crypto price target analyst prediction")
    elif asset_class == "commodity":
        feeds.extend(US_ANALYST_FEEDS[:4])
        google_queries.extend([
            "gold crude oil commodity price target forecast",
            "commodity futures analyst outlook upgrade",
        ])
    else:
        google_queries.append("brokerage upgrade downgrade price target NSE")

    for q in google_queries:
        enc = urllib.parse.quote_plus(q)
        feeds.append((
            f"Google Analyst — {q[:30]}",
            f"https://news.google.com/rss/search?q={enc}&hl=en&gl=US&ceid=US:en",
            12,
        ))

    raw = _collect_rss_articles(
        feeds,
        max_hours=MAX_ANALYST_AGE_DAYS * 24,
        max_total=100,
    )
    return [enrich_analyst_article(art) for art in raw]


def filter_analyst_calls_for_ticker(
    pool: list[dict],
    terms: list[str],
    *,
    max_calls: int = 20,
) -> list[dict]:
    """Return analyst calls matching ticker search terms."""
    analyst_keywords = (
        "upgrade", "downgrade", "target", "recommend", "initiat", "reiterat",
        "overweight", "underweight", "outperform", "buy", "sell", "hold",
        "accumulate", "brokerage", "analyst", "rating", "rerat", "re-rat",
    )

    def _matches(call: dict) -> bool:
        blob = f"{call.get('title', '')} {call.get('summary', '')} {call.get('stock', '')}".upper()
        if not any(k in blob.lower() for k in analyst_keywords):
            return False
        for term in terms:
            if len(term) >= 4 and term in blob:
                return True
            if len(term) <= 5 and re.search(rf"\b{re.escape(term)}\b", blob):
                return True
        return False

    matched = [c for c in pool if _matches(c)]
    action_rank = {"BUY": 4, "SELL": 3, "HOLD": 2, "—": 1}
    type_rank = {
        "UPGRADE": 5, "DOWNGRADE": 5, "TARGET_RAISE": 4, "TARGET_CUT": 4,
        "RERATING": 4, "INITIATE": 3, "REITERATE": 2, "RECOMMENDATION": 1,
    }
    matched.sort(
        key=lambda c: (
            action_rank.get(c.get("action"), 0),
            type_rank.get(c.get("call_type"), 0),
            c.get("published_dt", ""),
        ),
        reverse=True,
    )
    return matched[:max_calls]


def summarize_analyst_consensus(calls: list[dict]) -> dict:
    """Aggregate buy/sell/hold and upgrade/downgrade counts."""
    if not calls:
        return {
            "buy": 0, "sell": 0, "hold": 0,
            "upgrades": 0, "downgrades": 0, "target_raises": 0, "target_cuts": 0,
            "consensus": "NO DATA",
            "latest_target": "—",
            "call_count": 0,
        }
    buy = sum(1 for c in calls if c.get("action") == "BUY")
    sell = sum(1 for c in calls if c.get("action") == "SELL")
    hold = sum(1 for c in calls if c.get("action") == "HOLD")
    upgrades = sum(1 for c in calls if c.get("call_type") in ("UPGRADE", "TARGET_RAISE", "RERATING"))
    downgrades = sum(1 for c in calls if c.get("call_type") in ("DOWNGRADE", "TARGET_CUT"))
    target_raises = sum(1 for c in calls if c.get("call_type") == "TARGET_RAISE")
    target_cuts = sum(1 for c in calls if c.get("call_type") == "TARGET_CUT")

    if buy > sell and buy >= hold:
        consensus = "BULLISH"
    elif sell > buy and sell >= hold:
        consensus = "BEARISH"
    elif hold >= buy and hold >= sell:
        consensus = "NEUTRAL"
    else:
        consensus = "MIXED"

    latest_target = "—"
    for c in calls:
        pt = c.get("price_target")
        if pt and pt != "—":
            latest_target = pt
            break

    return {
        "buy": buy,
        "sell": sell,
        "hold": hold,
        "upgrades": upgrades,
        "downgrades": downgrades,
        "target_raises": target_raises,
        "target_cuts": target_cuts,
        "consensus": consensus,
        "latest_target": latest_target,
        "call_count": len(calls),
    }


def fetch_news() -> list[dict]:
    return _collect_rss_articles(INDIA_NEWS_FEEDS, max_hours=MAX_NEWS_AGE_HOURS, max_total=80)


def fetch_global_news() -> list[dict]:
    return _collect_rss_articles(GLOBAL_NEWS_FEEDS, max_hours=MAX_NEWS_AGE_HOURS, max_total=40)


def fetch_analyst_calls() -> list[dict]:
    return _collect_analyst_calls()


def _event_row(
    title: str,
    start: date,
    end: date | None,
    impact: str,
    detail: str,
    region: str,
) -> dict:
    end_d = end or start
    return {
        "title": title,
        "date": _format_event_range(start, end_d),
        "date_start": start.isoformat(),
        "date_end": end_d.isoformat(),
        "impact": impact,
        "detail": detail,
        "region": region,
    }


def _format_event_range(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%d %b %Y")
    if start.month == end.month and start.year == end.year:
        return f"{start.strftime('%d')}-{end.strftime('%d %b %Y')}"
    return f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"


def _build_event_catalog() -> list[dict]:
    """Macro calendar with explicit dates — filtered to future at runtime."""
    events: list[dict] = []

    def add(title, y, m, d, impact, detail, region, span=0):
        start = date(y, m, d)
        end = start + timedelta(days=span) if span else start
        events.append(_event_row(title, start, end, impact, detail, region))

    # ── India 2026 ──
    add("RBI Monetary Policy (MPC)", 2026, 2, 7, "HIGH", "Repo rate decision — liquidity & rate path.", "india", 1)
    add("Union Budget FY27", 2026, 2, 1, "HIGH", "Fiscal policy, capex, taxation — broad market mover.", "india")
    add("RBI Monetary Policy (MPC)", 2026, 4, 9, "HIGH", "Rate decision; guidance on inflation vs growth.", "india", 1)
    add("India CPI Inflation", 2026, 4, 14, "HIGH", "Consumer price index — RBI trajectory input.", "india")
    add("RBI Monetary Policy (MPC)", 2026, 6, 6, "HIGH", "Mid-year rate review; FII sensitivity.", "india", 1)
    add("India CPI Inflation", 2026, 6, 12, "HIGH", "May CPI print.", "india")
    add("India IIP / Industrial Production", 2026, 6, 12, "MEDIUM", "Manufacturing activity gauge.", "india")
    add("India WPI Inflation", 2026, 6, 14, "MEDIUM", "Producer-level inflation.", "india")
    add("GST Council Meeting", 2026, 6, 20, "MEDIUM", "Possible rate / compliance changes.", "india")
    add("RBI Monetary Policy (MPC)", 2026, 8, 8, "HIGH", "Rate decision.", "india", 1)
    add("RBI Monetary Policy (MPC)", 2026, 10, 10, "HIGH", "Festive-season liquidity & rates.", "india", 1)
    add("RBI Monetary Policy (MPC)", 2026, 12, 6, "HIGH", "Final MPC of calendar year.", "india", 1)

    # ── Global 2026 ──
    add("US FOMC Meeting", 2026, 1, 28, "HIGH", "Fed rate decision — EM & DXY impact.", "global", 1)
    add("US FOMC Meeting", 2026, 3, 18, "HIGH", "Fed dots & guidance.", "global", 1)
    add("US FOMC Meeting", 2026, 5, 6, "HIGH", "Rate path for H2.", "global", 1)
    add("US FOMC Meeting", 2026, 6, 17, "HIGH", "Key for FII flows into India.", "global", 1)
    add("US CPI Inflation", 2026, 6, 11, "HIGH", "Core CPI guides Fed — global risk appetite.", "global")
    add("US Non-Farm Payrolls", 2026, 6, 5, "HIGH", "Jobs report — DXY & yields.", "global")
    add("ECB Rate Decision", 2026, 6, 5, "MEDIUM", "Eurozone rates — risk sentiment.", "global")
    add("US FOMC Meeting", 2026, 7, 29, "HIGH", "Summer FOMC.", "global", 1)
    add("OPEC+ Ministerial Meeting", 2026, 6, 1, "HIGH", "Crude output — India import bill.", "global")
    add("Bank of Japan Policy", 2026, 6, 17, "MEDIUM", "Yen carry-trade / EM flows.", "global")
    add("US FOMC Meeting", 2026, 9, 16, "HIGH", "Pre-festive global liquidity.", "global", 1)
    add("US FOMC Meeting", 2026, 11, 4, "HIGH", "Year-end positioning.", "global", 1)
    add("US FOMC Meeting", 2026, 12, 16, "HIGH", "Final FOMC of 2026.", "global", 1)

    return events


def get_upcoming_events(reference: date | None = None) -> tuple[list[dict], list[dict]]:
    """Return India & global events with end date on or after reference (IST today)."""
    ref = reference or datetime.now(_IST).date()
    catalog = _build_event_catalog()

    india: list[dict] = []
    global_ev: list[dict] = []

    for ev in catalog:
        try:
            end_d = date.fromisoformat(ev["date_end"])
        except Exception:
            continue
        if end_d < ref:
            continue
        if ev["region"] == "india":
            india.append(ev)
        else:
            global_ev.append(ev)

    sort_key = lambda e: e.get("date_start", "")
    india.sort(key=sort_key)
    global_ev.sort(key=sort_key)
    return india, global_ev


def fetch_india_news() -> list[dict]:
    return fetch_news()


def get_india_events(reference: date | None = None) -> list[dict]:
    india, _global = get_upcoming_events(reference)
    return india
