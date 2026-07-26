"""
india_fii_dii_holdings_engine.py
---------------------------------
India stock ownership + fundamentals read from screener.in for one or more NSE
tickers over a user-selected date range:

- Promoters / FII / DII / Public stake trend
- Quarterly Revenue & Profit trend (Increasing / Decreasing)
- P/E justification (Undervalued / Fair / High / Overvalued vs ROCE)
- Combined invest-timing verdict (YES / WAIT / NO)
- Deals, orders & expansion plans from recent company announcements
"""

from __future__ import annotations

import logging
import re
import time
from calendar import monthrange
from datetime import date
from typing import Any, Callable

import pandas as pd
from bs4 import BeautifulSoup

from app.market_pulse.dhan_stock_engine import fetch_dhan_enrichment
from app.market_pulse.fundamental_analysis_engine import (
    _clean_num,
    _parse_growth_boxes,
    _parse_pros_cons,
    _parse_section_table,
    _parse_shareholding,
    _parse_top_ratios,
    _valuation_read,
    fetch_screener_html,
)

logger = logging.getLogger(__name__)

_HOLDING_FLAT_PP = 0.30
_REV_PROFIT_FLAT_PCT = 5.0
_CATEGORIES = ("Promoters", "FIIs", "DIIs", "Public")
_CATEGORY_ALIASES = {
    "promoters": "Promoters",
    "promoter": "Promoters",
    "fiis": "FIIs",
    "fii": "FIIs",
    "fpi": "FIIs",
    "fpis": "FIIs",
    "diis": "DIIs",
    "dii": "DIIs",
    "public": "Public",
    "others": "Public",
    "retail": "Public",
}

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Keywords used to flag deals / orders / expansion-style announcements
_DEAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Order / Contract", re.compile(
        r"\b(order|orders|contract|contracts|award|awarded|wins?|won|bagged|loa|letter of award|"
        r"purchase order|work order|mandate)\b", re.I,
    )),
    ("Deal / M&A / JV", re.compile(
        r"\b(deal|mou|agreement|acquisition|acquire[sd]?|merger|amalgamation|joint venture|\bjv\b|"
        r"partnership|strategic alliance|stake sale|stake purchase|preferential allotment|"
        r"ofs)\b", re.I,
    )),
    ("Expansion / Capex", re.compile(
        r"\b(expansion|expand|capex|capacity|plant|factory|facility|greenfield|brownfield|"
        r"new unit|commissioned|inaugurat|launch(?:es|ed)?|opens?|opened|invest(?:s|ment|ed)?|"
        r"subsidiary|lab|centre|center|campus)\b", re.I,
    )),
]

# Broader action taxonomy for the Actions result tab
_ACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Block / Bulk Deal", re.compile(
        r"\b(block deal|bulk deal|block trade|bulk trade|block.?deals|bulk.?deals)\b", re.I,
    )),
    ("Upgrade", re.compile(
        r"\b(upgrade[sd]?|raises?\s+(?:the\s+)?(?:price\s+)?target|target\s+raise|"
        r"outperform|overweight|rating raised)\b", re.I,
    )),
    ("Downgrade", re.compile(
        r"\b(downgrade[sd]?|cuts?\s+(?:the\s+)?(?:price\s+)?target|target\s+cut|"
        r"underperform|underweight|rating cut|rating lowered)\b", re.I,
    )),
    ("Analyst / Recommendation", re.compile(
        r"\b(analyst|brokerage|recommends?|recommendation|initiate[sd]? coverage|"
        r"reiterate[sd]?|price target|buy rating|sell rating|hold rating)\b", re.I,
    )),
    ("Order / Contract", _DEAL_PATTERNS[0][1]),
    ("Deal / M&A / JV", _DEAL_PATTERNS[1][1]),
    ("Expansion / Capex", _DEAL_PATTERNS[2][1]),
    ("News / Press", re.compile(
        r"\b(press release|newspaper|media|news)\b", re.I,
    )),
]

_ACTION_BUCKET_ORDER = [
    "Block / Bulk Deal",
    "Upgrade",
    "Downgrade",
    "Analyst / Recommendation",
    "Order / Contract",
    "Deal / M&A / JV",
    "Expansion / Capex",
    "News / Press",
    "Credit Rating",
    "Concall",
    "Other",
]



def _normalize_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    for suffix in (".NS", ".BO", ".NSE", ".BSE"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t


def parse_shareholding_period(label: str) -> date | None:
    """Parse screener column labels like 'Mar 2025' / 'Dec 2024' → month-end date."""
    if not label:
        return None
    text = str(label).strip()
    m = re.match(r"^([A-Za-z]{3})\s+(\d{4})$", text)
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1)[:3].lower())
    if not month:
        return None
    year = int(m.group(2))
    return date(year, month, monthrange(year, month)[1])


