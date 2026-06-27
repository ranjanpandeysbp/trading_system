"""
top_bottom_forecast.py
----------------------
Breakout / breakdown probability engine for the Top/Bottom analyzer.
Combines structure, momentum, volatility, patterns, EMA/S/R, and optional AI refinement.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import numpy as np
import pandas as pd
from app.market_pulse.env_config import api_key_env_hint
from app.market_pulse.price_action import analyze_ema_crossovers, detect_support_resistance
from app.market_pulse.price_extremes import classify_swing_structure, fetch_all_time_extremes
from app.market_pulse.sma_ema_position import analyze_sma_ema_position

try:
    from groq import Groq
except ImportError:
    Groq = None

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


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _sigmoid(x: float) -> float:
    return 100.0 / (1.0 + np.exp(-x))


def _momentum_pct_per_bar(close: pd.Series, bars: int = 10) -> float:
    if close is None or len(close) < bars + 1:
        return 0.0
    tail = close.tail(bars + 1)
    start = float(tail.iloc[0])
    end = float(tail.iloc[-1])
    if start <= 0:
        return 0.0
    total_pct = (end / start - 1) * 100
    return total_pct / bars


def _linear_slope_per_bar(close: pd.Series, bars: int = 15) -> float:
    if close is None or len(close) < 3:
        return 0.0
    y = close.tail(bars).astype(float).values
    x = np.arange(len(y))
    if len(y) < 2:
        return 0.0
    slope = np.polyfit(x, y, 1)[0]
    last = float(y[-1])
    return (slope / last * 100) if last > 0 else 0.0


def _volume_bias(df: pd.DataFrame) -> float:
    """+1 rising volume, -1 falling, 0 flat."""
    if df is None or "volume" not in df.columns or len(df) < 10:
        return 0.0
    vol = df["volume"].astype(float).tail(10)
    if vol.isna().all() or vol.sum() == 0:
        return 0.0
    first_half = vol.iloc[:5].mean()
    second_half = vol.iloc[5:].mean()
    if first_half <= 0:
        return 0.0
    chg = (second_half - first_half) / first_half
    return float(np.clip(chg * 3, -1, 1))


def _prob_break_level(
    current: float,
    level: float,
    direction: str,
    atr: float,
    mom_pct_bar: float,
    slope_pct_bar: float,
    rsi: float,
    structure_boost: float,
    pattern_boost: float,
    ema_boost: float,
    vol_bias: float,
    horizon: int = 5,
) -> tuple[float, list[str]]:
    """
    Heuristic probability (0–100) that price crosses `level` within `horizon` candles.
    direction: 'up' (break above) or 'down' (break below).
    """
    reasons: list[str] = []
    if current <= 0 or level <= 0 or atr <= 0:
        return 5.0, ["Insufficient price/ATR data."]

    dist = level - current
    dist_pct = abs(dist) / current * 100
    dist_atr = abs(dist) / atr

    already_broken = (direction == "up" and current >= level) or (direction == "down" and current <= level)
    if already_broken:
        return 88.0, [f"Price already at/through level ({level:.2f})."]

    toward = mom_pct_bar if direction == "up" else -mom_pct_bar
    slope = slope_pct_bar if direction == "up" else -slope_pct_bar
    effective_mom = toward * 0.6 + slope * 0.4

    # Base: farther in ATR terms → lower probability within 5 bars
    base = _sigmoid(2.8 - dist_atr * 1.15 + effective_mom * 0.35 * horizon)

    if direction == "up":
        if rsi > 72:
            base -= 12
            reasons.append(f"RSI {rsi:.0f} overbought — reduces upside break odds.")
        elif rsi < 45 and effective_mom > 0:
            base += 6
            reasons.append(f"RSI {rsi:.0f} has room to run higher.")
    else:
        if rsi < 28:
            base -= 12
            reasons.append(f"RSI {rsi:.0f} oversold — reduces downside break odds.")
        elif rsi > 55 and effective_mom < 0:
            base += 6
            reasons.append(f"RSI {rsi:.0f} supports further weakness.")

    base += structure_boost + pattern_boost + ema_boost + vol_bias * 5

    if dist_atr <= 0.35:
        base += 18
        reasons.append(f"Only {dist_atr:.2f} ATR from level — touch likely within {horizon} bars.")
    elif dist_atr <= 0.75:
        base += 10
        reasons.append(f"{dist_atr:.1f} ATR from level — reachable if momentum holds.")
    else:
        reasons.append(f"{dist_atr:.1f} ATR / {dist_pct:.1f}% away — needs strong momentum.")

    if effective_mom > 0.08 and direction == "up":
        reasons.append(f"Bullish drift +{effective_mom:.3f}%/bar supports upside test.")
    elif effective_mom < -0.08 and direction == "down":
        reasons.append(f"Bearish drift {effective_mom:.3f}%/bar supports downside test.")
    elif abs(effective_mom) < 0.03:
        base -= 8
        reasons.append("Flat momentum — break less likely near-term.")

    return round(_clamp(base), 1), reasons


def _pattern_boosts(candle_patterns: list, chart_patterns: list) -> tuple[float, float]:
    """Return (bull_boost, bear_boost) in probability points."""
    bull, bear = 0.0, 0.0
    for p in (candle_patterns or [])[-5:]:
        if p.get("type") == "bullish":
            bull += 4
        elif p.get("type") == "bearish":
            bear += 4
    for p in chart_patterns or []:
        if p.get("type") == "bullish":
            bull += 8
        elif p.get("type") == "bearish":
            bear += 8
    return min(bull, 20), min(bear, 20)


def _ema_boosts(ema: dict, sma_ema: dict) -> tuple[float, float]:
    bull, bear = 0.0, 0.0
    stack = (ema or {}).get("ema_stack", "MIXED")
    if stack == "BULLISH":
        bull += 10
    elif stack == "BEARISH":
        bear += 10
    regime = (sma_ema or {}).get("regime", "")
    if regime == "ABOVE_BOTH":
        bull += 6
    elif regime == "BELOW_BOTH":
        bear += 6
    return bull, bear


def _structure_boosts(swing: dict) -> tuple[float, float]:
    """Boost upside break vs downside break from HH/HL/LH/LL."""
    bull, bear = 0.0, 0.0
    hl = swing.get("high_label", "N/A")
    ll = swing.get("low_label", "N/A")
    if hl == "HH":
        bull += 12
    elif hl == "LH":
        bear += 8
    if ll == "HL":
        bull += 8
    elif ll == "LL":
        bear += 12
    bias = swing.get("structure_bias", "neutral")
    if bias == "bullish":
        bull += 8
    elif bias == "bearish":
        bear += 8
    return bull, bear


def _project_candles(
    current: float,
    atr: float,
    slope_pct_bar: float,
    mom_pct_bar: float,
    horizon: int = 5,
) -> list[dict]:
    """Project expected close and range for next 1–5 candles."""
    drift = slope_pct_bar * 0.55 + mom_pct_bar * 0.45
    rows = []
    price = current
    for n in range(1, horizon + 1):
        price = price * (1 + drift / 100)
        half_range = atr * (0.45 + 0.05 * n)
        low = price - half_range
        high = price + half_range
        if drift > 0.04:
            bias = "UP"
        elif drift < -0.04:
            bias = "DOWN"
        else:
            bias = "FLAT"
        rows.append({
            "candle": n,
            "expected_close": round(price, 4),
            "expected_low": round(low, 4),
            "expected_high": round(high, 4),
            "bias": bias,
        })
    return rows


def compute_top_bottom_forecast(
    df: pd.DataFrame,
    metrics: dict,
    symbol: str,
    market: str,
    exchange: str = "NSE",
    groww_token: str = "",
    candle_patterns: list | None = None,
    chart_patterns: list | None = None,
    supports: list | None = None,
    resistances: list | None = None,
    lookback: int = 100,
    horizon: int = 5,
    timeframe: str = "1d",
) -> dict:
    """Full quantitative breakout / breakdown forecast for Top/Bottom analyzer."""
    current = float(metrics.get("current", 0) or 0)
    rsi = float(metrics.get("rsi", 50) or 50)
    window_high = float(metrics.get("top", 0) or 0)
    window_low = float(metrics.get("bottom", 0) or 0)

    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else float((h - l).tail(14).mean())
    if pd.isna(atr) or atr <= 0:
        atr = max((window_high - window_low) * 0.02, current * 0.01)

    mom = _momentum_pct_per_bar(c, 10)
    slope = _linear_slope_per_bar(c, 15)
    vol_b = _volume_bias(df)

    swing = classify_swing_structure(df.tail(min(lookback, len(df))), window=5)
    swing_high = swing.get("recent_swing_high") or window_high
    swing_low = swing.get("recent_swing_low") or window_low

    all_time = fetch_all_time_extremes(symbol, market, exchange, groww_token)
    ath = all_time.get("ath")
    atl = all_time.get("atl")
    gap_ath = ((ath - current) / ath * 100) if ath and current else None
    gap_atl = ((current - atl) / atl * 100) if atl and current else None

    ema = analyze_ema_crossovers(df)
    sma_ema = analyze_sma_ema_position(df, timeframe=timeframe)
    bull_pat, bear_pat = _pattern_boosts(candle_patterns, chart_patterns)
    bull_struct, bear_struct = _structure_boosts(swing)
    bull_ema, bear_ema = _ema_boosts(ema, sma_ema)

    if resistances:
        nearest_res = min(resistances, key=lambda x: abs(x - current))
        if nearest_res > current and (nearest_res - current) / current * 100 < 2:
            bear_pat += 5
    if supports:
        nearest_sup = min(supports, key=lambda x: abs(x - current))
        if nearest_sup < current and (current - nearest_sup) / current * 100 < 2:
            bull_pat += 5

    drivers: list[str] = [
        f"Swing structure: {swing.get('structure_name', 'N/A')} ({swing.get('high_label')}/{swing.get('low_label')}).",
        f"EMA stack: {(ema or {}).get('ema_stack', 'N/A')} · 9/20 regime: {(sma_ema or {}).get('regime', 'N/A')}.",
        f"Momentum {mom:+.3f}%/bar · slope {slope:+.3f}%/bar · ATR {atr:.4f}.",
    ]
    if ath:
        drivers.append(f"ATH {ath:.2f} ({gap_ath:.1f}% below)" if gap_ath is not None else f"ATH {ath:.2f}")
    if atl:
        drivers.append(f"ATL {atl:.2f} ({gap_atl:.1f}% above)" if gap_atl is not None else f"ATL {atl:.2f}")

    all_reasons: dict[str, list[str]] = {}

    ath_prob, r_ath = (5.0, [])
    if ath and ath > current:
        ath_prob, r_ath = _prob_break_level(
            current, ath, "up", atr, mom, slope, rsi,
            bull_struct + bull_ema, bull_pat, 0, vol_b, horizon,
        )
    elif ath and current >= ath:
        ath_prob, r_ath = 92.0, ["Price at or above all-time high."]

    atl_prob, r_atl = (5.0, [])
    if atl and atl < current:
        atl_prob, r_atl = _prob_break_level(
            current, atl, "down", atr, mom, slope, rsi,
            bear_struct + bear_ema, bear_pat, 0, vol_b, horizon,
        )
    elif atl and current <= atl:
        atl_prob, r_atl = 92.0, ["Price at or below all-time low."]

    sh_prob, r_sh = _prob_break_level(
        current, float(swing_high), "up", atr, mom, slope, rsi,
        bull_struct + bull_ema, bull_pat, 0, vol_b, horizon,
    )
    sl_prob, r_sl = _prob_break_level(
        current, float(swing_low), "down", atr, mom, slope, rsi,
        bear_struct + bear_ema, bear_pat, 0, vol_b, horizon,
    )
    wh_prob, r_wh = _prob_break_level(
        current, window_high, "up", atr, mom, slope, rsi,
        bull_struct + bull_ema, bull_pat, 0, vol_b, horizon,
    )
    wl_prob, r_wl = _prob_break_level(
        current, window_low, "down", atr, mom, slope, rsi,
        bear_struct + bear_ema, bear_pat, 0, vol_b, horizon,
    )

    all_reasons = {
        "ath": r_ath, "atl": r_atl,
        "swing_high": r_sh, "swing_low": r_sl,
        "window_high": r_wh, "window_low": r_wl,
    }

    candle_forecast = _project_candles(current, atr, slope, mom, horizon)

    # Composite confidence: agreement of dominant signals
    bias = str(metrics.get("bias", "NEUTRAL"))
    if "LONG" in bias:
        dominant = max(ath_prob, sh_prob, wh_prob)
        conflict = max(atl_prob, sl_prob, wl_prob)
    elif "SHORT" in bias:
        dominant = max(atl_prob, sl_prob, wl_prob)
        conflict = max(ath_prob, sh_prob, wh_prob)
    else:
        dominant = max(ath_prob, sh_prob, wh_prob, atl_prob, sl_prob, wl_prob)
        conflict = min(ath_prob, sh_prob, wh_prob, atl_prob, sl_prob, wl_prob)

    signal_strength = abs(mom) + abs(slope) * 0.5 + (20 if "PEAK" in metrics.get("top_status", "") or "TROUGH" in metrics.get("bottom_status", "") else 0)
    composite = _clamp(45 + dominant * 0.35 - conflict * 0.15 + min(signal_strength, 15))

    if "PEAK" in metrics.get("top_status", ""):
        narrative = (
            f"Next {horizon} candles: elevated rejection risk near window high "
            f"({window_high:.2f}); upside breaks need volume confirmation."
        )
    elif "TROUGH" in metrics.get("bottom_status", ""):
        narrative = (
            f"Next {horizon} candles: bounce potential from window low "
            f"({window_low:.2f}); watch for HL confirmation."
        )
    elif slope > 0.05:
        narrative = f"Next {horizon} candles: upward drift toward {window_high:.2f} window high likely."
    elif slope < -0.05:
        narrative = f"Next {horizon} candles: downward drift toward {window_low:.2f} window low likely."
    else:
        narrative = f"Next {horizon} candles: range-bound between swing levels — break needs a catalyst."

    return {
        "horizon": horizon,
        "composite_confidence": round(composite, 1),
        "ath_cross_prob": ath_prob,
        "atl_cross_prob": atl_prob,
        "swing_high_break_prob": sh_prob,
        "swing_low_break_prob": sl_prob,
        "window_high_break_prob": wh_prob,
        "window_low_break_prob": wl_prob,
        "ath": ath,
        "atl": atl,
        "gap_from_ath_pct": gap_ath,
        "gap_from_atl_pct": gap_atl,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "window_high": window_high,
        "window_low": window_low,
        "swing_structure": swing,
        "candle_forecast": candle_forecast,
        "next_candles_summary": narrative,
        "drivers": drivers,
        "reasons": all_reasons,
        "momentum_pct_bar": round(mom, 4),
        "slope_pct_bar": round(slope, 4),
        "atr": round(atr, 4),
        "model": "quant_multi_factor_v1",
    }


def build_tb_forecast_ai_prompt(
    forecast: dict,
    metrics: dict,
    symbol: str,
    timeframe: str,
    market: str,
    lookback: int,
    currency: str,
) -> str:
    lines = [
        "=== TOP/BOTTOM BREAKOUT FORECAST — AI REFINEMENT ===",
        f"Symbol: {symbol} | TF: {timeframe} | Market: {market} | Lookback: {lookback} candles",
        f"Current: {currency}{metrics.get('current', 0):.4f}",
        f"Top status: {metrics.get('top_status')} | Bottom status: {metrics.get('bottom_status')}",
        f"Bias: {metrics.get('bias')} | RSI: {metrics.get('rsi', 0):.1f}",
        "",
        "=== QUANT MODEL OUTPUT (next 1-5 candles) ===",
        f"Composite confidence: {forecast.get('composite_confidence')}%",
        f"P(cross ATH): {forecast.get('ath_cross_prob')}% | P(cross ATL): {forecast.get('atl_cross_prob')}%",
        f"P(break swing high): {forecast.get('swing_high_break_prob')}% | P(break swing low): {forecast.get('swing_low_break_prob')}%",
        f"P(break window high): {forecast.get('window_high_break_prob')}% | P(break window low): {forecast.get('window_low_break_prob')}%",
        f"ATH: {forecast.get('ath')} | ATL: {forecast.get('atl')}",
        f"Swing H/L: {forecast.get('swing_high')} / {forecast.get('swing_low')}",
        f"Window H/L: {forecast.get('window_high')} / {forecast.get('window_low')}",
        f"Momentum: {forecast.get('momentum_pct_bar')}%/bar | Slope: {forecast.get('slope_pct_bar')}%/bar",
        "",
        "=== CANDLE PROJECTION ===",
    ]
    for row in forecast.get("candle_forecast") or []:
        lines.append(
            f"C+{row['candle']}: close ~{currency}{row['expected_close']:.4f} "
            f"[{currency}{row['expected_low']:.4f} – {currency}{row['expected_high']:.4f}] {row['bias']}"
        )
    lines.append(f"\nSummary: {forecast.get('next_candles_summary')}")
    lines.extend(["", "=== DRIVERS ==="] + (forecast.get("drivers") or []))
    return "\n".join(lines)


TB_FORECAST_AI_SYSTEM = """You are an expert quantitative analyst for Indian equities and crypto.
Given top/bottom scanner output and a quantitative probability model, refine probabilities for the NEXT 1-5 candles only.

