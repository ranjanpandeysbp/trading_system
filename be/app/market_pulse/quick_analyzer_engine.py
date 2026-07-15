"""
quick_analyzer_engine.py
--------------------------
Command Center — Quick Analyzer (India, US, Crypto).

Combines:
- Momentum — Multi-Timeframe Strength & Direction (momentum_engine.py)
- EMA / SMA + oscillators (RSI, MACD, ADX, Stochastic, ROC, Williams %R) computed
  independently PER SELECTED TIMEFRAME from that timeframe's own OHLCV (indicators.py)
- Bollinger Bands, Fibonacci retracement, EMA crossover, VWAP, and Price Action
  (candlestick patterns) — also per selected timeframe, reusing price_action.py

...into one Long/Short/Neutral trade setup with a confidence % and, when a trade is
suggested, a %SL / %TP (ATR-based stop, fixed R:R target).

Dhan.co's technical-analysis snapshot is still fetched and shown separately as a
clearly-labeled daily-only cross-check reference (India tickers only — Dhan has no
US/crypto coverage), but does not feed the score, since that page exposes no
timeframe parameter at all.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.dhan_stock_engine import fetch_technical_analysis as fetch_dhan_daily_technical
from app.market_pulse.ema_position_engine import _warmup_start
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import (
    add_adx,
    add_atr,
    add_bollinger_bands,
    add_ema,
    add_macd,
    add_roc,
    add_rsi,
    add_sma,
    add_stochastic,
    add_vwap,
    add_williams_r,
)
from app.market_pulse.momentum_engine import (
    TIMEFRAME_OPTIONS,
    MomentumConfig,
    _aggregate,
    analyze_timeframe,
    classify_actionability,
)
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import (
    analyze_ema_crossovers,
    analyze_fibonacci,
    detect_candlestick_patterns,
    detect_support_resistance,
)

logger = logging.getLogger(__name__)

_GROWW_MARKET = "Groww (India Stocks)"
_EMA_PERIODS = (5, 10, 20, 50, 100, 200)
_TECH_MIN_BARS = 30

# (name substring, description) — matched in order, first hit wins. Covers both this
# engine's own indicator set and the extra ones Dhan's daily reference includes
# (ATR, STOCH RSI, UO) so both tables get a consistent explanation column.
_INDICATOR_DESCRIPTIONS: list[tuple[str, str]] = [
    ("RSI DIVERGENCE", "Price vs RSI disagreement between the last two swing points. Bullish = price made a lower low while RSI made a higher low (downside momentum fading — classic reversal-up signal). Bearish = price made a higher high while RSI made a lower high (upside momentum fading — classic reversal-down signal)."),
    ("MACD DIVERGENCE", "Price vs MACD line disagreement between the last two swing points — same bullish/bearish reversal logic as RSI divergence, confirmed on trend momentum instead of pure oscillator strength."),
    ("S/R BREAKOUT", "Price vs the nearest support/resistance level formed BEFORE the last few bars. Bullish = closed above prior resistance (breakout). Bearish = closed below prior support (breakdown). Neutral = still inside the prior range."),
    ("EMA CROSSOVER", "EMA stack across scalp (9/21), swing (20/50), and trend (50/200) pairs. Bullish when faster EMAs sit above slower ones, bearish when below, mixed otherwise."),
    ("STOCH RSI", "RSI run through the Stochastic formula — more sensitive than plain RSI. ≥80 overbought, ≤20 oversold."),
    ("STOCH", "Stochastic %K — where price sits within its recent high/low range. ≥80 overbought, ≤20 oversold."),
    ("RSI", "Momentum oscillator, 0-100. ≥70 = overbought (extended, pullback risk), ≤30 = oversold (stretched, bounce risk)."),
    ("MACD", "Trend-following momentum. Bullish when the MACD line is above its signal line, bearish when below."),
    ("ADX", "Trend strength (not direction). ≥25 = strong/tradeable trend, below = weak or range-bound — direction should come from other rows."),
    ("ATR", "Average True Range — typical bar-to-bar volatility in price units. Used here to size the stop-loss."),
    ("UO", "Ultimate Oscillator — blends short/medium/long-term momentum into one reading to reduce false signals."),
    ("ROC", "Rate of change — % price move over the lookback window. Positive = upward momentum, negative = downward."),
    ("WILLR", "Williams %R (inverse stochastic, -100 to 0). ≥-20 overbought, ≤-80 oversold."),
    ("BOLLINGER", "Volatility bands (2σ around a moving average). Above upper = overbought/extended, below lower = oversold/extended, above/below mid = bullish/bearish bias."),
    ("FIBONACCI", "50%-61.8% retracement of the latest auto-detected swing — a classic pullback entry zone. In-zone during an uptrend pullback reads bullish, during a downtrend rally reads bearish."),
    ("VWAP", "Volume-weighted average price. Price above VWAP favors buyers (institutional benchmark), below favors sellers."),
    ("PRICE ACTION", "The most CRITICAL candlestick pattern in the last 10 bars — a HIGH-reliability reversal pattern (engulfing, hammer, shooting star, marubozu) is preferred even over a more recent but lower-reliability one (e.g. a doji)."),
    ("-EMA", "Exponential moving average — price above is bullish for that lookback, below is bearish."),
    ("-SMA", "Simple moving average — price above is bullish for that lookback, below is bearish."),
]


def describe_indicator(name: str) -> str:
    """Best-effort one-line explanation for an indicator/strategy row, matched by name."""
    up = (name or "").upper()
    for key, desc in _INDICATOR_DESCRIPTIONS:
        if key in up:
            return desc
    return ""


_MOMENTUM_WEIGHT_ACTIONABLE = 2.0
_MOMENTUM_WEIGHT_WATCH = 1.0
_EMA_WEIGHT = 1.5
_INDICATOR_WEIGHT = 1.2
_DIRECTION_THRESHOLD = 1.8

_SL_ATR_MULT = 1.5
_RR_RATIO = 2.0


def _fetch_tf_ohlcv_range(
    ticker: str, timeframe: str, market: str, from_date: date, to_date: date,
    *, groww_token: str, exchange: str,
) -> pd.DataFrame:
    """OHLCV over [from_date, to_date] plus a warm-up buffer before from_date, so the
    largest EMA (200) is meaningful from the very start of the visible window/chart."""
    from backtesting.data_fetcher import get_historical_data

    warm_start = _warmup_start(from_date, timeframe, list(_EMA_PERIODS))
    df = get_historical_data(
        ticker, str(warm_start), str(to_date + timedelta(days=1)),
        market=market, timeframe=timeframe, groww_token=groww_token, groww_exchange=exchange,
    )
    return normalize_ohlcv(df)


def _fetch_tf_ohlcv(
    ticker: str, timeframe: str, market: str, cfg: MomentumConfig, *, groww_token: str, exchange: str,
    from_date: date | None = None, to_date: date | None = None,
) -> pd.DataFrame:
    if from_date and to_date:
        try:
            df = _fetch_tf_ohlcv_range(ticker, timeframe, market, from_date, to_date, groww_token=groww_token, exchange=exchange)
            if not df.empty and len(df) >= cfg.min_bars:
                return df
        except Exception as exc:
            logger.debug("Quick Analyzer date-range fetch failed for %s %s: %s", ticker, timeframe, exc)

    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=cfg.lookback_bars)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )
    return df


def _normalize_bias(raw: str | None) -> str:
    if not raw:
        return "Neutral"
    up = raw.strip().upper()
    if "BULL" in up:
        return "Bullish"
    if "BEAR" in up:
        return "Bearish"
    return "Neutral"


# ---------------------------------------------------------------------------
# Divergence detection (price vs oscillator) — RSI and MACD
# ---------------------------------------------------------------------------

def _swing_points_1d(values, window: int) -> tuple[list[int], list[int]]:
    """Swing-high / swing-low bar indices for a 1D array (local extrema over a
    symmetric window, same convention used for OHLC swing detection elsewhere)."""
    n = len(values)
    highs_idx: list[int] = []
    lows_idx: list[int] = []
    for i in range(window, n - window):
        seg = values[i - window : i + window + 1]
        if np.isnan(seg).all():
            continue
        if values[i] == np.nanmax(seg):
            highs_idx.append(i)
        if values[i] == np.nanmin(seg):
            lows_idx.append(i)
    return highs_idx, lows_idx


def _divergence_for(price, osc, *, window: int = 5, lookback: int = 60) -> dict[str, Any]:
    """Bullish/bearish divergence between price and one oscillator series, comparing
    the last two swing lows (bullish) / swing highs (bearish) within the lookback."""
    n = len(price)
    start = max(0, n - lookback)
    p = price[start:]
    o = osc[start:]
    highs_idx, lows_idx = _swing_points_1d(p, window)

    out: dict[str, Any] = {"bullish": None, "bearish": None}

    if len(lows_idx) >= 2:
        i1, i2 = lows_idx[-2], lows_idx[-1]
        if not (np.isnan(o[i1]) or np.isnan(o[i2])) and p[i2] < p[i1] and o[i2] > o[i1]:
            out["bullish"] = {
                "price_1": round(float(p[i1]), 4), "price_2": round(float(p[i2]), 4),
                "osc_1": round(float(o[i1]), 4), "osc_2": round(float(o[i2]), 4),
                "bars_ago": len(p) - 1 - i2,
            }

    if len(highs_idx) >= 2:
        i1, i2 = highs_idx[-2], highs_idx[-1]
        if not (np.isnan(o[i1]) or np.isnan(o[i2])) and p[i2] > p[i1] and o[i2] < o[i1]:
            out["bearish"] = {
                "price_1": round(float(p[i1]), 4), "price_2": round(float(p[i2]), 4),
                "osc_1": round(float(o[i1]), 4), "osc_2": round(float(o[i2]), 4),
                "bars_ago": len(p) - 1 - i2,
            }

    return out


def detect_divergences(work: pd.DataFrame, *, swing_window: int = 5, lookback: int = 60) -> dict[str, Any]:
    """RSI and MACD divergence vs price, each independently checked."""
    close = work["close"].values
    out: dict[str, Any] = {}
    if "rsi_14" in work.columns:
        out["rsi"] = _divergence_for(close, work["rsi_14"].values, window=swing_window, lookback=lookback)
    if "macd_12_26" in work.columns:
        out["macd"] = _divergence_for(close, work["macd_12_26"].values, window=swing_window, lookback=lookback)
    return out


# ---------------------------------------------------------------------------
# Support/Resistance breakout / breakdown
# ---------------------------------------------------------------------------

def detect_breakout_breakdown(df: pd.DataFrame, *, window: int = 5, num_levels: int = 3, breakout_lookback: int = 5) -> dict[str, Any]:
    """Support/Resistance levels formed BEFORE the trailing `breakout_lookback` bars,
    then checked against the latest close for a breakout (above prior resistance) or
    breakdown (below prior support)."""
    if df.empty or len(df) < window * 2 + 1 + breakout_lookback:
        return {"event": "NONE", "supports": [], "resistances": []}

    prior = df.iloc[:-breakout_lookback] if breakout_lookback > 0 else df
    sr = detect_support_resistance(prior, window=window, num_levels=num_levels)
    supports = sr.get("supports") or []
    resistances = sr.get("resistances") or []

    latest_close = float(df["close"].iloc[-1])
    latest_vol = float(df["volume"].iloc[-1]) if "volume" in df.columns else None
    avg_vol = float(df["volume"].tail(20).mean()) if "volume" in df.columns and len(df) >= 20 else None
    vol_confirmed = bool(latest_vol and avg_vol and latest_vol >= avg_vol * 1.15)

    event = "NONE"
    level = None
    # Prior supports/resistances are relative to the PRIOR window's last price, so a level
    # the current close has since moved beyond is exactly a breakout/breakdown candidate.
    broken_resistances = [r for r in resistances if latest_close > r["price"]]
    broken_supports = [s for s in supports if latest_close < s["price"]]

    if broken_resistances:
        level = max(broken_resistances, key=lambda r: r["price"])
        event = "RESISTANCE_BREAKOUT"
    elif broken_supports:
        level = min(broken_supports, key=lambda s: s["price"])
        event = "SUPPORT_BREAKDOWN"

    return {
        "event": event,
        "level": level,
        "volume_confirmed": vol_confirmed,
        "supports": supports,
        "resistances": resistances,
    }


def compute_technical_snapshot(df_raw: pd.DataFrame, min_bars: int = _TECH_MIN_BARS) -> dict[str, Any] | None:
    """EMA/SMA + oscillators + Bollinger/Fibonacci/EMA-crossover/VWAP/Price-Action, all
    computed on THIS timeframe's own OHLCV — Bullish/Bearish/Neutral tags mirror Dhan's
    own convention (price vs MA, MACD vs signal, ADX threshold, etc.)."""
    df = normalize_ohlcv(df_raw)
    if df.empty or len(df) < min_bars:
        return None

    work = df.copy()
    for p in _EMA_PERIODS:
        work = add_ema(work, p)
        work = add_sma(work, p)
    work = add_rsi(work, 14)
    work = add_stochastic(work, 9, 6)
    work = add_macd(work, 12, 26, 9)
    work = add_adx(work, 14)
    work = add_roc(work, 12)
    work = add_williams_r(work, 14)
    work = add_atr(work, 14)
    work = add_bollinger_bands(work, 20, 2.0)
    try:
        work = add_vwap(work)
    except Exception as exc:
        logger.debug("VWAP calc failed: %s", exc)

    row = work.iloc[-1]
    price = float(row["close"])

    def _v(col: str) -> float | None:
        val = row.get(col)
        return None if val is None or pd.isna(val) else float(val)

    ema_rows = []
    for p in _EMA_PERIODS:
        val = _v(f"ema_{p}")
        if val is None:
            continue
        ema_rows.append({"indicator": f"{p}-EMA", "value": round(val, 4), "action": "Bullish" if price > val else "Bearish"})

    sma_rows = []
    for p in _EMA_PERIODS:
        val = _v(f"sma_{p}")
        if val is None:
            continue
        sma_rows.append({"indicator": f"{p}-SMA", "value": round(val, 4), "action": "Bullish" if price > val else "Bearish"})

    rsi = _v("rsi_14")
    rsi_action = "Neutral" if rsi is None else ("Overbought" if rsi >= 70 else "Oversold" if rsi <= 30 else "Neutral")

    stoch_k = _v("stoch_k_9")
    stoch_action = "Neutral" if stoch_k is None else ("Overbought" if stoch_k >= 80 else "Oversold" if stoch_k <= 20 else "Neutral")

    macd = _v("macd_12_26")
    macd_signal = _v("macd_signal_12_26_9")
    macd_action = "Neutral" if macd is None or macd_signal is None else ("Bullish" if macd > macd_signal else "Bearish")

    adx = _v("adx_14")
    adx_action = "Neutral" if adx is None else ("Strong Trend" if adx >= 25 else "Weak Trend")

    roc = _v("roc_12")
    roc_action = "Neutral" if roc is None else ("Uptrend" if roc > 0 else "Downtrend" if roc < 0 else "Neutral")

    willr = _v("williams_r_14")
    willr_action = "Neutral" if willr is None else ("Overbought" if willr >= -20 else "Oversold" if willr <= -80 else "Neutral")

    atr = _v("atr_14")

    # ── Bollinger Bands (20, 2.0) ──
    bb_upper = _v("bb_upper_20_2.0")
    bb_mid = _v("bb_middle_20_2.0")
    bb_lower = _v("bb_lower_20_2.0")
    bb_detail = None
    bb_action = "Neutral"
    if bb_upper is not None and bb_lower is not None and bb_mid is not None:
        bandwidth_pct = round((bb_upper - bb_lower) / bb_mid * 100, 2) if bb_mid else None
        if price > bb_upper:
            bb_position, bb_action = "Above Upper Band", "Overbought"
        elif price < bb_lower:
            bb_position, bb_action = "Below Lower Band", "Oversold"
        elif price > bb_mid:
            bb_position, bb_action = "Above Mid (Bullish)", "Bullish"
        else:
            bb_position, bb_action = "Below Mid (Bearish)", "Bearish"
        bb_detail = {
            "upper": round(bb_upper, 4), "mid": round(bb_mid, 4), "lower": round(bb_lower, 4),
            "bandwidth_pct": bandwidth_pct, "position": bb_position,
        }

    # ── Fibonacci retracement (auto swing high/low, 100-bar lookback) ──
    fib = analyze_fibonacci(df, lookback=min(100, len(df)))
    fib_action = "Neutral"
    if fib.get("price_in_golden_zone"):
        # direction "DOWN" = retracing down from a swing high (uptrend pullback) -> buy zone
        # direction "UP" = retracing up from a swing low (downtrend pullback) -> sell zone
        fib_action = "Bullish" if fib.get("direction") == "DOWN" else "Bearish"

    # ── EMA crossover strategy (9/21 scalp, 20/50 swing, 50/200 trend) ──
    ema_cross = analyze_ema_crossovers(df)
    ema_cross_action = _normalize_bias(ema_cross.get("ema_stack"))
    recent_cross = next(iter(sorted(ema_cross.get("crossovers") or [], key=lambda c: c.get("bars_ago", 999))), None)

    # ── VWAP ──
    vwap_val = _v("vwap")
    vwap_action = "Neutral" if vwap_val is None else ("Bullish" if price > vwap_val else "Bearish")

    # ── Price action (CRITICAL candlestick pattern) — a HIGH-reliability reversal
    # pattern is preferred even over a more recent but lower-reliability one. ──
    patterns = detect_candlestick_patterns(df)
    critical_patterns = [p for p in patterns if p.get("reliability") == "HIGH"]
    pattern_pool = critical_patterns if critical_patterns else patterns
    latest_pattern = min(pattern_pool, key=lambda p: p.get("bars_ago", 999)) if pattern_pool else None
    pa_action = _normalize_bias(latest_pattern.get("bias")) if latest_pattern else "Neutral"

    # ── Divergence: RSI and MACD vs price, last two swing points ──
    divergences = detect_divergences(work)
    rsi_div = divergences.get("rsi") or {}
    macd_div = divergences.get("macd") or {}

    def _div_action(div: dict) -> tuple[str, str]:
        if div.get("bullish"):
            b = div["bullish"]
            return "Bullish", f"Lower low {b['price_1']:,.4g}→{b['price_2']:,.4g}, higher low {b['osc_1']:.1f}→{b['osc_2']:.1f}"
        if div.get("bearish"):
            b = div["bearish"]
            return "Bearish", f"Higher high {b['price_1']:,.4g}→{b['price_2']:,.4g}, lower high {b['osc_1']:.1f}→{b['osc_2']:.1f}"
        return "Neutral", "No divergence in the lookback window"

    rsi_div_action, rsi_div_detail = _div_action(rsi_div)
    macd_div_action, macd_div_detail = _div_action(macd_div)

    # ── Support/Resistance breakout / breakdown ──
    breakout = detect_breakout_breakdown(df)
    if breakout["event"] == "RESISTANCE_BREAKOUT":
        breakout_action = "Bullish"
        lvl = breakout["level"]["price"] if breakout.get("level") else None
        breakout_value = f"Breakout above {lvl:,.4g}" if lvl is not None else "Breakout"
        if breakout.get("volume_confirmed"):
            breakout_value += " (volume confirmed)"
    elif breakout["event"] == "SUPPORT_BREAKDOWN":
        breakout_action = "Bearish"
        lvl = breakout["level"]["price"] if breakout.get("level") else None
        breakout_value = f"Breakdown below {lvl:,.4g}" if lvl is not None else "Breakdown"
        if breakout.get("volume_confirmed"):
            breakout_value += " (volume confirmed)"
    else:
        breakout_action = "Neutral"
        breakout_value = "Inside prior range"

    indicator_rows = [
        {"indicator": "RSI(14)", "value": round(rsi, 2) if rsi is not None else None, "action": rsi_action},
        {"indicator": "STOCH(9,6)", "value": round(stoch_k, 2) if stoch_k is not None else None, "action": stoch_action},
        {"indicator": "MACD(12,26)", "value": round(macd, 4) if macd is not None else None, "action": macd_action},
        {"indicator": "ADX(14)", "value": round(adx, 2) if adx is not None else None, "action": adx_action},
        {"indicator": "ROC(12)", "value": round(roc, 2) if roc is not None else None, "action": roc_action},
        {"indicator": "WillR(14)", "value": round(willr, 2) if willr is not None else None, "action": willr_action},
        {
            "indicator": "Bollinger Bands(20,2)",
            "value": bb_detail["position"] if bb_detail else None,
            "action": bb_action,
        },
        {
            "indicator": "Fibonacci Golden Zone",
            "value": ("In zone" if fib.get("price_in_golden_zone") else "Outside zone") if fib.get("swing_high") else None,
            "action": fib_action,
        },
        {
            "indicator": "EMA Crossover (9/21/50/200)",
            "value": ema_cross.get("ema_stack"),
            "action": ema_cross_action,
        },
        {
            "indicator": "VWAP",
            "value": round(vwap_val, 4) if vwap_val is not None else None,
            "action": vwap_action,
        },
        {
            "indicator": "Price Action",
            "value": latest_pattern.get("name") if latest_pattern else "No pattern",
            "action": pa_action,
            "description": (latest_pattern.get("description") if latest_pattern
                             else describe_indicator("Price Action")),
        },
        {"indicator": "RSI Divergence", "value": rsi_div_detail, "action": rsi_div_action},
        {"indicator": "MACD Divergence", "value": macd_div_detail, "action": macd_div_action},
        {"indicator": "S/R Breakout/Breakdown", "value": breakout_value, "action": breakout_action},
    ]
    for row in indicator_rows:
        row.setdefault("description", describe_indicator(row["indicator"]))

    return {
        "price": round(price, 4),
        "atr": round(atr, 4) if atr is not None else None,
        "ema": ema_rows,
        "sma": sma_rows,
        "indicators": indicator_rows,
        "strategies": {
            "bollinger": bb_detail,
            "fibonacci": fib,
            "ema_crossover": {"stack": ema_cross.get("ema_stack"), "recent_cross": recent_cross},
            "vwap": vwap_val,
            "price_action": latest_pattern,
            "divergence": {"rsi": rsi_div, "macd": macd_div},
            "breakout": breakout,
        },
    }


def _ema_indicator_tally(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    bull = sum(1 for r in rows if r.get("action") == "Bullish")
    bear = sum(1 for r in rows if r.get("action") == "Bearish")
    return bull, bear, len(rows)


def _finest_timeframe(timeframes: list[str]) -> str | None:
    if not timeframes:
        return None
    order = {tf: i for i, tf in enumerate(TIMEFRAME_OPTIONS)}
    return min(timeframes, key=lambda tf: order.get(tf, 999))


def classify_quick_setup(
    momentum: dict[str, Any],
    technical_by_tf: dict[str, dict[str, Any]],
    *,
    entry_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine momentum + per-timeframe EMA/Technical-Indicator/strategy reads into
    LONG/SHORT/NEUTRAL + confidence %, with an ATR-based %SL / %TP when a trade fires."""
    reasons: list[str] = []
    score = 0.0

    action = momentum.get("actionability") or {}
    m_dir = action.get("direction")
    m_bucket = action.get("bucket")
    overall_dir = momentum.get("overall_direction", "NO_DATA")

    if m_dir in ("LONG", "SHORT"):
        weight = _MOMENTUM_WEIGHT_ACTIONABLE if m_bucket == "ACTIONABLE" else _MOMENTUM_WEIGHT_WATCH
        score += weight if m_dir == "LONG" else -weight
        reasons.append(f"Momentum: {overall_dir} trend ({m_bucket}) — {action.get('reason', '')}")
    else:
        reasons.append(f"Momentum: {overall_dir} — no clear directional edge across the selected timeframes")

    ema_bull = ema_bear = ema_total = 0
    ind_bull = ind_bear = ind_total = 0
    for snap in (technical_by_tf or {}).values():
        b, s, t = _ema_indicator_tally(snap.get("ema") or [])
        ema_bull += b
        ema_bear += s
        ema_total += t
        b2, s2, t2 = _ema_indicator_tally(snap.get("indicators") or [])
        ind_bull += b2
        ind_bear += s2
        ind_total += t2

    n_tf = len(technical_by_tf or {})
    if ema_total:
        ema_component = (ema_bull - ema_bear) / ema_total
        score += ema_component * _EMA_WEIGHT
        reasons.append(f"EMA stack across {n_tf} timeframe(s): {ema_bull} bullish / {ema_bear} bearish of {ema_total}")
    if ind_bull or ind_bear:
        ind_component = (ind_bull - ind_bear) / max(ind_bull + ind_bear, 1)
        score += ind_component * _INDICATOR_WEIGHT
        reasons.append(
            f"Indicators + Bollinger/Fibonacci/EMA-crossover/VWAP/Price-Action/Divergence/S-R-Breakout across "
            f"{n_tf} timeframe(s): {ind_bull} bullish / {ind_bear} bearish of {ind_total} scored"
        )
    if not technical_by_tf:
        reasons.append("EMA/Technical Indicators unavailable — insufficient OHLCV to compute on the selected timeframe(s)")

    # Call out any confirmed divergence or S/R breakout by name — these are higher-value,
    # lower-frequency signals worth surfacing explicitly rather than only as a vote count.
    for tf, snap in (technical_by_tf or {}).items():
        strat = snap.get("strategies") or {}
        div = strat.get("divergence") or {}
        for osc_name, d in div.items():
            if d.get("bullish"):
                reasons.append(f"[{tf}] Bullish {osc_name.upper()} divergence — {d['bullish']['bars_ago']} bar(s) ago")
            if d.get("bearish"):
                reasons.append(f"[{tf}] Bearish {osc_name.upper()} divergence — {d['bearish']['bars_ago']} bar(s) ago")
        bo = strat.get("breakout") or {}
        if bo.get("event") == "RESISTANCE_BREAKOUT":
            lvl = bo["level"]["price"] if bo.get("level") else None
            reasons.append(f"[{tf}] Resistance breakout above {lvl:,.4g}" if lvl is not None else f"[{tf}] Resistance breakout")
        elif bo.get("event") == "SUPPORT_BREAKDOWN":
            lvl = bo["level"]["price"] if bo.get("level") else None
            reasons.append(f"[{tf}] Support breakdown below {lvl:,.4g}" if lvl is not None else f"[{tf}] Support breakdown")

    if score >= _DIRECTION_THRESHOLD:
        direction = "LONG"
    elif score <= -_DIRECTION_THRESHOLD:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    confidence = round(min(95.0, max(30.0, 50.0 + abs(score) * 12.0)), 1)
    if direction == "NEUTRAL":
        confidence = round(min(confidence, 55.0), 1)

    sl_pct = tp_pct = None
    if direction in ("LONG", "SHORT") and entry_snapshot:
        atr = entry_snapshot.get("atr")
        price = entry_snapshot.get("price")
        if atr and price:
            sl_pct = round(min(8.0, max(0.3, atr * _SL_ATR_MULT / price * 100)), 2)
            tp_pct = round(sl_pct * _RR_RATIO, 2)
            reasons.append(f"Stop {sl_pct}% (ATR×{_SL_ATR_MULT} on the finest selected timeframe) · Target {tp_pct}% (1:{_RR_RATIO:.0f} R:R)")

    return {
        "direction": direction,
        "confidence_pct": confidence,
        "score": round(score, 2),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "ema_bullish": ema_bull, "ema_bearish": ema_bear, "ema_total": ema_total,
        "indicator_bullish": ind_bull, "indicator_bearish": ind_bear, "indicator_total": ind_total,
        "reasons": reasons,
    }


