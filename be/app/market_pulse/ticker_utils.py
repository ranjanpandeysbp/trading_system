"""India index ticker lists for Market Pulse (no US/crypto)."""

from __future__ import annotations

from app.market_pulse.nifty_index_constituents import (
    NIFTY_CEMENT,
    NIFTY_CHEMICALS,
    NIFTY_CONSUMER_DURABLES,
    NIFTY_FINANCIAL_SERVICES_EX_BANK,
    NIFTY_HEALTHCARE,
)

DEFAULT_GROWW_TICKERS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "ITC", "SBIN", "BHARTIARTL",
    "KOTAKBANK", "LT", "AXISBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA",
]

NIFTY_50 = DEFAULT_GROWW_TICKERS

NIFTY_NEXT_50 = [
    "ABB", "DMART", "BAJAJHLDNG", "BANKBARODA", "DLF", "GODREJCP", "HAL", "HEROMOTOCO",
    "JIOFIN", "LTIM", "MUTHOOTFIN", "PFC", "RECLTD", "TRENT", "VEDL",
]

NIFTY_MIDCAP_150 = NIFTY_MIDCAP = [
    "PFC", "RECLTD", "TVSMOTOR", "LUPIN", "AUROPHARMA", "JUBLFOOD", "ZOMATO", "POLICYBZR",
    "BHEL", "SAIL", "ABCAPITAL", "DALBHARAT",
]

NIFTY_SMALLCAP_250 = ["SUZLON", "IRFC", "RVNL", "MAZDOCK", "CDSL", "BSE", "MCX"]

NIFTY_500 = list(dict.fromkeys(NIFTY_50 + NIFTY_MIDCAP_150 + NIFTY_SMALLCAP_250))

NIFTY_BANK = ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "SBIN", "AXISBANK", "INDUSINDBK", "BANDHANBNK"]
NIFTY_IT = ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"]
NIFTY_FINANCIAL = ["BAJFINANCE", "HDFCLIFE", "SBICARD", "BAJAJFINSV", "JIOFIN", "PFC", "RECLTD"]
NIFYAUTO = ["MARUTI", "TATAMOTORS", "M&M", "HEROMOTOCO", "EICHERMOT", "TVSMOTOR"]
NIFTY_FMCG = ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO"]
NIFTY_METAL = ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "SAIL", "COALINDIA"]
NIFTY_REALTY = ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "LODHA"]
NIFTY_ENERGY = ["RELIANCE", "ONGC", "IOC", "BPCL", "GAIL", "NTPC", "POWERGRID"]

INDEX_OPTIONS: dict[str, list[str]] = {
    "Default Groww Tickers": DEFAULT_GROWW_TICKERS,
    "NIFTY 50": NIFTY_50,
    "NIFTY NEXT 50": NIFTY_NEXT_50,
    "NIFTY BANK": NIFTY_BANK,
    "NIFTY IT": NIFTY_IT,
    "NIFTY FINANCIAL SERVICES": NIFTY_FINANCIAL,
    "NIFTY AUTO": NIFYAUTO,
    "NIFTY FMCG": NIFTY_FMCG,
    "NIFTY METAL": NIFTY_METAL,
    "NIFTY REALTY": NIFTY_REALTY,
    "NIFTY ENERGY": NIFTY_ENERGY,
    "NIFTY CEMENT": NIFTY_CEMENT,
    "NIFTY CHEMICALS": NIFTY_CHEMICALS,
    "NIFTY CONSUMER DURABLES": NIFTY_CONSUMER_DURABLES,
    "NIFTY HEALTHCARE": NIFTY_HEALTHCARE,
    "NIFTY FINANCIAL SERVICES EX-BANK": NIFTY_FINANCIAL_SERVICES_EX_BANK,
    "NIFTY MIDCAP 150": NIFTY_MIDCAP,
    "NIFTY SMALLCAP 250": NIFTY_SMALLCAP_250,
    "NIFTY 500": NIFTY_500,
}

GROWW_MARKET = "Groww (India Stocks)"
US_MARKET = "US Stocks (Yahoo)"
CRYPTO_MARKET = "CoinDCX Futures"
MARKET_OPTIONS = [GROWW_MARKET, US_MARKET, CRYPTO_MARKET]


def is_crypto_market(market: str) -> bool:
    return "CoinDCX" in (market or "")


def is_us_market(market: str) -> bool:
    m = (market or "").strip()
    return m == US_MARKET or m == "US Stocks" or "US Stocks" in m


def is_india_market(market: str) -> bool:
    return not is_crypto_market(market) and not is_us_market(market)


def market_currency(_market: str) -> str:
    return "₹"


def get_index_options_for_market(_market: str) -> dict[str, list[str]]:
    from app.market_pulse.ticker_utils_src import get_index_options_for_market as _full
    return _full(_market)


def get_coindcx_ticker_list():
    from app.market_pulse.ticker_utils_src import get_coindcx_ticker_list as _full
    return _full()


def get_us_index_options() -> dict[str, list[str]]:
    from app.market_pulse.us_index_constituents import get_us_index_options as _full
    return _full()
