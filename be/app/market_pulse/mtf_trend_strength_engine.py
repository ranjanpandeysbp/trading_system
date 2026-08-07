"""
mtf_trend_strength_engine.py
------------------------------
MTF Trend & Strength — for one or more tickers across one or more
timeframes: trend DIRECTION, a composite trend-STRENGTH score (0-100, a
different axis from direction — a market can be strongly bullish, strongly
bearish, or strong-but-directionless/choppy), and a trend-REVERSAL
probability with a numeric %confidence.

Direction + the underlying multi-factor confluence read is NOT reimplemented
here — it reuses `mtf_scanner_engine.MTFAnalyzer`, this app's existing
institutional 7-component MTF scorer (Trend/Momentum/PriceAction/S-R/Volume/
Volatility/Structure), already proven and used elsewhere. What's genuinely
new in this module:

  1. A dedicated trend-STRENGTH score, blending ADX (is there a real trend at
     all), Kaufman's Efficiency Ratio (how directly price is moving vs.
     chopping — ADX alone can stay elevated for a while after a trend has
     already turned choppy, ER catches that), and the confluence engine's own
     directional conviction (distance of its composite score from neutral).
  2. A trend-REVERSAL probability — real multi-factor confluence (RSI
     divergence, momentum exhaustion, ADX rolling over from a peak, Bollinger
     Band extremes, proximity to a tested opposing support/resistance level,
     a reversal candlestick pattern at the extreme, a volume climax), each
     only contributing when it genuinely applies, with the reasons kept
     alongside the score so the number is auditable, not a black box.

Not a backtested edge — a structured, transparent framework combining
several well-established technical concepts. Research / education only, not
financial advice.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse import pro_trade_shared as pts
from app.market_pulse.indicators import add_adx
from app.market_pulse.mtf_scanner_engine import (
    MIN_BARS,
    TF_ORDER,
    TIMEFRAMES,
    MTFAnalyzer,
    build_confluence,
    fetch_mtf_data,
)
from app.market_pulse.price_action import detect_support_resistance
from app.trading_hubs.support_resistance_engine import (
    SupportResistanceConfig,
    detect_bollinger_mean_reversion,
    detect_candlestick_patterns,
    detect_rsi_divergence,
)

logger = logging.getLogger(__name__)

MTF_TIMEFRAME_OPTIONS: list[str] = list(TF_ORDER)

_STRENGTH_BUCKETS = [(70.0, "Very Strong"), (45.0, "Strong"), (22.0, "Moderate"), (0.0, "Weak")]

# Approximate closed bars per calendar day (used to size history for a date range).
_BARS_PER_DAY: dict[str, float] = {
    "1m": 390,
    "5m": 78,
    "15m": 26,
    "30m": 13,
    "1h": 7,
    "4h": 2,
    "1d": 1,
    "1wk": 0.2,
    "1w": 0.2,
    "1mo": 0.05,
}


def _align_ts(value: str | pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    tz = getattr(index, "tz", None)
    if tz is not None:
        if ts.tzinfo is None:
            return ts.tz_localize(tz)
        return ts.tz_convert(tz)
    if ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts


def _range_mask(index: pd.DatetimeIndex, from_date: str | None, to_date: str | None) -> pd.Series:
    mask = pd.Series(True, index=index)
    if from_date:
        mask &= index >= _align_ts(from_date, index)
    if to_date:
        end = _align_ts(to_date, index) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        mask &= index <= end
    return mask


def _limit_for_range(tf: str, from_date: str | None, to_date: str | None, default: int = 300) -> int:
    if not from_date and not to_date:
        return default
    end = pd.Timestamp(to_date) if to_date else pd.Timestamp.utcnow().tz_localize(None)
    start = pd.Timestamp(from_date) if from_date else end - pd.Timedelta(days=90)
    days = max(1, int((end.normalize() - start.normalize()).days) + 1)
    est = int(days * _BARS_PER_DAY.get(tf, 1.0)) + 80
    return int(min(max(est, 120), 2500))


def _downsample_indices(n: int, max_points: int) -> list[int]:
    if n <= 0:
        return []
    if n <= max_points:
        return list(range(n))
    step = n / float(max_points)
    idxs = sorted({min(n - 1, int(i * step)) for i in range(max_points)})
    if idxs[-1] != n - 1:
        idxs.append(n - 1)
    return idxs


def _trend_path_series(
    df: pd.DataFrame,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    max_points: int = 90,
) -> dict[str, Any]:
    """Lightweight signed trend path (−100..+100) over the selected date range.

    Uses EMA stack + ADX/ER so we can chart rising/falling trend without
    re-running the full MTFAnalyzer on every bar.
    """
    empty = {
        "trend_path": [],
        "trend_path_summary": {
            "direction": "insufficient",
            "delta_score": 0.0,
            "start_score": None,
            "end_score": None,
            "from_date": from_date,
            "to_date": to_date,
            "points": 0,
        },
    }
    if df is None or df.empty or len(df) < MIN_BARS:
        return empty

    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index)

    close = work["close"].astype(float)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    adx_df = add_adx(work.copy(), period=14)
    adx = adx_df["adx_14"].astype(float)
    plus_di = adx_df["plus_di_14"].astype(float)
    minus_di = adx_df["minus_di_14"].astype(float)
    er = pts.kaufman_efficiency_ratio(close, period=14).astype(float)

    bull = (ema9 > ema21) & (close > ema50)
    bear = (ema9 < ema21) & (close < ema50)
    sign = pd.Series(0.0, index=work.index)
    sign = sign.mask(bull, 1.0).mask(bear, -1.0)
    soft = pd.Series(np.where(plus_di >= minus_di, 0.5, -0.5), index=work.index)
    sign = sign.where(sign != 0.0, soft)

    adx_score = (adx / 50.0 * 100.0).clip(lower=0.0, upper=100.0)
    er_score = (er * 100.0).clip(lower=0.0, upper=100.0)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    di_conviction = ((plus_di - minus_di).abs() / di_sum * 100.0).fillna(0.0).clip(lower=0.0, upper=100.0)
    strength = (adx_score * 0.45 + er_score * 0.30 + di_conviction * 0.25).clip(lower=0.0, upper=100.0)
    trend_score = (sign * strength).clip(lower=-100.0, upper=100.0)

    mask = _range_mask(work.index, from_date, to_date)
    # Need indicator warmup; drop early NaNs inside the window.
    valid = mask & trend_score.notna() & strength.notna()
    idx = work.index[valid]
    if len(idx) == 0:
        return empty

    scores = trend_score.loc[idx]
    strengths = strength.loc[idx]
    dirs = sign.loc[idx]

    span_days = max(0, (idx[-1] - idx[0]).days) if len(idx) > 1 else 0
    use_date_only = span_days >= 14

    sample = _downsample_indices(len(idx), max_points)
    path: list[dict[str, Any]] = []
    for i in sample:
        ts = idx[i]
        sc = float(scores.iloc[i])
        st = float(strengths.iloc[i])
        d = float(dirs.iloc[i])
        if d > 0.25:
            direction = "up"
        elif d < -0.25:
            direction = "down"
        else:
            direction = "flat"
        try:
            label = ts.strftime("%Y-%m-%d") if use_date_only else ts.strftime("%m-%d %H:%M")
        except Exception:
            label = str(ts)
        path.append({
            "t": ts.isoformat(),
            "label": label,
            "trend_score": round(sc, 1),
            "strength": round(st, 1),
            "direction": direction,
        })

    third = max(1, len(scores) // 3)
    start_avg = float(scores.iloc[:third].mean())
    end_avg = float(scores.iloc[-third:].mean())
    delta = end_avg - start_avg
    if delta >= 8:
        path_dir = "increasing"
    elif delta <= -8:
        path_dir = "decreasing"
    else:
        path_dir = "sideways"

    return {
        "trend_path": path,
        "trend_path_summary": {
            "direction": path_dir,
            "delta_score": round(delta, 1),
            "start_score": round(float(scores.iloc[0]), 1),
            "end_score": round(float(scores.iloc[-1]), 1),
            "from_date": from_date or (idx[0].strftime("%Y-%m-%d") if len(idx) else None),
            "to_date": to_date or (idx[-1].strftime("%Y-%m-%d") if len(idx) else None),
            "points": len(path),
        },
    }


def _strength_label(score: float) -> str:
    for threshold, label in _STRENGTH_BUCKETS:
        if score >= threshold:
            return label
    return "Weak"


def _trend_strength(df: pd.DataFrame, composite: float) -> tuple[float, dict[str, float]]:
    """Composite 0-100 strength score — a different axis from direction. ADX
    (45%) and Efficiency Ratio (30%) both independently answer "is this a
    real trend or just chop"; the confluence engine's own directional
    conviction (25%) adds the broader multi-factor read so a brief ADX spike
    alone can't outrank genuine multi-signal alignment."""
    components: dict[str, float] = {}

    adx_val = 15.0
    try:
        adx_df = add_adx(df.copy(), period=14)
        series = adx_df["adx_14"].dropna()
        if not series.empty:
            adx_val = float(series.iloc[-1])
    except Exception:
        pass
    components["adx"] = round(adx_val, 1)

    er_val = 0.25
    try:
        er_series = pts.kaufman_efficiency_ratio(df["close"], period=14).dropna()
        if not er_series.empty:
            er_val = float(er_series.iloc[-1])
    except Exception:
        pass
    components["efficiency_ratio"] = round(er_val, 3)

    conviction = abs(composite - 50) * 2
    components["directional_conviction"] = round(conviction, 1)

    adx_score = min(100.0, adx_val / 50.0 * 100.0)
    er_score = er_val * 100.0
    strength = adx_score * 0.45 + er_score * 0.30 + conviction * 0.25
    return round(min(100.0, max(0.0, strength)), 1), components