def _normalize_category(label: str) -> str | None:
    key = re.sub(r"[^a-z]", "", (label or "").lower())
    return _CATEGORY_ALIASES.get(key)


def _trend_label(delta: float, flat: float = _HOLDING_FLAT_PP) -> str:
    if delta > flat:
        return "INCREASING"
    if delta < -flat:
        return "DECREASING"
    return "STABLE"


def _pct_trend_label(pct_change: float | None, flat: float = _REV_PROFIT_FLAT_PCT) -> str:
    if pct_change is None:
        return "N/A"
    if pct_change > flat:
        return "INCREASING"
    if pct_change < -flat:
        return "DECREASING"
    return "STABLE"


def _filter_periods(
    periods: list[tuple[date, str]],
    from_date: date,
    to_date: date,
) -> list[tuple[date, str]]:
    """Keep quarter columns inside [from, to]; if <2, pad with nearest outside edges."""
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    periods = sorted(periods, key=lambda x: x[0])
    inside = [p for p in periods if from_date <= p[0] <= to_date]
    if len(inside) >= 2:
        return inside
    if not periods:
        return []
    before = [p for p in periods if p[0] <= to_date]
    after = [p for p in periods if p[0] >= from_date]
    pick: list[tuple[date, str]] = []
    if before:
        pick.append(before[-1])
    if after and after[0] not in pick:
        pick.append(after[0])
    if len(pick) < 2 and len(periods) >= 2:
        pick = periods[-2:]
    return sorted(pick, key=lambda x: x[0])


