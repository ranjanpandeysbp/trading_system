import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, timedelta, datetime
from groq import Groq
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
    market_currency,
)
from backtesting.data_fetcher import get_historical_data
from app.market_pulse.price_action import _render_pa_ai_report, _safe_pa_key
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
from app.market_pulse.price_extremes import render_price_extremes_for_ticker
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import (
    render_run_summary,
    summarize_error,
    summarize_mtf_aggregate,
    summarize_top_bottom,
)
from app.market_pulse.ta_screener_ui import (
    render_ta_screener_options,
    render_ta_screener_results,
    render_strategy_mtf_panel,
    should_show_ticker_in_screener,
)
from app.market_pulse.top_bottom_forecast import (
    build_tb_forecast_ai_prompt,
    compute_top_bottom_forecast,
    merge_ai_forecast,
    refine_forecast_with_ai,
    render_tb_forecast_panel,
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


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLESTICK PATTERN DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_candlestick_patterns(df):
    """Detect single and multi-candle patterns. Returns a list of dicts with index, name, type (bullish/bearish)."""
    patterns = []
    o, h, l, c = df['open'].values, df['high'].values, df['low'].values, df['close'].values
    n = len(df)
    idx = df.index

    for i in range(2, n):
        body = abs(c[i] - o[i])
        upper_wick = h[i] - max(c[i], o[i])
        lower_wick = min(c[i], o[i]) - l[i]
        full_range = h[i] - l[i]
        if full_range == 0:
            continue

        body_ratio = body / full_range
        prev_body = abs(c[i-1] - o[i-1])

        # Hammer (bullish reversal at bottom)
        if lower_wick > body * 2 and upper_wick < body * 0.5 and body_ratio < 0.35:
            patterns.append({"idx": i, "date": idx[i], "name": "Hammer", "type": "bullish", "price": l[i]})

        # Inverted Hammer (bullish reversal at bottom)
        if upper_wick > body * 2 and lower_wick < body * 0.5 and body_ratio < 0.35:
            patterns.append({"idx": i, "date": idx[i], "name": "Inverted Hammer", "type": "bullish", "price": h[i]})

        # Shooting Star (bearish reversal at top)
        if upper_wick > body * 2 and lower_wick < body * 0.5 and body_ratio < 0.35 and c[i] < o[i]:
            # Override inverted hammer if bearish context
            if len(patterns) > 0 and patterns[-1]["idx"] == i:
                patterns[-1] = {"idx": i, "date": idx[i], "name": "Shooting Star", "type": "bearish", "price": h[i]}
            else:
                patterns.append({"idx": i, "date": idx[i], "name": "Shooting Star", "type": "bearish", "price": h[i]})

        # Bullish Engulfing
        if i >= 1 and c[i-1] < o[i-1] and c[i] > o[i]:
            if o[i] <= c[i-1] and c[i] >= o[i-1] and body > prev_body:
                patterns.append({"idx": i, "date": idx[i], "name": "Bullish Engulfing", "type": "bullish", "price": c[i]})

        # Bearish Engulfing
        if i >= 1 and c[i-1] > o[i-1] and c[i] < o[i]:
            if o[i] >= c[i-1] and c[i] <= o[i-1] and body > prev_body:
                patterns.append({"idx": i, "date": idx[i], "name": "Bearish Engulfing", "type": "bearish", "price": c[i]})

        # Doji
        if body_ratio < 0.05 and full_range > 0:
            patterns.append({"idx": i, "date": idx[i], "name": "Doji", "type": "neutral", "price": c[i]})

    return patterns


def detect_chart_patterns(df):
    """Detect higher-level chart patterns: Double Top (M), Double Bottom (W), Head & Shoulders, Cup & Handle, Flags."""
    patterns = []
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    n = len(df)
    idx = df.index

    if n < 30:
        return patterns

    # Use a rolling window to find local peaks and troughs
    window = max(5, n // 20)
    peaks = []
    troughs = []
    for i in range(window, n - window):
        if h[i] == max(h[i-window:i+window+1]):
            peaks.append(i)
        if l[i] == min(l[i-window:i+window+1]):
            troughs.append(i)

    # Double Top (M pattern) - two peaks at similar levels with a trough between
    for j in range(len(peaks) - 1):
        p1, p2 = peaks[j], peaks[j+1]
        if p2 - p1 < window * 2:
            continue
        price_diff_pct = abs(h[p1] - h[p2]) / max(h[p1], h[p2]) * 100
        if price_diff_pct < 3.0:  # Within 3% of each other
            # Find trough between them
            mid_troughs = [t for t in troughs if p1 < t < p2]
            if mid_troughs:
                patterns.append({
                    "name": "Double Top (M)",
                    "type": "bearish",
                    "points": [
                        {"date": idx[p1], "price": h[p1]},
                        {"date": idx[mid_troughs[0]], "price": l[mid_troughs[0]]},
                        {"date": idx[p2], "price": h[p2]}
                    ]
                })

    # Double Bottom (W pattern) - two troughs at similar levels with a peak between
    for j in range(len(troughs) - 1):
        t1, t2 = troughs[j], troughs[j+1]
        if t2 - t1 < window * 2:
            continue
        price_diff_pct = abs(l[t1] - l[t2]) / max(l[t1], l[t2]) * 100
        if price_diff_pct < 3.0:
            mid_peaks = [p for p in peaks if t1 < p < t2]
            if mid_peaks:
                patterns.append({
                    "name": "Double Bottom (W)",
                    "type": "bullish",
                    "points": [
                        {"date": idx[t1], "price": l[t1]},
                        {"date": idx[mid_peaks[0]], "price": h[mid_peaks[0]]},
                        {"date": idx[t2], "price": l[t2]}
                    ]
                })

    # Head & Shoulders - three peaks where middle is highest
    for j in range(len(peaks) - 2):
        p1, p2, p3 = peaks[j], peaks[j+1], peaks[j+2]
        if h[p2] > h[p1] and h[p2] > h[p3]:
            shoulder_diff = abs(h[p1] - h[p3]) / max(h[p1], h[p3]) * 100
            head_above = (h[p2] - max(h[p1], h[p3])) / max(h[p1], h[p3]) * 100
            if shoulder_diff < 5.0 and head_above > 2.0:
                patterns.append({
                    "name": "Head & Shoulders",
                    "type": "bearish",
                    "points": [
                        {"date": idx[p1], "price": h[p1]},
                        {"date": idx[p2], "price": h[p2]},
                        {"date": idx[p3], "price": h[p3]}
                    ]
                })

    # Inverse Head & Shoulders
    for j in range(len(troughs) - 2):
        t1, t2, t3 = troughs[j], troughs[j+1], troughs[j+2]
        if l[t2] < l[t1] and l[t2] < l[t3]:
            shoulder_diff = abs(l[t1] - l[t3]) / max(l[t1], l[t3]) * 100
            head_below = (min(l[t1], l[t3]) - l[t2]) / min(l[t1], l[t3]) * 100
            if shoulder_diff < 5.0 and head_below > 2.0:
                patterns.append({
                    "name": "Inv Head & Shoulders",
                    "type": "bullish",
                    "points": [
                        {"date": idx[t1], "price": l[t1]},
                        {"date": idx[t2], "price": l[t2]},
                        {"date": idx[t3], "price": l[t3]}
                    ]
                })

    # Cup & Handle - U-shape trough followed by a small pullback
    if len(troughs) >= 1 and len(peaks) >= 2:
        for j in range(len(troughs)):
            t = troughs[j]
            # Find peaks before and after the trough
            left_peaks = [p for p in peaks if p < t and t - p > window]
            right_peaks = [p for p in peaks if p > t and p - t > window]
            if left_peaks and right_peaks:
                lp = left_peaks[-1]
                rp = right_peaks[0]
                rim_diff = abs(h[lp] - h[rp]) / max(h[lp], h[rp]) * 100
                depth = (max(h[lp], h[rp]) - l[t]) / max(h[lp], h[rp]) * 100
                if rim_diff < 5.0 and depth > 10.0:
                    patterns.append({
                        "name": "Cup & Handle",
                        "type": "bullish",
                        "points": [
                            {"date": idx[lp], "price": h[lp]},
                            {"date": idx[t], "price": l[t]},
                            {"date": idx[rp], "price": h[rp]}
                        ]
                    })
                    break  # Only report one

    # Flag pattern - strong move followed by consolidation channel
    if n > 40:
        # Check last 40 candles for a flag
        recent = c[-40:]
        # Strong impulse in first 10 candles
        impulse = recent[10] - recent[0]
        impulse_pct = abs(impulse) / recent[0] * 100 if recent[0] > 0 else 0
        # Consolidation in last 20 candles (low range)
        consol_range = max(recent[-20:]) - min(recent[-20:])
        consol_pct = consol_range / recent[-20] * 100 if recent[-20] > 0 else 0
        if impulse_pct > 5.0 and consol_pct < impulse_pct * 0.5:
            flag_type = "bullish" if impulse > 0 else "bearish"
            patterns.append({
                "name": f"{'Bull' if flag_type == 'bullish' else 'Bear'} Flag",
                "type": flag_type,
                "points": [
                    {"date": idx[-40], "price": c[-40]},
                    {"date": idx[-30], "price": c[-30]},
                    {"date": idx[-1], "price": c[-1]}
                ]
            })

    return patterns


def compute_support_resistance(df, num_levels=3):
    """Compute support and resistance levels using price clustering."""
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    
    # Combine key prices
    all_prices = np.concatenate([h, l, c])
    
    # Use histogram-based clustering
    price_range = all_prices.max() - all_prices.min()
    if price_range == 0:
        return [], []
    
    n_bins = max(20, len(df) // 5)
    counts, bin_edges = np.histogram(all_prices, bins=n_bins)
    
    # Find peaks in the histogram (price levels where price congregated)
    peak_indices = []
    for i in range(1, len(counts) - 1):
        if counts[i] > counts[i-1] and counts[i] > counts[i+1] and counts[i] > np.mean(counts):
            peak_indices.append(i)
    
    levels = [(bin_edges[i] + bin_edges[i+1]) / 2 for i in peak_indices]
    levels.sort()
    
    curr = c[-1]
    supports = sorted([lv for lv in levels if lv < curr], reverse=True)[:num_levels]
    resistances = sorted([lv for lv in levels if lv > curr])[:num_levels]
    
    return supports, resistances


def build_analysis_chart(df, metrics, ticker, tf, candle_patterns, chart_patterns, supports, resistances):
    """Build a comprehensive Plotly candlestick chart with all annotations."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.75, 0.25])

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name="Price", increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ), row=1, col=1)

    # Volume
    colors = ['#26a69a' if c >= o else '#ef5350' for c, o in zip(df['close'], df['open'])]
    fig.add_trace(go.Bar(
        x=df.index, y=df['volume'], name="Volume", marker_color=colors, opacity=0.4
    ), row=2, col=1)

    # Top / Bottom horizontal lines
    fig.add_hline(y=metrics['top'], line_dash="dash", line_color="red", line_width=1,
                  annotation_text=f"Peak: {metrics['top']:.2f}", row=1, col=1)
    fig.add_hline(y=metrics['bottom'], line_dash="dash", line_color="green", line_width=1,
                  annotation_text=f"Trough: {metrics['bottom']:.2f}", row=1, col=1)

    # Fibonacci levels
    for fib_name, fib_val in metrics['fibs'].items():
        fig.add_hline(y=fib_val, line_dash="dot", line_color="rgba(255,193,7,0.5)", line_width=1,
                      annotation_text=f"Fib {fib_name}: {fib_val:.2f}", row=1, col=1)

    # Support levels
    for s in supports:
        fig.add_hline(y=s, line_dash="dot", line_color="rgba(76,175,80,0.6)", line_width=1,
                      annotation_text=f"S: {s:.2f}", annotation_position="bottom left", row=1, col=1)

    # Resistance levels
    for r in resistances:
        fig.add_hline(y=r, line_dash="dot", line_color="rgba(244,67,54,0.6)", line_width=1,
                      annotation_text=f"R: {r:.2f}", annotation_position="top left", row=1, col=1)

    # SL / TP lines
    fig.add_hline(y=metrics['sl_price'], line_dash="dashdot", line_color="orangered", line_width=1.5,
                  annotation_text=f"SL: {metrics['sl_price']:.2f}", row=1, col=1)
    fig.add_hline(y=metrics['tp_price'], line_dash="dashdot", line_color="dodgerblue", line_width=1.5,
                  annotation_text=f"TP: {metrics['tp_price']:.2f}", row=1, col=1)

    # Candlestick pattern markers
    for p in candle_patterns:
        marker_color = "lime" if p["type"] == "bullish" else "red" if p["type"] == "bearish" else "yellow"
        symbol = "triangle-up" if p["type"] == "bullish" else "triangle-down" if p["type"] == "bearish" else "diamond"
        fig.add_trace(go.Scatter(
            x=[p["date"]], y=[p["price"]],
            mode="markers+text",
            marker=dict(color=marker_color, size=10, symbol=symbol, line=dict(width=1, color="white")),
            text=[p["name"]], textposition="top center" if p["type"] == "bullish" else "bottom center",
            textfont=dict(size=8, color=marker_color),
            showlegend=False, hovertext=p["name"]
        ), row=1, col=1)

    # Chart pattern annotations (lines connecting pattern points)
    pattern_colors = {"bullish": "lime", "bearish": "red", "neutral": "yellow"}
    for cp in chart_patterns:
        pts = cp.get("points", [])
        if len(pts) >= 2:
            clr = pattern_colors.get(cp["type"], "yellow")
            fig.add_trace(go.Scatter(
                x=[p["date"] for p in pts],
                y=[p["price"] for p in pts],
                mode="lines+markers+text",
                line=dict(color=clr, width=2, dash="dot"),
                marker=dict(size=8, color=clr),
                text=[cp["name"]] + [""] * (len(pts) - 1),
                textposition="top center",
                textfont=dict(size=9, color=clr),
                showlegend=False,
                hovertext=cp["name"]
            ), row=1, col=1)

    fig.update_layout(
        title=f"{ticker} — {tf}",
        template="plotly_dark",
        height=500,
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=50, r=20, t=40, b=20),
        font=dict(size=10)
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")

    return fig

def calculate_top_bottom_metrics(df, window=100):
    """
    Advanced Institutional Top/Bottom Analysis.
    Detects if a ticker is currently at a cycle peak, trough, or in transition.
    """
    if df.empty or len(df) < 20:
        return None

    # Use available data up to the requested window
    actual_window = min(window, len(df))
    recent_df = df.tail(actual_window)
    h = recent_df['high']
    l = recent_df['low']
    c = recent_df['close']

    curr_price = c.iloc[-1]
    highest_high = h.max()
    lowest_low = l.min()

    # How many candles ago was the top/bottom made
    top_candle_idx = h.values.argmax()
    bottom_candle_idx = l.values.argmin()
    candles_since_top = len(h) - 1 - top_candle_idx
    candles_since_bottom = len(l) - 1 - bottom_candle_idx

    # distance from top/bottom in %
    dist_from_top = ((highest_high - curr_price) / highest_high) * 100
    dist_from_bottom = ((curr_price - lowest_low) / lowest_low) * 100

    # Probabilistic Scoring for New Top/Bottom
    # RSI for momentum exhaustion
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs.iloc[-1]))

    # Fibonacci Retracement Levels
    range_val = highest_high - lowest_low
    fib_382 = highest_high - (0.382 * range_val)
    fib_500 = highest_high - (0.500 * range_val)
    fib_618 = highest_high - (0.618 * range_val)

    # Scoring logic: 
    # Top Status: If price is within 1% of highest high AND RSI > 70 => "EXHAUSTED TOP"
    # Bottom Status: If price is within 1% of lowest low AND RSI < 30 => "EXHAUSTED BOTTOM"
    
    top_status = "STILL ROOM"
    if dist_from_top < 1.0:
        top_status = "AT TOP"
        if rsi > 70: top_status = "PEAK (REVERSAL LIKELY)"
    elif dist_from_top < 5.0:
        top_status = "NEAR TOP"

    bottom_status = "STILL ROOM"
    if dist_from_bottom < 1.0:
        bottom_status = "AT BOTTOM"
        if rsi < 30: bottom_status = "TROUGH (ACCUMULATION)"
    elif dist_from_bottom < 5.0:
        bottom_status = "NEAR BOTTOM"

    # ATR Calculation
    try:
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        if pd.isna(atr): atr = (highest_high - lowest_low) * 0.05
    except:
        atr = (highest_high - lowest_low) * 0.05

    # Suggested Trade Setup
    trade_bias = "NEUTRAL"
    sl_price = 0.0
    tp_price = 0.0
    
    if "BOTTOM" in bottom_status or "TROUGH" in bottom_status:
        trade_bias = "LONG"
        sl_price = lowest_low - (atr * 1.5)
        tp_price = fib_500
    elif "TOP" in top_status or "PEAK" in top_status:
        trade_bias = "SHORT"
        sl_price = highest_high + (atr * 1.5)
        tp_price = fib_500
    else:
        if dist_from_bottom < dist_from_top:
            trade_bias = "LONG (Range)"
            sl_price = lowest_low - atr
            tp_price = highest_high
        else:
            trade_bias = "SHORT (Range)"
            sl_price = highest_high + atr
            tp_price = lowest_low

    sl_pct = abs(curr_price - sl_price) / curr_price * 100 if curr_price > 0 else 0
    tp_pct = abs(curr_price - tp_price) / curr_price * 100 if curr_price > 0 else 0

    return {
        "current": curr_price,
        "top": highest_high,
        "bottom": lowest_low,
        "dist_top": dist_from_top,
        "dist_bottom": dist_from_bottom,
        "rsi": rsi,
        "top_status": top_status,
        "bottom_status": bottom_status,
        "fibs": {"38.2%": fib_382, "50.0%": fib_500, "61.8%": fib_618},
        "bias": trade_bias,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "candles_since_top": candles_since_top,
        "candles_since_bottom": candles_since_bottom
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AI VIEW HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _render_tb_ai_config():
    """AI provider configuration (mirrors News Scanner / Price Action settings)."""
    return render_ai_config("tb", caption="AI View uses these settings for per-ticker top/bottom reports.")


def build_top_bottom_ai_prompt(symbol, timeframe, market, metrics, candle_patterns, chart_patterns,
                             supports, resistances, lookback, currency):
    """Serialize top/bottom analysis into an AI prompt."""
    lines = [
        "=== TOP / BOTTOM REVERSAL ANALYSIS ===",
        f"Symbol: {symbol}",
        f"Timeframe: {timeframe}",
        f"Market: {market}",
        f"Lookback Candles: {lookback}",
        f"Current Price: {currency}{metrics['current']:.4f}",
        "",
        "=== EXTREMES & STATUS ===",
        f"Peak (Top): {currency}{metrics['top']:.4f} — {metrics['candles_since_top']} candles ago",
        f"Trough (Bottom): {currency}{metrics['bottom']:.4f} — {metrics['candles_since_bottom']} candles ago",
        f"Distance from Top: {metrics['dist_top']:.2f}%",
        f"Distance from Bottom: {metrics['dist_bottom']:.2f}%",
        f"Top Status: {metrics['top_status']}",
        f"Bottom Status: {metrics['bottom_status']}",
        f"RSI: {metrics['rsi']:.1f}",
        "",
        "=== FIBONACCI RETRACEMENT LEVELS ===",
    ]
    for name, price in metrics["fibs"].items():
        lines.append(f"  {name}: {currency}{price:.4f}")

    lines.extend([
        "",
        "=== ENGINE TRADE SETUP ===",
        f"Bias: {metrics['bias']}",
        f"Suggested Stop Loss: {currency}{metrics['sl_price']:.4f} ({metrics['sl_pct']:.2f}% from entry)",
        f"Suggested Take Profit: {currency}{metrics['tp_price']:.4f} ({metrics['tp_pct']:.2f}% from entry)",
    ])

    if supports:
        lines.append("\n=== SUPPORT LEVELS ===")
        for i, s in enumerate(supports, 1):
            lines.append(f"  Support {i}: {currency}{s:.4f}")

    if resistances:
        lines.append("\n=== RESISTANCE LEVELS ===")
        for i, r in enumerate(resistances, 1):
            lines.append(f"  Resistance {i}: {currency}{r:.4f}")

    if chart_patterns:
        lines.append("\n=== CHART PATTERNS ===")
        for p in chart_patterns:
            lines.append(f"  - {p['name']} ({p['type']})")

    if candle_patterns:
        lines.append("\n=== RECENT CANDLESTICK PATTERNS ===")
        for p in candle_patterns[-8:]:
            dt = p["date"].strftime("%Y-%m-%d %H:%M") if hasattr(p["date"], "strftime") else str(p["date"])
            lines.append(f"  - {p['name']} ({p['type']}) at {dt}")

    forecast = metrics.get("forecast") if isinstance(metrics.get("forecast"), dict) else None
    if forecast:
        lines.extend([
            "",
            "=== BREAKOUT / BREAKDOWN FORECAST (next 1-5 candles) ===",
            f"Composite confidence: {forecast.get('composite_confidence')}%",
            f"P(cross ATH): {forecast.get('ath_cross_prob')}% | P(cross ATL): {forecast.get('atl_cross_prob')}%",
            f"P(break swing high): {forecast.get('swing_high_break_prob')}% | "
            f"P(break swing low): {forecast.get('swing_low_break_prob')}%",
            f"P(break window high): {forecast.get('window_high_break_prob')}% | "
            f"P(break window low): {forecast.get('window_low_break_prob')}%",
            f"Summary: {forecast.get('next_candles_summary', '')}",
        ])

    return "\n".join(lines)


def get_top_bottom_ai_report(prompt_data, provider, model, api_key):
    """Call AI provider for a top/bottom reversal trade report."""
    system = """You are an expert top/bottom reversal analyst for Indian equities (NSE/BSE)
and cryptocurrency futures. You specialize in identifying cycle peaks, troughs, RSI exhaustion,
Fibonacci retracements, and reversal pattern confluence.

Analyze the provided top/bottom scanner output. Be data-driven. If the asset is mid-range
with no clear extreme or conflicting signals, verdict must be AVOID.
Reversal trades need clear holding time and reversal-specific green/red flags (RSI, structure, volume).
""" + STANDARD_REPORT_FORMAT

    user_msg = f"Analyze this top/bottom scanner output and give a trade verdict with setup:\n\n{prompt_data}"

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


def _fetch_tb_data(ticker, tf, tb_market, tb_candles, groww_token):
    """Load OHLCV data for a single ticker/timeframe."""
    tf_to_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
    candle_minutes = tf_to_minutes.get(tf, 1440)
    days_needed = max(7, int((tb_candles * candle_minutes / 1440) * 2.5) + 1)
    yf_max = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 729, "4h": 729, "1d": 3650}
    days_needed = min(days_needed, yf_max.get(tf, 3650))
    return get_historical_data(
        ticker,
        str(date.today() - timedelta(days=days_needed)),
        str(date.today()),
        tb_market, tf,
        groww_token=groww_token,
    )


def _display_tb_tf_block(key, data, tb_market, tb_candles, provider, model, api_key, *, nested: bool = False):
    """Render one ticker/timeframe top-bottom result with optional AI View."""
    ticker = data["symbol"]
    tf = data["timeframe"]
    safe_key = _safe_pa_key(key)
    currency = market_currency(tb_market)

    if "error" in data:
        render_run_summary(summarize_error(ticker, tf, data["error"], tab="Top/Bottom"), compact=True)
        if not nested:
            st.markdown(f"**{tf} Interval**")
        st.warning(data["error"])
        return

    metrics = data["metrics"]
    forecast = data.get("forecast")
    if forecast:
        metrics = {**metrics, "forecast": forecast}
    render_run_summary(summarize_top_bottom(metrics, ticker, tf), compact=True)
    render_strategy_mtf_panel(
        symbol=ticker,
        market=tb_market,
        groww_token=get_active_groww_token(),
        exchange=st.session_state.get("tb_groww_ex", "NSE"),
        primary_tf=tf,
        strategy_direction=metrics.get("signal"),
    )
    df = data["df"]
    candle_patterns = data["candle_patterns"]
    chart_patterns = data["chart_patterns"]
    supports = data["supports"]
    resistances = data["resistances"]

    if not nested:
        st.markdown(f"**{tf} Interval**")
    ai_clicked = st.button("🤖 AI View", key=f"tb_ai_btn_{safe_key}", width='stretch')
    if ai_clicked:
        st.session_state[f"tb_ai_show_{safe_key}"] = True
        st.session_state[f"tb_ai_refresh_{safe_key}"] = True

    groww_token = get_active_groww_token()
    tb_exchange = st.session_state.get("tb_groww_ex", "NSE")
    render_price_extremes_for_ticker(
        ticker, df, tf, tb_market, exchange=tb_exchange,
        groww_token=groww_token, currency=currency, compact=True,
    )

    st.metric("Current Price", f"{metrics['current']:.2f}")

    dist_top_val = metrics["dist_top"] if not (pd.isna(metrics["dist_top"]) or np.isinf(metrics["dist_top"])) else 100.0
    dist_bottom_val = metrics["dist_bottom"] if not (pd.isna(metrics["dist_bottom"]) or np.isinf(metrics["dist_bottom"])) else 100.0

    t_color = "red" if "TOP" in metrics["top_status"] else "gray"
    st.markdown(f"**Top Status:** <span style='color:{t_color}'>{metrics['top_status']}</span>", unsafe_allow_html=True)
    st.caption(f"Dist: {dist_top_val:.2f}% | Peak: {metrics['top']:.2f} | 🕐 {metrics['candles_since_top']} candles ago")

    b_color = "green" if "BOTTOM" in metrics["bottom_status"] else "gray"
    st.markdown(f"**Bottom Status:** <span style='color:{b_color}'>{metrics['bottom_status']}</span>", unsafe_allow_html=True)
    st.caption(f"Dist: {dist_bottom_val:.2f}% | Trough: {metrics['bottom']:.2f} | 🕐 {metrics['candles_since_bottom']} candles ago")

    st.progress(max(0, min(100, int(100 - dist_top_val))), text="Proximity to Top")

    if forecast:
        with st.expander(f"🎯 Breakout Confidence & Next 1–5 Candle Forecast ({tf})", expanded=True):
            render_tb_forecast_panel(forecast, currency, tf)
            ai_fc_key = f"tb_fc_ai_{safe_key}"
            if st.button("🤖 Refine forecast with AI", key=f"tb_fc_ai_btn_{safe_key}", width='stretch'):
                st.session_state[ai_fc_key] = True
            if st.session_state.get(ai_fc_key) and api_key:
                cache_fc = f"tb_fc_merged_{safe_key}"
                if cache_fc not in st.session_state:
                    with st.spinner("AI refining probabilities..."):
                        prompt = build_tb_forecast_ai_prompt(
                            forecast, metrics, ticker, tf, tb_market, tb_candles, currency,
                        )
                        parsed, raw = refine_forecast_with_ai(prompt, provider, model, api_key)
                        if parsed:
                            st.session_state[cache_fc] = merge_ai_forecast(forecast, parsed)
                        else:
                            st.warning(raw or "AI refinement failed — showing quant model only.")
                if cache_fc in st.session_state:
                    st.markdown("**Blended quant + AI forecast**")
                    render_tb_forecast_panel(st.session_state[cache_fc], currency, tf, show_reasons=False)
            elif st.session_state.get(ai_fc_key) and not api_key:
                st.caption(f"💡 {api_key_env_hint(provider)} to enable AI forecast refinement.")

    with st.expander(f"What this {tf} analysis means"):
        st.write(f"In the last **{tb_candles} candles** on the **{tf}** timeframe, the highest price was **{metrics['top']:.2f}** and the lowest was **{metrics['bottom']:.2f}**.")
        st.write(f"The current price is **{dist_top_val:.2f}%** away from the top and **{dist_bottom_val:.2f}%** away from the bottom.")
        if "PEAK" in metrics["top_status"]:
            st.error(f"**Top Status: {metrics['top_status']}** - The price is at its peak and momentum (RSI) is heavily overbought. Reversal is highly likely.")
        elif "AT TOP" in metrics["top_status"]:
            st.warning(f"**Top Status: {metrics['top_status']}** - The price is within 1% of its peak.")
        elif "NEAR TOP" in metrics["top_status"]:
            st.info(f"**Top Status: {metrics['top_status']}** - The price is within 5% of its peak.")
        else:
            st.success(f"**Top Status: {metrics['top_status']}** - There is plenty of upward room before hitting the previous top.")

        if "TROUGH" in metrics["bottom_status"]:
            st.success(f"**Bottom Status: {metrics['bottom_status']}** - The price is at its bottom and momentum (RSI) is heavily oversold. This is a strong accumulation zone.")
        elif "AT BOTTOM" in metrics["bottom_status"]:
            st.warning(f"**Bottom Status: {metrics['bottom_status']}** - The price is within 1% of its lowest low.")
        elif "NEAR BOTTOM" in metrics["bottom_status"]:
            st.info(f"**Bottom Status: {metrics['bottom_status']}** - The price is within 5% of its lowest low.")
        else:
            st.error(f"**Bottom Status: {metrics['bottom_status']}** - There is plenty of downward room before hitting the previous bottom.")

    with st.expander(f"🛡️ Trade Setup & Margin Safety ({tf})"):
        bias_color = "green" if "LONG" in metrics["bias"] else "red" if "SHORT" in metrics["bias"] else "orange"
        st.markdown(f"**Bias:** <span style='color:{bias_color}'>{metrics['bias']}</span>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Suggested Stop Loss", f"{metrics['sl_price']:.2f}", f"-{metrics['sl_pct']:.2f}%", delta_color="inverse")
        with c2:
            st.metric("Suggested Take Profit", f"{metrics['tp_price']:.2f}", f"+{metrics['tp_pct']:.2f}%", delta_color="normal")

        st.caption("SL is calculated dynamically using ATR volatility buffers below/above the local extremes. TP targets key Fibonacci levels.")

        if is_crypto_market(tb_market):
            st.markdown("---")
            st.markdown("**⚠️ Margin Liquidation Safety (Crypto):**")
            if metrics["sl_pct"] > 0:
                max_lev = max(1, int(90 / metrics["sl_pct"]))
                st.write(f"- To avoid forced liquidation if your Stop Loss is hit, your **maximum safe leverage is {max_lev}x**.")
                st.write("- **Why?** Crypto exchanges liquidate you *before* your margin hits zero. If you use higher leverage, a volatile wick will liquidate your entire position before your SL is triggered.")
            st.write("- Place limit orders scaling out at 38.2% and 50% Fibonacci levels instead of a single Take Profit.")

    with st.expander(f"📈 View Advanced Chart & Patterns ({tf})", expanded=False):
        if chart_patterns:
            st.markdown("**Detected Chart Patterns:**")
            for p in chart_patterns:
                st.write(f"- {p['name']} ({p['type'].capitalize()})")
        if candle_patterns:
            recent_candles = candle_patterns[-5:]
            if recent_candles:
                st.markdown("**Recent Candlestick Patterns:**")
                for p in recent_candles:
                    if hasattr(p["date"], "strftime"):
                        dt_str = p["date"].strftime("%Y-%m-%d %H:%M")
                    else:
                        dt_str = str(p["date"])
                    st.write(f"- {p['name']} ({p['type'].capitalize()}) on {dt_str}")

        fig = build_analysis_chart(df, metrics, ticker, tf, candle_patterns, chart_patterns, supports, resistances)
        st.plotly_chart(fig, width='stretch')

    if st.session_state.get(f"tb_ai_show_{safe_key}", False):
        cache_key = f"tb_ai_report_{safe_key}"
        provider, model, api_key = render_block_ai_settings("tb", safe_key)
        force = st.session_state.pop(f"tb_ai_refresh_{safe_key}", False)
        picker_sig = f"{provider}|{model}"
        sig_key = f"tb_ai_sig_{safe_key}"
        if force or cache_key not in st.session_state or st.session_state.get(sig_key) != picker_sig:
            with st.spinner(f"🤖 Generating AI report for {ticker} | {tf}..."):
                m_ai = dict(metrics)
                if forecast:
                    m_ai["forecast"] = forecast
                prompt = build_top_bottom_ai_prompt(
                    ticker, tf, tb_market, m_ai, candle_patterns, chart_patterns,
                    supports, resistances, tb_candles, currency,
                )
                report = get_top_bottom_ai_report(prompt, provider, model, api_key)
                st.session_state[cache_key] = report
                st.session_state[sig_key] = picker_sig
        _render_pa_ai_report(ticker, tf, st.session_state[cache_key], provider, model)

    render_demo_trade_panel(
        "tb",
        key,
        ticker,
        tf,
        tb_market,
        f"Top/Bottom · {metrics.get('bias', 'N/A')}",
        current_price=metrics.get("current"),
        source_tab="Top/Bottom Analyzer",
        groww_token=groww_token,
        exchange=tb_exchange,
    )


def render_top_bottom_tab():
    st.markdown("<h1>🔝 Trough & Peak (Top/Bottom) Analyzer</h1>", unsafe_allow_html=True)
    st.write("Determine if a ticker has reached its local maximum (Top) or minimum (Bottom) using institutional multi-candle analysis, Fibonacci zones, and RSI exhaustion.")

    provider, model, api_key = _render_tb_ai_config()

    st.markdown("---")

    # --- Market Selection ---
    tb_market = st.selectbox(
        "🌐 Top/Bottom Analysis Market",
        MARKET_OPTIONS,
        index=0,
        key="tb_market"
    )

    # --- Ticker Selection ---
    st.markdown("### 📈 Select Assets to Analyze")
    tb_tickers = []
    tb_groww_exchange = "NSE"

    if is_crypto_market(tb_market):
        tb_tickers = render_coindcx_ticker_selection("tb")
    else:
        if is_india_market(tb_market):
            tb_groww_exchange = st.selectbox("EXCHANGE", ["NSE", "BSE"], index=0, key="tb_groww_ex")
        tb_tickers = render_equity_index_ticker_selection(tb_market, "tb")

    # --- Duration & Detail selection ---
    st.markdown("### ⏱️ Time Durations & Data Detail")
    tb_c1, tb_c2 = st.columns(2)
    with tb_c1:
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        tb_timeframes = render_ta_multiselect_timeframes(
            "tb",
            ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            legacy_default=["15m", "1h", "1d"],
            label="Choose Timeframes to Scan",
            help_text="Determine bullish/bearish alignment across multiple candles intervals simultaneously.",
        )
    with tb_c2:
        tb_candles = st.slider(
            "Candlestick Back-History Lookback",
            min_value=50,
            max_value=1500,
            value=500,
            step=50,
            key="tb_lookback_slider",
            help="Number of historical candles loaded to compute technical stats & indicators."
        )

    # --- Data Source Detection ---
    groww_token = get_active_groww_token()
    if is_india_market(tb_market):
        if groww_token and groww_token.strip():
            st.success("🌐 **Data Source: Groww API** (Bearer token detected in sidebar)")
        else:
            st.info("ℹ️ **Data Source: Yahoo Finance** (No Groww Bearer token in sidebar — provide one for Groww direct feed)")
    elif is_crypto_market(tb_market):
        st.info("🌐 **Data Source: CoinDCX Futures API**")
    else:
        st.info("🌐 **Data Source: Yahoo Finance (US Stocks)**")

    st.markdown("---")
    tb_actionable_only = render_ta_screener_options("tb")
    run_tb = st.button("🔎 SCAN TOP/BOTTOM SETUPS", width='stretch')

    if run_tb:
        if not tb_tickers or not tb_timeframes:
            st.error("Please select at least one ticker and one timeframe.")
            return

        all_results = {}
        total = len(tb_tickers) * len(tb_timeframes)
        progress = st.progress(0, text="Initializing top/bottom scan...")
        scan_idx = 0

        for ticker in tb_tickers:
            for tf in tb_timeframes:
                scan_idx += 1
                progress.progress(scan_idx / total, text=f"Analyzing {ticker} | {tf} ({scan_idx}/{total})...")
                result_key = f"{ticker}|{tf}"
                try:
                    with st.spinner(f"Loading {ticker} {tf}..."):
                        df = _fetch_tb_data(ticker, tf, tb_market, tb_candles, groww_token)
                        metrics = calculate_top_bottom_metrics(df, tb_candles)
                        if not metrics:
                            all_results[result_key] = {
                                "symbol": ticker, "timeframe": tf,
                                "error": f"No data for {tf}",
                            }
                            continue
                        candle_patterns = detect_candlestick_patterns(df)
                        chart_patterns = detect_chart_patterns(df)
                        supports, resistances = compute_support_resistance(df)
                        tb_exchange = st.session_state.get("tb_groww_ex", "NSE")
                        forecast = compute_top_bottom_forecast(
                            df, metrics, ticker, tb_market,
                            exchange=tb_exchange,
                            groww_token=groww_token,
                            candle_patterns=candle_patterns,
                            chart_patterns=chart_patterns,
                            supports=supports,
                            resistances=resistances,
                            lookback=tb_candles,
                            timeframe=tf,
                        )
                        all_results[result_key] = {
                            "symbol": ticker,
                            "timeframe": tf,
                            "df": df,
                            "metrics": metrics,
                            "forecast": forecast,
                            "candle_patterns": candle_patterns,
                            "chart_patterns": chart_patterns,
                            "supports": supports,
                            "resistances": resistances,
                        }
                except Exception as e:
                    all_results[result_key] = {
                        "symbol": ticker, "timeframe": tf,
                        "error": str(e)[:200],
                    }

        progress.empty()
        st.session_state.tb_all_results = all_results
        st.session_state.tb_analysis_market = tb_market
        st.session_state.tb_lookback = tb_candles

    all_results = st.session_state.get("tb_all_results", {})
    tb_market_display = st.session_state.get("tb_analysis_market", tb_market)
    tb_candles_display = st.session_state.get("tb_lookback", tb_candles)

    if all_results:
        if not api_key:
            st.info("💡 Set `GROQ_API_KEY` or `GEMINI_API_KEY` in your `.env` file to use **AI View** on each result.")

        tb_digest = []
        for k, d in all_results.items():
            if "error" in d:
                tb_digest.append(summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Top/Bottom"))
            else:
                m = dict(d["metrics"])
                if d.get("forecast"):
                    m["forecast"] = d["forecast"]
                tb_digest.append(summarize_top_bottom(m, d["symbol"], d["timeframe"]))
        tb_digest = render_ta_screener_results(
            tb_digest,
            title="🧭 Top/Bottom Screener",
            strategy_label="reversal",
            actionable_only=tb_actionable_only,
        )

        tickers_seen = []
        for data in all_results.values():
            if data["symbol"] not in tickers_seen:
                tickers_seen.append(data["symbol"])

        for ti, ticker in enumerate(tickers_seen):
            if not should_show_ticker_in_screener(ticker, tb_digest, actionable_only=tb_actionable_only):
                continue
            ticker_items = [(k, v) for k, v in all_results.items() if v["symbol"] == ticker]
            ticker_summaries = [
                summarize_error(d["symbol"], d["timeframe"], d["error"], tab="Top/Bottom")
                if "error" in d
                else summarize_top_bottom(
                    {**d["metrics"], **({"forecast": d["forecast"]} if d.get("forecast") else {})},
                    d["symbol"],
                    d["timeframe"],
                )
                for _, d in ticker_items
            ]

            with st.expander(
                ticker_section_label(ticker, ticker_summaries),
                expanded=should_expand_ticker(ti),
            ):
                if api_key and ticker_items:
                    _, mtf_btn = st.columns([4, 1])
                    with mtf_btn:
                        mtf_ticker_button("tb", ticker)

                    def _build_tb_mtf(items=ticker_items, m=tb_market_display, t=ticker, candles=tb_candles_display):
                        currency = market_currency(m)
                        sections = []
                        for _, data in items:
                            if "error" in data:
                                sections.append(
                                    f"Timeframe: {data['timeframe']}\nERROR: {data['error']}"
                                )
                            else:
                                sections.append(build_top_bottom_ai_prompt(
                                    data["symbol"], data["timeframe"], m,
                                    data["metrics"], data["candle_patterns"], data["chart_patterns"],
                                    data["supports"], data["resistances"], candles, currency,
                                ))
                        return combine_timeframe_sections(
                            "MULTI-TIMEFRAME TOP/BOTTOM SCAN", t, sections, market=m,
                        )

                    render_mtf_ai_view_report(
                        "tb", ticker, _build_tb_mtf, MTF_AI_SYSTEM,
                        provider, model, api_key, len(ticker_items),
                    )

                if len(ticker_items) > 1:
                    render_run_summary(summarize_mtf_aggregate(ticker_summaries, ticker, "Top/Bottom"))

                for key, data in ticker_items:
                    tf = data.get("timeframe", "?")
                    summary = next(
                        (s for s in ticker_summaries if s.get("timeframe") == tf),
                        None,
                    )
                    extra = ""
                    if "error" not in data:
                        m = data["metrics"]
                        extra = f"{m.get('top_status', '—')} / {m.get('bottom_status', '—')}"
                    with st.expander(
                        tf_section_label(tf, summary, extra=extra),
                        expanded=(len(ticker_items) == 1),
                    ):
                        _display_tb_tf_block(
                            key, data, tb_market_display, tb_candles_display,
                            provider, model, api_key, nested=True,
                        )

        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("top_bottom")
