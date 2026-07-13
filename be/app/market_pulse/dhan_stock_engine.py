"""
dhan_stock_engine.py
----------------------
Dhan.co stock-detail-page data client. Each stock page is server-rendered
(Next.js) and embeds a full `__NEXT_DATA__` JSON blob in the initial HTML with
peer comparison + industry P/E, an F&O options snapshot (PCR, ATM IV, max
pain, OI-based support/resistance), analyst rating consensus, corporate
actions (dividends/results calendar), and multi-period investment returns —
all from a single public page GET, no login/API key/JS execution required.

Coverage: NSE large/mid-cap tickers in DHAN_SLUG_MAP. Dhan's own pagination
for its full ~2,945-ticker list is client-side only (no server-side query
param), so this map is a static seed of the top-traded names rather than the
full universe. Tickers outside the map return None from every function here —
callers must treat Dhan data as an optional enrichment layer, not a required
dependency, and degrade gracefully when it's unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BASE = "https://dhan.co/stocks"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
_TIMEOUT = 20
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)

DHAN_SLUG_MAP: dict[str, str] = {
    "ADANIENSOL": "adani-transmission-ltd",
    "ADANIENT": "adani-enterprises-ltd",
    "ADANIGREEN": "adani-green-energy-ltd",
    "ADANIPORTS": "adani-ports-sez-ltd",
    "ADANIPOWER": "adani-power-ltd",
    "ASIANPAINT": "asian-paints-ltd",
    "AXISBANK": "axis-bank-ltd",
    "BAJAJ-AUTO": "bajaj-auto-ltd",
    "BAJAJFINSV": "bajaj-finserv-ltd",
    "BAJFINANCE": "bajaj-finance-ltd",
    "BEL": "bharat-electronics-ltd",
    "BHARTIARTL": "bharti-airtel-ltd",
    "COALINDIA": "coal-india-ltd",
    "DIVISLAB": "divis-laboratories-ltd",
    "DMART": "dmart-avenue-supermarts-ltd",
    "EICHERMOT": "eicher-motors-ltd",
    "ETERNAL": "zomato-ltd",
    "GRASIM": "grasim-industries-ltd",
    "HAL": "hal-hindustan-aeronautics-ltd",
    "HCLTECH": "hcl-technologies-ltd",
    "HDFCBANK": "hdfc-bank-ltd",
    "HINDALCO": "hindalco-industries-ltd",
    "HINDUNILVR": "hindustan-unilever-ltd",
    "HINDZINC": "hindustan-zinc-ltd",
    "ICICIBANK": "icici-bank-ltd",
    "INDIGO": "indigo-interglobe-aviation-ltd",
    "INFY": "infosys-ltd",
    "IOC": "indian-oil-corporation-ltd",
    "ITC": "itc-ltd",
    "JSWSTEEL": "jsw-steel-ltd",
    "KOTAKBANK": "kotak-mahindra-bank-ltd",
    "LICI": "lic-of-india-ltd",
    "LT": "lt-larsen-toubro-ltd",
    "M&M": "mahindra-mahindra-ltd",
    "MARUTI": "maruti-suzuki-ltd",
    "NESTLEIND": "nestle-india-ltd",
    "NTPC": "ntpc-ltd",
    "ONGC": "oil-natural-gas-corporation-ltd",
    "POWERGRID": "power-grid-corporation-of-india-ltd",
    "RELIANCE": "reliance-industries-ltd",
    "SBILIFE": "sbi-life-insurance-ltd",
    "SBIN": "state-bank-of-india-ltd",
    "SHRIRAMFIN": "shriram-transport-finance-company-ltd",
    "SUNPHARMA": "sun-pharmaceutical-ltd",
    "TATASTEEL": "tata-steel-ltd",
    "TCS": "tcs-tata-consultancy-services-ltd",
    "TITAN": "titan-ltd",
    "TVSMOTOR": "tvs-motors-ltd",
    "ULTRACEMCO": "ultratech-cement-ltd",
    "VAML": "vedanta-aluminium-metal-ltd",
    "WIPRO": "wipro-ltd",
}


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def fetch_dhan_page_props(ticker: str) -> dict[str, Any] | None:
    """Fetch and parse one stock's Dhan page props. Returns None if the ticker
    isn't in DHAN_SLUG_MAP or the page can't be fetched/parsed."""
    slug = DHAN_SLUG_MAP.get(ticker.strip().upper())
    if not slug:
        return None
    url = f"{_BASE}/{slug}-share-price/"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            return None
        data = json.loads(m.group(1))
        return data.get("props", {}).get("pageProps") or None
    except Exception as exc:
        logger.debug("Dhan fetch failed for %s (%s): %s", ticker, url, exc)
        return None


def parse_company_profile(pp: dict[str, Any]) -> dict[str, Any]:
    cv = (pp.get("fundamentalsData") or {}).get("CV") or {}
    return {
        "sector": cv.get("SECTOR"),
        "industry": cv.get("INDUSTRY_NAME"),
        "sub_sector": cv.get("SUB_SECTOR"),
        "classification": cv.get("COMPANY_CLASSIFICATION"),
        "face_value": _num(cv.get("FACE_VALUE")),
        "book_value": _num(cv.get("BOOK_VALUE")),
        "price_to_book": _num(cv.get("PRICE_TO_BOOK_VALUE")),
        "stock_pe": _num(cv.get("STOCK_PE")),
        "dividend_yield_pct": _num(cv.get("DIVIDEND_YEILD")),
        "market_cap_cr": _num(cv.get("MARKET_CAP")),
    }


def parse_peers(pp: dict[str, Any]) -> dict[str, Any]:
    """Peer comparison table + industry P/E, from Dhan's similar-stocks panel."""
    peers = pp.get("similarStkData") or []
    if not peers:
        return {"industry_pe": None, "peers": []}
    industry_pe = next((_num(p.get("Ind_Pe")) for p in peers if _num(p.get("Ind_Pe"))), None)
    rows = []
    for p in peers:
        rows.append({
            "symbol": p.get("Sym"),
            "name": p.get("DispSym"),
            "price": _num(p.get("Ltp")),
            "pe": _num(p.get("Pe")),
            "pb": _num(p.get("Pb")),
            "roe_pct": _num(p.get("Roe")),
            "roce_pct": _num(p.get("ROCE")),
            "div_yield_pct": _num(p.get("DivYeild")),
            "market_cap_cr": _num(p.get("Mcap")),
            "eps": _num(p.get("Eps")),
            "revenue_cr": _num(p.get("Revenue")),
            "return_1y_pct": _num(p.get("PricePerchng1year")),
            "qtr_profit_growth_pct": _num(p.get("YoYLastQtrlyProfitGrowth")),
        })
    return {"industry_pe": industry_pe, "peers": rows}


