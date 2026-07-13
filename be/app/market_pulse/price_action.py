from contextlib import nullcontext
"""
price_action.py
---------------
Comprehensive Price Action & Technical Analysis Engine for TrueBacktester.

Analyses:
  1. Support & Resistance (swing-point + volume-weighted clustering)
  2. Trendline detection (algorithmic)
  3. RSI analysis + divergence detection
  4. EMA crossover system (9/21, 20/50, 50/200)
  5. Fibonacci retracement & extensions (Golden Zone)
  6. Elliott Wave analysis (impulse + corrective)
  7. Candlestick pattern recognition (15+ patterns)
  8. Chart pattern detection (double top/bottom, H&S, wedges, triangles)
  9. Trade setup generator (LONG/SHORT with SL/TP/RR)
 10. Streamlit UI renderer

Supports both Groww (India Stocks) and CoinDCX Futures markets.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging
import sys
import os
import time
import re
from datetime import date, timedelta
from groq import Groq
from app.market_pulse.ai_view import (
    render_ai_config,
    render_block_ai_settings,
    mtf_ticker_button,
    render_mtf_ai_view_report,
    combine_timeframe_sections,
    MTF_AI_SYSTEM,
    STANDARD_REPORT_FORMAT,
)
from app.market_pulse.demo_trading import render_demo_trade_panel
from app.market_pulse.env_config import api_key_env_hint
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import (
    render_run_summary,
    summarize_error,
    summarize_mtf_aggregate,
    summarize_price_action,
)
from app.market_pulse.ta_screener_ui import (
    render_ta_screener_options,
    render_ta_screener_results,
    render_strategy_mtf_panel,
    should_show_ticker_in_screener,
)
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    INDEX_OPTIONS,
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
    market_currency,
)
from app.market_pulse.ta_ticker_sections import (
    should_expand_ticker,
    tf_section_label,
    ticker_section_label,
)
try:
    from google import genai as genai_new
    GENAI_NEW = True
except ImportError:
    try:
        import google.generativeai as genai
        GENAI_NEW = False
    except ImportError:
        GENAI_NEW = False
        genai = None

logger = logging.getLogger(__name__)

# Allow importing from parent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reuse existing data fetching & ticker utilities
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.price_extremes import render_price_extremes_for_ticker
from app.market_pulse.price_action_simple import (
    StrategyConfig as PASimpleConfig,
    render_price_action_simple_for_ticker,
    render_price_action_simple_section,
)
try:
    from app.market_pulse.ticker_utils import INDEX_OPTIONS, get_coindcx_ticker_list, COINDCX_USDT_TICKERS
except ImportError:
    INDEX_OPTIONS = {"Custom": []}
    COINDCX_USDT_TICKERS = []
    def get_coindcx_ticker_list():
        return []

try:
    from backtesting.data_fetcher import POPULAR_NSE_STOCKS
except ImportError:
    POPULAR_NSE_STOCKS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


# ==========================================================================
# 1. SUPPORT & RESISTANCE
# ==========================================================================

def detect_support_resistance(df, window=5, num_levels=3, atr_tolerance_mult=0.5):
    """
    Detect support and resistance levels using swing-point analysis
    with volume-weighted clustering.

    Returns dict with:
      supports: list of {price, strength, touches}
      resistances: list of {price, strength, touches}
    """
    if df.empty or len(df) < window * 2 + 1:
        return {"supports": [], "resistances": []}

    highs = df["high"].values
    lows = df["low"].values
    close_arr = df["close"].values
    vol = df["volume"].values if "volume" in df.columns else np.ones(len(df))
    current_price = float(close_arr[-1])

    # Calculate ATR for clustering tolerance
    atr = _calc_atr(df, 14)
    tolerance = atr * atr_tolerance_mult

    # Find swing highs and swing lows
    swing_highs = []
    swing_lows = []

    for i in range(window, len(df) - window):
        # Swing high: highest in window
        if highs[i] == max(highs[i - window:i + window + 1]):
            swing_highs.append((float(highs[i]), float(vol[i]), i))
        # Swing low: lowest in window
        if lows[i] == min(lows[i - window:i + window + 1]):
            swing_lows.append((float(lows[i]), float(vol[i]), i))

    # Cluster nearby levels
    def cluster_levels(levels, tol):
        if not levels:
            return []
        sorted_lvls = sorted(levels, key=lambda x: x[0])
        clusters = []
        current_cluster = [sorted_lvls[0]]

        for lvl in sorted_lvls[1:]:
            if abs(lvl[0] - current_cluster[-1][0]) <= tol:
                current_cluster.append(lvl)
            else:
                clusters.append(current_cluster)
                current_cluster = [lvl]
        clusters.append(current_cluster)

        result = []
        for cluster in clusters:
            # Volume-weighted average price
            total_vol = sum(l[1] for l in cluster)
            if total_vol > 0:
                vwap = sum(l[0] * l[1] for l in cluster) / total_vol
            else:
                vwap = np.mean([l[0] for l in cluster])
            strength = len(cluster)  # number of touches
            recency = max(l[2] for l in cluster)  # most recent touch index
            result.append({
                "price": round(float(vwap), 4),
                "strength": strength,
                "touches": strength,
                "recency": recency,
            })
        return result

    # Cluster and separate into supports (below price) and resistances (above)
    all_supports = cluster_levels(swing_lows, tolerance)
    all_resistances = cluster_levels(swing_highs, tolerance)

    supports = sorted(
        [s for s in all_supports if s["price"] < current_price],
        key=lambda x: (-x["strength"], -x["recency"])
    )[:num_levels]

    resistances = sorted(
        [r for r in all_resistances if r["price"] > current_price],
        key=lambda x: (-x["strength"], -x["recency"])
    )[:num_levels]

    return {"supports": supports, "resistances": resistances}


# ==========================================================================
# 2. TRENDLINE DETECTION
# ==========================================================================

def detect_trendlines(df, window=5):
    """
    Detect ascending and descending trendlines by connecting swing points.

    Returns dict with:
      uptrend: {slope, intercept, start_idx, end_idx, points, strength}
      downtrend: {slope, intercept, start_idx, end_idx, points, strength}
      trend_direction: 'UP', 'DOWN', or 'SIDEWAYS'
      linear_regression: {slope, intercept, r_squared}
    """
    result = {
        "uptrend": None, "downtrend": None,
        "trend_direction": "SIDEWAYS",
        "linear_regression": None,
    }

    if df.empty or len(df) < window * 3:
        return result

    close_arr = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    # Linear regression on close prices
    x = np.arange(n)
    coeffs = np.polyfit(x, close_arr, 1)
    slope, intercept = coeffs[0], coeffs[1]
    predicted = np.polyval(coeffs, x)
    ss_res = np.sum((close_arr - predicted) ** 2)
    ss_tot = np.sum((close_arr - np.mean(close_arr)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    result["linear_regression"] = {
        "slope": round(float(slope), 6),
        "intercept": round(float(intercept), 4),
        "r_squared": round(float(r_squared), 4),
        "slope_pct_per_bar": round(float(slope / close_arr[-1] * 100), 4),
    }

    # Find swing lows for uptrend line
    swing_low_indices = []
    for i in range(window, n - window):
        if lows[i] == min(lows[i - window:i + window + 1]):
            swing_low_indices.append(i)

    # Find swing highs for downtrend line
    swing_high_indices = []
    for i in range(window, n - window):
        if highs[i] == max(highs[i - window:i + window + 1]):
            swing_high_indices.append(i)

    # Best uptrend line (connect ascending swing lows)
    if len(swing_low_indices) >= 2:
        best_up = _best_trendline(swing_low_indices, lows, ascending=True)
        if best_up:
            result["uptrend"] = best_up

    # Best downtrend line (connect descending swing highs)
    if len(swing_high_indices) >= 2:
        best_down = _best_trendline(swing_high_indices, highs, ascending=False)
        if best_down:
            result["downtrend"] = best_down

    # Determine overall trend direction
    slope_pct = slope / close_arr[-1] * 100
    if slope_pct > 0.05:
        result["trend_direction"] = "UP"
    elif slope_pct < -0.05:
        result["trend_direction"] = "DOWN"
    else:
        result["trend_direction"] = "SIDEWAYS"

    return result


def _best_trendline(indices, prices, ascending=True):
    """Find the best-fitting trendline through swing points."""
    if len(indices) < 2:
        return None

    best = None
    best_score = -1

    # Try all pairs of swing points
    for i in range(len(indices)):
        for j in range(i + 1, min(i + 6, len(indices))):  # limit search
            idx1, idx2 = indices[i], indices[j]
            p1, p2 = float(prices[idx1]), float(prices[idx2])

            if ascending and p2 <= p1:
                continue
            if not ascending and p2 >= p1:
                continue

            sl = (p2 - p1) / (idx2 - idx1)
            inter = p1 - sl * idx1

            # Count how many other swing points are near the line
            touches = 0
            for k in range(len(indices)):
                idx_k = indices[k]
                expected = sl * idx_k + inter
                actual = float(prices[idx_k])
                tolerance = abs(expected) * 0.005  # 0.5%
                if abs(actual - expected) <= tolerance:
                    touches += 1

            if touches > best_score:
                best_score = touches
                best = {
                    "slope": round(float(sl), 6),
                    "intercept": round(float(inter), 4),
                    "start_idx": int(idx1),
                    "end_idx": int(idx2),
                    "points": touches,
                    "strength": touches,
                }

    return best


# ==========================================================================
# 3. RSI ANALYSIS + DIVERGENCE
# ==========================================================================

def analyze_rsi(df, period=14):
    """
    Calculate RSI and detect divergences.

    Returns dict with:
      rsi_values: array
      current_rsi: float
      zone: 'OVERBOUGHT', 'OVERSOLD', 'NEUTRAL'
      bullish_divergence: bool
      bearish_divergence: bool
      divergence_details: str
    """
    result = {
        "rsi_values": None, "current_rsi": 50.0,
        "zone": "NEUTRAL",
        "bullish_divergence": False, "bearish_divergence": False,
        "divergence_details": "",
    }

    if df.empty or len(df) < period + 5:
        return result

    close = df["close"].values.astype(float)

    # Calculate RSI
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = pd.Series(gains).ewm(span=period, adjust=False).mean().values
    avg_loss = pd.Series(losses).ewm(span=period, adjust=False).mean().values

    with np.errstate(divide='ignore', invalid='ignore'):
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))

    # Pad to match df length
    rsi_full = np.concatenate([[50.0], rsi])
    result["rsi_values"] = rsi_full
    result["current_rsi"] = round(float(rsi_full[-1]), 2)

    if rsi_full[-1] > 70:
        result["zone"] = "OVERBOUGHT"
    elif rsi_full[-1] < 30:
        result["zone"] = "OVERSOLD"

    # Detect divergences (look back 20 bars)
    lookback = min(30, len(close) - 1)
    if lookback > 10:
        price_recent = close[-lookback:]
        rsi_recent = rsi_full[-lookback:]

        # Find local lows for bullish divergence
        price_lows = []
        rsi_lows = []
        for i in range(2, len(price_recent) - 2):
            if price_recent[i] < price_recent[i-1] and price_recent[i] < price_recent[i+1]:
                price_lows.append((i, price_recent[i]))
            if rsi_recent[i] < rsi_recent[i-1] and rsi_recent[i] < rsi_recent[i+1]:
                rsi_lows.append((i, rsi_recent[i]))

        # Bullish divergence: price makes lower low, RSI makes higher low
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            if price_lows[-1][1] < price_lows[-2][1] and rsi_lows[-1][1] > rsi_lows[-2][1]:
                result["bullish_divergence"] = True
                result["divergence_details"] = "Bullish RSI divergence: price made lower low but RSI made higher low — potential reversal UP"

        # Find local highs for bearish divergence
        price_highs = []
        rsi_highs = []
        for i in range(2, len(price_recent) - 2):
            if price_recent[i] > price_recent[i-1] and price_recent[i] > price_recent[i+1]:
                price_highs.append((i, price_recent[i]))
            if rsi_recent[i] > rsi_recent[i-1] and rsi_recent[i] > rsi_recent[i+1]:
                rsi_highs.append((i, rsi_recent[i]))

        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            if price_highs[-1][1] > price_highs[-2][1] and rsi_highs[-1][1] < rsi_highs[-2][1]:
                result["bearish_divergence"] = True
                result["divergence_details"] = "Bearish RSI divergence: price made higher high but RSI made lower high — potential reversal DOWN"

    return result


# ==========================================================================
# 4. EMA CROSSOVER SYSTEM
# ==========================================================================

def analyze_ema_crossovers(df):
    """
    Compute multiple EMA pairs and detect crossovers.

    Returns dict with:
      emas: {9, 21, 20, 50, 200} arrays
      crossovers: list of {type, fast, slow, signal, bar_idx}
      ema_stack: 'BULLISH', 'BEARISH', or 'MIXED'
      price_vs_ema200: 'ABOVE' or 'BELOW'
    """
    result = {
        "emas": {}, "crossovers": [],
        "ema_stack": "MIXED", "price_vs_ema200": "BELOW",
    }

    if df.empty or len(df) < 50:
        return result

    close = df["close"].values.astype(float)

    # Calculate EMAs
    for period in [9, 21, 20, 50, 200]:
        if len(close) >= period:
            result["emas"][period] = _ema(close, period)
        else:
            result["emas"][period] = np.full(len(close), np.nan)

    # Detect crossovers
    pairs = [(9, 21, "Scalping"), (20, 50, "Swing"), (50, 200, "Trend")]
    for fast_p, slow_p, style in pairs:
        fast = result["emas"].get(fast_p)
        slow = result["emas"].get(slow_p)
        if fast is None or slow is None:
            continue

        # Check last 5 bars for recent crossover
        for i in range(max(1, len(close) - 5), len(close)):
            if fast[i-1] <= slow[i-1] and fast[i] > slow[i]:
                result["crossovers"].append({
                    "type": "GOLDEN_CROSS" if fast_p == 50 else "BULLISH_CROSS",
                    "fast": fast_p, "slow": slow_p,
                    "signal": "BUY",
                    "style": style,
                    "bar_idx": i,
                    "bars_ago": len(close) - 1 - i,
                })
            elif fast[i-1] >= slow[i-1] and fast[i] < slow[i]:
                result["crossovers"].append({
                    "type": "DEATH_CROSS" if fast_p == 50 else "BEARISH_CROSS",
                    "fast": fast_p, "slow": slow_p,
                    "signal": "SELL",
                    "style": style,
                    "bar_idx": i,
                    "bars_ago": len(close) - 1 - i,
                })

    # EMA stack alignment
    ema9 = result["emas"].get(9)
    ema21 = result["emas"].get(21)
    ema50 = result["emas"].get(50)
    if ema9 is not None and ema21 is not None and ema50 is not None:
        if ema9[-1] > ema21[-1] > ema50[-1]:
            result["ema_stack"] = "BULLISH"
        elif ema9[-1] < ema21[-1] < ema50[-1]:
            result["ema_stack"] = "BEARISH"

    # Price vs EMA 200
    ema200 = result["emas"].get(200)
    if ema200 is not None and not np.isnan(ema200[-1]):
        result["price_vs_ema200"] = "ABOVE" if close[-1] > ema200[-1] else "BELOW"

    return result


def _ema(data, period):
    """Calculate EMA."""
    s = pd.Series(data)
    return s.ewm(span=period, adjust=False).mean().values


# ==========================================================================
# 5. FIBONACCI GOLDEN ZONE
# ==========================================================================

def analyze_fibonacci(df, lookback=100):
    """
    Auto-detect the latest swing high/low and compute Fibonacci levels.

    Returns dict with:
      swing_high, swing_low: float
      direction: 'UP' (retracement from high) or 'DOWN' (retracement from low)
      levels: dict of {level_name: price}
      golden_zone: {upper, lower}
      price_in_golden_zone: bool
      extensions: dict of {level_name: price}
    """
    result = {
        "swing_high": None, "swing_low": None,
        "direction": "UP", "levels": {},
        "golden_zone": {"upper": 0, "lower": 0},
        "price_in_golden_zone": False,
        "extensions": {},
    }

    if df.empty or len(df) < 20:
        return result

    close = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    lb = min(lookback, len(df))

    recent_highs = highs[-lb:]
    recent_lows = lows[-lb:]

    swing_high = float(np.max(recent_highs))
    swing_low = float(np.min(recent_lows))
    current_price = float(close[-1])

    sh_idx = int(np.argmax(recent_highs))
    sl_idx = int(np.argmin(recent_lows))

    result["swing_high"] = round(swing_high, 4)
    result["swing_low"] = round(swing_low, 4)

    # Determine direction: if high came after low, price went up then retracing
    if sh_idx > sl_idx:
        result["direction"] = "DOWN"  # retracing down from high
        diff = swing_high - swing_low
        fib_levels = {
            "0.0% (High)": swing_high,
            "23.6%": swing_high - diff * 0.236,
            "38.2%": swing_high - diff * 0.382,
            "50.0%": swing_high - diff * 0.5,
            "61.8% (Golden)": swing_high - diff * 0.618,
            "78.6%": swing_high - diff * 0.786,
            "100.0% (Low)": swing_low,
        }
        extensions = {
            "127.2%": swing_high - diff * 1.272,
            "161.8%": swing_high - diff * 1.618,
            "261.8%": swing_high - diff * 2.618,
        }
        golden_upper = swing_high - diff * 0.5
        golden_lower = swing_high - diff * 0.618
    else:
        result["direction"] = "UP"  # retracing up from low
        diff = swing_high - swing_low
        fib_levels = {
            "0.0% (Low)": swing_low,
            "23.6%": swing_low + diff * 0.236,
            "38.2%": swing_low + diff * 0.382,
            "50.0%": swing_low + diff * 0.5,
            "61.8% (Golden)": swing_low + diff * 0.618,
            "78.6%": swing_low + diff * 0.786,
            "100.0% (High)": swing_high,
        }
        extensions = {
            "127.2%": swing_low + diff * 1.272,
            "161.8%": swing_low + diff * 1.618,
            "261.8%": swing_low + diff * 2.618,
        }
        golden_upper = swing_low + diff * 0.618
        golden_lower = swing_low + diff * 0.5

    result["levels"] = {k: round(v, 4) for k, v in fib_levels.items()}
    result["extensions"] = {k: round(v, 4) for k, v in extensions.items()}
    result["golden_zone"] = {
        "upper": round(max(golden_upper, golden_lower), 4),
        "lower": round(min(golden_upper, golden_lower), 4),
    }
    result["price_in_golden_zone"] = (
        result["golden_zone"]["lower"] <= current_price <= result["golden_zone"]["upper"]
    )

    return result


# ==========================================================================
# 6. ELLIOTT WAVE ANALYSIS
# ==========================================================================

def analyze_elliott_waves(df, zigzag_pct=3.0):
    """
    Algorithmic Elliott Wave detection using ZigZag filter.

    Returns dict with:
      waves: list of {wave_num, start_idx, end_idx, start_price, end_price, direction}
      pattern: 'IMPULSE', 'CORRECTIVE', 'INCOMPLETE', or 'NONE'
      current_wave: int (1-5 for impulse, A-C for corrective)
      wave_targets: dict of projected prices
      valid_impulse: bool
      notes: str
    """
    result = {
        "waves": [], "pattern": "NONE",
        "current_wave": 0, "wave_targets": {},
        "valid_impulse": False, "notes": "",
    }

    if df.empty or len(df) < 30:
        result["notes"] = "Insufficient data for Elliott Wave analysis."
        return result

    close = df["close"].values.astype(float)

    # ZigZag filter to find significant turning points
    pivots = _zigzag(close, pct_threshold=zigzag_pct)

    if len(pivots) < 4:
        result["notes"] = f"Only {len(pivots)} pivot points found (need >= 6 for impulse, >= 4 for corrective)."
        return result

    # Try to detect 5-wave impulse pattern (most recent pivots)
    if len(pivots) >= 6:
        last6 = pivots[-6:]
        impulse = _validate_impulse(last6, close)
        if impulse["valid"]:
            result["waves"] = impulse["waves"]
            result["pattern"] = "IMPULSE"
            result["valid_impulse"] = True
            result["current_wave"] = impulse["current_wave"]
            result["wave_targets"] = impulse["targets"]
            result["notes"] = impulse["notes"]
            return result

    # Try to detect ABC corrective pattern
    if len(pivots) >= 4:
        last4 = pivots[-4:]
        corrective = _validate_corrective(last4, close)
        if corrective["valid"]:
            result["waves"] = corrective["waves"]
            result["pattern"] = "CORRECTIVE"
            result["current_wave"] = corrective["current_wave"]
            result["wave_targets"] = corrective["targets"]
            result["notes"] = corrective["notes"]
            return result

    # Incomplete pattern
    result["pattern"] = "INCOMPLETE"
    result["notes"] = f"Detected {len(pivots)} pivots but no valid impulse or corrective pattern."
    # Still return the pivots as waves for visualization
    for i in range(1, len(pivots)):
        p0 = pivots[i-1]
        p1 = pivots[i]
        result["waves"].append({
            "wave_num": i,
            "start_idx": int(p0[0]),
            "end_idx": int(p1[0]),
            "start_price": round(float(p0[1]), 4),
            "end_price": round(float(p1[1]), 4),
            "direction": "UP" if p1[1] > p0[1] else "DOWN",
        })

    return result


def _zigzag(data, pct_threshold=3.0):
    """Find significant pivot points using ZigZag filter."""
    if len(data) < 3:
        return []

    pivots = [(0, data[0])]
    last_pivot = data[0]
    last_direction = 0  # 1=up, -1=down
    last_idx = 0

    for i in range(1, len(data)):
        change = (data[i] - last_pivot) / last_pivot * 100

        if abs(change) >= pct_threshold:
            if change > 0:
                if last_direction == -1:
                    pivots.append((last_idx, last_pivot))
                last_direction = 1
                last_pivot = data[i]
                last_idx = i
            else:
                if last_direction == 1:
                    pivots.append((last_idx, last_pivot))
                last_direction = -1
                last_pivot = data[i]
                last_idx = i
        else:
            if last_direction == 1 and data[i] > last_pivot:
                last_pivot = data[i]
                last_idx = i
            elif last_direction == -1 and data[i] < last_pivot:
                last_pivot = data[i]
                last_idx = i

    pivots.append((last_idx, last_pivot))
    return pivots


def _validate_impulse(pivots, close):
    """Validate 5-wave impulse pattern from 6 pivot points."""
    result = {"valid": False, "waves": [], "current_wave": 0, "targets": {}, "notes": ""}

    if len(pivots) < 6:
        return result

    p = [pv[1] for pv in pivots]
    idx = [pv[0] for pv in pivots]

    # Determine if bullish or bearish impulse
    bullish = p[5] > p[0]

    if bullish:
        # Rules for bullish impulse:
        # Wave 1: p[0]→p[1] UP, Wave 2: p[1]→p[2] DOWN, Wave 3: p[2]→p[3] UP
        # Wave 4: p[3]→p[4] DOWN, Wave 5: p[4]→p[5] UP
        w1_up = p[1] > p[0]
        w2_down = p[2] < p[1]
        w3_up = p[3] > p[2]
        w4_down = p[4] < p[3]
        w5_up = p[5] > p[4]

        if not (w1_up and w2_down and w3_up and w4_down and w5_up):
            return result

        # Rule: Wave 2 must not retrace below Wave 1 start
        if p[2] < p[0]:
            result["notes"] = "Wave 2 retraced below Wave 1 start (invalid)."
            return result

        # Rule: Wave 3 must not be the shortest
        w1_len = abs(p[1] - p[0])
        w3_len = abs(p[3] - p[2])
        w5_len = abs(p[5] - p[4])
        if w3_len < w1_len and w3_len < w5_len:
            result["notes"] = "Wave 3 is shortest (invalid — Wave 3 cannot be the shortest)."
            return result

        # Rule: Wave 4 must not overlap Wave 1 territory
        if p[4] < p[1]:
            result["notes"] = "Wave 4 overlaps Wave 1 territory (invalid)."
            return result
    else:
        # Bearish impulse (mirror)
        w1_down = p[1] < p[0]
        w2_up = p[2] > p[1]
        w3_down = p[3] < p[2]
        w4_up = p[4] > p[3]
        w5_down = p[5] < p[4]

        if not (w1_down and w2_up and w3_down and w4_up and w5_down):
            return result

        if p[2] > p[0]:
            return result

        w1_len = abs(p[0] - p[1])
        w3_len = abs(p[2] - p[3])
        w5_len = abs(p[4] - p[5])
        if w3_len < w1_len and w3_len < w5_len:
            return result

        if p[4] > p[1]:
            return result

    # Valid impulse!
    result["valid"] = True
    wave_names = ["Wave 1", "Wave 2", "Wave 3", "Wave 4", "Wave 5"]
    for i in range(5):
        result["waves"].append({
            "wave_num": i + 1,
            "start_idx": int(idx[i]),
            "end_idx": int(idx[i + 1]),
            "start_price": round(float(p[i]), 4),
            "end_price": round(float(p[i + 1]), 4),
            "direction": "UP" if p[i + 1] > p[i] else "DOWN",
        })

    # Determine current wave position
    current_price = float(close[-1])
    if abs(current_price - p[5]) / p[5] < 0.01:
        result["current_wave"] = 5
        result["notes"] = "Currently at end of Wave 5 — expect ABC corrective move."
    else:
        result["current_wave"] = 5
        result["notes"] = "5-wave impulse detected. Watch for corrective ABC pattern."

    # Targets: after impulse, expect ABC correction
    wave_range = abs(p[5] - p[0])
    if bullish:
        result["targets"] = {
            "ABC 38.2%": round(p[5] - wave_range * 0.382, 4),
            "ABC 50.0%": round(p[5] - wave_range * 0.5, 4),
            "ABC 61.8%": round(p[5] - wave_range * 0.618, 4),
        }
    else:
        result["targets"] = {
            "ABC 38.2%": round(p[5] + wave_range * 0.382, 4),
            "ABC 50.0%": round(p[5] + wave_range * 0.5, 4),
            "ABC 61.8%": round(p[5] + wave_range * 0.618, 4),
        }

    return result


def _validate_corrective(pivots, close):
    """Validate ABC corrective pattern from 4 pivot points."""
    result = {"valid": False, "waves": [], "current_wave": 0, "targets": {}, "notes": ""}

    if len(pivots) < 4:
        return result

    p = [pv[1] for pv in pivots]
    idx = [pv[0] for pv in pivots]

    # Detect bearish ABC (down-up-down) or bullish ABC (up-down-up)
    a_down = p[1] < p[0]
    b_up = p[2] > p[1]
    c_down = p[3] < p[2]

    a_up = p[1] > p[0]
    b_down = p[2] < p[1]
    c_up = p[3] > p[2]

    bearish_abc = a_down and b_up and c_down
    bullish_abc = a_up and b_down and c_up

    if not (bearish_abc or bullish_abc):
        return result

    # B wave should not retrace beyond A start
    if bearish_abc and p[2] > p[0]:
        return result
    if bullish_abc and p[2] < p[0]:
        return result

    result["valid"] = True
    wave_labels = ["Wave A", "Wave B", "Wave C"]
    for i in range(3):
        result["waves"].append({
            "wave_num": chr(65 + i),  # A, B, C
            "start_idx": int(idx[i]),
            "end_idx": int(idx[i + 1]),
            "start_price": round(float(p[i]), 4),
            "end_price": round(float(p[i + 1]), 4),
            "direction": "UP" if p[i + 1] > p[i] else "DOWN",
        })

    result["current_wave"] = "C"
    a_range = abs(p[1] - p[0])

    if bearish_abc:
        result["notes"] = "Bearish ABC correction detected. After Wave C, expect new impulse UP."
        result["targets"] = {
            "New impulse start": round(float(p[3]), 4),
            "Wave C = Wave A": round(p[2] - a_range, 4),
            "Reversal target": round(float(p[0]), 4),
        }
    else:
        result["notes"] = "Bullish ABC correction detected. After Wave C, expect new impulse DOWN."
        result["targets"] = {
            "New impulse start": round(float(p[3]), 4),
            "Wave C = Wave A": round(p[2] + a_range, 4),
            "Reversal target": round(float(p[0]), 4),
        }

    return result


# ==========================================================================
# 7. CANDLESTICK PATTERN RECOGNITION
# ==========================================================================

def detect_candlestick_patterns(df):
    """
    Detect candlestick patterns in the last ~10 bars.

    Returns list of {name, type, bias, bar_idx, reliability, description}
    """
    patterns = []
    if df.empty or len(df) < 5:
        return patterns

    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)

    # Only scan last 10 bars
    start = max(3, n - 10)

    for i in range(start, n):
        body = abs(c[i] - o[i])
        candle_range = h[i] - l[i]
        if candle_range == 0:
            continue

        upper_wick = h[i] - max(o[i], c[i])
        lower_wick = min(o[i], c[i]) - l[i]
        body_ratio = body / candle_range
        is_bullish = c[i] > o[i]

        bars_ago = n - 1 - i

        # ── Single candle patterns ──
        # Doji
        if body_ratio < 0.1:
            patterns.append({
                "name": "Doji", "type": "single",
                "bias": "NEUTRAL", "bar_idx": i, "bars_ago": bars_ago,
                "reliability": "MODERATE",
                "description": "Indecision — open and close nearly equal. Potential reversal signal.",
            })

        # Hammer (bullish reversal at bottom)
        elif lower_wick > body * 2 and upper_wick < body * 0.5 and i > 1 and c[i-1] < o[i-1]:
            patterns.append({
                "name": "Hammer", "type": "single",
                "bias": "BULLISH", "bar_idx": i, "bars_ago": bars_ago,
                "reliability": "HIGH",
                "description": "Bullish reversal: long lower wick shows buying pressure after decline.",
            })

        # Shooting Star (bearish reversal at top)
        elif upper_wick > body * 2 and lower_wick < body * 0.5 and i > 1 and c[i-1] > o[i-1]:
            patterns.append({
                "name": "Shooting Star", "type": "single",
                "bias": "BEARISH", "bar_idx": i, "bars_ago": bars_ago,
                "reliability": "HIGH",
                "description": "Bearish reversal: long upper wick shows selling pressure at highs.",
            })

        # Marubozu (strong momentum)
        elif body_ratio > 0.9:
            bias = "BULLISH" if is_bullish else "BEARISH"
            patterns.append({
                "name": f"{'Bullish' if is_bullish else 'Bearish'} Marubozu", "type": "single",
                "bias": bias, "bar_idx": i, "bars_ago": bars_ago,
                "reliability": "HIGH",
                "description": f"{'Strong buying' if is_bullish else 'Strong selling'} pressure — no wicks.",
            })

        # ── Double candle patterns ──
        if i >= 1:
            prev_body = abs(c[i-1] - o[i-1])
            prev_bullish = c[i-1] > o[i-1]

            # Bullish Engulfing
            if not prev_bullish and is_bullish and c[i] > o[i-1] and o[i] < c[i-1] and body > prev_body:
                patterns.append({
                    "name": "Bullish Engulfing", "type": "double",
                    "bias": "BULLISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "HIGH",
                    "description": "Strong bullish reversal — current green candle completely engulfs previous red candle.",
                })

            # Bearish Engulfing
            elif prev_bullish and not is_bullish and c[i] < o[i-1] and o[i] > c[i-1] and body > prev_body:
                patterns.append({
                    "name": "Bearish Engulfing", "type": "double",
                    "bias": "BEARISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "HIGH",
                    "description": "Strong bearish reversal — current red candle completely engulfs previous green candle.",
                })

            # Piercing Line
            if not prev_bullish and is_bullish and o[i] < l[i-1] and c[i] > (o[i-1] + c[i-1]) / 2:
                patterns.append({
                    "name": "Piercing Line", "type": "double",
                    "bias": "BULLISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "MODERATE",
                    "description": "Bullish reversal — opens below prior low, closes above prior midpoint.",
                })

            # Dark Cloud Cover
            if prev_bullish and not is_bullish and o[i] > h[i-1] and c[i] < (o[i-1] + c[i-1]) / 2:
                patterns.append({
                    "name": "Dark Cloud Cover", "type": "double",
                    "bias": "BEARISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "MODERATE",
                    "description": "Bearish reversal — opens above prior high, closes below prior midpoint.",
                })

        # ── Triple candle patterns ──
        if i >= 2:
            # Morning Star
            prev2_bearish = c[i-2] < o[i-2]
            prev1_small = abs(c[i-1] - o[i-1]) / (h[i-1] - l[i-1] + 1e-10) < 0.3
            if prev2_bearish and prev1_small and is_bullish and c[i] > (o[i-2] + c[i-2]) / 2:
                patterns.append({
                    "name": "Morning Star", "type": "triple",
                    "bias": "BULLISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "VERY HIGH",
                    "description": "Strong bullish reversal: big red → small body → big green. Classic bottom pattern.",
                })

            # Evening Star
            prev2_bullish = c[i-2] > o[i-2]
            if prev2_bullish and prev1_small and not is_bullish and c[i] < (o[i-2] + c[i-2]) / 2:
                patterns.append({
                    "name": "Evening Star", "type": "triple",
                    "bias": "BEARISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "VERY HIGH",
                    "description": "Strong bearish reversal: big green → small body → big red. Classic top pattern.",
                })

            # Three White Soldiers
            if (c[i] > o[i] and c[i-1] > o[i-1] and c[i-2] > o[i-2] and
                c[i] > c[i-1] > c[i-2] and o[i] > o[i-1] > o[i-2]):
                patterns.append({
                    "name": "Three White Soldiers", "type": "triple",
                    "bias": "BULLISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "VERY HIGH",
                    "description": "Very strong bullish momentum — three consecutive rising green candles.",
                })

            # Three Black Crows
            if (c[i] < o[i] and c[i-1] < o[i-1] and c[i-2] < o[i-2] and
                c[i] < c[i-1] < c[i-2] and o[i] < o[i-1] < o[i-2]):
                patterns.append({
                    "name": "Three Black Crows", "type": "triple",
                    "bias": "BEARISH", "bar_idx": i, "bars_ago": bars_ago,
                    "reliability": "VERY HIGH",
                    "description": "Very strong bearish momentum — three consecutive falling red candles.",
                })

    return patterns


# ==========================================================================
# 8. CHART PATTERN DETECTION
# ==========================================================================

def detect_chart_patterns(df, window=5):
    """
    Detect chart patterns using swing points.

    Returns list of {name, bias, reliability, target, notes}
    """
    patterns = []
    if df.empty or len(df) < 30:
        return patterns

    close = df["close"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    current_price = float(close[-1])
    atr = _calc_atr(df, 14)
    tolerance = atr * 0.5

    # Find swing points
    swing_highs = []
    swing_lows = []
    for i in range(window, len(df) - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            swing_highs.append((i, float(highs[i])))
        if lows[i] == min(lows[i-window:i+window+1]):
            swing_lows.append((i, float(lows[i])))

    # ── Double Top ──
    if len(swing_highs) >= 2:
        h1 = swing_highs[-2]
        h2 = swing_highs[-1]
        if abs(h1[1] - h2[1]) <= tolerance and h2[0] - h1[0] > 5:
            neckline = min(lows[h1[0]:h2[0]+1]) if h1[0] < h2[0] else current_price
            target = neckline - (h1[1] - neckline)
            patterns.append({
                "name": "Double Top",
                "bias": "BEARISH",
                "reliability": "HIGH",
                "neckline": round(float(neckline), 4),
                "target": round(float(target), 4),
                "notes": f"Bearish reversal pattern. Two peaks near {h1[1]:.2f}. Target: {target:.2f}",
            })

    # ── Double Bottom ──
    if len(swing_lows) >= 2:
        l1 = swing_lows[-2]
        l2 = swing_lows[-1]
        if abs(l1[1] - l2[1]) <= tolerance and l2[0] - l1[0] > 5:
            neckline = max(highs[l1[0]:l2[0]+1]) if l1[0] < l2[0] else current_price
            target = neckline + (neckline - l1[1])
            patterns.append({
                "name": "Double Bottom",
                "bias": "BULLISH",
                "reliability": "HIGH",
                "neckline": round(float(neckline), 4),
                "target": round(float(target), 4),
                "notes": f"Bullish reversal pattern. Two troughs near {l1[1]:.2f}. Target: {target:.2f}",
            })

    # ── Head and Shoulders ──
    if len(swing_highs) >= 3:
        left = swing_highs[-3]
        head = swing_highs[-2]
        right = swing_highs[-1]
        if (head[1] > left[1] and head[1] > right[1] and
            abs(left[1] - right[1]) <= tolerance * 2):
            neckline = min(lows[left[0]:right[0]+1]) if left[0] < right[0] else current_price
            target = neckline - (head[1] - neckline)
            patterns.append({
                "name": "Head & Shoulders",
                "bias": "BEARISH",
                "reliability": "VERY HIGH",
                "neckline": round(float(neckline), 4),
                "target": round(float(target), 4),
                "notes": f"Classic bearish reversal. Head at {head[1]:.2f}, neckline at {neckline:.2f}.",
            })

    # ── Inverse Head and Shoulders ──
    if len(swing_lows) >= 3:
        left = swing_lows[-3]
        head = swing_lows[-2]
        right = swing_lows[-1]
        if (head[1] < left[1] and head[1] < right[1] and
            abs(left[1] - right[1]) <= tolerance * 2):
            neckline = max(highs[left[0]:right[0]+1]) if left[0] < right[0] else current_price
            target = neckline + (neckline - head[1])
            patterns.append({
                "name": "Inverse Head & Shoulders",
                "bias": "BULLISH",
                "reliability": "VERY HIGH",
                "neckline": round(float(neckline), 4),
                "target": round(float(target), 4),
                "notes": f"Classic bullish reversal. Head at {head[1]:.2f}, neckline at {neckline:.2f}.",
            })

    # ── Rising Wedge (bearish) ──
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        h_slope = (swing_highs[-1][1] - swing_highs[-2][1]) / max(1, swing_highs[-1][0] - swing_highs[-2][0])
        l_slope = (swing_lows[-1][1] - swing_lows[-2][1]) / max(1, swing_lows[-1][0] - swing_lows[-2][0])
        if h_slope > 0 and l_slope > 0 and l_slope > h_slope:
            patterns.append({
                "name": "Rising Wedge",
                "bias": "BEARISH",
                "reliability": "MODERATE",
                "neckline": round(float(swing_lows[-1][1]), 4),
                "target": round(float(swing_lows[-2][1]), 4),
                "notes": "Bearish pattern: converging rising trendlines suggest weakening uptrend.",
            })

    # ── Falling Wedge (bullish) ──
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        h_slope = (swing_highs[-1][1] - swing_highs[-2][1]) / max(1, swing_highs[-1][0] - swing_highs[-2][0])
        l_slope = (swing_lows[-1][1] - swing_lows[-2][1]) / max(1, swing_lows[-1][0] - swing_lows[-2][0])
        if h_slope < 0 and l_slope < 0 and h_slope < l_slope:
            patterns.append({
                "name": "Falling Wedge",
                "bias": "BULLISH",
                "reliability": "MODERATE",
                "neckline": round(float(swing_highs[-1][1]), 4),
                "target": round(float(swing_highs[-2][1]), 4),
                "notes": "Bullish pattern: converging falling trendlines suggest weakening downtrend.",
            })

    return patterns



# ==========================================================================
# 8b. ADVANCED INDICATORS (MACD, BB, STOCH, VWAP, SMC)
# ==========================================================================

def analyze_advanced_indicators(df):
    """Calculate MACD, Bollinger Bands, Stochastic, VWAP, and SMC."""
    result = {
        "macd": {"macd": None, "signal": None, "hist": None, "trend": "NEUTRAL"},
        "bbands": {"upper": None, "mid": None, "lower": None, "position": "NEUTRAL"},
        "stoch": {"k": None, "d": None, "zone": "NEUTRAL"},
        "vwap": {"value": None, "position": "NEUTRAL"},
        "smc": {"fvg_bullish": [], "fvg_bearish": [], "ob_bullish": [], "ob_bearish": []}
    }
    
    if df.empty or len(df) < 50:
        return result
        
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    open_arr = df['open'].values.astype(float)
    current_price = float(close[-1])
    
    try:
        import pandas_ta as ta
        
        # MACD
        macd_df = df.ta.macd(fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            result["macd"]["macd"] = macd_df.iloc[:, 0].values
            result["macd"]["hist"] = macd_df.iloc[:, 1].values
            result["macd"]["signal"] = macd_df.iloc[:, 2].values
            
            hist_val = result["macd"]["hist"][-1]
            if hist_val > 0 and hist_val > result["macd"]["hist"][-2]:
                result["macd"]["trend"] = "STRONG BULLISH"
            elif hist_val > 0:
                result["macd"]["trend"] = "WEAK BULLISH"
            elif hist_val < 0 and hist_val < result["macd"]["hist"][-2]:
                result["macd"]["trend"] = "STRONG BEARISH"
            else:
                result["macd"]["trend"] = "WEAK BEARISH"
                
        # Bollinger Bands
        bb_df = df.ta.bbands(length=20, std=2)
        if bb_df is not None and not bb_df.empty:
            result["bbands"]["lower"] = bb_df.iloc[:, 0].values
            result["bbands"]["mid"] = bb_df.iloc[:, 1].values
            result["bbands"]["upper"] = bb_df.iloc[:, 2].values
            
            if current_price > result["bbands"]["upper"][-1]:
                result["bbands"]["position"] = "ABOVE UPPER (OVERBOUGHT)"
            elif current_price < result["bbands"]["lower"][-1]:
                result["bbands"]["position"] = "BELOW LOWER (OVERSOLD)"
            elif current_price > result["bbands"]["mid"][-1]:
                result["bbands"]["position"] = "ABOVE MID (BULLISH)"
            else:
                result["bbands"]["position"] = "BELOW MID (BEARISH)"
                
        # Stochastic
        stoch_df = df.ta.stoch(k=14, d=3, smooth_k=3)
        if stoch_df is not None and not stoch_df.empty:
            result["stoch"]["k"] = stoch_df.iloc[:, 0].values
            result["stoch"]["d"] = stoch_df.iloc[:, 1].values
            
            k_val = result["stoch"]["k"][-1]
            if k_val > 80:
                result["stoch"]["zone"] = "OVERBOUGHT"
            elif k_val < 20:
                result["stoch"]["zone"] = "OVERSOLD"
                
        # VWAP
        if 'volume' in df.columns:
            # Need datetime index for VWAP
            if not isinstance(df.index, pd.DatetimeIndex):
                try:
                    temp_df = df.copy()
                    temp_df.index = pd.to_datetime(temp_df.index)
                    vwap_series = temp_df.ta.vwap()
                    if vwap_series is not None:
                        result["vwap"]["value"] = vwap_series.values
                except:
                    # Fallback
                    v = df['volume'].values
                    tp = (high + low + close) / 3
                    result["vwap"]["value"] = np.cumsum(tp * v) / (np.cumsum(v) + 1e-10)
            else:
                vwap_series = df.ta.vwap()
                if vwap_series is not None:
                    result["vwap"]["value"] = vwap_series.values
            
            if result["vwap"]["value"] is not None and not np.isnan(result["vwap"]["value"][-1]):
                if current_price > result["vwap"]["value"][-1]:
                    result["vwap"]["position"] = "ABOVE VWAP (BULLISH)"
                else:
                    result["vwap"]["position"] = "BELOW VWAP (BEARISH)"
                    
    except Exception as e:
        logger.error(f"pandas_ta error: {e}")
        
    # --- Smart Money Concepts (SMC) Simplified ---
    # 1. Fair Value Gaps (FVG)
    for i in range(2, len(df)):
        # Bullish FVG: Low of candle i > High of candle i-2
        if low[i] > high[i-2] and close[i-1] > open_arr[i-1]:
            result["smc"]["fvg_bullish"].append({
                "idx": i-1, "top": float(low[i]), "bottom": float(high[i-2])
            })
        # Bearish FVG: High of candle i < Low of candle i-2
        if high[i] < low[i-2] and close[i-1] < open_arr[i-1]:
            result["smc"]["fvg_bearish"].append({
                "idx": i-1, "top": float(low[i-2]), "bottom": float(high[i])
            })
            
    # Filter only unmitigated (unfilled) FVGs (keep last 5)
    def filter_unmitigated(fvgs, is_bullish):
        unmitigated = []
        for fvg in reversed(fvgs):
            filled = False
            for j in range(fvg["idx"] + 2, len(df)):
                if is_bullish and low[j] < fvg["bottom"]:
                    filled = True
                    break
                if not is_bullish and high[j] > fvg["top"]:
                    filled = True
                    break
            if not filled:
                unmitigated.append(fvg)
            if len(unmitigated) >= 3:
                break
        return unmitigated
        
    result["smc"]["fvg_bullish"] = filter_unmitigated(result["smc"]["fvg_bullish"], True)
    result["smc"]["fvg_bearish"] = filter_unmitigated(result["smc"]["fvg_bearish"], False)
    
    # 2. Order Blocks (OB)
    # Simplified: Last down candle before strong up move (Bullish OB)
    # Last up candle before strong down move (Bearish OB)
    atr = _calc_atr(df, 14)
    for i in range(2, len(df)-2):
        body_i = abs(close[i] - open_arr[i])
        
        # Bullish OB: strong bullish engulfing over a bearish candle
        if close[i-1] < open_arr[i-1] and close[i] > open_arr[i] and close[i] > high[i-1] and body_i > atr * 1.5:
            result["smc"]["ob_bullish"].append({
                "idx": i-1, "top": float(high[i-1]), "bottom": float(low[i-1])
            })
            
        # Bearish OB: strong bearish engulfing over a bullish candle
        if close[i-1] > open_arr[i-1] and close[i] < open_arr[i] and close[i] < low[i-1] and body_i > atr * 1.5:
            result["smc"]["ob_bearish"].append({
                "idx": i-1, "top": float(high[i-1]), "bottom": float(low[i-1])
            })
            
    # Keep only the latest 3 OBs
    result["smc"]["ob_bullish"] = result["smc"]["ob_bullish"][-3:]
    result["smc"]["ob_bearish"] = result["smc"]["ob_bearish"][-3:]

    return result


# ==========================================================================
# 9. TRADE SETUP GENERATOR
# ==========================================================================

def generate_trade_setups(df, sr, trendlines, rsi, ema, fib, elliott, candle_patterns, chart_patterns, adv_indicators, is_crypto=False):
    """
    Combine all signals into scored trade setups.

    Returns list of setup dicts with entry, SL, TP, RR, confidence, signals.
    """
    setups = []
    if df.empty:
        return setups

    close = df["close"].values.astype(float)
    current_price = float(close[-1])
    atr = _calc_atr(df, 14)
    currency = "$" if is_crypto else "₹"

    # Collect bullish and bearish signals with weights
    bull_signals = []
    bear_signals = []

    # RSI signals
    if rsi["zone"] == "OVERSOLD":
        bull_signals.append(("RSI Oversold (<30)", 15))
    elif rsi["zone"] == "OVERBOUGHT":
        bear_signals.append(("RSI Overbought (>70)", 15))
    if rsi["bullish_divergence"]:
        bull_signals.append(("RSI Bullish Divergence", 20))
    if rsi["bearish_divergence"]:
        bear_signals.append(("RSI Bearish Divergence", 20))

    # EMA signals
    if ema["ema_stack"] == "BULLISH":
        bull_signals.append(("EMA Stack Bullish (9>21>50)", 15))
    elif ema["ema_stack"] == "BEARISH":
        bear_signals.append(("EMA Stack Bearish (9<21<50)", 15))

    if ema["price_vs_ema200"] == "ABOVE":
        bull_signals.append(("Price Above EMA 200", 10))
    else:
        bear_signals.append(("Price Below EMA 200", 10))

    for xo in ema.get("crossovers", []):
        if xo["bars_ago"] <= 3:
            if xo["signal"] == "BUY":
                bull_signals.append((f"{xo['type']} ({xo['fast']}/{xo['slow']})", 18))
            else:
                bear_signals.append((f"{xo['type']} ({xo['fast']}/{xo['slow']})", 18))

    # Fibonacci
    if fib["price_in_golden_zone"]:
        if fib["direction"] == "DOWN":
            bull_signals.append(("Price in Fibonacci Golden Zone (bounce zone)", 20))
        else:
            bear_signals.append(("Price in Fibonacci Golden Zone (rejection zone)", 20))

    # Trendline
    if trendlines["trend_direction"] == "UP":
        bull_signals.append(("Overall Uptrend (regression)", 10))
    elif trendlines["trend_direction"] == "DOWN":
        bear_signals.append(("Overall Downtrend (regression)", 10))

    # Elliott Wave
    if elliott["pattern"] == "IMPULSE":
        if elliott.get("current_wave") == 5:
            bear_signals.append(("Elliott Wave 5 complete — expect correction", 15))
    elif elliott["pattern"] == "CORRECTIVE":
        bull_signals.append(("Elliott ABC correction may be ending", 12))

    # Candlestick patterns
    for cp in candle_patterns:
        if cp["bars_ago"] <= 2:
            weight = {"VERY HIGH": 18, "HIGH": 14, "MODERATE": 10}.get(cp["reliability"], 8)
            if cp["bias"] == "BULLISH":
                bull_signals.append((f"Candle: {cp['name']}", weight))
            elif cp["bias"] == "BEARISH":
                bear_signals.append((f"Candle: {cp['name']}", weight))

    # Chart patterns
    for cp in chart_patterns:
        weight = {"VERY HIGH": 20, "HIGH": 16, "MODERATE": 12}.get(cp["reliability"], 10)
        if cp["bias"] == "BULLISH":
            bull_signals.append((f"Chart: {cp['name']}", weight))
        elif cp["bias"] == "BEARISH":
            bear_signals.append((f"Chart: {cp['name']}", weight))
            
    # Advanced Indicators
    if adv_indicators:
        macd = adv_indicators.get("macd", {})
        if "STRONG BULLISH" in macd.get("trend", ""):
            bull_signals.append(("MACD Strong Bullish", 15))
        elif "STRONG BEARISH" in macd.get("trend", ""):
            bear_signals.append(("MACD Strong Bearish", 15))
            
        stoch = adv_indicators.get("stoch", {})
        if stoch.get("zone") == "OVERSOLD":
            bull_signals.append(("Stochastic Oversold", 10))
        elif stoch.get("zone") == "OVERBOUGHT":
            bear_signals.append(("Stochastic Overbought", 10))
            
        vwap = adv_indicators.get("vwap", {})
        if "BULLISH" in vwap.get("position", ""):
            bull_signals.append(("Price > VWAP", 10))
        elif "BEARISH" in vwap.get("position", ""):
            bear_signals.append(("Price < VWAP", 10))
            
        bb = adv_indicators.get("bbands", {})
        if "OVERSOLD" in bb.get("position", ""):
            bull_signals.append(("BB Lower Band (Bounce)", 12))
        elif "OVERBOUGHT" in bb.get("position", ""):
            bear_signals.append(("BB Upper Band (Rejection)", 12))
            
        smc = adv_indicators.get("smc", {})
        if smc.get("fvg_bullish"):
            bull_signals.append(("SMC: Bullish FVG Nearby", 15))
        if smc.get("fvg_bearish"):
            bear_signals.append(("SMC: Bearish FVG Nearby", 15))
        if smc.get("ob_bullish"):
            bull_signals.append(("SMC: Bullish Order Block", 18))
        if smc.get("ob_bearish"):
            bear_signals.append(("SMC: Bearish Order Block", 18))

    # Calculate scores
    bull_score = sum(w for _, w in bull_signals)
    bear_score = sum(w for _, w in bear_signals)

    # S/R levels for SL/TP
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])

    nearest_support = supports[0]["price"] if supports else current_price - atr * 2
    nearest_resistance = resistances[0]["price"] if resistances else current_price + atr * 2
    deep_support = supports[1]["price"] if len(supports) > 1 else nearest_support - atr
    deep_resistance = resistances[1]["price"] if len(resistances) > 1 else nearest_resistance + atr

    # Generate LONG setup if bull score > threshold
    if bull_score >= 20:
        entry = current_price
        sl = max(nearest_support - atr * 0.3, current_price - atr * 2.5)
        tp1 = nearest_resistance
        tp2 = deep_resistance

        # Use fib extensions for TP if available
        for ext_name, ext_price in fib.get("extensions", {}).items():
            if ext_price > current_price and ext_price > tp1:
                tp2 = max(tp2, ext_price)
                break

        sl_dist = abs(entry - sl)
        tp1_dist = abs(tp1 - entry)
        rr1 = tp1_dist / sl_dist if sl_dist > 0 else 0
        rr2 = abs(tp2 - entry) / sl_dist if sl_dist > 0 else 0

        confidence = min(95, bull_score)
        if bear_score > 30:
            confidence = max(10, confidence - bear_score // 2)

        setups.append({
            "direction": "LONG",
            "entry": round(entry, 4),
            "stop_loss": round(sl, 4),
            "take_profit_1": round(tp1, 4),
            "take_profit_2": round(tp2, 4),
            "sl_pct": round((entry - sl) / entry * 100, 2),
            "tp1_pct": round((tp1 - entry) / entry * 100, 2),
            "tp2_pct": round((tp2 - entry) / entry * 100, 2),
            "rr_ratio_1": round(rr1, 2),
            "rr_ratio_2": round(rr2, 2),
            "confidence": confidence,
            "signals": [s[0] for s in bull_signals],
            "opposing_signals": [s[0] for s in bear_signals],
            "style": "Scalping" if rr1 < 1.5 else "Swing",
            "currency": currency,
        })

    # Generate SHORT setup if bear score > threshold
    if bear_score >= 20:
        entry = current_price
        sl = min(nearest_resistance + atr * 0.3, current_price + atr * 2.5)
        tp1 = nearest_support
        tp2 = deep_support

        sl_dist = abs(sl - entry)
        tp1_dist = abs(entry - tp1)
        rr1 = tp1_dist / sl_dist if sl_dist > 0 else 0
        rr2 = abs(entry - tp2) / sl_dist if sl_dist > 0 else 0

        confidence = min(95, bear_score)
        if bull_score > 30:
            confidence = max(10, confidence - bull_score // 2)

        setups.append({
            "direction": "SHORT",
            "entry": round(entry, 4),
            "stop_loss": round(sl, 4),
            "take_profit_1": round(tp1, 4),
            "take_profit_2": round(tp2, 4),
            "sl_pct": round((sl - entry) / entry * 100, 2),
            "tp1_pct": round((entry - tp1) / entry * 100, 2),
            "tp2_pct": round((entry - tp2) / entry * 100, 2),
            "rr_ratio_1": round(rr1, 2),
            "rr_ratio_2": round(rr2, 2),
            "confidence": confidence,
            "signals": [s[0] for s in bear_signals],
            "opposing_signals": [s[0] for s in bull_signals],
            "style": "Scalping" if rr1 < 1.5 else "Swing",
            "currency": currency,
        })

    return sorted(setups, key=lambda x: x["confidence"], reverse=True)


# ==========================================================================
# HELPER: ATR
# ==========================================================================

def _calc_atr(df, period=14):
    """Calculate ATR."""
    try:
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        tr = []
        for i in range(1, len(h)):
            tr.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))
        if not tr:
            return float((df["high"] - df["low"]).mean())
        return float(pd.Series(tr).ewm(span=period, adjust=False).mean().iloc[-1])
    except Exception:
        return float((df["high"] - df["low"]).mean())


# ==========================================================================
# MASTER ANALYSIS FUNCTION
# ==========================================================================

def run_full_analysis(df, is_crypto=False):
    """
    Run all analysis engines on a single OHLCV DataFrame.

    Returns a comprehensive dict with all analysis results.
    """
    sr = detect_support_resistance(df)
    trendlines = detect_trendlines(df)
    rsi = analyze_rsi(df)
    ema = analyze_ema_crossovers(df)
    fib = analyze_fibonacci(df)
    
    # Advanced indicators (VWAP, BB, MACD, Stoch, SMC)
    adv_indicators = analyze_advanced_indicators(df)

    # Use smaller zigzag for intraday, larger for daily
    bars = len(df)
    zigzag_pct = 2.0 if bars > 200 else 3.0 if bars > 100 else 5.0
    elliott = analyze_elliott_waves(df, zigzag_pct=zigzag_pct)

    candle_patterns = detect_candlestick_patterns(df)
    chart_patterns = detect_chart_patterns(df)

    setups = generate_trade_setups(
        df, sr, trendlines, rsi, ema, fib, elliott,
        candle_patterns, chart_patterns, adv_indicators, is_crypto=is_crypto
    )

    current_price = float(df["close"].iloc[-1])
    atr = _calc_atr(df, 14)

    # Overall bias calculation
    bull_count = sum(1 for cp in candle_patterns if cp["bias"] == "BULLISH")
    bear_count = sum(1 for cp in candle_patterns if cp["bias"] == "BEARISH")
    bull_chart = sum(1 for cp in chart_patterns if cp["bias"] == "BULLISH")
    bear_chart = sum(1 for cp in chart_patterns if cp["bias"] == "BEARISH")

    bias_score = 0
    if rsi["zone"] == "OVERSOLD": bias_score += 2
    elif rsi["zone"] == "OVERBOUGHT": bias_score -= 2
    if rsi["bullish_divergence"]: bias_score += 3
    if rsi["bearish_divergence"]: bias_score -= 3
    if ema["ema_stack"] == "BULLISH": bias_score += 2
    elif ema["ema_stack"] == "BEARISH": bias_score -= 2
    if ema["price_vs_ema200"] == "ABOVE": bias_score += 1
    else: bias_score -= 1
    if fib["price_in_golden_zone"]:
        bias_score += 2 if fib["direction"] == "DOWN" else -2
    if trendlines["trend_direction"] == "UP": bias_score += 1
    elif trendlines["trend_direction"] == "DOWN": bias_score -= 1
    bias_score += bull_count - bear_count + bull_chart - bear_chart

    if bias_score >= 3:
        overall_bias = "STRONG BULLISH"
        bias_emoji = "🟢🟢"
    elif bias_score >= 1:
        overall_bias = "BULLISH"
        bias_emoji = "🟢"
    elif bias_score <= -3:
        overall_bias = "STRONG BEARISH"
        bias_emoji = "🔴🔴"
    elif bias_score <= -1:
        overall_bias = "BEARISH"
        bias_emoji = "🔴"
    else:
        overall_bias = "NEUTRAL"
        bias_emoji = "🟡"

    return {
        "current_price": current_price,
        "atr": round(atr, 4),
        "atr_pct": round(atr / current_price * 100, 3),
        "support_resistance": sr,
        "trendlines": trendlines,
        "rsi": rsi,
        "ema": ema,
        "fibonacci": fib,
        "elliott_wave": elliott,
        "candlestick_patterns": candle_patterns,
        "chart_patterns": chart_patterns,
        "adv_indicators": adv_indicators,
        "trade_setups": setups,
        "overall_bias": overall_bias,
        "bias_emoji": bias_emoji,
        "bias_score": bias_score,
    }


# ==========================================================================
# 10. PLOTLY CHART BUILDER
# ==========================================================================

def build_analysis_chart(df, analysis, symbol, timeframe):
    """Build an interactive Plotly chart with all analysis overlays."""

    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.5, 0.15, 0.15, 0.1, 0.1],
        subplot_titles=[f"{symbol} | {timeframe}", "RSI (14)", "MACD", "Stochastic", "Volume"],
    )

    # ── Candlestick chart ──
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="Price", increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # ── Support & Resistance lines ──
    sr = analysis["support_resistance"]
    colors_s = ["#4caf50", "#66bb6a", "#81c784"]
    colors_r = ["#f44336", "#ef5350", "#e57373"]
    for i, s in enumerate(sr.get("supports", [])):
        fig.add_hline(
            y=s["price"], line_dash="dash",
            line_color=colors_s[min(i, 2)],
            annotation_text=f"S{i+1}: {s['price']:.2f} ({s['touches']}x)",
            annotation_position="bottom right",
            row=1, col=1,
        )
    for i, r in enumerate(sr.get("resistances", [])):
        fig.add_hline(
            y=r["price"], line_dash="dash",
            line_color=colors_r[min(i, 2)],
            annotation_text=f"R{i+1}: {r['price']:.2f} ({r['touches']}x)",
            annotation_position="top right",
            row=1, col=1,
        )

    # ── Fibonacci levels ──
    fib = analysis["fibonacci"]
    fib_colors = {
        "23.6%": "rgba(255,235,59,0.3)", "38.2%": "rgba(255,193,7,0.3)",
        "50.0%": "rgba(255,152,0,0.4)", "61.8% (Golden)": "rgba(255,87,34,0.5)",
        "78.6%": "rgba(244,67,54,0.3)",
    }
    for name, price in fib.get("levels", {}).items():
        short_name = name.split("(")[0].strip()
        if short_name in ["0.0%", "100.0%"]:
            continue
        color = fib_colors.get(name, "rgba(158,158,158,0.3)")
        fig.add_hline(
            y=price, line_dash="dot", line_color=color, line_width=1,
            annotation_text=f"Fib {name}: {price:.2f}",
            annotation_position="left", annotation_font_size=9,
            row=1, col=1,
        )

    # ── Fibonacci Golden Zone shading ──
    gz = fib.get("golden_zone", {})
    if gz.get("upper") and gz.get("lower"):
        fig.add_hrect(
            y0=gz["lower"], y1=gz["upper"],
            fillcolor="rgba(255,152,0,0.12)", line_width=0,
            annotation_text="Golden Zone", annotation_position="top left",
            row=1, col=1,
        )

    # ── EMA lines ──
    ema_data = analysis["ema"]["emas"]
    ema_colors = {9: "#ff9800", 21: "#2196f3", 50: "#9c27b0", 200: "#ffffff"}
    for period, arr in ema_data.items():
        if arr is not None and not np.all(np.isnan(arr)):
            fig.add_trace(go.Scatter(
                x=df.index, y=arr,
                name=f"EMA {period}", line=dict(width=1, color=ema_colors.get(period, "#888")),
                opacity=0.7,
            ), row=1, col=1)

    # ── Trendlines ──
    tl = analysis["trendlines"]
    lr = tl.get("linear_regression")
    if lr:
        x_arr = np.arange(len(df))
        y_lr = lr["slope"] * x_arr + lr["intercept"]
        fig.add_trace(go.Scatter(
            x=df.index, y=y_lr,
            name="Linear Regression", line=dict(width=1, dash="dot", color="rgba(255,255,255,0.4)"),
        ), row=1, col=1)
    up_tl = tl.get("uptrend")
    if up_tl:
        si = int(up_tl.get("start_idx", 0))
        si = max(0, min(si, len(df) - 1))
        y_up = [up_tl["slope"] * i + up_tl["intercept"] for i in range(si, len(df))]
        fig.add_trace(go.Scatter(
            x=df.index[si:], y=y_up,
            name="Uptrend line", line=dict(width=2, dash="dash", color="#4caf50"),
        ), row=1, col=1)
    dn_tl = tl.get("downtrend")
    if dn_tl:
        si = int(dn_tl.get("start_idx", 0))
        si = max(0, min(si, len(df) - 1))
        y_dn = [dn_tl["slope"] * i + dn_tl["intercept"] for i in range(si, len(df))]
        fig.add_trace(go.Scatter(
            x=df.index[si:], y=y_dn,
            name="Downtrend line", line=dict(width=2, dash="dash", color="#ef5350"),
        ), row=1, col=1)

    # ── Elliott Wave annotations ──
    ew = analysis["elliott_wave"]
    if ew["waves"]:
        for w in ew["waves"]:
            label = str(w["wave_num"])
            fig.add_annotation(
                x=df.index[min(w["end_idx"], len(df)-1)],
                y=w["end_price"],
                text=label,
                showarrow=True, arrowhead=2, arrowsize=0.8,
                font=dict(size=11, color="#ffeb3b", family="Arial Black"),
                bgcolor="rgba(0,0,0,0.6)", bordercolor="#ffeb3b",
                row=1, col=1,
            )

    # ── Candlestick pattern annotations ──
    for cp in analysis.get("candlestick_patterns", []):
        if cp["bar_idx"] < len(df):
            color = "#4caf50" if cp["bias"] == "BULLISH" else "#f44336" if cp["bias"] == "BEARISH" else "#ffc107"
            fig.add_annotation(
                x=df.index[cp["bar_idx"]],
                y=float(df["high"].iloc[cp["bar_idx"]]) * 1.002,
                text=cp["name"][:10],
                showarrow=True, arrowhead=1,
                font=dict(size=8, color=color),
                bgcolor="rgba(0,0,0,0.7)",
                row=1, col=1,
            )

    # ── RSI subplot ──
    rsi_vals = analysis["rsi"].get("rsi_values")
    if rsi_vals is not None:
        fig.add_trace(go.Scatter(
            x=df.index, y=rsi_vals,
            name="RSI(14)", line=dict(color="#e040fb", width=1.5),
        ), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="rgba(244,67,54,0.5)", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="rgba(76,175,80,0.5)", row=2, col=1)
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(244,67,54,0.08)", line_width=0, row=2, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(76,175,80,0.08)", line_width=0, row=2, col=1)

    # ── Advanced Indicators (VWAP, BB, SMC) on main chart ──
    adv = analysis.get("adv_indicators", {})
    if adv:
        # VWAP
        vwap = adv.get("vwap", {}).get("value")
        if vwap is not None and not np.all(np.isnan(vwap)):
            fig.add_trace(go.Scatter(
                x=df.index, y=vwap, name="VWAP",
                line=dict(color="#ffff00", width=1.5, dash="dot"), opacity=0.8
            ), row=1, col=1)
            
        # Bollinger Bands
        bb = adv.get("bbands", {})
        bb_u, bb_m, bb_l = bb.get("upper"), bb.get("mid"), bb.get("lower")
        if bb_u is not None and not np.all(np.isnan(bb_u)):
            fig.add_trace(go.Scatter(x=df.index, y=bb_u, name="BB Upper", line=dict(color="rgba(33, 150, 243, 0.4)", width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=bb_l, name="BB Lower", line=dict(color="rgba(33, 150, 243, 0.4)", width=1), fill="tonexty", fillcolor="rgba(33, 150, 243, 0.05)"), row=1, col=1)
            
        # SMC: Order Blocks (last 2)
        smc = adv.get("smc", {})
        for ob in smc.get("ob_bullish", [])[-2:]:
            fig.add_hrect(y0=ob["bottom"], y1=ob["top"], fillcolor="rgba(76, 175, 80, 0.15)", line_width=1, line_color="rgba(76, 175, 80, 0.5)", annotation_text="Bullish OB", annotation_position="left", row=1, col=1)
        for ob in smc.get("ob_bearish", [])[-2:]:
            fig.add_hrect(y0=ob["bottom"], y1=ob["top"], fillcolor="rgba(244, 67, 54, 0.15)", line_width=1, line_color="rgba(244, 67, 54, 0.5)", annotation_text="Bearish OB", annotation_position="left", row=1, col=1)

    # ── MACD subplot ──
    macd = adv.get("macd", {})
    if macd.get("macd") is not None:
        fig.add_trace(go.Scatter(x=df.index, y=macd["macd"], name="MACD", line=dict(color="#2962FF", width=1.5)), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=macd["signal"], name="Signal", line=dict(color="#FF6D00", width=1.5)), row=3, col=1)
        colors_hist = ["#26a69a" if val >= 0 else "#ef5350" for val in macd["hist"]]
        fig.add_trace(go.Bar(x=df.index, y=macd["hist"], name="Histogram", marker_color=colors_hist), row=3, col=1)

    # ── Stochastic subplot ──
    stoch = adv.get("stoch", {})
    if stoch.get("k") is not None:
        fig.add_trace(go.Scatter(x=df.index, y=stoch["k"], name="%K", line=dict(color="#00E676", width=1.5)), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=stoch["d"], name="%D", line=dict(color="#FF1744", width=1.5)), row=4, col=1)
        fig.add_hline(y=80, line_dash="dash", line_color="rgba(244,67,54,0.5)", row=4, col=1)
        fig.add_hline(y=20, line_dash="dash", line_color="rgba(76,175,80,0.5)", row=4, col=1)

    # ── Volume subplot ──
    if "volume" in df.columns:
        colors = ["#26a69a" if c >= o else "#ef5350"
                  for c, o in zip(df["close"], df["open"])]
        fig.add_trace(go.Bar(
            x=df.index, y=df["volume"],
            name="Volume", marker_color=colors, opacity=0.6,
        ), row=5, col=1)

    # Layout
    fig.update_layout(
        template="plotly_dark",
        height=1000,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=9)),
        xaxis_rangeslider_visible=False,
        margin=dict(l=60, r=20, t=60, b=30),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    fig.update_yaxes(title_text="Stoch", row=4, col=1, range=[0, 100])
    fig.update_yaxes(title_text="Vol", row=5, col=1)

    return fig


# ==========================================================================
# 11. AI ANALYSIS HELPERS
# ==========================================================================

def _render_pa_ai_config():
    """AI provider configuration (mirrors News Scanner settings)."""
    return render_ai_config("pa", caption="AI View uses these settings for per-ticker technical reports.")


def build_price_action_ai_prompt(symbol, timeframe, market, analysis, currency):
    """Serialize price-action analysis output into an AI prompt."""
    lines = [
        f"=== PRICE ACTION ANALYSIS ===",
        f"Symbol: {symbol}",
        f"Timeframe: {timeframe}",
        f"Market: {market}",
        f"Current Price: {currency}{analysis['current_price']:,.4f}",
        f"ATR: {currency}{analysis['atr']:,.4f} ({analysis['atr_pct']:.2f}%)",
        f"Overall Bias: {analysis['overall_bias']} (score: {analysis.get('bias_score', 0)})",
        "",
        "=== TREND & MOMENTUM ===",
        f"Trend Direction: {analysis['trendlines']['trend_direction']}",
        f"RSI: {analysis['rsi']['current_rsi']:.1f} — Zone: {analysis['rsi']['zone']}",
        f"RSI Bullish Divergence: {analysis['rsi']['bullish_divergence']}",
        f"RSI Bearish Divergence: {analysis['rsi']['bearish_divergence']}",
        f"EMA Stack: {analysis['ema']['ema_stack']}",
        f"Price vs EMA200: {analysis['ema'].get('price_vs_ema200', 'N/A')}",
    ]

    adv = analysis.get("adv_indicators", {})
    if adv:
        macd = adv.get("macd", {})
        stoch = adv.get("stoch", {})
        vwap = adv.get("vwap", {})
        bb = adv.get("bbands", {})
        smc = adv.get("smc", {})
        lines.extend([
            f"MACD Trend: {macd.get('trend', 'N/A')}",
            f"Stochastic Zone: {stoch.get('zone', 'N/A')}",
            f"VWAP Position: {vwap.get('position', 'N/A')}",
            f"Bollinger Position: {bb.get('position', 'N/A')}",
            f"SMC Bullish OB: {len(smc.get('ob_bullish', []))} | Bearish OB: {len(smc.get('ob_bearish', []))}",
            f"SMC Bullish FVG: {len(smc.get('fvg_bullish', []))} | Bearish FVG: {len(smc.get('fvg_bearish', []))}",
        ])

    fib = analysis["fibonacci"]
    lines.extend([
        "",
        "=== FIBONACCI ===",
        f"Direction: {fib.get('direction', 'N/A')}",
        f"Price in Golden Zone: {fib.get('price_in_golden_zone', False)}",
    ])
    for name, price in fib.get("levels", {}).items():
        lines.append(f"  {name}: {currency}{price:,.4f}")

    sr = analysis["support_resistance"]
    lines.append("\n=== SUPPORT & RESISTANCE ===")
    for i, s in enumerate(sr.get("supports", []), 1):
        lines.append(f"  Support {i}: {currency}{s['price']:,.4f} (strength {s['strength']})")
    for i, r in enumerate(sr.get("resistances", []), 1):
        lines.append(f"  Resistance {i}: {currency}{r['price']:,.4f} (strength {r['strength']})")

    ew = analysis["elliott_wave"]
    if ew.get("pattern") != "NONE":
        lines.extend([
            "",
            "=== ELLIOTT WAVE ===",
            f"Pattern: {ew['pattern']}",
            f"Current Wave: {ew.get('current_wave', 'N/A')}",
            f"Notes: {ew.get('notes', '')}",
        ])
        for name, price in ew.get("wave_targets", {}).items():
            lines.append(f"  {name}: {currency}{price:,.4f}")

    cps = analysis.get("candlestick_patterns", [])
    if cps:
        lines.append("\n=== CANDLESTICK PATTERNS ===")
        for cp in cps[:10]:
            lines.append(
                f"  - {cp['name']} ({cp['bias']}, {cp['reliability']}) — {cp['description'][:100]}"
            )

    chps = analysis.get("chart_patterns", [])
    if chps:
        lines.append("\n=== CHART PATTERNS ===")
        for cp in chps:
            lines.append(
                f"  - {cp['name']} ({cp['bias']}, {cp['reliability']}) "
                f"Target: {currency}{cp['target']:,.4f} — {cp.get('notes', '')}"
            )

    setups = analysis.get("trade_setups", [])
    lines.append("\n=== ENGINE-GENERATED TRADE SETUPS ===")
    if setups:
        for i, setup in enumerate(setups, 1):
            lines.extend([
                f"Setup {i}: {setup['direction']} | Confidence {setup['confidence']}% | Style: {setup['style']}",
                f"  Entry: {currency}{setup['entry']:,.4f}",
                f"  Stop Loss: {currency}{setup['stop_loss']:,.4f} ({setup['sl_pct']:.2f}%)",
                f"  TP1: {currency}{setup['take_profit_1']:,.4f} ({setup['tp1_pct']:.2f}%)",
                f"  TP2: {currency}{setup['take_profit_2']:,.4f} ({setup['tp2_pct']:.2f}%)",
                f"  R:R TP1: {setup['rr_ratio_1']:.2f} | R:R TP2: {setup['rr_ratio_2']:.2f}",
                f"  Signals: {', '.join(setup.get('signals', [])[:8])}",
                f"  Opposing: {', '.join(setup.get('opposing_signals', [])[:4])}",
            ])
    else:
        lines.append("  No clear automated setup — signals conflicting or weak.")

    return "\n".join(lines)


def get_price_action_ai_report(prompt_data, provider, model, api_key):
    """Call AI provider for a price-action trade report."""
    system = """You are an expert technical analyst specializing in price action, Elliott Wave,
