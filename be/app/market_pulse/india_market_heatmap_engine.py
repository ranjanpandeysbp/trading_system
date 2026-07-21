"""
india_market_heatmap_engine.py
-------------------------------
NSE/BSE index heatmap data via the tradebrains.in public heatmap API.

API: https://portal.tradebrains.in/api/stocks/heatmap/{SYMBOL}/?page=1&per_page=5000&filter=1D
"""

from __future__ import annotations

import logging
from urllib.parse import quote
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://portal.tradebrains.in/api/stocks/heatmap"

# All indices supported by the tradebrains.in heatmap — name shown in the UI dropdown,
# `symbol` is substituted into the API URL in place of "NIFTY".
INDEX_LIST: list[dict[str, str]] = [
    {"name": "BSE Sensex", "exchange": "BSE", "symbol": "SENSEX"},
    {"name": "Nifty 50", "exchange": "NSE", "symbol": "NIFTY"},
    {"name": "BSE 500", "exchange": "BSE", "symbol": "BSE500"},
    {"name": "BSE Information Technology", "exchange": "BSE", "symbol": "BSEIT"},
    {"name": "BSE Fast Moving Consumer Goods", "exchange": "BSE", "symbol": "BSEFMCG"},
    {"name": "BSE Capital Goods", "exchange": "BSE", "symbol": "BSE CG"},
    {"name": "BSE Consumer Durables", "exchange": "BSE", "symbol": "BSE CD"},
    {"name": "BSE Healthcare", "exchange": "BSE", "symbol": "BSE HC"},
    {"name": "BSE 100", "exchange": "BSE", "symbol": "BSE100"},
    {"name": "BSE 200", "exchange": "BSE", "symbol": "BSE200"},
    {"name": "BSE Dollex 200", "exchange": "BSE", "symbol": "DOL200"},
    {"name": "BSE PSU", "exchange": "BSE", "symbol": "BSEPSU"},
    {"name": "BSE Teck", "exchange": "BSE", "symbol": "BSETECK"},
    {"name": "Nifty Next 50", "exchange": "NSE", "symbol": "NIFTYJR"},
    {"name": "Nifty 500", "exchange": "NSE", "symbol": "NIFTY500"},
    {"name": "BSE BANKEX", "exchange": "BSE", "symbol": "BANKEX"},
    {"name": "Nifty IT", "exchange": "NSE", "symbol": "NIFTYIT"},
    {"name": "BSE Auto", "exchange": "BSE", "symbol": "AUTO"},
    {"name": "BSE Metal", "exchange": "BSE", "symbol": "METAL"},
    {"name": "BSE Oil & Gas", "exchange": "BSE", "symbol": "BSEOILGAS"},
    {"name": "BSE MidCap", "exchange": "BSE", "symbol": "BSEMIDCAP"},
    {"name": "BSE SmallCap", "exchange": "BSE", "symbol": "BSESMALLCAP"},
    {"name": "Nifty Bank", "exchange": "NSE", "symbol": "BANKNIFTY"},
    {"name": "Nifty Energy", "exchange": "NSE", "symbol": "NIFTYENERGY"},
    {"name": "Nifty Pharma", "exchange": "NSE", "symbol": "NIFTYPHARMA"},
    {"name": "Nifty Midcap 100", "exchange": "NSE", "symbol": "NIFTYMIDCAP"},
    {"name": "Nifty 100", "exchange": "NSE", "symbol": "NIFTY100"},
    {"name": "BSE Realty", "exchange": "BSE", "symbol": "BSEREALTY"},
    {"name": "Nifty Infrastructure", "exchange": "NSE", "symbol": "NIFTYINFRAST"},
    {"name": "Nifty Realty", "exchange": "NSE", "symbol": "NIFTYREALTY"},
    {"name": "Nifty PSU Bank", "exchange": "NSE", "symbol": "NIFTYPSUBANK"},
    {"name": "Nifty Midcap 50", "exchange": "NSE", "symbol": "MIDCAP50"},
    {"name": "BSE Power", "exchange": "BSE", "symbol": "POWER"},
    {"name": "Nifty MNC", "exchange": "NSE", "symbol": "NIFTYMNC"},
    {"name": "Nifty FMCG", "exchange": "NSE", "symbol": "NIFTYFMCG"},
    {"name": "Nifty PSE", "exchange": "NSE", "symbol": "NIFTYPSE"},
    {"name": "Nifty Services Sector", "exchange": "NSE", "symbol": "NIFTYSERVICE"},
    {"name": "BSE IPO", "exchange": "BSE", "symbol": "BSEIPO"},
    {"name": "Nifty Smallcap 100", "exchange": "NSE", "symbol": "NIFTYSMALL"},
    {"name": "Nifty India Consumption", "exchange": "NSE", "symbol": "NIFTYCONSUMP"},
    {"name": "Nifty Auto", "exchange": "NSE", "symbol": "NIFTYAUTO"},
    {"name": "Nifty Metal", "exchange": "NSE", "symbol": "NIFTYMETAL"},
    {"name": "Nifty 200", "exchange": "NSE", "symbol": "NIFTY200"},
    {"name": "Nifty Media", "exchange": "NSE", "symbol": "NIFTYMEDIA"},
    {"name": "Nifty Commodities", "exchange": "NSE", "symbol": "NIFTYCDTY"},
    {"name": "Nifty Financial Services", "exchange": "NSE", "symbol": "NIFTYFINANCE"},
    {"name": "Nifty Dividend Opportunities 50", "exchange": "NSE", "symbol": "NIFTYDIVOPPT"},
    {"name": "BSE Greenex", "exchange": "BSE", "symbol": "GREENEX"},
    {"name": "Nifty Alpha 50", "exchange": "NSE", "symbol": "NIFTYALPHA"},
    {"name": "BSE CARBONEX", "exchange": "BSE", "symbol": "CARBONEX"},
    {"name": "BSE SME IPO", "exchange": "BSE", "symbol": "SMEIPO"},
    {"name": "Nifty 100 Liquid 15", "exchange": "NSE", "symbol": "NIFTY100LIQ15"},
    {"name": "Nifty CPSE", "exchange": "NSE", "symbol": "NIFTYCPSE"},
    {"name": "Nifty50 Value 20", "exchange": "NSE", "symbol": "NIFTYV20"},
    {"name": "Nifty Growth Sectors 15", "exchange": "NSE", "symbol": "NI15"},
    {"name": "BSE India Infrastructure Index", "exchange": "BSE", "symbol": "BSEINDINFRA"},
    {"name": "BSE CPSE", "exchange": "BSE", "symbol": "CPSE"},
    {"name": "Nifty 100 Equal Weight", "exchange": "NSE", "symbol": "NIFTY100EQWEIG"},
    {"name": "BSE Allcap", "exchange": "BSE", "symbol": "BSEALLCAP"},
    {"name": "BSE LargeCap", "exchange": "BSE", "symbol": "LRGCAP"},
    {"name": "BSE Commodities", "exchange": "BSE", "symbol": "COMDTY"},
    {"name": "BSE Consumer Discretionary", "exchange": "BSE", "symbol": "CONDIS"},
    {"name": "BSE Energy", "exchange": "BSE", "symbol": "ENERGY"},
    {"name": "BSE Financial Services", "exchange": "BSE", "symbol": "FINSER"},
    {"name": "BSE Industrials", "exchange": "BSE", "symbol": "INDSTR"},
    {"name": "BSE Telecommunication", "exchange": "BSE", "symbol": "TELCOM"},
    {"name": "BSE Utilities", "exchange": "BSE", "symbol": "UTILS"},
    {"name": "BSE India Manufacturing Index", "exchange": "BSE", "symbol": "BSEINDMANUF"},
    {"name": "BSE MidCap Select Index", "exchange": "BSE", "symbol": "MIDSEL"},
    {"name": "BSE SmallCap Select Index", "exchange": "BSE", "symbol": "SMLSEL"},
    {"name": "Nifty Midcap Liquid 15", "exchange": "NSE", "symbol": "LIX 15 MIDCAP"},
    {"name": "Nifty100 Quality 30", "exchange": "NSE", "symbol": "NSEQ30"},
    {"name": "Nifty Private Bank", "exchange": "NSE", "symbol": "NIFTYPTBNK"},
    {"name": "BSE SENSEX 50", "exchange": "BSE", "symbol": "BSESENSEX50"},
    {"name": "BSE SENSEX Next 50", "exchange": "BSE", "symbol": "SNXT50"},
    {"name": "BSE Bharat 22 Index", "exchange": "BSE", "symbol": "BHRT22"},
    {"name": "BSE 100 ESG Index (INR)", "exchange": "BSE", "symbol": "ESG100"},
    {"name": "BSE 150 MidCap Index", "exchange": "BSE", "symbol": "MID150"},
    {"name": "BSE 250 SmallCap Index", "exchange": "BSE", "symbol": "SML250"},
    {"name": "BSE 250 LargeMidCap Index", "exchange": "BSE", "symbol": "LMI250"},
    {"name": "BSE 400 MidSmallCap Index", "exchange": "BSE", "symbol": "MSL400"},
    {"name": "BSE Dividend Stability Index", "exchange": "BSE", "symbol": "S&PDIVSTABLE"},
    {"name": "BSE Enhanced Value Index", "exchange": "BSE", "symbol": "SPBSEVIP"},
    {"name": "BSE Low Volatility Index", "exchange": "BSE", "symbol": "SPBSLVIP"},
    {"name": "BSE Momentum Index", "exchange": "BSE", "symbol": "SPBSMOIP"},
    {"name": "BSE Quality Index", "exchange": "BSE", "symbol": "SPBSQIP"},
    {"name": "Nifty 50 Equal Weight", "exchange": "NSE", "symbol": "NIFTY50EQWEIG"},
    {"name": "Nifty 100 Low Volatility 30", "exchange": "NSE", "symbol": "NIFTY100LOWVOL30"},
    {"name": "BSE Diversified Financials Revenue Growth", "exchange": "BSE", "symbol": "BSEDIVFINREVG"},
    {"name": "BSE 100 LargeCap TMC Index", "exchange": "BSE", "symbol": "BSE100LARGECAPTMC"},
    {"name": "BSE Private Banks Index", "exchange": "BSE", "symbol": "BSEPVTBANK"},
    {"name": "Nifty LargeMidcap 250", "exchange": "NSE", "symbol": "NIFTYLGEMID250"},
    {"name": "Nifty Midcap 150", "exchange": "NSE", "symbol": "NIFTYMIDCAP150"},
    {"name": "Nifty MidSmallcap 400", "exchange": "NSE", "symbol": "NIFTYMIDSMALL400"},
    {"name": "Nifty Smallcap 50", "exchange": "NSE", "symbol": "NIFTYSMALLCAP50"},
    {"name": "Nifty Smallcap 250", "exchange": "NSE", "symbol": "NIFTYSMALLCAP250"},
    {"name": "Nifty100 ESG", "exchange": "NSE", "symbol": "NIFTY100ESG"},
    {"name": "Nifty200 Quality 30", "exchange": "NSE", "symbol": "NIFTY200QLTY30"},
    {"name": "Nifty Alpha Low-Volatility 30", "exchange": "NSE", "symbol": "NFTALLO30"},
    {"name": "Nifty Consumer Durables", "exchange": "NSE", "symbol": "NCONSDUR"},
    {"name": "Nifty Oil & Gas", "exchange": "NSE", "symbol": "NOILGAS"},
    {"name": "Nifty Midcap150 Quality 50", "exchange": "NSE", "symbol": "NMID150Q50"},
    {"name": "Nifty Financial Services 25/50", "exchange": "NSE", "symbol": "NTYFIN2550"},
    {"name": "Nifty200 Momentum 30", "exchange": "NSE", "symbol": "NFTY200MOM30"},
    {"name": "Nifty Healthcare Index", "exchange": "NSE", "symbol": "NIFTYHEALTH"},
    {"name": "Nifty 500 Multicap 50:25:25", "exchange": "NSE", "symbol": "NIFTY500M502525"},
    {"name": "Nifty India Manufacturing", "exchange": "NSE", "symbol": "NIFTYMFG"},
    {"name": "Nifty Midcap Select", "exchange": "NSE", "symbol": "NIFTYMIDSELECT"},
    {"name": "Nifty Microcap 250", "exchange": "NSE", "symbol": "NIFTYMICRO250"},
    {"name": "Nifty India Digital Index", "exchange": "NSE", "symbol": "NIFTYINDIADIG"},
    {"name": "Nifty Total Market", "exchange": "NSE", "symbol": "NIFTYTOTALMCAP"},
    {"name": "BSE Services", "exchange": "BSE", "symbol": "SERVICES"},
]

