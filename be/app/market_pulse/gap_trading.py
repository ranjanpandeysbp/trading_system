"""
gap_trading.py
--------------
Core Gap Trading Strategy engine for TrueBacktester.

Features:
  - Gap Up / Gap Down detection with configurable min gap % threshold
  - Two-level Support (S1, S2) and Resistance (R1, R2) via swing-point analysis
  - Trade Setup generation: entry, stop-loss, target, R:R ratio
  - Fade (counter-trend) and Continuation (momentum) modes
  - Gap fill probability estimation from historical data
  - Data fetching helpers for Groww (yfinance fallback) and CoinDCX
"""

import logging
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Timeframe metadata helpers
# ---------------------------------------------------------------------------

# Maps timeframe key -> (yfinance period, yfinance interval, bars_to_fetch)
YF_TF_MAP = {
    "1m":  ("7d",   "1m",   300),
    "3m":  ("60d",  "1m",   300),   # yfinance has no 3m; resample from 1m
    "5m":  ("60d",  "5m",   300),
    "15m": ("60d",  "15m",  300),
    "30m": ("60d",  "30m",  200),
    "1h":  ("730d", "1h",   300),
    "4h":  ("730d", "1h",   300),   # yfinance doesn't have 4h; use 1h & resample
    "1d":  ("5y",   "1d",   500),
    "1w":  ("10y",  "1wk",  200),
    "1M":  ("max",  "1mo",  120),
}

CRYPTO_YF_SUFFIX = "-USD"      # BTC-USD, ETH-USD, etc.

# Minimum bars required for reliable gap detection
MIN_BARS_REQUIRED = 10


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

def _yfinance_symbol(symbol: str, is_crypto: bool, market: str = "") -> str:
    """Map a trading symbol to a yfinance ticker."""
    sym = symbol.upper().strip()
    if is_crypto:
        sym = sym.replace("B-", "").replace("_USDT", "").replace("-USDT", "").replace("USDT", "")
        return sym + CRYPTO_YF_SUFFIX
    from app.market_pulse.ticker_utils import is_us_market
    if is_us_market(market):
        from app.market_pulse.us_market_yfinance import us_symbol_to_yf
        return us_symbol_to_yf(sym)
    from app.market_pulse.nse_index_yfinance import (
        groww_symbol_to_yf,
        index_yf_candidates,
        is_nse_index_symbol,
        stock_symbol_to_yf,
    )
    if is_nse_index_symbol(sym):
        candidates = index_yf_candidates(sym)
        return candidates[0] if candidates else groww_symbol_to_yf(sym)
    return stock_symbol_to_yf(sym)


def fetch_ohlcv_yfinance(symbol: str, tf_key: str, is_crypto: bool = False, limit: int = 300, market: str = "") -> pd.DataFrame:
    """Fetch OHLCV data from yfinance for gap analysis. Returns a DataFrame
    with columns open/high/low/close/volume indexed by datetime, with the
    final row dropped if it's a still-forming candle for `tf_key` (yfinance
    does return the current partial intraday candle during market hours)."""
    from app.market_pulse.bar_utils import last_closed_bar

    df = _fetch_ohlcv_yfinance_raw(symbol, tf_key, is_crypto=is_crypto, limit=limit, market=market)
    return last_closed_bar(df, tf_key)


