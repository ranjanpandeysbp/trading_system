"""
momentum_engine.py
-------------------
Multi-timeframe momentum scanner — trend, strength (strong/medium/weak),
direction-of-change (increasing/decreasing), and consolidation/breakout odds
for one or more tickers (India / US / Crypto).

Strength comes from ADX (the standard trend-strength indicator, direction-agnostic
by construction); direction-of-change comes from ADX's own slope (rising ADX =
strengthening trend, falling ADX = weakening, regardless of which way price is
going); trend direction comes from EMA stacking + MACD; RSI/ROC/volume feed the
continuation-confidence and breakout-odds scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_adx, add_bollinger_bands, add_ema, add_macd, add_roc, add_rsi, add_vol_sma
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

logger = logging.getLogger(__name__)

TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
DEFAULT_TIMEFRAMES = ["15m", "1h", "4h", "1d"]
# Higher timeframes carry more weight when aggregating direction/confidence across TFs.
_TF_WEIGHT = {
    "1m": 0.3, "5m": 0.6, "15m": 1.0, "30m": 1.25, "1h": 1.5, "4h": 2.0, "1d": 3.0, "1w": 4.0,
}

_ADX_STRONG = 25.0
_ADX_MEDIUM = 18.0
_ADX_SLOPE_FLAT = 1.5  # |delta ADX| below this over slope_lookback bars = STABLE

_EMA_FAST = 8
_EMA_MID = 21
_EMA_SLOW = 50
_BB_WIDTH_LOOKBACK = 100
_BB_WIDTH_CONSOLIDATION_PCTILE = 0.30
_SR_LOOKBACK = 20  # prior N bars (excluding current) used as the resistance/support reference
_BREAKOUT_VOL_CONFIRM = 1.15  # volume ratio above which a fresh S/R break is "volume confirmed"


@dataclass
class MomentumConfig:
    timeframes: list[str] = field(default_factory=lambda: list(DEFAULT_TIMEFRAMES))
    lookback_bars: int = 300
    min_bars: int = 60
    slope_lookback: int = 5


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work = add_ema(work, _EMA_FAST)
    work = add_ema(work, _EMA_MID)
    work = add_ema(work, _EMA_SLOW)
    work = add_rsi(work, 14)
    work = add_macd(work)
    work = add_adx(work, 14)
    work = add_roc(work, 10)
    work = add_bollinger_bands(work, 20, 2.0)
    work = add_vol_sma(work, 20)
    bb_upper = work["bb_upper_20_2.0"]
    bb_lower = work["bb_lower_20_2.0"]
    bb_mid = work["bb_middle_20_2.0"].replace(0, np.nan)
    work["bb_width_pct"] = (bb_upper - bb_lower) / bb_mid * 100
    # Prior-N-bar high/low (current bar excluded) — the resistance/support level a fresh
    # close can "break" through.
    work["prior_res"] = work["high"].shift(1).rolling(_SR_LOOKBACK).max()
    work["prior_sup"] = work["low"].shift(1).rolling(_SR_LOOKBACK).min()
    return work


def _rsi_zone(rsi: float) -> str:
    if pd.isna(rsi):
        return "—"
    if rsi >= 80:
        return "Extended overbought"
    if rsi >= 70:
        return "Overbought"
    if rsi >= 55:
        return "Bullish"
    if rsi >= 45:
        return "Neutral"
    if rsi >= 30:
        return "Bearish"
    if rsi >= 20:
        return "Oversold"
    return "Extended oversold"


def _trend_direction(row: pd.Series) -> str:
    fast, mid, slow = row.get(f"ema_{_EMA_FAST}"), row.get(f"ema_{_EMA_MID}"), row.get(f"ema_{_EMA_SLOW}")
    price = row.get("close")
    if any(pd.isna(v) for v in (fast, mid, slow, price)):
        return "FLAT"
    if price > fast > mid > slow:
        return "UP"
    if price < fast < mid < slow:
        return "DOWN"
    return "FLAT"


def _strength_label(adx: float) -> str:
    if pd.isna(adx):
        return "WEAK"
    if adx >= _ADX_STRONG:
        return "STRONG"
    if adx >= _ADX_MEDIUM:
        return "MEDIUM"
    return "WEAK"


def _is_consolidating(work: pd.DataFrame, adx: float) -> bool:
    if pd.isna(adx) or adx >= _ADX_MEDIUM:
        return False
    widths = work["bb_width_pct"].dropna()
    if len(widths) < 20:
        return False
    recent = widths.tail(_BB_WIDTH_LOOKBACK)
    current = widths.iloc[-1]
    pctile = (recent < current).mean()
    return pctile <= _BB_WIDTH_CONSOLIDATION_PCTILE


def analyze_timeframe(df_raw: pd.DataFrame, timeframe: str, cfg: MomentumConfig) -> dict[str, Any] | None:
    df = normalize_ohlcv(df_raw)
    if df.empty or len(df) < cfg.min_bars:
        return None
    work = _compute_indicators(df)
    row = work.iloc[-1]
    lb = min(cfg.slope_lookback, len(work) - 1)
    prior = work.iloc[-1 - lb]

    price = float(row["close"])
    adx = float(row.get("adx_14", np.nan))
    adx_prior = float(prior.get("adx_14", np.nan))
    rsi = float(row.get("rsi_14", np.nan))
    macd_hist = float(row.get("macd_hist_12_26_9", 0.0) or 0.0)
    roc = float(row.get("roc_10", 0.0) or 0.0)
    vol_ratio = float(row.get("vol_ratio_20", 1.0) or 1.0)

    trend = _trend_direction(row)
    strength = _strength_label(adx)
    consolidating = _is_consolidating(work, adx)
    # A "FLAT" EMA-stack read (no BB-width squeeze, just no clean directional
    # stack) is functionally the same no-clear-direction case as a BB-width
    # CONSOLIDATING read — both should get the same breakout-lean odds below
    # rather than leaving FLAT with no probability at all.
    no_clear_direction = consolidating or trend == "FLAT"
    if no_clear_direction:
        trend = "CONSOLIDATING"

    adx_delta = adx - adx_prior if not (pd.isna(adx) or pd.isna(adx_prior)) else 0.0
    if adx_delta > _ADX_SLOPE_FLAT:
        momentum_change = "INCREASING"
    elif adx_delta < -_ADX_SLOPE_FLAT:
        momentum_change = "DECREASING"
    else:
        momentum_change = "STABLE"

    reasons: list[str] = [
        f"ADX(14) {adx:.1f} ({strength.lower()} trend, {'rising' if adx_delta > 0 else 'falling' if adx_delta < 0 else 'flat'} "
        f"{adx_delta:+.1f} over {lb} bars)",
        f"EMA stack {_EMA_FAST}/{_EMA_MID}/{_EMA_SLOW}: {'bullish' if trend == 'UP' else 'bearish' if trend == 'DOWN' else 'mixed/flat'}",
        f"RSI(14) {rsi:.1f} — {_rsi_zone(rsi)}",
        f"MACD histogram {macd_hist:+.3g} ({'bullish' if macd_hist > 0 else 'bearish' if macd_hist < 0 else 'flat'})",
        f"ROC(10) {roc:+.2f}% · Volume {vol_ratio:.2f}x avg",
    ]

    breakout_up_pct = breakout_down_pct = None
    confidence_continue_pct = None

    if no_clear_direction:
        bb_upper = float(row.get("bb_upper_20_2.0", np.nan))
        bb_lower = float(row.get("bb_lower_20_2.0", np.nan))
        pos = 0.5
        if not (pd.isna(bb_upper) or pd.isna(bb_lower)) and bb_upper > bb_lower:
            pos = (price - bb_lower) / (bb_upper - bb_lower)
        up_score = 50.0
        up_score += (pos - 0.5) * 60
        up_score += (rsi - 50.0) * 0.4 if not pd.isna(rsi) else 0
        up_score += np.sign(macd_hist) * min(abs(macd_hist), 3.0) * 3
        up_score += (vol_ratio - 1.0) * 5 * (1 if pos >= 0.5 else -1)
        up_score = max(10.0, min(90.0, up_score))
        breakout_up_pct = round(up_score, 1)
        breakout_down_pct = round(100.0 - up_score, 1)
        reasons.append(
            f"Range position {pos * 100:.0f}% of Bollinger band · "
            f"breakout lean {'up' if up_score >= 50 else 'down'}"
        )
    else:
        conf = 50.0
        conf += min(25.0, max(0.0, (adx - _ADX_MEDIUM)) * 1.2)
        if trend == "UP":
            conf += 10 if macd_hist > 0 else -8
            if rsi >= 80:
                conf -= 12
                reasons.append("RSI extended overbought — pullback risk elevated")
            elif rsi < 45:
                conf -= 8
            if vol_ratio >= 1.1:
                conf += 6
        elif trend == "DOWN":
            conf += 10 if macd_hist < 0 else -8
            if rsi <= 20:
                conf -= 12
                reasons.append("RSI extended oversold — bounce risk elevated")
            elif rsi > 55:
                conf -= 8
            if vol_ratio >= 1.1:
                conf += 6
        if momentum_change == "DECREASING":
            conf -= 8
        elif momentum_change == "INCREASING":
            conf += 6
        confidence_continue_pct = round(max(15.0, min(92.0, conf)), 1)

    # Fresh support/resistance break on a trending (non-consolidating) bar — flags when
    # price has just closed beyond its prior N-bar range, and scores how strongly that
    # break is backed by trend strength, volume, and momentum. Consolidating/flat bars
    # already get their own range-resolution odds above, so this only fires outside that case.
    breakout_event = "RANGE" if no_clear_direction else "NONE"
    if not no_clear_direction:
        prior_res = float(row.get("prior_res", np.nan))
        prior_sup = float(row.get("prior_sup", np.nan))
        breaking_resistance = not pd.isna(prior_res) and price > prior_res
        breaking_support = not pd.isna(prior_sup) and price < prior_sup

        if breaking_resistance and not breaking_support:
            breakout_event = "RESISTANCE_BREAK"
            up = 50.0
            up += min(22.0, max(0.0, adx - _ADX_MEDIUM) * 1.1)
            up += min(15.0, max(0.0, vol_ratio - 1.0) * 15)
            up += 8 if macd_hist > 0 else -8
            up += 6 if roc > 0 else -6
            up = max(15.0, min(95.0, up))
            breakout_up_pct = round(up, 1)
            breakout_down_pct = round(100.0 - up, 1)
            strong = vol_ratio >= _BREAKOUT_VOL_CONFIRM and adx >= _ADX_MEDIUM
            reasons.append(
                f"{'Strong' if strong else 'Weak'} break above {_SR_LOOKBACK}-bar resistance "
                f"{prior_res:.4g} · {vol_ratio:.2f}x volume"
            )
        elif breaking_support and not breaking_resistance:
            breakout_event = "SUPPORT_BREAK"
            down = 50.0
            down += min(22.0, max(0.0, adx - _ADX_MEDIUM) * 1.1)
            down += min(15.0, max(0.0, vol_ratio - 1.0) * 15)
            down += 8 if macd_hist < 0 else -8
            down += 6 if roc < 0 else -6
            down = max(15.0, min(95.0, down))
            breakout_down_pct = round(down, 1)
            breakout_up_pct = round(100.0 - down, 1)
            strong = vol_ratio >= _BREAKOUT_VOL_CONFIRM and adx >= _ADX_MEDIUM
            reasons.append(
                f"{'Strong' if strong else 'Weak'} break below {_SR_LOOKBACK}-bar support "
                f"{prior_sup:.4g} · {vol_ratio:.2f}x volume"
            )

    return {
        "timeframe": timeframe,
        "bars": len(work),
        "price": price,
        "trend_direction": trend,
        "strength": strength,
        "momentum_change": momentum_change,
        "adx": round(adx, 1) if not pd.isna(adx) else None,
        "adx_delta": round(adx_delta, 1),
        "rsi": round(rsi, 1) if not pd.isna(rsi) else None,
        "rsi_zone": _rsi_zone(rsi),
        "macd_hist": round(macd_hist, 4),
        "roc_pct": round(roc, 2),
        "volume_ratio": round(vol_ratio, 2),
        "is_consolidating": consolidating,
        "breakout_event": breakout_event,
        "breakout_up_pct": breakout_up_pct,
        "breakout_down_pct": breakout_down_pct,
        "confidence_continue_pct": confidence_continue_pct,
        "reasons": reasons,
    }


def _fetch_tf_data(ticker: str, market: str, timeframe: str, cfg: MomentumConfig, *, groww_token: str, exchange: str) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=cfg.lookback_bars)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )
    return df


def _aggregate(per_tf: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [tf for tf in per_tf if tf is not None]
    if not valid:
        return {
            "overall_direction": "NO_DATA",
            "overall_strength": "—",
            "overall_momentum_change": "—",
            "confidence_continue_pct": None,
            "breakout_up_pct": None,
            "breakout_down_pct": None,
            "alignment": "No timeframes returned enough data.",
            "reasons": [],
        }

    dir_weight = {"UP": 0.0, "DOWN": 0.0, "CONSOLIDATING": 0.0, "FLAT": 0.0}
    total_weight = 0.0
    adx_weighted = 0.0
    conf_weighted, conf_weight_sum = 0.0, 0.0
    bo_up_weighted, bo_weight_sum = 0.0, 0.0
    change_votes = {"INCREASING": 0.0, "DECREASING": 0.0, "STABLE": 0.0}

    for tf in valid:
        w = _TF_WEIGHT.get(tf["timeframe"], 1.0)
        total_weight += w
        dir_weight[tf["trend_direction"]] = dir_weight.get(tf["trend_direction"], 0.0) + w
        if tf["adx"] is not None:
            adx_weighted += tf["adx"] * w
        change_votes[tf["momentum_change"]] = change_votes.get(tf["momentum_change"], 0.0) + w
        if tf["confidence_continue_pct"] is not None:
            conf_weighted += tf["confidence_continue_pct"] * w
            conf_weight_sum += w
        if tf["breakout_up_pct"] is not None:
            bo_up_weighted += tf["breakout_up_pct"] * w
            bo_weight_sum += w

    dominant_dir = max(dir_weight, key=dir_weight.get)
    dominant_share = dir_weight[dominant_dir] / total_weight if total_weight else 0.0
    n_agree = sum(1 for tf in valid if tf["trend_direction"] == dominant_dir)

    if dominant_dir == "CONSOLIDATING" or (dominant_dir == "FLAT" and dominant_share >= 0.5):
        overall_direction = "CONSOLIDATING"
    elif dominant_share < 0.55 and len(valid) > 1:
        overall_direction = "MIXED"
    else:
        overall_direction = dominant_dir

    overall_adx = adx_weighted / total_weight if total_weight else 0.0
    overall_strength = _strength_label(overall_adx)
    overall_change = max(change_votes, key=change_votes.get)

    confidence = round(conf_weighted / conf_weight_sum, 1) if conf_weight_sum else None
    breakout_up = round(bo_up_weighted / bo_weight_sum, 1) if bo_weight_sum else None
    breakout_down = round(100.0 - breakout_up, 1) if breakout_up is not None else None

    if overall_direction == "MIXED":
        confidence = round(min(confidence or 50.0, 45.0), 1) if confidence else 40.0

    alignment = f"{n_agree}/{len(valid)} timeframe(s) aligned {dominant_dir}" if dominant_dir not in ("CONSOLIDATING",) else \
        f"{n_agree}/{len(valid)} timeframe(s) consolidating"

    reasons = [
        f"Direction weight: " + ", ".join(f"{k} {v:.1f}" for k, v in dir_weight.items() if v > 0),
        f"Weighted ADX {overall_adx:.1f} → {overall_strength.lower()} trend strength",
        f"Momentum change votes: " + ", ".join(f"{k} {v:.1f}" for k, v in change_votes.items() if v > 0),
    ]

    return {
        "overall_direction": overall_direction,
        "overall_strength": overall_strength,
        "overall_momentum_change": overall_change,
        "confidence_continue_pct": confidence,
        "breakout_up_pct": breakout_up,
        "breakout_down_pct": breakout_down,
        "alignment": alignment,
        "reasons": reasons,
    }


_ACTIONABLE_CONF_STRONG = 60.0
_ACTIONABLE_CONF_MEDIUM = 62.0
_WATCH_BREAKOUT_LEAN = 65.0


def classify_actionability(agg: dict[str, Any]) -> dict[str, Any]:
    """Experienced-trader-style bucketing: only a clean, strong-enough, non-fading
    directional read is ACTIONABLE; a fading/weak/borderline read or a consolidation
    leaning toward a breakout is WATCH; anything mixed/flat/no-data is NO_TRADE.
    Chasing weak or already-decelerating momentum is exactly what experienced
    traders avoid, so strength + momentum-change direction both gate the call,
    not confidence alone."""
    direction = agg.get("overall_direction")
    strength = agg.get("overall_strength")
    change = agg.get("overall_momentum_change")
    conf = agg.get("confidence_continue_pct") or 0.0
    bo_up = agg.get("breakout_up_pct")
    bo_down = agg.get("breakout_down_pct")

    if direction in ("UP", "DOWN"):
        trade_dir = "LONG" if direction == "UP" else "SHORT"
        fading = change == "DECREASING"
        if strength == "STRONG" and not fading and conf >= _ACTIONABLE_CONF_STRONG:
            return {"bucket": "ACTIONABLE", "direction": trade_dir,
                    "reason": f"Strong {direction} trend, momentum {change.lower()}, {conf:.0f}% confidence to continue."}
        if strength == "MEDIUM" and change == "INCREASING" and conf >= _ACTIONABLE_CONF_MEDIUM:
            return {"bucket": "ACTIONABLE", "direction": trade_dir,
                    "reason": f"Medium {direction} trend but building (ADX rising), {conf:.0f}% confidence to continue."}
        if fading:
            return {"bucket": "WATCH", "direction": trade_dir,
                    "reason": f"{direction} trend but momentum is fading (ADX falling) — wait for re-acceleration before entering."}
        if strength == "WEAK":
            return {"bucket": "WATCH", "direction": trade_dir,
                    "reason": f"{direction} direction but trend strength is weak (ADX) — not enough conviction yet."}
        return {"bucket": "WATCH", "direction": trade_dir,
                "reason": f"{direction} trend present but confidence ({conf:.0f}%) is below the actionable bar."}

    if direction == "CONSOLIDATING":
        if bo_up is not None and (bo_up >= _WATCH_BREAKOUT_LEAN or bo_down >= _WATCH_BREAKOUT_LEAN):
            lean_dir = "LONG" if bo_up >= bo_down else "SHORT"
            lean_pct = max(bo_up, bo_down)
            return {"bucket": "WATCH", "direction": lean_dir,
                    "reason": f"Consolidating with a {lean_pct:.0f}% breakout lean — watch for the actual break, not yet triggered."}
        return {"bucket": "NO_TRADE", "direction": None,
                "reason": "Consolidating with no clear breakout lean either way."}

    return {"bucket": "NO_TRADE", "direction": None,
            "reason": "Timeframes disagree (MIXED) or insufficient data — no tradeable edge right now."}


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: MomentumConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MomentumConfig()
    per_tf: list[dict[str, Any]] = []
    for tf in cfg.timeframes:
        try:
            df = _fetch_tf_data(ticker, market, tf, cfg, groww_token=groww_token, exchange=exchange)
            result = analyze_timeframe(df, tf, cfg)
            if result:
                per_tf.append(result)
        except Exception as exc:
            logger.debug("momentum analyze failed for %s %s: %s", ticker, tf, exc)

    if not per_tf:
        return {"ticker": ticker, "market": market, "error": f"Insufficient data across {', '.join(cfg.timeframes)}."}

    agg = _aggregate(per_tf)
    actionability = classify_actionability(agg)
    return {
        "ticker": ticker,
        "market": market,
        "timeframes": cfg.timeframes,
        "per_tf": per_tf,
        "actionability": actionability,
        **agg,
    }


def analyze_tickers(
    tickers: list[str],
    market: str,
    *,
    cfg: MomentumConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    cfg = cfg or MomentumConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("momentum scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})
    return results


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: MomentumConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    """Alias for analyze_tickers, matching the scan_universe() naming convention
    used by the other market_pulse scanner engines."""
    return analyze_tickers(tickers, market, cfg=cfg, groww_token=groww_token, exchange=exchange)


# ---------------------------------------------------------------------------
# AI View
# ---------------------------------------------------------------------------

MOMENTUM_AI_SYSTEM = """You are a technical analyst reviewing a multi-timeframe momentum scan for one ticker — ADX trend strength, EMA-stack direction, RSI, MACD histogram, ROC, volume ratio, and Bollinger Band consolidation/breakout odds, computed independently per timeframe and then aggregated.