def parse_options_snapshot(pp: dict[str, Any]) -> dict[str, Any] | None:
    """Nearest-expiry F&O snapshot: PCR, ATM IV, max pain, OI-based support/resistance."""
    fno = pp.get("fnoData") or {}
    opsum = fno.get("opsum") or {}
    if not opsum:
        return None
    entries = sorted(opsum.values(), key=lambda e: e.get("exp", 0) or 0)
    entries = [e for e in entries if (e.get("daystoexp") or 0) >= 0]
    if not entries:
        return None
    nearest = entries[0]
    return {
        "expiry_days": nearest.get("daystoexp"),
        "lot_size": nearest.get("lot"),
        "pcr": _num(nearest.get("pcr")),
        "atm_iv": _num(nearest.get("atmiv")),
        "atm_strike": _num(nearest.get("atm_strike")),
        "max_pain_strike": _num(nearest.get("mxpn_strk")),
        "oi_support": _num(nearest.get("oi_support")),
        "oi_resistance": _num(nearest.get("oi_resist")),
        "total_call_oi": _num(nearest.get("tcoi")),
        "total_put_oi": _num(nearest.get("tpoi")),
        "call_oi_chg_pct": _num(nearest.get("tcoi_pchng")),
        "put_oi_chg_pct": _num(nearest.get("tpoi_pchng")),
    }


def parse_analyst_rating(pp: dict[str, Any]) -> dict[str, Any] | None:
    fdt_list = pp.get("fetchdtData") or []
    if not fdt_list:
        return None
    rating = fdt_list[0].get("AnalystRating")
    if not rating:
        return None
    return {
        "rating": rating.get("Rating"),
        "buy": rating.get("Buy"), "buy_pct": rating.get("BuyPer"),
        "hold": rating.get("Hold"), "hold_pct": rating.get("HoldPer"),
        "sell": rating.get("Sell"), "sell_pct": rating.get("SellPer"),
        "total_analysts": rating.get("Total"),
    }


