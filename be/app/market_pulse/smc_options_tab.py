"""
SMC + Options PCR + Delivery/Turnover flow analysis for NSE indices and constituents.
Quant Smart Money scoring plus optional AI refinement per index and ticker.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from app.market_pulse.ai_view import call_ai_report, render_ai_config
from app.market_pulse.groww_auth import get_active_groww_token

logger = logging.getLogger(__name__)


def _news_scanner():
    """Lazy import to avoid circular load with hub_tabs → mega_analyser → smc_options."""
    from truebacktesting import news_scanner
    return news_scanner


from app.market_pulse.nse_index_yfinance import (
    normalize_index_name,
    stock_symbol_to_yf,
)
from app.market_pulse.run_summary import summarize_smc_flow
from app.market_pulse.ta_screener_ui import (
    render_ta_screener_options,
    render_ta_screener_results,
    render_strategy_mtf_panel,
)
from app.market_pulse.ta_ticker_sections import verdict_icon
from app.market_pulse.index_ohlcv import (
    build_constituent_proxy_ohlcv,
    fetch_index_daily_ohlcv_title,
)
from app.market_pulse.nifty_index_constituents import (
    constituent_key_for_index as _constituent_key_for_index,
    get_index_constituent_symbols,
)
from app.market_pulse.ticker_utils import INDEX_OPTIONS
from app.market_pulse.week52_high_low import (
    _get_index_names_by_group,
    fetch_nse_index_constituent_quotes,
    resolve_index_constituents,
)

logger = logging.getLogger(__name__)

# NSE option-chain symbols for index-level PCR
_INDEX_OC_SYMBOL: dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY FINANCIAL SERVICES 25/50": "FINNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "NIFTY MIDCAP SELECT": "MIDCPNIFTY",
    "NIFTY NEXT 50": "NIFTY",
    "NIFTY 100": "NIFTY",
    "NIFTY 200": "NIFTY",
    "NIFTY 500": "NIFTY",
    "NIFTY IT": "NIFTY",
    "NIFTY PHARMA": "NIFTY",
    "NIFTY AUTO": "NIFTY",
    "NIFTY METAL": "NIFTY",
    "NIFTY REALTY": "NIFTY",
    "NIFTY FMCG": "NIFTY",
    "NIFTY ENERGY": "NIFTY",
    "NIFTY PSU BANK": "NIFTY",
    "NIFTY PRIVATE BANK": "NIFTY",
    "NIFTY MEDIA": "NIFTY",
    "NIFTY INFRA": "NIFTY",
    "NIFTY COMMODITIES": "NIFTY",
    "NIFTY CONSUMPTION": "NIFTY",
    "NIFTY INDIA MANUFACTURING": "NIFTY",
    "NIFTY INDIA DIGITAL": "NIFTY",
    "NIFTY HEALTHCARE": "NIFTY",
    "NIFTY OIL & GAS": "NIFTY",
    "NIFTY EV & NEW AGE AUTOMOTIVE": "NIFTY",
    "NIFTY MOBILITY": "NIFTY",
    "NIFTY HOUSING": "NIFTY",
    "NIFTY CORE HOUSING": "NIFTY",
    "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP 25% CAP": "NIFTY",
    "NIFTY INDIA CORPORATE GROUP INDEX - ADITYA BIRLA GROUP": "NIFTY",
    "NIFTY INDIA CORPORATE GROUP INDEX - MAHINDRA GROUP": "NIFTY",
}

_DEFAULT_INDEX_GROUPS = (
    "INDICES ELIGIBLE IN DERIVATIVES",
    "SECTORAL INDICES",
)

def _fallback_index_groups() -> dict[str, list[str]]:
    """Static index universe from INDEX_OPTIONS when NSE breadth is unavailable."""
    broad = [k for k in INDEX_OPTIONS if k != "Default Groww Tickers"]
    fo = [
        n for n in (
            "NIFTY 50", "NIFTY BANK", "NIFTY FINANCIAL SERVICES",
            "NIFTY MIDCAP 150", "NIFTY NEXT 50",
        )
        if n in INDEX_OPTIONS
    ]
    sectoral = [
        n for n in (
            "NIFTY IT", "NIFTY AUTO", "NIFTY FMCG", "NIFTY METAL",
            "NIFTY REALTY", "NIFTY ENERGY", "NIFTY CEMENT", "NIFTY CHEMICALS",
            "NIFTY CONSUMER DURABLES", "NIFTY HEALTHCARE",
            "NIFTY FINANCIAL SERVICES EX-BANK",
        )
        if n in INDEX_OPTIONS
    ]
    return {
        "INDICES ELIGIBLE IN DERIVATIVES": fo,
        "BROAD MARKET INDICES": broad,
        "SECTORAL INDICES": sectoral,
        "THEMATIC INDICES": [],
        "STRATEGY INDICES": [],
    }


def _get_smc_index_groups(breadth: dict | None) -> tuple[dict[str, list[str]], str]:
    """Merge NSE breadth groups with yfinance/INDEX_OPTIONS fallback."""
    nse_groups = _get_index_names_by_group(breadth)
    fallback = _fallback_index_groups()
    merged: dict[str, list[str]] = {}
    used_fallback = False
    for group in _news_scanner()._NIFTY_BREADTH_GROUP_ORDER:
        names = [n for n in (nse_groups.get(group) or []) if n]
        if not names:
            names = list(fallback.get(group) or [])
            if names:
                used_fallback = True
        merged[group] = names
    if not any(merged.values()):
        merged = fallback
        used_fallback = True
    source = "yfinance / local index lists" if used_fallback or not breadth else "NSE allIndices"
    return merged, source


def _as_float(val: Any) -> float:
    """Coerce scalar, Series, or ndarray element to float (avoids ambiguous truth tests)."""
    if val is None:
        return float("nan")
    if isinstance(val, pd.Series):
        val = val.iloc[0] if len(val) else np.nan
    elif isinstance(val, pd.DataFrame):
        val = val.iloc[0, 0] if val.size else np.nan
    elif isinstance(val, np.ndarray):
        val = val.flat[0] if val.size else np.nan
    return float(val)


def _first_nonempty_df(*candidates: pd.DataFrame | None) -> pd.DataFrame | None:
    """Return first non-empty DataFrame (never use `df1 or df2` — ambiguous truth)."""
    for df in candidates:
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            return df
    return None


_OHLC_FIELD_NAMES = frozenset({"open", "high", "low", "close", "volume", "adj close"})


def _ohlc_level_from_multiindex(columns: pd.MultiIndex) -> int:
    """Return MultiIndex level that holds Open/High/Low/Close (0 or 1)."""
    if columns.nlevels < 2:
        return 0
    lv0 = {str(x).strip().lower() for x in columns.get_level_values(0)}
    lv1 = {str(x).strip().lower() for x in columns.get_level_values(1)}
    if lv0 & _OHLC_FIELD_NAMES:
        return 0
    if lv1 & _OHLC_FIELD_NAMES:
        return 1
    return 0


def _df_ohlc_series(df: pd.DataFrame, col: str) -> pd.Series:
    """Single numeric series for an OHLC column (handles duplicate/MultiIndex fallout)."""
    if col not in df.columns:
        return pd.Series(dtype=float)
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return pd.to_numeric(s, errors="coerce").squeeze()


def _flatten_ohlc_dataframe(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Normalize yfinance OHLC to single non-duplicated Open/High/Low/Close columns."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        level = _ohlc_level_from_multiindex(out.columns)
        out.columns = [
            str(c[level]).lower()
            if isinstance(c, tuple) and len(c) > level
            else str(c).lower()
            for c in out.columns
        ]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    rename = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "adj close": "Adj Close",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    if out.columns.duplicated().any():
        out = out.loc[:, ~out.columns.duplicated()]
    needed = [c for c in ("Open", "High", "Low", "Close") if c in out.columns]
    if len(needed) < 4:
        return None
    for col in needed + (["Volume"] if "Volume" in out.columns else []):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=needed, how="any")
    return out if not out.empty else None


def _normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame | None:
    return _flatten_ohlc_dataframe(df)


def _extract_yf_ticker_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Pull one ticker's OHLC block from a yfinance multi-ticker download."""
    if raw is None or raw.empty:
        return None
    if not isinstance(raw.columns, pd.MultiIndex):
        return raw
    lv0 = raw.columns.get_level_values(0)
    lv1 = raw.columns.get_level_values(1) if raw.columns.nlevels > 1 else pd.Index([])
    if ticker in lv0:
        return raw[ticker]
    if ticker in lv1:
        return raw.xs(ticker, axis=1, level=1)
    if {str(x).lower() for x in lv0} & _OHLC_FIELD_NAMES:
        return raw
    return None


