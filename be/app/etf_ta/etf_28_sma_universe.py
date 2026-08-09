"""
etf_28_sma_universe.py
----------------------
Universes for the ETF 28 SMA Momentum Strategy (FIRE in India).

Combines:
  - FIRE curated list (from the channel videos / user list)
  - ETF Shop 4.0 primary + master India ETF lists
"""

from __future__ import annotations

from app.etf_ta.india_etf_universe import ETF_SHOP_39_PRIMARY, MASTER_INDIA_ETFS

# FIRE in India — ETF 28 SMA momentum list (NSE symbols; NSE: prefix stripped)
FIRE_28_SMA_LIST: list[str] = [
    "DIVIDEND",
    "ECAPINSURE",
    "GROWWHOSPI",
    "DEFENCE",
    "MOMMIDCAP",
    "GROWWPOWER",
    "SELECTIPO",
    "BANK10ADD",
    "CPSEETF",
    "GOLDBEES",
    "HNGSNGBEES",
    "MAHKTECH",
    "MOMIDMTM",
    "MSCIINDIA",
    "MONQ50",
    "MON100",
    "NIF100BEES",
    "NIFTY100EW",
    "ESG",
    "LOWVOLIETF",
    "HDFCQUAL",
    "GROWWN200",
    "ALPHAETF",
    "MOM30IETF",
    "QUAL30IETF",
    "VAL30IETF",
    "NIFTYBEES",
    "EQUAL50ADD",
    "NV20IETF",
    "MONIFTY500",
    "HEALTHCARE",
    "MOMENTUM50",
    "MULTICAP",
    "EMULTIMQ",
    "VALUEAXIS",
    "ALPHA",
    "ALPL30IETF",
    "AUTOBEES",
    "BANKBEES",
    "MOCAPITAL",
    "CEMNTGROWW",
    "CHEMICAL",
    "COMMOIETF",
    "DIVOPPBEES",
    "ENERGY",
    "EVINDIA",
    "BFSI",
    "FINIETF",
    "FMCGIETF",
    "HDFCGROWTH",
    "HEALTHIETF",
    "CONSUMBEES",
    "MODEFENCE",
    "TNIDETF",
    "GROWWNET",
    "MAKEINDIA",
    "CONSUMER",
    "GROWWRAIL",
    "MOTOUR",
    "INFRAIETF",
    "ITBEES",
    "ELM250",
    "METALIETF",
    "MOM100",
    "MID150BEES",
    "SBIMIDMOM",
    "MIDCAP",
    "MIDSMALL",
    "MNC",
    "JUNIORBEES",
    "OILIETF",
    "PHARMABEES",
    "PVTBANIETF",
    "MOREALTY",
    "SML100CASE",
    "HDFCSML250",
    "SMALLCAP",
    "TOP10ADD",
    "TOP15IETF",
    "TOP20",
    "AONETOTAL",
    "AONETMMQ50",
    "MAFANG",
    "PSUBNKBEES",
    "MASPTOP50",
    "HDFCBSE500",
    "ICICIB22",
    "MOHEALTH",
    "MIDSELIETF",
    "MOQUALITY",
    "SENSEXIETF",
    "SHARIABEES",
    "SILVERBEES",
]

# Prefer liquid Shop symbols when FIRE list has ambiguous/alias names
_ALIAS_TO_PREFERRED: dict[str, str] = {
    "DEFENCE": "MODEFENCE",
    "NV20IETF": "NV20BEES",
    "HDFCGROWTH": "HDFCGROW",
    "MIDCAP": "MIDCAPETF",
    "INFRAIETF": "INFRABEES",
}


def _norm(sym: str) -> str:
    s = str(sym or "").upper().strip()
    if s.startswith("NSE:"):
        s = s[4:]
    if s.startswith("BSE:"):
        s = s[4:]
    return s


def canonicalize_symbol(symbol: str) -> str:
    s = _norm(symbol)
    return _ALIAS_TO_PREFERRED.get(s, s)


def fire_28_sma_symbols() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in FIRE_28_SMA_LIST:
        s = canonicalize_symbol(raw)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def etf_shop_symbols() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in list(ETF_SHOP_39_PRIMARY) + list(MASTER_INDIA_ETFS):
        s = canonicalize_symbol(raw)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def combined_universe() -> list[str]:
    """FIRE list first, then ETF Shop symbols not already included."""
    seen: set[str] = set()
    out: list[str] = []
    for s in fire_28_sma_symbols() + etf_shop_symbols():
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


ETF_28_SMA_PRESETS: dict[str, list[str]] = {
    "FIRE 28 SMA — curated list": fire_28_sma_symbols(),
    "ETF Shop 4.0 — 39 distinct": list(ETF_SHOP_39_PRIMARY),
    "Combined (FIRE + ETF Shop)": combined_universe(),
    "Master India ETFs (~120+)": list(MASTER_INDIA_ETFS),
}
