"""
multi_asset_etf_universe.py
------------------------------
ETF Shop 4.0 universes for US / Crypto / Commodity — the same "distinct
underlying, no duplicate exposure" curation principle as
india_etf_universe.py's ETF_SHOP_39_PRIMARY, applied to each market's own
actual tradeable instruments:

  - US: real US-listed ETFs (broad market, sector SPDRs, factor/style,
    growth/value, international) fetched the same way any other US ticker
    in this app is (yfinance via fetch_data_for_gap_scan / US_MARKET).
  - Crypto: this app's CoinDCX market has no "ETF" product — the closest
    equivalent basket-style, buy-and-hold-and-rotate universe is the top
    liquid coins themselves, so that's what this preset uses (labeled
    honestly as "top coins", not as ETFs, to avoid implying a product that
    doesn't exist on this venue).
  - Commodity: real US-listed commodity ETFs (GLD, SLV, USO, ...) — distinct
    from the CL=F/GC=F *futures* symbols used elsewhere in this app
    (asset_class_config.COMMODITY_META) for scanners/screeners. ETF Shop's
    buy-and-hold-and-rotate model fits an ETF share (no contract expiry/roll)
    far better than a futures contract, so this is a separate, ETF-specific
    list rather than reusing the futures universe.

Each of US/Crypto/Commodity also has a "Stocks" preset alongside its ETF/coin
preset (India already had one via india_etf_universe's Nifty 50 addition) —
the Rank-vs-20-DMA/SIP/FIFO engine is generic over any daily-OHLCV ticker, so
letting the user rotate individual large-cap stocks instead of a diversified
basket is just another preset, not a different engine. Crypto has no stock
equivalent on this app's CoinDCX venue (no equities trade there), so it
intentionally has no Stocks preset rather than faking one with US-listed
"crypto stocks" that CoinDCX can't actually fetch.

All prices/capital for US/Crypto/Commodity are converted to INR for display
and for every capital/quantity calculation (get_usd_inr_rate below) — these
markets genuinely trade in USD, so this app tracks the shop's capital pool
in ₹ throughout while the underlying instrument still executes in $, exactly
like a real multi-currency brokerage statement converted to a home-currency
view. Percentage-based ranking (price vs 20-DMA) is scale-invariant, so this
conversion never changes which instrument ranks #1 — only the numbers shown.
"""

from __future__ import annotations

import logging
import time

from app.market_pulse.ticker_utils import CRYPTO_MARKET, US_MARKET

logger = logging.getLogger(__name__)

# Live USD/INR rate, cached briefly to avoid hitting yfinance on every
# request — same "INR=X" ticker this app already uses elsewhere (see
# india_loader.py's USD/INR macro-context tile) for this exact rate.
_FX_CACHE_TTL_SECONDS = 900
_FX_CACHE: dict[str, tuple[float, float]] = {}
_USD_INR_FALLBACK = 87.0  # only used if the live fetch fails


def get_usd_inr_rate() -> float:
    """Live USD/INR spot rate. `fast_info` returns nothing useful for FX
    pairs on this ticker (verified live), so this reuses news_scanner's
    get_yf_data — the same fast_info → info → history fallback chain
    india_loader.py's own USD/INR macro-context tile already relies on for
    this exact "INR=X" ticker — rather than reinventing a second, thinner
    fetch chain that silently falls back more often than it should."""
    now = time.time()
    cached = _FX_CACHE.get("USDINR")
    if cached and (now - cached[1]) < _FX_CACHE_TTL_SECONDS:
        return cached[0]
    rate = _USD_INR_FALLBACK
    try:
        from app.market_pulse.news_scanner import get_yf_data

        live, _pct, _hist = get_yf_data("INR=X", period="5d", interval="1d")
        if live and float(live) > 0:
            rate = float(live)
    except Exception as exc:
        logger.debug("USD/INR live fetch failed, using fallback %.2f: %s", _USD_INR_FALLBACK, exc)
    _FX_CACHE["USDINR"] = (rate, now)
    return rate

# ---------------------------------------------------------------------------
# US — broad market, sector (SPDR Select), factor/style, growth, and a few
# thematic ETFs. Each ticker here trades on real US exchanges and is fetched
# via the same yfinance path as any other US ticker in this app.
# ---------------------------------------------------------------------------
US_ETF_PRIMARY: list[str] = [
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO",  # broad market
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",  # SPDR sectors
    "VUG", "VTV", "IWF", "IWD",  # growth / value
    "SCHD", "VYM",  # dividend
    "ARKK", "SMH", "SOXX",  # thematic / semis
    "EFA", "EEM", "VEA", "VWO",  # international / emerging
    "GLD", "SLV",  # commodity ETFs also commonly rotated alongside equity ETFs
]