INDEX_NAME_TO_SYMBOL: dict[str, str] = {row["name"]: row["symbol"] for row in INDEX_LIST}
INDEX_NAME_TO_EXCHANGE: dict[str, str] = {row["name"]: row["exchange"] for row in INDEX_LIST}
INDEX_NAMES: list[str] = [row["name"] for row in INDEX_LIST]


def fetch_heatmap(symbol: str, filter_period: str = "1D") -> list[dict[str, Any]]:
    """Fetch heatmap constituents for an index/sector symbol from tradebrains.in.

    Returns a list of dicts: ticker, company, price, change_abs, change_pct — sorted
    by change_pct descending (biggest gainers first, biggest losers last).
    """
    url = f"{_BASE_URL}/{quote(symbol)}/"
    try:
        resp = requests.get(
            url,
            params={"page": 1, "per_page": 5000, "filter": filter_period},
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            logger.warning("tradebrains heatmap %s -> HTTP %s", symbol, resp.status_code)
            return []
        data = resp.json()
        rows = data.get("results") or []
    except Exception as exc:
        logger.warning("tradebrains heatmap %s failed: %s", symbol, exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        ticker = (row.get("symbol") or "").strip()
        if not ticker:
            continue
        out.append({
            "ticker": ticker,
            "company": row.get("comp_name") or row.get("short_name") or ticker,
            "price": row.get("curr_price"),
            "change_abs": row.get("change"),
            "change_pct": row.get("per_change"),
        })
    out.sort(key=lambda r: (r.get("change_pct") if r.get("change_pct") is not None else -999), reverse=True)
    return out
