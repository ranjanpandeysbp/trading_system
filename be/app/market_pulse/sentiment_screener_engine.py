"""Trend and Sentiment Screener — composite score (India)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.sr_breakout import (
    analyze_sr_breakout,
    apply_sr_breakout_scoring,
    compute_trade_confidence,
)
from app.market_pulse.ticker_utils import GROWW_MARKET, is_crypto_market, is_india_market

def analyze_ticker_sentiment(df: pd.DataFrame, market: str = GROWW_MARKET, timeframe: str = "1d") -> dict:
    """
    Institutional-grade multi-indicator sentiment scoring engine.
    Combines 25+ technical checks, 15+ candlestick patterns, Smart Money Concepts (Order Blocks,
    Fair Value Gaps, Liquidity Sweeps), ATR-based trade signals with dynamic SL/TP,
    VWAP crossover, Fibonacci Golden Zones, S/R reversals, Williams %R, CMF,
    ADX, Stochastic, Supertrend, OBV, Pivot Points, and momentum divergences
    into a weighted composite score (-100 to +100).
    
    Returns a dict with: score, rating, insights, trade_signal (BUY/SELL/WAIT),
    sl_pct, tp_pct, atr_pct, rsi, vol_ratio, macd_hist, adx, trend_str
    """
    if df.empty or len(df) < 50:
        return {"score": 0.0, "rating": "NEUTRAL (No Data)", "insights": ["Insufficient candle history for analysis."],
                "rsi": 0.0, "vol_ratio": 0.0, "macd_hist": 0.0, "adx": 0.0, "trend_str": "N/A",
                "trade_signal": "WAIT", "sl_pct": 0.0, "tp_pct": 0.0, "atr_pct": 0.0,
                "trade_confidence": 0, "sr_breakout": None}

    insights = []
    bull_pts = 0
    bear_pts = 0
    
    c = df['close']
    h = df['high']
    l = df['low']
    o = df['open']
    v = df['volume']
    
    curr_close  = c.values[-1]
    curr_high   = h.values[-1]
    curr_low    = l.values[-1]
    curr_open   = o.values[-1]
    curr_vol    = v.values[-1]
    prev_close  = c.values[-2]
    prev_open   = o.values[-2]
    prev_high   = h.values[-2]
    prev_low    = l.values[-2]

    # ══════════════════════════════════════════════════════════════════════
    # PRE-COMPUTE: True Range & ATR (used across multiple sections)
    # ══════════════════════════════════════════════════════════════════════
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_14 = tr.rolling(window=14).mean()
    atr_val = atr_14.values[-1] if not np.isnan(atr_14.values[-1]) else 0.0
    atr_pct = (atr_val / (curr_close + 1e-10)) * 100

    # ── 1. EMA / SMA Alignment (weight: 30) ──────────────────────────────
    ema_9   = c.ewm(span=9,   adjust=False).mean().values[-1]
    ema_21  = c.ewm(span=21,  adjust=False).mean().values[-1]
    ema_50  = c.ewm(span=50,  adjust=False).mean().values[-1]
    sma_200 = c.rolling(window=min(200, len(c))).mean().values[-1] if len(c) >= 100 else ema_50

    if curr_close > ema_9:
        bull_pts += 6; insights.append("🟢 Price > EMA(9) — Short-term bullish.")
    else:
        bear_pts += 6; insights.append("🔴 Price < EMA(9) — Short-term bearish.")

    if ema_9 > ema_21:
        bull_pts += 6; insights.append("🟢 EMA(9) > EMA(21) — Bullish crossover alignment.")
    else:
        bear_pts += 6; insights.append("🔴 EMA(9) < EMA(21) — Bearish death-cross alignment.")

    if curr_close > ema_50:
        bull_pts += 6; insights.append("🟢 Price > EMA(50) — Medium-term bullish bias.")
    else:
        bear_pts += 6; insights.append("🔴 Price < EMA(50) — Medium-term bearish bias.")

    if len(c) >= 100:
        if curr_close > sma_200:
            bull_pts += 6; insights.append("🟢 Price > SMA(200) — Long-term structural uptrend.")
        else:
            bear_pts += 6; insights.append("🔴 Price < SMA(200) — Long-term structural downtrend.")

    # Perfect stack: close > ema9 > ema21 > ema50
    if curr_close > ema_9 > ema_21 > ema_50:
        bull_pts += 6; insights.append("🏆 Perfect Bullish EMA stack: Price > 9 > 21 > 50.")
    elif curr_close < ema_9 < ema_21 < ema_50:
        bear_pts += 6; insights.append("💀 Perfect Bearish EMA stack: Price < 9 < 21 < 50.")

    # ── 2. RSI Momentum (weight: 15) ─────────────────────────────────────
    delta = c.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean().values[-1]
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean().values[-1]
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))

    if rsi > 70:
        bull_pts += 10; insights.append(f"🔥 RSI {rsi:.1f} — Overbought / Strong bullish momentum (caution for reversal).")
    elif rsi > 55:
        bull_pts += 8; insights.append(f"🟢 RSI {rsi:.1f} — Healthy bullish momentum.")
    elif rsi < 30:
        bear_pts += 10; insights.append(f"❄️ RSI {rsi:.1f} — Oversold / Extreme bearish (bounce possible).")
    elif rsi < 45:
        bear_pts += 8; insights.append(f"🔴 RSI {rsi:.1f} — Weakening bearish momentum.")
    else:
        insights.append(f"⚖️ RSI {rsi:.1f} — Neutral zone.")

    # RSI Divergence (simple: price higher high but RSI lower high → bearish div)
    if len(c) >= 20:
        rsi_series = 100 - (100 / (1 + delta.where(delta > 0, 0).rolling(14).mean() / ((-delta.where(delta < 0, 0)).rolling(14).mean() + 1e-10)))
        if not rsi_series.empty and len(rsi_series.dropna()) >= 10:
            price_last10_max = c.values[-10:].max()
            price_prev10_max = c.values[-20:-10].max()
            rsi_last10_max = rsi_series.values[-10:].max() if len(rsi_series) >= 10 else rsi
            rsi_prev10_max = rsi_series.values[-20:-10].max() if len(rsi_series) >= 20 else rsi
            
            if price_last10_max > price_prev10_max and rsi_last10_max < rsi_prev10_max:
                bear_pts += 8; insights.append("⚠️ Bearish RSI Divergence: Price making higher highs but RSI making lower highs.")
            elif price_last10_max < price_prev10_max and rsi_last10_max > rsi_prev10_max:
                bull_pts += 8; insights.append("✨ Bullish RSI Divergence: Price making lower lows but RSI making higher lows.")

    # ── 3. MACD Momentum (weight: 15) ────────────────────────────────────
    ema_12 = c.ewm(span=12, adjust=False).mean()
    ema_26 = c.ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    macd_h_val = macd_hist.values[-1]
    macd_h_prev = macd_hist.values[-2]
    macd_l_val = macd_line.values[-1]

    if macd_l_val > macd_signal.values[-1]:
        bull_pts += 8; insights.append(f"🟢 MACD Line above Signal Line — Bullish momentum.")
    else:
        bear_pts += 8; insights.append(f"🔴 MACD Line below Signal Line — Bearish momentum.")

    if macd_h_val > 0 and macd_h_val > macd_h_prev:
        bull_pts += 7; insights.append(f"📈 MACD Histogram expanding positive ({macd_h_val:.4f}) — Accelerating bullish momentum.")
    elif macd_h_val < 0 and macd_h_val < macd_h_prev:
        bear_pts += 7; insights.append(f"📉 MACD Histogram expanding negative ({macd_h_val:.4f}) — Accelerating bearish momentum.")

    # MACD zero-line crossover
    if macd_l_val > 0 and macd_line.values[-2] <= 0:
        bull_pts += 5; insights.append("🚀 MACD just crossed above zero-line — Fresh bullish trend signal!")
    elif macd_l_val < 0 and macd_line.values[-2] >= 0:
        bear_pts += 5; insights.append("📉 MACD just crossed below zero-line — Fresh bearish trend signal!")

    # ── 4. ADX Trend Strength (weight: 12) ───────────────────────────────
    try:
        up_move = h.diff()
        down_move = (-l.diff())
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)
        plus_di = 100 * (plus_dm.rolling(14).mean() / (atr_14 + 1e-10))
        minus_di = 100 * (minus_dm.rolling(14).mean() / (atr_14 + 1e-10))
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
        adx = dx.rolling(14).mean().values[-1]
        pdi_val = plus_di.values[-1]
        mdi_val = minus_di.values[-1]

        if adx > 25:
            if pdi_val > mdi_val:
                bull_pts += 12; insights.append(f"🟢 ADX {adx:.1f} (Strong Trend) with +DI > -DI — Strong bullish trend confirmed.")
            else:
                bear_pts += 12; insights.append(f"🔴 ADX {adx:.1f} (Strong Trend) with -DI > +DI — Strong bearish trend confirmed.")
        elif adx > 20:
            if pdi_val > mdi_val:
                bull_pts += 5; insights.append(f"🟡 ADX {adx:.1f} (Developing Trend) — Moderate bullish trend building.")
            else:
                bear_pts += 5; insights.append(f"🟡 ADX {adx:.1f} (Developing Trend) — Moderate bearish trend building.")
        else:
            insights.append(f"⚖️ ADX {adx:.1f} — No significant trend (Ranging/Choppy market).")
    except Exception:
        adx = 0.0

    # ── 5. Stochastic Oscillator (weight: 10) ────────────────────────────
    try:
        stoch_low = l.rolling(window=14).min()
        stoch_high = h.rolling(window=14).max()
        stoch_k = ((c - stoch_low) / (stoch_high - stoch_low + 1e-10)) * 100
        stoch_d = stoch_k.rolling(window=3).mean()
        sk = stoch_k.values[-1]
        sd = stoch_d.values[-1]
        
        if sk > 80 and sd > 80:
            bull_pts += 5; insights.append(f"🔥 Stochastic K={sk:.0f}/D={sd:.0f} — Overbought zone (strong momentum, reversal risk).")
        elif sk < 20 and sd < 20:
            bear_pts += 5; insights.append(f"❄️ Stochastic K={sk:.0f}/D={sd:.0f} — Oversold zone (weak momentum, bounce possible).")
        elif sk > sd and sk > 50:
            bull_pts += 5; insights.append(f"🟢 Stochastic K={sk:.0f} crossing above D={sd:.0f} in bullish zone.")
        elif sk < sd and sk < 50:
            bear_pts += 5; insights.append(f"🔴 Stochastic K={sk:.0f} crossing below D={sd:.0f} in bearish zone.")
    except Exception:
        sk = 50.0
        sd = 50.0

    # ── 6. Supertrend (weight: 10) ───────────────────────────────────────
    try:
        atr_st = tr.rolling(window=10).mean()
        hl2 = (h + l) / 2
        upper_band = hl2 + (3.0 * atr_st)
        lower_band = hl2 - (3.0 * atr_st)
        
        if curr_close > lower_band.values[-1] and curr_close > hl2.values[-1]:
            bull_pts += 10; insights.append("🟢 Supertrend(10, 3.0) — Bullish direction signal.")
        elif curr_close < upper_band.values[-1] and curr_close < hl2.values[-1]:
            bear_pts += 10; insights.append("🔴 Supertrend(10, 3.0) — Bearish direction signal.")
    except Exception:
        pass

    # ── 7. Bollinger Bands (weight: 12) ──────────────────────────────────
    sma_20 = c.rolling(window=20).mean()
    std_20 = c.rolling(window=20).std()
    bb_upper = (sma_20 + 2 * std_20).values[-1]
    bb_lower = (sma_20 - 2 * std_20).values[-1]
    bb_mid = sma_20.values[-1]
    bb_width = (bb_upper - bb_lower) / (bb_mid + 1e-10)
    
    # Bollinger Band Width squeeze detection
    bb_width_series = ((sma_20 + 2 * std_20) - (sma_20 - 2 * std_20)) / (sma_20 + 1e-10)
    bb_width_avg = bb_width_series.rolling(50).mean().values[-1] if len(bb_width_series.dropna()) >= 50 else bb_width

    if curr_close > bb_upper:
        bull_pts += 10; insights.append("⚡ Price ABOVE Upper Bollinger Band — Volatility breakout / Extreme bullish.")
    elif curr_close < bb_lower:
        bear_pts += 10; insights.append("⚡ Price BELOW Lower Bollinger Band — Volatility breakdown / Extreme bearish.")
    elif curr_close > bb_mid:
        bull_pts += 4; insights.append("🟢 Price in upper half of Bollinger Bands.")
    else:
        bear_pts += 4; insights.append("🔴 Price in lower half of Bollinger Bands.")

    if bb_width < bb_width_avg * 0.6:
        insights.append("🔔 Bollinger Band Squeeze detected — Explosive move imminent!")

    # ── 8. Volume Confirmation (weight: 15) ──────────────────────────────
    vol_sma = v.rolling(window=20).mean().values[-1]
    vol_ratio = curr_vol / (vol_sma + 1e-10)
    price_chg = (curr_close - prev_close) / (prev_close + 1e-10)

    if vol_ratio > 2.0:
        if price_chg > 0:
            bull_pts += 15; insights.append(f"🔥 Explosive buying volume: {vol_ratio:.1f}x average on up-candle.")
        else:
            bear_pts += 15; insights.append(f"💀 Panic selling volume: {vol_ratio:.1f}x average on down-candle.")
    elif vol_ratio > 1.5:
        if price_chg > 0:
            bull_pts += 10; insights.append(f"🟢 Strong buying volume: {vol_ratio:.1f}x average.")
        else:
            bear_pts += 10; insights.append(f"🔴 Strong selling volume: {vol_ratio:.1f}x average.")
    elif vol_ratio > 1.0:
        if price_chg > 0:
            bull_pts += 3; insights.append("🟢 Moderate buying volume support.")
        else:
            bear_pts += 3; insights.append("🔴 Moderate selling pressure.")
    else:
        insights.append(f"📊 Volume below average ({vol_ratio:.1f}x) — Low conviction move.")

    # ── 9. OBV Divergence (weight: 8) ────────────────────────────────────
    try:
        obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
        obv_vals = obv.values
        if len(obv_vals) >= 20:
            obv_slope = obv_vals[-1] - obv_vals[-10]
            price_slope = c.values[-1] - c.values[-10]
            if price_slope > 0 and obv_slope < 0:
                bear_pts += 8; insights.append("⚠️ Bearish OBV Divergence: Price rising but volume accumulation declining.")
            elif price_slope < 0 and obv_slope > 0:
                bull_pts += 8; insights.append("✨ Bullish OBV Divergence: Price falling but smart money accumulating.")
            elif obv_slope > 0:
                bull_pts += 4; insights.append("🟢 OBV trending up — Volume supports price action.")
            else:
                bear_pts += 4; insights.append("🔴 OBV trending down — Volume diverging from price.")
    except Exception:
        pass

    # ── 10. Multi-Level Support & Resistance (weight: 15) ────────────────
    swing_high_20 = h.rolling(window=20).max().values[-2]
    swing_low_20 = l.rolling(window=20).min().values[-2]
    swing_high_50 = h.rolling(window=min(50, len(h))).max().values[-2] if len(h) >= 50 else swing_high_20
    swing_low_50 = l.rolling(window=min(50, len(l))).min().values[-2] if len(l) >= 50 else swing_low_20

    if curr_close > swing_high_20:
        bull_pts += 10; insights.append("🚀 Breakout above 20-period swing high!")
    if curr_close > swing_high_50 and len(h) >= 50:
        bull_pts += 5; insights.append("🚀🚀 Breakout above 50-period swing high — Major bullish breakout!")
    if curr_close < swing_low_20:
        bear_pts += 10; insights.append("📉 Breakdown below 20-period swing low!")
    if curr_close < swing_low_50 and len(l) >= 50:
        bear_pts += 5; insights.append("📉📉 Breakdown below 50-period swing low — Major bearish breakdown!")

    # ── 11. Fibonacci Golden Zone & Retracement (weight: 14) ─────────────
    try:
        lookback = min(50, len(c) - 1)
        fib_high = h.values[-lookback:].max()
        fib_low = l.values[-lookback:].min()
        fib_range = fib_high - fib_low
        if fib_range > 0:
            fib_236 = fib_high - 0.236 * fib_range
            fib_382 = fib_high - 0.382 * fib_range
            fib_500 = fib_high - 0.500 * fib_range
            fib_618 = fib_high - 0.618 * fib_range
            fib_786 = fib_high - 0.786 * fib_range
            fib_position = (curr_close - fib_low) / fib_range

            # Golden Zone: 0.618 to 0.382 retracement (highest probability reversal area)
            in_golden_zone = fib_618 <= curr_close <= fib_382
            
            if fib_position > 0.786:
                bull_pts += 8; insights.append(f"🟢 Price at upper Fibonacci zone ({fib_position:.1%}) — Above 78.6% retracement.")
            elif fib_position > 0.618:
                bull_pts += 4; insights.append(f"🟢 Price near Fibonacci 61.8% level — Bullish territory.")
            elif fib_position < 0.236:
                bear_pts += 8; insights.append(f"🔴 Price at lower Fibonacci zone ({fib_position:.1%}) — Below 23.6% retracement.")
            elif fib_position < 0.382:
                bear_pts += 4; insights.append(f"🔴 Price near Fibonacci 38.2% support level — Bearish territory.")
            
            # Golden Zone reversal detection
            if in_golden_zone:
                body = abs(curr_close - curr_open)
                lower_wick = min(curr_open, curr_close) - curr_low
                # Bullish reversal at golden zone (hammer-like candle + price trending up from fib_618)
                if curr_close > curr_open and lower_wick > 1.5 * body:
                    bull_pts += 10; insights.append(f"🏆 GOLDEN ZONE BULLISH REVERSAL: Price in Fib 38.2%-61.8% zone ({fib_382:.2f}-{fib_618:.2f}) with bullish rejection candle!")
                elif curr_close < curr_open and (curr_high - max(curr_open, curr_close)) > 1.5 * body:
                    bear_pts += 10; insights.append(f"💀 GOLDEN ZONE BEARISH REJECTION: Price in Fib 38.2%-61.8% zone with bearish rejection candle!")
                else:
                    insights.append(f"📐 Price inside Fibonacci GOLDEN ZONE ({fib_382:.2f}-{fib_618:.2f}) — High probability reversal area.")

            # Sitting at key fib level (±1%)
            for fib_name, fib_lvl in [("23.6%", fib_236), ("38.2%", fib_382), ("50.0%", fib_500), ("61.8%", fib_618), ("78.6%", fib_786)]:
                if abs(curr_close - fib_lvl) / (fib_lvl + 1e-10) < 0.01:
                    insights.append(f"📐 Price sitting at Fibonacci {fib_name} level ({fib_lvl:.2f}) — Key decision zone.")
    except Exception:
        pass

    # ── 12. VWAP Enhanced (weight: 12) ───────────────────────────────────
    try:
        typical_price = (h + l + c) / 3
        vwap = (typical_price * v).cumsum() / (v.cumsum() + 1e-10)
        vwap_val = vwap.values[-1]
        vwap_prev = vwap.values[-2]
        
        # VWAP crossover
        if curr_close > vwap_val and prev_close <= vwap_prev:
            bull_pts += 10; insights.append(f"🚀 VWAP Reclaim! Price just crossed ABOVE VWAP ({vwap_val:.2f}) — Institutional buying signal!")
        elif curr_close < vwap_val and prev_close >= vwap_prev:
            bear_pts += 10; insights.append(f"📉 VWAP Rejection! Price just crossed BELOW VWAP ({vwap_val:.2f}) — Institutional selling signal!")
        elif curr_close > vwap_val:
            bull_pts += 6; insights.append(f"🟢 Price above VWAP ({vwap_val:.2f}) — Institutional buying bias.")
        else:
            bear_pts += 6; insights.append(f"🔴 Price below VWAP ({vwap_val:.2f}) — Institutional selling bias.")
        
        # VWAP + Volume confluence
        if curr_close > vwap_val and vol_ratio > 1.5:
            bull_pts += 4; insights.append("💎 VWAP + Volume Confluence: Above VWAP with above-average volume — High conviction bullish.")
        elif curr_close < vwap_val and vol_ratio > 1.5:
            bear_pts += 4; insights.append("💎 VWAP + Volume Confluence: Below VWAP with above-average volume — High conviction bearish.")
    except Exception:
        pass

    # ── 13. Candlestick Patterns (weight: 12) ────────────────────────────
    body = abs(curr_close - curr_open)
    upper_wick = curr_high - max(curr_open, curr_close)
    lower_wick = min(curr_open, curr_close) - curr_low
    prev_body = abs(prev_close - prev_open)
    candle_range = curr_high - curr_low
    avg_body = (o - c).abs().rolling(20).mean().values[-1] if len(c) >= 20 else body

    # Bullish Engulfing
    if prev_close < prev_open and curr_close > curr_open and curr_close >= prev_open and curr_open <= prev_close:
        bull_pts += 8; insights.append("🕯️ Bullish Engulfing — Strong reversal pattern!")

    # Bearish Engulfing
    elif prev_close > prev_open and curr_close < curr_open and curr_close <= prev_open and curr_open >= prev_close:
        bear_pts += 8; insights.append("🕯️ Bearish Engulfing — Strong reversal pattern!")

    # Hammer (bullish)
    elif lower_wick > 2 * body and upper_wick < body * 0.5 and curr_close > curr_open:
        bull_pts += 7; insights.append("🕯️ Hammer — Bullish reversal, selling pressure exhausted.")

    # Inverted Hammer / Shooting Star
    elif upper_wick > 2 * body and lower_wick < body * 0.5:
        if price_chg > 0 or curr_close < ema_9:
            bear_pts += 7; insights.append("🕯️ Shooting Star — Bearish rejection at highs.")
        else:
            bull_pts += 5; insights.append("🕯️ Inverted Hammer — Potential bullish reversal.")

    # Doji (indecision)
    elif body < candle_range * 0.1 and candle_range > 0:
        insights.append("🕯️ Doji detected — Market indecision / potential reversal point.")

    # Marubozu (strong conviction)
    elif body > candle_range * 0.9 and candle_range > 0:
        if curr_close > curr_open:
            bull_pts += 6; insights.append("🕯️ Bullish Marubozu — Full-body bullish candle, extreme buying conviction.")
        else:
            bear_pts += 6; insights.append("🕯️ Bearish Marubozu — Full-body bearish candle, extreme selling conviction.")

    # Three White Soldiers / Three Black Crows (check last 3 candles)
    if len(c) >= 4:
        c3 = c.values[-3:]
        o3 = o.values[-3:]
        if all(c3[i] > o3[i] for i in range(3)) and all(c3[i] > c3[i-1] for i in range(1, 3)):
            bull_pts += 8; insights.append("🕯️ Three White Soldiers — Powerful bullish continuation pattern.")
        elif all(c3[i] < o3[i] for i in range(3)) and all(c3[i] < c3[i-1] for i in range(1, 3)):
            bear_pts += 8; insights.append("🕯️ Three Black Crows — Powerful bearish continuation pattern.")

    # Morning Star / Evening Star (3-candle reversal patterns)
    if len(c) >= 4:
        c_3ago = c.values[-3]; o_3ago = o.values[-3]
        c_2ago = c.values[-2]; o_2ago = o.values[-2]
        body_3ago = abs(c_3ago - o_3ago)
        body_2ago = abs(c_2ago - o_2ago)
        # Morning Star: big red candle → small body → big green candle
        if c_3ago < o_3ago and body_3ago > avg_body * 1.5 and body_2ago < avg_body * 0.5 and curr_close > curr_open and body > avg_body * 1.0:
            bull_pts += 8; insights.append("🌟 Morning Star — Classic 3-candle bullish reversal pattern!")
        # Evening Star: big green candle → small body → big red candle
        elif c_3ago > o_3ago and body_3ago > avg_body * 1.5 and body_2ago < avg_body * 0.5 and curr_close < curr_open and body > avg_body * 1.0:
            bear_pts += 8; insights.append("🌑 Evening Star — Classic 3-candle bearish reversal pattern!")

    # ── 14. S/R Reversal Patterns (weight: 10) ───────────────────────────
    try:
        # Hammer at Support
        near_support = abs(curr_low - swing_low_20) / (swing_low_20 + 1e-10) < 0.015
        near_resistance = abs(curr_high - swing_high_20) / (swing_high_20 + 1e-10) < 0.015
        
        if near_support and lower_wick > 2 * body and curr_close > curr_open:
            bull_pts += 10; insights.append("🔑 S/R REVERSAL: Hammer candle at support level — High probability bullish bounce!")
        elif near_resistance and upper_wick > 2 * body and curr_close < curr_open:
            bear_pts += 10; insights.append("🔑 S/R REVERSAL: Shooting Star at resistance level — High probability bearish rejection!")
        
        # Breakout + Retest (price broke above resistance and now retesting it as support)
        if len(h) >= 5:
            prev_5_high = h.values[-6:-1].max()
            prev_5_low = l.values[-6:-1].min()
            if curr_close > prev_5_high and curr_low <= prev_5_high * 1.005:
                bull_pts += 6; insights.append("🔑 Breakout + Retest: Price broke resistance and retesting as support — Textbook bullish entry!")
            elif curr_close < prev_5_low and curr_high >= prev_5_low * 0.995:
                bear_pts += 6; insights.append("🔑 Breakdown + Retest: Price broke support and retesting as resistance — Textbook bearish entry!")
    except Exception:
        pass

    # ── 15. Price Momentum (Rate of Change) (weight: 8) ──────────────────
    if len(c) >= 15:
        roc_14 = ((curr_close - c.values[-15]) / (c.values[-15] + 1e-10)) * 100
        if roc_14 > 5:
            bull_pts += 8; insights.append(f"📈 14-period ROC: +{roc_14:.1f}% — Strong upward momentum.")
        elif roc_14 > 0:
            bull_pts += 3; insights.append(f"📈 14-period ROC: +{roc_14:.1f}% — Mild upward momentum.")
        elif roc_14 < -5:
            bear_pts += 8; insights.append(f"📉 14-period ROC: {roc_14:.1f}% — Strong downward momentum.")
        elif roc_14 < 0:
            bear_pts += 3; insights.append(f"📉 14-period ROC: {roc_14:.1f}% — Mild downward momentum.")

    # ── 16. Pivot Points (Standard/Classic) (weight: 10) ──────────────────
    try:
        prev_h = h.rolling(window=20).max().values[-2]
        prev_l = l.rolling(window=20).min().values[-2]
        prev_c = c.values[-2]
        
        pivot = (prev_h + prev_l + prev_c) / 3
        r1 = 2 * pivot - prev_l
        s1 = 2 * pivot - prev_h
        r2 = pivot + (prev_h - prev_l)
        s2 = pivot - (prev_h - prev_l)
        
        if curr_close > r2:
            bull_pts += 10; insights.append(f"🚀 Pivot Breakout: Price crossed above R2 Resistance ({r2:.2f})!")
        elif curr_close > r1:
            bull_pts += 6; insights.append(f"🟢 Pivot Trend: Price is above R1 Resistance ({r1:.2f}) — target R2.")
        elif curr_close < s2:
            bear_pts += 10; insights.append(f"📉 Pivot Breakdown: Price crossed below S2 Support ({s2:.2f})!")
        elif curr_close < s1:
            bear_pts += 6; insights.append(f"🔴 Pivot Trend: Price is below S1 Support ({s1:.2f}) — target S2.")
        else:
            insights.append(f"⚖️ Pivot Range: Price trading inside standard S1/R1 Pivot range.")
    except Exception:
        pass

    # ══════════════════════════════════════════════════════════════════════
    # NEW ADVANCED INDICATORS
    # ══════════════════════════════════════════════════════════════════════

    # ── 17. Williams %R (weight: 8) ──────────────────────────────────────
    try:
        w_high = h.rolling(window=14).max()
        w_low = l.rolling(window=14).min()
        williams_r = ((w_high - c) / (w_high - w_low + 1e-10)) * -100
        wr_val = williams_r.values[-1]
        
        if wr_val > -20:
            bear_pts += 4; insights.append(f"📊 Williams %R: {wr_val:.0f} — Overbought territory (reversal risk).")
        elif wr_val < -80:
            bull_pts += 4; insights.append(f"📊 Williams %R: {wr_val:.0f} — Oversold territory (bounce likely).")
        
        # Williams %R crossover from oversold
        if len(williams_r.dropna()) >= 2:
            wr_prev = williams_r.values[-2]
            if wr_val > -80 and wr_prev <= -80:
                bull_pts += 8; insights.append(f"🚀 Williams %R crossed above -80 (from {wr_prev:.0f} → {wr_val:.0f}) — Bullish momentum ignition!")
            elif wr_val < -20 and wr_prev >= -20:
                bear_pts += 8; insights.append(f"📉 Williams %R crossed below -20 (from {wr_prev:.0f} → {wr_val:.0f}) — Bearish momentum collapse!")
    except Exception:
        pass

    # ── 18. Chaikin Money Flow (CMF) (weight: 10) ────────────────────────
    try:
        mf_multiplier = ((c - l) - (h - c)) / (h - l + 1e-10)
        mf_volume = mf_multiplier * v
        cmf = mf_volume.rolling(window=20).sum() / (v.rolling(window=20).sum() + 1e-10)
        cmf_val = cmf.values[-1]
        
        if cmf_val > 0.15:
            bull_pts += 10; insights.append(f"💰 CMF {cmf_val:.3f} — Strong institutional BUYING pressure (Smart Money inflow).")
        elif cmf_val > 0.05:
            bull_pts += 5; insights.append(f"🟢 CMF {cmf_val:.3f} — Moderate buying pressure.")
        elif cmf_val < -0.15:
            bear_pts += 10; insights.append(f"💸 CMF {cmf_val:.3f} — Strong institutional SELLING pressure (Smart Money outflow).")
        elif cmf_val < -0.05:
            bear_pts += 5; insights.append(f"🔴 CMF {cmf_val:.3f} — Moderate selling pressure.")
        else:
            insights.append(f"⚖️ CMF {cmf_val:.3f} — Neutral money flow.")
    except Exception:
        pass

    # ── 19. Smart Money Concepts: Order Blocks (weight: 12) ──────────────
    try:
        if len(c) >= 10:
            # Bullish Order Block: Last bearish candle before a significant up-move
            # Look for a red candle followed by 3+ consecutive green candles moving up
            for i in range(-10, -3):
                if c.values[i] < o.values[i]:  # Bearish candle
                    subsequent_greens = sum(1 for j in range(i+1, min(i+4, 0) or -1) if c.values[j] > o.values[j])
                    if subsequent_greens >= 2:
                        ob_top = max(o.values[i], c.values[i])
                        ob_bottom = min(o.values[i], c.values[i])
                        # Check if current price is near or inside the order block
                        if ob_bottom <= curr_close <= ob_top * 1.01:
                            bull_pts += 10; insights.append(f"🏦 SMART MONEY: Bullish Order Block detected @ {ob_bottom:.2f}-{ob_top:.2f} — Institutional demand zone!")
                            break
                elif c.values[i] > o.values[i]:  # Bullish candle
                    subsequent_reds = sum(1 for j in range(i+1, min(i+4, 0) or -1) if c.values[j] < o.values[j])
                    if subsequent_reds >= 2:
                        ob_top = max(o.values[i], c.values[i])
                        ob_bottom = min(o.values[i], c.values[i])
                        if ob_bottom * 0.99 <= curr_close <= ob_top:
                            bear_pts += 10; insights.append(f"🏦 SMART MONEY: Bearish Order Block detected @ {ob_bottom:.2f}-{ob_top:.2f} — Institutional supply zone!")
                            break
    except Exception:
        pass

    # ── 20. Smart Money: Fair Value Gaps (FVG) (weight: 10) ─────────────
    try:
        if len(c) >= 5:
            # Bullish FVG: candle[i-1] high < candle[i+1] low (gap that price hasn't filled)
            for i in range(-4, -1):
                prev_candle_high = h.values[i-1]
                next_candle_low = l.values[i+1]
                if next_candle_low > prev_candle_high:
                    fvg_top = next_candle_low
                    fvg_bottom = prev_candle_high
                    if fvg_bottom <= curr_close <= fvg_top:
                        bull_pts += 8; insights.append(f"📊 SMART MONEY: Bullish FVG (Fair Value Gap) @ {fvg_bottom:.2f}-{fvg_top:.2f} — Discount zone, expect upward fill!")
                        break
                    elif curr_close > fvg_top:
                        bull_pts += 3; insights.append(f"📊 Bullish FVG filled — Continuation higher expected.")
                        break
                        
            # Bearish FVG: candle[i-1] low > candle[i+1] high (gap down)
            for i in range(-4, -1):
                prev_candle_low = l.values[i-1]
                next_candle_high = h.values[i+1]
                if prev_candle_low > next_candle_high:
                    fvg_top = prev_candle_low
                    fvg_bottom = next_candle_high
                    if fvg_bottom <= curr_close <= fvg_top:
                        bear_pts += 8; insights.append(f"📊 SMART MONEY: Bearish FVG (Fair Value Gap) @ {fvg_bottom:.2f}-{fvg_top:.2f} — Premium zone, expect downward fill!")
                        break
                    elif curr_close < fvg_bottom:
                        bear_pts += 3; insights.append(f"📊 Bearish FVG filled — Continuation lower expected.")
                        break
    except Exception:
        pass

    # ── 21. Smart Money: Liquidity Sweep (Stop Hunt) (weight: 12) ────────
    try:
        if len(c) >= 10:
            recent_low = l.values[-10:-1].min()
            recent_high = h.values[-10:-1].max()
            
            # Bullish Liquidity Sweep: price swept below recent lows then closed back above
            if curr_low < recent_low and curr_close > recent_low:
                bull_pts += 12; insights.append(f"🎯 SMART MONEY: Bullish Liquidity Sweep! Price swept below {recent_low:.2f} and reclaimed — Stop hunt completed, expect reversal UP!")
            
            # Bearish Liquidity Sweep: price swept above recent highs then closed back below
            elif curr_high > recent_high and curr_close < recent_high:
                bear_pts += 12; insights.append(f"🎯 SMART MONEY: Bearish Liquidity Sweep! Price swept above {recent_high:.2f} and rejected — Stop hunt completed, expect reversal DOWN!")
    except Exception:
        pass

    # ── 22. ATR Volatility Context (weight: 6) ───────────────────────────
    try:
        atr_avg_50 = tr.rolling(window=14).mean().rolling(50).mean().values[-1]
        if atr_val > atr_avg_50 * 1.5:
            insights.append(f"⚡ ATR Expansion: Current ATR ({atr_pct:.2f}%) is 1.5x above average — High volatility / Trending market!")
            if price_chg > 0:
                bull_pts += 6; insights.append("🔥 Volatility expanding with bullish price action — Trend acceleration.")
            else:
                bear_pts += 6; insights.append("💀 Volatility expanding with bearish price action — Sell-off acceleration.")
        elif atr_val < atr_avg_50 * 0.5:
            insights.append(f"🔕 ATR Contraction: Current ATR ({atr_pct:.2f}%) is below 50% of average — Low volatility / Squeeze imminent!")
    except Exception:
        pass

    # ── 23. Market Specific Extra Technical Metrics ──────────────────────
    if is_india_market(market):
        # Supertrend Fast (7, 3) Crossover check
        try:
            atr_7 = tr.rolling(window=7).mean().values[-1]
            hl2_val = (curr_high + curr_low) / 2
            st_up_7 = hl2_val - 3.0 * atr_7
            if curr_close > st_up_7:
                bull_pts += 6; insights.append("🟢 Supertrend (7, 3) shows strong short-term Indian swing buy signal.")
            else:
                bear_pts += 6; insights.append("🔴 Supertrend (7, 3) shows strong short-term Indian swing sell signal.")
        except Exception:
            pass
    elif is_crypto_market(market):
        # Crypto Futures specific: Volatility expansions and hyper-momentum check
        try:
            atr_avg = tr.rolling(window=14).mean().rolling(50).mean().values[-1]
            if atr_val > atr_avg * 1.5:
                insights.append("🪙 CoinDCX Crypto Alert: High volatility contraction/expansion breakout underway!")
                if price_chg > 0:
                    bull_pts += 8; insights.append("🔥 Volatility expanding to the upside (Crypto bullish breakout).")
                else:
                    bear_pts += 8; insights.append("💀 Volatility expanding to the downside (Crypto bearish dump).")
        except Exception:
            pass
            
        # Dual RSI & Stochastic hyper momentum crossover
        try:
            if rsi > 60 and sk > 70:
                bull_pts += 8; insights.append("🔥 CoinDCX Crypto Alert: Dual RSI & Stochastic hyper-bullish momentum overlap.")
            elif rsi < 40 and sk < 30:
                bear_pts += 8; insights.append("💀 CoinDCX Crypto Alert: Dual RSI & Stochastic hyper-bearish momentum overlap.")
        except Exception:
            pass

    # ── 24. S/R Breakout / Breakdown / Fakeout / Reversal (weight: 18) ───
    sr_analysis = analyze_sr_breakout(df, timeframe=timeframe)
    sr_bull, sr_bear, sr_insights = apply_sr_breakout_scoring(sr_analysis)
    bull_pts += sr_bull
    bear_pts += sr_bear
    insights.extend(sr_insights)

    # ══════════════════════════════════════════════════════════════════════
    # COMPOSITE SCORE & TRADE SIGNAL GENERATION
    # ══════════════════════════════════════════════════════════════════════
    total = bull_pts + bear_pts
    net_score = ((bull_pts - bear_pts) / (total + 1e-10)) * 100.0
    trade_confidence = compute_trade_confidence(net_score, sr_analysis)

    if net_score >= 65:
        rating = "🔥 STRONG BUY / VERY BULLISH"
    elif net_score >= 35:
        rating = "📈 BUY / BULLISH"
    elif net_score >= 10:
        rating = "🟢 LEAN BULLISH"
    elif net_score <= -65:
        rating = "💀 STRONG SELL / VERY BEARISH"
    elif net_score <= -35:
        rating = "📉 SELL / BEARISH"
    elif net_score <= -10:
        rating = "🔴 LEAN BEARISH"
    else:
        rating = "⚖️ NEUTRAL"

    # Determine trend strength label
    if abs(net_score) >= 65:
        trend_str = "EXTREME"
    elif abs(net_score) >= 35:
        trend_str = "STRONG"
    elif abs(net_score) >= 10:
        trend_str = "MODERATE"
    else:
        trend_str = "WEAK/NONE"

    # ── ATR-Based Trade Signal with Dynamic SL/TP ────────────────────────
    atr_sl_mult = 1.5
    atr_tp_mult = 2.0
    
    trade_signal = "WAIT"
    sl_pct = 0.0
    tp_pct = 0.0
    
    sr_suggest = sr_analysis.get("trade_suggestion", "WAIT")
    min_conf = 50

    if net_score >= 15 and trade_confidence >= min_conf:
        if sr_suggest == "SELL" and sr_analysis.get("confidence", 0) >= 60:
            trade_signal = "WAIT"
            insights.append(
                f"⏸️ BUY blocked — S/R says {sr_analysis.get('event_label', 'bearish')} "
                f"({sr_analysis.get('confidence', 0)}% conf)."
            )
        else:
            trade_signal = "BUY"
            sl_price = curr_close - (atr_sl_mult * atr_val)
            tp_price = curr_close + (atr_tp_mult * atr_val)
            sl_pct = round(abs(curr_close - sl_price) / (curr_close + 1e-10) * 100, 2)
            tp_pct = round(abs(tp_price - curr_close) / (curr_close + 1e-10) * 100, 2)
            insights.append(
                f"🎯 ATR TRADE: BUY | Confidence {trade_confidence}% | SL {sl_pct:.2f}% | "
                f"TP {tp_pct:.2f}% | R:R 1:{atr_tp_mult/atr_sl_mult:.1f}"
            )
    elif net_score <= -15 and trade_confidence >= min_conf:
        if sr_suggest == "BUY" and sr_analysis.get("confidence", 0) >= 60:
            trade_signal = "WAIT"
            insights.append(
                f"⏸️ SELL blocked — S/R says {sr_analysis.get('event_label', 'bullish')} "
                f"({sr_analysis.get('confidence', 0)}% conf)."
            )
        else:
            trade_signal = "SELL"
            sl_price = curr_close + (atr_sl_mult * atr_val)
            tp_price = curr_close - (atr_tp_mult * atr_val)
            sl_pct = round(abs(sl_price - curr_close) / (curr_close + 1e-10) * 100, 2)
            tp_pct = round(abs(curr_close - tp_price) / (curr_close + 1e-10) * 100, 2)
            insights.append(
                f"🎯 ATR TRADE: SELL | Confidence {trade_confidence}% | SL {sl_pct:.2f}% | "
                f"TP {tp_pct:.2f}% | R:R 1:{atr_tp_mult/atr_sl_mult:.1f}"
            )
    else:
        insights.append(
            f"⏸️ ATR TRADE: WAIT — Score {net_score:.1f}, trade confidence {trade_confidence}% "
            f"(need ≥{min_conf}%). ATR: {atr_pct:.2f}%"
        )

    return {
        "score": round(net_score, 1),
        "rating": rating,
        "insights": insights,
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
        "macd_hist": round(macd_h_val, 6),
        "adx": round(adx, 1) if isinstance(adx, (int, float)) else 0.0,
        "trend_str": trend_str,
        "trade_signal": trade_signal,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "atr_pct": round(atr_pct, 2),
        "trade_confidence": trade_confidence,
        "sr_breakout": sr_analysis,
    }

def run_sentiment_screener(
    tickers: list[str],
    timeframes: list[str],
    *,
    market: str = GROWW_MARKET,
    groww_token: str = "",
    exchange: str = "NSE",
    lookback_days: int = 120,
) -> dict:
    """Scan tickers x timeframes; returns ranked rows."""
    rows: list[dict] = []
    errors: list[str] = []
    for tick in tickers:
        for tf in timeframes:
            try:
                df = fetch_data_for_gap_scan(
                    tick, tf, market, groww_token, exchange, limit=max(lookback_days, 300)
                )
                if df is None or df.empty or len(df) < 50:
                    rows.append({
                        "ticker": tick,
                        "timeframe": tf,
                        "score": 0.0,
                        "rating": "No Data",
                        "insights": ["Insufficient candle history."],
                        "trade_signal": "WAIT",
                        "error": "insufficient_data",
                    })
                    continue
                analysis = analyze_ticker_sentiment(df, market=market, timeframe=tf)
                rows.append({
                    "ticker": tick,
                    "timeframe": tf,
                    "score": analysis.get("score", 0),
                    "rating": analysis.get("rating", ""),
                    "insights": analysis.get("insights", []),
                    "rsi": analysis.get("rsi"),
                    "vol_ratio": analysis.get("vol_ratio"),
                    "macd_hist": analysis.get("macd_hist"),
                    "adx": analysis.get("adx"),
                    "trend_str": analysis.get("trend_str"),
                    "trade_signal": analysis.get("trade_signal"),
                    "sl_pct": analysis.get("sl_pct"),
                    "tp_pct": analysis.get("tp_pct"),
                    "atr_pct": analysis.get("atr_pct"),
                    "trade_confidence": analysis.get("trade_confidence"),
                    "sr_breakout": analysis.get("sr_breakout"),
                    "current_price": float(df["close"].iloc[-1]),
                })
            except Exception as exc:
                errors.append(f"{tick}|{tf}: {exc}")
                rows.append({"ticker": tick, "timeframe": tf, "error": str(exc)[:200]})
    rows.sort(key=lambda r: abs(r.get("score") or 0), reverse=True)
    return {"market": market, "rows": rows, "errors": errors}
