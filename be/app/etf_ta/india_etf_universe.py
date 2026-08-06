"""
india_etf_universe.py
---------------------
India NSE ETF universes for ETF Shop 4.0 (STF Shop tab).

3.0 rule: primary shop uses ETFs on distinct underlying assets — no overlap
(e.g. not two Nifty 50 or two Bank Nifty funds in the active shop list).
Master list (~120+) is for manual substitution when a ticker has data issues.

Ticker corrections (verified against actual NSE/BSE listings — some originally
listed symbols do not exist or trade under a different symbol):
  - NIFTY_500: ICICI500 -> BSE500IETF (ICICI Prudential BSE 500 ETF; BSE: 541313)
  - BHARAT_22: BHARAT22 -> ICICIB22 (Bharat 22 ETF; BSE: 540787)
  - BSE_SENSEX_22 removed: it duplicated ICICIB22 (same fund as BHARAT_22 above,
    not a distinct "BSE Sensex 22" product)
  - NETF_MID150: NETFMID150 -> MID150BEES (Nippon India ETF Nifty Midcap 150; BSE: 542932)
  - QUALITY_30 removed: NETFQ30 has no direct NSE/BSE match
  - METAL removed: METALBEES does not exist
  - REALTY: REALTYBEES -> MOREALTY (Motilal Oswal Nifty Realty ETF; BSE: 544147)
  - ENERGY: ENERGYBEES -> ENERGY (Mirae Asset Nifty Energy ETF; BSE: 544604)
"""

from __future__ import annotations

from app.market_pulse.high_vol_etf_tickers import HIGH_VOL_ETF
from app.market_pulse.ticker_utils import NIFTY_50, NIFTY_NEXT_50

# Underlying asset tag → one chosen liquid NSE symbol (no duplicate exposure in Shop 3.0)
ETF_SHOP_39_UNDERLYING: dict[str, str] = {
    "NIFTY_50": "NIFTYBEES",
    "NIFTY_NEXT_50": "JUNIORBEES",
    "NIFTY_BANK": "BANKBEES",
    "NIFTY_IT": "ITBEES",
    "NIFTY_PSU_BANK": "PSUBNKBEES",
    "NIFTY_MIDCAP_150": "MIDCAPETF",
    "NIFTY_SMLCAP_250": "HDFCSML250",
    "NIFTY_500": "BSE500IETF",
    "NIFTY_100": "UTINIFTETF",
    "SENSEX": "UTISXN50",
    "GOLD": "GOLDBEES",
    "SILVER": "SILVERBEES",
    "MOMENTUM_100": "MOM100",
    "MOMENTUM_50": "MOM50",
    "MSCI_INDIA": "MON100",
    "DIVIDEND_OPPORTUNITIES": "DIVOPPBEES",
    "CONSUMPTION": "CONSUMBEES",
    "PHARMA": "PHARMABEES",
    "AUTO": "AUTOBEES",
    "INFRA": "INFRABEES",
    "CPSE": "CPSEETF",
    "DEFENCE": "MODEFENCE",
    "FMCG": "FMCGIETF",
    "NV20": "NV20BEES",
    "BHARAT_22": "ICICIB22",
    "TOP_50_EQUAL": "MASPTOP50",
    "MIDCAP_150_HDFC": "HDFCMID150",
    "NETF_MID150": "MID150BEES",
    "GROWW_POWER": "GROWWPOWER",
    "GROWW_DEFENCE": "GROWWDEFNC",
    "GROWW_EV": "GROWWEV",
    "GROWW_LOW_VOL": "GROWWLOVOL",
    "LIQUID": "LIQUIDBEES",
    "HEALTHCARE": "HEALTHY",
    "REALTY": "MOREALTY",
    "ENERGY": "ENERGY",
}

ETF_SHOP_39_PRIMARY: list[str] = list(ETF_SHOP_39_UNDERLYING.values())

# Reverse lookup: symbol → underlying label
ETF_UNDERLYING_LABEL: dict[str, str] = {v: k for k, v in ETF_SHOP_39_UNDERLYING.items()}