def _reversal_probability(df: pd.DataFrame, direction: str) -> tuple[float, list[str]]:
    """Multi-factor reversal-risk score (5-90%). No single signal here is
    reliable on its own (that's exactly why a one-indicator system isn't
    institutional-grade) — several agreeing at once is a genuine warning the
    current trend is running out of room. Only scored against an already-
    established LONG/SHORT read; "reversal" isn't meaningful language for a
    market with no trend yet."""
    if direction not in ("LONG", "SHORT"):
        return 0.0, ["No established directional trend to reverse."]

    reasons: list[str] = []
    score = 15.0  # base "nothing lasts forever" floor

    close = df["close"]
    rsi_series = pts.rsi(close, 14)
    rsi_val = float(rsi_series.dropna().iloc[-1]) if not rsi_series.dropna().empty else None

    _, exhaustion_note = pts.momentum_exhaustion_note(rsi_val, direction)
    if exhaustion_note:
        score += 22
        reasons.append(exhaustion_note)

    cfg = SupportResistanceConfig()
    try:
        divergences = detect_rsi_divergence(df, rsi_series, cfg)
    except Exception:
        divergences = []
    opposing_div = "bearish" if direction == "LONG" else "bullish"
    for d in divergences:
        if d.get("direction") == opposing_div:
            score += 20
            reasons.append(d["note"])

    try:
        adx_s = add_adx(df.copy(), period=14)["adx_14"].dropna()
        if len(adx_s) >= 6:
            recent_peak = float(adx_s.iloc[-6:-1].max())
            current = float(adx_s.iloc[-1])
            if recent_peak >= 25 and current < recent_peak * 0.85:
                score += 15
                reasons.append(
                    f"ADX has rolled over from a recent peak of {recent_peak:.0f} to {current:.0f} — trend strength is fading."
                )
    except Exception:
        pass

    try:
        boll = detect_bollinger_mean_reversion(df)
    except Exception:
        boll = None
    if boll:
        agrees = (boll["signal"] == "bearish" and direction == "LONG") or (boll["signal"] == "bullish" and direction == "SHORT")
        if agrees:
            score += 15
            reasons.append(boll["note"])

    try:
        sr = detect_support_resistance(df)
    except Exception:
        sr = {}
    curr = float(close.iloc[-1])
    nearest = None
    side = ""
    if direction == "LONG":
        candidates = [r for r in (sr.get("resistances") or []) if r["price"] > curr]
        if candidates:
            nearest = min(candidates, key=lambda r: r["price"])
            side = "resistance"
    else:
        candidates = [s for s in (sr.get("supports") or []) if s["price"] < curr]
        if candidates:
            nearest = max(candidates, key=lambda s: s["price"])
            side = "support"
    if nearest is not None:
        dist_pct = abs(nearest["price"] - curr) / curr * 100 if curr else 100.0
        if dist_pct < 1.0 and nearest.get("touches", 0) >= 2:
            score += 15
            reasons.append(
                f"Price is within {dist_pct:.1f}% of a {side} level already tested {nearest['touches']}x at "
                f"{nearest['price']:,.4g} — a real ceiling/floor to react at."
            )

    try:
        patterns = detect_candlestick_patterns(df, lookback=3)
    except Exception:
        patterns = []
    opposing_pattern_dir = "bearish" if direction == "LONG" else "bullish"
    for p in patterns:
        if p.get("direction") == opposing_pattern_dir and p.get("bars_ago", 99) <= 1:
            score += 13
            when = "on the latest bar" if p["bars_ago"] == 0 else "1 bar ago"
            reasons.append(f"{p['name']} pattern {when} — {p['note']}.")

    try:
        vz = pts.volume_zscore(df["volume"], window=20).dropna()
        if not vz.empty and float(vz.iloc[-1]) >= 2.5:
            score += 10
            reasons.append(
                f"Volume climax on the latest bar ({float(vz.iloc[-1]):.1f}σ above its 20-bar average) — "
                "often marks exhaustion, not continuation."
            )
    except Exception:
        pass

    if not reasons:
        reasons.append("No reversal warning signs — the current trend shows no exhaustion, divergence, or rejection at a nearby level.")

    return round(min(90.0, max(5.0, score)), 1), reasons