US_ETF_UNDERLYING_LABEL: dict[str, str] = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow 30", "IWM": "Russell 2000",
    "VTI": "Total US Market", "VOO": "S&P 500 (Vanguard)",
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care",
    "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLI": "Industrials",
    "XLB": "Materials", "XLU": "Utilities", "XLRE": "Real Estate", "XLC": "Communication Services",
    "VUG": "Growth", "VTV": "Value", "IWF": "Russell 1000 Growth", "IWD": "Russell 1000 Value",
    "SCHD": "Dividend (Schwab)", "VYM": "High Dividend Yield",
    "ARKK": "Innovation (ARK)", "SMH": "Semiconductors", "SOXX": "Semiconductors (iShares)",
    "EFA": "Developed Markets ex-US", "EEM": "Emerging Markets", "VEA": "Developed Markets (Vanguard)",
    "VWO": "Emerging Markets (Vanguard)",
    "GLD": "Gold", "SLV": "Silver",
}

US_ETF_MASTER: list[str] = sorted(set(US_ETF_PRIMARY + [
    "VXUS", "VGT", "VHT", "VFH", "VDE", "VIS", "VAW", "VPU", "VNQ", "VOX",
    "MTUM", "QUAL", "USMV", "VLUE", "SIZE",
    "JEPI", "JEPQ", "SCHG", "SCHV",
    "IEMG", "IEFA", "ACWI",
]))

# US Stocks — an alternative to the ETF preset above; large-cap names across
# tech/financials/healthcare/consumer/industrials rather than a diversified
# basket, for users who'd rather rotate individual stocks.
US_STOCK_PRIMARY: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO",  # mega-cap tech
    "JPM", "BAC", "WFC", "GS",  # financials
    "UNH", "JNJ", "LLY", "PFE",  # healthcare
    "WMT", "PG", "KO", "PEP", "MCD",  # consumer staples/discretionary
    "XOM", "CVX",  # energy
    "HD", "DIS", "NKE", "V", "MA",  # industrials / consumer / payments
]

US_STOCK_LABEL: dict[str, str] = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "NVDA": "Nvidia", "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom",
    "JPM": "JPMorgan Chase", "BAC": "Bank of America", "WFC": "Wells Fargo", "GS": "Goldman Sachs",
    "UNH": "UnitedHealth", "JNJ": "Johnson & Johnson", "LLY": "Eli Lilly", "PFE": "Pfizer",
    "WMT": "Walmart", "PG": "Procter & Gamble", "KO": "Coca-Cola", "PEP": "PepsiCo", "MCD": "McDonald's",
    "XOM": "Exxon Mobil", "CVX": "Chevron",
    "HD": "Home Depot", "DIS": "Walt Disney", "NKE": "Nike", "V": "Visa", "MA": "Mastercard",
}

# ---------------------------------------------------------------------------
# Crypto — no ETF product on this app's CoinDCX venue; top liquid coins used
# as the buy-and-hold-and-rotate universe instead (see module docstring).
# ---------------------------------------------------------------------------
CRYPTO_COIN_PRIMARY: list[str] = [
    "B-BTCUSDT", "B-ETHUSDT", "B-SOLUSDT", "B-BNBUSDT", "B-XRPUSDT",
    "B-ADAUSDT", "B-DOGEUSDT", "B-AVAXUSDT", "B-DOTUSDT", "B-MATICUSDT",
    "B-LTCUSDT", "B-LINKUSDT", "B-ATOMUSDT", "B-UNIUSDT", "B-NEARUSDT",
]

CRYPTO_COIN_LABEL: dict[str, str] = {
    "B-BTCUSDT": "Bitcoin", "B-ETHUSDT": "Ethereum", "B-SOLUSDT": "Solana",
    "B-BNBUSDT": "BNB", "B-XRPUSDT": "XRP", "B-ADAUSDT": "Cardano",
    "B-DOGEUSDT": "Dogecoin", "B-AVAXUSDT": "Avalanche", "B-DOTUSDT": "Polkadot",
    "B-MATICUSDT": "Polygon", "B-LTCUSDT": "Litecoin", "B-LINKUSDT": "Chainlink",
    "B-ATOMUSDT": "Cosmos", "B-UNIUSDT": "Uniswap", "B-NEARUSDT": "NEAR Protocol",
}

# ---------------------------------------------------------------------------
# Commodity — real US-listed commodity ETFs (distinct from the CL=F/GC=F
# futures symbols used by this app's commodity screeners/scanners).
# ---------------------------------------------------------------------------
COMMODITY_ETF_PRIMARY: list[str] = [
    "GLD", "SLV", "IAU", "SIVR",  # precious metals
    "USO", "UNG", "BNO",  # energy
    "DBA", "DBC", "PDBC",  # broad commodity baskets
    "CPER", "PALL", "PPLT",  # industrial / other metals
    "WEAT", "CORN", "SOYB",  # agriculture
]

