"""
detect_sector_rotation_engine.py
--------------------------------
Detect Sector Rotation — top-down CRS + Hull confirmation strategy.

Source: https://www.youtube.com/watch?v=IfMDd2XlArU&t=123s

Rules:
  1. Cyclical pullback setup — sector delivered negative returns for 2–3 consecutive
     months (or quarters). Marks a deeply underperforming sector that may be ripe
     for reversal.
  2. Comparative Relative Strength (weekly) — RS = Sector ÷ Benchmark; want RS above
     its 50-period SMA (sector outperforming the broad market).
  3. Hull Moving Average confirmation — sector close above HMA (absolute uptrend).
     Hull Suite "Buy" analogue: close > HMA(9) on weekly.
  4. Final: BUY / ROTATE IN when (2) and (3) are true. Pullback history elevates
     conviction when present.

Markets:
  🇮🇳 India — Nifty sector indices vs Nifty 50
  🇺🇸 US    — SPDR sector ETFs vs SPY
  ₿ Crypto — thematic CoinDCX pairs vs BTC
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

YOUTUBE_DETECT_SECTOR_ROTATION_URL = "https://www.youtube.com/watch?v=IfMDd2XlArU&t=123s"

MarketKind = Literal["india", "us", "crypto"]

# ─── Universes ──────────────────────────────────────────────────────────────

INDIA_SECTORS: dict[str, str] = {
    "Nifty Bank": "^NSEBANK",
    "Nifty IT": "^CNXIT",
    "Nifty FMCG": "^CNXFMCG",
    "Nifty Pharma": "^CNXPHARMA",
    "Nifty Auto": "^CNXAUTO",
    "Nifty Metal": "^CNXMETAL",
    "Nifty Realty": "^CNXREALTY",
    "Nifty Energy": "^CNXENERGY",
    "Nifty Media": "^CNXMEDIA",
    "Nifty PSU Bank": "^CNXPSUBANK",
    "Nifty Infra": "^CNXINFRA",
    "Nifty Financial Services": "NIFTY_FIN_SERVICE.NS",
    "Nifty Midcap 150": "^NSEMDCP150",
    "Nifty Smallcap 250": "NIFTYSML250.NS",
}
INDIA_BENCHMARK = "^NSEI"
INDIA_BENCHMARK_LABEL = "Nifty 50"

# ETF fallbacks if index tickers fail
INDIA_SECTOR_FALLBACKS: dict[str, str] = {
    "Nifty Bank": "BANKBEES.NS",
    "Nifty IT": "ITBEES.NS",
    "Nifty Pharma": "PHARMABEES.NS",
    "Nifty Metal": "METALBEES.NS",
    "Nifty Realty": "REALTYBEES.NS",
    "Nifty Energy": "ENERGYBEES.NS",
}
INDIA_BENCHMARK_FALLBACK = "NIFTYBEES.NS"

US_SECTORS: dict[str, str] = {
    "Communication (XLC)": "XLC",
    "Consumer Discretionary (XLY)": "XLY",
    "Consumer Staples (XLP)": "XLP",
    "Energy (XLE)": "XLE",
    "Financials (XLF)": "XLF",
    "Health Care (XLV)": "XLV",
    "Industrials (XLI)": "XLI",
    "Materials (XLB)": "XLB",
    "Real Estate (XLRE)": "XLRE",
    "Technology (XLK)": "XLK",
    "Utilities (XLU)": "XLU",
}
US_BENCHMARK = "SPY"
US_BENCHMARK_LABEL = "S&P 500 (SPY)"

CRYPTO_SECTORS: dict[str, str] = {
    "Ethereum (ETH)": "B-ETHUSDT",
    "Solana (SOL)": "B-SOLUSDT",
    "XRP": "B-XRPUSDT",
    "Cardano (ADA)": "B-ADAUSDT",
    "Avalanche (AVAX)": "B-AVAXUSDT",
    "Chainlink (LINK)": "B-LINKUSDT",
    "Polkadot (DOT)": "B-DOTUSDT",
    "NEAR": "B-NEARUSDT",
    "Dogecoin (DOGE)": "B-DOGEUSDT",
    "Sui (SUI)": "B-SUIUSDT",
    "Arbitrum (ARB)": "B-ARBUSDT",
    "Optimism (OP)": "B-OPUSDT",
    "Uniswap (UNI)": "B-UNIUSDT",
    "Aave (AAVE)": "B-AAVEUSDT",
    "Injective (INJ)": "B-INJUSDT",
}
CRYPTO_BENCHMARK = "B-BTCUSDT"
CRYPTO_BENCHMARK_LABEL = "Bitcoin (BTC)"

# ─── Linked ETFs + top constituents (per sector) ───────────────────────────

INDIA_SECTOR_ETFS: dict[str, list[str]] = {
    "Nifty Bank": ["BANKBEES", "SETFNIFBK", "HDFCNIFBAN", "BANKIETF", "UTIBANKETF"],
    "Nifty IT": ["ITBEES", "SBIETFIT", "ITIETF", "AXISTECETF", "ICICITECH"],
    "Nifty FMCG": ["FMCGIETF", "ICICIFMCG", "CONSUMBEES"],
    "Nifty Pharma": ["PHARMABEES", "HDFCPHARM", "ICICIPHARM", "HEALTHY"],
    "Nifty Auto": ["AUTOBEES", "ICICIAUTO", "AUTOIETF"],
    "Nifty Metal": ["METALBEES"],
    "Nifty Realty": ["REALTYBEES"],
    "Nifty Energy": ["ENERGYBEES", "GROWWPOWER", "CPSEETF"],
    "Nifty Media": [],
    "Nifty PSU Bank": ["PSUBNKBEES", "KOTAKPSUBK", "PSUBANK"],
    "Nifty Infra": ["INFRABEES", "INFRAIETF", "MOINFRA"],
    "Nifty Financial Services": ["FINIETF", "BANKBEES", "HDFCPVTBAN"],
    "Nifty Midcap 150": ["MIDCAPETF", "NETFMID150", "HDFCMID150", "ICICIM150"],
    "Nifty Smallcap 250": ["HDFCSML250", "SMALLCAP"],
}

INDIA_SECTOR_INDEX_KEY: dict[str, str] = {
    "Nifty Bank": "NIFTY BANK",
    "Nifty IT": "NIFTY IT",
    "Nifty FMCG": "NIFTY FMCG",
    "Nifty Pharma": "NIFTY PHARMA",
    "Nifty Auto": "NIFTY AUTO",
    "Nifty Metal": "NIFTY METAL",
    "Nifty Realty": "NIFTY REALTY",
    "Nifty Energy": "NIFTY ENERGY",
    "Nifty Media": "NIFTY MEDIA",
    "Nifty PSU Bank": "NIFTY PSU BANK",
    "Nifty Infra": "NIFTY INFRA",
    "Nifty Financial Services": "NIFTY FINANCIAL SERVICES",
    "Nifty Midcap 150": "NIFTY MIDCAP 150",
    "Nifty Smallcap 250": "NIFTY SMALLCAP 250",
}

US_SECTOR_ETFS: dict[str, list[str]] = {
    "Communication (XLC)": ["XLC", "VOX", "FCOM"],
    "Consumer Discretionary (XLY)": ["XLY", "VCR", "FDIS"],
    "Consumer Staples (XLP)": ["XLP", "VDC", "FSTA"],
    "Energy (XLE)": ["XLE", "VDE", "XOP"],
    "Financials (XLF)": ["XLF", "VFH", "KRE"],
    "Health Care (XLV)": ["XLV", "VHT", "IHI"],
    "Industrials (XLI)": ["XLI", "VIS", "FIDU"],
    "Materials (XLB)": ["XLB", "VAW", "XME"],
    "Real Estate (XLRE)": ["XLRE", "VNQ", "IYR"],
    "Technology (XLK)": ["XLK", "VGT", "QQQ"],
    "Utilities (XLU)": ["XLU", "VPU", "IDU"],
}

US_SECTOR_TOP_STOCKS: dict[str, list[str]] = {
    "Communication (XLC)": [
        "META", "GOOGL", "GOOG", "NFLX", "T", "VZ", "DIS", "CMCSA", "TMUS", "CHTR",
        "EA", "TTWO", "WBD", "LYV", "OMC", "FOXA", "FOX", "MTCH", "PARA", "NWS",
    ],
    "Consumer Discretionary (XLY)": [
        "AMZN", "TSLA", "HD", "MCD", "BKNG", "LOW", "TJX", "NKE", "SBUX", "CMG",
        "ORLY", "MAR", "AZO", "ABNB", "DHI", "ROST", "GM", "F", "YUM", "LEN",
    ],
    "Consumer Staples (XLP)": [
        "PG", "COST", "WMT", "KO", "PEP", "PM", "MDLZ", "MO", "CL", "KMB",
        "GIS", "SYY", "STZ", "KHC", "KR", "HSY", "ADM", "EL", "MKC", "CHD",
    ],
    "Energy (XLE)": [
        "XOM", "CVX", "COP", "EOG", "SLB", "WMB", "MPC", "PSX", "OXY", "VLO",
        "HES", "KMI", "BKR", "HAL", "FANG", "DVN", "TRGP", "EQT", "CTRA", "OKE",
    ],
    "Financials (XLF)": [
        "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "SPGI", "MS", "AXP",
        "C", "BLK", "SCHW", "CB", "PGR", "MMC", "ICE", "CME", "AON", "USB",
    ],
    "Health Care (XLV)": [
        "LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "AMGN", "DHR", "PFE",
        "ISRG", "SYK", "BSX", "VRTX", "MDT", "GILD", "REGN", "ELV", "BMY", "CI",
    ],
    "Industrials (XLI)": [
        "GE", "CAT", "RTX", "UNP", "HON", "ETN", "UPS", "BA", "DE", "LMT",
        "ADP", "WM", "TT", "PH", "GD", "ITW", "EMR", "NOC", "CSX", "MMM",
    ],
    "Materials (XLB)": [
        "LIN", "SHW", "APD", "ECL", "FCX", "NEM", "CTVA", "DOW", "NUE", "DD",
        "MLM", "VMC", "PPG", "STLD", "IFF", "ALB", "CF", "MOS", "EMN", "PKG",
    ],
    "Real Estate (XLRE)": [
        "PLD", "AMT", "EQIX", "WELL", "SPG", "O", "CCI", "DLR", "PSA", "EXR",
        "VICI", "AVB", "CBRE", "IRM", "EQR", "VTR", "SBAC", "WY", "ARE", "INVH",
    ],
    "Technology (XLK)": [
        "NVDA", "AAPL", "MSFT", "AVGO", "CRM", "ORCL", "AMD", "ADBE", "CSCO", "ACN",
        "IBM", "INTU", "TXN", "QCOM", "NOW", "AMAT", "MU", "PANW", "LRCX", "KLAC",
    ],
    "Utilities (XLU)": [
        "NEE", "SO", "DUK", "CEG", "AEP", "SRE", "D", "PCG", "EXC", "XEL",
        "EIX", "WEC", "ED", "PEG", "AWK", "DTE", "ETR", "ES", "FE", "PPL",
    ],
}

CRYPTO_SECTOR_ETFS: dict[str, list[str]] = {
    "Ethereum (ETH)": ["ETHA", "ETHE", "ETH"],
    "Solana (SOL)": [],
    "XRP": [],
    "Cardano (ADA)": [],
    "Avalanche (AVAX)": [],
    "Chainlink (LINK)": ["LINK"],
    "Polkadot (DOT)": [],
    "NEAR": [],
    "Dogecoin (DOGE)": [],
    "Sui (SUI)": [],
    "Arbitrum (ARB)": [],
    "Optimism (OP)": [],
    "Uniswap (UNI)": [],
    "Aave (AAVE)": [],
    "Injective (INJ)": [],
}

CRYPTO_THEME_PEERS: dict[str, list[str]] = {
    "Ethereum (ETH)": [
        "ETH", "LDO", "ARB", "OP", "AAVE", "UNI", "MKR", "SNX", "CRV", "COMP",
        "1INCH", "ENS", "RPL", "SSV", "PENDLE", "ENA", "EIGEN", "STRK", "BLAST", "W",
    ],
    "Solana (SOL)": [
        "SOL", "JUP", "PYTH", "RAY", "WIF", "BONK", "JTO", "ORCA", "MNDE", "TNSR",
        "W", "KMNO", "DRIFT", "RENDER", "HNT", "MOBILE", "MEW", "POPCAT", "IO", "CLOUD",
    ],
    "XRP": [
        "XRP", "XLM", "HBAR", "ALGO", "QNT", "XDC", "IOTA", "FET", "RLUSD", "SOLO",
    ],
    "Cardano (ADA)": [
        "ADA", "DOT", "ATOM", "NEAR", "ALGO", "ICP", "EGLD", "FLOW", "MINA", "ROSE",
    ],
    "Avalanche (AVAX)": [
        "AVAX", "SOL", "NEAR", "SUI", "APT", "SEI", "TIA", "INJ", "ATOM", "DOT",
    ],
    "Chainlink (LINK)": [
        "LINK", "PYTH", "API3", "BAND", "TRB", "GRT", "FLUX", "UMA", "NEST", "DIA",
    ],
    "Polkadot (DOT)": [
        "DOT", "KSM", "ATOM", "NEAR", "ADA", "GLMR", "ASTR", "MOVR", "PHA", "CFG",
    ],
    "NEAR": [
        "NEAR", "SUI", "APT", "SEI", "TIA", "INJ", "ATOM", "DOT", "ICP", "EGLD",
    ],
    "Dogecoin (DOGE)": [
        "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "BRETT", "NEIRO", "TURBO",
    ],
    "Sui (SUI)": [
        "SUI", "APT", "SEI", "TIA", "NEAR", "INJ", "ATOM", "SOL", "AVAX", "DOT",
    ],
    "Arbitrum (ARB)": [
        "ARB", "OP", "STRK", "MATIC", "POL", "IMX", "METIS", "MANTA", "BLAST", "ZK",
    ],
    "Optimism (OP)": [
        "OP", "ARB", "STRK", "MATIC", "POL", "BASE", "BLAST", "MODE", "FRAX", "SNX",
    ],
    "Uniswap (UNI)": [
        "UNI", "AAVE", "MKR", "CRV", "COMP", "SNX", "1INCH", "SUSHI", "BAL", "LDO",
        "PENDLE", "DYDX", "GMX", "JUP", "CAKE", "RAY", "ORCA", "VELO", "AERO", "RUNE",
    ],
    "Aave (AAVE)": [
        "AAVE", "MKR", "COMP", "CRV", "SNX", "LDO", "MORPHO", "ENA", "PENDLE", "FRAX",
        "DAI", "USDC", "UNI", "LINK", "ETH",
    ],
    "Injective (INJ)": [
        "INJ", "DYDX", "GMX", "SNX", "PERP", "TIA", "SEI", "SUI", "APT", "ATOM",
    ],
}

_TOP_N = 20


@dataclass
class DetectSectorRotationConfig:
    crs_sma_period: int = 50
    hma_length: int = 9
    pullback_months: int = 2  # consecutive negative months required (2–3)
    pullback_mode: str = "months"  # "months" | "quarters"
    lookback_years: int = 5
    min_weeks: int = 55


def _wma(series: pd.Series, length: int) -> pd.Series:
    weights = np.arange(1, length + 1, dtype=float)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def hma(series: pd.Series, length: int = 9) -> pd.Series:
    """Hull Moving Average."""
    half = max(int(length / 2), 1)
    sqrt_n = max(int(np.sqrt(length)), 1)
    raw = 2 * _wma(series, half) - _wma(series, length)
    return _wma(raw, sqrt_n)


def _normalize_ohlc(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    col = "Close" if "Close" in df.columns else "close" if "close" in df.columns else None
    if col is None:
        return None
    s = df[col].astype(float).dropna()
    if s.empty:
        return None
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s


def _yf_weekly(symbol: str, years: int = 5) -> pd.Series | None:
    try:
        raw = yf.download(
            symbol, period=f"{years}y", interval="1wk",
            progress=False, auto_adjust=True, threads=False,
        )
        return _normalize_ohlc(raw)
    except Exception as exc:
        logger.debug("yfinance weekly failed for %s: %s", symbol, exc)
        return None


def _groww_weekly(etf_symbol: str, groww_token: str, years: int = 5) -> pd.Series | None:
    """Weekly close series for a *tradeable* India ETF symbol via Groww
    (authenticated API when a token is configured, else Groww's public
    charting service). Groww's candle API only covers real CASH-segment
    instruments (stocks/ETFs) — bare index symbols like NIFTY/BANKNIFTY
    return near-empty data — so this is only called with an ETF proxy
    (e.g. NIFTYBEES, BANKBEES), never the raw index ticker."""
    from app.data.groww_client import fetch_groww_ohlcv

    sym = (etf_symbol or "").strip().upper().removesuffix(".NS").removesuffix(".BO")
    if not sym:
        return None
    limit = max(60, years * 53 + 5)
    try:
        df = fetch_groww_ohlcv(sym, "NSE", "1w", api_token=groww_token, limit=limit)
    except Exception as exc:
        logger.debug("Groww weekly failed for %s: %s", sym, exc)
        return None
    if df is not None and not df.empty and "close" in df.columns:
        s = df["close"].astype(float).dropna()
        if len(s) >= 40:
            return s
    return None


def _crypto_weekly(symbol: str, limit: int = 300) -> pd.Series | None:
    try:
        from app.market_pulse.heatmap import fetch_coindcx_ohlcv
        df = fetch_coindcx_ohlcv(symbol, "1w", limit=limit)
        if df is None or df.empty:
            # Fallback: daily → weekly resample
            daily = fetch_coindcx_ohlcv(symbol, "1d", limit=limit * 7)
            if daily is None or daily.empty:
                return None
            daily = daily.copy()
            if not isinstance(daily.index, pd.DatetimeIndex):
                if "timestamp" in daily.columns:
                    daily.index = pd.to_datetime(daily["timestamp"], unit="s", errors="coerce")
                else:
                    return None
            close_col = "close" if "close" in daily.columns else "Close"
            s = daily[close_col].astype(float)
            s = s.resample("W-FRI").last().dropna()
            return s
        close_col = "close" if "close" in df.columns else "Close"
        s = df[close_col].astype(float).dropna()
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        return s
    except Exception as exc:
        logger.debug("CoinDCX weekly failed for %s: %s", symbol, exc)
        return None


def _fetch_weekly_close(market: MarketKind, symbol: str, years: int = 5) -> pd.Series | None:
    if market == "crypto":
        return _crypto_weekly(symbol)
    return _yf_weekly(symbol, years=years)


def _monthly_returns(weekly: pd.Series) -> pd.Series:
    monthly = weekly.resample("ME").last().dropna()
    return monthly.pct_change().dropna()


def _quarterly_returns(weekly: pd.Series) -> pd.Series:
    q = weekly.resample("QE").last().dropna()
    return q.pct_change().dropna()


def detect_cyclical_pullback(
    weekly: pd.Series, *, months: int = 2, mode: str = "months",
) -> dict[str, Any]:
    """
    True when the last `months` consecutive month (or quarter) returns are negative.
    """
    months = max(int(months), 2)
    if mode == "quarters":
        rets = _quarterly_returns(weekly)
        label = "quarters"
    else:
        rets = _monthly_returns(weekly)
        label = "months"

    if len(rets) < months:
        return {
            "pullback": False, "consecutive_neg": 0, "required": months,
            "mode": label, "recent_returns_pct": [], "reason": f"Insufficient {label} history.",
        }

    recent = rets.iloc[-months:]
    consecutive = 0
    for v in reversed(rets.tolist()):
        if v < 0:
            consecutive += 1
        else:
            break

    pullback = bool((recent < 0).all())
    recent_pct = [round(float(x) * 100, 2) for x in recent.tolist()]
    reason = (
        f"Last {months} {label} all negative ({', '.join(f'{p:+.1f}%' for p in recent_pct)}) — cyclical pullback setup."
        if pullback
        else f"Last {months} {label}: {', '.join(f'{p:+.1f}%' for p in recent_pct)} — no full pullback streak."
    )
    return {
        "pullback": pullback,
        "consecutive_neg": consecutive,
        "required": months,
        "mode": label,
        "recent_returns_pct": recent_pct,
        "reason": reason,
    }


def analyze_sector_pair(
    sector_weekly: pd.Series,
    benchmark_weekly: pd.Series,
    *,
    name: str,
    symbol: str,
    cfg: DetectSectorRotationConfig,
) -> dict[str, Any]:
    aligned = pd.concat(
        [sector_weekly.rename("sector"), benchmark_weekly.rename("bench")],
        axis=1,
    ).dropna()
    if len(aligned) < cfg.min_weeks:
        return {
            "name": name, "symbol": symbol,
            "error": f"Insufficient weekly overlap ({len(aligned)} weeks, need {cfg.min_weeks}+).",
        }

    crs = aligned["sector"] / aligned["bench"]
    crs_sma = crs.rolling(cfg.crs_sma_period).mean()
    sector_hma = hma(aligned["sector"], cfg.hma_length)

    last_i = -1
    # Need SMA warm-up
    if pd.isna(crs_sma.iloc[last_i]) or pd.isna(sector_hma.iloc[last_i]):
        return {"name": name, "symbol": symbol, "error": "Indicators not warm yet."}

    close = float(aligned["sector"].iloc[last_i])
    crs_v = float(crs.iloc[last_i])
    sma_v = float(crs_sma.iloc[last_i])
    hma_v = float(sector_hma.iloc[last_i])
    prev_crs, prev_sma = float(crs.iloc[-2]), float(crs_sma.iloc[-2]) if len(crs) > 1 else (crs_v, sma_v)

    outperforming = crs_v > sma_v
    hull_buy = close > hma_v
    crs_cross_up = prev_crs <= prev_sma and crs_v > sma_v

    pullback = detect_cyclical_pullback(
        aligned["sector"], months=cfg.pullback_months, mode=cfg.pullback_mode,
    )

    # Trailing relative performance (1m / 3m / 6m approx on weekly)
    def _ret(weeks: int) -> float | None:
        if len(aligned) <= weeks:
            return None
        a, b = float(aligned["sector"].iloc[-1]), float(aligned["sector"].iloc[-1 - weeks])
        return round((a / b - 1) * 100, 2) if b else None

    if outperforming and hull_buy:
        verdict = "BUY"
        if pullback["pullback"] or crs_cross_up:
            setup = "ROTATE_IN"
            confidence = 90 if pullback["pullback"] and crs_cross_up else 80
        else:
            setup = "HOLD_LEADER"
            confidence = 70
    elif outperforming and not hull_buy:
        verdict = "WATCH"
        setup = "RS_LEADING_WAIT_HULL"
        confidence = 45
    elif hull_buy and not outperforming:
        verdict = "WATCH"
        setup = "HULL_UP_WAIT_RS"
        confidence = 40
    else:
        verdict = "AVOID"
        setup = "WEAK"
        confidence = 15
        if pullback["pullback"]:
            setup = "PULLBACK_WAITING"
            confidence = 30

    reasons = [
        pullback["reason"],
        f"CRS {crs_v:.4f} vs 50-wk SMA {sma_v:.4f} — "
        + ("outperforming benchmark." if outperforming else "underperforming / below RS MA."),
        f"Hull({cfg.hma_length}): close {close:,.2f} vs HMA {hma_v:,.2f} — "
        + ("absolute uptrend (Buy)." if hull_buy else "below HMA (no absolute buy)."),
    ]
    if crs_cross_up:
        reasons.append("Fresh CRS cross above its 50-week SMA this week.")

    return {
        "name": name,
        "symbol": symbol,
        "as_of": str(aligned.index[-1].date()) if hasattr(aligned.index[-1], "date") else str(aligned.index[-1]),
        "close": round(close, 4),
        "crs": round(crs_v, 6),
        "crs_sma_50": round(sma_v, 6),
        "hma": round(hma_v, 4),
        "outperforming": outperforming,
        "hull_buy": hull_buy,
        "crs_cross_up": crs_cross_up,
        "pullback": pullback,
        "verdict": verdict,
        "setup": setup,
        "confidence_pct": confidence,
        "ret_4w_pct": _ret(4),
        "ret_13w_pct": _ret(13),
        "ret_26w_pct": _ret(26),
        "reasons": reasons,
    }


def _universe(market: MarketKind) -> tuple[dict[str, str], str, str]:
    if market == "india":
        return INDIA_SECTORS, INDIA_BENCHMARK, INDIA_BENCHMARK_LABEL
    if market == "us":
        return US_SECTORS, US_BENCHMARK, US_BENCHMARK_LABEL
    return CRYPTO_SECTORS, CRYPTO_BENCHMARK, CRYPTO_BENCHMARK_LABEL


def _dedupe_keep_order(items: list[str], limit: int = _TOP_N) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        s = (raw or "").strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def sector_linked_instruments(market: MarketKind, name: str) -> dict[str, Any]:
    """ETFs linked to a sector plus up to top-20 stocks / theme peers."""
    if market == "india":
        etfs = list(INDIA_SECTOR_ETFS.get(name) or [])
        stocks: list[str] = []
        index_key = INDIA_SECTOR_INDEX_KEY.get(name, name.upper())
        try:
            from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols

            stocks = get_index_constituent_symbols(index_key)
        except Exception as exc:
            logger.debug("India constituents for %s failed: %s", name, exc)
        if not stocks:
            try:
                from app.market_pulse.ticker_utils import INDEX_OPTIONS

                stocks = list(INDEX_OPTIONS.get(index_key) or [])
            except Exception:
                stocks = []
        return {
            "etfs": etfs,
            "top_stocks": _dedupe_keep_order(stocks, _TOP_N),
            "top_stocks_label": "Top stocks (index weight order)",
        }

    if market == "us":
        return {
            "etfs": list(US_SECTOR_ETFS.get(name) or []),
            "top_stocks": _dedupe_keep_order(list(US_SECTOR_TOP_STOCKS.get(name) or []), _TOP_N),
            "top_stocks_label": "Top holdings (approx. by weight)",
        }

    return {
        "etfs": list(CRYPTO_SECTOR_ETFS.get(name) or []),
        "top_stocks": _dedupe_keep_order(list(CRYPTO_THEME_PEERS.get(name) or []), _TOP_N),
        "top_stocks_label": "Theme peers",
    }


def _attach_instruments(row: dict[str, Any], market: MarketKind) -> dict[str, Any]:
    meta = sector_linked_instruments(market, str(row.get("name") or ""))
    row["etfs"] = meta["etfs"]
    row["top_stocks"] = meta["top_stocks"]
    row["top_stocks_label"] = meta["top_stocks_label"]
    return row


def _load_sector_series(
    market: MarketKind, name: str, symbol: str, years: int, *, groww_token: str = "",
) -> pd.Series | None:
    if market == "india":
        proxy = INDIA_SECTOR_FALLBACKS.get(name)
        if proxy:
            s = _groww_weekly(proxy, groww_token, years=years)
            if s is not None:
                return s
    s = _fetch_weekly_close(market, symbol, years=years)
    if s is not None and len(s) >= 40:
        return s
    if market == "india":
        fb = INDIA_SECTOR_FALLBACKS.get(name)
        if fb:
            return _fetch_weekly_close(market, fb, years=years)
    return s


def scan_detect_sector_rotation(
    market: MarketKind,
    *,
    cfg: DetectSectorRotationConfig | None = None,
    sector_filter: list[str] | None = None,
    max_workers: int = 6,
    groww_token: str = "",
) -> dict[str, Any]:
    """Scan all (or filtered) sectors for a market; return ranked rotation snapshot."""
    cfg = cfg or DetectSectorRotationConfig()
    sectors, bench_sym, bench_label = _universe(market)

    if sector_filter:
        sectors = {k: v for k, v in sectors.items() if k in sector_filter}
        if not sectors:
            sectors = dict(_universe(market)[0])

    bench = None
    if market == "india":
        bench = _groww_weekly(INDIA_BENCHMARK_FALLBACK, groww_token, years=cfg.lookback_years)
    if bench is None or len(bench) < cfg.min_weeks:
        bench = _fetch_weekly_close(market, bench_sym, years=cfg.lookback_years)
    if (bench is None or len(bench) < cfg.min_weeks) and market == "india":
        bench = _fetch_weekly_close(market, INDIA_BENCHMARK_FALLBACK, years=cfg.lookback_years)
    if bench is None or len(bench) < cfg.min_weeks:
        return {
            "market": market,
            "error": f"Could not load weekly benchmark {bench_label} ({bench_sym}).",
            "results": [],
            "buy": [],
            "watch": [],
            "avoid": [],
        }

    results: list[dict[str, Any]] = []

    def _one(item: tuple[str, str]) -> dict[str, Any]:
        name, sym = item
        series = _load_sector_series(market, name, sym, cfg.lookback_years, groww_token=groww_token)
        if series is None or len(series) < 40:
            return _attach_instruments({"name": name, "symbol": sym, "error": "No weekly data."}, market)
        row = analyze_sector_pair(series, bench, name=name, symbol=sym, cfg=cfg)
        return _attach_instruments(row, market)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_one, item): item[0] for item in sectors.items()}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append(
                    _attach_instruments({"name": futs[fut], "error": str(exc)[:160]}, market)
                )

    def _rank_key(r: dict) -> tuple:
        order = {"BUY": 0, "WATCH": 1, "AVOID": 2}
        return (order.get(r.get("verdict", "AVOID"), 9), -float(r.get("confidence_pct") or 0))

    ok = [r for r in results if not r.get("error")]
    ok.sort(key=_rank_key)
    err = [r for r in results if r.get("error")]

    buy = [r for r in ok if r.get("verdict") == "BUY"]
    watch = [r for r in ok if r.get("verdict") == "WATCH"]
    avoid = [r for r in ok if r.get("verdict") == "AVOID"]

    return {
        "market": market,
        "benchmark": bench_label,
        "benchmark_symbol": bench_sym,
        "youtube": YOUTUBE_DETECT_SECTOR_ROTATION_URL,
        "config": {
            "crs_sma_period": cfg.crs_sma_period,
            "hma_length": cfg.hma_length,
            "pullback_months": cfg.pullback_months,
            "pullback_mode": cfg.pullback_mode,
        },
        "results": ok + err,
        "buy": buy,
        "watch": watch,
        "avoid": avoid,
        "buy_count": len(buy),
        "watch_count": len(watch),
        "avoid_count": len(avoid),
        "strategy": "Detect Sector Rotation — CRS(50) · Hull(9) · Cyclical Pullback",
    }


def list_sectors(market: MarketKind) -> list[str]:
    return list(_universe(market)[0].keys())