def _plain_english(ticker: str, tf: str, direction: str, bias: str, strength_score: float, strength_label: str, reversal_pct: float) -> str:
    tf_label = TIMEFRAMES.get(tf, {}).get("label", tf)
    if direction not in ("LONG", "SHORT"):
        return (
            f"{ticker} on {tf_label} is {bias.lower()} — no clean directional trend right now "
            f"({strength_label.lower()} trend strength), so there's nothing to call a reversal on either."
        )
    verb = "an uptrend" if direction == "LONG" else "a downtrend"
    reversal_txt = (
        "with meaningful reversal risk building" if reversal_pct >= 55 else
        "with only mild reversal risk so far" if reversal_pct >= 30 else
        "with no significant reversal warning yet"
    )
    return (
        f"{ticker} on {tf_label} is in {verb} ({bias}) with {strength_label.lower()} trend strength "
        f"({strength_score:.0f}/100) — {reversal_txt} ({reversal_pct:.0f}% reversal probability)."
    )


def analyze_ticker_timeframe(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    fetch_limit = _limit_for_range(tf, from_date, to_date, default=limit)
    df = fetch_mtf_data(ticker, tf, market, groww_token, exchange, fetch_limit)
    if df.empty or len(df) < MIN_BARS:
        return {"ticker": ticker, "timeframe": tf, "error": f"Insufficient {tf} data for {ticker} ({len(df)} bars)."}

    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    # Snapshot as of to_date (inclusive); path uses the selected window with warmup history.
    df_asof = df
    if to_date:
        end = _align_ts(to_date, df.index) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df_asof = df[df.index <= end]
    if df_asof.empty or len(df_asof) < MIN_BARS:
        return {
            "ticker": ticker,
            "timeframe": tf,
            "error": f"Insufficient {tf} data for {ticker} in the selected date range ({len(df_asof)} bars).",
        }

    analyzer = MTFAnalyzer(df_asof)
    base = analyzer.to_dict(tf)
    composite = base["composite"]
    direction = base["direction"]

    strength_score, strength_components = _trend_strength(df_asof, composite)
    reversal_pct, reversal_reasons = _reversal_probability(df_asof, direction)
    strength_label = _strength_label(strength_score)
    path_payload = _trend_path_series(df, from_date=from_date, to_date=to_date)

    return {
        **base,
        "ticker": ticker,
        "from_date": from_date,
        "to_date": to_date,
        "strength_score": strength_score,
        "strength_label": strength_label,
        "strength_components": strength_components,
        "reversal_probability_pct": reversal_pct,
        "reversal_reasons": reversal_reasons,
        "plain_english": _plain_english(ticker, tf, direction, base["bias"], strength_score, strength_label, reversal_pct),
        **path_payload,
    }


def analyze_ticker(
    ticker: str,
    timeframes: list[str],
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    tf_results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for tf in timeframes:
        if tf not in TIMEFRAMES:
            continue
        result = analyze_ticker_timeframe(
            ticker, tf, market,
            groww_token=groww_token, exchange=exchange, limit=limit,
            from_date=from_date, to_date=to_date,
        )
        if result.get("error"):
            errors[tf] = result["error"]
        else:
            tf_results[tf] = result

    confluence = build_confluence(tf_results) if tf_results else {"verdict": "NO DATA"}

    elevated = [tf for tf, r in tf_results.items() if r.get("reversal_probability_pct", 0) >= 55]
    reversal_summary = (
        "Elevated reversal risk on " + ", ".join(TIMEFRAMES.get(tf, {}).get("label", tf) for tf in elevated) + "."
        if elevated else "No timeframe currently shows elevated reversal risk."
    )

    return {
        "ticker": ticker,
        "market": market,
        "from_date": from_date,
        "to_date": to_date,
        "timeframes": tf_results,
        "errors": errors,
        "confluence": confluence,
        "reversal_summary": reversal_summary,
        "elevated_reversal_timeframes": elevated,
    }


def scan_universe(
    tickers: list[str],
    timeframes: list[str],
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    results = {
        t: analyze_ticker(
            t, timeframes, market,
            groww_token=groww_token, exchange=exchange,
            from_date=from_date, to_date=to_date,
        )
        for t in tickers
    }
    return {"market": market, "from_date": from_date, "to_date": to_date, "results": results}