Respond with VALID JSON ONLY (no markdown fences):
{
  "ath_cross_prob": <0-100 integer>,
  "atl_cross_prob": <0-100 integer>,
  "swing_high_break_prob": <0-100 integer>,
  "swing_low_break_prob": <0-100 integer>,
  "window_high_break_prob": <0-100 integer>,
  "window_low_break_prob": <0-100 integer>,
  "composite_confidence": <0-100 integer>,
  "next_1_to_5_candles": "<one paragraph plain English>",
  "candle_bias": ["UP|DOWN|FLAT", "UP|DOWN|FLAT", "UP|DOWN|FLAT", "UP|DOWN|FLAT", "UP|DOWN|FLAT"],
  "reasoning": "<2-4 sentences>"
}

Be conservative when signals conflict. ATH/ATL breaks in 5 candles are rare unless price is already within ~1 ATR."""


def _parse_forecast_ai_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def refine_forecast_with_ai(
    prompt: str,
    provider: str,
    model: str,
    api_key: str,
) -> tuple[dict | None, str]:
    """Call AI to refine probabilities. Returns (parsed_json, raw_text)."""
    if provider == "Custom / Other":
        return None, "Custom provider not supported."
    if not api_key:
        return None, api_key_env_hint(provider)

    try:
        if provider == "Groq (LLaMA)" and Groq:
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": TB_FORECAST_AI_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1200,
                temperature=0.15,
            )
            raw = resp.choices[0].message.content or ""
        elif provider == "Google Gemini":
            if GENAI_NEW:
                client = genai_new.Client(api_key=api_key)
                combined = TB_FORECAST_AI_SYSTEM + "\n\n" + prompt
                resp = client.models.generate_content(model=model, contents=combined)
                raw = resp.text or ""
            elif genai:
                genai.configure(api_key=api_key)
                gmodel = genai.GenerativeModel(model, system_instruction=TB_FORECAST_AI_SYSTEM)
                raw = gmodel.generate_content(prompt).text or ""
            else:
                return None, "Gemini library not installed."
        else:
            return None, "Unsupported provider."
        parsed = _parse_forecast_ai_json(raw)
        return parsed, raw
    except Exception as e:
        return None, f"AI error: {e}"


def merge_ai_forecast(quant: dict, ai: dict) -> dict:
    """Blend quant + AI probabilities (60% quant, 40% AI for stability)."""
    merged = dict(quant)
    if not ai:
        merged["ai_blended"] = False
        return merged

    prob_keys = [
        "ath_cross_prob", "atl_cross_prob",
        "swing_high_break_prob", "swing_low_break_prob",
        "window_high_break_prob", "window_low_break_prob",
        "composite_confidence",
    ]
    for k in prob_keys:
        qv = float(quant.get(k, 0) or 0)
        av = float(ai.get(k, qv) or qv)
        merged[k] = round(_clamp(qv * 0.6 + av * 0.4), 1)

    merged["next_candles_summary"] = ai.get("next_1_to_5_candles") or quant.get("next_candles_summary")
    merged["ai_reasoning"] = ai.get("reasoning", "")
    merged["ai_candle_bias"] = ai.get("candle_bias") or []
    merged["ai_blended"] = True
    merged["model"] = "quant_multi_factor_v1 + ai_blend"
    return merged


def _prob_bar_html(label: str, prob: float, color: str) -> str:
    p = _clamp(prob)
    return f"""
    <div style="margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;font-size:0.78rem;color:#94a3b8;margin-bottom:4px;">
            <span>{label}</span><span style="font-weight:700;color:{color};">{p:.0f}%</span>
        </div>
        <div style="background:#1e293b;border-radius:6px;height:8px;overflow:hidden;">
            <div style="width:{p}%;height:100%;background:{color};border-radius:6px;"></div>
        </div>
    </div>"""


def render_tb_forecast_panel(
    forecast: dict,
    currency: str,
    timeframe: str,
    *,
    show_reasons: bool = True,
) -> None:
    """Render breakout/breakdown confidence UI."""
    if not forecast:
        st.caption("Forecast unavailable.")
        return

    conf = forecast.get("composite_confidence", 0)
    conf_color = "#10b981" if conf >= 65 else "#f59e0b" if conf >= 45 else "#94a3b8"
    st.markdown(
        f"""
        <div style="background:#0f1729;border:1px solid #1e3a5f;border-left:4px solid {conf_color};
                    border-radius:12px;padding:16px 18px;margin:12px 0;">
            <div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;">Forecast Confidence</div>
            <div style="font-size:1.6rem;font-weight:700;color:{conf_color};">{conf:.0f}%</div>
            <div style="font-size:0.8rem;color:#94a3b8;margin-top:6px;">
                {forecast.get('next_candles_summary', '')}
            </div>
            <div style="font-size:0.68rem;color:#475569;margin-top:6px;">Model: {forecast.get('model', 'quant')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🎯 Upside break probabilities (next 1–5 candles)**")
        st.markdown(_prob_bar_html("Cross ATH", forecast.get("ath_cross_prob", 0), "#10b981"), unsafe_allow_html=True)
        st.markdown(_prob_bar_html("Break swing high", forecast.get("swing_high_break_prob", 0), "#34d399"), unsafe_allow_html=True)
        st.markdown(_prob_bar_html(f"Break {timeframe} window high", forecast.get("window_high_break_prob", 0), "#6ee7b7"), unsafe_allow_html=True)
    with c2:
        st.markdown("**🎯 Downside break probabilities (next 1–5 candles)**")
        st.markdown(_prob_bar_html("Cross ATL", forecast.get("atl_cross_prob", 0), "#ef4444"), unsafe_allow_html=True)
        st.markdown(_prob_bar_html("Break swing low", forecast.get("swing_low_break_prob", 0), "#f87171"), unsafe_allow_html=True)
        st.markdown(_prob_bar_html(f"Break {timeframe} window low", forecast.get("window_low_break_prob", 0), "#fca5a5"), unsafe_allow_html=True)

    levels = st.columns(4)
    levels[0].metric("ATH", f"{currency}{(forecast.get('ath') or 0):,.2f}" if forecast.get("ath") else "N/A")
    levels[1].metric("% below ATH", f"{forecast.get('gap_from_ath_pct', 0):.1f}%" if forecast.get("gap_from_ath_pct") is not None else "N/A")
    levels[2].metric("ATL", f"{currency}{(forecast.get('atl') or 0):,.2f}" if forecast.get("atl") else "N/A")
    levels[3].metric("% above ATL", f"{forecast.get('gap_from_atl_pct', 0):.1f}%" if forecast.get("gap_from_atl_pct") is not None else "N/A")

    swing = forecast.get("swing_structure") or {}
    st.caption(
        f"Swing high **{forecast.get('swing_high', 0):.2f}** · "
        f"Swing low **{forecast.get('swing_low', 0):.2f}** · "
        f"Structure: **{swing.get('structure_name', 'N/A')}** ({swing.get('high_label')}/{swing.get('low_label')})"
    )

    st.markdown("**📅 Next 1–5 candle projection**")
    rows = forecast.get("candle_forecast") or []
    ai_bias = forecast.get("ai_candle_bias") or []
    if rows:
        table = []
        for i, r in enumerate(rows):
            bias = ai_bias[i] if i < len(ai_bias) else r["bias"]
            table.append({
                "Candle": f"+{r['candle']}",
                "Expected close": f"{currency}{r['expected_close']:,.4f}",
                "Range": f"{currency}{r['expected_low']:,.4f} – {currency}{r['expected_high']:,.4f}",
                "Bias": bias,
            })
        st.dataframe(pd.DataFrame(table), hide_index=True, width='stretch')

    if forecast.get("ai_reasoning"):
        st.info(f"**AI refinement:** {forecast['ai_reasoning']}")

    if show_reasons and forecast.get("drivers"):
        with st.expander("🔬 Model drivers & factor detail", expanded=False):
            for d in forecast["drivers"]:
                st.markdown(f"- {d}")
            reasons = forecast.get("reasons") or {}
            for key, lbl in [
                ("ath", "ATH cross"), ("atl", "ATL cross"),
                ("swing_high", "Swing high"), ("swing_low", "Swing low"),
                ("window_high", "Window high"), ("window_low", "Window low"),
            ]:
                rlist = reasons.get(key) or []
                if rlist:
                    st.markdown(f"**{lbl}:**")
                    for line in rlist[:4]:
                        st.caption(f"· {line}")