def analyze_quick(
    ticker: str,
    timeframes: list[str],
    market: str = _GROWW_MARKET,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    """One ticker (India/US/Crypto): per-timeframe momentum + per-timeframe EMA/Indicators/
    strategies -> combined setup. The Dhan.co daily reference only applies to India tickers
    (Dhan has no US/crypto coverage). When from_date/to_date are given, OHLCV is fetched for
    that date range (plus a warm-up buffer) instead of a fixed bar-count lookback."""
    cfg = MomentumConfig(timeframes=timeframes)
    per_tf_momentum: list[dict[str, Any]] = []
    technical_by_tf: dict[str, dict[str, Any]] = {}

    for tf in timeframes:
        try:
            df = _fetch_tf_ohlcv(
                ticker, tf, market, cfg, groww_token=groww_token, exchange=exchange,
                from_date=from_date, to_date=to_date,
            )
        except Exception as exc:
            logger.debug("Quick Analyzer OHLCV fetch failed for %s %s: %s", ticker, tf, exc)
            continue

        try:
            mom = analyze_timeframe(df, tf, cfg)
            if mom:
                per_tf_momentum.append(mom)
        except Exception as exc:
            logger.debug("Momentum failed for %s %s: %s", ticker, tf, exc)

        try:
            snap = compute_technical_snapshot(df)
            if snap:
                technical_by_tf[tf] = snap
        except Exception as exc:
            logger.debug("Technical snapshot failed for %s %s: %s", ticker, tf, exc)

    if not per_tf_momentum:
        return {"ticker": ticker, "error": f"Insufficient data across {', '.join(timeframes)}."}

    agg = _aggregate(per_tf_momentum)
    actionability = classify_actionability(agg)
    momentum = {
        "ticker": ticker, "market": market, "timeframes": timeframes,
        "per_tf": per_tf_momentum, "actionability": actionability, **agg,
    }

    finest_tf = _finest_timeframe(list(technical_by_tf.keys()))
    entry_snapshot = technical_by_tf.get(finest_tf) if finest_tf else None

    setup = classify_quick_setup(momentum, technical_by_tf, entry_snapshot=entry_snapshot)
    daily_reference = fetch_dhan_daily_technical(ticker) if market == _GROWW_MARKET else None

    return {
        "ticker": ticker,
        "market": market,
        "timeframes": timeframes,
        "from_date": from_date,
        "to_date": to_date,
        "momentum": momentum,
        "technical_by_tf": technical_by_tf,
        "daily_reference": daily_reference,
        "setup": setup,
    }


def analyze_quick_many(
    tickers: list[str],
    timeframes: list[str],
    market: str = _GROWW_MARKET,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            results.append(analyze_quick(
                ticker, timeframes, market, groww_token=groww_token, exchange=exchange,
                from_date=from_date, to_date=to_date,
            ))
        except Exception as exc:
            logger.debug("Quick Analyzer failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "error": str(exc)[:200]})
    return results


def apply_combined_signals_to_quick_results(
    results: list[dict[str, Any]],
    market: str,
    *,
    include_fundamentals: bool = False,
    include_option_chain: bool = False,
    groww_token: str = "",
) -> None:
    """Combine each result's technical setup direction/confidence with Fundamental
    Analysis and/or Option Chain PCR/max-pain/OI bias for the same ticker, in place —
    Groww (India) only. Mirrors the original app's checkbox behaviour: fundamentals
    are combined first, then option chain chains on top of that combined read. Stashes
    the pre-combination technical-only direction/confidence before overwriting."""
    if not (include_fundamentals or include_option_chain):
        return
    from app.market_pulse.fundamentals_combine import combine_with_fundamentals, is_groww_india_market

    if not is_groww_india_market(market):
        return
    from app.market_pulse.option_chain_combine import combine_with_option_chain

    for r in results:
        setup = r.get("setup")
        if not setup or r.get("error"):
            continue
        direction = setup.get("direction")
        confidence = setup.get("confidence_pct") or 0.0
        setup["technical_direction"] = direction
        setup["technical_confidence_pct"] = confidence

        if include_fundamentals:
            combo = combine_with_fundamentals(r["ticker"], direction, confidence)
            r["fundamentals_combo"] = combo
            direction = combo["combined_direction"]
            confidence = combo["combined_confidence_pct"]

        if include_option_chain:
            combo = combine_with_option_chain(r["ticker"], direction, confidence, groww_token=groww_token)
            r["option_chain_combo"] = combo
            direction = combo["combined_direction"]
            confidence = combo["combined_confidence_pct"]

        setup["direction"] = direction
        setup["confidence_pct"] = confidence