COMMODITY_ETF_LABEL: dict[str, str] = {
    "GLD": "Gold (SPDR)", "SLV": "Silver (iShares)", "IAU": "Gold (iShares)", "SIVR": "Silver (abrdn)",
    "USO": "Crude Oil", "UNG": "Natural Gas", "BNO": "Brent Crude Oil",
    "DBA": "Agriculture (Invesco)", "DBC": "Broad Commodity (Invesco)", "PDBC": "Broad Commodity (optimum yield)",
    "CPER": "Copper", "PALL": "Palladium", "PPLT": "Platinum",
    "WEAT": "Wheat", "CORN": "Corn", "SOYB": "Soybeans",
}

# Commodity Stocks — an alternative to the commodity-ETF preset above: real
# equities of energy/mining/agriculture companies whose earnings are directly
# levered to commodity prices ("commodity stocks" in the ordinary finance
# sense), rather than a fund holding the physical commodity/futures directly.
COMMODITY_STOCK_PRIMARY: list[str] = [
    "XOM", "CVX", "COP", "OXY", "SLB",  # energy majors / oilfield services
    "FCX", "NEM", "GOLD", "AA", "SCCO",  # mining — copper, gold, aluminum
    "ADM", "BG", "MOS", "CF",  # agriculture — grain trading, fertilizer
]

COMMODITY_STOCK_LABEL: dict[str, str] = {
    "XOM": "Exxon Mobil (Oil)", "CVX": "Chevron (Oil)", "COP": "ConocoPhillips (Oil)",
    "OXY": "Occidental Petroleum (Oil)", "SLB": "SLB (Oilfield Services)",
    "FCX": "Freeport-McMoRan (Copper)", "NEM": "Newmont (Gold)", "GOLD": "Barrick Gold",
    "AA": "Alcoa (Aluminum)", "SCCO": "Southern Copper",
    "ADM": "Archer-Daniels-Midland (Grain)", "BG": "Bunge (Grain)",
    "MOS": "The Mosaic Company (Potash)", "CF": "CF Industries (Nitrogen)",
}

# Per-asset-class registry keyed the same way as ASSET_CLASS_CONFIG, so the
# service layer can do a single dict lookup instead of branching per market.
MULTI_ASSET_ETF_UNIVERSE: dict[str, dict[str, object]] = {
    "us": {
        "market": US_MARKET, "exchange": "NASDAQ", "currency": "₹",
        "primary": US_ETF_PRIMARY, "master": US_ETF_MASTER,
        "labels": {**US_ETF_UNDERLYING_LABEL, **US_STOCK_LABEL},
        "presets": {
            "US ETF Shop — broad + sector (recommended)": US_ETF_PRIMARY,
            "US Master backup (~30+)": US_ETF_MASTER,
            "US Broad Market": ["SPY", "QQQ", "DIA", "IWM", "VTI", "VOO"],
            "US Sector (SPDR)": ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"],
            "US Stocks — mega-cap (28)": US_STOCK_PRIMARY,
        },
    },
    "crypto": {
        "market": CRYPTO_MARKET, "exchange": "NSE", "currency": "₹",
        "primary": CRYPTO_COIN_PRIMARY, "master": CRYPTO_COIN_PRIMARY, "labels": CRYPTO_COIN_LABEL,
        "presets": {
            "Crypto Shop — top 15 liquid coins (recommended)": CRYPTO_COIN_PRIMARY,
            "Crypto Majors": ["B-BTCUSDT", "B-ETHUSDT", "B-SOLUSDT", "B-BNBUSDT"],
        },
    },
    "commodity": {
        "market": US_MARKET, "exchange": "NASDAQ", "currency": "₹",
        "primary": COMMODITY_ETF_PRIMARY, "master": COMMODITY_ETF_PRIMARY,
        "labels": {**COMMODITY_ETF_LABEL, **COMMODITY_STOCK_LABEL},
        "presets": {
            "Commodity ETF Shop — metals + energy + agri (recommended)": COMMODITY_ETF_PRIMARY,
            "Precious Metals": ["GLD", "SLV", "IAU", "SIVR", "PALL", "PPLT"],
            "Energy": ["USO", "UNG", "BNO"],
            "Broad Commodity Basket": ["DBA", "DBC", "PDBC"],
            "Commodity Stocks — energy + mining + agri (14)": COMMODITY_STOCK_PRIMARY,
        },
    },
}


def default_universe_for(asset_class: str) -> list[str]:
    entry = MULTI_ASSET_ETF_UNIVERSE.get(asset_class)
    return list(entry["primary"]) if entry else []  # type: ignore[index]


def underlying_label_for(asset_class: str, symbol: str) -> str:
    entry = MULTI_ASSET_ETF_UNIVERSE.get(asset_class)
    if not entry:
        return "—"
    labels: dict[str, str] = entry["labels"]  # type: ignore[assignment]
    return labels.get(symbol.upper().strip(), "—")