# Master backup list (~120+) — substitute when Google Finance / data pull fails
MASTER_INDIA_ETFS: list[str] = sorted(set(ETF_SHOP_39_PRIMARY + [
    "SETFNIF50", "SETFNIFBK", "SETFNN50", "SETF10GILT", "SETFGOLD", "SETFSN50",
    "KOTAKBKETF", "KOTAKPSUBK", "KOTAKIT", "KOTAKGOLD", "KOTAKNV20",
    "HDFCNIF100", "HDFCNIFTY", "HDFCSENSEX", "HDFCMOMENT", "HDFCQUAL", "HDFCGROW",
    "HDFCPVTBAN", "HDFCPHARM", "HDFCLOWVOL", "HDFCNEXT50", "HDFCGOLD",
    "ICICITECH", "ICICIGOLD", "ICICIMCAP", "ICICISENSX", "ICICINV20", "ICICIALPLV",
    "ICICIBANKN", "ICICIFMCG", "ICICIAUTO", "ICICIPHARM", "ICICIM150",
    "UTIBANKETF", "UTINEXT50", "UTISENSETF", "UTINIFTETF", "UTISXN50",
    "NIPPONETF", "NIFTYETF", "NV20BEES", "PSUBNKBEES",
    "AXISGOLD", "AXISNIFTY", "AXISTECETF", "AXISBPSETF", "AXISCETF", "AXISHCETF",
    "MIRAEETF", "MAFANG", "MAESG", "MAM150ETF", "MAFSETF",
    "SBISENSEX", "SBIETFQLTY", "SBIETFIT", "SBIETFPB", "SBIETFCON",
    "BSLNIFTY", "BSLBANKETF", "BSLGOLDETF", "BSLNIFMID150",
    "EDELWEISSMF", "ESG", "MAKEINDIA", "EQUAL50", "ALPHAETF",
    "MIDCETF", "SMALLCAP", "TNIDETF", "SHARIABEES",
    "GOLDSHARE", "SILVERETF", "GOLDBEES", "SILVERBEES",
    "LIQUIDETF", "LIQUIDBEES", "LIQUID1", "LIQUIDCETF",
    "GROWWNET", "GROWWRAIL", "GROWWLIQID", "GROWWSLVR",
    "MOGOLD", "MOM100", "MOM50", "MOMENTUM",
    "TOP100CASE", "TOP10ADD", "MIDSELIQ", "MIDQ50ADD",
    "BANKETFADD", "ITETFADD", "AUTOBEES", "CONSUMBEES",
    "INFRABEES", "PHARMABEES", "FMCGIETF", "MODEFENCE",
    "GROWWPOWER", "GROWWDEFNC", "GROWWEV", "GROWWLOVOL",
    "NETFCONSUM", "NETFIT", "NETFNIF100",
    "MASPTOP50", "MAHKTECH", "MAFCTETF",
]))

ETF_PRESETS: dict[str, list[str]] = {
    "ETF Shop 4.0 — 39 distinct (recommended)": ETF_SHOP_39_PRIMARY,
    "ETF Shop 3.0 — 39 distinct (legacy label)": ETF_SHOP_39_PRIMARY,
    "Master backup (~120+)": MASTER_INDIA_ETFS,
    "Index BEES": [
        "NIFTYBEES", "JUNIORBEES", "BANKBEES", "ITBEES", "PSUBNKBEES", "MIDCAPETF",
    ],
    "Thematic / Sector": [
        "DIVOPPBEES", "CONSUMBEES", "PHARMABEES", "AUTOBEES", "INFRABEES",
        "FMCGIETF", "MODEFENCE", "GROWWPOWER", "GROWWDEFNC", "GROWWEV",
        "MOREALTY", "ENERGY", "HEALTHY",
    ],
    "Commodity": ["GOLDBEES", "SILVERBEES", "HDFCGOLD", "GOLDSHARE"],
    "Smart Beta / Factor": [
        "MOM100", "MOM50", "MON100", "NV20BEES", "MID150BEES", "MASPTOP50",
    ],
    # Same broad, actively-traded NSE ETF universe already used for the general ticker-picker
    # "High Vol ETF" dropdown elsewhere in this app (app.market_pulse.high_vol_etf_tickers) —
    # reused here rather than curating a second, separate list.
    "High Vol ETF": HIGH_VOL_ETF,
    # Individual stocks instead of a diversified ETF basket — reuses this app's
    # own verified NIFTY_50/NIFTY_NEXT_50 constituent lists (ticker_utils.py)
    # rather than curating a third copy of the same data.
    "India Stocks — Nifty 50 (recommended)": NIFTY_50,
    "India Stocks — Nifty Next 50": NIFTY_NEXT_50,
}

GROWW_INDIA_MARKET = "Groww (India Stocks)"

# Legacy alias
LIQUID_INDIA_ETFS = ETF_SHOP_39_PRIMARY


def default_etf_universe() -> list[str]:
    return list(ETF_SHOP_39_PRIMARY)


def underlying_for_symbol(symbol: str) -> str:
    return ETF_UNDERLYING_LABEL.get(symbol.upper().strip(), "—")