def _is_valid_price(val: Any) -> bool:
    f = _as_float(val)
    return not np.isnan(f) and f > 0


def _lookup_stock_flow(stock_lookup: dict[str, dict], sym: str) -> dict[str, float]:
    """Resolve bhavcopy row for an NSE symbol (case / punctuation tolerant)."""
    sym_u = (sym or "").strip().upper()
    if not sym_u:
        return {}
    if sym_u in stock_lookup:
        return stock_lookup[sym_u]
    compact = re.sub(r"[^A-Z0-9]", "", sym_u)
    for key, row in stock_lookup.items():
        if key == sym_u:
            return row
        if re.sub(r"[^A-Z0-9]", "", key) == compact:
            return row
    return {}


def _resolve_last_and_pct(
    quote: dict,
    flat_df: pd.DataFrame | None,
    flow: dict[str, float],
) -> tuple[float | None, float | None]:
    """Fill LTP and day % change from quote, OHLCV, or bhavcopy close."""
    last = quote.get("last")
    pct = quote.get("pct_chg")
    if not _is_valid_price(last) and flat_df is not None and not flat_df.empty and "Close" in flat_df.columns:
        last = _as_float(flat_df["Close"].iloc[-1])
    close_flow = flow.get("close")
    if not _is_valid_price(last) and close_flow is not None and _is_valid_price(close_flow):
        last = _as_float(close_flow)
    if pct is None and flat_df is not None and len(flat_df) >= 2 and "Close" in flat_df.columns:
        prev = _as_float(flat_df["Close"].iloc[-2])
        cur = _as_float(last) if _is_valid_price(last) else _as_float(flat_df["Close"].iloc[-1])
        if prev > 0 and _is_valid_price(cur):
            pct = (cur / prev - 1) * 100
    if not _is_valid_price(last):
        last = None
    if pct is not None and np.isnan(_as_float(pct)):
        pct = None
    return last, pct