Given the per-timeframe breakdown and the aggregate verdict:

1. **Momentum read** — is momentum strong/medium/weak, and is it increasing or decreasing? Reconcile any disagreement between timeframes (e.g. "short-term momentum fading inside a still-strong daily uptrend").
2. **Direction & continuation** — state the dominant direction and whether the data supports the trend continuing, citing the specific confidence % and what's driving it (ADX level, RSI room-to-run, volume confirmation).
3. **Consolidation / breakout** — if timeframes show consolidation, state the breakout-up vs breakout-down odds and what would confirm a resolution either way.
4. **Trade stance** — TAKE LONG / TAKE SHORT / WAIT (consolidating) / AVOID (mixed/conflicting), with a one-line risk note.

Cite the actual numbers from the data (ADX, RSI, MACD histogram, ROC, volume ratio, confidence %) — never invent values not present in the feed.
"""


def build_momentum_ai_prompt(result: dict) -> str:
    lines = [
        "=== MULTI-TIMEFRAME MOMENTUM SCAN ===",
        f"Ticker: {result.get('ticker')}",
        f"Market: {result.get('market')}",
        f"Timeframes: {', '.join(result.get('timeframes') or [])}",
        "",
        "── AGGREGATE ──",
        f"Direction: {result.get('overall_direction')} · Strength: {result.get('overall_strength')} · "
        f"Momentum change: {result.get('overall_momentum_change')}",
        f"Alignment: {result.get('alignment')}",
        f"Confidence trend continues: {result.get('confidence_continue_pct')}%",
    ]
    if result.get("breakout_up_pct") is not None:
        lines.append(f"Breakout odds: UP {result.get('breakout_up_pct')}% / DOWN {result.get('breakout_down_pct')}%")
    lines.append("")
    lines.append("── PER-TIMEFRAME ──")
    for tf in result.get("per_tf") or []:
        lines.append(
            f"[{tf['timeframe']}] {tf['trend_direction']} · {tf['strength']} · momentum {tf['momentum_change']} · "
            f"S/R event {tf.get('breakout_event', 'NONE')} · "
            f"price {tf['price']:.4g} · ADX {tf['adx']} (Δ{tf['adx_delta']:+}) · RSI {tf['rsi']} ({tf['rsi_zone']}) · "
            f"MACD hist {tf['macd_hist']:+} · ROC {tf['roc_pct']:+}% · Vol {tf['volume_ratio']}x"
            + (f" · confidence continues {tf['confidence_continue_pct']}%" if tf.get("confidence_continue_pct") is not None else "")
            + (f" · breakout UP {tf['breakout_up_pct']}% / DOWN {tf['breakout_down_pct']}%" if tf.get("breakout_up_pct") is not None else "")
        )
    return "\n".join(lines)
