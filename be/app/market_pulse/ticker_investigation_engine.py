"""
ticker_investigation_engine.py
--------------------------------
Multi-source news + multi-window price action + S/R + strategy hints per ticker.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Callable

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.indicators import add_rsi
from app.market_pulse.market_pulse_feeds import (
    GLOBAL_NEWS_FEEDS,
    INDIA_NEWS_FEEDS,
    _collect_rss_articles,
    enrich_analyst_article,
    fetch_analyst_calls_pool,
    filter_analyst_calls_for_ticker,
    summarize_analyst_consensus,
)
from app.market_pulse.commodity_screener_engine import COMMODITY_META
from app.market_pulse.run_summary import default_sl_tp_for_timeframe, make_trade_plan
from app.market_pulse.sr_breakout import analyze_sr_breakout
from app.market_pulse.ticker_utils import CRYPTO_MARKET, GROWW_MARKET, US_MARKET
from app.market_pulse.weak_strong_sr_engine import analyze_weak_strong_sr

logger = logging.getLogger(__name__)

ASSET_CONFIG: dict[str, dict[str, Any]] = {
    "crypto": {
        "label": "Crypto (CoinDCX)",
        "market": CRYPTO_MARKET,
        "exchange": "NSE",
        "default_tickers": ["B-BTCUSDT", "B-ETHUSDT", "B-SOLUSDT", "B-BNBUSDT", "B-XRPUSDT"],
    },
    "india": {
        "label": "Indian stocks (NSE)",
        "market": GROWW_MARKET,
        "exchange": "NSE",
        "default_tickers": ["NIFTYBEES", "BANKBEES", "RELIANCE", "TCS", "HDFCBANK"],
    },
    "us": {
        "label": "US stocks",
        "market": US_MARKET,
        "exchange": "NASDAQ",
        "default_tickers": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
    },
    "commodity": {
        "label": "Commodities (Yahoo futures)",
        "market": US_MARKET,
        "exchange": "NASDAQ",
        "default_tickers": ["CL=F", "GC=F", "SI=F", "HG=F", "NG=F", "ZW=F"],
    },
}

# Extra Yahoo futures beyond commodity screener core set
EXTRA_COMMODITY_META: dict[str, dict[str, str]] = {
    "BRENT": {"name": "Brent Crude Oil", "unit": "$/bbl", "yf": "BZ=F"},
    "PLAT": {"name": "Platinum", "unit": "$/oz", "yf": "PL=F"},
    "PALL": {"name": "Palladium", "unit": "$/oz", "yf": "PA=F"},
    "CORN": {"name": "Corn", "unit": "¢/bu", "yf": "ZC=F"},
    "SOY": {"name": "Soybeans", "unit": "¢/bu", "yf": "ZS=F"},
    "COFFEE": {"name": "Coffee", "unit": "¢/lb", "yf": "KC=F"},
    "SUGAR": {"name": "Sugar", "unit": "¢/lb", "yf": "SB=F"},
    "COCOA": {"name": "Cocoa", "unit": "$/t", "yf": "CC=F"},
    "HEATOIL": {"name": "Heating Oil", "unit": "$/gal", "yf": "HO=F"},
    "GASOLINE": {"name": "RBOB Gasoline", "unit": "$/gal", "yf": "RB=F"},
}

ALL_COMMODITY_META: dict[str, dict[str, str | float]] = {
    **COMMODITY_META,
    **EXTRA_COMMODITY_META,
}

INDIA_INDEX_ETF_LABELS: dict[str, str] = {
    "NIFTYBEES": "Nifty 50 Index (NIFTYBEES)",
    "BANKBEES": "Nifty Bank Index (BANKBEES)",
    "ITBEES": "Nifty IT Index (ITBEES)",
    "GOLDBEES": "Gold ETF India (GOLDBEES)",
    "SILVERBEES": "Silver ETF India (SILVERBEES)",
    "JUNIORBEES": "Nifty Next 50 (JUNIORBEES)",
    "MIDCAPETF": "Nifty Midcap 150 (MIDCAPETF)",
    "HDFCSML250": "Nifty Smallcap 250 (HDFCSML250)",
    "MON100": "Nasdaq 100 (MON100)",
    "MODEFENCE": "Defence ETF (MODEFENCE)",
    "FMCGIETF": "FMCG ETF (FMCGIETF)",
    "GROWWPOWER": "Power ETF (GROWWPOWER)",
}

INDIA_STOCK_EXTRAS: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "ITC",
    "KOTAKBANK", "AXISBANK", "MARUTI", "TATAMOTORS", "SUNPHARMA", "BAJFINANCE", "HINDUNILVR",
    "TITAN", "WIPRO", "HCLTECH", "ADANIENT", "NTPC", "POWERGRID", "ONGC", "COALINDIA",
    "ZOMATO", "TRENT", "HAL", "BEL", "DMART", "PIDILITIND", "ASIANPAINT", "ULTRACEMCO",
    "NESTLEIND", "BAJAJFINSV", "JSWSTEEL", "TATASTEEL", "ADANIPORTS", "GRASIM", "DIVISLAB",
    "APOLLOHOSP", "EICHERMOT", "M&M", "HEROMOTOCO", "INDUSINDBK", "SBILIFE", "HDFCLIFE",
]

US_INDEX_ETF_LABELS: dict[str, str] = {
    "SPY": "S&P 500 Index (SPY)",
    "QQQ": "Nasdaq 100 Index (QQQ)",
    "DIA": "Dow Jones Index (DIA)",
    "IWM": "Russell 2000 Index (IWM)",
    "VTI": "Total US Market (VTI)",
    "VOO": "S&P 500 (VOO)",
    "XLK": "Technology Sector (XLK)",
    "XLF": "Financial Sector (XLF)",
    "XLE": "Energy Sector (XLE)",
    "XLV": "Healthcare Sector (XLV)",
    "XLI": "Industrial Sector (XLI)",
    "XLP": "Consumer Staples (XLP)",
    "XLY": "Consumer Discretionary (XLY)",
    "GLD": "Gold ETF (GLD)",
    "SLV": "Silver ETF (SLV)",
    "USO": "Oil ETF (USO)",
    "UNG": "Natural Gas ETF (UNG)",
    "TLT": "20Y Treasury Bond (TLT)",
    "HYG": "High Yield Bonds (HYG)",
}

US_STOCK_EXTRAS: list[str] = [
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AMD", "NFLX",
    "CRM", "ORCL", "AVGO", "COST", "JPM", "BAC", "WFC", "GS", "MS", "V", "MA",
    "XOM", "CVX", "COP", "SLB", "UNH", "JNJ", "PFE", "LLY", "ABBV", "MRK",
    "DIS", "UBER", "ABNB", "COIN", "MSTR", "SMCI", "ARM", "PLTR", "INTC", "QCOM",
]

CRYPTO_NAME_LABELS: dict[str, str] = {
    "B-BTCUSDT": "Bitcoin (BTC-USDT)",
    "B-ETHUSDT": "Ethereum (ETH-USDT)",
    "B-SOLUSDT": "Solana (SOL-USDT)",
    "B-BNBUSDT": "BNB (BNB-USDT)",
    "B-XRPUSDT": "Ripple (XRP-USDT)",
    "B-ADAUSDT": "Cardano (ADA-USDT)",
    "B-DOGEUSDT": "Dogecoin (DOGE-USDT)",
    "B-AVAXUSDT": "Avalanche (AVAX-USDT)",
    "B-LINKUSDT": "Chainlink (LINK-USDT)",
    "B-DOTUSDT": "Polkadot (DOT-USDT)",
    "B-MATICUSDT": "Polygon (MATIC-USDT)",
    "B-LTCUSDT": "Litecoin (LTC-USDT)",
    "B-ATOMUSDT": "Cosmos (ATOM-USDT)",
    "B-NEARUSDT": "NEAR Protocol (NEAR-USDT)",
    "B-ARBUSDT": "Arbitrum (ARB-USDT)",
    "B-OPUSDT": "Optimism (OP-USDT)",
    "B-INJUSDT": "Injective (INJ-USDT)",
    "B-SUIUSDT": "Sui (SUI-USDT)",
    "B-PEPEUSDT": "Pepe (PEPE-USDT)",
    "B-WIFUSDT": "dogwifhat (WIF-USDT)",
}

# (window label, bar TF, bars back)
PRICE_WINDOWS: list[tuple[str, str, int]] = [
    ("5 days", "1d", 5),
    ("24 hrs", "1h", 24),
    ("4 hrs", "1h", 4),
    ("1 hr", "15m", 4),
    ("15 min", "5m", 3),
    ("5 min", "1m", 5),
]

SR_PRIMARY_TF = "15m"
SR_LOOKBACK_TFS = ("5m", "15m", "1h", "1d")
PA_ANALYSIS_TFS = ("15m", "1d")

CRYPTO_NEWS_FEEDS: list[tuple[str, str, int]] = [
    ("CoinTelegraph", "https://cointelegraph.com/rss", 12),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", 12),
    ("Decrypt", "https://decrypt.co/feed", 10),
    ("CryptoSlate", "https://cryptoslate.com/feed/", 10),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/", 8),
]

US_NEWS_FEEDS: list[tuple[str, str, int]] = [
    ("Yahoo Finance US", "https://finance.yahoo.com/rss/topstories", 12),
    ("MarketWatch Top", "https://feeds.marketwatch.com/marketwatch/topstories/", 12),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html", 10),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", 10),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml", 10),
    ("Benzinga", "https://www.benzinga.com/feed", 8),
]

INDIA_EXTRA_FEEDS: list[tuple[str, str, int]] = [
    ("ET Now Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms", 10),
    ("Zee Business", "https://www.zeebiz.com/rss/latest.xml", 8),
    ("LiveMint Companies", "https://www.livemint.com/rss/companies", 8),
]

COMMODITY_NEWS_FEEDS: list[tuple[str, str, int]] = [
    ("Moneycontrol Commodities", "https://www.moneycontrol.com/rss/commodities.xml", 14),
    ("LiveMint Markets", "https://www.livemint.com/rss/markets", 10),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", 10),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html", 10),
    ("MarketWatch Top", "https://feeds.marketwatch.com/marketwatch/topstories/", 10),
]

INVESTIGATION_AI_SYSTEM = """You are an elite sell-side research analyst synthesizing NEWS + ANALYST CALLS + MULTI-TIMEFRAME price action.