def _fetch_ohlcv_yfinance_raw(symbol: str, tf_key: str, is_crypto: bool = False, limit: int = 300, market: str = "") -> pd.DataFrame:
    try:
        import yfinance as yf

        yf_sym = _yfinance_symbol(symbol, is_crypto, market)
        period, interval, _ = YF_TF_MAP.get(tf_key, ("1y", "1d", 300))

        # Resample timeframes yfinance does not offer natively
        _RESAMPLE = {"3m": ("60d", "1m", "3min"), "4h": ("2y", "1h", "4h")}
        if tf_key in _RESAMPLE:
            rs_period, rs_interval, rs_rule = _RESAMPLE[tf_key]
            symbols_try = [yf_sym]
            if not is_crypto:
                from app.market_pulse.nse_index_yfinance import index_yf_candidates, is_nse_index_symbol
                if is_nse_index_symbol(symbol):
                    symbols_try = index_yf_candidates(symbol) or symbols_try
            raw = pd.DataFrame()
            for try_sym in symbols_try:
                raw = yf.download(
                    try_sym, period=rs_period, interval=rs_interval,
                    progress=False, auto_adjust=True, threads=False,
                )
                if not raw.empty:
                    break
            if raw.empty:
                return pd.DataFrame()
            raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                           for c in raw.columns]
            raw = raw[["open", "high", "low", "close", "volume"]]
            df = raw.resample(rs_rule).agg({
                "open": "first", "high": "max",
                "low": "min", "close": "last", "volume": "sum"
            }).dropna()
            return df.tail(limit)

        symbols_to_try = [yf_sym]
        if not is_crypto:
            from app.market_pulse.nse_index_yfinance import index_yf_candidates, is_nse_index_symbol
            if is_nse_index_symbol(symbol):
                symbols_to_try = index_yf_candidates(symbol) or symbols_to_try

        raw = pd.DataFrame()
        for try_sym in symbols_to_try:
            raw = yf.download(
                try_sym, period=period, interval=interval,
                progress=False, auto_adjust=True, threads=False,
            )
            if not raw.empty:
                yf_sym = try_sym
                break
        if raw.empty:
            logger.debug(f"yfinance returned empty for {symbol} (tried {symbols_to_try})")
            return pd.DataFrame()

        # Flatten MultiIndex columns if present
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() for c in raw.columns]

        df = raw[["open", "high", "low", "close", "volume"]].copy()
        df.dropna(inplace=True)
        df = df.tail(limit)
        logger.debug(f"Fetched {len(df)} bars for {yf_sym} [{tf_key}] via yfinance")
        return df

    except Exception as e:
        logger.error(f"yfinance fetch failed for {symbol} [{tf_key}]: {e}")
        return pd.DataFrame()


def fetch_data_for_gap_scan(
    symbol: str,
    timeframe: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
) -> pd.DataFrame:
    """Unified data fetcher for gap scanning — and, by extension, for nearly
    every scanning engine in this app, since they all fetch through here.

    Tries Groww/CoinDCX APIs first; falls back to yfinance. Returns OHLCV
    DataFrame or empty DataFrame on failure. The final row is dropped if
    it's a still-forming candle for `timeframe` (see bar_utils.py) so every
    caller scores confirmed bars only, without needing its own repaint gate.
    """
    from app.market_pulse.bar_utils import last_closed_bar

    df = _fetch_data_for_gap_scan_raw(symbol, timeframe, market, groww_token, exchange, limit=limit)
    return last_closed_bar(df, timeframe)


