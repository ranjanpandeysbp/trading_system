"""
fundamental_analysis_engine.py
--------------------------------
India-only fundamental analysis, scraped from screener.in's public company page
(no login / API key required — server-rendered HTML, no JS needed). Enriched
with Dhan.co data via `dhan_stock_engine.fetch_dhan_enrichment` (peer comparison
+ industry P/E, F&O options snapshot, analyst rating consensus, corporate
actions, multi-period returns) — degrades gracefully to `None`
(screener.in-only analysis) if a ticker isn't covered by Dhan's slug map.

For one or more NSE tickers, derives:
- Valuation read (PE vs ROCE-adjusted fair band, plus industry-P/E comparison
  when Dhan data is available) + dividend yield.
- Shareholding trend over ~12 months (Promoters / FIIs / DIIs / Public), with
  a plain-English implication per category.
- Profit & revenue trend over the trailing twelve months (screener's own TTM
  compounded-growth figures) plus longer-term CAGR context.
- Debt trend (borrowings, quarter-over-quarter across recent years).
- Screener.in's own machine-generated Pros / Cons checklist.
- Analyst rating consensus, options PCR/max-pain/OI support-resistance, peer
  comparison, corporate actions, and multi-period investment returns (Dhan,
  when available).
- A combined BULLISH / NEUTRAL / BEARISH investment signal with confidence %.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

from app.market_pulse.dhan_stock_engine import fetch_dhan_enrichment

_BASE = "https://www.screener.in/company"
_HOME = "https://www.screener.in/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
    "Connection": "keep-alive",
}
_TIMEOUT = 30
_MAX_RETRIES = 3

# Holding-% swing (percentage points) over the lookback window below which we call it STABLE.
_HOLDING_FLAT_PP = 0.5
_HOLDING_LOOKBACK_QUARTERS = 4  # ~12 months of quarterly shareholding disclosures

_session: requests.Session | None = None


def _screener_session() -> requests.Session:
    """Shared session so cookies from a warm-up hit are reused."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(_HEADERS)
        try:
            _session.get(_HOME, timeout=_TIMEOUT)
        except Exception as exc:
            logger.debug("screener.in warm-up failed: %s", exc)
    return _session


def fetch_screener_html(ticker: str) -> tuple[str | None, str | None]:
    """Fetch screener.in's company page HTML. Tries consolidated financials first,
    falls back to standalone for companies without a consolidated filing.

    Retries on transient HTTP/network failures. Returns (html, url) or (None, None).
    """
    ticker = ticker.strip().upper()
    session = _screener_session()
    last_err = ""
    for suffix in ("consolidated/", ""):
        url = f"{_BASE}/{ticker}/{suffix}"
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
                status = resp.status_code
                text = resp.text or ""
                if status == 200 and text:
                    # Prefer pages with company stats; shareholding alone is enough for FII/DII.
                    if "top-ratios" in text or 'id="shareholding"' in text or "Shareholding" in text:
                        return text, url
                    last_err = f"HTTP 200 but page missing company data markers ({url})"
                elif status in (403, 429, 503):
                    last_err = f"HTTP {status} from screener.in (blocked/rate-limited)"
                    # Cool down then retry; re-warm session on hard blocks.
                    if attempt < _MAX_RETRIES:
                        time.sleep(1.5 * attempt)
                        if status == 403:
                            try:
                                session.get(_HOME, timeout=_TIMEOUT)
                            except Exception:
                                pass
                        continue
                else:
                    last_err = f"HTTP {status} for {url}"
            except requests.Timeout:
                last_err = f"Timeout fetching {url}"
            except requests.RequestException as exc:
                last_err = f"Network error: {exc}"
            except Exception as exc:
                last_err = f"Fetch error: {exc}"
            if attempt < _MAX_RETRIES:
                time.sleep(0.8 * attempt)
        # try next suffix
    logger.warning("screener.in fetch failed for %s — %s", ticker, last_err or "unknown")
    # Stash last error on the function for callers that want a richer message.
    fetch_screener_html.last_error = last_err  # type: ignore[attr-defined]
    return None, None