Given ticker headlines, brokerage upgrades/downgrades/re-ratings/price targets, % moves (5d → 5m), RSI zones, support/resistance strength, breakout/breakdown odds, and forming strategies:

1. **Analyst impact** — how upgrades, downgrades, and target changes affect sentiment and gap risk.
2. **Immediate impact** — next 1–4 hours: catalysts, sentiment, likely reaction.
3. **Intraday bias** — direction, key levels, scalp vs wait.
4. **Swing outlook** — 3–15 day view if data supports it.
5. **Trade stance** — TAKE / WATCH / AVOID with confidence % and risk notes.

Cite specific analyst calls, targets, headlines, % moves, S/R prices, and RSI. If analysts conflict with technicals, say WAIT.
Emphasize risk management — position size, stop beyond invalidation, no FOMO.
"""

TRADE_SETUP_AI_SYSTEM = """You are an elite institutional trader synthesizing TECHNICALS + NEWS + ANALYST CALLS into ONE actionable trade plan.

You receive: multi-timeframe % moves, RSI zones, weak/strong S/R, breakout/breakdown odds, news headlines, analyst upgrades/downgrades/targets, and rule-based setup candidates with SL%/TP%.

Output MUST include:
1. **VERDICT:** TAKE LONG / TAKE SHORT / NO TRADE / WAIT (one line at top)
2. **Primary setup** — direction, style (scalp vs swing), entry logic, **SL %**, **TP %**, **confidence %**, R:R, max hold
3. **News & analyst impact** — how headlines and brokerage calls shift odds (cite specific items)
4. **Technical confluence** — which TFs agree, key S/R levels, invalidation
5. **Alternate plan** — if no trade, what would change your mind