def _fetch_data_for_gap_scan_raw(
    symbol: str,
    timeframe: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market or "crypto" in market.lower()
    from app.market_pulse.ticker_utils import is_us_market
    is_us = is_us_market(market)
    is_india = not is_crypto and not is_us

    # ── US stocks (Yahoo only) ────────────────────────────────────────────
    if is_us:
        df = fetch_ohlcv_yfinance(symbol, timeframe, is_crypto=False, limit=limit, market=market)
        return df

    # ── India stocks ──────────────────────────────────────────────────────
    if is_india:
        # Groww API or public charting service for intraday; yfinance fallback
        if timeframe not in ("1w", "1M"):
            try:
                sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from app.market_pulse.heatmap import fetch_groww_ohlcv
                df = fetch_groww_ohlcv(symbol, exchange, timeframe, groww_token, limit=limit)
                if not df.empty and len(df) >= MIN_BARS_REQUIRED:
                    return df.tail(limit)
            except Exception as e:
                logger.debug(f"Groww OHLCV fetch failed for {symbol}: {e}")

        # yfinance fallback (always works for 1d/1w/1M)
        df = fetch_ohlcv_yfinance(symbol, timeframe, is_crypto=False, limit=limit, market=market)
        return df

    # ── CoinDCX Crypto ────────────────────────────────────────────────────
    else:
        if timeframe not in ("1w", "1M"):
            try:
                from app.market_pulse.heatmap import fetch_coindcx_ohlcv
                df = fetch_coindcx_ohlcv(symbol, timeframe, limit=limit)
                if not df.empty and len(df) >= MIN_BARS_REQUIRED:
                    # CoinDCX returns time-indexed via integer; convert
                    if "time" in df.columns:
                        df["date"] = pd.to_datetime(df["time"], unit="s")
                        df.set_index("date", inplace=True)
                        df.drop(columns=["time"], errors="ignore", inplace=True)
                    return df.tail(limit)
            except Exception as e:
                logger.debug(f"CoinDCX OHLCV fetch failed for {symbol}: {e}")

        # yfinance fallback for crypto (weekly/monthly or API failure)
        df = fetch_ohlcv_yfinance(symbol, timeframe, is_crypto=True, limit=limit, market=market)
        return df


# ---------------------------------------------------------------------------
# Gap Detection
# ---------------------------------------------------------------------------

def detect_gaps(df: pd.DataFrame, min_gap_pct: float = 0.3) -> pd.DataFrame:
    """
    Detect gap-up and gap-down events in OHLCV data.

    A gap occurs when:
      Gap Up:   open[i] > close[i-1]  (by >= min_gap_pct %)
      Gap Down: open[i] < close[i-1]  (by >= min_gap_pct %)

    Returns the input DataFrame with added columns:
      gap_pct     : float — gap size as % of previous close (signed, negative = gap down)
      gap_type    : str   — 'gap_up', 'gap_down', or ''
      gap_filled  : bool  — True if price later returned to the gap level (historical)
      prev_close  : float — previous bar's close
    """
    if df.empty or len(df) < 2:
        return df

    df = df.copy()
    prev_close = df["close"].shift(1)
    raw_gap = (df["open"] - prev_close) / prev_close * 100

    df["prev_close"] = prev_close
    df["gap_pct"] = raw_gap.fillna(0.0)
    df["gap_type"] = ""
    df.loc[df["gap_pct"] >= min_gap_pct, "gap_type"] = "gap_up"
    df.loc[df["gap_pct"] <= -min_gap_pct, "gap_type"] = "gap_down"

    # Determine historically whether each gap was filled
    df["gap_filled"] = False
    gap_indices = df.index[df["gap_type"] != ""].tolist()
    iloc_map = {idx: i for i, idx in enumerate(df.index)}

    for idx in gap_indices:
        i = iloc_map[idx]
        row = df.iloc[i]
        gap_t = row["gap_type"]
        gap_open = row["open"]
        p_close = row["prev_close"]

        if pd.isna(p_close) or p_close == 0:
            continue

        # Look forward in subsequent bars for gap fill
        future_slice = df.iloc[i + 1 : i + 51]  # up to 50 bars ahead
        if future_slice.empty:
            continue

        if gap_t == "gap_up":
            # Filled when low <= prev_close
            filled = (future_slice["low"] <= p_close).any()
        else:
            # Filled when high >= prev_close
            filled = (future_slice["high"] >= p_close).any()

        df.at[idx, "gap_filled"] = filled

    return df


def gap_fill_probability(df: pd.DataFrame, gap_type: str) -> float:
    """
    Estimate historical fill probability for the given gap type
    based on all historical gap events in the dataframe.
    """
    if "gap_type" not in df.columns or "gap_filled" not in df.columns:
        return 0.65  # default estimate

    historical = df[df["gap_type"] == gap_type].iloc[:-1]  # exclude last (current) row
    if historical.empty:
        return 0.65

    fill_rate = historical["gap_filled"].mean()
    return round(float(fill_rate), 3)


# ---------------------------------------------------------------------------
# Two-Level Support & Resistance
# ---------------------------------------------------------------------------

def calculate_two_level_sr(df: pd.DataFrame, short_lb: int = 20, long_lb: int = 50) -> dict:
    """
    Calculate two levels of support and resistance using swing-point analysis.

    Returns dict with keys:
      s1, s2   : nearest and second support levels
      r1, r2   : nearest and second resistance levels
    """
    result = {"s1": None, "s2": None, "r1": None, "r2": None}

    if df.empty or len(df) < short_lb:
        return result

    try:
        current_price = float(df["close"].iloc[-1])
        lows  = df["low"].values
        highs = df["high"].values

        # ── Find swing lows (support candidates) ──────────────────────────
        swing_lows = []
        for i in range(1, len(lows) - 1):
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                swing_lows.append(lows[i])

        # Sort descending (highest swing low first = nearest support)
        swing_lows_below = sorted(
            [l for l in swing_lows if l < current_price], reverse=True
        )

        if swing_lows_below:
            result["s1"] = round(float(swing_lows_below[0]), 4)
        if len(swing_lows_below) >= 2:
            # Cluster nearby levels — find second meaningfully different level
            s1 = swing_lows_below[0]
            threshold = s1 * 0.005  # 0.5% difference required
            for lvl in swing_lows_below[1:]:
                if abs(lvl - s1) > threshold:
                    result["s2"] = round(float(lvl), 4)
                    break

        # ── Find swing highs (resistance candidates) ───────────────────────
        swing_highs = []
        for i in range(1, len(highs) - 1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                swing_highs.append(highs[i])

        # Sort ascending (lowest swing high first = nearest resistance)
        swing_highs_above = sorted(
            [h for h in swing_highs if h > current_price]
        )

        if swing_highs_above:
            result["r1"] = round(float(swing_highs_above[0]), 4)
        if len(swing_highs_above) >= 2:
            r1 = swing_highs_above[0]
            threshold = r1 * 0.005
            for lvl in swing_highs_above[1:]:
                if abs(lvl - r1) > threshold:
                    result["r2"] = round(float(lvl), 4)
                    break

        # ── Fallback using percentile if swing points sparse ──────────────
        if result["s1"] is None:
            result["s1"] = round(float(np.percentile(df["low"].tail(short_lb), 10)), 4)
        if result["s2"] is None:
            result["s2"] = round(float(np.percentile(df["low"].tail(long_lb), 5)), 4)
        if result["r1"] is None:
            result["r1"] = round(float(np.percentile(df["high"].tail(short_lb), 90)), 4)
        if result["r2"] is None:
            result["r2"] = round(float(np.percentile(df["high"].tail(long_lb), 95)), 4)

    except Exception as e:
        logger.error(f"S/R calculation error: {e}")

    return result


# ---------------------------------------------------------------------------
# ATR Calculation (for SL)
# ---------------------------------------------------------------------------

def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate the most recent ATR value."""
    try:
        high = df["high"].values
        low  = df["low"].values
        close = df["close"].values

        tr_list = []
        for i in range(1, len(high)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )
            tr_list.append(tr)

        if not tr_list:
            return (df["high"] - df["low"]).mean()

        tr_series = pd.Series(tr_list)
        atr = tr_series.ewm(span=period, adjust=False).mean().iloc[-1]
        return float(atr)
    except Exception:
        return float((df["high"] - df["low"]).mean())


# ---------------------------------------------------------------------------
# Trade Setup Generation
# ---------------------------------------------------------------------------

def _format_price(price: Optional[float], is_crypto: bool) -> str:
    """Format price with appropriate decimal places."""
    if price is None:
        return "N/A"
    if is_crypto:
        if price > 1000:
            return f"${price:,.2f}"
        elif price > 1:
            return f"${price:.4f}"
        else:
            return f"${price:.6f}"
    else:
        return f"₹{price:,.2f}"


def generate_gap_trade_setups(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    is_crypto: bool = False,
    min_gap_pct: float = 0.3,
    mode: str = "both",  # "fade", "continuation", "both"
) -> list:
    """
    Generate complete trade setups for the most recent gap event(s).

    Each setup dict contains:
      symbol, timeframe, gap_type, gap_pct, strategy,
      entry, stop_loss, target, sl_pct, tp_pct, rr_ratio,
      s1, s2, r1, r2 (support/resistance levels),
      fill_probability, signal_quality, notes, is_crypto,
      currency_symbol, current_price, prev_close
    """
    setups = []

    if df.empty or len(df) < MIN_BARS_REQUIRED:
        return setups

    # Run gap detection
    df_gaps = detect_gaps(df, min_gap_pct=min_gap_pct)
    sr = calculate_two_level_sr(df_gaps)
    atr = _calculate_atr(df_gaps)

    current_price = float(df_gaps["close"].iloc[-1])
    currency = "$" if is_crypto else "₹"

    # Look at the last few bars for recent gaps (most recent first)
    recent = df_gaps[df_gaps["gap_type"] != ""].tail(5)

    if recent.empty:
        # No gap found — return an informational entry
        setups.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "gap_type": "no_gap",
            "gap_pct": 0.0,
            "strategy": "—",
            "entry": current_price,
            "stop_loss": None,
            "target": None,
            "sl_pct": 0.0,
            "tp_pct": 0.0,
            "rr_ratio": 0.0,
            "s1": sr["s1"], "s2": sr["s2"],
            "r1": sr["r1"], "r2": sr["r2"],
            "fill_probability": 0.0,
            "signal_quality": "⚪ No Gap",
            "notes": f"No gap ≥ {min_gap_pct}% detected in recent bars.",
            "is_crypto": is_crypto,
            "currency": currency,
            "current_price": current_price,
            "prev_close": float(df_gaps["prev_close"].iloc[-1]) if "prev_close" in df_gaps else current_price,
        })
        return setups

    # Process each recent gap event
    for idx, row in recent.iloc[::-1].iterrows():
        gap_t = row["gap_type"]
        gap_pct = float(row["gap_pct"])
        gap_open = float(row["open"])
        prev_close = float(row["prev_close"]) if not pd.isna(row["prev_close"]) else gap_open
        fill_prob = gap_fill_probability(df_gaps, gap_t)
        atr_pct = (atr / current_price) * 100 if current_price > 0 else 1.0

        # ── GAP UP setups ──────────────────────────────────────────────────
        if gap_t == "gap_up":
            # --- Fade Strategy (Short) ---
            if mode in ("fade", "both"):
                entry = gap_open
                sl    = gap_open + (atr * 1.5)
                tgt   = prev_close  # gap fill
                if sl > entry and tgt < entry:
                    sl_pct_val  = ((sl - entry) / entry) * 100
                    tp_pct_val  = ((entry - tgt) / entry) * 100
                    rr          = tp_pct_val / sl_pct_val if sl_pct_val > 0 else 0
                    quality     = _signal_quality(rr, fill_prob, atr_pct)
                    setups.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "gap_type": "gap_up",
                        "gap_pct": round(gap_pct, 3),
                        "strategy": "Fade Short (Gap Fill)",
                        "entry": round(entry, 4),
                        "stop_loss": round(sl, 4),
                        "target": round(tgt, 4),
                        "sl_pct": round(sl_pct_val, 2),
                        "tp_pct": round(tp_pct_val, 2),
                        "rr_ratio": round(rr, 2),
                        "s1": sr["s1"], "s2": sr["s2"],
                        "r1": sr["r1"], "r2": sr["r2"],
                        "fill_probability": fill_prob,
                        "signal_quality": quality,
                        "notes": (
                            f"Gap Up of {gap_pct:+.2f}% detected. "
                            f"Fade strategy targets gap fill at {currency}{tgt:,.2f}. "
                            f"Historical fill rate: {fill_prob:.0%}."
                        ),
                        "is_crypto": is_crypto,
                        "currency": currency,
                        "current_price": current_price,
                        "prev_close": prev_close,
                    })

            # --- Continuation Strategy (Long) ---
            if mode in ("continuation", "both"):
                entry = gap_open * 1.003  # small pullback confirmation
                sl    = prev_close        # gap fill invalidates bullish thesis
                tgt   = gap_open + 2 * abs(gap_open - prev_close)  # 2× gap extension
                if tgt > entry and sl < entry:
                    sl_pct_val  = ((entry - sl) / entry) * 100
                    tp_pct_val  = ((tgt - entry) / entry) * 100
                    rr          = tp_pct_val / sl_pct_val if sl_pct_val > 0 else 0
                    quality     = _signal_quality(rr, 1 - fill_prob, atr_pct)
                    setups.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "gap_type": "gap_up",
                        "gap_pct": round(gap_pct, 3),
                        "strategy": "Continuation Long (Momentum)",
                        "entry": round(entry, 4),
                        "stop_loss": round(sl, 4),
                        "target": round(tgt, 4),
                        "sl_pct": round(sl_pct_val, 2),
                        "tp_pct": round(tp_pct_val, 2),
                        "rr_ratio": round(rr, 2),
                        "s1": sr["s1"], "s2": sr["s2"],
                        "r1": sr["r1"], "r2": sr["r2"],
                        "fill_probability": fill_prob,
                        "signal_quality": quality,
                        "notes": (
                            f"Gap Up of {gap_pct:+.2f}% — momentum continuation long. "
                            f"SL below gap at {currency}{sl:,.2f} (gap-fill would invalidate). "
                            f"Target: 2× gap extension at {currency}{tgt:,.2f}."
                        ),
                        "is_crypto": is_crypto,
                        "currency": currency,
                        "current_price": current_price,
                        "prev_close": prev_close,
                    })

        # ── GAP DOWN setups ────────────────────────────────────────────────
        elif gap_t == "gap_down":
            # --- Fade Strategy (Long) ---
            if mode in ("fade", "both"):
                entry = gap_open
                sl    = gap_open - (atr * 1.5)
                tgt   = prev_close  # gap fill
                if sl < entry and tgt > entry:
                    sl_pct_val  = ((entry - sl) / entry) * 100
                    tp_pct_val  = ((tgt - entry) / entry) * 100
                    rr          = tp_pct_val / sl_pct_val if sl_pct_val > 0 else 0
                    quality     = _signal_quality(rr, fill_prob, atr_pct)
                    setups.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "gap_type": "gap_down",
                        "gap_pct": round(gap_pct, 3),
                        "strategy": "Fade Long (Gap Fill)",
                        "entry": round(entry, 4),
                        "stop_loss": round(sl, 4),
                        "target": round(tgt, 4),
                        "sl_pct": round(sl_pct_val, 2),
                        "tp_pct": round(tp_pct_val, 2),
                        "rr_ratio": round(rr, 2),
                        "s1": sr["s1"], "s2": sr["s2"],
                        "r1": sr["r1"], "r2": sr["r2"],
                        "fill_probability": fill_prob,
                        "signal_quality": quality,
                        "notes": (
                            f"Gap Down of {gap_pct:.2f}% detected. "
                            f"Fade strategy targets gap fill at {currency}{tgt:,.2f}. "
                            f"Historical fill rate: {fill_prob:.0%}."
                        ),
                        "is_crypto": is_crypto,
                        "currency": currency,
                        "current_price": current_price,
                        "prev_close": prev_close,
                    })

            # --- Continuation Strategy (Short) ---
            if mode in ("continuation", "both"):
                entry = gap_open * 0.997  # small dead-cat-bounce confirmation
                sl    = prev_close         # gap fill would invalidate bearish thesis
                tgt   = gap_open - 2 * abs(prev_close - gap_open)  # 2× extension down
                if tgt < entry and sl > entry:
                    sl_pct_val  = ((sl - entry) / entry) * 100
                    tp_pct_val  = ((entry - tgt) / entry) * 100
                    rr          = tp_pct_val / sl_pct_val if sl_pct_val > 0 else 0
                    quality     = _signal_quality(rr, 1 - fill_prob, atr_pct)
                    setups.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "gap_type": "gap_down",
                        "gap_pct": round(gap_pct, 3),
                        "strategy": "Continuation Short (Momentum)",
                        "entry": round(entry, 4),
                        "stop_loss": round(sl, 4),
                        "target": round(tgt, 4),
                        "sl_pct": round(sl_pct_val, 2),
                        "tp_pct": round(tp_pct_val, 2),
                        "rr_ratio": round(rr, 2),
                        "s1": sr["s1"], "s2": sr["s2"],
                        "r1": sr["r1"], "r2": sr["r2"],
                        "fill_probability": fill_prob,
                        "signal_quality": quality,
                        "notes": (
                            f"Gap Down of {gap_pct:.2f}% — momentum continuation short. "
                            f"SL above gap at {currency}{sl:,.2f}. "
                            f"Target: 2× gap extension at {currency}{tgt:,.2f}."
                        ),
                        "is_crypto": is_crypto,
                        "currency": currency,
                        "current_price": current_price,
                        "prev_close": prev_close,
                    })

    # De-duplicate: keep only the best RR per (symbol, timeframe, strategy) combo
    seen = {}
    deduped = []
    for s in setups:
        key = (s["symbol"], s["timeframe"], s["strategy"])
        if key not in seen or s["rr_ratio"] > seen[key]["rr_ratio"]:
            seen[key] = s
    deduped = list(seen.values())

    return sorted(deduped, key=lambda x: x["rr_ratio"], reverse=True)


def _signal_quality(rr: float, probability: float, atr_pct: float) -> str:
    """Return a quality badge string based on R:R, probability, and volatility."""
    if rr >= 2.5 and probability >= 0.6:
        return "⭐⭐⭐ PREMIUM"
    elif rr >= 2.0 and probability >= 0.5:
        return "⭐⭐ HIGH"
    elif rr >= 1.5:
        return "⭐ MODERATE"
    elif rr >= 1.0:
        return "🔶 LOW"
    else:
        return "🔴 POOR"


# ---------------------------------------------------------------------------
# Multi-Ticker / Multi-Timeframe Batch Scanner
# ---------------------------------------------------------------------------

def run_gap_scanner(
    symbols: list,
    timeframes: list,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    min_gap_pct: float = 0.3,
    mode: str = "both",
    limit: int = 100,
) -> pd.DataFrame:
    """
    Run the gap scanner across all symbol × timeframe combinations.

    Returns a flat DataFrame with all trade setups (or no-gap rows).
    Columns match generate_gap_trade_setups() output keys.
    """
    all_setups = []
    is_crypto = "CoinDCX" in market or "crypto" in market.lower()

    for symbol in symbols:
        for tf in timeframes:
            try:
                df = fetch_data_for_gap_scan(
                    symbol=symbol,
                    timeframe=tf,
                    market=market,
                    groww_token=groww_token,
                    exchange=exchange,
                    limit=limit,
                )
                if df.empty:
                    logger.warning(f"No data for {symbol} [{tf}]")
                    all_setups.append({
                        "symbol": symbol, "timeframe": tf,
                        "gap_type": "data_error", "gap_pct": 0.0,
                        "strategy": "—", "entry": None, "stop_loss": None,
                        "target": None, "sl_pct": 0.0, "tp_pct": 0.0,
                        "rr_ratio": 0.0, "s1": None, "s2": None,
                        "r1": None, "r2": None,
                        "fill_probability": 0.0,
                        "signal_quality": "❌ No Data",
                        "notes": f"Could not fetch data for {symbol} [{tf}].",
                        "is_crypto": is_crypto, "currency": "$" if is_crypto else "₹",
                        "current_price": None, "prev_close": None,
                    })
                    continue

                setups = generate_gap_trade_setups(
                    df=df,
                    symbol=symbol,
                    timeframe=tf,
                    is_crypto=is_crypto,
                    min_gap_pct=min_gap_pct,
                    mode=mode,
                )
                all_setups.extend(setups)

            except Exception as e:
                logger.error(f"Gap scan error for {symbol} [{tf}]: {e}")
                all_setups.append({
                    "symbol": symbol, "timeframe": tf,
                    "gap_type": "error", "gap_pct": 0.0,
                    "strategy": "—", "entry": None, "stop_loss": None,
                    "target": None, "sl_pct": 0.0, "tp_pct": 0.0,
                    "rr_ratio": 0.0, "s1": None, "s2": None,
                    "r1": None, "r2": None,
                    "fill_probability": 0.0,
                    "signal_quality": "❌ Error",
                    "notes": str(e),
                    "is_crypto": is_crypto, "currency": "$" if is_crypto else "₹",
                    "current_price": None, "prev_close": None,
                })

    if not all_setups:
        return pd.DataFrame()

    return pd.DataFrame(all_setups)
