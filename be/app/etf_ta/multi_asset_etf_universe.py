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
"""

from __future__ import annotations

from app.market_pulse.ticker_utils import CRYPTO_MARKET, US_MARKET

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

# Per-asset-class registry keyed the same way as ASSET_CLASS_CONFIG, so the
# service layer can do a single dict lookup instead of branching per market.
MULTI_ASSET_ETF_UNIVERSE: dict[str, dict[str, object]] = {
    "us": {
        "market": US_MARKET, "exchange": "NASDAQ", "currency": "$",
        "primary": US_ETF_PRIMARY, "master": US_ETF_MASTER, "labels": US_ETF_UNDERLYING_LABEL,
        "presets": {
            "US ETF Shop — broad + sector (recommended)": US_ETF_PRIMARY,
            "US Master backup (~30+)": US_ETF_MASTER,
            "US Broad Market": ["SPY", "QQQ", "DIA", "IWM", "VTI", "VOO"],
            "US Sector (SPDR)": ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"],
        },
    },
    "crypto": {
        "market": CRYPTO_MARKET, "exchange": "NSE", "currency": "$",
        "primary": CRYPTO_COIN_PRIMARY, "master": CRYPTO_COIN_PRIMARY, "labels": CRYPTO_COIN_LABEL,
        "presets": {
            "Crypto Shop — top 15 liquid coins (recommended)": CRYPTO_COIN_PRIMARY,
            "Crypto Majors": ["B-BTCUSDT", "B-ETHUSDT", "B-SOLUSDT", "B-BNBUSDT"],
        },
    },
    "commodity": {
        "market": US_MARKET, "exchange": "NASDAQ", "currency": "$",
        "primary": COMMODITY_ETF_PRIMARY, "master": COMMODITY_ETF_PRIMARY, "labels": COMMODITY_ETF_LABEL,
        "presets": {
            "Commodity ETF Shop — metals + energy + agri (recommended)": COMMODITY_ETF_PRIMARY,
            "Precious Metals": ["GLD", "SLV", "IAU", "SIVR", "PALL", "PPLT"],
            "Energy": ["USO", "UNG", "BNO"],
            "Broad Commodity Basket": ["DBA", "DBC", "PDBC"],
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