support/resistance, candlestick patterns, and multi-timeframe analysis for Indian equities (NSE/BSE)
and cryptocurrency futures.

Analyze the provided technical data. Be data-driven and reference specific levels from the input.
If signals strongly conflict or confidence is low, verdict must be AVOID.
For every BUY or SELL verdict, specify holding time, green signs to stay in, and red flags to exit.
""" + STANDARD_REPORT_FORMAT

    user_msg = f"Analyze this price action output and give a trade verdict with setup:\n\n{prompt_data}"

    if provider == "Custom / Other":
        return "❌ Custom / Other AI provider is not supported for AI View. Use Groq or Google Gemini."

    if not api_key:
        return f"❌ {api_key_env_hint(provider)}"

    try:
        if provider == "Groq (LLaMA)":
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=2500,
                temperature=0.35,
            )
            return resp.choices[0].message.content
        elif provider == "Google Gemini":
            if GENAI_NEW:
                client = genai_new.Client(api_key=api_key)
                combined = system + "\n\n" + user_msg
                resp = client.models.generate_content(model=model, contents=combined)
                return resp.text
            elif genai:
                genai.configure(api_key=api_key)
                gmodel = genai.GenerativeModel(model, system_instruction=system)
                resp = gmodel.generate_content(user_msg)
                return resp.text
            return "❌ Google Gemini library not installed."
    except Exception as e:
        return f"❌ AI Report Error: {str(e)}\n\nPlease check your API key and model selection."


def _parse_ai_verdict(report_text):
    """Extract BUY/SELL/AVOID from AI report for banner styling."""
    match = re.search(
        r"##\s*FINAL\s*VERDICT\s*\n\s*(BUY|SELL|AVOID)",
        report_text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"\b(BUY|SELL|AVOID)\b", report_text[:400], re.IGNORECASE)
    if not match:
        return None, "#94a3b8", "⚪"
    verdict = match.group(1).upper()
    colors = {"BUY": "#10b981", "SELL": "#ef4444", "AVOID": "#f59e0b"}
    emojis = {"BUY": "🟢", "SELL": "🔴", "AVOID": "🟡"}
    return verdict, colors.get(verdict, "#94a3b8"), emojis.get(verdict, "⚪")


def _escape_streamlit_markdown(text):
    """Escape $ so Streamlit does not treat prices as LaTeX math."""
    return text.replace("$", "\\$")


def _strip_verdict_header(report_text):
    """Remove the FINAL VERDICT line from body when shown in the banner."""
    return re.sub(
        r"##\s*FINAL\s*VERDICT\s*\n\s*(?:BUY|SELL|AVOID)\s*\n*",
        "",
        report_text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _render_pa_ai_report(symbol, timeframe, report_text, provider, model):
    """Render AI report using native Streamlit widgets (theme-friendly, no raw HTML)."""
    if report_text.startswith("❌"):
        st.error(report_text)
        return

    verdict, _, vemoji = _parse_ai_verdict(report_text)
    body = _strip_verdict_header(report_text)

    with st.container(border=True):
        st.caption(f"🤖 AI View · {symbol} · {timeframe} · {provider} · {model}")

        if verdict == "BUY":
            st.success(f"{vemoji} **AI FINAL VERDICT: {verdict}**")
        elif verdict == "SELL":
            st.error(f"{vemoji} **AI FINAL VERDICT: {verdict}**")
        elif verdict == "AVOID":
            st.warning(f"{vemoji} **AI FINAL VERDICT: {verdict}**")
        else:
            st.info("⚪ AI verdict could not be parsed from the response.")

        st.markdown(_escape_streamlit_markdown(body))


def _safe_pa_key(key):
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _display_pa_result_block(key, data, is_crypto, pa_market, provider, model, api_key, *, nested: bool = False):
    """Render a single ticker/timeframe analysis block with optional AI View."""
    symbol = data["symbol"]
    tf = data["timeframe"]
    currency = "$" if is_crypto else "₹"
    safe_key = _safe_pa_key(key)

    if "error" in data:
        render_run_summary(summarize_error(symbol, tf, data["error"], tab="Price Action"), compact=True)
        with st.expander(f"❌ {symbol} | {tf} — Error", expanded=False):
            st.error(data["error"])
        return

    df = data["df"]
    a = data["analysis"]
    bias = a["overall_bias"]
    emoji = a["bias_emoji"]
    price = a["current_price"]

    render_run_summary(summarize_price_action(a, symbol, tf), compact=True)

    render_strategy_mtf_panel(
        symbol=symbol,
        market=pa_market,
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("pa_exchange", "NSE"),
        primary_tf=tf,
        strategy_direction=bias if bias in ("BULLISH", "BEARISH", "LONG", "SHORT") else None,
    )

    header_col, ai_col = st.columns([5, 1])
    with header_col:
        if not nested:
            st.markdown(f"### {emoji} {symbol} | {tf} — {bias} | {currency}{price:,.2f}")
        else:
            st.markdown(f"**{emoji} {bias}** · {currency}{price:,.2f}")
    with ai_col:
        ai_clicked = st.button("🤖 AI View", key=f"pa_ai_btn_{safe_key}", width='stretch')

    if ai_clicked:
        st.session_state[f"pa_ai_show_{safe_key}"] = True
        st.session_state[f"pa_ai_refresh_{safe_key}"] = True

    groww_token = get_active_groww_token()
    pa_exchange = st.session_state.get("pa_exchange", "NSE")
    render_price_extremes_for_ticker(
        symbol, df, tf, pa_market, exchange=pa_exchange,
        groww_token=groww_token, currency=currency, compact=True,
    )
    pas_cfg = st.session_state.get("pa_simple_cfg", PASimpleConfig())
    render_price_action_simple_for_ticker(
        df, cfg=pas_cfg, currency=currency, compact=True,
    )

    with st.expander(f"📊 Technical Details — {symbol} | {tf}", expanded=True):
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Trend", a["trendlines"]["trend_direction"])
        sc2.metric("RSI", f"{a['rsi']['current_rsi']:.1f}", delta=a["rsi"]["zone"])
        sc3.metric("EMA Stack", a["ema"]["ema_stack"])
        sc4.metric("ATR %", f"{a['atr_pct']:.2f}%")
        fib_status = "IN ZONE ✓" if a["fibonacci"]["price_in_golden_zone"] else "Outside"
        sc5.metric("Fib Golden", fib_status)

        sc6, sc7, sc8, sc9, sc10 = st.columns(5)
        adv = a.get("adv_indicators", {})
        macd_trend = adv.get("macd", {}).get("trend", "N/A").replace(" ", "\n")
        sc6.metric("MACD", macd_trend)
        stoch_zone = adv.get("stoch", {}).get("zone", "N/A")
        sc7.metric("Stochastic", stoch_zone)
        vwap_pos = adv.get("vwap", {}).get("position", "N/A").split(" ")[0]
        sc8.metric("VWAP", vwap_pos)
        bb_pos = adv.get("bbands", {}).get("position", "N/A").split(" ")[0]
        sc9.metric("Bollinger", bb_pos)

        smc = adv.get("smc", {})
        smc_status = "Neutral"
        if smc.get("ob_bullish") or smc.get("fvg_bullish"):
            smc_status = "Bullish OB/FVG"
        elif smc.get("ob_bearish") or smc.get("fvg_bearish"):
            smc_status = "Bearish OB/FVG"
        sc10.metric("Smart Money", smc_status)

        chart = build_analysis_chart(df, a, symbol, tf)
        st.plotly_chart(chart, width='stretch')

        st.markdown("#### 🎯 Trade Setups")
        setups = a.get("trade_setups", [])
        if setups:
            for setup in setups:
                dir_emoji = "🟢 LONG" if setup["direction"] == "LONG" else "🔴 SHORT"
                conf_bar = "🟩" * (setup["confidence"] // 20) + "⬜" * (5 - setup["confidence"] // 20)
                st.markdown(f"""