def fetch_yfinance_stock_quotes(symbols: tuple[str, ...]) -> list[dict]:
    """Last price and 1-day % change via yfinance (NSE .NS tickers)."""
    if not symbols:
        return []
    tickers = [stock_symbol_to_yf(s) for s in symbols]
    try:
        raw = yf.download(
            tickers,
            period="5d",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
            auto_adjust=True,
        )
    except Exception as e:
        logger.error(f"yfinance quotes error: {e}")
        return []
    if raw is None or raw.empty:
        return []

    out: list[dict] = []
    got: set[str] = set()
    for sym in symbols:
        t = stock_symbol_to_yf(sym)
        try:
            if len(symbols) == 1:
                block = raw.dropna(how="all")
            else:
                block = _extract_yf_ticker_frame(raw, t)
            if block is None:
                continue
            sub = _normalize_ohlcv_columns(block)
            if sub is None or sub.empty or "Close" not in sub.columns:
                continue
            last, pct_chg = _resolve_last_and_pct({}, sub, {})
            if not _is_valid_price(last):
                continue
            out.append({
                "symbol": sym,
                "last": last,
                "pct_chg": pct_chg,
                "year_high": None,
                "year_low": None,
                "source": "yfinance",
            })
            got.add(sym.upper())
        except Exception:
            continue

    missing = [s for s in symbols if s.upper() not in got]
    for sym in missing[:30]:
        try:
            raw_one = yf.download(
                stock_symbol_to_yf(sym),
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            sub = _normalize_ohlcv_columns(raw_one.dropna(how="all") if raw_one is not None else None)
            if sub is None or sub.empty:
                continue
            last, pct_chg = _resolve_last_and_pct({}, sub, {})
            if not _is_valid_price(last):
                continue
            out.append({
                "symbol": sym,
                "last": last,
                "pct_chg": pct_chg,
                "year_high": None,
                "year_low": None,
                "source": "yfinance",
            })
        except Exception:
            continue
    return out


def fetch_index_ohlcv_yfinance(index_name: str) -> pd.DataFrame | None:
    """Daily OHLC for an NSE index (Yahoo index ticker or constituent proxy)."""
    return fetch_index_daily_ohlcv_title(index_name, period="6mo")


def _quotes_from_yfinance_symbols(symbols: list[str]) -> list[dict]:
    """Build quote rows from yfinance when NSE live quotes are unavailable."""
    if not symbols:
        return []
    rows = fetch_yfinance_stock_quotes(tuple(symbols))
    return [{
        "symbol": r["symbol"],
        "last": r.get("last"),
        "pct_chg": r.get("pct_chg"),
        "year_high": r.get("year_high"),
        "year_low": r.get("year_low"),
        "source": r.get("source", "yfinance"),
    } for r in rows]


def _nse_constituent_symbol_list(index_name: str, limit: int = 150) -> list[str]:
    """Symbol list from static/CSV lists, INDEX_OPTIONS, then NSE API."""
    from app.market_pulse.news_scanner import _fetch_nse_index_constituent_symbols

    static = get_index_constituent_symbols(index_name)
    if static:
        return static[:limit]

    key = _constituent_key_for_index(index_name)
    if key:
        symbols = INDEX_OPTIONS.get(key) or []
        if symbols:
            return symbols[:limit]

    names = list(dict.fromkeys([
        index_name,
        normalize_index_name(index_name),
    ]))
    for candidate in names:
        symbols = _fetch_nse_index_constituent_symbols(candidate)
        if symbols:
            return symbols[:limit]
    return []


def resolve_index_constituent_quotes(index_name: str) -> list[dict]:
    """NSE live quotes first; yfinance + INDEX_OPTIONS + NSE symbol list fallback."""
    stocks = resolve_index_constituents(index_name)
    if not stocks:
        symbols = _nse_constituent_symbol_list(index_name)
        if symbols:
            stocks = _quotes_from_yfinance_symbols(symbols)
    if not stocks:
        return []
    out: list[dict] = []
    for s in stocks:
        sym = (s.get("symbol") or "").strip()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "last": s.get("last"),
            "pct_chg": s.get("pct_chg"),
            "year_high": s.get("year_high"),
            "year_low": s.get("year_low"),
            "source": s.get("source", "nse"),
        })
    if out and out[0].get("source") != "nse":
        logger.info(f"SMC: using yfinance constituents for {index_name} ({len(out)} stocks)")
    return out


def fetch_bhavcopy_stock_lookup() -> dict[str, dict[str, float]]:
    """Full EQ bhavcopy map: symbol -> turnover, delivery_pct, volume, close."""
    try:
        session = requests.Session()
        _news_scanner()._warm_nse_session(session, "/market-data/live-equity-market")
        csv_text = None
        today = datetime.now().date()
        for offset in range(0, 12):
            dt = today - timedelta(days=offset)
            if dt.weekday() >= 5:
                continue
            csv_text = _news_scanner()._fetch_bhavcopy_csv(session, dt)
            if csv_text:
                break
        if not csv_text:
            return {}
        stocks = _news_scanner()._parse_bhavcopy_eq_stocks(csv_text)
        out: dict[str, dict[str, float]] = {}
        for s in stocks:
            sym = (s.get("symbol") or "").strip().upper()
            if not sym:
                continue
            turnover_lacs = float(s.get("turnover_lacs") or 0)
            out[sym] = {
                "turnover_cr": round(turnover_lacs / 100, 4),
                "delivery_pct": float(s.get("deliv_per") or 0),
                "volume": float(s.get("qty") or 0),
                "close": float(s.get("close") or 0),
            }
        return out
    except Exception as e:
        logger.error(f"Bhavcopy stock lookup error: {e}")
        return {}


def _swing_points(high: pd.Series, low: pd.Series, window: int = 3) -> tuple[list[float], list[float]]:
    sh, sl = [], []
    high = pd.to_numeric(high, errors="coerce").squeeze()
    low = pd.to_numeric(low, errors="coerce").squeeze()
    if isinstance(high, pd.DataFrame):
        high = high.iloc[:, 0]
    if isinstance(low, pd.DataFrame):
        low = low.iloc[:, 0]
    if not isinstance(high, pd.Series):
        high = pd.Series(high)
    if not isinstance(low, pd.Series):
        low = pd.Series(low)
    n = len(high)
    for i in range(window, n - window):
        h_slice = high.iloc[i - window : i + window + 1]
        l_slice = low.iloc[i - window : i + window + 1]
        hi = _as_float(high.iloc[i])
        lo = _as_float(low.iloc[i])
        if hi >= _as_float(h_slice.max()):
            sh.append(hi)
        if lo <= _as_float(l_slice.min()):
            sl.append(lo)
    return sh[-4:], sl[-4:]