def _series_for_category(sh_df: pd.DataFrame, category: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for idx in sh_df.index:
        if _normalize_category(str(idx)) != category:
            continue
        for col in sh_df.columns:
            val = _clean_num(str(sh_df.loc[idx, col]))
            if val is not None:
                out[str(col)] = float(val)
        break
    return out


def _row_series(df: pd.DataFrame, row_name: str) -> dict[str, float]:
    if df is None or df.empty or row_name not in df.index:
        return {}
    out: dict[str, float] = {}
    for col in df.columns:
        val = _clean_num(str(df.loc[row_name, col]))
        if val is not None:
            out[str(col)] = float(val)
    return out


def _metric_change(
    series: dict[str, float],
    selected: list[tuple[date, str]],
) -> dict[str, Any] | None:
    if not series or len(selected) < 2:
        return None
    usable = [(d, c) for d, c in selected if c in series]
    if len(usable) < 2:
        return None
    first_d, first_c = usable[0]
    last_d, last_c = usable[-1]
    first_v = series[first_c]
    last_v = series[last_c]
    if first_v == 0:
        pct = None
    else:
        pct = round((last_v - first_v) / abs(first_v) * 100, 1)
    change = round(last_v - first_v, 2)
    return {
        "first_date": first_d,
        "first_period": first_c,
        "first_value": round(first_v, 2),
        "last_date": last_d,
        "last_period": last_c,
        "last_value": round(last_v, 2),
        "change": change,
        "change_pct": pct,
        "trend": _pct_trend_label(pct),
        "n_periods": len(usable),
    }


def _invest_summary(cat_trends: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Score FII/DII/Promoter/Public trends into GOOD / MIXED / BAD for ownership."""
    score = 0
    reasons: list[str] = []

    fii = cat_trends.get("FIIs") or {}
    dii = cat_trends.get("DIIs") or {}
    prom = cat_trends.get("Promoters") or {}
    pub = cat_trends.get("Public") or {}

    fii_t, dii_t = fii.get("trend"), dii.get("trend")
    prom_t, pub_t = prom.get("trend"), pub.get("trend")

    def _pp(info: dict) -> str:
        v = info.get("change_pp")
        if v is None:
            return "?"
        return f"{v:+.2f}"

    if fii_t == "INCREASING":
        score += 2
        reasons.append(f"FIIs accumulating ({_pp(fii)} pp) — foreign institutional support.")
    elif fii_t == "DECREASING":
        score -= 2
        reasons.append(f"FIIs trimming ({_pp(fii)} pp) — foreign outflow pressure.")

    if dii_t == "INCREASING":
        score += 2
        reasons.append(f"DIIs accumulating ({_pp(dii)} pp) — domestic smart-money support.")
    elif dii_t == "DECREASING":
        score -= 1
        reasons.append(f"DIIs reducing ({_pp(dii)} pp) — domestic institutions lightening.")

    if prom_t == "INCREASING":
        score += 1
        reasons.append(f"Promoters raising stake ({_pp(prom)} pp) — insider conviction.")
    elif prom_t == "DECREASING":
        score -= 2
        reasons.append(f"Promoters reducing ({_pp(prom)} pp) — caution; check OFS/pledge.")

    if pub_t == "INCREASING" and (fii_t == "DECREASING" or dii_t == "DECREASING"):
        score -= 1
        reasons.append("Public stake rising while institutions sell — possible distribution pattern.")
    elif pub_t == "DECREASING" and (fii_t == "INCREASING" or dii_t == "INCREASING"):
        score += 1
        reasons.append("Public stake falling while institutions buy — shares moving into stronger hands.")

    if fii_t == "DECREASING" and dii_t == "INCREASING":
        reasons.append(
            "DII buying into FII selling — domestic demand is cushioning foreign outflows (mixed)."
        )

    if score >= 3:
        verdict, tone = "GOOD", "Favorable ownership trend for investing."
    elif score <= -3:
        verdict, tone = "BAD", "Unfavorable ownership trend — caution on fresh buys."
    else:
        verdict, tone = "MIXED", "No clear ownership edge — wait for stronger institutional confirmation."

    return {
        "verdict": verdict,
        "tone": tone,
        "score": score,
        "reasons": reasons,
        "summary": f"{verdict} — {tone}",
    }


def _link_item_from_anchor(a) -> dict[str, Any] | None:
    if not a:
        return None
    title_el = None
    for child in a.children:
        if getattr(child, "name", None) is None:
            chunk = str(child).strip()
            if chunk:
                title_el = chunk
                break
    title = title_el or a.get_text(" ", strip=True)
    sub = a.select_one(".ink-600, .smaller, div")
    subtitle = sub.get_text(" ", strip=True) if sub else ""
    href = a.get("href") or ""
    if not title or title.lower() in ("all", "recent", "important", "search"):
        return None
    return {
        "title": title[:220],
        "detail": subtitle[:320] if subtitle else "",
        "url": href,
        "text": f"{title} {subtitle}".strip(),
    }


def _parse_documents_sections(soup: BeautifulSoup) -> dict[str, list[dict[str, Any]]]:
    """Parse screener #documents into Announcements / Credit ratings / Concalls."""
    out: dict[str, list[dict[str, Any]]] = {
        "announcements": [],
        "credit_ratings": [],
        "concalls": [],
    }
    section = soup.select_one("#documents")
    if not section:
        return out

    key_map = {
        "announcements": "announcements",
        "credit ratings": "credit_ratings",
        "concalls": "concalls",
    }
    for h3 in section.select("h3"):
        heading = (h3.get_text(strip=True) or "").lower()
        bucket = key_map.get(heading)
        if not bucket:
            continue
        # Prefer the list immediately under this heading
        ul = h3.find_next("ul", class_="list-links")
        if ul is None:
            ul = h3.find_next("ul")
        if ul is None:
            continue
        # Stop if we've walked into another documents subsection
        between = h3.find_all_next(["h3", "ul"], limit=6)
        # Use first matching list-links after this h3 before next h3
        cur = h3.next_sibling
        found_ul = None
        while cur is not None:
            if getattr(cur, "name", None) == "h3":
                break
            if getattr(cur, "name", None) == "ul":
                found_ul = cur
                break
            # dive into wrappers
            if getattr(cur, "select_one", None):
                inner = cur.select_one("ul.list-links") or cur.select_one("ul")
                if inner is not None:
                    found_ul = inner
                    break
            cur = cur.next_sibling
        if found_ul is None:
            found_ul = ul
        for li in found_ul.select("li"):
            item = _link_item_from_anchor(li.select_one("a"))
            if not item:
                continue
            if bucket == "announcements" and (
                "annualreport" in (item.get("url") or "").lower()
                or item["title"].lower().startswith("financial year")
            ):
                continue
            if bucket == "concalls" and item["title"].lower() in ("transcript", "ppt", "rec", "notes"):
                # Keep but mark as concall artifact; detail often empty
                item["detail"] = item.get("detail") or item["title"]
            out[bucket].append(item)
    return out


def _parse_announcements(soup: BeautifulSoup, limit: int = 40) -> list[dict[str, Any]]:
    """Parse recent announcements from screener #documents → Announcements list."""
    docs = _parse_documents_sections(soup)
    return (docs.get("announcements") or [])[:limit]


def _classify_deals(announcements: list[dict[str, Any]]) -> dict[str, Any]:
    """Flag announcements that look like orders, deals, or expansion plans."""
    flagged: list[dict[str, Any]] = []
    by_type: dict[str, int] = {}
    for ann in announcements:
        text = ann.get("text") or ""
        matched: list[str] = []
        for label, pat in _DEAL_PATTERNS:
            if pat.search(text):
                matched.append(label)
                by_type[label] = by_type.get(label, 0) + 1
        if matched:
            flagged.append({**ann, "tags": matched})

    if flagged:
        summary = (
            f"{len(flagged)} deal/order/expansion-style announcement(s) found "
            f"({', '.join(f'{k}: {v}' for k, v in by_type.items())})."
        )
        tone = "Positive pipeline signal — recent commercial activity is visible in filings."
    else:
        summary = (
            "No clear order / deal / expansion keywords in the recent announcements list "
            "(routine earnings, meetings, or presentations may still appear below)."
        )
        tone = "No fresh commercial-catalyst headlines flagged — dig into filings if needed."

    return {
        "flagged": flagged,
        "all": announcements,
        "counts": by_type,
        "summary": summary,
        "tone": tone,
        "n_flagged": len(flagged),
        "n_all": len(announcements),
    }


def _tag_action_item(item: dict[str, Any], *, default_tag: str | None = None) -> dict[str, Any]:
    text = item.get("text") or item.get("title") or ""
    matched: list[str] = []
    for label, pat in _ACTION_PATTERNS:
        if pat.search(text):
            matched.append(label)
    if default_tag and default_tag not in matched:
        matched.append(default_tag)
    if not matched:
        matched = ["Other"]
    primary = matched[0]
    # Prefer higher-signal tags when multiple match
    for preferred in _ACTION_BUCKET_ORDER:
        if preferred in matched:
            primary = preferred
            break
    return {**item, "tags": matched, "primary": primary}


def _build_actions(
    soup: BeautifulSoup,
    *,
    dhan: dict | None = None,
) -> dict[str, Any]:
    """Build the Actions tab payload from screener documents (+ optional analyst consensus)."""
    docs = _parse_documents_sections(soup)
    announcements = docs.get("announcements") or []
    credit_ratings = docs.get("credit_ratings") or []
    concalls = docs.get("concalls") or []

    tagged: list[dict[str, Any]] = []
    for ann in announcements:
        tagged.append(_tag_action_item(ann))
    for cr in credit_ratings:
        item = _tag_action_item(cr, default_tag="Credit Rating")
        # Agency rating updates belong in Credit Rating, not broker Analyst
        item["primary"] = "Credit Rating"
        if "Credit Rating" not in item["tags"]:
            item["tags"] = ["Credit Rating", *item["tags"]]
        tagged.append(item)
    # Keep a short concall sample (unique URLs)
    seen_urls: set[str] = set()
    concall_sample: list[dict[str, Any]] = []
    for c in concalls:
        url = c.get("url") or ""
        if url in seen_urls:
            continue
        seen_urls.add(url)
        item = _tag_action_item(c, default_tag="Concall")
        concall_sample.append(item)
        tagged.append(item)
        if len(concall_sample) >= 8:
            break

    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in _ACTION_BUCKET_ORDER}
    for item in tagged:
        primary = item.get("primary") or "Other"
        buckets.setdefault(primary, []).append(item)

    counts = {k: len(v) for k, v in buckets.items() if v}

    analyst_reco = None
    if dhan and dhan.get("analyst_rating"):
        rating = dhan["analyst_rating"]
        analyst_reco = {
            "rating": rating.get("rating"),
            "buy_pct": rating.get("buy_pct"),
            "hold_pct": rating.get("hold_pct"),
            "sell_pct": rating.get("sell_pct"),
            "total_analysts": rating.get("total_analysts"),
            "source": "Dhan.co (shown alongside screener Actions when available)",
            "note": (
                f"Consensus {rating.get('rating')} — "
                f"Buy {rating.get('buy_pct')}% / Hold {rating.get('hold_pct')}% / "
                f"Sell {rating.get('sell_pct')}% "
                f"({rating.get('total_analysts')} analysts)."
            ),
        }

    n_signal = sum(
        counts.get(k, 0)
        for k in (
            "Block / Bulk Deal", "Upgrade", "Downgrade", "Analyst / Recommendation",
            "Order / Contract", "Deal / M&A / JV", "Expansion / Capex", "Credit Rating",
        )
    )
    summary = (
        f"{len(announcements)} recent announcement(s), {len(credit_ratings)} credit-rating link(s), "
        f"{len(concall_sample)} concall link(s). "
        f"{n_signal} action-style item(s) flagged across orders/deals/ratings/upgrades."
    )

    return {
        "announcements": announcements,
        "credit_ratings": credit_ratings,
        "concalls": concall_sample,
        "items": tagged,
        "buckets": buckets,
        "counts": counts,
        "n_announcements": len(announcements),
        "n_signal": n_signal,
        "analyst_reco": analyst_reco,
        "summary": summary,
        "explanation": [
            "**Actions** pulls screener.in's Documents card on the company page:",
            "- **Announcements** — recent BSE/exchange filings & press releases",
            "- **Credit ratings** — ICRA / CRISIL / CARE etc. rating-update links",
            "- **Concalls** — latest transcript / PPT / audio links",
            "Items are keyword-sorted into Block/Bulk Deal, Upgrade, Downgrade, Analyst/Recommendation, "
            "Order/Contract, Deal/M&A, Expansion/Capex, News/Press.",
            "Screener's dedicated Trades (bulk/block) table is login-gated; block-deal rows here come from "
            "announcement text when filings mention them. Broker upgrade/downgrade headlines rarely appear "
            "in company filings — credit-rating updates and any analyst-worded announcements are shown instead.",
        ],
    }



def _build_valuation(
    pe: float | None,
    roce: float | None,
    dhan: dict | None,
) -> dict[str, Any]:
    valuation = _valuation_read(pe, roce)
    valuation["pe"] = pe
    valuation["roce_pct"] = roce
    explanation = [
        "**How P/E justification works:** we compare Stock P/E to ROCE%.",
        "Rough rule of thumb used here — P/E ÷ ROCE:",
        "- **< 0.6** → Undervalued / Attractively Valued (cheap vs capital efficiency)",
        "- **0.6 – 1.1** → Fairly Valued",
        "- **1.1 – 1.8** → Highly Valued / Rich",
        "- **> 1.8** → Overvalued / Expensive",
        "A high-ROCE business can justify a higher P/E; a low-ROCE business usually cannot.",
    ]

    peers_note = None
    if dhan:
        peers = dhan.get("peers") or {}
        industry_pe = peers.get("industry_pe")
        stock_pe = pe or (dhan.get("profile") or {}).get("stock_pe")
        if industry_pe and stock_pe and industry_pe > 0:
            ratio = stock_pe / industry_pe
            if ratio < 0.85:
                peers_note = (
                    f"Also cheap vs peers: stock P/E {stock_pe:.1f}x vs industry P/E {industry_pe:.1f}x."
                )
            elif ratio > 1.3:
                peers_note = (
                    f"Also rich vs peers: stock P/E {stock_pe:.1f}x vs industry P/E {industry_pe:.1f}x."
                )
            else:
                peers_note = (
                    f"In line with peers: stock P/E {stock_pe:.1f}x vs industry P/E {industry_pe:.1f}x."
                )
            valuation["industry_pe"] = industry_pe
            valuation["vs_industry"] = peers_note

    valuation["explanation"] = explanation
    return valuation


def _build_revenue_profit(
    quarterly_df: pd.DataFrame,
    growth_boxes: dict,
    from_date: date,
    to_date: date,
) -> dict[str, Any]:
    periods: list[tuple[date, str]] = []
    if quarterly_df is not None and not quarterly_df.empty:
        for col in quarterly_df.columns:
            d = parse_shareholding_period(str(col))
            if d is not None:
                periods.append((d, str(col)))
    selected = _filter_periods(periods, from_date, to_date) if periods else []

    sales = _row_series(quarterly_df, "Sales")
    profit = _row_series(quarterly_df, "Net Profit")
    sales_chg = _metric_change(sales, selected) if selected else None
    profit_chg = _metric_change(profit, selected) if selected else None

    chart_rows: list[dict[str, Any]] = []
    for d, col in selected:
        row: dict[str, Any] = {"date": d, "period": col}
        if col in sales:
            row["sales"] = sales[col]
        if col in profit:
            row["net_profit"] = profit[col]
        if "sales" in row or "net_profit" in row:
            chart_rows.append(row)

    ttm_sales = (growth_boxes.get("Compounded Sales Growth") or {}).get("TTM")
    ttm_profit = (growth_boxes.get("Compounded Profit Growth") or {}).get("TTM")

    reasons: list[str] = []
    if sales_chg:
        reasons.append(
            f"Sales {sales_chg['trend'].lower()} over selected quarters "
            f"({sales_chg['first_period']} → {sales_chg['last_period']}: "
            f"{sales_chg['change_pct']}% change)."
        )
    if profit_chg:
        reasons.append(
            f"Net Profit {profit_chg['trend'].lower()} over selected quarters "
            f"({profit_chg.get('change_pct')}% change)."
        )
    if ttm_sales is not None:
        reasons.append(f"Screener TTM compounded sales growth: {ttm_sales}%.")
    if ttm_profit is not None:
        reasons.append(f"Screener TTM compounded profit growth: {ttm_profit}%.")

    return {
        "sales": sales_chg,
        "net_profit": profit_chg,
        "ttm_sales_growth_pct": ttm_sales,
        "ttm_profit_growth_pct": ttm_profit,
        "sales_cagr": growth_boxes.get("Compounded Sales Growth") or {},
        "profit_cagr": growth_boxes.get("Compounded Profit Growth") or {},
        "periods": [c for _, c in selected],
        "dates": [d for d, _ in selected],
        "chart_df": pd.DataFrame(chart_rows),
        "reasons": reasons,
        "explanation": [
            "**Revenue & Profit** use screener's quarterly results table (Sales, Net Profit).",
            "Only quarters inside (or nearest to) your From/To dates are compared.",
            f"Change > +{_REV_PROFIT_FLAT_PCT:.0f}% → Increasing; < −{_REV_PROFIT_FLAT_PCT:.0f}% → Decreasing; else Stable.",
            "TTM compounded growth boxes give a longer trailing view beyond the selected window.",
        ],
    }


def _invest_timing(
    ownership: dict[str, Any],
    revenue_profit: dict[str, Any],
    valuation: dict[str, Any],
    deals: dict[str, Any],
) -> dict[str, Any]:
    """Combine ownership + business + valuation + deals into YES / WAIT / NO."""
    score = 0
    reasons: list[str] = []

    own = ownership.get("verdict")
    if own == "GOOD":
        score += 2
        reasons.append("+ Ownership: favorable institutional/promoter trend.")
    elif own == "BAD":
        score -= 2
        reasons.append("- Ownership: unfavorable stake trend.")
    else:
        reasons.append("~ Ownership: mixed / unclear.")

    sales_t = ((revenue_profit.get("sales") or {}) or {}).get("trend")
    profit_t = ((revenue_profit.get("net_profit") or {}) or {}).get("trend")
    if sales_t == "INCREASING":
        score += 1
        reasons.append("+ Revenue increasing over the selected quarters.")
    elif sales_t == "DECREASING":
        score -= 1
        reasons.append("- Revenue decreasing over the selected quarters.")
    if profit_t == "INCREASING":
        score += 1
        reasons.append("+ Profit increasing over the selected quarters.")
    elif profit_t == "DECREASING":
        score -= 1
        reasons.append("- Profit decreasing over the selected quarters.")

    val_label = valuation.get("label") or "N/A"
    if val_label.startswith("Undervalued"):
        score += 2
        reasons.append(f"+ Valuation: {val_label} — P/E looks attractive vs ROCE.")
    elif val_label == "Fairly Valued":
        score += 1
        reasons.append("+ Valuation: Fairly Valued — P/E roughly justified by ROCE.")
    elif val_label.startswith("Highly Valued"):
        score -= 1
        reasons.append(f"- Valuation: {val_label} — already pricing in a lot of good news.")
    elif val_label.startswith("Overvalued"):
        score -= 2
        reasons.append(f"- Valuation: {val_label} — limited margin of safety on P/E.")

    if (deals.get("n_flagged") or 0) >= 2:
        score += 1
        reasons.append("+ Multiple recent deal/order/expansion announcements.")
    elif (deals.get("n_flagged") or 0) == 1:
        reasons.append("~ At least one recent deal/order/expansion headline.")

    if score >= 4:
        verdict = "YES"
        tone = "Conditions look favorable to consider investing (ownership + business + valuation aligned)."
    elif score <= -2:
        verdict = "NO"
        tone = "Conditions look unfavorable for fresh buying right now — wait for better ownership/valuation/business signals."
    else:
        verdict = "WAIT"
        tone = "Mixed picture — not a clear green light; wait for confirmation or a better entry."

    return {
        "verdict": verdict,
        "tone": tone,
        "score": score,
        "reasons": reasons,
        "summary": f"{verdict} — {tone}",
        "explanation": [
            "**Invest timing** is a heuristic combining four tabs:",
            "1) Ownership trend (FII/DII/Promoters/Public)",
            "2) Revenue & Profit direction in your date range",
            "3) Whether P/E is justified vs ROCE (and peers when available)",
            "4) Recent deals / orders / expansion headlines",
            "YES ≥ +4 · WAIT in between · NO ≤ −2. Not financial advice — use as a checklist, not a trigger.",
        ],
    }


def analyze_ticker_shareholding(
    ticker: str,
    from_date: date,
    to_date: date,
) -> dict[str, Any]:
    """Full India FII-DII + fundamentals package for one NSE ticker."""
    ticker = _normalize_ticker(ticker)
    html, url = fetch_screener_html(ticker)
    if not html:
        detail = getattr(fetch_screener_html, "last_error", "") or "network/HTTP failure"
        return {
            "ticker": ticker,
            "error": (
                f"Could not fetch screener.in data for '{ticker}'. {detail}. "
                "Check network access from the backend, wait a few seconds if rate-limited, and retry."
            ),
        }

    soup = BeautifulSoup(html, "html.parser")
    sh_df = _parse_shareholding(soup)
    if sh_df is None or sh_df.empty:
        return {
            "ticker": ticker,
            "error": f"No shareholding table found on screener.in for '{ticker}'.",
            "source_url": url,
        }

    periods: list[tuple[date, str]] = []
    for col in sh_df.columns:
        d = parse_shareholding_period(str(col))
        if d is not None:
            periods.append((d, str(col)))

    if len(periods) < 2:
        return {
            "ticker": ticker,
            "error": f"Need at least 2 quarterly shareholding disclosures for '{ticker}'.",
            "source_url": url,
        }

    selected = _filter_periods(periods, from_date, to_date)
    if len(selected) < 2:
        return {
            "ticker": ticker,
            "error": (
                f"Not enough shareholding periods near {from_date} → {to_date} for '{ticker}'. "
                "Widen the date range (disclosures are typically quarterly)."
            ),
            "source_url": url,
        }

    first_d, first_col = selected[0]
    last_d, last_col = selected[-1]
    cat_trends: dict[str, dict[str, Any]] = {}
    chart_rows: list[dict[str, Any]] = []

    for cat in _CATEGORIES:
        series = _series_for_category(sh_df, cat)
        if not series:
            continue
        for d, col in selected:
            if col in series:
                chart_rows.append({
                    "ticker": ticker,
                    "date": d,
                    "period": col,
                    "category": cat,
                    "holding_pct": series[col],
                })
        if first_col not in series or last_col not in series:
            continue
        first_pct = series[first_col]
        last_pct = series[last_col]
        change = round(last_pct - first_pct, 2)
        cat_trends[cat] = {
            "category": cat,
            "first_date": first_d,
            "first_period": first_col,
            "first_pct": round(first_pct, 2),
            "last_date": last_d,
            "last_period": last_col,
            "last_pct": round(last_pct, 2),
            "change_pp": change,
            "trend": _trend_label(change),
            "n_periods": len([c for _, c in selected if c in series]),
        }

    if not cat_trends:
        return {
            "ticker": ticker,
            "error": f"Could not parse Promoters/FII/DII/Public rows for '{ticker}'.",
            "source_url": url,
        }

    ownership = _invest_summary(cat_trends)

    top_ratios = _parse_top_ratios(soup)
    growth_boxes = _parse_growth_boxes(soup)
    quarterly_df = _parse_section_table(soup, "quarters")
    pros_cons = _parse_pros_cons(soup)

    def _num(label: str, idx: int = 0) -> float | None:
        entry = top_ratios.get(label)
        if not entry or not entry.get("numbers"):
            return None
        nums = entry["numbers"]
        return nums[idx] if idx < len(nums) else None

    pe = _num("Stock P/E")
    roce = _num("ROCE")
    roe = _num("ROE")
    current_price = _num("Current Price")
    market_cap = _num("Market Cap")

    dhan = None
    try:
        dhan = fetch_dhan_enrichment(ticker)
    except Exception as exc:
        logger.debug("Dhan enrichment failed for %s: %s", ticker, exc)

    valuation = _build_valuation(pe, roce, dhan)
    revenue_profit = _build_revenue_profit(quarterly_df, growth_boxes, from_date, to_date)
    announcements = _parse_announcements(soup)
    deals = _classify_deals(announcements)
    actions = _build_actions(soup, dhan=dhan)
    timing = _invest_timing(ownership, revenue_profit, valuation, deals)

    # Attach ticker onto revenue chart for multi-ticker views
    rp_chart = revenue_profit.get("chart_df")
    if isinstance(rp_chart, pd.DataFrame) and not rp_chart.empty:
        rp_chart = rp_chart.copy()
        rp_chart["ticker"] = ticker
        revenue_profit["chart_df"] = rp_chart

    return {
        "ticker": ticker,
        "source_url": url,
        "from_date": from_date,
        "to_date": to_date,
        "first_date": first_d,
        "last_date": last_d,
        "periods": [c for _, c in selected],
        "dates": [d for d, _ in selected],
        "categories": cat_trends,
        "invest": ownership,  # ownership-only (kept for backward UI compat)
        "ownership": ownership,
        "valuation": valuation,
        "revenue_profit": revenue_profit,
        "deals": deals,
        "actions": actions,
        "timing": timing,
        "pros_cons": pros_cons,
        "pe": pe,
        "roce_pct": roce,
        "roe_pct": roe,
        "current_price": current_price,
        "market_cap_cr": market_cap,
        "dhan": dhan,
        "chart_df": pd.DataFrame(chart_rows),
        "shareholding_df": sh_df,
        "quarterly_df": quarterly_df,
    }


def analyze_tickers_shareholding(
    tickers: list[str],
    from_date: date,
    to_date: date,
    *,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Batch analyze tickers; returns multi-tab summary + per-ticker detail."""
    clean = []
    seen: set[str] = set()
    for t in tickers:
        n = _normalize_ticker(t)
        if n and n not in seen:
            seen.add(n)
            clean.append(n)

    if not clean:
        return {"error": "Select at least one Indian NSE ticker."}

    if from_date > to_date:
        from_date, to_date = to_date, from_date

    results: list[dict[str, Any]] = []
    total = max(len(clean), 1)
    for i, ticker in enumerate(clean):
        if progress_callback:
            progress_callback(i / total, f"Analyzing — {ticker}")
        if i > 0:
            # Polite delay — screener.in rate-limits bursts from the same IP.
            time.sleep(0.6)
        results.append(analyze_ticker_shareholding(ticker, from_date, to_date))

    if progress_callback:
        progress_callback(1.0, "Done")

    ok = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]

    summary_rows: list[dict[str, Any]] = []
    for r in ok:
        cats = r.get("categories") or {}
        own = r.get("ownership") or r.get("invest") or {}
        val = r.get("valuation") or {}
        rp = r.get("revenue_profit") or {}
        timing = r.get("timing") or {}
        deals = r.get("deals") or {}
        actions = r.get("actions") or {}
        sales = rp.get("sales") or {}
        profit = rp.get("net_profit") or {}
        row: dict[str, Any] = {
            "Ticker": r["ticker"],
            "From": r.get("first_date"),
            "To": r.get("last_date"),
            "Timing": timing.get("verdict"),
            "Timing score": timing.get("score"),
            "Ownership": own.get("verdict"),
            "Valuation": val.get("label"),
            "P/E": r.get("pe"),
            "ROCE %": r.get("roce_pct"),
            "Revenue trend": sales.get("trend"),
            "Revenue Δ%": sales.get("change_pct"),
            "Profit trend": profit.get("trend"),
            "Profit Δ%": profit.get("change_pct"),
            "Deals flagged": deals.get("n_flagged"),
            "Actions flagged": actions.get("n_signal"),
            "Summary": timing.get("summary"),
        }
        for cat in _CATEGORIES:
            info = cats.get(cat) or {}
            row[f"{cat} %"] = info.get("last_pct")
            row[f"{cat} Δ"] = info.get("change_pp")
            row[f"{cat} trend"] = info.get("trend")
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    if not summary.empty and "Timing score" in summary.columns:
        summary = summary.sort_values("Timing score", ascending=False).reset_index(drop=True)

    chart_parts = [
        r["chart_df"] for r in ok
        if isinstance(r.get("chart_df"), pd.DataFrame) and not r["chart_df"].empty
    ]
    chart_all = pd.concat(chart_parts, ignore_index=True) if chart_parts else pd.DataFrame()

    rp_parts = [
        (r.get("revenue_profit") or {}).get("chart_df")
        for r in ok
    ]
    rp_parts = [c for c in rp_parts if isinstance(c, pd.DataFrame) and not c.empty]
    revenue_chart_all = pd.concat(rp_parts, ignore_index=True) if rp_parts else pd.DataFrame()

    dates_used: list[date] = []
    for r in ok:
        dates_used.extend(r.get("dates") or [])
    dates_used = sorted(set(dates_used))

    note = (
        f"{len(ok)} ticker(s) from screener.in — ownership, quarterly P&L, P/E vs ROCE, "
        f"and recent announcements for {from_date} → {to_date}."
    )
    if dates_used:
        note += f" Ownership snapshot span: {dates_used[0]} → {dates_used[-1]}."

    return {
        "tickers": clean,
        "from_date": from_date,
        "to_date": to_date,
        "dates": dates_used,
        "summary": summary,
        "results": results,
        "ok": ok,
        "errors": errors,
        "chart_all": chart_all,
        "revenue_chart_all": revenue_chart_all,
        "snapshot_note": note,
        "source": "screener.in",
    }