**{dir_emoji}** | Confidence: {setup['confidence']}% {conf_bar} | Style: {setup['style']}

| | Price | % from Entry |
|---|---|---|
| **Entry** | `{currency}{setup['entry']:,.4f}` | — |
| **Stop Loss** | `{currency}{setup['stop_loss']:,.4f}` | `{setup['sl_pct']:.2f}%` |
| **Take Profit 1** | `{currency}{setup['take_profit_1']:,.4f}` | `{setup['tp1_pct']:.2f}%` |
| **Take Profit 2** | `{currency}{setup['take_profit_2']:,.4f}` | `{setup['tp2_pct']:.2f}%` |
| **R:R (TP1)** | `{setup['rr_ratio_1']:.2f}` | |
| **R:R (TP2)** | `{setup['rr_ratio_2']:.2f}` | |

✅ **Supporting Signals**: {', '.join(setup['signals'][:6])}
""")
                if setup.get("opposing_signals"):
                    st.caption(f"⚠️ Opposing: {', '.join(setup['opposing_signals'][:4])}")
                st.markdown("---")
        else:
            st.info("No clear trade setup — signals are conflicting or too weak.")

        ew = a["elliott_wave"]
        if ew["pattern"] != "NONE":
            st.markdown("#### 🌊 Elliott Wave Analysis")
            ew_col1, ew_col2 = st.columns([1, 1])
            with ew_col1:
                st.markdown(f"**Pattern**: {ew['pattern']}")
                st.markdown(f"**Current Wave**: {ew['current_wave']}")
                st.caption(ew.get("notes", ""))
            with ew_col2:
                if ew.get("wave_targets"):
                    st.markdown("**Wave Targets:**")
                    for name, p in ew["wave_targets"].items():
                        st.markdown(f"- {name}: `{currency}{p:,.4f}`")

        cps = a.get("candlestick_patterns", [])
        if cps:
            st.markdown("#### 🕯️ Candlestick Patterns Detected")
            cp_rows = [{
                "Pattern": cp["name"], "Bias": cp["bias"], "Type": cp["type"].title(),
                "Reliability": cp["reliability"], "Bars Ago": cp["bars_ago"],
                "Notes": cp["description"][:80],
            } for cp in cps]
            st.dataframe(pd.DataFrame(cp_rows), width='stretch', hide_index=True)

        chps = a.get("chart_patterns", [])
        if chps:
            st.markdown("#### 📐 Chart Patterns Detected")
            for cp in chps:
                bias_icon = "🟢" if cp["bias"] == "BULLISH" else "🔴"
                st.markdown(
                    f"- {bias_icon} **{cp['name']}** ({cp['reliability']}) — "
                    f"Target: `{currency}{cp['target']:,.4f}` | {cp['notes']}"
                )

        st.markdown("#### 🧱 Key Levels")
        sr = a["support_resistance"]
        level_rows = []
        for i, s in enumerate(sr.get("supports", [])):
            level_rows.append({
                "Level": f"Support {i+1}",
                "Price": f"{currency}{s['price']:,.4f}",
                "Strength": "⭐" * min(s["strength"], 5),
                "Touches": s["touches"],
            })
        for i, r in enumerate(sr.get("resistances", [])):
            level_rows.append({
                "Level": f"Resistance {i+1}",
                "Price": f"{currency}{r['price']:,.4f}",
                "Strength": "⭐" * min(r["strength"], 5),
                "Touches": r["touches"],
            })
        if level_rows:
            st.dataframe(pd.DataFrame(level_rows), width='stretch', hide_index=True)

        fib = a["fibonacci"]
        if fib.get("levels"):
            st.markdown("#### 📏 Fibonacci Levels")
            fib_rows = []
            for name, p in fib["levels"].items():
                in_zone = "⬅️ GOLDEN ZONE" if "Golden" in name else ""
                fib_rows.append({"Level": name, "Price": f"{currency}{p:,.4f}", "Note": in_zone})
            st.dataframe(pd.DataFrame(fib_rows), width='stretch', hide_index=True)

    if st.session_state.get(f"pa_ai_show_{safe_key}", False):
        cache_key = f"pa_ai_report_{safe_key}"
        provider, model, api_key = render_block_ai_settings("pa", safe_key)
        force = st.session_state.pop(f"pa_ai_refresh_{safe_key}", False)
        picker_sig = f"{provider}|{model}"
        sig_key = f"pa_ai_sig_{safe_key}"
        if force or cache_key not in st.session_state or st.session_state.get(sig_key) != picker_sig:
            with nullcontext():
                prompt = build_price_action_ai_prompt(symbol, tf, pa_market, a, currency)
                report = get_price_action_ai_report(prompt, provider, model, api_key)
                st.session_state[cache_key] = report
                st.session_state[sig_key] = picker_sig
        _render_pa_ai_report(symbol, tf, st.session_state[cache_key], provider, model)

    bias_label = a.get("overall_bias", "Price Action")
    render_demo_trade_panel(
        "pa",
        key,
        symbol,
        tf,
        pa_market,
        f"Price Action · {bias_label}",
        current_price=price,
        source_tab="Price Action Analyzer",
        groww_token=groww_token,
        exchange=pa_exchange,
    )

    st.markdown("---")


# ==========================================================================
# 12. STREAMLIT UI RENDERER
# ==========================================================================

def render_price_action_tab():
    """Main Streamlit UI for the Price Action Analyzer tab."""

    st.markdown("<h1>🔮 Price Action & Technical Analyzer</h1>", unsafe_allow_html=True)
    st.write(
        "Comprehensive multi-indicator analysis: Support/Resistance, Trendlines, "
        "RSI Divergence, EMA Crossovers, Fibonacci Golden Zone, Elliott Wave, "
        "Candlestick & Chart Patterns — with actionable trade setups."
    )

    provider, model, api_key = _render_pa_ai_config()

    st.markdown("---")

    # ── Market Selection ──
    pa_col1, pa_col2 = st.columns([1, 1])
    with pa_col1:
        pa_market = st.selectbox(
            "🌐 Market",
            MARKET_OPTIONS,
            index=0,
            key="pa_market",
        )
    with pa_col2:
        if is_india_market(pa_market):
            pa_exchange = st.selectbox("Exchange", ["NSE", "BSE"], index=0, key="pa_exchange")
        else:
            pa_exchange = "NSE"

    # ── Ticker Selection (same as other tabs) ──
    st.markdown("### 📊 Select Assets")
    pa_tickers = []
    is_crypto = is_crypto_market(pa_market)

    if is_crypto:
        pa_tickers = render_coindcx_ticker_selection("pa")
    else:
        pa_tickers = render_equity_index_ticker_selection(pa_market, "pa")

    # ── Timeframe & Candle Count ──
    st.markdown("### ⏱️ Timeframes & Candle History")
    pa_tf_col, pa_candle_col = st.columns([1, 1])
    with pa_tf_col:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        pa_timeframes = render_ta_multiselect_timeframes(
            "pa",
            ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            legacy_default=["15m", "1h", "1d"],
            label="Timeframes to Analyze",
        )
    with pa_candle_col:
        pa_candle_count = st.slider(
            "Max Candles (History Depth)",
            min_value=50, max_value=650, value=200, step=50,
            key="pa_candle_count",
            help="More candles = deeper analysis but slower. 200 is a good balance.",
        )

    st.markdown("---")
    render_price_action_simple_section(
        market=pa_market,
        tickers=pa_tickers,
        timeframes=pa_timeframes,
        candle_count=pa_candle_count,
        exchange=pa_exchange,
        key_prefix="pa_simple",
    )

    st.markdown("---")

    # ── Analysis Options ──
    with st.expander("⚙️ Advanced Options", expanded=False):
        pa_sr_window = st.slider("S/R Swing Window", 3, 15, 5, key="pa_sr_window")
        pa_zigzag_pct = st.slider("Elliott Wave ZigZag %", 1.0, 10.0, 3.0, 0.5, key="pa_zigzag_pct")
        pa_fib_lookback = st.slider("Fibonacci Lookback Bars", 30, 300, 100, 10, key="pa_fib_lookback")

    # ── Run Button ──
    st.markdown("---")
    total_scans = len(pa_tickers) * len(pa_timeframes)
    pa_actionable_only = render_ta_screener_options("pa")
    if total_scans > 0:
        st.caption(f"🧮 Total combinations: **{total_scans}** ({len(pa_tickers)} tickers × {len(pa_timeframes)} timeframes)")

    run_pa = st.button("🔎 SCAN PRICE ACTION SETUPS", width="stretch", key="run_pa_btn")

    if run_pa:
        if not pa_tickers:
            st.error("❌ Please select at least one ticker.")
            return
        if not pa_timeframes:
            st.error("❌ Please select at least one timeframe.")
            return

        all_results = {}
        progress = st.progress(0, text="Initializing analysis...")
        scan_idx = 0

        for tick in pa_tickers:
            for tf in pa_timeframes:
                scan_idx += 1
                pct = scan_idx / total_scans
                progress.progress(pct, text=f"Analyzing {tick} | {tf} ({scan_idx}/{total_scans})...")

                try:
                    groww_token = get_active_groww_token()
                    df = fetch_data_for_gap_scan(
                        symbol=tick,
                        timeframe=tf,
                        market=pa_market,
                        groww_token=groww_token,
                        exchange=pa_exchange,
                        limit=pa_candle_count,
                    )

                    if df.empty or len(df) < 20:
                        all_results[f"{tick}|{tf}"] = {
                            "error": f"Insufficient data ({len(df)} bars). Need >= 20.",
                            "symbol": tick, "timeframe": tf,
                        }
                        continue

                    analysis = run_full_analysis(df, is_crypto=is_crypto)
                    # Override with user-selected params
                    analysis["support_resistance"] = detect_support_resistance(df, window=pa_sr_window)
                    analysis["elliott_wave"] = analyze_elliott_waves(df, zigzag_pct=pa_zigzag_pct)
                    analysis["fibonacci"] = analyze_fibonacci(df, lookback=pa_fib_lookback)

                    # Regenerate setups with updated analysis
                    analysis["trade_setups"] = generate_trade_setups(
                        df, analysis["support_resistance"], analysis["trendlines"],
                        analysis["rsi"], analysis["ema"], analysis["fibonacci"],
                        analysis["elliott_wave"], analysis["candlestick_patterns"],
                        analysis["chart_patterns"], analysis.get("adv_indicators", {}), is_crypto=is_crypto,
                    )

                    all_results[f"{tick}|{tf}"] = {
                        "df": df, "analysis": analysis,
                        "symbol": tick, "timeframe": tf,
                    }

                except Exception as e:
                    all_results[f"{tick}|{tf}"] = {
                        "error": str(e)[:200],
                        "symbol": tick, "timeframe": tf,
                    }

                time.sleep(0.05)  # gentle rate limiting

        progress.empty()

        if not all_results:
            st.warning("No results generated.")
            return

        st.session_state.pa_all_results = all_results
        st.session_state.pa_is_crypto = is_crypto
        st.session_state.pa_analysis_market = pa_market

    all_results = st.session_state.get("pa_all_results", {})
    is_crypto = st.session_state.get("pa_is_crypto", False)
    pa_market_display = st.session_state.get("pa_analysis_market", pa_market)

    if all_results:
        st.markdown("---")
        st.markdown("## 📋 Analysis Results")
        if not api_key:
            st.info("💡 Set `GROQ_API_KEY` or `GEMINI_API_KEY` in your `.env` file to use **AI View** on each result.")

        pa_digest = []
        for k, d in all_results.items():
            if "error" in d:
                pa_digest.append(summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Price Action"))
            else:
                pa_digest.append(summarize_price_action(d["analysis"], d["symbol"], d["timeframe"]))
        pa_digest = render_ta_screener_results(
            pa_digest,
            title="🧭 Price Action Screener",
            strategy_label="price action",
            actionable_only=pa_actionable_only,
        )

        tickers_seen = []
        for data in all_results.values():
            sym = data.get("symbol")
            if sym and sym not in tickers_seen:
                tickers_seen.append(sym)

        currency = "$" if is_crypto else "₹"
        for ti, ticker in enumerate(tickers_seen):
            if not should_show_ticker_in_screener(ticker, pa_digest, actionable_only=pa_actionable_only):
                continue
            ticker_items = [(k, v) for k, v in all_results.items() if v.get("symbol") == ticker]
            ticker_summaries = [
                summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Price Action")
                if "error" in d
                else summarize_price_action(d["analysis"], d["symbol"], d["timeframe"])
                for _, d in ticker_items
            ]

            with st.expander(
                ticker_section_label(ticker, ticker_summaries),
                expanded=should_expand_ticker(ti),
            ):
                if api_key and ticker_items:
                    _, mtf_btn = st.columns([4, 1])
                    with mtf_btn:
                        mtf_ticker_button("pa", ticker)

                    def _build_pa_mtf(
                        items=ticker_items, m=pa_market_display, t=ticker, cur=currency,
                    ):
                        sections = []
                        for _, data in items:
                            if "error" in data:
                                sections.append(
                                    f"Timeframe: {data['timeframe']}\nERROR: {data['error']}"
                                )
                            else:
                                sections.append(build_price_action_ai_prompt(
                                    data["symbol"], data["timeframe"], m, data["analysis"], cur,
                                ))
                        return combine_timeframe_sections(
                            "MULTI-TIMEFRAME PRICE ACTION SCAN", t, sections, market=m,
                        )

                    render_mtf_ai_view_report(
                        "pa", ticker, _build_pa_mtf, MTF_AI_SYSTEM,
                        provider, model, api_key, len(ticker_items),
                    )

                if len(ticker_items) > 1:
                    render_run_summary(summarize_mtf_aggregate(ticker_summaries, ticker, "Price Action"))

                for key, data in ticker_items:
                    tf = data.get("timeframe", "?")
                    summary = next((s for s in ticker_summaries if s.get("timeframe") == tf), None)
                    extra = ""
                    if "error" not in data:
                        a = data.get("analysis") or {}
                        extra = f"{a.get('overall_bias', '—')} · {currency}{a.get('current_price', 0):,.2f}"
                    with st.expander(
                        tf_section_label(tf, summary, extra=extra),
                        expanded=(len(ticker_items) == 1),
                    ):
                        _display_pa_result_block(
                            key, data, is_crypto, pa_market_display,
                            provider, model, api_key, nested=True,
                        )

    if all_results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("price_action")

    # ── Disclaimer ──
    st.markdown("---")
    st.caption(
        "⚠️ **Disclaimer**: This is a technical analysis tool for educational purposes. "
        "Elliott Wave analysis is probabilistic, not definitive. Past performance does not guarantee "
        "future results. Always use proper risk management."
    )