def analyze_smc_from_ohlcv(df: pd.DataFrame) -> dict[str, Any]:
    """Smart Money Concepts: structure, premium/discount, liquidity sweep hint."""
    if df is None or df.empty or len(df) < 15:
        return {
            "structure": "Insufficient data",
            "bias": "Neutral",
            "zone": "Equilibrium",
            "sweep": False,
            "swing_highs": [],
            "swing_lows": [],
        }
    df = _flatten_ohlc_dataframe(df)
    if df is None or df.empty:
        return {
            "structure": "Insufficient data",
            "bias": "Neutral",
            "zone": "Equilibrium",
            "sweep": False,
            "swing_highs": [],
            "swing_lows": [],
        }
    high_s = _df_ohlc_series(df, "High")
    low_s = _df_ohlc_series(df, "Low")
    close_s = _df_ohlc_series(df, "Close")
    open_s = _df_ohlc_series(df, "Open")
    if high_s.empty or low_s.empty or close_s.empty or open_s.empty:
        return {"structure": "No OHLC", "bias": "Neutral", "zone": "Equilibrium", "sweep": False}
    sh, sl = _swing_points(high_s, low_s)
    structure = "Ranging / Mixed"
    bias = "Neutral"
    if len(sh) >= 2 and len(sl) >= 2:
        hh = sh[-1] > sh[-2]
        hl = sl[-1] > sl[-2]
        lh = sh[-1] < sh[-2]
        ll = sl[-1] < sl[-2]
        if hh and hl:
            structure, bias = "Bullish BOS (HH/HL)", "Bullish"
        elif lh and ll:
            structure, bias = "Bearish BOS (LH/LL)", "Bearish"
        elif hh and ll:
            structure, bias = "Expansion / Volatile", "Neutral"
    lookback = min(20, len(df))
    r_high = _as_float(high_s.iloc[-lookback:].max())
    r_low = _as_float(low_s.iloc[-lookback:].min())
    last = _as_float(close_s.iloc[-1])
    if r_high > r_low:
        pos = (last - r_low) / (r_high - r_low)
        if pos >= 0.62:
            zone = "Premium (sell-side liquidity)"
        elif pos <= 0.38:
            zone = "Discount (buy-side liquidity)"
        else:
            zone = "Equilibrium"
    else:
        zone = "Equilibrium"
    sweep = False
    if len(df) >= 3:
        prev_low = _as_float(low_s.iloc[-3:-1].min())
        prev_high = _as_float(high_s.iloc[-3:-1].max())
        last_low = _as_float(low_s.iloc[-1])
        last_high = _as_float(high_s.iloc[-1])
        last_close = _as_float(close_s.iloc[-1])
        if last_low < prev_low and last_close > prev_low:
            sweep = True
        if last_high > prev_high and last_close < prev_high:
            sweep = True
    return {
        "structure": structure,
        "bias": bias,
        "zone": zone,
        "sweep": sweep,
        "swing_highs": sh,
        "swing_lows": sl,
        "range_high": r_high,
        "range_low": r_low,
        "last_close": last,
    }