def parse_corporate_actions(pp: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    fdt_list = pp.get("fetchdtData") or []
    if not fdt_list:
        return []
    acts = fdt_list[0].get("CorpAct") or []
    out = []
    for a in acts[:limit]:
        out.append({
            "type": a.get("ActType"),
            "announced": a.get("AnnDate"),
            "ex_date": a.get("ExDate"),
            "record_date": a.get("RecDate"),
            "dividend_type": a.get("DivType") if a.get("DivType") not in (None, "NA") else None,
            "note": ((a.get("Rmk") or "").strip()[:220]) or None,
        })
    return out


def parse_investment_returns(pp: dict[str, Any]) -> dict[str, float | None]:
    """Multi-period % price return, from the live quote snapshot."""
    scrip_list = pp.get("scripData") or []
    if not scrip_list:
        return {}
    scrip = scrip_list[0]
    return {
        "1w": _num(scrip.get("chp1wk")), "2w": _num(scrip.get("chp2wk")),
        "1m": _num(scrip.get("chp1m")), "3m": _num(scrip.get("chp3m")),
        "6m": _num(scrip.get("chp6m")), "9m": _num(scrip.get("chp9m")),
        "1y": _num(scrip.get("chp1y")), "2y": _num(scrip.get("chp2y")),
        "3y": _num(scrip.get("chp3y")), "5y": _num(scrip.get("chp5y")),
    }


def fetch_dhan_enrichment(ticker: str) -> dict[str, Any] | None:
    """One-call combined Dhan enrichment for a ticker. Returns None if the
    ticker isn't covered by DHAN_SLUG_MAP or the page couldn't be fetched."""
    pp = fetch_dhan_page_props(ticker)
    if not pp:
        return None
    return {
        "source_url": f"{_BASE}/{DHAN_SLUG_MAP.get(ticker.strip().upper())}-share-price/",
        "profile": parse_company_profile(pp),
        "peers": parse_peers(pp),
        "options_snapshot": parse_options_snapshot(pp),
        "analyst_rating": parse_analyst_rating(pp),
        "corporate_actions": parse_corporate_actions(pp),
        "investment_returns": parse_investment_returns(pp),
    }


# ---------------------------------------------------------------------------
# Market movers — Today's Indian Tickers (Top Gainers/Losers, 52W High/Low,
# Most Active by Value/Volume). Each dhan.co live-market page embeds the same
# flat list-of-stocks schema as the stock-detail page's peer panel, so one
# shared row parser covers all six categories.
# ---------------------------------------------------------------------------

MARKET_MOVER_URLS: dict[str, str] = {
    "top_gainers": "https://dhan.co/stock-market-live/top-gainers-today/",
    "top_losers": "https://dhan.co/stock-market-live/top-losers-today/",
    "52w_high": "https://dhan.co/stock-market-live/52-week-high-stocks/",
    "52w_low": "https://dhan.co/stock-market-live/52-week-low-stocks/",
    "most_active_value": "https://dhan.co/stock-market-live/most-active-by-value/",
    "most_active_volume": "https://dhan.co/stock-market-live/most-active-by-volume/",
}

MARKET_MOVER_LABELS: dict[str, str] = {
    "top_gainers": "📈 Top Gainers",
    "top_losers": "📉 Top Losers",
    "52w_high": "🚀 52-Week High",
    "52w_low": "🔻 52-Week Low",
    "most_active_value": "💰 Most Active by Value",
    "most_active_volume": "📊 Most Active by Volume",
}


_SIGNAL_FOR_LABEL = {"BULLISH": "BUY", "BEARISH": "SELL", "NEUTRAL": "WAIT"}


def classify_mover_signal(r: dict[str, Any]) -> dict[str, Any]:
    """Experienced-trader-style BUY/SELL/WAIT read for one mover row, from what's
    actually available in the live-movers snapshot (no OHLC history here): today's
    move direction, multi-period return alignment (is today's move part of a real
    trend or a one-day blip against it), position within the 52-week range, and a
    fundamentals quality/valuation sanity check — so a big move isn't taken at
    face value without checking whether the underlying business supports it."""
    score = 0.0
    reasons: list[str] = []

    change_pct = r.get("change_pct")
    ret_1w = r.get("return_1w_pct")
    ret_1m = r.get("return_1m_pct")
    price = r.get("price")
    high_1y = r.get("high_1y")
    low_1y = r.get("low_1y")
    qtr_growth = r.get("qtr_profit_growth_pct")
    roe = r.get("roe_pct")
    roce = r.get("roce_pct")
    pe = r.get("pe")
    ind_pe = r.get("industry_pe")

    if change_pct is not None:
        if change_pct > 0:
            score += 1
            reasons.append(f"+ Up {change_pct:.1f}% today")
        elif change_pct < 0:
            score -= 1
            reasons.append(f"- Down {change_pct:.1f}% today")

    if ret_1w is not None and ret_1m is not None:
        if ret_1w > 0 and ret_1m > 0:
            score += 1
            reasons.append("+ 1W and 1M returns both positive — trend, not a blip")
        elif ret_1w < 0 and ret_1m < 0:
            score -= 1
            reasons.append("- 1W and 1M returns both negative — sustained weakness")
        elif (change_pct or 0) > 0 and ret_1m < 0:
            reasons.append("⚠ Today up but 1M return still negative — possible bounce in a downtrend")
        elif (change_pct or 0) < 0 and ret_1m > 0:
            reasons.append("⚠ Today down but 1M return still positive — possible pullback in an uptrend")

    if price and high_1y and low_1y and high_1y > low_1y:
        range_pos = (price - low_1y) / (high_1y - low_1y)
        if range_pos >= 0.9:
            score += 1
            reasons.append(f"+ Near 52-week high ({range_pos * 100:.0f}% of range) — structural strength")
        elif range_pos <= 0.1:
            score -= 1
            reasons.append(f"- Near 52-week low ({range_pos * 100:.0f}% of range) — structural weakness")

    if qtr_growth is not None:
        if qtr_growth > 15:
            score += 1
            reasons.append(f"+ Quarterly profit growth {qtr_growth:.0f}% YoY")
        elif qtr_growth < -10:
            score -= 1
            reasons.append(f"- Quarterly profit declined {qtr_growth:.0f}% YoY")

    if roe is not None and roce is not None:
        if roe >= 15 and roce >= 15:
            score += 1
            reasons.append(f"+ Quality returns on capital (ROE {roe:.0f}%, ROCE {roce:.0f}%)")
        elif roe < 5 or roce < 5:
            score -= 1
            reasons.append(f"- Weak returns on capital (ROE {roe:.0f}%, ROCE {roce:.0f}%)")

    if pe is not None and ind_pe and ind_pe > 0 and pe > 0:
        ratio = pe / ind_pe
        if ratio > 2.5:
            score -= 1
            reasons.append(f"- P/E {pe:.1f}x is {ratio:.1f}x industry P/E — richly valued, mean-reversion risk")
        elif ratio < 0.7:
            score += 0.5
            reasons.append(f"+ P/E {pe:.1f}x is below industry P/E {ind_pe:.1f}x — reasonably valued")

    if score >= 3:
        label = "BULLISH"
    elif score <= -3:
        label = "BEARISH"
    else:
        label = "NEUTRAL"
    confidence = round(min(95.0, 50.0 + abs(score) * 8), 1)

    return {
        "label": label,
        "signal": _SIGNAL_FOR_LABEL[label],
        "confidence_pct": confidence,
        "score": score,
        "reasons": reasons,
    }


def _parse_mover_row(row: dict[str, Any]) -> dict[str, Any]:
    # NOTE: Dhan's "Pchange" field is the absolute price change (currency units),
    # not a percentage, despite the name — verified against Ltp - BcClose (previous
    # close). "PPerchange" is the actual day's % change.
    parsed = {
        "symbol": row.get("Sym"),
        "name": row.get("DispSym"),
        "price": _num(row.get("Ltp")),
        "change_pct": _num(row.get("PPerchange")),
        "change_abs": _num(row.get("Pchange")),
        "volume": _num(row.get("Volume")),
        "value_traded_cr": (_num(row.get("ValueTradedToday")) or 0) / 1e7 if row.get("ValueTradedToday") is not None else None,
        "market_cap_cr": _num(row.get("Mcap")),
        "pe": _num(row.get("Pe")),
        "industry_pe": _num(row.get("Ind_Pe")),
        "roe_pct": _num(row.get("Roe")),
        "roce_pct": _num(row.get("ROCE")),
        "div_yield_pct": _num(row.get("DivYeild")),
        "high_1y": _num(row.get("High1Yr")),
        "low_1y": _num(row.get("Low1Yr")),
        "return_1w_pct": _num(row.get("PricePerchng1week")),
        "return_1m_pct": _num(row.get("PricePerchng1mon")),
        "return_1y_pct": _num(row.get("PricePerchng1year")),
        "qtr_profit_growth_pct": _num(row.get("YoYLastQtrlyProfitGrowth")),
        "seosym": row.get("Seosym"),
    }
    parsed["signal"] = classify_mover_signal(parsed)
    return parsed


def fetch_market_movers(category: str) -> list[dict[str, Any]]:
    """Fetch one 'Today's Indian Tickers' category (see MARKET_MOVER_URLS keys).
    These are live-market snapshot pages that change throughout the session.
    Returns an empty list if the category is unknown or the page can't be
    fetched/parsed."""
    url = MARKET_MOVER_URLS.get(category)
    if not url:
        return []
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            return []
        data = json.loads(m.group(1))
        rows = data.get("props", {}).get("pageProps", {}).get("listData") or []
        if not isinstance(rows, list):
            return []
        return [_parse_mover_row(r) for r in rows]
    except Exception as exc:
        logger.debug("Dhan market-movers fetch failed for %s (%s): %s", category, url, exc)
        return []