Rules:
- Only TAKE TRADE when TA + (news OR analysts) align; conflicting signals → NO TRADE.
- SL must sit beyond invalidation (below support for longs, above resistance for shorts).
- Confidence 55–65 = cautious; 66–75 = standard; 76+ = high confluence only.
- Reference concrete numbers from the data — never invent price targets not in the feed.
"""

_BULL_NEWS_WORDS = (
    "surge", "rally", "soar", "jump", "gain", "rise", "bullish", "upgrade", "beat",
    "record high", "outperform", "accumulate", "buy", "breakout", "recovery",
)
_BEAR_NEWS_WORDS = (
    "fall", "drop", "plunge", "slump", "decline", "bearish", "downgrade", "miss",
    "cut", "sell", "warning", "crash", "breakdown", "concern", "probe", "investigation",
)

_TICKER_ALIASES: dict[str, list[str]] = {
    "B-BTCUSDT": ["BTC", "BITCOIN", "BTCUSDT", "BTC-USDT"],
    "B-ETHUSDT": ["ETH", "ETHEREUM", "ETHUSDT"],
    "B-SOLUSDT": ["SOL", "SOLANA", "SOLUSDT"],
    "RELIANCE": ["RELIANCE", "RIL", "RELIANCE INDUSTRIES"],
    "HDFCBANK": ["HDFC BANK", "HDFCBANK"],
    "TCS": ["TCS", "TATA CONSULTANCY"],
    "INFY": ["INFY", "INFOSYS"],
    "AAPL": ["APPLE", "AAPL"],
    "MSFT": ["MICROSOFT", "MSFT"],
    "NVDA": ["NVIDIA", "NVDA"],
    "SPY": ["S&P 500", "SPY", "S&P500"],
    "CL=F": ["CRUDE", "WTI", "OIL", "CRUDE OIL", "PETROLEUM"],
    "GC=F": ["GOLD", "BULLION", "PRECIOUS METAL"],
    "SI=F": ["SILVER"],
    "HG=F": ["COPPER"],
    "NG=F": ["NATURAL GAS", "NATGAS", "GAS"],
    "ZW=F": ["WHEAT", "GRAIN"],
}


def _commodity_meta_for_ticker(ticker: str) -> dict[str, str] | None:
    key = ticker.upper().replace(".NS", "")
    sym_to_yf = {sym: str(meta["yf"]) for sym, meta in ALL_COMMODITY_META.items()}
    name_to_yf = {str(meta["name"]).upper(): str(meta["yf"]) for meta in ALL_COMMODITY_META.values()}

    if key in ALL_COMMODITY_META:
        meta = ALL_COMMODITY_META[key]
        return {"sym": key, "yf": str(meta["yf"]), "name": str(meta["name"])}
    if key in sym_to_yf.values():
        for sym, meta in ALL_COMMODITY_META.items():
            if str(meta["yf"]).upper() == key:
                return {"sym": sym, "yf": str(meta["yf"]), "name": str(meta["name"])}
    if key in name_to_yf:
        yf = name_to_yf[key]
        for sym, meta in ALL_COMMODITY_META.items():
            if str(meta["yf"]) == yf:
                return {"sym": sym, "yf": yf, "name": str(meta["name"])}
    # Partial name match e.g. "GOLD", "CRUDE"
    for sym, meta in ALL_COMMODITY_META.items():
        name_up = str(meta["name"]).upper()
        if key in name_up or name_up.startswith(key):
            return {"sym": sym, "yf": str(meta["yf"]), "name": str(meta["name"])}
    return None


def ticker_display_name(symbol: str, asset_class: str) -> str:
    """Human-readable label for UI headlines and pickers."""
    pool = investigation_ticker_pool(asset_class)
    if symbol in pool:
        return pool[symbol]
    if asset_class == "commodity":
        meta = _commodity_meta_for_ticker(symbol)
        if meta:
            return f"{meta['name']} ({meta['yf']})"
    if asset_class == "crypto":
        if symbol in CRYPTO_NAME_LABELS:
            return CRYPTO_NAME_LABELS[symbol]
        base = symbol.replace("B-", "").replace("USDT", "")
        if base:
            return f"{base}-USDT"
    return symbol


def investigation_ticker_pool(asset_class: str) -> dict[str, str]:
    """Map data symbol → display label for multiselect."""
    pool: dict[str, str] = {}

    if asset_class == "commodity":
        for _sym, meta in ALL_COMMODITY_META.items():
            yf = str(meta["yf"])
            if yf not in pool:
                pool[yf] = f"{meta['name']} ({yf})"
        return pool

    if asset_class == "india":
        pool.update(INDIA_INDEX_ETF_LABELS)
        try:
            from app.market_pulse.ticker_utils import DEFAULT_GROWW_TICKERS
            for sym in DEFAULT_GROWW_TICKERS:
                if sym not in pool:
                    pool[sym] = sym
        except Exception:
            pass
        for sym in INDIA_STOCK_EXTRAS:
            if sym not in pool:
                pool[sym] = sym
        return pool

    if asset_class == "us":
        pool.update(US_INDEX_ETF_LABELS)
        for sym in US_STOCK_EXTRAS:
            if sym not in pool:
                pool[sym] = sym
        try:
            from app.market_pulse.us_index_constituents import US_INDEX_ETFS
            for sym in US_INDEX_ETFS:
                if sym not in pool:
                    pool[sym] = f"{sym} (Index ETF)"
        except Exception:
            pass
        return pool

    if asset_class == "crypto":
        pool.update(CRYPTO_NAME_LABELS)
        try:
            from app.market_pulse.ticker_utils import get_coindcx_ticker_list
            for item in get_coindcx_ticker_list():
                sym = item["symbol"] if isinstance(item, dict) else item
                if sym not in pool:
                    base = sym.replace("B-", "").replace("USDT", "")
                    pool[sym] = f"{base}-USDT"
        except Exception:
            pass
        return pool

    return pool


def investigation_ticker_options(asset_class: str, query: str = "", *, limit: int = 100) -> list[str]:
    """Filtered symbol list for multiselect (sorted by label)."""
    pool = investigation_ticker_pool(asset_class)
    q = (query or "").strip().upper()
    items = list(pool.items())
    if q:
        items = [
            (sym, label) for sym, label in items
            if q in sym.upper() or q in label.upper()
        ]
    items.sort(key=lambda x: x[1].upper())
    seen: set[str] = set()
    out: list[str] = []
    for sym, _ in items:
        if sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
        if len(out) >= limit:
            break
    return out


def investigation_resolve_symbols(asset_class: str, raw: list[str]) -> list[dict[str, str]]:
    """Resolve user input to data symbols with display names."""
    if asset_class == "commodity":
        out_syms: list[str] = []
        for item in raw:
            t = (item or "").strip()
            if not t:
                continue
            meta = _commodity_meta_for_ticker(t)
            if meta:
                out_syms.append(meta["yf"])
            elif "=" in t or t.upper().endswith("F"):
                out_syms.append(t.upper())
            else:
                out_syms.append(t.upper())
        symbols = list(dict.fromkeys(out_syms))
    else:
        from app.market_pulse.buy_sell_advisor_engine import resolve_tickers
        symbols = resolve_tickers(asset_class, raw)
    return [
        {"symbol": sym, "display_name": ticker_display_name(sym, asset_class)}
        for sym in symbols
    ]


def _search_terms(ticker: str, asset_class: str) -> list[str]:
    t = ticker.upper().replace("B-", "").replace("USDT", "").replace("_", "")
    terms = {ticker.upper(), t}
    if asset_class == "crypto":
        base = ticker.replace("B-", "").replace("USDT", "").replace("_", "")
        terms.update({base, f"{base}USDT", f"{base}-USDT", base[:3]})
    elif asset_class == "commodity":
        meta = _commodity_meta_for_ticker(ticker)
        if meta:
            terms.update({meta["sym"], meta["yf"].upper(), meta["name"].upper()})
            for word in meta["name"].upper().split():
                if len(word) >= 3:
                    terms.add(word)
        sym = ticker.upper().replace("=F", "")
        if sym:
            terms.add(sym)
    else:
        sym = ticker.upper().replace(".NS", "").replace(".US", "")
        terms.add(sym)
    for alias in _TICKER_ALIASES.get(ticker.upper(), []):
        terms.add(alias.upper())
    if asset_class == "commodity":
        meta = _commodity_meta_for_ticker(ticker)
        if meta:
            for alias in _TICKER_ALIASES.get(meta["yf"].upper(), []):
                terms.add(alias.upper())
    return [x for x in terms if len(x) >= 2]


def _article_matches(article: dict, terms: list[str]) -> bool:
    blob = f"{article.get('title', '')} {article.get('summary', '')}".upper()
    for term in terms:
        if len(term) >= 4 and term in blob:
            return True
        if len(term) <= 5 and re.search(rf"\b{re.escape(term)}\b", blob):
            return True
    return False


def _google_news_feed(query: str, *, hl: str = "en", gl: str = "US", ceid: str = "US:en") -> tuple[str, str, int]:
    q = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
    return (f"Google News — {query[:40]}", url, 15)


def _feeds_for_asset(asset_class: str, ticker: str) -> list[tuple[str, str, int]]:
    feeds: list[tuple[str, str, int]] = []
    if asset_class == "crypto":
        feeds.extend(CRYPTO_NEWS_FEEDS)
        feeds.extend(GLOBAL_NEWS_FEEDS[:3])
        base = ticker.replace("B-", "").replace("USDT", "").replace("_", "")
        feeds.append(_google_news_feed(f"{base} crypto", hl="en", gl="US", ceid="US:en"))
        feeds.append(_google_news_feed(f"{base} bitcoin" if base == "BTC" else f"{base} cryptocurrency"))
    elif asset_class == "india":
        feeds.extend(INDIA_NEWS_FEEDS)
        feeds.extend(INDIA_EXTRA_FEEDS)
        sym = ticker.upper().replace(".NS", "")
        feeds.append(_google_news_feed(f"{sym} NSE stock", hl="en-IN", gl="IN", ceid="IN:en"))
        feeds.append(_google_news_feed(f"{sym} share price India", hl="en-IN", gl="IN", ceid="IN:en"))
    elif asset_class == "commodity":
        feeds.extend(COMMODITY_NEWS_FEEDS)
        feeds.extend(GLOBAL_NEWS_FEEDS[:2])
        meta = _commodity_meta_for_ticker(ticker)
        name = meta["name"] if meta else ticker.replace("=F", "")
        feeds.append(_google_news_feed(f"{name} futures commodity price"))
        feeds.append(_google_news_feed(f"{name} commodity outlook OPEC supply"))
        feeds.append(_google_news_feed(f"{name} commodity analyst forecast"))
    else:
        feeds.extend(US_NEWS_FEEDS)
        feeds.extend(GLOBAL_NEWS_FEEDS[:2])
        sym = ticker.upper().replace(".US", "")
        feeds.append(_google_news_feed(f"{sym} stock", hl="en-US", gl="US", ceid="US:en"))
        feeds.append(_google_news_feed(f"{sym} stock marketwatch OR bloomberg", hl="en-US", gl="US", ceid="US:en"))
    return feeds


def fetch_ticker_news(ticker: str, asset_class: str, *, max_articles: int = 25) -> list[dict]:
    """Aggregate RSS + Google News headlines mentioning the ticker."""
    terms = _search_terms(ticker, asset_class)
    feeds = _feeds_for_asset(asset_class, ticker)
    raw = _collect_rss_articles(feeds, max_hours=120, max_total=120)
    matched = [a for a in raw if _article_matches(a, terms)]
    if len(matched) < 5:
        for art in raw:
            if art not in matched:
                matched.append(art)
            if len(matched) >= max_articles:
                break
    for art in matched:
        art["ticker"] = ticker
    return matched[:max_articles]


def _analyst_google_feeds(ticker: str, asset_class: str) -> list[tuple[str, str, int]]:
    """Ticker-specific Google News queries for brokerage / analyst coverage."""
    if asset_class == "crypto":
        base = ticker.replace("B-", "").replace("USDT", "").replace("_", "")
        queries = [
            f"{base} crypto price target analyst",
            f"{base} upgrade downgrade rating",
        ]
        hl, gl, ceid = "en", "US", "US:en"
    elif asset_class == "india":
        sym = ticker.upper().replace(".NS", "")
        queries = [
            f"{sym} upgrade downgrade price target brokerage",
            f"{sym} analyst rating target NSE",
        ]
        hl, gl, ceid = "en-IN", "IN", "IN:en"
    elif asset_class == "commodity":
        meta = _commodity_meta_for_ticker(ticker)
        name = meta["name"] if meta else ticker.replace("=F", " commodity")
        queries = [
            f"{name} commodity price target forecast",
            f"{name} futures analyst outlook upgrade downgrade",
        ]
        hl, gl, ceid = "en-US", "US", "US:en"
    else:
        sym = ticker.upper().replace(".US", "")
        queries = [
            f"{sym} analyst upgrade downgrade price target",
            f"{sym} price target rating reiterate",
        ]
        hl, gl, ceid = "en-US", "US", "US:en"

    feeds: list[tuple[str, str, int]] = []
    for q in queries:
        enc = urllib.parse.quote_plus(q)
        feeds.append((
            f"Google Analyst — {q[:35]}",
            f"https://news.google.com/rss/search?q={enc}&hl={hl}&gl={gl}&ceid={ceid}",
            12,
        ))
    return feeds


def fetch_ticker_analyst_calls(
    ticker: str,
    asset_class: str,
    terms: list[str],
    pool: list[dict],
    *,
    max_calls: int = 20,
) -> tuple[list[dict], dict]:
    """Brokerage recos, upgrades/downgrades, and price targets for one ticker."""
    matched = filter_analyst_calls_for_ticker(pool, terms, max_calls=50)

    extra_raw = _collect_rss_articles(
        _analyst_google_feeds(ticker, asset_class),
        max_hours=14 * 24,
        max_total=25,
    )
    seen_titles: set[str] = {re.sub(r"\W+", "", c.get("title", "").lower())[:100] for c in matched}
    for art in extra_raw:
        enriched = enrich_analyst_article(art)
        if not _article_matches(
            {"title": enriched.get("title", ""), "summary": enriched.get("summary", "")},
            terms,
        ):
            continue
        key = re.sub(r"\W+", "", enriched.get("title", "").lower())[:100]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        enriched["ticker"] = ticker
        matched.append(enriched)

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
    calls = matched[:max_calls]
    for c in calls:
        c["ticker"] = ticker
    return calls, summarize_analyst_consensus(calls)


def _rsi_zone(rsi: float) -> str:
    if rsi >= 70:
        return "Overbought"
    if rsi >= 60:
        return "Mildly overbought"
    if rsi <= 30:
        return "Oversold"
    if rsi <= 40:
        return "Mildly oversold"
    return "Neutral"


def _pct_change(df: pd.DataFrame, bars_back: int) -> float | None:
    if df is None or df.empty or len(df) <= bars_back:
        return None
    close = df["close"].astype(float)
    old = float(close.iloc[-1 - bars_back])
    new = float(close.iloc[-1])
    if old == 0:
        return None
    return round((new - old) / old * 100, 3)


def _compute_rsi(df: pd.DataFrame, period: int = 14) -> float | None:
    if df is None or df.empty or len(df) < period + 2:
        return None
    work = df.copy()
    work.columns = [str(c).lower() for c in work.columns]
    work = add_rsi(work, period)
    col = f"rsi_{period}"
    if col not in work.columns:
        return None
    val = float(work[col].iloc[-1])
    return round(val, 1) if pd.notna(val) else None


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    return out.dropna(subset=["close"], how="any")


def _fetch_bars(
    ticker: str,
    tf: str,
    market: str,
    groww_token: str,
    exchange: str,
    limit: int,
    cache: dict,
) -> pd.DataFrame:
    key = (ticker, tf)
    if key not in cache:
        try:
            cache[key] = _normalize_ohlc(
                fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit),
            )
        except Exception as exc:
            logger.debug("OHLC fetch failed %s %s: %s", ticker, tf, exc)
            cache[key] = pd.DataFrame()
    return cache[key]


def compute_price_windows(
    ticker: str,
    market: str,
    groww_token: str,
    exchange: str,
    cache: dict,
    *,
    is_crypto: bool,
) -> list[dict]:
    rows: list[dict] = []
    limits = {"1d": 30, "1h": 120, "15m": 120, "5m": 120, "1m": 120}
    for label, tf, bars in PRICE_WINDOWS:
        df = _fetch_bars(ticker, tf, market, groww_token, exchange, limits.get(tf, 100), cache)
        pct = _pct_change(df, bars)
        rsi = _compute_rsi(df)
        rows.append({
            "window": label,
            "timeframe": tf,
            "bars": bars,
            "change_pct": pct,
            "rsi": rsi,
            "rsi_zone": _rsi_zone(rsi) if rsi is not None else "—",
            "price": float(df["close"].iloc[-1]) if not df.empty else None,
        })
    return rows


def _compact_pa_profile(analysis: dict, tf: str) -> dict:
    """Slim Price Action snapshot for investigation UI and setup scoring."""
    adv = analysis.get("adv_indicators") or {}
    vwap = adv.get("vwap") or {}
    vol = analysis.get("volume") or adv.get("volume") or {}
    approaching = analysis.get("approaching") or {}
    setups = analysis.get("trade_setups") or []
    best = max(setups, key=lambda s: s.get("confidence", 0)) if setups else None
    smc = adv.get("smc") or {}

    verdict = "AVOID"
    if best and float(best.get("confidence", 0) or 0) >= 60:
        verdict = "BUY" if best.get("direction") == "LONG" else "SELL"
    elif approaching.get("count", 0) > 0:
        verdict = "WATCHLIST"

    return {
        "timeframe": tf,
        "overall_bias": analysis.get("overall_bias"),
        "bias_score": analysis.get("bias_score"),
        "trend": (analysis.get("trendlines") or {}).get("trend_direction"),
        "rsi": (analysis.get("rsi") or {}).get("current_rsi"),
        "rsi_zone": (analysis.get("rsi") or {}).get("zone"),
        "rsi_bull_div": (analysis.get("rsi") or {}).get("bullish_divergence"),
        "rsi_bear_div": (analysis.get("rsi") or {}).get("bearish_divergence"),
        "ema_stack": (analysis.get("ema") or {}).get("ema_stack"),
        "fib_golden": (analysis.get("fibonacci") or {}).get("price_in_golden_zone"),
        "vwap_position": vwap.get("position"),
        "vwap_distance_pct": vwap.get("distance_pct"),
        "volume_ratio": vol.get("ratio"),
        "volume_label": vol.get("label"),
        "volume_trend": vol.get("trend"),
        "mfi": vol.get("mfi"),
        "smc_bull_ob": len(smc.get("ob_bullish") or []),
        "smc_bear_ob": len(smc.get("ob_bearish") or []),
        "smc_bull_fvg": len(smc.get("fvg_bullish") or []),
        "smc_bear_fvg": len(smc.get("fvg_bearish") or []),
        "approaching_alerts": approaching.get("alerts") or [],
        "approaching_count": approaching.get("count", 0),
        "verdict": verdict,
        "best_setup": best,
        "setup_count": len(setups),
        "candle_pattern_count": len(analysis.get("candlestick_patterns") or []),
        "chart_pattern_count": len(analysis.get("chart_patterns") or []),
    }


def compute_price_action_profile(
    ticker: str,
    market: str,
    groww_token: str,
    exchange: str,
    cache: dict,
    *,
    is_crypto: bool,
) -> dict:
    """Run Price Action engine on primary intraday + daily bars."""
    from app.market_pulse.price_action import run_full_analysis

    limits = {"15m": 220, "1d": 120}
    by_tf: dict[str, dict] = {}
    for tf in PA_ANALYSIS_TFS:
        df = _fetch_bars(
            ticker, tf, market, groww_token, exchange, limits.get(tf, 200), cache,
        )
        if df.empty or len(df) < 50:
            by_tf[tf] = {"insufficient": True, "timeframe": tf}
            continue
        try:
            analysis = run_full_analysis(df, is_crypto=is_crypto)
            by_tf[tf] = _compact_pa_profile(analysis, tf)
        except Exception as exc:
            logger.warning("PA analysis failed %s %s: %s", ticker, tf, exc)
            by_tf[tf] = {"insufficient": True, "timeframe": tf, "error": str(exc)[:120]}

    primary = by_tf.get(SR_PRIMARY_TF) or by_tf.get("1d") or {}
    return {"primary_tf": SR_PRIMARY_TF, "by_tf": by_tf, "primary": primary}


def _sr_from_wssr(df: pd.DataFrame, tf: str, is_crypto: bool) -> dict:
    if df.empty or len(df) < 45:
        return {"insufficient": True, "timeframe": tf}
    analysis = analyze_weak_strong_sr(df, chart_tf=tf, is_crypto=is_crypto)
    ctx = analysis.get("sr_context") or {}
    ns = ctx.get("nearest_support") or {}
    nr = ctx.get("nearest_resistance") or {}
    br = analyze_sr_breakout(df, timeframe=tf, lookback=min(40, max(20, len(df) // 3)))
    breakout_pct = breakdown_pct = 50.0
    if not br.get("insufficient"):
        dist_r = abs(br.get("dist_resistance_pct") or 5)
        dist_s = abs(br.get("dist_support_pct") or 5)
        mom = 1 if (br.get("bias") == "BULLISH") else (-1 if br.get("bias") == "BEARISH" else 0)
        breakout_pct = min(92, max(8, 55 - dist_r * 4 + mom * 12 + (br.get("confidence", 0) - 50) * 0.2))
        breakdown_pct = min(92, max(8, 55 - dist_s * 4 - mom * 12 + (br.get("confidence", 0) - 50) * 0.2))
        if br.get("event") == "BREAKOUT":
            breakout_pct = max(breakout_pct, float(br.get("confidence", 60)))
        elif br.get("event") == "BREAKDOWN":
            breakdown_pct = max(breakdown_pct, float(br.get("confidence", 60)))
    return {
        "timeframe": tf,
        "support": ns.get("price"),
        "support_strength": ns.get("strength", "—"),
        "support_touches": ns.get("touches"),
        "resistance": nr.get("price"),
        "resistance_strength": nr.get("strength", "—"),
        "resistance_touches": nr.get("touches"),
        "support_dist_pct": ctx.get("support_dist_pct"),
        "resistance_dist_pct": ctx.get("resistance_dist_pct"),
        "breakout_chance_pct": round(breakout_pct, 1),
        "breakdown_chance_pct": round(breakdown_pct, 1),
        "sr_bias": ctx.get("sr_bias") or analysis.get("sr_bias", "—"),
        "verdict": analysis.get("verdict", "—"),
        "confidence": analysis.get("confidence", 0),
        "event": br.get("event", "RANGE"),
        "event_label": br.get("event_label", ""),
    }


def compute_sr_levels(
    ticker: str,
    market: str,
    groww_token: str,
    exchange: str,
    cache: dict,
    *,
    is_crypto: bool,
) -> dict:
    by_tf: dict[str, dict] = {}
    limits = {"5m": 200, "15m": 200, "1h": 150, "1d": 60}
    for tf in SR_LOOKBACK_TFS:
        df = _fetch_bars(ticker, tf, market, groww_token, exchange, limits.get(tf, 150), cache)
        by_tf[tf] = _sr_from_wssr(df, tf, is_crypto)
    primary = by_tf.get(SR_PRIMARY_TF) or by_tf.get("5m") or {}
    return {"primary_tf": SR_PRIMARY_TF, "by_tf": by_tf, "immediate": primary}


def _news_sentiment_score(news: list[dict]) -> dict[str, Any]:
    """Score headline sentiment -100 (bear) to +100 (bull)."""
    bull = bear = 0
    for art in news[:20]:
        blob = f"{art.get('title', '')} {art.get('summary', '')}".lower()
        bull += sum(1 for w in _BULL_NEWS_WORDS if w in blob)
        bear += sum(1 for w in _BEAR_NEWS_WORDS if w in blob)
    total = bull + bear
    if total == 0:
        return {"score": 0, "label": "NEUTRAL", "bull_hits": 0, "bear_hits": 0}
    score = round((bull - bear) / max(total, 1) * 100)
    if score >= 25:
        label = "BULLISH"
    elif score <= -25:
        label = "BEARISH"
    else:
        label = "NEUTRAL"
    return {"score": score, "label": label, "bull_hits": bull, "bear_hits": bear}


def _analyst_sentiment_score(consensus: dict) -> dict[str, Any]:
    buy = int(consensus.get("buy") or 0)
    sell = int(consensus.get("sell") or 0)
    hold = int(consensus.get("hold") or 0)
    upgrades = int(consensus.get("upgrades") or 0)
    downgrades = int(consensus.get("downgrades") or 0)
    net = buy - sell + (upgrades - downgrades) * 0.5
    total = buy + sell + hold + 1
    score = round(net / total * 100)
    score = max(-100, min(100, score))
    if consensus.get("consensus") in ("BULLISH", "BEARISH", "NEUTRAL"):
        label = consensus["consensus"]
    elif score >= 20:
        label = "BULLISH"
    elif score <= -20:
        label = "BEARISH"
    else:
        label = "NEUTRAL"
    return {"score": score, "label": label, "buy": buy, "sell": sell}


def _sl_tp_for_setup(
    direction: str,
    price: float | None,
    imm: dict,
    timeframe: str,
    style: str,
    asset_class: str,
) -> tuple[float, float]:
    """Derive SL%/TP% from S/R distance with timeframe floors."""
    dsl, dtp = default_sl_tp_for_timeframe(timeframe)
    sl, tp = dsl, dtp
    if not price or price <= 0:
        return sl, tp

    sup = imm.get("support")
    res = imm.get("resistance")
    dir_u = direction.upper()

    if dir_u in ("LONG", "BUY") and sup:
        dist_sl = (price - float(sup)) / price * 100
        sl = max(dsl * 0.85, min(4.5, dist_sl * 1.15 + 0.15))
        if res:
            dist_tp = (float(res) - price) / price * 100
            tp = max(dtp, min(15.0, dist_tp * 0.92))
    elif dir_u in ("SHORT", "SELL") and res:
        dist_sl = (float(res) - price) / price * 100
        sl = max(dsl * 0.85, min(4.5, dist_sl * 1.15 + 0.15))
        if sup:
            dist_tp = (price - float(sup)) / price * 100
            tp = max(dtp, min(15.0, dist_tp * 0.92))

    if style == "scalp":
        sl = min(sl, dsl * 1.25)
        tp = max(tp, sl * 1.35)
        tp = min(tp, dtp * 1.3)
    else:
        tp = max(tp, sl * 1.5)

    if asset_class == "crypto":
        sl = round(sl * 1.08, 2)
    elif asset_class == "commodity":
        sl = round(sl * 1.12, 2)
        tp = round(tp * 1.1, 2)
    else:
        sl = round(sl, 2)
        tp = round(tp, 2)
    return sl, tp


def _mtf_bias_score(by_tf: dict) -> tuple[int, int, str]:
    bull = bear = 0
    for block in by_tf.values():
        if block.get("insufficient"):
            continue
        bias = str(block.get("sr_bias") or block.get("verdict") or "").upper()
        event = str(block.get("event") or "").upper()
        if "BULL" in bias or bias in ("BUY", "WATCH_BUY") or event == "BREAKOUT":
            bull += 1
        elif "BEAR" in bias or bias in ("SELL",) or event == "BREAKDOWN":
            bear += 1
    if bull > bear:
        return bull, bear, "BULLISH"
    if bear > bull:
        return bull, bear, "BEARISH"
    return bull, bear, "NEUTRAL"


def _make_setup(
    *,
    name: str,
    direction: str,
    style: str,
    timeframe: str,
    confidence: float,
    detail: str,
    reasons: list[str],
    forming: bool,
    price: float | None,
    imm: dict,
    asset_class: str,
) -> dict:
    sl, tp = _sl_tp_for_setup(direction, price, imm, timeframe, style, asset_class)
    conf = max(18.0, min(92.0, confidence))
    dir_u = direction.upper()
    take = forming and conf >= 56 and dir_u in ("LONG", "SHORT", "BUY", "SELL")
    if dir_u == "BUY":
        dir_u = "LONG"
    elif dir_u == "SELL":
        dir_u = "SHORT"
    plan = make_trade_plan(
        direction=dir_u if take else "—",
        timeframe=timeframe.split("–")[0].split("/")[0].strip() or "15m",
        stop_loss_pct=sl,
        take_profit_pct=tp,
        confidence_pct=conf,
        style=style if style in ("scalp", "swing") else "swing",
        exit_rule=detail[:200],
    )
    rr = round(tp / sl, 2) if sl > 0 else None
    return {
        "name": name,
        "direction": dir_u if dir_u in ("LONG", "SHORT") else "WAIT",
        "take_trade": take,
        "forming": forming,
        "confidence_pct": round(conf, 1),
        "sl_pct": sl,
        "tp_pct": tp,
        "rr_ratio": rr,
        "timeframe": timeframe,
        "style": style,
        "detail": detail,
        "reasons": reasons[:6],
        "trade_plan": plan,
        "invalidation": (
            f"Close {'below support' if dir_u == 'LONG' else 'above resistance' if dir_u == 'SHORT' else 'beyond range'} "
            f"or SL -{sl:.2f}% hit."
        ),
    }


def build_trade_setups(
    price_windows: list[dict],
    sr: dict,
    *,
    asset_class: str,
    ticker: str = "",
    news: list[dict] | None = None,
    analyst_consensus: dict | None = None,
    current_price: float | None = None,
    price_action: dict | None = None,
) -> dict[str, Any]:
    """World-class confluence engine — TA + Price Action + news + analysts → ranked setups."""
    setups: list[dict] = []
    by_tf = sr.get("by_tf") or {}
    imm = sr.get("immediate") or {}
    pa_primary = (price_action or {}).get("primary") or {}
    if pa_primary.get("insufficient"):
        pa_primary = {}
    news_sent = _news_sentiment_score(news or [])
    anal_sent = _analyst_sentiment_score(analyst_consensus or {})
    bull_tf, bear_tf, mtf_label = _mtf_bias_score(by_tf)
    price = current_price
    if price is None:
        for w in price_windows:
            if w.get("price") is not None:
                price = w["price"]
                break

    def add(**kwargs) -> None:
        setups.append(_make_setup(price=price, imm=imm, asset_class=asset_class, **kwargs))

    # ── 0. Price Action multi-indicator (same engine as PA screener) ──
    best_pa = pa_primary.get("best_setup")
    if best_pa and float(best_pa.get("confidence", 0) or 0) >= 58:
        pa_dir = best_pa.get("direction", "LONG")
        conf = float(best_pa.get("confidence", 50))
        if pa_dir == "LONG" and news_sent["label"] == "BULLISH":
            conf += 6
        elif pa_dir == "SHORT" and news_sent["label"] == "BEARISH":
            conf += 6
        if pa_dir == "LONG" and anal_sent["label"] == "BULLISH":
            conf += 5
        elif pa_dir == "SHORT" and anal_sent["label"] == "BEARISH":
            conf += 5
        if pa_primary.get("volume_label") in ("VOLUME SPIKE", "HIGH VOLUME EXPANSION"):
            conf += 4
        if pa_primary.get("fib_golden"):
            conf += 3
        pa_signals = best_pa.get("signals") or []
        add(
            name="Price Action multi-indicator setup",
            direction=pa_dir,
            style=(best_pa.get("style") or "swing").lower(),
            timeframe=pa_primary.get("timeframe", SR_PRIMARY_TF),
            confidence=conf,
            forming=conf >= 58,
            detail=(
                f"PA engine {pa_dir} — {pa_primary.get('overall_bias')} bias · "
                f"engine conf {best_pa.get('confidence')}%"
            ),
            reasons=[
                f"Trend {pa_primary.get('trend')} · RSI {pa_primary.get('rsi')} ({pa_primary.get('rsi_zone')})",
                f"EMA {pa_primary.get('ema_stack')} · VWAP {str(pa_primary.get('vwap_position', '')).split('(')[0].strip()}",
                f"RVOL {pa_primary.get('volume_ratio')}× ({pa_primary.get('volume_label', 'NORMAL')})",
                *pa_signals[:3],
            ],
        )

    if pa_primary.get("approaching_count", 0) > 0 and not (
        best_pa and float(best_pa.get("confidence", 0) or 0) >= 65
    ):
        alerts = pa_primary.get("approaching_alerts") or []
        blob = " ".join(alerts).lower()
        appr_dir = "LONG"
        if any(k in blob for k in ("resistance", "bearish", "loss", "breakdown")):
            appr_dir = "SHORT"
        elif any(k in blob for k in ("support", "reclaim", "bullish")):
            appr_dir = "LONG"
        conf = 52 + min(14, int(pa_primary.get("approaching_count", 0)) * 4)
        if pa_primary.get("fib_golden"):
            conf += 5
        if pa_primary.get("volume_label") in ("VOLUME SPIKE", "HIGH VOLUME EXPANSION"):
            conf += 4
        add(
            name="Price Action approaching setup (WATCHLIST)",
            direction=appr_dir,
            style="scalp" if asset_class in ("crypto", "india") else "swing",
            timeframe=SR_PRIMARY_TF,
            confidence=conf,
            forming=False,
            detail=alerts[0] if alerts else "Setup approaching key S/R or VWAP level.",
            reasons=alerts[:4],
        )

    # ── 1. Institutional breakout (S/R + event) ──
    if imm.get("event") == "BREAKOUT":
        conf = 48 + float(imm.get("breakout_chance_pct") or 50) * 0.35
        conf += bull_tf * 5
        if news_sent["label"] == "BULLISH":
            conf += 8
        if anal_sent["label"] == "BULLISH":
            conf += 7
        add(
            name="Institutional resistance breakout",
            direction="LONG",
            style="swing" if asset_class in ("us", "india", "commodity") else "scalp",
            timeframe=imm.get("timeframe", "15m"),
            confidence=conf,
            forming=conf >= 55,
            detail=imm.get("event_label") or "Breakout above resistance with follow-through.",
            reasons=[
                f"Breakout event on {imm.get('timeframe', '15m')} · breakout odds {imm.get('breakout_chance_pct')}%",
                f"MTF bias {mtf_label} ({bull_tf} bull / {bear_tf} bear legs)",
                f"News sentiment {news_sent['label']} ({news_sent['score']:+d})",
            ],
        )

    if imm.get("event") == "BREAKDOWN":
        conf = 48 + float(imm.get("breakdown_chance_pct") or 50) * 0.35
        conf += bear_tf * 5
        if news_sent["label"] == "BEARISH":
            conf += 8
        if anal_sent["label"] == "BEARISH":
            conf += 7
        add(
            name="Institutional support breakdown",
            direction="SHORT",
            style="swing",
            timeframe=imm.get("timeframe", "15m"),
            confidence=conf,
            forming=conf >= 55,
            detail="Breakdown below support — trend continuation short.",
            reasons=[
                f"Breakdown on {imm.get('timeframe')} · breakdown odds {imm.get('breakdown_chance_pct')}%",
                f"MTF {mtf_label}",
                f"Analyst tone {anal_sent['label']}",
            ],
        )

    if imm.get("event") == "FAKEOUT":
        fade_dir = "SHORT" if imm.get("verdict", "").upper().find("SELL") >= 0 else "LONG"
        conf = 52 + float(imm.get("confidence") or 45) * 0.3
        add(
            name="Liquidity fakeout fade (SMC-style)",
            direction=fade_dir,
            style="scalp",
            timeframe=imm.get("timeframe", "15m"),
            confidence=conf,
            forming=conf >= 58,
            detail="False break rejected — fade back into range (institutional trap).",
            reasons=["Fakeout detected at key S/R", "Stop beyond sweep wick / failed break level"],
        )

    if imm.get("event") == "REVERSAL":
        rev_dir = "LONG" if "BULL" in str(imm.get("sr_bias", "")).upper() else "SHORT"
        conf = 50 + float(imm.get("confidence") or 40) * 0.35
        if news_sent["score"] * (1 if rev_dir == "LONG" else -1) > 15:
            conf += 10
        add(
            name="S/R reversal (rejection candle)",
            direction=rev_dir,
            style="scalp" if asset_class == "crypto" else "swing",
            timeframe=imm.get("timeframe", "15m"),
            confidence=conf,
            forming=conf >= 56,
            detail="Reversal at support/resistance with wick rejection.",
            reasons=[f"Reversal event · S/R bias {imm.get('sr_bias')}"],
        )

    # ── 2. Mean reversion at strong S/R ──
    oversold = any(w.get("rsi_zone", "").startswith("Oversold") for w in price_windows[:4])
    overbought = any(w.get("rsi_zone", "").startswith("Overbought") for w in price_windows[:4])
    if imm.get("support_strength") == "strong" and oversold:
        conf = 55 + float(imm.get("confidence") or 45) * 0.25
        if anal_sent["label"] != "BEARISH":
            conf += 6
        add(
            name="Strong support + oversold RSI (swing long)",
            direction="LONG",
            style="swing",
            timeframe="1d/15m",
            confidence=conf,
            forming=conf >= 58,
            detail="Institutional floor + RSI exhaustion — bounce swing.",
            reasons=["Strong support below", "Oversold on intraday/daily RSI", f"News {news_sent['label']}"],
        )
    if imm.get("resistance_strength") == "strong" and overbought:
        conf = 55 + float(imm.get("confidence") or 45) * 0.25
        add(
            name="Strong resistance + overbought RSI (fade short)",
            direction="SHORT",
            style="swing",
            timeframe="1d/15m",
            confidence=conf,
            forming=conf >= 58,
            detail="Heavy supply zone + RSI stretched — mean-reversion short.",
            reasons=["Strong resistance overhead", "Overbought RSI cluster"],
        )

    # ── 3. MTF trend follow ──
    if bull_tf >= 3:
        conf = 42 + bull_tf * 11
        if news_sent["label"] == "BULLISH":
            conf += 10
        if anal_sent["label"] == "BULLISH":
            conf += 8
        add(
            name="Multi-timeframe bullish alignment",
            direction="LONG",
            style="swing",
            timeframe="MTF",
            confidence=conf,
            forming=conf >= 60,
            detail=f"{bull_tf}/4 timeframes bullish — trade pullbacks to support.",
            reasons=[f"MTF S/R alignment · news {news_sent['label']} · analysts {anal_sent['label']}"],
        )
    if bear_tf >= 3:
        conf = 42 + bear_tf * 11
        if news_sent["label"] == "BEARISH":
            conf += 10
        add(
            name="Multi-timeframe bearish alignment",
            direction="SHORT",
            style="swing",
            timeframe="MTF",
            confidence=conf,
            forming=conf >= 60,
            detail=f"{bear_tf}/4 timeframes bearish — fade rallies to resistance.",
            reasons=[f"MTF bearish confluence"],
        )

    # ── 4. News + analyst catalyst ──
    if abs(news_sent["score"]) >= 35 or anal_sent["label"] in ("BULLISH", "BEARISH"):
        cat_dir = "LONG" if news_sent["score"] >= 0 and anal_sent["label"] != "BEARISH" else "SHORT"
        if anal_sent["label"] == "BEARISH" and news_sent["score"] <= 0:
            cat_dir = "SHORT"
        elif anal_sent["label"] == "BULLISH" and news_sent["score"] >= 0:
            cat_dir = "LONG"
        short_m = next((w for w in price_windows if w["window"] == "1 hr"), None)
        mom = short_m.get("change_pct") if short_m else 0
        aligned = (cat_dir == "LONG" and (mom or 0) >= 0) or (cat_dir == "SHORT" and (mom or 0) <= 0)
        conf = 45 + abs(news_sent["score"]) * 0.2 + abs(anal_sent["score"]) * 0.15
        if aligned:
            conf += 12
        if bull_tf >= 2 and cat_dir == "LONG":
            conf += 6
        if bear_tf >= 2 and cat_dir == "SHORT":
            conf += 6
        add(
            name="News + analyst catalyst flow",
            direction=cat_dir,
            style="swing",
            timeframe="1h/1d",
            confidence=conf,
            forming=conf >= 58 and aligned,
            detail=f"Headline tone {news_sent['label']} + brokerage {anal_sent['label']} aligned with tape.",
            reasons=[
                f"News score {news_sent['score']:+d} ({news_sent['bull_hits']} bull / {news_sent['bear_hits']} bear hits)",
                f"Analyst buys/sells {anal_sent.get('buy', 0)}/{anal_sent.get('sell', 0)}",
            ],
        )

    # ── 5. Intraday momentum scalp ──
    short_moves = [w for w in price_windows if w["window"] in ("5 min", "15 min", "1 hr")]
    if short_moves and asset_class in ("crypto", "india"):
        avg_short = sum(w["change_pct"] or 0 for w in short_moves) / len(short_moves)
        rsi_vals = [w["rsi"] for w in short_moves if w["rsi"] is not None]
        avg_rsi = sum(rsi_vals) / len(rsi_vals) if rsi_vals else 50
        if abs(avg_short) > 0.12 and 38 < avg_rsi < 62:
            scalp_dir = "LONG" if avg_short > 0 else "SHORT"
            conf = 48 + abs(avg_short) * 12
            add(
                name="Intraday momentum scalp (VWAP/EMA continuation)",
                direction=scalp_dir,
                style="scalp",
                timeframe="5m–15m",
                confidence=conf,
                forming=conf >= 57,
                detail=f"Short-window drift {avg_short:+.2f}% · RSI {avg_rsi:.0f} — continuation scalp.",
                reasons=["Momentum across 5m/15m/1h windows", "RSI not exhausted"],
            )

    # ── 6. Commodity macro range ──
    if asset_class == "commodity" and imm.get("event") in ("RANGE", "REVERSAL"):
        meta = _commodity_meta_for_ticker(ticker)
        name = meta["name"] if meta else "Commodity"
        bias = str(imm.get("sr_bias") or "NEUTRAL").upper()
        dir_guess = "LONG" if "BULL" in bias or bias == "BUY" else "SHORT" if "BEAR" in bias or bias == "SELL" else "WAIT"
        if dir_guess != "WAIT":
            conf = 50 + float(imm.get("confidence") or 40) * 0.3
            if news_sent["label"] in ("BULLISH", "BEARISH"):
                conf += 8
            add(
                name=f"{name} macro range break",
                direction=dir_guess,
                style="swing",
                timeframe="4h/1d",
                confidence=conf,
                forming=conf >= 56,
                detail="Futures coiling at S/R — macro headline catalyst may trigger range break.",
                reasons=["Commodity futures S/R compression", f"News {news_sent['label']}"],
            )

    # PA bias nudge on existing rule-based setups
    pa_bias = str(pa_primary.get("overall_bias") or "").upper()
    for s in setups:
        d = s.get("direction")
        if d == "LONG" and ("BULL" in pa_bias):
            s["confidence_pct"] = min(92.0, float(s["confidence_pct"]) + 3)
        elif d == "SHORT" and ("BEAR" in pa_bias):
            s["confidence_pct"] = min(92.0, float(s["confidence_pct"]) + 3)

    if not setups:
        dsl, dtp = default_sl_tp_for_timeframe("15m")
        setups.append(_make_setup(
            name="No high-probability edge",
            direction="WAIT",
            style="—",
            timeframe="—",
            confidence=28,
            forming=False,
            detail="Wait for TA + news + analyst confluence before risking capital.",
            reasons=["Insufficient alignment across engines"],
            price=price,
            imm=imm,
            asset_class=asset_class,
        ))

    setups.sort(key=lambda s: (-int(s.get("take_trade")), -s.get("confidence_pct", 0)))
    primary = setups[0]
    strategies = [
        {
            "name": s["name"],
            "forming": s.get("forming", False),
            "take_trade": s.get("take_trade", False),
            "direction": s.get("direction"),
            "confidence_pct": s.get("confidence_pct"),
            "sl_pct": s.get("sl_pct"),
            "tp_pct": s.get("tp_pct"),
            "rr_ratio": s.get("rr_ratio"),
            "timeframe": s.get("timeframe"),
            "style": s.get("style"),
            "detail": s.get("detail"),
            "reasons": s.get("reasons", []),
        }
        for s in setups[:6]
    ]
    return {
        "primary": primary,
        "setups": setups[:5],
        "strategies": strategies,
        "news_sentiment": news_sent,
        "analyst_sentiment": anal_sent,
        "mtf_label": mtf_label,
        "pa_verdict": pa_primary.get("verdict"),
    }


def _build_suggested_trades(
    setup_bundle: dict,
    price_action: dict | None = None,
) -> list[dict]:
    """Ranked trade ideas with confidence %, SL %, and TP % for investigation UI."""
    trades: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _push(raw: dict) -> None:
        name = str(raw.get("name") or "Setup")
        direction = raw.get("direction", "WAIT")
        if direction == "BUY":
            direction = "LONG"
        elif direction == "SELL":
            direction = "SHORT"
        key = (name, str(direction))
        if key in seen:
            return
        seen.add(key)

        conf = float(raw.get("confidence_pct") or raw.get("confidence") or 0)
        take = bool(raw.get("take_trade"))
        forming = bool(raw.get("forming"))
        if take and direction in ("LONG", "SHORT"):
            status = "TAKE"
        elif forming or conf >= 52 or direction in ("LONG", "SHORT"):
            status = "WATCH"
        else:
            status = "MONITOR"

        sl = float(raw.get("sl_pct") or 0)
        tp = float(raw.get("tp_pct") or raw.get("tp1_pct") or 0)
        rr = raw.get("rr_ratio") or raw.get("rr_ratio_1")
        if rr is not None:
            try:
                rr = round(float(rr), 2)
            except (TypeError, ValueError):
                rr = None

        trades.append({
            "name": name,
            "direction": direction if direction in ("LONG", "SHORT") else "WAIT",
            "status": status,
            "confidence_pct": round(conf, 1),
            "sl_pct": round(sl, 2),
            "tp_pct": round(tp, 2),
            "rr_ratio": rr,
            "style": raw.get("style", "—"),
            "timeframe": raw.get("timeframe", "—"),
            "detail": raw.get("detail", ""),
            "reasons": list(raw.get("reasons") or [])[:4],
        })

    for s in setup_bundle.get("setups") or []:
        _push(s)

    pa = (price_action or {}).get("primary") or {}
    best_pa = pa.get("best_setup")
    if best_pa and not pa.get("insufficient"):
        pa_conf = float(best_pa.get("confidence") or 0)
        _push({
            "name": "Price Action engine (VWAP · RVOL · SMC)",
            "direction": best_pa.get("direction", "WAIT"),
            "confidence_pct": pa_conf,
            "sl_pct": best_pa.get("sl_pct"),
            "tp_pct": best_pa.get("tp1_pct"),
            "rr_ratio_1": best_pa.get("rr_ratio_1"),
            "style": (best_pa.get("style") or "swing").lower(),
            "timeframe": pa.get("timeframe", SR_PRIMARY_TF),
            "take_trade": pa_conf >= 62,
            "forming": pa_conf >= 52 or pa.get("verdict") == "WATCHLIST",
            "detail": f"PA bias {pa.get('overall_bias')} · verdict {pa.get('verdict', '—')}",
            "reasons": best_pa.get("signals", [])[:4],
        })

    rank = {"TAKE": 3, "WATCH": 2, "MONITOR": 1}
    trades.sort(
        key=lambda t: (rank.get(t["status"], 0), t["confidence_pct"]),
        reverse=True,
    )
    return trades[:8]


def detect_forming_strategies(
    price_windows: list[dict],
    sr: dict,
    *,
    asset_class: str,
    ticker: str = "",
    news: list[dict] | None = None,
    analyst_consensus: dict | None = None,
    current_price: float | None = None,
) -> list[dict]:
    """Backward-compatible wrapper — returns strategy list from build_trade_setups."""
    return build_trade_setups(
        price_windows, sr,
        asset_class=asset_class,
        ticker=ticker,
        news=news,
        analyst_consensus=analyst_consensus,
        current_price=current_price,
    )["strategies"]


def investigate_ticker(
    ticker: str,
    asset_class: str,
    *,
    market: str,
    exchange: str,
    groww_token: str = "",
    ohlc_cache: dict | None = None,
    analyst_pool: list[dict] | None = None,
) -> dict:
    """Full investigation payload for one ticker."""
    is_crypto = asset_class == "crypto"
    cache = ohlc_cache if ohlc_cache is not None else {}
    terms = _search_terms(ticker, asset_class)

    news = fetch_ticker_news(ticker, asset_class)
    pool = analyst_pool if analyst_pool is not None else fetch_analyst_calls_pool(asset_class)
    analyst_calls, analyst_consensus = fetch_ticker_analyst_calls(
        ticker, asset_class, terms, pool,
    )
    price_windows = compute_price_windows(
        ticker, market, groww_token, exchange, cache, is_crypto=is_crypto,
    )
    sr = compute_sr_levels(
        ticker, market, groww_token, exchange, cache, is_crypto=is_crypto,
    )
    price_action = compute_price_action_profile(
        ticker, market, groww_token, exchange, cache, is_crypto=is_crypto,
    )

    current_price = None
    for w in price_windows:
        if w.get("price") is not None:
            current_price = w["price"]
            break

    setup_bundle = build_trade_setups(
        price_windows,
        sr,
        asset_class=asset_class,
        ticker=ticker,
        news=news,
        analyst_consensus=analyst_consensus,
        current_price=current_price,
        price_action=price_action,
    )
    strategies = setup_bundle["strategies"]
    trade_setup = setup_bundle["primary"]
    suggested_trades = _build_suggested_trades(setup_bundle, price_action)

    return {
        "ticker": ticker,
        "display_name": ticker_display_name(ticker, asset_class),
        "asset_class": asset_class,
        "market": market,
        "current_price": current_price,
        "news": news,
        "news_count": len(news),
        "analyst_calls": analyst_calls,
        "analyst_consensus": analyst_consensus,
        "price_windows": price_windows,
        "sr": sr,
        "price_action": price_action,
        "strategies": strategies,
        "trade_setup": trade_setup,
        "trade_setups": setup_bundle.get("setups") or [],
        "suggested_trades": suggested_trades,
        "news_sentiment": setup_bundle.get("news_sentiment"),
        "analyst_sentiment": setup_bundle.get("analyst_sentiment"),
        "mtf_label": setup_bundle.get("mtf_label"),
        "pa_verdict": setup_bundle.get("pa_verdict"),
    }


def run_ticker_investigation(
    asset_class: str,
    tickers: list[str],
    *,
    groww_token: str = "",
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict | None:
    cfg = ASSET_CONFIG.get(asset_class)
    if not cfg or not tickers:
        return None

    market = str(cfg["market"])
    exchange = str(cfg.get("exchange") or "NSE")
    results: list[dict] = []
    cache: dict = {}
    analyst_pool = fetch_analyst_calls_pool(asset_class)
    total = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback((i + 0.2) / total, f"News & TA: {ticker}")
        try:
            results.append(
                investigate_ticker(
                    ticker,
                    asset_class,
                    market=market,
                    exchange=exchange,
                    groww_token=groww_token,
                    ohlc_cache=cache,
                    analyst_pool=analyst_pool,
                ),
            )
        except Exception as exc:
            logger.warning("Investigation failed %s: %s", ticker, exc)
            results.append({
                "ticker": ticker,
                "display_name": ticker_display_name(ticker, asset_class),
                "asset_class": asset_class,
                "market": market,
                "error": str(exc)[:200],
                "news": [],
                "analyst_calls": [],
                "analyst_consensus": summarize_analyst_consensus([]),
                "price_windows": [],
                "sr": {},
                "strategies": [],
                "trade_setup": None,
                "trade_setups": [],
            })
        if progress_callback:
            progress_callback((i + 1) / total, f"Done: {ticker}")

    return {
        "asset_class": asset_class,
        "market": market,
        "tickers": tickers,
        "results": results,
    }


def build_investigation_ai_prompt(result: dict, currency: str = "₹") -> str:
    """Build AI prompt for one ticker investigation."""
    lines = [
        "=== TICKER INVESTIGATION REPORT ===",
        f"Ticker: {result.get('display_name') or result.get('ticker')}",
        f"Symbol: {result.get('ticker')}",
        f"Market: {result.get('market')}",
        f"Price: {currency}{result.get('current_price', '—')}",
        "",
        "── PRICE MOVES & RSI ──",
    ]
    for w in result.get("price_windows") or []:
        ch = w.get("change_pct")
        ch_s = f"{ch:+.2f}%" if ch is not None else "—"
        lines.append(
            f"{w.get('window')} ({w.get('timeframe')}): {ch_s} · RSI {w.get('rsi', '—')} · {w.get('rsi_zone', '')}",
        )

    imm = (result.get("sr") or {}).get("immediate") or {}
    pa = (result.get("price_action") or {}).get("primary") or {}
    if not pa.get("insufficient"):
        lines.extend([
            "",
            "── PRICE ACTION (multi-indicator) ──",
            f"Bias: {pa.get('overall_bias', '—')} · Trend: {pa.get('trend', '—')} · "
            f"RSI {pa.get('rsi', '—')} ({pa.get('rsi_zone', '—')}) · EMA {pa.get('ema_stack', '—')}",
            f"VWAP: {pa.get('vwap_position', '—')} ({pa.get('vwap_distance_pct', '—')}%) · "
            f"RVOL {pa.get('volume_ratio', '—')}× ({pa.get('volume_label', '—')}) · MFI {pa.get('mfi', '—')}",
            f"Fib golden: {pa.get('fib_golden')} · SMC OB bull/bear {pa.get('smc_bull_ob')}/{pa.get('smc_bear_ob')} · "
            f"PA verdict: {pa.get('verdict', '—')}",
        ])
        if pa.get("approaching_alerts"):
            lines.append("Approaching: " + " | ".join(pa["approaching_alerts"][:4]))
        best_pa = pa.get("best_setup")
        if best_pa:
            lines.append(
                f"Best PA setup: {best_pa.get('direction')} conf {best_pa.get('confidence')}% · "
                f"SL {best_pa.get('sl_pct')}% TP {best_pa.get('tp1_pct')}%"
            )
    lines.extend([
        "",
        "── IMMEDIATE S/R (15m) ──",
        f"Support: {imm.get('support', '—')} ({imm.get('support_strength', '—')}, {imm.get('support_touches', '—')} touches)",
        f"Resistance: {imm.get('resistance', '—')} ({imm.get('resistance_strength', '—')})",
        f"Breakout chance: {imm.get('breakout_chance_pct', '—')}% · Breakdown chance: {imm.get('breakdown_chance_pct', '—')}%",
        f"Bias: {imm.get('sr_bias', '—')} · Event: {imm.get('event_label') or imm.get('event', '—')}",
        "",
        "── ANALYST CALLS & PRICE TARGETS ──",
    ])
    consensus = result.get("analyst_consensus") or {}
    lines.append(
        f"Consensus: {consensus.get('consensus', '—')} · "
        f"Buy {consensus.get('buy', 0)} / Sell {consensus.get('sell', 0)} / Hold {consensus.get('hold', 0)} · "
        f"Upgrades {consensus.get('upgrades', 0)} / Downgrades {consensus.get('downgrades', 0)} · "
        f"Latest target: {consensus.get('latest_target', '—')}",
    )
    for c in (result.get("analyst_calls") or [])[:10]:
        lines.append(
            f"• [{c.get('action')}] {c.get('call_type')} — {c.get('brokerage')} — "
            f"target {c.get('price_target')} (was {c.get('prior_target')}) — {c.get('title', '')[:100]}",
        )

    lines.extend([
        "",
        "── SUGGESTED TRADES (confidence · SL · TP) ──",
    ])
    for tr in result.get("suggested_trades") or []:
        lines.append(
            f"[{tr.get('status')}] {tr.get('direction')} · {tr.get('name')} · "
            f"conf {tr.get('confidence_pct')}% · SL -{tr.get('sl_pct')}% · "
            f"TP +{tr.get('tp_pct')}% · R:R {tr.get('rr_ratio', '—')} · "
            f"{tr.get('style')} · {tr.get('timeframe')}"
        )
        if tr.get("detail"):
            lines.append(f"  {tr['detail'][:120]}")

    lines.extend([
        "",
        "── RULE-BASED TRADE SETUP (primary) ──",
    ])
    primary = result.get("trade_setup") or {}
    if primary:
        take = primary.get("take_trade")
        lines.append(
            f"Verdict: {'TAKE ' + primary.get('direction', '') if take else 'NO TRADE / WAIT'} · "
            f"conf {primary.get('confidence_pct')}% · SL -{primary.get('sl_pct')}% · "
            f"TP +{primary.get('tp_pct')}% · R:R {primary.get('rr_ratio', '—')} · "
            f"{primary.get('style')} · {primary.get('timeframe')}",
        )
        lines.append(f"Setup: {primary.get('name')} — {primary.get('detail', '')}")
        for r in primary.get("reasons") or []:
            lines.append(f"  • {r}")
        ns = result.get("news_sentiment") or {}
        als = result.get("analyst_sentiment") or {}
        lines.append(
            f"News sentiment: {ns.get('label', '—')} ({ns.get('score', 0):+d}) · "
            f"Analyst tone: {als.get('label', '—')} · MTF: {result.get('mtf_label', '—')}",
        )

    lines.extend([
        "",
        "── ALL SETUP CANDIDATES ──",
    ])
    for s in result.get("strategies") or []:
        flag = "TAKE" if s.get("take_trade") else ("FORMING" if s.get("forming") else "watch")
        lines.append(
            f"[{flag}] {s.get('name')} · {s.get('direction', '—')} ({s.get('style')}) · "
            f"{s.get('timeframe')} · conf {s.get('confidence_pct')}% · "
            f"SL -{s.get('sl_pct')}% TP +{s.get('tp_pct')}% — {s.get('detail', '')}",
        )

    lines.extend(["", f"── NEWS ({result.get('news_count', 0)} headlines) ──"])
    for art in (result.get("news") or [])[:12]:
        lines.append(f"• [{art.get('source')}] {art.get('title')} ({art.get('published', '')})")
        if art.get("summary"):
            lines.append(f"  {art['summary'][:180]}")

    return "\n".join(lines)


def build_trade_setup_ai_prompt(result: dict, currency: str = "₹") -> str:
    """Focused AI prompt for trade setup synthesis (TA + news + analysts)."""
    base = build_investigation_ai_prompt(result, currency)
    primary = result.get("trade_setup") or {}
    extra = [
        "",
        "=== INSTRUCTION FOR AI TRADE SETUP ===",
        "Synthesize the data above into ONE primary trade plan.",
        "You may adjust SL%/TP%/confidence slightly if news/analysts strongly support or contradict the rule-based primary setup.",
        "If rule-based primary says TAKE but news/analysts conflict — output NO TRADE with explanation.",
        "",
        "── RULE ENGINE PRIMARY (reference) ──",
    ]
    if primary:
        extra.append(
            f"{primary.get('name')} · {primary.get('direction')} · "
            f"take={primary.get('take_trade')} · conf {primary.get('confidence_pct')}% · "
            f"SL -{primary.get('sl_pct')}% · TP +{primary.get('tp_pct')}%",
        )
        extra.append(f"Detail: {primary.get('detail', '')}")
        extra.append(f"Invalidation: {primary.get('invalidation', '')}")
    else:
        extra.append("No primary setup — derive from confluence only.")
    return base + "\n" + "\n".join(extra)