fetch_screener_html.last_error = ""  # type: ignore[attr-defined]


def _clean_num(text: str | None) -> float | None:
    if not text:
        return None
    t = text.replace(",", "").replace("₹", "").replace("%", "").replace("Cr.", "").strip()
    if t in ("", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_top_ratios(soup: BeautifulSoup) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ul = soup.select_one("#top-ratios")
    if not ul:
        return out
    for li in ul.select("li"):
        name_el = li.select_one(".name")
        value_el = li.select_one(".value")
        if not name_el or not value_el:
            continue
        label = name_el.get_text(strip=True)
        numbers = [_clean_num(n.get_text(strip=True)) for n in value_el.select(".number")]
        out[label] = {"text": value_el.get_text(" ", strip=True), "numbers": numbers}
    return out


def _parse_pros_cons(soup: BeautifulSoup) -> dict[str, list[str]]:
    section = soup.select_one("#analysis")
    pros = [li.get_text(strip=True) for li in section.select(".pros li")] if section else []
    cons = [li.get_text(strip=True) for li in section.select(".cons li")] if section else []
    return {"pros": pros, "cons": cons}


def _table_to_df(table) -> pd.DataFrame:
    rows = table.select("tr")
    if not rows:
        return pd.DataFrame()
    header = [c.get_text(strip=True) for c in rows[0].select("td,th")]
    data = []
    labels = []
    for r in rows[1:]:
        cells = [c.get_text(strip=True) for c in r.select("td,th")]
        if not cells or not cells[0]:
            continue
        label = cells[0].rstrip("+").strip()
        if label.lower() == "raw pdf":
            continue
        labels.append(label)
        data.append(cells[1:])
    df = pd.DataFrame(data, index=labels, columns=header[1: len(data[0]) + 1] if data else [])
    return df


def _parse_section_table(soup: BeautifulSoup, section_id: str) -> pd.DataFrame:
    section = soup.select_one(f"#{section_id}")
    if not section:
        return pd.DataFrame()
    table = section.select_one("table")
    if not table:
        return pd.DataFrame()
    return _table_to_df(table)


def _parse_growth_boxes(soup: BeautifulSoup) -> dict[str, dict[str, float | None]]:
    section = soup.select_one("#profit-loss")
    out: dict[str, dict[str, float | None]] = {}
    if not section:
        return out
    for table in section.select("table.ranges-table"):
        rows = table.select("tr")
        if not rows:
            continue
        title = rows[0].get_text(strip=True)
        periods: dict[str, float | None] = {}
        for r in rows[1:]:
            cells = [c.get_text(strip=True) for c in r.select("td,th")]
            if len(cells) < 2:
                continue
            periods[cells[0].rstrip(":").strip()] = _clean_num(cells[1])
        out[title] = periods
    return out


def _parse_shareholding(soup: BeautifulSoup) -> pd.DataFrame:
    section = soup.select_one("#shareholding")
    if not section:
        return pd.DataFrame()
    tables = section.select("table")
    if not tables:
        return pd.DataFrame()
    return _table_to_df(tables[0])  # first table = quarterly


def _trend_label(delta: float, flat: float = _HOLDING_FLAT_PP) -> str:
    if delta > flat:
        return "Increasing"
    if delta < -flat:
        return "Decreasing"
    return "Stable"


_HOLDING_IMPLICATIONS = {
    ("Promoters", "Increasing"): "Promoters raising stake — strong conviction signal (open-market buy / preferential allotment).",
    ("Promoters", "Decreasing"): "Promoters trimming stake — caution flag; check for pledge, OFS, or block deal disclosures.",
    ("Promoters", "Stable"): "Promoter holding steady — no new conviction signal either way.",
    ("FIIs", "Increasing"): "Foreign institutions accumulating — bullish; often precedes broader re-rating.",
    ("FIIs", "Decreasing"): "Foreign institutions trimming exposure — cautionary, watch for continued outflows.",
    ("FIIs", "Stable"): "FII holding roughly unchanged — no strong institutional signal.",
    ("DIIs", "Increasing"): "Domestic mutual funds/insurers accumulating — bullish 'smart domestic money' signal.",
    ("DIIs", "Decreasing"): "Domestic institutions reducing exposure — mildly cautionary.",
    ("DIIs", "Stable"): "DII holding roughly unchanged — no strong institutional signal.",
    ("Public", "Increasing"): "Retail/public stake rising — if institutions are simultaneously selling, this can be a distribution pattern (caution).",
    ("Public", "Decreasing"): "Retail/public stake falling — shares moving into stronger (institutional/promoter) hands.",
    ("Public", "Stable"): "Retail/public holding roughly unchanged.",
}


def _shareholding_trend(sh_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if sh_df.empty:
        return out
    cols = list(sh_df.columns)
    lookback = min(_HOLDING_LOOKBACK_QUARTERS, len(cols) - 1)
    for label in sh_df.index:
        if label == "No. of Shareholders":
            continue
        series = [_clean_num(v) for v in sh_df.loc[label]]
        series = [v for v in series if v is not None]
        if len(series) < 2:
            continue
        latest = series[-1]
        base = series[-1 - lookback] if len(series) > lookback else series[0]
        delta = round(latest - base, 2)
        trend = _trend_label(delta)
        out[label] = {
            "latest_pct": latest,
            "delta_pp_12m": delta,
            "trend": trend,
            "implication": _HOLDING_IMPLICATIONS.get((label, trend), ""),
        }
    return out


def _valuation_read(pe: float | None, roce: float | None) -> dict[str, Any]:
    if pe is None or pe <= 0:
        return {"label": "N/A", "reason": "P/E unavailable or negative (loss-making / not meaningful)."}
    if roce is None or roce <= 0:
        return {"label": "N/A", "reason": "ROCE unavailable — cannot quality-adjust the P/E."}
    ratio = pe / roce
    if ratio < 0.6:
        label = "Undervalued / Attractively Valued"
        note = "the P/E is well below what its capital efficiency (ROCE) would justify — priced cheaply relative to how well it earns on capital."
    elif ratio <= 1.1:
        label = "Fairly Valued"
        note = "the P/E roughly tracks its ROCE — priced in line with its capital efficiency, neither cheap nor rich."
    elif ratio <= 1.8:
        label = "Highly Valued / Rich"
        note = "the P/E runs ahead of its ROCE — the market is already paying up for growth/quality beyond current capital efficiency."
    else:
        label = "Overvalued / Expensive"
        note = "the P/E is far above what its ROCE justifies — priced for near-flawless execution, with little room for disappointment."
    return {
        "label": label,
        "reason": f"P/E {pe:.1f}x vs ROCE {roce:.1f}% (P/E ÷ ROCE = {ratio:.2f}) — {note}",
        "pe_roce_ratio": round(ratio, 2),
    }


def _debt_trend(bs_df: pd.DataFrame) -> dict[str, Any]:
    if bs_df.empty or "Borrowings" not in bs_df.index:
        return {"trend": "N/A", "note": "Balance sheet borrowings row unavailable."}
    series = [_clean_num(v) for v in bs_df.loc["Borrowings"]]
    series = [v for v in series if v is not None]
    if not series:
        return {"trend": "N/A", "note": "Borrowings data unavailable."}
    latest = series[-1]
    if latest == 0 and all(v == 0 for v in series[-3:]):
        return {"trend": "Debt-free", "note": "Company carries no borrowings in recent years.", "latest_cr": latest}
    prior = series[-2] if len(series) > 1 else series[-1]
    if prior == 0:
        pct_change = None
    else:
        pct_change = round((latest - prior) / abs(prior) * 100, 1)
    trend = "Increasing" if (pct_change or 0) > 5 else "Decreasing" if (pct_change or 0) < -5 else "Stable"
    return {"trend": trend, "latest_cr": latest, "yoy_change_pct": pct_change}


def _profit_revenue_trend(growth_boxes: dict) -> dict[str, Any]:
    sales_ttm = (growth_boxes.get("Compounded Sales Growth") or {}).get("TTM")
    profit_ttm = (growth_boxes.get("Compounded Profit Growth") or {}).get("TTM")

    def _label(v: float | None) -> str:
        if v is None:
            return "N/A"
        if v > 5:
            return "Increasing"
        if v < -5:
            return "Decreasing"
        return "Flat"

    return {
        "revenue_ttm_growth_pct": sales_ttm,
        "revenue_trend": _label(sales_ttm),
        "profit_ttm_growth_pct": profit_ttm,
        "profit_trend": _label(profit_ttm),
        "sales_cagr": growth_boxes.get("Compounded Sales Growth") or {},
        "profit_cagr": growth_boxes.get("Compounded Profit Growth") or {},
        "roe_trend": growth_boxes.get("Return on Equity") or {},
    }


def _overall_signal(
    valuation: dict, pr_trend: dict, holding_trend: dict, debt: dict, pros_cons: dict,
    dhan: dict | None = None,
) -> dict[str, Any]:
    score = 0
    factors: list[str] = []

    val_label = valuation.get("label", "N/A")
    if val_label in ("Undervalued / Attractively Valued", "Fairly Valued"):
        score += 1
        factors.append(f"+ Valuation: {val_label}")
    elif val_label in ("Highly Valued / Rich", "Overvalued / Expensive"):
        score -= 1
        factors.append(f"- Valuation: {val_label}")

    if pr_trend.get("revenue_trend") == "Increasing":
        score += 1
        factors.append("+ Revenue growing (TTM)")
    elif pr_trend.get("revenue_trend") == "Decreasing":
        score -= 1
        factors.append("- Revenue declining (TTM)")

    if pr_trend.get("profit_trend") == "Increasing":
        score += 1
        factors.append("+ Profit growing (TTM)")
    elif pr_trend.get("profit_trend") == "Decreasing":
        score -= 1
        factors.append("- Profit declining (TTM)")

    promoter = holding_trend.get("Promoters", {})
    if promoter.get("trend") == "Increasing":
        score += 1
        factors.append("+ Promoter holding rising")
    elif promoter.get("trend") == "Decreasing":
        score -= 1
        factors.append("- Promoter holding falling")

    fii = holding_trend.get("FIIs", {})
    if fii.get("trend") == "Increasing":
        score += 1
        factors.append("+ FII holding rising")
    elif fii.get("trend") == "Decreasing":
        score -= 1
        factors.append("- FII holding falling")

    dii = holding_trend.get("DIIs", {})
    if dii.get("trend") == "Increasing":
        score += 1
        factors.append("+ DII holding rising")
    elif dii.get("trend") == "Decreasing":
        score -= 1
        factors.append("- DII holding falling")

    if debt.get("trend") in ("Debt-free", "Decreasing"):
        score += 1
        factors.append(f"+ Debt: {debt.get('trend')}")
    elif debt.get("trend") == "Increasing":
        score -= 1
        factors.append("- Debt increasing")

    n_pros = len(pros_cons.get("pros") or [])
    n_cons = len(pros_cons.get("cons") or [])
    if n_pros > n_cons:
        score += 1
        factors.append(f"+ Screener checklist: {n_pros} pros vs {n_cons} cons")
    elif n_cons > n_pros:
        score -= 1
        factors.append(f"- Screener checklist: {n_cons} cons vs {n_pros} pros")

    max_possible = 8
    if dhan:
        max_possible = 10
        peers = dhan.get("peers") or {}
        industry_pe = peers.get("industry_pe")
        stock_pe = (dhan.get("profile") or {}).get("stock_pe")
        if industry_pe and stock_pe and industry_pe > 0:
            ratio = stock_pe / industry_pe
            if ratio < 0.85:
                score += 1
                factors.append(f"+ P/E {stock_pe:.1f}x is below industry P/E {industry_pe:.1f}x — cheap vs peers")
            elif ratio > 1.3:
                score -= 1
                factors.append(f"- P/E {stock_pe:.1f}x is well above industry P/E {industry_pe:.1f}x — rich vs peers")

        rating = dhan.get("analyst_rating") or {}
        if rating.get("rating") == "Buy" and (rating.get("buy_pct") or 0) >= 60:
            score += 1
            factors.append(f"+ Analyst consensus: {rating.get('rating')} ({rating.get('buy_pct')}% of {rating.get('total_analysts')} analysts)")
        elif rating.get("rating") == "Sell" or (rating.get("sell_pct") or 0) >= 50:
            score -= 1
            factors.append(f"- Analyst consensus: {rating.get('rating')} ({rating.get('sell_pct')}% sell of {rating.get('total_analysts')} analysts)")

    if score >= 3:
        signal = "BULLISH"
    elif score <= -3:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"
    confidence = min(95, 50 + abs(score) * 8)

    return {
        "signal": signal,
        "score": score,
        "max_score": max_possible,
        "confidence_pct": confidence,
        "factors": factors,
    }


_SIGNAL_TO_VERDICT = {"BULLISH": "BUY", "NEUTRAL": "NEUTRAL", "BEARISH": "SELL"}


def analyze_ticker(ticker: str) -> dict[str, Any]:
    """Full fundamental-analysis read for one NSE ticker via screener.in.

    Returns a dict always containing `ticker` and `verdict` ("BUY"/"NEUTRAL"/"SELL"
    or "ERROR" if the scrape failed), matching this package's engine convention.
    """
    ticker = ticker.strip().upper()
    html, url = fetch_screener_html(ticker)
    if not html:
        return {
            "ticker": ticker,
            "verdict": "ERROR",
            "error": (
                f"Could not fetch screener.in data for '{ticker}'. "
                f"{getattr(fetch_screener_html, 'last_error', '') or 'network/HTTP failure'}. "
                "Check backend network access to screener.in and retry."
            ),
        }

    soup = BeautifulSoup(html, "lxml")
    top_ratios = _parse_top_ratios(soup)
    pros_cons = _parse_pros_cons(soup)
    quarterly_df = _parse_section_table(soup, "quarters")
    profit_loss_df = _parse_section_table(soup, "profit-loss")
    balance_sheet_df = _parse_section_table(soup, "balance-sheet")
    ratios_df = _parse_section_table(soup, "ratios")
    shareholding_df = _parse_shareholding(soup)
    growth_boxes = _parse_growth_boxes(soup)

    def _num(label: str, idx: int = 0) -> float | None:
        entry = top_ratios.get(label)
        if not entry or not entry.get("numbers"):
            return None
        nums = entry["numbers"]
        return nums[idx] if idx < len(nums) else None

    pe = _num("Stock P/E")
    roce = _num("ROCE")
    roe = _num("ROE")
    div_yield = _num("Dividend Yield")
    market_cap = _num("Market Cap")
    book_value = _num("Book Value")
    current_price = _num("Current Price")

    valuation = _valuation_read(pe, roce)
    holding_trend = _shareholding_trend(shareholding_df)
    pr_trend = _profit_revenue_trend(growth_boxes)
    debt = _debt_trend(balance_sheet_df)
    try:
        dhan = fetch_dhan_enrichment(ticker)
    except Exception as exc:
        logger.debug("Dhan enrichment failed for %s: %s", ticker, exc)
        dhan = None
    overall = _overall_signal(valuation, pr_trend, holding_trend, debt, pros_cons, dhan)

    return {
        "ticker": ticker,
        "verdict": _SIGNAL_TO_VERDICT.get(overall.get("signal"), "NEUTRAL"),
        "source_url": url,
        "dhan": dhan,
        "current_price": current_price,
        "market_cap_cr": market_cap,
        "pe": pe,
        "roce_pct": roce,
        "roe_pct": roe,
        "dividend_yield_pct": div_yield,
        "book_value": book_value,
        "top_ratios": top_ratios,
        "pros_cons": pros_cons,
        "valuation": valuation,
        "holding_trend": holding_trend,
        "profit_revenue_trend": pr_trend,
        "debt": debt,
        "overall": overall,
        "quarterly_df": quarterly_df,
        "profit_loss_df": profit_loss_df,
        "balance_sheet_df": balance_sheet_df,
        "ratios_df": ratios_df,
        "shareholding_df": shareholding_df,
    }


def analyze_tickers(tickers: list[str]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for t in tickers:
        t = t.strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(analyze_ticker(t))
    return out


FUNDAMENTAL_ANALYSIS_AI_SYSTEM = """You are a fundamental equity research analyst reviewing screener.in-sourced financials for one NSE-listed Indian stock: valuation (P/E vs ROCE), shareholding trend (Promoters/FII/DII/Public over ~12 months), TTM revenue & profit growth, debt trend, screener.in's own machine-generated pros/cons checklist, and — where available — Dhan.co data: peer comparison with industry P/E, analyst rating consensus, an F&O options snapshot (PCR, max pain, OI-based support/resistance), corporate actions, and multi-period price returns.

Given this data:
1. **Valuation** — state plainly whether the stock looks undervalued, fairly valued, or overvalued, referencing the P/E vs ROCE relationship, dividend yield, and — if present — how its P/E compares to the industry P/E and its peer group.
2. **Ownership signal** — interpret the FII/DII/Promoter/Public holding trend together (e.g. institutions buying while retail sells is a stronger signal than either alone).
3. **Business momentum** — synthesize the TTM revenue and profit growth into a one-line read on business trajectory.
4. **Balance sheet** — flag debt trend and any leverage concern.
5. **Street view** — if analyst rating consensus is present, state it plainly (e.g. "27 of 28 analysts rate Buy"); if an options snapshot is present, note the PCR reading and max-pain/OI support-resistance as near-term positioning context (caveat: PCR/max-pain are sentiment indicators, not standalone trade signals).
6. **Verdict** — BULLISH / NEUTRAL / BEARISH with a confidence % and the single strongest supporting and opposing factor.

Cite only figures present in the data — never invent a ratio, holding %, growth figure, peer name, or analyst count. This is research/education only, not financial advice.
"""


def build_fundamental_analysis_ai_prompt(result: dict) -> str:
    if result.get("error"):
        return f"Ticker: {result.get('ticker')}\nError: {result['error']}"

    lines = [
        "=== FUNDAMENTAL ANALYSIS (screener.in + Dhan.co) ===",
        f"Ticker: {result.get('ticker')}",
        f"Current Price: Rs {result.get('current_price')} · Market Cap: Rs {result.get('market_cap_cr')} Cr.",
        f"P/E: {result.get('pe')} · ROCE: {result.get('roce_pct')}% · ROE: {result.get('roe_pct')}% · "
        f"Dividend Yield: {result.get('dividend_yield_pct')}% · Book Value: Rs {result.get('book_value')}",
        "",
        "── VALUATION ──",
        f"{result['valuation'].get('label')}: {result['valuation'].get('reason')}",
        "",
        "── SHAREHOLDING TREND (~12 months) ──",
    ]
    for label, info in (result.get("holding_trend") or {}).items():
        lines.append(
            f"{label}: {info.get('latest_pct')}% (Δ {info.get('delta_pp_12m'):+.2f}pp) → {info.get('trend')}. "
            f"{info.get('implication')}"
        )
    pr = result.get("profit_revenue_trend") or {}
    lines += [
        "",
        "── PROFIT & REVENUE (TTM) ──",
        f"Revenue TTM growth: {pr.get('revenue_ttm_growth_pct')}% ({pr.get('revenue_trend')})",
        f"Profit TTM growth: {pr.get('profit_ttm_growth_pct')}% ({pr.get('profit_trend')})",
        f"Sales CAGR: {pr.get('sales_cagr')}",
        f"Profit CAGR: {pr.get('profit_cagr')}",
        f"ROE trend: {pr.get('roe_trend')}",
        "",
        "── DEBT ──",
        f"{result.get('debt')}",
        "",
        "── SCREENER PROS/CONS ──",
        f"Pros: {'; '.join((result.get('pros_cons') or {}).get('pros') or [])}",
        f"Cons: {'; '.join((result.get('pros_cons') or {}).get('cons') or [])}",
    ]

    dhan = result.get("dhan")
    if dhan:
        profile = dhan.get("profile") or {}
        peers = dhan.get("peers") or {}
        rating = dhan.get("analyst_rating") or {}
        opts = dhan.get("options_snapshot") or {}
        returns = dhan.get("investment_returns") or {}
        corp_acts = dhan.get("corporate_actions") or []

        lines += [
            "",
            "── COMPANY PROFILE (Dhan) ──",
            f"Sector: {profile.get('sector')} · Industry: {profile.get('industry')} · "
            f"Classification: {profile.get('classification')} · Price/Book: {profile.get('price_to_book')}",
        ]
        if peers.get("industry_pe"):
            lines.append(f"Industry P/E: {peers.get('industry_pe')}x (vs this stock's P/E {profile.get('stock_pe')}x)")
        if peers.get("peers"):
            lines.append("Peers: " + "; ".join(
                f"{p['name']} (P/E {p.get('pe')}, ROE {p.get('roe_pct')}%, 1y return {p.get('return_1y_pct')}%)"
                for p in peers["peers"][:6]
            ))
        if rating:
            lines.append(
                f"Analyst consensus: {rating.get('rating')} — Buy {rating.get('buy')} ({rating.get('buy_pct')}%) / "
                f"Hold {rating.get('hold')} ({rating.get('hold_pct')}%) / Sell {rating.get('sell')} ({rating.get('sell_pct')}%) "
                f"of {rating.get('total_analysts')} analysts"
            )
        if opts:
            lines.append(
                f"Options snapshot ({opts.get('expiry_days')}d to expiry): PCR {opts.get('pcr')} · ATM IV {opts.get('atm_iv'):.1f}% "
                f"· Max pain {opts.get('max_pain_strike')} · OI support/resistance {opts.get('oi_support')}/{opts.get('oi_resistance')}"
                if opts.get("atm_iv") is not None else
                f"Options snapshot ({opts.get('expiry_days')}d to expiry): PCR {opts.get('pcr')} · Max pain {opts.get('max_pain_strike')} "
                f"· OI support/resistance {opts.get('oi_support')}/{opts.get('oi_resistance')}"
            )
        if returns:
            lines.append("Returns: " + " · ".join(f"{k}: {v}%" for k, v in returns.items() if v is not None))
        if corp_acts:
            lines.append("Recent corporate actions: " + "; ".join(
                f"{a['type']} ({a.get('announced')})" for a in corp_acts[:5]
            ))

    lines += [
        "",
        "── OVERALL SIGNAL ──",
        f"{result['overall'].get('signal')} (confidence {result['overall'].get('confidence_pct')}%) — "
        + "; ".join(result['overall'].get('factors') or []),
    ]
    return "\n".join(lines)