def fetch_daily_ohlcv_batch(symbols: tuple[str, ...], days: int = 60) -> dict[str, pd.DataFrame]:
    if not symbols:
        return {}
    tickers = [stock_symbol_to_yf(s) for s in symbols]
    try:
        raw = yf.download(
            tickers,
            period=f"{max(days, 30)}d",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.error(f"yfinance batch error: {e}")
        return {}
    if raw is None or getattr(raw, "empty", True):
        return {}
    out: dict[str, pd.DataFrame] = {}
    if len(symbols) == 1:
        sym = symbols[0]
        flat = _flatten_ohlc_dataframe(raw.dropna(how="all"))
        if flat is not None and not flat.empty:
            out[sym] = flat
        return out
    for sym in symbols:
        t = stock_symbol_to_yf(sym)
        try:
            block = _extract_yf_ticker_frame(raw, t)
            if block is None:
                continue
            flat = _flatten_ohlc_dataframe(block.dropna(how="all"))
            if flat is not None and not flat.empty:
                out[sym.upper()] = flat
                out[sym] = flat
        except Exception:
            continue
    return out


def _flow_scores(flow: dict[str, float], median_delivery: float, median_turnover: float) -> dict[str, Any]:
    d = _as_float(flow.get("delivery_pct", 0))
    t = _as_float(flow.get("turnover_cr", 0))
    median_delivery = _as_float(median_delivery)
    median_turnover = _as_float(median_turnover)
    delivery_signal = "Neutral"
    if median_delivery > 0:
        if d >= median_delivery * 1.25:
            delivery_signal = "High delivery — institutional accumulation"
        elif d <= median_delivery * 0.75:
            delivery_signal = "Low delivery — speculative churn"
    turnover_signal = "Normal"
    if median_turnover > 0:
        if t >= median_turnover * 1.5:
            turnover_signal = "Turnover spike — smart money participation"
        elif t <= median_turnover * 0.5:
            turnover_signal = "Thin turnover — low conviction"
    return {
        "delivery_pct": d,
        "turnover_cr": t,
        "delivery_signal": delivery_signal,
        "turnover_signal": turnover_signal,
    }


def _pcr_adjustment(pcr_data: dict | None) -> tuple[float, str]:
    if not pcr_data:
        return 0.0, "No index PCR"
    pcr = float(pcr_data.get("pcr") or 1.0)
    label = str(pcr_data.get("label") or "")
    adj = 0.0
    note = f"PCR {pcr:.2f} ({label})"
    if pcr >= 1.35:
        adj = 0.8
        note += " — put heavy, contrarian bullish bias"
    elif pcr <= 0.65:
        adj = -0.8
        note += " — call heavy, contrarian bearish bias"
    elif 0.85 <= pcr <= 1.15:
        adj = 0.0
        note += " — balanced"
    return adj, note


def predict_next_move(
    *,
    smc: dict,
    flow: dict[str, float] | None,
    pcr_data: dict | None,
    pct_chg: float | None,
    median_delivery: float = 0,
    median_turnover: float = 0,
    is_index: bool = False,
) -> dict[str, Any]:
    """Quant Smart Money prediction: direction, confidence, 1–5 session bias."""
    score = 0.0
    reasons: list[str] = []

    bias = smc.get("bias", "Neutral")
    if bias == "Bullish":
        score += 2.0
        reasons.append(f"SMC structure bullish ({smc.get('structure', '')})")
    elif bias == "Bearish":
        score -= 2.0
        reasons.append(f"SMC structure bearish ({smc.get('structure', '')})")

    zone = smc.get("zone", "")
    if "Discount" in zone:
        score += 1.2
        reasons.append("Price in discount zone — buy-side liquidity favored")
    elif "Premium" in zone:
        score -= 1.2
        reasons.append("Price in premium zone — sell-side liquidity favored")

    if smc.get("sweep"):
        if bias == "Bullish":
            score += 0.8
            reasons.append("Bullish liquidity sweep (stop hunt then reclaim)")
        elif bias == "Bearish":
            score -= 0.8
            reasons.append("Bearish liquidity sweep")
        else:
            reasons.append("Liquidity sweep detected — watch CHoCH")

    if flow:
        fs = _flow_scores(flow, median_delivery, median_turnover)
        d = fs["delivery_pct"]
        if "accumulation" in fs["delivery_signal"]:
            score += 1.0
            reasons.append(fs["delivery_signal"])
        elif "speculative" in fs["delivery_signal"]:
            score -= 0.5
            reasons.append(fs["delivery_signal"])
        if "spike" in fs["turnover_signal"].lower():
            score += 0.4 if score >= 0 else -0.4
            reasons.append(fs["turnover_signal"])

    if is_index and pcr_data:
        adj, pnote = _pcr_adjustment(pcr_data)
        score += adj
        reasons.append(pnote)

    if pct_chg is not None:
        if pct_chg > 1.5:
            score += 0.3
        elif pct_chg < -1.5:
            score -= 0.3

    confidence = min(92, max(38, 50 + abs(score) * 8))
    if score >= 1.5:
        direction = "Bullish"
        verdict = "BUY"
        next_move = "Higher — expect continuation toward range high / BOS upside"
    elif score <= -1.5:
        direction = "Bearish"
        verdict = "SELL"
        next_move = "Lower — expect pullback toward range low / BOS downside"
    else:
        direction = "Sideways"
        verdict = "HOLD"
        next_move = "Range-bound — wait for CHoCH or delivery confirmation"

    sessions = []
    step = score / 5
    base = _as_float(smc.get("last_close") or 0)
    if np.isnan(base):
        base = 0.0
    for i in range(1, 6):
        if base > 0:
            pct = step * i * 0.15
            proj = base * (1 + pct / 100)
            sessions.append({"session": i, "bias_pct": round(pct, 2), "level": round(proj, 2)})
        else:
            sessions.append({"session": i, "bias_pct": round(step * i * 0.1, 2), "level": None})

    return {
        "direction": direction,
        "verdict": verdict,
        "confidence": round(confidence, 1),
        "score": round(score, 2),
        "next_move": next_move,
        "reasons": reasons[:8],
        "sessions": sessions,
    }


def _parse_ai_json(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _build_index_proxy_ohlcv(ohlcv_map: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    """Equal-weight average OHLC across constituents as index SMC proxy."""
    proxy = build_constituent_proxy_ohlcv(ohlcv_map)
    if proxy is None:
        return None
    return _flatten_ohlc_dataframe(proxy.rename(columns=str.title))


def refine_prediction_with_ai(
    *,
    name: str,
    kind: str,
    quant: dict,
    smc: dict,
    flow: dict | None,
    pcr: dict | None,
    provider: str,
    model: str,
    api_key: str,
) -> dict | None:
    prompt = f"""You are an Indian equity Smart Money Concepts (SMC) analyst.
Analyze {kind}: {name}

Quant baseline:
{json.dumps(quant, indent=2)}

SMC:
{json.dumps(smc, indent=2)}

Delivery/Turnover:
{json.dumps(flow or {}, indent=2)}

Options PCR (if index):
{json.dumps(pcr or {}, indent=2)}

Use SMC (BOS, CHoCH, premium/discount, liquidity), PCR positioning, and delivery/turnover for institutional flow.
Return ONLY valid JSON:
{{
  "direction": "Bullish|Bearish|Sideways",
  "verdict": "BUY|SELL|HOLD",
  "confidence": 0-100,
  "next_move": "one sentence what price does next 1-5 sessions",
  "smc_note": "key SMC level or event",
  "flow_note": "delivery/turnover interpretation",
  "sessions": [{{"session": 1, "bias": "up|down|flat", "note": "..."}}]
}}"""
    system = (
        "You are an Indian equity Smart Money Concepts analyst. "
        "Return ONLY valid JSON as specified — no markdown fences."
    )
    try:
        raw = call_ai_report(
            prompt,
            system,
            provider,
            model,
            api_key,
            user_intro="SMC flow prediction JSON:",
            max_tokens=1200,
        )
        parsed = _parse_ai_json(raw)
        if parsed:
            parsed["ai_raw"] = raw[:500]
            return parsed
    except Exception as e:
        logger.error(f"SMC AI error ({name}): {e}")
    return None


def analyze_index(
    index_name: str,
    stock_lookup: dict[str, dict],
    groww_token: str | None,
    max_stocks: int,
) -> dict[str, Any]:
    oc_sym = _INDEX_OC_SYMBOL.get(index_name)
    pcr_block: dict | None = None
    oc_sentiment: dict | None = None
    if oc_sym:
        try:
            oc = _news_scanner().fetch_nse_option_chain(oc_sym, groww_token or "")
            if oc:
                oc_sentiment = _news_scanner().analyze_options_sentiment(oc)
                pcr_block = {
                    "pcr": oc.get("pcr_oi"),
                    "label": oc_sentiment.get("verdict"),
                    "max_pain": oc.get("max_pain"),
                    "score": oc_sentiment.get("score"),
                }
        except Exception as e:
            logger.warning(f"Option chain {index_name}: {e}")

    quotes = resolve_index_constituent_quotes(index_name)
    index_df = fetch_index_ohlcv_yfinance(index_name)

    if not quotes:
        symbols = _nse_constituent_symbol_list(index_name, limit=max_stocks)
        if symbols:
            quotes = _quotes_from_yfinance_symbols(symbols[:max_stocks])

    if (index_df is None or index_df.empty) and not quotes:
        symbols = _nse_constituent_symbol_list(index_name, limit=max_stocks)
        if symbols:
            ohlcv_map = fetch_daily_ohlcv_batch(tuple(symbols[:max_stocks]))
            index_df = _build_index_proxy_ohlcv(ohlcv_map)

    if not quotes and (index_df is None or index_df.empty):
        return {
            "index": index_name,
            "error": "No constituents and no yfinance index OHLC",
            "tickers": [],
        }

    symbols = [q["symbol"] for q in quotes[:max_stocks]] if quotes else []
    del_vals = [
        float(_lookup_stock_flow(stock_lookup, s).get("delivery_pct", 0) or 0)
        for s in symbols
        if _lookup_stock_flow(stock_lookup, s)
    ]
    turn_vals = [
        float(_lookup_stock_flow(stock_lookup, s).get("turnover_cr", 0) or 0)
        for s in symbols
        if _lookup_stock_flow(stock_lookup, s)
    ]
    med_del = float(np.median(del_vals)) if del_vals else 0.0
    med_turn = float(np.median(turn_vals)) if turn_vals else 0.0

    ohlcv_map = fetch_daily_ohlcv_batch(tuple(symbols)) if symbols else {}

    pct_vals = [float(q.get("pct_chg") or 0) for q in quotes if q.get("pct_chg") is not None]
    index_pct = float(np.nanmean(pct_vals)) if pct_vals else 0.0
    if not quotes and index_df is not None and len(index_df) >= 2 and "Close" in index_df.columns:
        last_i = _as_float(index_df["Close"].iloc[-1])
        prev_i = _as_float(index_df["Close"].iloc[-2])
        if prev_i > 0:
            index_pct = (last_i / prev_i - 1) * 100
    agg_flow = {
        "delivery_pct": float(np.nanmean([
            _lookup_stock_flow(stock_lookup, s).get("delivery_pct", 0) for s in symbols
        ])) if symbols else 0.0,
        "turnover_cr": float(np.nansum([
            _lookup_stock_flow(stock_lookup, s).get("turnover_cr", 0) for s in symbols
        ])) if symbols else 0.0,
    }
    proxy = _build_index_proxy_ohlcv(ohlcv_map)
    if index_df is not None and not index_df.empty and len(index_df) >= 15:
        index_smc = analyze_smc_from_ohlcv(index_df)
        index_smc["data_source"] = "yfinance_index"
    elif proxy is not None and not proxy.empty:
        index_smc = analyze_smc_from_ohlcv(proxy)
        index_smc["data_source"] = "yfinance_proxy"
    else:
        index_smc = {
            "structure": "Proxy unavailable",
            "bias": "Neutral",
            "zone": "Equilibrium",
            "sweep": False,
            "data_source": "none",
        }
    if quotes:
        last_vals = [_as_float(q.get("last") or 0) for q in quotes]
        index_smc["last_close"] = float(np.nanmean(last_vals)) if last_vals else 0.0
    elif index_df is not None and "Close" in index_df.columns:
        index_smc["last_close"] = _as_float(index_df["Close"].iloc[-1])

    index_pred = predict_next_move(
        smc=index_smc,
        flow=agg_flow,
        pcr_data=pcr_block,
        pct_chg=index_pct,
        median_delivery=med_del,
        median_turnover=med_turn,
        is_index=True,
    )

    ticker_rows: list[dict] = []
    for q in quotes[:max_stocks]:
        sym = q["symbol"]
        flow_row = _lookup_stock_flow(stock_lookup, sym)
        raw_df = _first_nonempty_df(ohlcv_map.get(sym), ohlcv_map.get(sym.upper()))
        flat_df = _flatten_ohlc_dataframe(raw_df)
        last, pct_chg = _resolve_last_and_pct(q, flat_df, flow_row)
        smc = analyze_smc_from_ohlcv(flat_df) if flat_df is not None and not flat_df.empty else {
            "structure": "No history",
            "bias": "Neutral",
            "zone": "Equilibrium",
            "sweep": False,
            "last_close": last,
        }
        if not _is_valid_price(smc.get("last_close")):
            smc["last_close"] = last
        flow_scores = _flow_scores(flow_row, med_del, med_turn)
        pred = predict_next_move(
            smc=smc,
            flow=flow_row or None,
            pcr_data=None,
            pct_chg=pct_chg,
            median_delivery=med_del,
            median_turnover=med_turn,
            is_index=False,
        )
        ticker_rows.append({
            "symbol": sym,
            "last": last,
            "pct_chg": pct_chg,
            "smc": smc,
            "flow": flow_scores,
            "prediction": pred,
        })

    quote_source = quotes[0].get("source", "nse") if quotes else "unknown"
    return {
        "index": index_name,
        "oc_symbol": oc_sym,
        "pcr": pcr_block,
        "oc_sentiment": oc_sentiment,
        "constituent_count": len(quotes),
        "constituent_source": quote_source,
        "index_smc": index_smc,
        "index_prediction": index_pred,
        "tickers": ticker_rows,
    }


def _display_num(val: Any, decimals: int = 2) -> float | None:
    if val is None:
        return None
    f = _as_float(val)
    if np.isnan(f):
        return None
    return round(f, decimals)


def _verdict_color(verdict: str) -> str:
    v = (verdict or "").upper()
    if v == "BUY":
        return "🟢"
    if v == "SELL":
        return "🔴"
    return "🟡"


def render_smc_options_tab() -> None:
    st.subheader("SMC · Options PCR · Delivery & Turnover")
    st.caption(
        "Smart Money Concepts structure, index PCR, bhavcopy delivery/turnover, "
        "and quant + AI next-move forecast for each index and constituent."
    )

    from app.market_pulse.ta_mtf_hub_ui import render_ta_hub_badge

    render_ta_hub_badge("smc_options")

    if "smc_flow_loaded" not in st.session_state:
        st.session_state.smc_flow_loaded = False
    if "smc_flow_results" not in st.session_state:
        st.session_state.smc_flow_results = []

    ai_provider, ai_model, ai_key = render_ai_config(key_prefix="smc_flow")

    breadth = _news_scanner().fetch_nse_market_breadth()
    index_groups, group_source = _get_smc_index_groups(breadth)
    available_groups = [g for g in _news_scanner()._NIFTY_BREADTH_GROUP_ORDER if index_groups.get(g)]
    if not available_groups:
        available_groups = [g for g, names in index_groups.items() if names]

    if group_source != "NSE allIndices":
        st.caption(
            f"Index universe: **{group_source}** (NSE breadth unavailable — "
            "using Yahoo Finance + built-in index lists)."
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        groups = st.multiselect(
            "Index groups",
            available_groups,
            default=[g for g in _DEFAULT_INDEX_GROUPS if g in available_groups] or available_groups[:2],
            format_func=lambda g: _news_scanner()._NIFTY_BREADTH_GROUP_LABELS.get(g, g),
            key="smc_flow_index_groups",
        )
    with c2:
        max_indices = st.slider("Max indices per group", 1, 25, 8)
    with c3:
        max_stocks = st.slider("Max stocks per index", 5, 50, 20)

    use_ai = st.checkbox("AI refine predictions (index + each ticker)", value=False)
    smc_actionable_only = render_ta_screener_options("smc_flow")
    groww_token = st.session_state.get("groww_token") or ""

    if st.button("🔎 SCAN SMC · PCR · FLOW SETUPS", type="primary", key="smc_flow_run"):
        st.session_state.smc_flow_loaded = True
        selected_indices: list[str] = []
        for g in groups:
            for idx in (index_groups.get(g) or [])[:max_indices]:
                if idx not in selected_indices:
                    selected_indices.append(idx)

        if not selected_indices:
            st.warning("Select at least one index group with indices.")
            st.session_state.smc_flow_results = []
        else:
            fetch_bhavcopy_stock_lookup.clear()
            fetch_daily_ohlcv_batch.clear()
            fetch_yfinance_stock_quotes.clear()
            fetch_nse_index_constituent_quotes.clear()
            fetch_index_ohlcv_yfinance.clear()
            stock_lookup = fetch_bhavcopy_stock_lookup()
            fii_dii = _news_scanner().fetch_nse_fii_dii()
            results: list[dict] = []
            prog = st.progress(0, text="Scanning indices…")
            for i, idx_name in enumerate(selected_indices):
                prog.progress((i + 1) / len(selected_indices), text=f"Analyzing {idx_name}…")
                try:
                    row = analyze_index(idx_name, stock_lookup, groww_token or None, max_stocks)
                    if use_ai and ai_key:
                        ip = row.get("index_prediction", {})
                        ai_idx = refine_prediction_with_ai(
                            name=idx_name,
                            kind="index",
                            quant=ip,
                            smc=row.get("index_smc", {}),
                            flow={
                                "delivery_pct": np.mean([
                                    t.get("flow", {}).get("delivery_pct", 0)
                                    for t in row.get("tickers", [])
                                ]) if row.get("tickers") else 0,
                            },
                            pcr=row.get("pcr"),
                            provider=ai_provider,
                            model=ai_model,
                            api_key=ai_key,
                        )
                        if ai_idx:
                            row["index_prediction_ai"] = ai_idx
                        for t in row.get("tickers", []):
                            ai_t = refine_prediction_with_ai(
                                name=t["symbol"],
                                kind="stock",
                                quant=t.get("prediction", {}),
                                smc=t.get("smc", {}),
                                flow=t.get("flow", {}),
                                pcr=None,
                                provider=ai_provider,
                                model=ai_model,
                                api_key=ai_key,
                            )
                            if ai_t:
                                t["prediction_ai"] = ai_t
                    results.append(row)
                except Exception as e:
                    results.append({"index": idx_name, "error": str(e), "tickers": []})
            prog.empty()
            st.session_state.smc_flow_results = results
            st.session_state.smc_fii_dii = fii_dii

    if not st.session_state.smc_flow_loaded:
        st.info("Click **Run SMC · PCR · Flow Analysis** to load data (not fetched on page open).")
        return

    results: list[dict] = st.session_state.smc_flow_results or []
    if not results:
        st.warning("No results — run the scan.")
        return

    fii = st.session_state.get("smc_fii_dii") or {}
    if fii:
        fii_net = (fii.get("fii") or {}).get("net_cr")
        dii_net = (fii.get("dii") or {}).get("net_cr")
        combined = (fii_net or 0) + (dii_net or 0) if fii_net is not None and dii_net is not None else None
        fc1, fc2, fc3 = st.columns(3)
        fc1.metric("FII net (₹ Cr)", f"{fii_net:,.0f}" if fii_net is not None else "—")
        fc2.metric("DII net (₹ Cr)", f"{dii_net:,.0f}" if dii_net is not None else "—")
        fc3.metric("FII+DII", f"{combined:,.0f}" if combined is not None else "—")

    summaries: list[dict] = []
    for row in results:
        idx = row.get("index", "?")
        if row.get("error"):
            st.error(f"{idx}: {row['error']}")
            continue

        pred = row.get("index_prediction", {})
        pcr = row.get("pcr") or {}
        with st.expander(
            f"{_verdict_color(pred.get('verdict', ''))} **{idx}** — "
            f"{pred.get('direction', '—')} ({pred.get('confidence', 0)}% conf)",
            expanded=False,
        ):
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Verdict", pred.get("verdict", "—"))
            m2.metric("Confidence", f"{pred.get('confidence', 0)}%")
            m3.metric("PCR", f"{pcr.get('pcr', '—')}" if pcr else "N/A")
            m4.metric("Constituents", row.get("constituent_count", 0))

            st.markdown(f"**Next move:** {pred.get('next_move', '—')}")
            smc = row.get("index_smc", {})
            src = row.get("constituent_source", "nse")
            smc_src = smc.get("data_source", "")
            st.markdown(
                f"**SMC:** {smc.get('structure', '—')} · **Zone:** {smc.get('zone', '—')} · "
                f"**Bias:** {smc.get('bias', '—')} · "
                f"**Data:** constituents={src}"
                f"{f', index OHLC={smc_src}' if smc_src else ''}"
            )
            if pred.get("reasons"):
                st.markdown("**Quant reasons:**")
                for r in pred["reasons"]:
                    st.markdown(f"- {r}")

            if row.get("index_prediction_ai"):
                ai = row["index_prediction_ai"]
                st.success(
                    f"**AI:** {ai.get('verdict', '—')} — {ai.get('direction', '')} "
                    f"({ai.get('confidence', '?')}%) · {ai.get('next_move', '')}"
                )

            sess = pred.get("sessions") or []
            if sess:
                st.markdown("**1–5 session bias (quant)**")
                st.dataframe(
                    pd.DataFrame(sess),
                    width='stretch',
                    hide_index=True,
                )

            tickers = row.get("tickers") or []
            if tickers:
                st.markdown("#### Constituent tickers")
                overview = pd.DataFrame([
                    {
                        "Symbol": t["symbol"],
                        "LTP": _display_num(t.get("last")),
                        "Chg%": _display_num(t.get("pct_chg")),
                        "Verdict": t.get("prediction", {}).get("verdict"),
                        "Conf%": _display_num(t.get("prediction", {}).get("confidence"), 1),
                    }
                    for t in tickers
                ])
                st.dataframe(overview, width='stretch', hide_index=True)

                for t in tickers:
                    sym = t["symbol"]
                    tp = t.get("prediction", {})
                    smc = t.get("smc", {})
                    flow = t.get("flow", {})
                    ai_t = t.get("prediction_ai")
                    verdict = tp.get("verdict", "—")
                    with st.expander(
                        f"{verdict_icon(verdict)} **{sym}** — {verdict} "
                        f"({tp.get('confidence', 0)}%) · {smc.get('bias', '—')} · "
                        f"LTP {_display_num(t.get('last')) or '—'}",
                        expanded=False,
                    ):
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("LTP", _display_num(t.get("last")) or "—")
                        c2.metric("Chg%", _display_num(t.get("pct_chg")) or "—")
                        c3.metric("Del%", _display_num(flow.get("delivery_pct")) or "—")
                        c4.metric("Turnover Cr", _display_num(flow.get("turnover_cr")) or "—")
                        st.markdown(
                            f"**SMC:** {smc.get('structure', '—')} · **Zone:** {smc.get('zone', '—')} · "
                            f"**Bias:** {smc.get('bias', '—')}"
                        )
                        st.markdown(f"**Next move:** {tp.get('next_move', '—')}")
                        if tp.get("reasons"):
                            for r in tp["reasons"][:5]:
                                st.markdown(f"- {r}")
                        if ai_t:
                            st.success(
                                f"**AI:** {ai_t.get('verdict', '—')} ({ai_t.get('confidence', '?')}%) — "
                                f"{ai_t.get('next_move', '')}"
                            )
                        render_strategy_mtf_panel(
                            symbol=sym,
                            market="Groww (India Stocks)",
                            groww_token=get_active_groww_token(),
                            exchange="NSE",
                            primary_tf="1d",
                            strategy_direction=tp.get("direction"),
                        )

            summaries.append(
                summarize_smc_flow(row, timeframe="1-5 sessions"),
            )

    if summaries:
        render_ta_screener_results(
            summaries,
            title="🧭 SMC · PCR · Flow Screener",
            strategy_label="SMC/flow",
            actionable_only=smc_actionable_only,
        )

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("smc_options")
